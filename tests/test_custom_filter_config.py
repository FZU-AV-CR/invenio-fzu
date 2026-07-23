import json
from pathlib import Path

import yaml

from models.fram.model import fram_model


ROOT = Path(__file__).resolve().parents[1]


def _load_metadata(model_name: str) -> dict:
    metadata_path = ROOT / "models" / model_name / "metadata.yaml"
    with metadata_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_sipm_box_and_atlas_batch_have_text_match_facet_defs() -> None:
    sipm_metadata = _load_metadata("sipm")
    atlas_metadata = _load_metadata("atlas_itk")

    sipm_box = sipm_metadata["Metadata"]["properties"]["box"]
    atlas_batch = atlas_metadata["Metadata"]["properties"]["batch"]

    assert sipm_box["facet-def"]["facet"] == "models.sipm.facets.TextMatchFacet"
    assert sipm_box["facet-def"]["field"] == "metadata.box"

    assert atlas_batch["facet-def"]["facet"] == "models.atlas_itk.facets.TextMatchFacet"
    assert atlas_batch["facet-def"]["field"] == "metadata.batch"


def test_fram_footprint_survives_schema_dump() -> None:
    payload = json.loads((ROOT / "sample_data" / "Fram" / "fram_001.json").read_text(encoding="utf-8"))
    schema = fram_model.MetadataSchema()

    loaded = schema.load(payload["metadata"])
    dumped = schema.dump(loaded)

    assert dumped["footprint"] == payload["metadata"]["footprint"]
