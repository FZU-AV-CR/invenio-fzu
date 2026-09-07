"""On-demand FITS image preview endpoint for FRAM records.

Replicates the fram.fzu.cz archive's server-side FITS-to-JPEG rendering,
bypassing oarepo_ui's generic content-negotiated record/file routing (which
is built for JSON/HTML views, not raw binary image responses).

Only records with *exactly one* FITS (``.fits``/``.fit``) file are
previewed. Any deviation from that (no files, multiple files, non-FITS
files only, a file still uploading, ...) results in a 404 response and --
per the record detail template -- no ``<img>`` tag is rendered at all, so
no broken-image icon or placeholder is ever shown to the user.
"""

from __future__ import annotations

import logging
from io import BytesIO

from flask import Response, g, request, send_file
from invenio_records_resources.services.errors import PermissionDeniedError
from oarepo_runtime import current_runtime
from sqlalchemy.exc import NoResultFound
from werkzeug.exceptions import Forbidden, NotFound

from .preview import DEFAULT_PAN, DEFAULT_SCALE, DEFAULT_STRETCH, DEFAULT_ZOOM, render_fits_preview
from .preview_cache import get_or_render_preview

log = logging.getLogger(__name__)

#: FITS files are conventionally suffixed either way.
FITS_EXTENSIONS = (".fits", ".fit")

#: Safety cap: refuse to render preview for unexpectedly huge files rather
#: than risk excessive memory usage / a denial-of-service vector.
MAX_PREVIEW_SOURCE_SIZE = 512 * 1024 * 1024  # 512 MiB

#: Cache-Control max-age for successfully rendered/cached preview images.
PREVIEW_MAX_AGE = 24 * 60 * 60  # seconds


def _find_sole_fits_file(files_dict: dict) -> dict | None:
    """Return the single completed FITS file entry, or None if not exactly one."""
    entries = files_dict.get("entries", []) if files_dict.get("enabled") else []
    fits_entries = [
        entry
        for entry in entries
        if entry.get("status") == "completed" and entry.get("key", "").lower().endswith(FITS_EXTENSIONS)
    ]
    if len(fits_entries) != 1:
        return None
    return fits_entries[0]


def _resolve_record_and_sole_fits_file(pid_value: str):
    """Resolve a FRAM record + its file service + its sole FITS file entry.

    Shared by ``fits_preview_view`` and ``fits_header_view`` so the
    "exactly one completed FITS file, permission-checked" resolution logic
    (and its 404/403 semantics) only needs to be implemented once.

    :return: ``(record, file_service, fits_file_dict)``.
    :raises NotFound: record/draft doesn't exist, or doesn't have exactly
        one completed FITS file visible to the current identity.
    :raises Forbidden: identity lacks permission to list/read the record's
        files.
    """
    model = current_runtime.models.get("fram")
    if model is None:  # pragma: no cover - defensive, should never happen
        raise NotFound()

    try:
        record = model.service.read(g.identity, pid_value)
    except NoResultFound:
        try:
            record = model.service.read_draft(g.identity, pid_value)
            file_service = model.draft_file_service
        except NoResultFound:
            raise NotFound() from None
    else:
        file_service = model.file_service

    if file_service is None:  # pragma: no cover - defensive
        raise NotFound()

    try:
        files = file_service.list_files(g.identity, record.id)
    except PermissionDeniedError as e:
        raise Forbidden(str(e)) from e

    fits_file = _find_sole_fits_file(files.to_dict())
    if fits_file is None:
        raise NotFound()

    return record, file_service, fits_file


def _read_fits_file_bytes(file_service, record_id: str, file_key: str) -> BytesIO:
    """Read a record's file content into an in-memory buffer, permission-checked."""
    try:
        file_item = file_service.get_file_content(g.identity, record_id, file_key)
        with file_item.get_stream("rb") as stream:
            return BytesIO(stream.read())
    except PermissionDeniedError as e:
        raise Forbidden(str(e)) from e


def fits_preview_view(pid_value: str) -> Response:
    """Render (or serve from cache) the FITS preview JPEG for a FRAM record.

    Query parameters (all optional), matching the real fram.fzu.cz archive
    viewer's toolbar semantics (see ``preview.py``'s module docstring for
    the full rationale/comparison):

    - ``stretch``: one of ``preview.STRETCH_FUNCTIONS`` keys.
    - ``scale``: one of ``preview.SCALE_QMAX_PERCENTILES`` keys (the
      "qmax" percentile of the clip interval).
    - ``zoom``: one of ``preview.ZOOM_LEVELS``.
    - ``dx``/``dy``: pan offsets (fractions of a quadrant), used together
      with ``zoom`` > 1.
    - ``grid``: ``"1"`` to draw a grid overlay, anything else (or absent)
      for no overlay.
    """
    stretch = request.args.get("stretch", DEFAULT_STRETCH)
    scale = request.args.get("scale", DEFAULT_SCALE)
    zoom = request.args.get("zoom", DEFAULT_ZOOM)
    dx = request.args.get("dx", DEFAULT_PAN)
    dy = request.args.get("dy", DEFAULT_PAN)
    grid = request.args.get("grid", "0")
    show_grid = grid == "1"

    record, file_service, fits_file = _resolve_record_and_sole_fits_file(pid_value)

    file_key = fits_file["key"]
    checksum = fits_file.get("checksum") or ""
    size = fits_file.get("size") or 0

    if size and size > MAX_PREVIEW_SOURCE_SIZE:
        log.warning("FITS file %s (record %s) too large for preview (%d bytes)", file_key, record.id, size)
        raise NotFound()

    def _render() -> bytes:
        buffer = _read_fits_file_bytes(file_service, record.id, file_key)
        return render_fits_preview(buffer, stretch=stretch, scale=scale, zoom=zoom, dx=dx, dy=dy, grid=show_grid)

    cache_path = get_or_render_preview(
        checksum or file_key, stretch, scale, zoom, _render, dx=dx, dy=dy, grid=grid
    )

    return send_file(
        cache_path,
        mimetype="image/jpeg",
        conditional=True,
        etag=True,
        max_age=PREVIEW_MAX_AGE,
    )
