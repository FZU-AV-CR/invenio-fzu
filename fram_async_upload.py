"""
Async upload pipeline for a single FRAM FITS file.

Mirrors the shape of the DELPHI template (async_upload.py): one async function
does checksum -> extract -> validate -> build metadata -> create draft ->
upload file -> publish, and writes rows to a stats CSV (upload_stats.csv) as
it goes.

Differences from the DELPHI case:
  - FRAM uploads exactly one FITS file per record (no zip / multi-file branch).
  - There is no recid known up front; each FITS file becomes its own record,
    and the "key" used for resume/stats purposes is the path of the FITS file
    relative to the root input directory (so site subfolders don't collide).
  - Every FITS file (light, masterdark, masterflat, bias, dcurrent, ...) is
    uploaded as its own independent record. Calibration frames are NOT linked
    to light frames at upload time -- that association is done at read time
    by the portal, via metadata lookup (site/ccd/camera_serial/binning/
    usable_width/usable_height + type-specific fields + nearest timestamp).
    This means every record's metadata must carry those fields consistently,
    regardless of observation type.
  - Overscan cropping and bias subtraction (via calibrate.py) are applied
    when computing metadata (usable dimensions, mean, median). Linearization
    is intentionally NOT applied -- mean/median reflect crop+bias only. The
    archived FITS file itself is always the untouched original either way.
  - Three environment-specific client factories are provided: create_local_
    client(), create_test1_client(), create_production_client(). Tokens are
    resolved as: explicit arg -> INVENIO_TOKEN env var -> interactive
    getpass() prompt. create_production_client() additionally requires an
    explicit interactive confirmation (or confirm=False from an
    already-vetted caller, e.g. a --yes CLI flag) before connecting, since
    this script can run unattended for a long time against a large,
    hard-to-undo dataset.

KNOWN OPEN ITEM: camera_serial is read from the CCD_SER header keyword.
calibrate.py's own find_calibration_config() internally keys off a DIFFERENT
header field, header['product_id'] (seen as a HIERARCH keyword in sample
headers so far), to look up airtemp-based bias fallbacks and linearization
curves. That lookup is independent of what we put in the output metadata,
but if header['product_id'] is not resolvable on the header object
crop_overscans() receives -- e.g. because it's only present in the primary
HDU while extract_fits_metadata reads the header via
fits.getheader(path, -1), the *last* HDU -- find_calibration_config() will
raise a KeyError for any file whose overscan can't be measured directly from
the pixel data. Worth checking against a real file before a production run.
"""

from __future__ import annotations

import asyncio
import csv
import datetime
import getpass
import hashlib
import json
import logging
import os
import time
import warnings
from logging.handlers import RotatingFileHandler
from pathlib import Path

import healpy as hp
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning


from yarl import URL

try:
    from nrp_cmd.async_client import get_async_client
    from nrp_cmd.config import Config, RepositoryConfig
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"Missing NRP async library: {exc}")

from calibrate import crop_overscans

warnings.simplefilter("ignore", FITSFixedWarning)

logger = logging.getLogger(__name__)

# ============================================================
# ENVIRONMENT / CLIENT CONFIGURATION
# ============================================================

TOKEN_ENV_VAR = "INVENIO_TOKEN"

# Confirmed for local only so far; verify before using with test1/production.
DEFAULT_SCHEMA_URL = "local://fram-v1.0.0.json"

ENVIRONMENTS = {
    "local": {
        "alias": "physica-local",
        "url": "https://127.0.0.1:5000/",
        "verify_tls": False,
    },
    "test1": {
        "alias": "physica-test1",
        "url": "https://test1.physics.du.cesnet.cz/",
        "verify_tls": True,
    },
    "production": {
        "alias": "physica-production",
        "url": "https://invenio.fzu.cz/",
        "verify_tls": True,
    },
}

# Fixed metadata, shared by every record
CREATORS = [
    {
        "person_or_org": {
            "name": "FZU Institute of Physics of the Czech Academy of Sciences",
            "type": "organizational",
        },
    }
]

