from ccmm_invenio.ui.config import CCMMRecordsUIResourceConfig
from ccmm_invenio.ui.resource import CCMMRecordsUIResource
from flask_menu import current_menu
from invenio_i18n import lazy_gettext as _
from oarepo_rdm.ui.components import (
    CommunitiesMembershipsComponent,
    RDMVocabularyOptionsComponent,
)
from oarepo_ui.overrides import UIComponent
from oarepo_ui.overrides.components import UIComponentImportMode
from oarepo_ui.proxies import current_oarepo_ui
from oarepo_ui.resources import BabelComponent
from oarepo_ui.resources.components import (
    # AllowedCommunitiesComponent,
    AllowedHtmlTagsComponent,
    EmptyRecordAccessComponent,
    FilesComponent,
    FilesLockedComponent,
    FilesQuotaAndTransferComponent,
    PermissionsComponent,
    RecordRestrictionComponent,
)
from oarepo_ui.resources.components.custom_fields import CustomFieldsComponent
from oarepo_ui.resources.records.config import RecordsUIResourceConfig
from oarepo_ui.resources.records.resource import RecordsUIResource
from oarepo_ui.utils import can_view_deposit_page

from .views import fits_preview_view


class FramUIResourceConfig(CCMMRecordsUIResourceConfig):
    template_folder = "templates"
    url_prefix = "/fram"
    blueprint_name = "fram_ui"
    model_name = "fram"

    search_component = UIComponent(
        "FramResultsListItem",
        "@js/fram/search/ResultsListItem",
        UIComponentImportMode.DEFAULT,
    )

    application_id = "fram"


class FramUIResource(CCMMRecordsUIResource):
    pass


def ui_overrides(app):
    """Register UI overrides."""
    ui_resource_config = FramUIResourceConfig()

    if (
        current_oarepo_ui is not None
        and ui_resource_config.model
        and ui_resource_config.model.record_json_schema
        and ui_resource_config.search_component
    ):
        current_oarepo_ui.register_result_list_item(
            ui_resource_config.model.record_json_schema,
            ui_resource_config.search_component,
        )


def init_menu(app):
    """Initialize menu before first request."""
    ui_resource_config = FramUIResourceConfig()

    with app.app_context():
        current_menu.submenu("plus.create_fram").register(
            f"{ui_resource_config.blueprint_name}.deposit_create",
            _("New FRAM"),
            order=1,
            visible_when=can_view_deposit_page,
        )


def finalize_app(app):
    """Finalize app"""
    init_menu(app)
    ui_overrides(app)


def create_blueprint(app):
    """Register blueprint for this resource."""
    blueprint = FramUIResource(FramUIResourceConfig()).as_blueprint()

    # Custom on-demand FITS image preview route. Registered directly on the
    # Flask blueprint (bypassing oarepo_ui's generic content-negotiated
    # record/file routing, which is built for JSON/HTML views and does not
    # fit a raw binary image response) so it can serve `image/jpeg` bytes.
    # See ui/fram/views.py for the implementation and design rationale.
    blueprint.add_url_rule(
        "/fram/records/<pid_value>/preview/fits-image.jpg",
        view_func=fits_preview_view,
        endpoint="fits_preview",
    )

    return blueprint
