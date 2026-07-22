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
    PatchIndexPropertyMapping,
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
            "metadata.alt_az.altitude",
            "metadata.alt_az.azimuth",

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

        # Facet group: only fields with a small, repeated set of values
        # belong here (OpenSearch terms aggregation -> sidebar checkboxes).
        # Continuous/high-cardinality fields (RA/Dec/radius, altitude,
        # filename, title, observation_time) are handled instead as
        # input-based filters in CustomFilters.jsx (see
        # ui/fram/semantic-ui/js/fram/search/CustomFilters.jsx), which
        # mirrors how the original FRAM archive exposed e.g. "night" as a
        # direct date input rather than a browsable facet.
        AddFacetGroup(
            name="default",
            facets=[
                "metadata.site",
                "metadata.type",
                "metadata.target",
                "metadata.observation_night",
                "metadata.identifier",
                "metadata.exposure",
                "metadata.ccd",
                "metadata.camera_serial",
                "metadata.filter",
                "metadata.binning",
                "metadata.image_size.height",
                "metadata.image_size.width",
                "metadata.image_size.usable_height",
                "metadata.image_size.usable_width",
                "metadata.healpix_idx",
            ],
        ),

        # ── Spherical index: OpenSearch geo mapping overrides ──────────────
        # oarepo emits `center_geo`/`footprint` as generic `object` mappings
        # (Section 4b/4a of the spherical index spec). We own our model's
        # generated mapping file, so we patch it ourselves here rather than
        # requesting a change from Cesnet -- this is a self-service override
        # applied at `nrp model build` / `./run.sh reset` time, not something
        # that needs coordination with the Cesnet-managed OpenSearch cluster.
        #
        # center_geo: {lat, lon} shadow field -> geo_point, enables
        # geo_distance cone search queries.
        PatchIndexPropertyMapping(
            "metadata.center_geo",
            {"type": "geo_point", "properties": None, "dynamic": None},
        ),
        # footprint: GeoJSON polygon (optional, second-pass position
        # re-checking only, not exposed in the UI) -> geo_shape.
        # `footprint` is declared as `keyword` in metadata.yaml (see the
        # field's docstring for why), so oarepo's default mapping also
        # carries a leftover `ignore_above: 256` (keyword-only setting)
        # that OpenSearch rejects on a geo_shape field -- null it out here
        # the same way `dynamic` is nulled out for center_geo above.
        PatchIndexPropertyMapping(
            "metadata.footprint",
            {
                "type": "geo_shape",
                "properties": None,
                "dynamic": None,
                "ignore_above": None,
            },
        ),


    ],
    configuration={"ui_blueprint_name": "fram_ui"},
)

