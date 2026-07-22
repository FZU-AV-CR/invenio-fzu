"""Custom facets for the FRAM model.

``RangeQueryFacet`` implements arbitrary min/max range filtering for
continuous numeric or lexicographically-sortable keyword fields
(altitude, azimuth, observation_night) that oarepo's default facet
generation would otherwise treat as a plain ``TermsFacet`` (exact-match
only, which silently returns zero results for range-style filter values).

It is registered per-field via the ``facet-def`` key in metadata.yaml,
e.g.:

    altitude:
      type: float
      facet-def:
        facet: models.fram.facets.RangeQueryFacet

The UI (CustomFilters.jsx) sends a single string value in the form
``"min..max"`` (either bound may be omitted for an open-ended range),
consistent with the range-string convention already used elsewhere in
oarepo/invenio (e.g. ``oarepo_runtime.services.facets.date.DateFacet``).

This facet is filter-only (no bucket aggregation/browsable value list),
since altitude/azimuth/observation_night are continuous/high-cardinality
fields presented as free-form range inputs, not checkbox facets.

``ConeSearchFacet`` implements sky-position (cone) search: "give me all
records whose field-of-view center is within `radius` degrees of
(RA, Dec)". It is a *virtual* facet -- there is no single metadata.yaml
field named "cone_search" to attach a `facet-def` to (unlike
RangeQueryFacet above). It is instead injected directly into the
model's `RecordFacets` dictionary via `AddToDictionary` in model.py,
under the literal key "cone_search" matching the filter key the UI
(CustomFilters.jsx `ConeSearchInputsComponent`) sends.

Implementation note (2-round / "Plan B" architecture, see
SKY_POSITION_SEARCH_TODO.md and the FRAM_spherical_index_impl spec):
this facet implements ONLY round 1 (coarse HEALPix filter). Round 2
(exact `footprint` geo_shape containment check, to eliminate false
positives introduced by round 1's deliberately-widened search radius)
is not yet implemented -- see the class docstring's "Phase 2" note.

Round 1 correctness requirement: `healpix_idx` stores only the pixel
of the record's field-of-view *center*, not the set of pixels the
field-of-view actually covers. A naive `query_disc(user_radius)` would
therefore produce false NEGATIVES for any record whose center lies
outside the user's search radius but whose (wide) field-of-view still
overlaps the queried sky position. To guarantee zero false negatives,
the search radius passed to `query_disc` is widened by
`MAX_FOV_RADIUS_DEG` (an upper bound on any record's `radius` field):
by the triangle inequality, if a queried point X lies within the
record's field-of-view (radius <= MAX_FOV_RADIUS_DEG) and within
`user_radius` of some point, then the record's center is within
`user_radius + MAX_FOV_RADIUS_DEG` of that point -- so widening
the disk this way can only ever add extra (false-positive) candidates,
never drop a true match. This makes round 1 a safe coarse filter;
round 2 (footprint) is what narrows candidates back down to exact
matches.
"""

from __future__ import annotations

import json
from typing import Any

import healpy as hp
import numpy as np
from invenio_records_resources.services.records.facets import Facet
from invenio_search.engine import dsl

#: NSIDE used when computing `healpix_idx` at ingestion time (see
#: metadata.yaml's `healpix_idx` docstring). Must match exactly, or
#: `query_disc` will return pixel indices from the wrong tessellation.
HEALPIX_NSIDE = 64

#: Upper bound (degrees) on any FRAM record's `radius` (field-of-view
#: half-angle) field. Used to widen the cone-search query radius so
#: round-1 filtering (this facet) never produces false negatives --
#: see the module/class docstrings for the full explanation. FRAM's
#: widest known field of view is ~20.3 deg (see sample_data/Fram/
#: fram_001.json); 25 deg is used as a safety margin. If FRAM
#: instruments with wider fields of view are added later, this
#: constant MUST be increased accordingly, or round 1 can silently
#: start dropping true matches again.
MAX_FOV_RADIUS_DEG = 25.0


