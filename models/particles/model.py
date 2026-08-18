"""
Particles detector experiments

"""

from __future__ import annotations

from ccmm_invenio.models import ccmm_production_preset_1_1_0
from invenio_i18n import lazy_gettext as _
from invenio_rdm_records.resources.serializers.ui.schema import UIRecordSchema
from invenio_records_permissions.generators import AuthenticatedUser
from oarepo_model.api import model
from oarepo_model.customizations import (
    AddFacetGroup,
    AddMetadataExport,
    AddToDictionary,
    PrependMixin,
    SetDefaultSearchFields,
)
from oarepo_model.datatypes.registry import from_yaml
from oarepo_model.model import ModelMixin

from .facets import (
    DatesTypeRangeFacet,
    EnergyRangeOverlapFacet,
    TextMatchFacet,
)
from .serializers import DataCiteJSONSerializer



class ParticlesPermissionPolicyMixin(ModelMixin):
    """Custom permission policy for particles."""

    can_view_deposit_page = [AuthenticatedUser()]


particles_model = model(
    "particles",
    version="1.0.0",
    presets=[ccmm_production_preset_1_1_0],
    types=[from_yaml("metadata.yaml", __file__)],
    metadata_type="Metadata",
    customizations=[
        # Add your customizations here, such as custom exports and class mixins.
        # The list of available extensions is at https://github.com/oarepo/oarepo-model.
        # If you do not find a customization that suits your needs or need a
        # help with using customizations, please contact us at support@cesnet.cz and
        # specify the keyword "Invenio repository development" inside the subject or
        # mail body of the request.
        # TODO: remove this customization if you use oarepo-communities for RDM 14
        PrependMixin("PermissionPolicy", ParticlesPermissionPolicyMixin),
        # export for datacite
        AddMetadataExport(
            code="datacite",
            name=_("Datacite export"),
            mimetype="application/vnd.datacite.datacite+json",
            serializer=DataCiteJSONSerializer(),
        ),
        PrependMixin("RecordUISchema", UIRecordSchema),
        # Limit searchable fields to prevent maxClauseCount error
        SetDefaultSearchFields(
            "metadata.title",
            "metadata.description",
            "metadata.subjects.subject",
            "metadata.creators.person_or_org.name",
            "metadata.contributors.person_or_org.name",
            "metadata.experiment.id",
            "metadata.category",
            "metadata.dataset_type",
            "metadata.number_of_events",
            "metadata.recid",
            "metadata.collision_information",
            "metadata.related_resources",
        ),
        AddFacetGroup(
            name="default",
            facets=[
                "metadata.experiment",
                "metadata.category",
                "metadata.dataset_type",
                "metadata.collision_information.type",
                "metadata.file_types",

                # TODO: somehow include "metadata.dates.created.year",
                # "metadata.number_of_events",

            ],
        ),

        # ── Collision energy range filter: virtual facet registration ─────
        # "metadata.collision_information.energy_range" is NOT a
        # metadata.yaml field -- it's a virtual facet spanning two real
        # fields (energy_min, energy_max), using interval-overlap
        # semantics (see EnergyRangeOverlapFacet's docstring in
        # models/particles/facets.py for the full rationale). Registered
        # directly into RecordFacets here, the same pattern used for
        # FRAM's "cone_search" virtual facet (models/fram/model.py).
        AddToDictionary(
            "RecordFacets",
            {
                "metadata.collision_information.energy_range": EnergyRangeOverlapFacet(
                    min_field="metadata.collision_information.energy_min",
                    max_field="metadata.collision_information.energy_max",
                ),
                # ── Title partial-match filter: virtual facet ──────────
                # "title" comes from the CCMM/RDM preset, not our own
                # metadata.yaml, so it can't use a `facet-def` entry.
                # See TextMatchFacet's docstring in facets.py.
                "metadata.title": TextMatchFacet(
                    field="metadata.title.keyword",
                ),
                # ── Created date range filter: virtual facet ───────────
                # "metadata.dates" (RDM/CCMM RDMDates) is an array of
                # {date, type: {id}} objects; filters on the "Created"
                # typed entry only. See DatesTypeRangeFacet's docstring
                # in facets.py for the plain-bool (non-nested) rationale.
                "metadata.dates.created_range": DatesTypeRangeFacet(
                    date_field="metadata.dates.date",
                    type_field="metadata.dates.type.id",
                    type_id="Created",
                ),
            },
        ),
    ],

    configuration={"ui_blueprint_name": "particles_ui"},
)

