"""Custom facets for the Atlas ITk model.

``TextMatchFacet`` implements a free-text substring filter (no
aggregation buckets) for high-cardinality array-of-keyword fields
(``components``, ``component_types``, ``files``) where a checkbox
facet bucket list would be unusable (potentially thousands of
distinct values, one per component/file). The user types a fragment
and it's matched as a case-insensitive substring via an OpenSearch
``wildcard`` query.

Note: ``wildcard`` queries against an ``array`` field with ``keyword``
items work the same way as against a plain ``keyword`` field --
OpenSearch/Lucene indexes each array element as a separate value in
the same inverted-index field, and a ``wildcard`` query matches if
ANY indexed value matches the pattern.

Registered per-field via the ``facet-def`` key in metadata.yaml, e.g.:

    components:
      type: array
      items:
        type: keyword
      facet-def:
        facet: models.atlas_itk.facets.TextMatchFacet
        field: metadata.components
        label:
          en: Component
          cs: Komponenta

This mirrors the identical ``TextMatchFacet`` implementation in
``models/fram/facets.py`` (filename/target fields) and
``models/sipm/facets.py`` (tray_numbers/qr_list) -- kept as a separate
per-model copy rather than a shared import, consistent with how each
model in this repository owns its own facets module.
"""

from __future__ import annotations

from typing import Any

from invenio_records_resources.services.records.facets import Facet
from invenio_search.engine import dsl


class TextMatchFacet(Facet):
    """Free-text substring filter facet (no aggregation buckets).

    Accepts a single filter value (plain string, no special syntax) and
    matches it as a case-insensitive substring against a ``keyword``
    (or array-of-``keyword``) field, via an OpenSearch ``wildcard``
    query wrapping the value in ``*...*``.

    Special wildcard characters (``*``, ``?``) typed by the user are
    escaped before being embedded in the wildcard query, so they are
    matched as literal characters rather than being interpreted as
    additional wildcards.
    """

    #: Not a browsable facet: apply the filter directly rather than via
    #: post_filter, since there is no bucket list depending on it.
    post_filter = False

    def __init__(self, field: Any = None, label: Any = None, **kwargs: Any) -> None:
        """Constructor.

        Stores ``field``/``label`` as instance attributes (mirroring
        ``oarepo_runtime``'s ``DateFacet``), since the base ``dsl.Facet``
        only stores kwargs it explicitly recognizes.
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