class RangeQueryFacet(Facet):
    """Arbitrary min/max range filter facet (no aggregation buckets).

    Accepts filter values of the form ``"min..max"``, ``"min.."``, or
    ``"..max"``. Values are passed through as-is to the OpenSearch range
    query (works for both numeric fields and lexicographically-sortable
    keyword strings such as YYYYMMDD dates).
    """

    #: Not a browsable facet: apply the filter directly rather than via
    #: post_filter, since there is no bucket list depending on it.
    post_filter = False

    def __init__(self, field: Any = None, label: Any = None, **kwargs: Any) -> None:
        """Constructor.

        Stores ``field`` and ``label`` as instance attributes (mirroring
        ``invenio_records_resources``'s own ``DateFacet``), rather than
        relying on the base ``dsl.Facet``/``self._params`` -- the base
        class only stores kwargs it explicitly recognizes (e.g. built-in
        aggregation params), so a generic ``field`` kwarg passed through
        ``**kwargs`` never actually lands in ``self._params["field"]``.

        ``self._label`` is also set explicitly (mirroring
        ``LabelledFacetMixin.__init__``) since the UI template that
        renders the facet sidebar accesses ``facet._label`` directly,
        which otherwise raises ``AttributeError`` for facets that don't
        use ``LabelledFacetMixin``.
        """
        self._field = field
        self._label = label or ""
        super().__init__(label=label, **kwargs)


    def get_aggregation(self) -> Any:
        """Return a minimal aggregation (no buckets are displayed for this facet)."""
        return dsl.A("filter", dsl.Q("match_all"))


    def get_values(self, data: Any, filter_values: Any) -> dict:
        """This facet has no browsable bucket list."""
        return {"buckets": []}

    def get_labelled_values(self, data: Any, filter_values: Any) -> dict:
        """This facet has no browsable bucket list."""
        return {"buckets": [], "label": str(getattr(self, "_label", ""))}

    def add_filter(self, filter_values: list) -> Any:
        """Construct a range filter query from "min..max" style values."""
        if not filter_values:
            return None

        q = None
        for value in filter_values:
            rq = self._build_range_query(value)
            if rq is None:
                continue
            q = rq if q is None else q | rq
        return q

    def _build_range_query(self, value: str) -> Any:
        """Parse a single "min..max" value and build a range dsl.Q."""
        if not isinstance(value, str):
            return None

        value = value.strip()
        if not value:
            return None

        if ".." in value:
            start_raw, _, end_raw = value.partition("..")
        else:
            # single value: exact match via range (gte == lte)
            start_raw = end_raw = value

        start_raw = start_raw.strip()
        end_raw = end_raw.strip()

        es_range: dict[str, Any] = {}
        if start_raw:
            es_range["gte"] = self._coerce(start_raw)
        if end_raw:
            es_range["lte"] = self._coerce(end_raw)

        if not es_range:
            return None

        return dsl.Q("range", **{self._field: es_range})


    @staticmethod
    def _coerce(raw: str) -> Any:
        """Coerce a raw string bound to int/float if possible, else leave as string."""
        try:
            if "." in raw:
                return float(raw)
            return int(raw)
        except ValueError:
            return raw