CONTRIBUTORS = [
    {
        "person_or_org": {
            "name": "FRAM collaboration",
            "type": "organizational",
        },
        "role": {"id": "ResearchGroup"},
    }
]

SUBJECTS = [
    "Fram",
    "Telescope",
    "Astrophysics",
    "Auger",
    "CTA",
    "Photometric robotic atmosperic monitor",
    "Physics",
    "Paranal",
    "Roque de los Muchachos",
]

SITE_CANDIDATES = ["auger2", "auger", "cta-n", "cta-s0", "cta-s1"]

# Master-calibration / non-science IMAGETYP values; these are uploaded as
# their own records too. Kept here only for reference -- no filtering is
# applied based on this set.
CALIBRATION_IMAGETYPES = {"masterdark", "masterflat", "bias", "dcurrent"}

HEALPIX_NSIDE = 64  # ~0.9° cell resolution; 49,152 total pixels


# Fields every record must have a usable value for, regardless of observation
# type, since these drive read-time calibration association. NOTE: "target"
# is intentionally NOT required -- calibration frames (masterdark/masterflat/
# bias/dcurrent) legitimately have no astronomical target. This is a minimal
# defensive check, not a substitute for the separate data-cleaning/correction
# tool planned as its own project.
REQUIRED_METADATA_FIELDS = ("site", "ccd", "camera_serial", "binning")

# Canonical stats row schema -- every call to _write_stats supplies exactly
# this set of keys so the CSV header stays consistent across "started" and
# terminal rows.
STATS_FIELDS = (
    "key",
    "recid",
    "status",
    "error",
    "start_ts",
    "duration_s",
    "file_count",
    "zip_used",
    "bytes_uploaded",
    "checksum_md5",
)


# ============================================================
# CLIENT HELPERS
# ============================================================


def _resolve_token(token: str | None = None) -> str:
    """Resolve an API token: explicit arg -> INVENIO_TOKEN env var ->
    interactive prompt. Never hardcode tokens in source."""
    if token:
        return token
    env_token = os.environ.get(TOKEN_ENV_VAR)
    if env_token:
        return env_token
    prompted = getpass.getpass(f"Enter API token ({TOKEN_ENV_VAR} is not set): ").strip()
    if not prompted:
        raise RuntimeError(f"No API token supplied, {TOKEN_ENV_VAR} is not set, and none was entered.")
    return prompted


async def _create_client(env_name: str, token: str | None = None):
    env = ENVIRONMENTS[env_name]
    resolved_token = _resolve_token(token)
    config = Config()
    config.add_repository(
        RepositoryConfig(
            alias=env["alias"],
            url=URL(env["url"]),
            token=resolved_token,
            verify_tls=env["verify_tls"],
        )
    )
    return await get_async_client(env["alias"], config=config)


async def create_local_client(token: str | None = None):
    """Connect to the local dev repository (physica-local @ 127.0.0.1:5000)."""
    return await _create_client("local", token=token)


async def create_test1_client(token: str | None = None):
    """Connect to the test1 repository (physica-test1 @ test1.physics.du.cesnet.cz)."""
    return await _create_client("test1", token=token)


async def create_production_client(token: str | None = None, confirm: bool = True):
    """Connect to the PRODUCTION repository (physica-production @ invenio.fzu.cz).

    By default this requires an interactive confirmation before connecting,
    since this script can run unattended for a long time against a large,
    hard-to-undo dataset. Pass confirm=False only from a caller that has
    already obtained confirmation some other way (e.g. a --yes CLI flag).
    """
    if confirm:
        env = ENVIRONMENTS["production"]
        response = input(
            f"You are about to connect to the PRODUCTION repository ({env['url']}). "
            "Type 'PRODUCTION' (all caps) to continue, anything else to abort: "
        ).strip()
        if response != "PRODUCTION":
            raise RuntimeError("Production run not confirmed by operator. Aborting.")
    return await _create_client("production", token=token)


