"""
Conversion of json files stored inside zip archives to a zstd-compressed
jsonl fixture file suitable for import

How to run:

    python scripts/convert_to_fixtures.py ../invenio-fzu-data app_data/fram.jsonl.zst

Then:
    invenio rdm-records add-to-fixtures fram

"""

import json
import zipfile
from compression import zstd
from pathlib import Path

import click

S3_PREFIX="https://s3.nrp1.du.cesnet.cz/89fc50d6_5164_4bf3_b600_1c90d6f8436e:avcrfzu-repo-physics-prod-direct-001"

@click.command()
@click.argument("in_dir")
@click.argument("out_file")
def convert(in_dir, out_file):
    """Convert json records from zips under IN_DIR to a zstd jsonl fixture."""
    in_dir = Path(in_dir)
    out_file = Path(out_file)

    if not in_dir.exists():
        raise click.Abort("The input directory does not exist")

    with zstd.open(out_file, "wt", encoding="utf-8") as out:
        for record_data in _convert_records(in_dir):
            out.write(json.dumps(record_data, ensure_ascii=False))
            out.write("\n")


def _read_records(in_dir):
    """Yield json records from zip archives under in_dir, one member at a time."""
    for zip_path in sorted(in_dir.rglob("*.zip")):
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                if info.is_dir() or not info.filename.endswith(".json"):
                    continue
                if "bad" in info.filename.split("/")[:-1]:
                    continue
                with zf.open(info) as f:
                    yield json.load(f)


def _convert_records(in_dir):
    """Yield converted records one by one from the input directory."""
    for record_data in _read_records(in_dir):
        id_ = None
        for rec_file in record_data.get("files", {}).get("entries", []):
            path = rec_file.pop("path")
            rec_file["transfer"] = {
                "type": "R",
                "url": f"{S3_PREFIX}/{path}"
            }
            # file names are not unique across instruments (cta-s0 vs cta-s1),
            # so prefix them with the instrument, e.g. cta-s0-20220611223351-881
            instrument = path.split("/")[1]
            id_ = f"{instrument}-{rec_file['key'].removesuffix('-RA.fits')}"
        identifiers = record_data.get("metadata", {}).get("identifiers", [])
        if identifiers:
            for idx, identifier in reversed(list(enumerate(record_data.get("metadata", {}).get("identifiers", [])))):
                if not identifier.get("identifier"):
                    del identifiers[idx]
            if not identifiers:
                del record_data.get("metadata", {})["identifiers"]
        if id_:
            record_data["id"] = id_

        yield record_data

if __name__ == "__main__":
    convert()