class TextMatchFacet(Facet):
    """Free-text substring filter facet (no aggregation buckets).

    Accepts a single filter value (plain string, no special syntax) and
    matches it as a case-insensitive substring against a ``keyword``
    field, via an OpenSearch ``wildcard`` query wrapping the value in
    ``*...*``. Intended for high-cardinality / near-unique fields
    (``filename``, ``title``, ``target``) where a checkbox facet's
    bucket list would be unusable, and where a simple exact-match
    ``TermsFacet`` would also be too restrictive for the user typing a
    fragment of the value.

    Not a fit for numeric fields (e.g. ``identifier``): OpenSearch
    ``wildcard`` queries require a keyword/text field, not an
    integer -- see the field's own facet decision in metadata.yaml.

    Registered per-field via the ``facet-def`` key in metadata.yaml,
    e.g.:

        filename:
          type: keyword
          facet-def:
            facet: models.fram.facets.TextMatchFacet

    Special wildcard characters (``*``, ``?``) typed by the user are
    escaped before being embedded in the wildcard query, so they are
    matched as literal characters rather than being interpreted as
    additional wildcards.
    """

    #: Not a browsable facet: apply the filter directly rather than via
    #: post_filter, since there is no bucket list depending on it.
    post_filter = False

    def __init__(self, field: Any = None, label: Any = None, **kwargs: Any) -> None:
        """Constructor. See ``RangeQueryFacet.__init__`` for rationale."""
        self._field = field
        self._label = label or ""
        super().__init__(label=label, **kwargs)

    def get_aggregation(self) -> Any:
        """Return a minimal aggregation (no buckets are displayed for this facet)."""
        return dsl.A("filter", dsl.Q("match_all"))

    def get_values(self, data: Any, filter_values: Any) -> dict:
        """This facet has no browsable bucket list."""
        return {"buckets": []}

    def get_labelled_values(self, data: Any, filter_values: Any) -> dict:
        """This facet has no browsable bucket list."""
        return {"buckets": [], "label": str(getattr(self, "_label", ""))}

    def add_filter(self, filter_values: list) -> Any:
        """Construct a wildcard substring query from plain string values."""
        if not filter_values:
            return None

        q = None
        for value in filter_values:
            rq = self._build_wildcard_query(value)
            if rq is None:
                continue
            q = rq if q is None else q | rq
        return q

    def _build_wildcard_query(self, value: str) -> Any:
        """Build a case-insensitive ``*value*`` wildcard query."""
        if not isinstance(value, str):
            return None

        value = value.strip()
        if not value:
            return None

        escaped = value.replace("\\", "\\\\").replace("*", "\\*").replace("?", "\\?")
        return dsl.Q(
            "wildcard",
            **{self._field: {"value": f"*{escaped}*", "case_insensitive": True}},
        )


class ExactMatchFacet(Facet):
    """Exact-match filter facet (no aggregation buckets).

    Accepts a single filter value (plain string) and matches it exactly
    (OpenSearch ``term`` query) against a ``keyword`` field. Intended
    for fields we don't fully own the mapping of -- e.g. ``title``,
    which comes from the CCMM/RDM preset (``RDMTitle``, type
    ``fulltext+keyword``) rather than our own metadata.yaml. That
    composite type generates a ``text`` field (``metadata.title``) plus
    a ``.keyword`` multi-field (``metadata.title.keyword``); an exact
    ``term`` query against the ``.keyword`` sub-field is a simpler,
    more robust operation than a ``wildcard`` query (see
    ``TextMatchFacet``) and is less likely to be affected if CESNET
    changes analyzer/mapping details of the composite type in a future
    update -- both still depend on the ``.keyword`` sub-field existing,
    but ``term`` has no dependency on wildcard/analyzer edge cases.

    Not registered via ``facet-def`` in metadata.yaml (title is not our
    field); instead injected directly into ``RecordFacets`` via
    ``AddToDictionary`` in model.py, the same pattern used for
    ``cone_search``.
    """

    #: Not a browsable facet: apply the filter directly rather than via
    #: post_filter, since there is no bucket list depending on it.
    post_filter = False

    def __init__(self, field: Any = None, label: Any = None, **kwargs: Any) -> None:
        """Constructor. See ``RangeQueryFacet.__init__`` for rationale."""
        self._field = field
        self._label = label or ""
        super().__init__(label=label, **kwargs)

    def get_aggregation(self) -> Any:
        """Return a minimal aggregation (no buckets are displayed for this facet)."""
        return dsl.A("filter", dsl.Q("match_all"))

    def get_values(self, data: Any, filter_values: Any) -> dict:
        """This facet has no browsable bucket list."""
        return {"buckets": []}

    def get_labelled_values(self, data: Any, filter_values: Any) -> dict:
        """This facet has no browsable bucket list."""
        return {"buckets": [], "label": str(getattr(self, "_label", ""))}

    def add_filter(self, filter_values: list) -> Any:
        """Construct an exact-match term query from plain string values."""
        if not filter_values:
            return None

        q = None
        for value in filter_values:
            rq = self._build_term_query(value)
            if rq is None:
                continue
            q = rq if q is None else q | rq
        return q

    def _build_term_query(self, value: str) -> Any:
        """Build an exact ``term`` query."""
        if not isinstance(value, str):
            return None

        value = value.strip()
        if not value:
            return None

        return dsl.Q("term", **{self._field: value})


