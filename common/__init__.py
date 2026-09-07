from ccmm_invenio.models import ccmm_production_preset_1_1_0
from oarepo_communities.model.presets import communities_preset
from oarepo_requests.model.presets.requests import requests_preset
from oarepo_workflows.model.presets import workflows_preset

model_presets=[
    ccmm_production_preset_1_1_0,
    workflows_preset,
    requests_preset,
    communities_preset,
]
"""Base presets for all model types."""