async def create_client_for_environment(
    env_name: str, token: str | None = None, confirm_production: bool = True
):
    """Dispatch to the right create_*_client() based on an environment name
    string ('local' / 'test1' / 'production'), as used by the CLI's
    --environment flag."""
    if env_name == "local":
        return await create_local_client(token=token)
    if env_name == "test1":
        return await create_test1_client(token=token)
    if env_name == "production":
        return await create_production_client(token=token, confirm=confirm_production)
    raise ValueError(f"Unknown environment: {env_name!r} (expected one of {sorted(ENVIRONMENTS)})")


# ============================================================
# CHECKSUM
# ============================================================


def compute_md5(path: Path, chunk_size: int = 1024 * 1024) -> str:
    md5 = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            md5.update(chunk)
    return md5.hexdigest()


# ============================================================
# FITS HEADER EXTRACTION
# (adapted from upload_copy.py's process_file; to be improved later)
# ============================================================


def _spherical_distance(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Calculate great circle distance between two points on a sphere (in degrees)."""
    ra1_rad = np.radians(ra1)
    dec1_rad = np.radians(dec1)
    ra2_rad = np.radians(ra2)
    dec2_rad = np.radians(dec2)

    # Haversine formula
    dlat = dec2_rad - dec1_rad
    dlon = ra2_rad - ra1_rad
    a = np.sin(dlat / 2) ** 2 + np.cos(dec1_rad) * np.cos(dec2_rad) * np.sin(dlon / 2) ** 2
    c = 2 * np.arcsin(np.sqrt(a))
    return np.degrees(c)


def _ra_to_lon(ra: float) -> float:
    """Remap RA (0–360°) to OpenSearch longitude (−180 to +180°)."""
    return ra - 360.0 if ra > 180.0 else ra


def _compute_footprint(
    wcs, usable_width: int, usable_height: int
) -> dict | None:
    """
    Return a GeoJSON Polygon of the image corners for OpenSearch geo_shape
    indexing, with RA remapped to −180..+180°.

    Populates the existing `footprint` metadata field (previously always None).
    The original PostgreSQL schema had this as a POLYGON type for geo search;
    here we use GeoJSON for OpenSearch geo_shape.

    Images near RA=0/360° straddle the antimeridian in the remapped system.
    Setting GeoJSON orientation='right' tells OpenSearch to take the short
    arc across the antimeridian rather than wrapping around the globe.

    Returns None on any WCS computation error.
    """
    try:
        # Four corners + closing point (0-indexed pixel coordinates)
        px = [0, usable_width, usable_width, 0,             0]
        py = [0, 0,            usable_height, usable_height, 0]
        ras, decs = wcs.all_pix2world(px, py, 0)

        coords = [
            [_ra_to_lon(float(ra)), float(dec)]
            for ra, dec in zip(ras, decs)
        ]

        # Detect antimeridian crossing: longitude span > 180° means the image
        # straddles the RA=0/360 boundary after remapping.
        lons = [c[0] for c in coords]
        crosses_antimeridian = (max(lons) - min(lons)) > 180.0

        polygon: dict = {
            "type": "polygon",
            "coordinates": [coords],
        }
        if crosses_antimeridian:
            polygon["orientation"] = "right"

        return polygon
    except Exception:
        return None


def _parse_iso_time(string: str) -> datetime.datetime:
    return datetime.datetime.strptime(string, "%Y-%m-%dT%H:%M:%S.%f")



def _get_night(time_: datetime.datetime, lon: float | None = None, site: str | None = None) -> str:
    if lon is None:
        if site == "auger":
            lon = -69.4497
        elif site == "cta-n":
            lon = -17.89
        elif site in ("cta-s0", "cta-s1"):
            lon = -70.32482
        else:
            lon = 0
    shifted = time_ + datetime.timedelta(seconds=lon * 86400 / 360 - 86400 / 2)
    return shifted.strftime("%Y%m%d")


def extract_fits_metadata(
    fits_path: Path,
    filename: str | None = None,
    site: str | None = None,
    night: str | None = None,
) -> dict:
    """
    Extract metadata from a single FITS file's header, returning a flat dict.
    Adapted from upload_copy.py's process_file(); kept as a sync function
    since astropy I/O is not async-native (run via asyncio.to_thread).

    No filtering is applied here: every IMAGETYP (object, masterdark,
    masterflat, bias, dcurrent, ...) is extracted and returned, since each
    becomes its own record. See validate_extracted_metadata() for the
    minimal downstream sanity check.

    Applies overscan cropping + bias subtraction (calibrate.crop_overscans)
    but NOT linearization -- usable_width/usable_height/mean/median reflect
    crop+bias only. The uploaded FITS file itself is always the untouched
    original; this only affects computed metadata.
    """
    if filename is None:
        filename = str(fits_path)
    path_str = str(fits_path)

    if site is None:
        for candidate in SITE_CANDIDATES:
            if candidate in path_str:
                site = candidate
                break

    header = fits.getheader(path_str, -1)

    if night is None:
        time_ = _parse_iso_time(header["DATE-OBS"])
        if header.get("LONGITUD") is not None:
            night = _get_night(time_, lon=header["LONGITUD"])
        else:
            night = _get_night(time_, site=site)

    image = fits.getdata(path_str, -1)

    width, height = header["NAXIS1"], header["NAXIS2"]
    image, header = crop_overscans(image, header)
    usable_width, usable_height = image.shape[1], image.shape[0]

    # Calculate radius, center, and spherical index fields
    obs_type = header.get("IMAGETYP", "unknown")
    is_science     = obs_type == "object"
    is_calibration = obs_type in CALIBRATION_IMAGETYPES

    wcs = None
    if is_science and header.get("CTYPE1"):
        wcs = WCS(header)
        ra, dec = wcs.all_pix2world(
            [0, usable_width, 0.5 * usable_width],
            [0, usable_height, 0.5 * usable_height],
            0,
        )
        radius = 0.5 * _spherical_distance(ra[0], dec[0], ra[1], dec[1])
        ra0, dec0 = float(ra[2]), float(dec[2])
    else:
        ra0, dec0, radius = 0.0, 0.0, 0.0

    # Spherical index fields — always None for calibration frames or when
    # no valid sky position is available (ra0==0 acts as the sentinel).
    if is_calibration or ra0 == 0.0:
        center_geo  = None
        footprint   = None   # was already None; kept None for non-science frames
        healpix_idx = None
    else:
        center_geo = {"lat": dec0, "lon": _ra_to_lon(ra0)}
        footprint  = (                      # now populated (was always None before)
            _compute_footprint(wcs, usable_width, usable_height)
            if wcs is not None else None
        )
        theta = np.radians(90.0 - dec0)    # HEALPix co-latitude
        phi   = np.radians(ra0)
        healpix_idx = int(hp.ang2pix(HEALPIX_NSIDE, theta, phi))


    time_ = _parse_iso_time(header["DATE-OBS"])

    target = header.get("TARGET")
    obj_name = header.get("OBJECT")
    target_display = f"{target} / {obj_name}" if target and obj_name else (target or obj_name)

    return {
        "filename": filename,
        "night": night,
        "observation_time": time_.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "creation_date": time_.date().isoformat(),
        "target": target_display,
        "type": obs_type,
        "filter": header.get("FILTER", "unknown"),
        "ccd": header.get("CCD_NAME"),
        # Sourced from CCD_SER, not header['product_id'] -- see the KNOWN
        # OPEN ITEM note at the top of this file.
        "camera_serial": header.get("CCD_SER"),
        "site": site,
        "ra0": ra0,
        "dec0": dec0,
        "radius": radius,
        "exposure": header.get("EXPOSURE"),
        "width": int(width),
        "height": int(height),
        "usable_width": int(usable_width),
        "usable_height": int(usable_height),
        "binning": header.get("BINNING"),
        "mean": float(np.mean(image)),
        "median": float(np.median(image)),
        "altitude": header.get("TEL_ALT"),
        "azimuth": header.get("TEL_AZ"),
        "footprint":   footprint,      # was hardcoded None; now a GeoJSON polygon (or None for calibration)
        # ── NEW ──────────────────────────────────────────────────────────
        "center_geo":  center_geo,
        "healpix_idx": healpix_idx,
    }



def validate_extracted_metadata(extracted: dict) -> list[str]:
    """Return a list of problems with extracted FITS metadata. An empty list
    means the record is fine to upload.

    This is a minimal defensive check -- it exists to stop a handful of
    malformed headers from crashing the batch or silently uploading records
    with null fields the read-time association logic depends on (site/ccd/
    camera_serial/binning/usable dimensions). It is NOT a substitute for the
    more thorough corruption-detection/correction tool planned as a separate
    project.
    """
    problems = []
    for field in REQUIRED_METADATA_FIELDS:
        if not extracted.get(field):
            problems.append(f"missing required field: {field}")
    if not extracted.get("usable_width") or not extracted.get("usable_height"):
        problems.append("usable_width/usable_height is zero or missing")
    return problems


# ============================================================
# METADATA -> INVENIORDM JSON
# (adapted from Fram_upload2_create_metadata.py)
# ============================================================


def build_invenio_metadata(extracted: dict) -> dict:
    title = "FRAM_" + Path(extracted["filename"]).stem
    publication_date = datetime.date.today().isoformat()

    return {
        "metadata": {
            "resource_type": {"id": "c_ddb1"},
            "creators": CREATORS,
            "contributors": CONTRIBUTORS,
            "file_types": ["fits"],
            "title": title,
            "publication_date": publication_date,
            "publisher": "FZU Institute of Physics of the Czech Academy of Sciences",
            "additional_descriptions": [
                {
                    "lang": {"id": "ENG"},
                    "type": {"id": "abstract"},
                    "description": (
                        "This dataset contains observation data in the fits format. "
                        "The observation comes from robotic telescope "
                        "(Phototometric Robotic Atmospheric Monitor - FRAM)."
                    ),
                }
            ],
            "subjects": [{"subject": s} for s in SUBJECTS],
            "rights": [{"id": "4-BY"}],
            "dates": [{"date": extracted["creation_date"], "type": {"id": "Created"}}],
            "experiment": {"id": "FRAM"},
            "target": extracted["target"],
            "type": extracted["type"],
            "observation_time": extracted["observation_time"],
            "observation_night": extracted["night"],
            "exposure": extracted["exposure"],
            "center": {"ra": extracted["ra0"], "dec": extracted["dec0"]},
            "radius": extracted["radius"],
            "site": extracted["site"],
            "ccd": extracted["ccd"],
            "camera_serial": extracted["camera_serial"],
            "filter": extracted["filter"],
            "binning": extracted["binning"],
            "image_size": {
                "width": extracted["width"],
                "height": extracted["height"],
                "usable_width": extracted["usable_width"],
                "usable_height": extracted["usable_height"],
            },
            "declination": extracted["dec0"],
            "altitude_azimuth": {
                "altitude": extracted["altitude"],
                "azimuth": extracted["azimuth"],
            },
            "filename": extracted["filename"],
            "footprint":   extracted["footprint"],   # now a GeoJSON polygon, not None
            # ── NEW ──────────────────────────────────────────────────────
            "center_geo":  extracted["center_geo"],
            "healpix_idx": extracted["healpix_idx"],
        },

        "files": {"enabled": False},
        "access": {
            "record": "public",
            "files": "restricted",
            "embargo": {"active": "false", "reason": "null"},
            "status": "restricted",
            "communities": {"ids": ["222"]},
        },
        "communities": {"ids": ["111"]},
    }


# ============================================================
# STATS WRITING
# ============================================================


def _stats_payload(key: str, **overrides) -> dict:
    payload = {field: None for field in STATS_FIELDS}
    payload.update(key=key, file_count=1, zip_used=False, bytes_uploaded=0)
    payload.update(overrides)
    return payload


async def _write_stats(stats_path: Path | None, fmt: str, payload: dict) -> None:
    if not stats_path:
        return

    def _sync_write():
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "csv":
            write_header = not stats_path.exists()
            with stats_path.open("a", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=STATS_FIELDS, extrasaction="ignore")
                if write_header:
                    writer.writeheader()
                writer.writerow(payload)
        else:  # jsonl
            with stats_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    await asyncio.to_thread(_sync_write)


# ============================================================
# PER-FILE PIPELINE
# ============================================================


async def upload_fits_async(
    client,
    fits_path: Path,
    relative_key: str,
    stats_path: Path | None = Path("../stats/upload_stats.csv"),
    stats_format: str = "csv",
    dry_run: bool = False,
    validate: bool = True,
    schema_url: str = DEFAULT_SCHEMA_URL,
) -> object | None:
    """
    Full pipeline for a single FITS file: checksum -> extract -> validate ->
    build metadata -> [create -> upload -> publish] -> stats.

    relative_key: path of fits_path relative to the root input directory,
    used as the resume/dedup key (so site subfolders don't collide) and
    written into the record's own "filename" metadata field.

    A "started" stats row is written immediately before records.create() is
    called (real, non-dry-run uploads only) -- if the process dies between
    that point and the terminal row written in `finally` below, the key will
    show up as "interrupted" on the next run (see fram_bulk_async.py's
    _scan_stats()), which may indicate an orphaned draft in the repository
    worth checking manually. This is not a full transactional guarantee --
    just enough to make crashes visible instead of silent.
    """
    start = time.perf_counter()
    start_ts = time.time()
    status = "ok"
    error = None
    bytes_uploaded = 0
    checksum_md5 = None
    published = None

    try:
        checksum_md5 = await asyncio.to_thread(compute_md5, fits_path)
        extracted = await asyncio.to_thread(extract_fits_metadata, fits_path, relative_key)

        if validate:
            problems = validate_extracted_metadata(extracted)
            if problems:
                status = "skipped_invalid"
                error = "; ".join(problems)
                logger.warning("[%s] Skipping, validation failed: %s", relative_key, error)
                return None

        metadata = build_invenio_metadata(extracted)

        if dry_run:
            status = "dryrun"
            bytes_uploaded = fits_path.stat().st_size
            logger.info("[%s] Dry run OK (would create/upload/publish)", relative_key)
            return None

        await _write_stats(
            stats_path,
            stats_format,
            _stats_payload(relative_key, status="started", start_ts=start_ts, checksum_md5=checksum_md5),
        )

        record = await client.records.create(
            {
                "metadata": metadata["metadata"],
                "access": metadata["access"],
                "files": metadata["files"],
                #"community": metadata["communities"],
                "community": {"pids": 111,},
                "$schema": schema_url,
            }
        )
        logger.info("[%s] Created draft: %s", relative_key, record.id)

        file_ = await client.files.upload(
            record,
            key=fits_path.name,
            metadata={"description": "Measurement data"},
            source=str(fits_path),
        )
        logger.info("[%s] Uploaded: %s", relative_key, file_.key)
        bytes_uploaded = fits_path.stat().st_size

        published = await client.records.publish(record)
        logger.info("[%s] Published: %s", relative_key, published.id)

    except Exception as exc:
        status = "failed"
        error = str(exc)
        raise
    finally:
        await _write_stats(
            stats_path,
            stats_format,
            _stats_payload(
                relative_key,
                recid=getattr(published, "id", None),
                status=status,
                error=error,
                start_ts=start_ts,
                duration_s=round(time.perf_counter() - start, 3),
                bytes_uploaded=bytes_uploaded,
                checksum_md5=checksum_md5,
            ),
        )

    return published


def setup_logging(level=logging.INFO, log_file: Path | None = None):
    handlers = [logging.StreamHandler()]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(log_file, maxBytes=20 * 1024 * 1024, backupCount=5, encoding="utf-8")
        )
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )
    for noisy in ("nrp_cmd", "urllib3", "aiohttp", "botocore", "boto3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def main_async() -> None:
    """Single-file smoke test against the local dev repository."""
    setup_logging()
    client = await create_local_client()

    fits_path = Path("sample/20260408105436-044-RA.fits")
    await upload_fits_async(
        client=client,
        fits_path=fits_path,
        relative_key=fits_path.name,
        stats_path=Path("upload_stats.csv"),
        stats_format="csv",
    )


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
