"""UI resource components for the FRAM record detail page.

Adds two pieces of ``extra_context`` (consumed by
``record_detail/main.html``) that need Python logic not expressible in
Jinja alone:

- ``fits_header_cards``: the record's raw FITS header, for the
  collapsible "Original FITS header" section (see
  ``docs/FITS_DYNAMIC_VIEWER_HANDOFF.md`` -- matches fram.fzu.cz's own
  header dump, per the stakeholder-provided extraction snippet).
- ``dark_frame``/``flat_frame``: the record's best-matching calibration
  frames (see ``ui/fram/calibration.py``), for the "Dark:"/"Flat:"
  metadata table rows.

Both are computed only when the record has exactly one accessible
completed FITS file (same gate used by the preview image itself), and
both fail soft (log + omit the context key) rather than breaking detail
page rendering if anything goes wrong -- this is optional supplementary
information, not core record data.
"""

from __future__ import annotations

import logging
from typing import Any

from astropy.io import fits
from flask_principal import Identity
from invenio_records_resources.services.records.results import RecordItem
from oarepo_runtime import current_runtime
from oarepo_runtime.typing import record_from_result
from oarepo_ui.resources.components import UIResourceComponent
from oarepo_ui.resources.records.config import RecordsUIResourceConfig
from werkzeug.exceptions import Forbidden

from .calibration import find_calibration_frame
from .views import _find_sole_fits_file, _read_fits_file_bytes

log = logging.getLogger(__name__)

#: FITS header keywords not worth displaying (structural/boilerplate,
#: matches the stakeholder-provided extraction snippet in
#: docs/FITS_DYNAMIC_VIEWER_HANDOFF.md).
_IGNORED_HEADER_KEYWORDS = {"COMMENT", "SIMPLE", "BZERO", "BSCALE", "EXTEND", "HISTORY"}


class FramFitsMetadataComponent[T: RecordsUIResourceConfig = RecordsUIResourceConfig](UIResourceComponent[T]):
    """Populate FITS header + dark/flat calibration links for the detail page."""

    def before_ui_detail(
        self,
        *,
        api_record: RecordItem,
        identity: Identity,
        extra_context: dict,
        files: dict | None = None,
        **kwargs: Any,
    ) -> None:
        """Add ``fits_header_cards``/``dark_frame``/``flat_frame`` to extra_context."""
        try:
            record_metadata = api_record["metadata"]
        except Exception:
            log.exception("Could not read record metadata for FITS metadata component")
            return

        # Dark/flat calibration lookup only needs the record's own
        # metadata (no file access required) -- runs independently of
        # whether a previewable FITS file is present.
        for frame_type, context_key in (("masterdark", "dark_frame"), ("masterflat", "flat_frame")):
            try:
                frame = find_calibration_frame(record_metadata, frame_type)
            except Exception:
                log.exception("Calibration frame lookup failed for %s", frame_type)
                frame = None
            if frame is not None:
                extra_context[context_key] = frame

        # FITS header dump requires reading the actual file content, so
        # it's gated on the same "exactly one completed FITS file,
        # permission-checked" condition as the preview image.
        if not files:
            return

        fits_file = _find_sole_fits_file(files)
        if fits_file is None:
            return

        file_service = current_runtime.get_file_service_for_record(record_from_result(api_record))
        if file_service is None:
            return

        try:
            buffer = _read_fits_file_bytes(file_service, api_record.id, fits_file["key"])
            with fits.open(buffer, memmap=False) as hdul:
                header = None
                for hdu in hdul:
                    if getattr(hdu, "data", None) is not None:
                        header = hdu.header
                        break
                if header is None:
                    return
                cards = [
                    (card.keyword, str(card.value), card.comment)
                    for card in header.cards
                    if card.keyword not in _IGNORED_HEADER_KEYWORDS
                ]
        except Forbidden:
            return
        except Exception:
            log.exception("Could not read FITS header for record %s", api_record.id)
            return

        extra_context["fits_header_cards"] = cards
