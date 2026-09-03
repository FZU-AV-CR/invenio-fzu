"""Runtime dark/flat calibration-frame lookup for FRAM records.

Replicates fram.fzu.cz's ``find_calibration_image()`` algorithm
(``archive/views_images.py`` in the real ``fram-archive`` Django app),
confirmed against that project's actual source and a stakeholder email
exchange (see ``docs/FITS_DYNAMIC_VIEWER_HANDOFF.md`` for the full
comparison and quotes).

Per the stakeholder's explicit guidance, calibration frames are **not**
linked to science records via a dedicated metadata field -- they are
located at query time using already-indexed metadata fields, so no
metadata.yaml schema change or upload-time linking step is needed:

    "these calibration images do not need to be explicitly linked to
    the original image as dedicated fields. Instead, they may be
    located at runtime using the metadata."

The matching algorithm (see ``find_calibration_frame``'s docstring for
the exact rules):

- ``metadata.type`` must be ``"masterdark"``/``"masterflat"`` (this
  module only implements the master-frame lookup, not the
  bias+dcurrent-reconstruction fallback, since the sample dataset does
  not exercise it and reconstructing a synthetic dark from bias+dcurrent
  is calibration *math*, out of scope for this round -- see the handoff
  doc's "Raw toggle"/"Processed FITS" sections).
- ``site``, ``ccd``, ``camera_serial``, ``binning``,
  ``image_size.usable_width``/``usable_height`` must match exactly.
- for flats: ``filter`` must also match exactly.
- for darks: ``exposure`` must also match exactly.
- among remaining candidates, prefer the latest ``observation_time`` not
  after the science record's own ``observation_time``; if none exists,
  fall back to the closest *later* one.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import g
from invenio_search.engine import dsl
from oarepo_runtime import current_runtime

log = logging.getLogger(__name__)

#: Fields (dotted metadata paths) that must match exactly regardless of
#: whether we're looking for a dark or a flat frame.
_COMMON_MATCH_FIELDS = (
    "metadata.site",
    "metadata.ccd",
    "metadata.camera_serial",
    "metadata.binning",
    "metadata.image_size.usable_width",
    "metadata.image_size.usable_height",
)

#: Extra field that must match exactly, per calibration frame type.
_TYPE_SPECIFIC_MATCH_FIELD = {
    "masterflat": "metadata.filter",
    "masterdark": "metadata.exposure",
}


def _get_path(data: dict, dotted_path: str) -> Any:
    """Resolve a dotted path (e.g. ``metadata.image_size.usable_width``)."""
    value = data
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def find_calibration_frame(record_metadata: dict, frame_type: str) -> dict | None:
    """Find the best-matching calibration frame for a science record.

    :param record_metadata: the science record's ``metadata`` dict (as
        returned by the UI-facing record serialization, i.e.
        ``record["metadata"]``).
    :param frame_type: ``"masterdark"`` or ``"masterflat"``.
    :return: the matching calibration record's dict (with at least
        ``id``/``metadata.filename``), or ``None`` if no match is found
        (including if the science record itself lacks the fields needed
        to match against, e.g. it's itself a calibration frame).
    """
    match_field = _TYPE_SPECIFIC_MATCH_FIELD.get(frame_type)
    if match_field is None:  # pragma: no cover - defensive, internal misuse only
        raise ValueError(f"Unsupported calibration frame_type: {frame_type!r}")

    observation_time = record_metadata.get("observation_time")
    if not observation_time:
        return None

    must_clauses = [dsl.Q("term", **{"metadata.type": frame_type})]
    for field in (*_COMMON_MATCH_FIELDS, match_field):
        value = _get_path({"metadata": record_metadata}, field)
        if value is None:
            # Missing match criterion on the science record itself --
            # can't reliably find a calibration frame (e.g. the record
            # doesn't declare camera_serial). Bail out rather than
            # matching too broadly.
            return None
        must_clauses.append(dsl.Q("term", **{field: value}))

    extra_filter = dsl.Q("bool", must=must_clauses)

    model = current_runtime.models.get("fram")
    if model is None:  # pragma: no cover - defensive, should never happen
        return None

    try:
        results = model.service.search(
            g.identity,
            params={"size": 50, "page": 1},
            extra_filter=extra_filter,
        )
        candidates = list(results)
    except Exception:
        log.exception("Calibration frame lookup failed for frame_type=%s", frame_type)
        return None

    if not candidates:
        return None

    earlier = [c for c in candidates if (c.get("metadata", {}).get("observation_time") or "") <= observation_time]
    later = [c for c in candidates if (c.get("metadata", {}).get("observation_time") or "") > observation_time]

    if earlier:
        # Latest one not exceeding the science record's own time.
        return max(earlier, key=lambda c: c["metadata"]["observation_time"])
    if later:
        # Fall back to the closest later one.
        return min(later, key=lambda c: c["metadata"]["observation_time"])
    return None
