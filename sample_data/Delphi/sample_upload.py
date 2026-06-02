import asyncio
import csv
import json
import logging
import time
from pathlib import Path
import zipfile
from contextlib import asynccontextmanager
import getpass

# from _pytest._code import source
from yarl import URL

try:
    from nrp_cmd.async_client import get_async_client
    from nrp_cmd.config import Config, RepositoryConfig
    from nrp_cmd.errors import (
        RepositoryCommunicationError,
        RepositoryClientError,
        StructureError
    )
except Exception as exc:
    raise SystemExit(f"Missing NRP async library: {exc}")


def fill_cern_metadata(source) -> dict:
    def _first(seq, default=None):
        return seq[0] if isinstance(seq, list) and seq else default

    def _to_year(value):
        if not value:
            return ""
        return str(value)[:4]

    def _parse_energy_range(value):
        # Expect strings like "181-210 GeV"
        if not value or not isinstance(value, str):
            return "", 0, 0
        numbers = []
        current = ""
        for ch in value:
            if ch.isdigit() or ch == ".":
                current += ch
            elif current:
                numbers.append(current)
                current = ""
        if current:
            numbers.append(current)
        if len(numbers) >= 2:
            try:
                return value, float(numbers[0]), float(numbers[1])
            except ValueError:
                return value, 0, 0
        return value, 0, 0

    def _extract_ecms(value):
        # finds patterns like "ecms=191.6" and returns float
        if not value or not isinstance(value, str):
            return None
        lowered = value.lower()
        token = "ecms="
        if token not in lowered:
            return None
        start = lowered.find(token) + len(token)
        num = []
        for ch in lowered[start:]:
            if ch.isdigit() or ch == ".":
                num.append(ch)
            elif num:
                break
        try:
            return float("".join(num)) if num else None
        except ValueError:
            return None

    # with open(path, "r", encoding="utf-8") as fh:
    #     source = json.load(fh)

    metadata = {
    "metadata": {
        "resource_type": {
            "id": "c_ddb1"
        },
        "recid": None,
        "creators": [
            {
                "person_or_org": {
                    "name": "DELPHI Collaboration",
                    "type": "organizational"
                }
            }
        ],
        "file_types": [],
        "title": "test",
        "publication_date": None,
        "publisher": "CERN Open Data Portal",
        "description": "",
        "subjects": [
            {
                "subject": "Higgs physics"
            },
            {
                "subject": "Electron–positron collisions"
            }
        ],
        "rights": [
            {
                "id": "CC0-1.0"
            }
        ],
        "identifiers": [
            {
                "identifier": "",
                "scheme": "url"
            }
        ],
        "dates": [
            {
                "date": "",
                "type": {
                    "id": "Created"
                }
            }
        ],
        "experiment": "DELPHI",
        "collision_information": {
            "type": "e+e-",
            "energy": "",
            "energy_min": 0,
            "energy_max": 0
        },
        "category": {
        },
        "dataset_type": None,
        "number_of_events": 0
    },
    "files": {
        "enabled": True
    }
}

    src = source
    tgt = metadata.get("metadata", {})

    # print(json.dumps(src, indent=2))

    # Title / publisher / dates
    tgt["title"] = src.get("title", tgt.get("title", ""))
    # FZU
    tgt["publisher"] = "FZU Institute of Physics of the Czech Academy of Sciences"
    # Today
    tgt["publication_date"] = time.strftime("%Y-%m-%d")
    # tgt["publication_date"] = "2026-02-28"

    # Record ID
    recid = int(src.get("recid"))
    tgt["recid"] = recid

    # Description: combine key narrative fields
    parts = []
    for key in ("methodology",  "abstract"):
        entry = src.get(key, {})
        desc = entry.get("description") if isinstance(entry, dict) else None
        if desc:
            parts.append(desc.strip())
    if parts:
        tgt["description"] = "\n\n".join(parts)

    # Creators from collaboration
    collab = (src.get("collaboration") or {}).get("name")
    if collab:
        tgt["creators"] = [{
            "person_or_org": {"name": collab, "type": "organizational"}
        }]

    # File types / formats
    formats = (src.get("distribution") or {}).get("formats")
    # always add json
    formats = set(formats or []) | {"json"}
    if formats:
        tgt["file_types"] = [str(f).lower() for f in formats]

    # Subjects from categories + collections
    subjects = []
    primary = (src.get("categories") or {}).get("primary")
    if primary:
        subjects.append({"subject": str(primary)})
    for item in src.get("collections", []):
        subjects.append({"subject": str(item)})
    if subjects:
        tgt["subjects"] = subjects

    # Rights / license
    license_info = src.get("license", {})
    if isinstance(license_info, dict):
        attr = str(license_info.get("attribution", "")).lower()
        if "cc0-1.0" in attr:
            tgt["rights"] = [{"id": "CC0-1.0"}]

    # Identifiers (append DOI/OAI if present)
    identifiers = tgt.get("identifiers", [])
    def _add_identifier(value, scheme):
        if not value:
            return
        if any(i.get("identifier") == value for i in identifiers):
            return
        identifiers.append({"identifier": value, "scheme": scheme})

    # Dates (created)
    created_year = _to_year(_first(src.get("date_created", [])))
    if created_year and tgt.get("dates"):
        tgt["dates"][0]["date"] = created_year

    # Experiment
    exp = _first(src.get("experiment", [])) or collab
    if exp:
        tgt["experiment"] = exp

    # Dataset type
    secondary = (src.get("type") or {}).get("secondary", [])
    if isinstance(secondary, list) and any(str(s).lower() == "simulated" for s in secondary):
        tgt["dataset_type"] = "simulated"
    elif isinstance(secondary, list) and any(str(s).lower() == "collision" for s in secondary):
        tgt["dataset_type"] = "collision"
    elif isinstance(secondary, list) and any(str(s).lower() == "logbook" for s in secondary):
        # TODO: fix values
        tgt["dataset_type"] = "logbook"
        tgt["resource_type"] = {"id": "publication"}
        tgt.pop("collision_information", None)  # logbooks don't have collision info
        tgt.pop("number_of_events", None)  # logbooks don't have experiment field
        metadata["metadata"] = tgt
        return metadata
    elif isinstance(secondary, list) and any(str(s).lower() == "manual" for s in secondary):
        tgt["dataset_type"] = "manual"
        tgt["resource_type"] = {"id": "publication"}
        tgt.pop("collision_information", None)  # logbooks don't have collision info
        tgt.pop("number_of_events", None)  # logbooks don't have experiment field
        metadata["metadata"] = tgt
        return metadata
    elif isinstance(secondary, list) and any(str(s).lower() == "report" for s in secondary):
        tgt["dataset_type"] = "report"
        tgt["resource_type"] = {"id": "publication"}
        tgt.pop("collision_information", None)  # logbooks don't have collision info
        tgt.pop("number_of_events", None)  # logbooks don't have experiment field
        metadata["metadata"] = tgt
        return metadata
    else:
        tgt["dataset_type"] = str(secondary[0]).lower()
        if "dataset_type" in tgt and tgt["dataset_type"] not in ("Collision", "Simulated"):
            print(f"Warning: dataset_type unknown. Got '{tgt['dataset_type']}'")

    # _add_identifier(src.get("doi"), "doi")
    # _add_identifier(((src.get("pids") or {}).get("oai") or {}).get("id"), "oai")
    # if identifiers:
    #     tgt["identifiers"] = identifiers

    # Collision information
    colinfo = src.get("collision_information", {})
    if isinstance(colinfo, dict):
        energy_str, e_min, e_max = _parse_energy_range(colinfo.get("energy"))
        ecms = _extract_ecms((src.get("abstract") or {}).get("description"))
        if ecms is not None:
            energy_str = f"{ecms} GeV"
            e_min = e_max = ecms
        tgt["collision_information"] = {
            "type": colinfo.get("type", tgt.get("collision_information", {}).get("type", "")),
            "energy": energy_str,
            "energy_min": e_min,
            "energy_max": e_max
        }
        # print(tgt["collision_information"])

    # Category
    if primary:
        tgt["category"] = {"id": str(primary).lower()}

    # Number of events
    num_events = (src.get("distribution") or {}).get("number_events")
    if isinstance(num_events, int):
        tgt["number_of_events"] = num_events

    metadata["metadata"] = tgt
    return metadata


