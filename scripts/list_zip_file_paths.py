"""
List files.entries[].path of all json records stored inside zip archives.
Records inside a "bad" directory are skipped.

The zip archives are read member by member, so neither the archives
nor their content are ever fully extracted to disk or loaded into memory.

How to run:

    python scripts/list_zip_file_paths.py ../invenio-fzu-data > paths.txt

"""

import json
import sys
import zipfile
from pathlib import Path

import click


@click.command()
@click.argument("in_dir")
def list_paths(in_dir):
    """Print file paths referenced by json records in zips under IN_DIR."""
    in_dir = Path(in_dir)

    if not in_dir.exists():
        raise click.BadParameter("The input directory does not exist")

    for zip_path in sorted(in_dir.rglob("*.zip")):
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                if info.is_dir() or not info.filename.endswith(".json"):
                    continue
                if "bad" in info.filename.split("/")[:-1]:
                    continue
                with zf.open(info) as f:
                    try:
                        record_data = json.load(f)
                    except json.JSONDecodeError as e:
                        print(f"{zip_path}:{info.filename}: {e}", file=sys.stderr)
                        continue
                for rec_file in record_data.get("files", {}).get("entries", []):
                    if "path" in rec_file:
                        print(rec_file["path"])


if __name__ == "__main__":
    list_paths()
