"""
Particles detector experiments

"""

from __future__ import annotations

from ccmm_invenio.models import ccmm_production_preset_1_1_0
from invenio_i18n import lazy_gettext as _
from invenio_records_permissions.generators import AuthenticatedUser
from oarepo_model.api import model
from oarepo_model.customizations import (
    AddFacetGroup,
    AddMetadataExport,
    PrependMixin,
    SetDefaultSearchFields,
)
from oarepo_model.datatypes.registry import from_yaml
from oarepo_model.model import ModelMixin

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
        ),
        AddFacetGroup(
            name="default",
            facets=[
                "metadata.title",
                "metadata.experiment",
                "metadata.category",
                "metadata.dataset_type",
                "metadata.collision_information.type",
                "metadata.file_types",
                # TODO: somehow include "metadata.dates.created.year",
                # "metadata.number_of_events",

            ],
        ),
    ],
    configuration={"ui_blueprint_name": "particles_ui"},
)