async def create_local_client():
    config = Config()
    token = ""

    # securely enter the token
    if token == "":
        token = getpass.getpass("Enter API token for repository: ").strip()

    config.add_repository(RepositoryConfig(
        alias="physica-local",
        url=URL("https://127.0.0.1:5000/"),
        token=token,
        verify_tls=False
    ))
    return await get_async_client("physica-local", config=config)


async def upload_record_async(
    client,
    original: dict,
):
    # try:
        # Fill metadata template with actual values
        metadata = fill_cern_metadata(original)
        # print(json.dumps(metadata, indent=2))

        # Create a new record
        record = await client.records.create(
            metadata,
            files_enabled=False,
            model="particles" # , community="my-community-slug", workflow="review"
        )

        record.metadata["identifiers"][0]["identifier"] = str(record.links.self_html)
        record.metadata["identifiers"][0]["scheme"] = "url"

        if len(original.get("distribution", []).get("files", [])) > 20:
            record.metadata["file_types"] = record.metadata.get("file_types", []) + ["zip"]

        updated = await client.records.draft_records.update(record)

        published = await client.records.publish(record)
        return published
    # except Exception as exc:
    #     print(f"Error uploading record: {exc}")


async def main_async() -> None:
    client = await create_local_client()

    sample = json.loads(Path("sampled_metadata.json").read_text(encoding="utf-8"))

    print(f"Uploading {len(sample)} records...")
    tasks = []
    for record in sample:
        # print(json.dumps(record, indent=2))
        tasks.append(upload_record_async(
            client=client,
            original=record,
        ))
        # break

    results = await asyncio.gather(*tasks, return_exceptions=True)
    print(f"Upload completed. {len(results)} records processed.")
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            print(f"Record {i} upload failed: {result}")
        else:
            print(f"Record {i} uploaded successfully: {result.links.self_html}")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()

