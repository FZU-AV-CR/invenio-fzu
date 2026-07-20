"""
A generic dataset model for fram observation data.

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


class FramPermissionPolicyMixin(ModelMixin):
    """Custom permission policy for fram."""

    can_view_deposit_page = [AuthenticatedUser()]


# TODO: Consider letting users add an image/icon for the model,
# so that the deposit model selection page is more visually appealing.
fram_model = model(
    "fram",
    version="1.0.0",
    description="A generic dataset model for fram observation data.\n",
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
        PrependMixin("PermissionPolicy", FramPermissionPolicyMixin),
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
            "metadata.identifier",
            "metadata.target",
            "metadata.type",
            "metadata.observation_time",
            "metadata.observation_night",
            "metadata.exposure",
            "metadata.center.ra",
            "metadata.center.dec",
            "metadata.radius",
            "metadata.altitude_azimuth.altitude",
            "metadata.altitude_azimuth.azimuth",
            "metadata.site",
            "metadata.ccd",
            "metadata.camera_serial",
            "metadata.filter",
            "metadata.binning",
            "metadata.image_size.height",
            "metadata.image_size.width",
            "metadata.image_size.usable_height",
            "metadata.image_size.usable_width",
            "metadata.file_types",
            "metadata.filename",
            "metadata.footprint",
            "metadata.healpix_idx",
        ),

        AddFacetGroup(
            name="default",
            facets=[
                "metadata.site",
                "metadata.type",
                "metadata.target",
                "metadata.observation_night",
                "metadata.observation_time",
                "metadata.filename",
                "metadata.identifier",
                "metadata.exposure",
                "metadata.center.ra",
                "metadata.center.dec",
                "metadata.radius",
                "metadata.altitude_azimuth.altitude",

                #"metadata.altitude_azimuth.azimuth",

                "metadata.ccd",
                "metadata.camera_serial",
                "metadata.filter",
                "metadata.binning",
                "metadata.image_size.height",
                "metadata.image_size.width",
                "metadata.image_size.usable_height",
                "metadata.image_size.usable_width",

                #"metadata.file_footprint",

                "metadata.healpix_idx",
                "metadata.title",
            ],
        ),

    ],
    configuration={"ui_blueprint_name": "fram_ui"},
)
