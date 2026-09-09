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
import argparse

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

SUBJECTS = [
    "Test",
]

# Community slug + metadata-model name, per Cesnet's nrp_cmd usage example
# (client.records.create(metadata, model="particles")). Both are passed as
# proper keyword arguments to client.records.create() below -- NOT
# embedded in the JSON body, which is a real routing/type mismatch (the
# body has no meaning for "community"/"model" as ordinary fields; nrp_cmd
# only recognizes them as constructor kwargs).
FRAM_COMMUNITY = "fram"
FRAM_MODEL = "fram"

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



def _parse_iso_time(string: str) -> datetime.datetime:
    return datetime.datetime.strptime(string, "%Y-%m-%dT%H:%M:%S.%f")



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

    
    header = fits.getheader(path_str, -1)


    return {
        "filename": filename,
        "creation_date": datetime.date.today().isoformat(),
    }



def build_invenio_metadata(extracted: dict) -> dict:
    title = "FRAM_" + Path(extracted["filename"]).stem
    publication_date = datetime.date.today().isoformat()

    return {
        "metadata": {
            "related_resources": [{"title": "FRAM_2022_cta-n", "identifiers": [{"identifier": "https://test1.physics.du.cesnet.cz/fram/records/f4dex-2h991", "scheme": "url"}], "relation_type": {"id": "IsPartOf"}},
                                  {"title": "FRAM", "identifiers": [{"identifier": "https://test1.physics.du.cesnet.cz/fram/records/qv8r6-g0h40", "scheme": "url"}], "relation_type": {"id": "IsPartOf"}}],
            "resource_type": {"id": "c_ddb1"},
            "creators": CREATORS,
            "file_types": ["fits"],
            "title": title,
            "publication_date": publication_date,
            "publisher": "FZU Institute of Physics of the Czech Academy of Sciences",
            "additional_descriptions": [
                {
                    "lang": {"id": "ENG"},
                    "type": {"id": "abstract"},
                    "description": (
                        "TEST"
                    ),
                }
            ],
            "subjects": [{"subject": s} for s in SUBJECTS],
            "rights": [{"id": "4-BY"}],
            "dates": [{"date": extracted["creation_date"], "type": {"id": "Created"}}],
            "experiment": {"id": "FRAM"},
        },
        "files": {"enabled": True},
        "access": {
            "record": "public",
            "files": "restricted",
            "embargo": {"active": "false", "reason": "null"},
            "status": "restricted",
        },
        # Passed as client.records.create()'s community=/model= keyword
        # arguments by upload_fits_async() below -- NOT embedded in the
        # JSON body itself. See FRAM_COMMUNITY/FRAM_MODEL above.
        "community": FRAM_COMMUNITY,
        "model": FRAM_MODEL,
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
    stats_path: Path | None = Path("upload_stats.csv"),
    stats_format: str = "csv",
    dry_run: bool = False,
    validate: bool = True,
    schema_url: str = DEFAULT_SCHEMA_URL,
    disable_schema: bool = False,
) -> object | None:

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

        metadata = build_invenio_metadata(extracted)

        if dry_run:
            status = "dryrun"
            bytes_uploaded = fits_path.stat().st_size
            logger.info("[%s] Dry run OK (would create/upload/publish)", relative_key)
            return None

        # await _write_stats(
        #     stats_path,
        #     stats_format,
        #     _stats_payload(relative_key, status="started", start_ts=start_ts, checksum_md5=checksum_md5),
        # )

        record_body = {
            "metadata": metadata["metadata"],
            "access": metadata["access"],
            "files": metadata["files"],
        }
        if not disable_schema:
            record_body["$schema"] = schema_url

        # community/model are constructor kwargs on client.records.create(),
        # not JSON body fields -- see FRAM_COMMUNITY/FRAM_MODEL above and
        # build_invenio_metadata()'s comment. Omitted entirely (rather than
        # passed as None) when unset, matching nrp_cmd's own defaults.
        create_kwargs: dict = {}
        if metadata.get("community"):
            create_kwargs["community"] = metadata["community"]
        if metadata.get("model"):
            create_kwargs["model"] = metadata["model"]

        record = await client.records.create(record_body, **create_kwargs)
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

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Minimal, self-contained single-file upload test -- exercises real "
                     "connectivity/schema/community/model handling against a chosen environment "
                     "without going through the full bulk pipeline (bulk_async.py/async_upload.py/"
                     "fram_upload.py). Every flag below is actually read by this script; none are "
                     "vestigial (a prior version of this file defined --environment and others via "
                     "argparse but never passed them to main_async(), so they had no effect at all --"
                     " fixed here)."
    )
    parser.add_argument(
        "--fits-file", default="/home/erutherford/Python WSL/Archive/v1/FRAM/sample/20260408105436-044-RA.fits",
        help="Path to the single FITS file to test-upload.",
    )
    parser.add_argument(
        "--environment", choices=sorted(ENVIRONMENTS), default="local",
        help="Which repository to upload to (local / test1 / production).",
    )
    parser.add_argument(
        "--token", default=None,
        help=f"API token; prefer the {TOKEN_ENV_VAR} environment variable over this flag "
             "to avoid leaking credentials via process listings or shell history.",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip the interactive confirmation prompt required for --environment production.",
    )
    parser.add_argument(
        "--schema-url", default=DEFAULT_SCHEMA_URL,
        help="Invenio $schema value to send. Confirmed only for local so far -- verify before using "
             "with test1/production. Ignored entirely if --disable-schema is set.",
    )
    parser.add_argument(
        "--disable-schema", action="store_true",
        help="No longer does anything -- omitting \"$schema\" is now the DEFAULT. Kept only so an "
             "existing command line that already includes this flag keeps working unchanged. Use "
             "--enable-schema to opt back into sending \"$schema\".",
    )
    parser.add_argument(
        "--enable-schema", action="store_true",
        help="Send \"$schema\" in the record body (the old default behavior). Confirmed unnecessary "
             "for FRAM/test1: a published record resolved the correct \"$schema\" server-side purely "
             "from model=, even with no \"$schema\" sent at all.",
    )
    parser.add_argument(
        "--stats-path", default="upload_stats.csv",
        help="Path to the stats CSV for this single test upload.",
    )
    parser.add_argument("--log-file", default=None, help="Optional log file path, in addition to console output.")
    parser.add_argument("--dry-run", action="store_true", help="Extract & validate metadata but do not create/upload/publish anything.")
    return parser.parse_args()


async def main_async(args: argparse.Namespace) -> None:
    """Single-file smoke test against whichever repository --environment selects."""
    client = await create_client_for_environment(
        args.environment, token=args.token, confirm_production=not args.yes,
    )

    fits_path = Path(args.fits_file)
    await upload_fits_async(
        client=client,
        fits_path=fits_path,
        relative_key=fits_path.name,
        stats_path=Path(args.stats_path) if args.stats_path else None,
        stats_format="csv",
        dry_run=args.dry_run,
        schema_url=args.schema_url,
        disable_schema=not args.enable_schema,
    )


def main() -> None:
    args = parse_args()
    setup_logging(log_file=Path(args.log_file) if args.log_file else None)
    logger.info(
        "Testing upload: environment=%s fits_file=%s schema=%s",
        args.environment, args.fits_file,
        "DISABLED (default -- pass --enable-schema to send $schema)" if not args.enable_schema else args.schema_url,
    )
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()

# cd tests
# python3 TEST_async_upload.py --environment local
# python3 TEST_async_upload.py --environment test1 --fits-file "/path/to/one.fits" --disable-schema
# python3 TEST_async_upload.py --environment test1 --fits-file "/path/to/one.fits" --dry-run