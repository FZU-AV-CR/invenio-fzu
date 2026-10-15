"""
Conversion of individual json files to a fixture file suitable for import

How to run:

    python scripts/convert_to_fixtures.py <data-directory> app_data/fram.json

Then:
    invenio rdm-records add-to-fixtures fram

"""

import json
import click
from pathlib import Path

S3_PREFIX="https://s3.nrp1.du.cesnet.cz/89fc50d6_5164_4bf3_b600_1c90d6f8436e:avcrfzu-repo-physics-prod-direct-001"

@click.command()
@click.argument("in_dir")
@click.argument("out_file")
def convert(in_dir, out_file):
    """Convert the datafiles from the input directory to invenio fixtures."""
    in_dir = Path(in_dir)
    out_file = Path(out_file)

    if not in_dir.exists():
        raise click.Abort("The input directory does not exist")

    fixture_data = []

    for base, _subdirs, files in Path(in_dir).walk():
        for f in files:
            record_data = json.loads((base / f).read_text())
            id_ = None
            for rec_file in record_data.get("files", {}).get("entries", []):
                rec_file["transfer"] = {
                    "type": "R",
                    "url": f"{S3_PREFIX}/{rec_file.pop("path")}"
                }
                id_ = rec_file["key"][:-5]
            identifiers = record_data.get("metadata", {}).get("identifiers", [])
            if identifiers:
                for idx, identifier in reversed(list(enumerate(record_data.get("metadata", {}).get("identifiers", [])))):
                    if not identifier.get("identifier"):
                        del identifiers[idx]
                if not identifiers:
                    del record_data.get("metadata", {})["identifiers"]
            if id_:
                record_data["id"] = id_

            fixture_data.append(record_data)

    out_file.write_text(json.dumps(fixture_data, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    convert()