class ConeSearchFacet(Facet):


    """Sky-position (cone) search facet -- round 1 (coarse HEALPix filter).

    Registered directly under the literal key ``"cone_search"`` in
    ``RecordFacets`` (via ``AddToDictionary`` in model.py), NOT through
    a ``facet-def`` in metadata.yaml -- there is no single field named
    "cone_search"; it's a virtual facet whose filter logic spans two
    real fields (``center.ra``/``center.dec`` at ingestion time,
    ``healpix_idx`` at query time).

    Filter value: a single JSON string ``'{"lat":.., "lon":.., "radius":..}'``
    matching what ``ConeSearchInputsComponent`` in CustomFilters.jsx sends
    (``lat`` = Dec, ``lon`` = RA remapped client-side to -180..180,
    ``radius`` = user's search radius in degrees).

    Query logic: computes every HEALPix pixel (NSIDE=``HEALPIX_NSIDE``)
    whose center lies within ``radius + MAX_FOV_RADIUS_DEG`` of the
    queried point (see module docstring for why the radius is widened),
    then issues a ``terms`` query against ``metadata.healpix_idx`` for
    that pixel set. This is deliberately a coarse, over-inclusive filter
    (may include false positives for records whose actual field of view
    does not reach the queried point) -- see the module docstring's
    "Phase 2" note for the planned ``footprint`` exact-containment
    follow-up query that would eliminate those false positives. Not
    having Phase 2 does NOT introduce false negatives; it only means
    result lists may occasionally include a few extra non-matching
    records near the edge of the search radius.
    """

    #: Not a browsable facet: apply the filter directly rather than via
    #: post_filter, since there is no bucket list depending on it.
    post_filter = False

    def __init__(self, field: str = "metadata.healpix_idx", label: Any = None, **kwargs: Any) -> None:
        """Constructor. ``field`` is the healpix_idx field to query against."""
        self._field = field
        self._label = label or ""
        super().__init__(label=label, **kwargs)

    def get_aggregation(self) -> Any:
        """Return a minimal aggregation (no buckets are displayed for this facet)."""
        return dsl.A("filter", dsl.Q("match_all"))

    def get_values(self, data: Any, filter_values: Any) -> dict:
        """This facet has no browsable bucket list."""
        return {"buckets": []}

    def get_labelled_values(self, data: Any, filter_values: Any) -> dict:
        """This facet has no browsable bucket list."""
        return {"buckets": [], "label": str(getattr(self, "_label", ""))}

    def add_filter(self, filter_values: list) -> Any:
        """Construct a `terms` query on healpix_idx from JSON cone-search values."""
        if not filter_values:
            return None

        q = None
        for value in filter_values:
            rq = self._build_cone_query(value)
            if rq is None:
                continue
            q = rq if q is None else q | rq
        return q

    def _build_cone_query(self, value: str) -> Any:
        """Parse a single JSON `{"lat":.., "lon":.., "radius":..}` value."""
        if not isinstance(value, str):
            return None

        try:
            params = json.loads(value)
            lat = float(params["lat"])
            lon = float(params["lon"])
            radius = float(params["radius"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None

        if radius < 0:
            return None

        # Widen the query radius so round-1 filtering can never produce
        # false negatives -- see module docstring.
        query_radius_deg = radius + MAX_FOV_RADIUS_DEG

        vec = hp.ang2vec(lon, lat, lonlat=True)
        pix_list = hp.query_disc(
            nside=HEALPIX_NSIDE,
            vec=vec,
            radius=np.radians(query_radius_deg),
        )

        if len(pix_list) == 0:
            # Degenerate query (e.g. radius so large it wraps the
            # whole sky would normally return everything, but an
            # empty result here means something went wrong upstream --
            # be safe and match nothing rather than everything).
            return dsl.Q("match_none")

        return dsl.Q("terms", **{self._field: [int(p) for p in pix_list]})
