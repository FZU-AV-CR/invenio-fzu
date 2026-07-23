"""
Dune (Fermilab) silicon photomultiplier datasets

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
    PrependMixin,
    SetDefaultSearchFields,
)
from oarepo_model.datatypes.registry import from_yaml
from oarepo_model.model import ModelMixin

from .serializers import DataCiteJSONSerializer


class SipmPermissionPolicyMixin(ModelMixin):
    """Custom permission policy for sipm."""

    can_view_deposit_page = [AuthenticatedUser()]


sipm_model = model(
    "sipm",
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
        PrependMixin("PermissionPolicy", SipmPermissionPolicyMixin),
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
            "metadata.box",
            "metadata.trays",
            "metadata.tray_numbers",
            "metadata.qr_list",
            "metadata.measurement_types",
            "metadata.ardu_units",
            "metadata.requestor_search",
            "metadata.requestor",
            "metadata.manufacturer",
            "metadata.file_types",
        ),
        AddFacetGroup(
            name="default",
            facets=[
                "metadata.box",
                "metadata.requestor",
                "metadata.manufacturer",
                "metadata.title",
                "metadata.trays",
                "metadata.qr_list",

            ],
        ),
    ],
    configuration={"ui_blueprint_name": "sipm_ui"},
)
