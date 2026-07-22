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
"""

from __future__ import annotations

from typing import Any

from invenio_records_resources.services.records.facets import Facet
from invenio_search.engine import dsl


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
