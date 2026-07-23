"""Custom facets for the Particles (Delphi) model.

``EnergyRangeOverlapFacet`` implements a "collision energy" range filter
over ``collision_information.energy_min``/``energy_max`` -- a pair of
fields representing the *record's own* energy range (e.g. a dataset
covering "5-15 TeV"), rather than a single value.

Unlike FRAM's ``RangeQueryFacet`` (models/fram/facets.py), which applies
a user-supplied "min..max" range directly as an OpenSearch ``range``
query against a single numeric field, this facet is a *virtual* facet
spanning two real fields, and uses "overlap" (interval intersection)
semantics rather than a plain range comparison:

    a record matches the user's query range [qmin, qmax] iff
    the record's own range [energy_min, energy_max] intersects it,
    i.e.:   energy_min <= qmax   AND   energy_max >= qmin

(Either bound of the query may be omitted for an open-ended query,
exactly as with ``RangeQueryFacet``'s "min.." / "..max" syntax; the
corresponding half of the overlap condition is then simply dropped.)

This was a deliberate choice (see docs/discussion in this session):
a "containment" interpretation (record's range must *fully cover* the
query range) was considered and rejected as less intuitive/less useful
for a physicist searching for datasets in a given collision energy
range -- "overlap" is the standard, expected behaviour for range
filters (as with e.g. filtering events by time window or price range).

Registered as a *virtual* facet (like FRAM's ``cone_search`` /
``metadata.title``) via ``AddToDictionary("RecordFacets", {...})`` in
model.py, under the key ``"metadata.collision_information.energy_range"``
-- there is no single metadata.yaml field to attach a ``facet-def`` to,
since the filter logic spans two real fields.

``RangeQueryFacet`` (used here for ``number_of_events``) and
``TextMatchFacet`` (used here for ``title``) are copied verbatim from
``models/fram/facets.py`` (same implementation, no cross-model import,
consistent with how each model keeps its own self-contained
``facets.py`` -- see that module's docstrings for the full rationale of
each).

``DatesTypeRangeFacet`` implements a min/max date-range filter over the
RDM/CCMM ``metadata.dates`` field -- an array of ``{date, type, ...}``
objects (see ``oarepo_rdm``'s ``RDMDates``/``RDMDate`` element) -- date range
selection is restricted to entries whose ``type.id`` matches a given
vocabulary id (``"Created"`` for the Particles model's "created date"
filter, since Particles' `dates` is populated as `[{"date":
creation_date, "type": {"id": "Created"}}]`, mirroring FRAM's
``fram_async_upload.py`` population pattern).

This uses a **plain bool** query (``range`` on ``metadata.dates.date``
AND ``term`` on ``metadata.dates.type.id``), NOT a ``nested`` query --
``metadata.dates`` is mapped as a plain OpenSearch ``object`` (array of
objects flattened by field, not "nested" document type), so a plain
bool AND risks "cross-object matching" (i.e. could technically match a
record where *some* array entry has the right date and a *different*
array entry has the right type). This is an accepted, deliberate
simplification for now: in practice, both Particles and FRAM only ever
populate a single ``dates`` entry (type ``"Created"``), so there is no
other entry to "leak" a false-positive match with. If a model's
``dates`` array grows to include multiple heterogeneous entries (e.g.
"Collected", "Valid", "Created" all populated together), this facet
would need to be upgraded to a real OpenSearch ``nested`` query (which
requires ``metadata.dates`` to be mapped with ``"type": "nested"`` via
``PatchIndexPropertyMapping``, see FRAM's ``center_geo``/``footprint``
mapping overrides in ``models/fram/model.py`` for the pattern) to stay
fully correct.
"""

from __future__ import annotations

from typing import Any

from invenio_records_resources.services.records.facets import Facet
from invenio_search.engine import dsl


class EnergyRangeOverlapFacet(Facet):
    """Collision-energy range filter using interval-overlap semantics.

    Accepts a single filter value of the form ``"min..max"`` (either
    bound may be omitted), and matches records whose own
    ``energy_min``/``energy_max`` range overlaps the queried range.
    """

    #: Not a browsable facet: apply the filter directly rather than via
    #: post_filter, since there is no bucket list depending on it.
    post_filter = False

    def __init__(
        self,
        min_field: str = "metadata.collision_information.energy_min",
        max_field: str = "metadata.collision_information.energy_max",
        label: Any = None,
        **kwargs: Any,
    ) -> None:
        """Constructor.

        ``min_field``/``max_field`` are the two real fields this virtual
        facet spans. See ``RangeQueryFacet.__init__`` (models/fram/facets.py)
        for why ``field``-like kwargs must be stored explicitly here
        rather than relying on the base ``dsl.Facet``/``self._params``,
        and why ``self._label`` must be set explicitly as well (the UI
        template accesses ``facet._label`` directly).
        """
        self._min_field = min_field
        self._max_field = max_field
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
        """Construct an overlap filter query from "min..max" style values."""
        if not filter_values:
            return None

        q = None
        for value in filter_values:
            rq = self._build_overlap_query(value)
            if rq is None:
                continue
            q = rq if q is None else q | rq
        return q

    def _build_overlap_query(self, value: str) -> Any:
        """Parse a single "min..max" value and build an overlap dsl.Q.

        Overlap condition: ``energy_min <= qmax AND energy_max >= qmin``.
        If ``qmax`` is omitted, only the second clause applies (and vice
        versa); if both are omitted, no filter is applied for this value.
        """
        if not isinstance(value, str):
            return None

        value = value.strip()
        if not value:
            return None

        if ".." in value:
            start_raw, _, end_raw = value.partition("..")
        else:
            # single value: treat as a zero-width query range [v, v]
            start_raw = end_raw = value

        start_raw = start_raw.strip()
        end_raw = end_raw.strip()

        qmin = self._coerce(start_raw) if start_raw else None
        qmax = self._coerce(end_raw) if end_raw else None

        if qmin is None and qmax is None:
            return None

        clauses = []
        if qmax is not None:
            # record's energy_min must not exceed the query's upper bound
            clauses.append(dsl.Q("range", **{self._min_field: {"lte": qmax}}))
        if qmin is not None:
            # record's energy_max must not be below the query's lower bound
            clauses.append(dsl.Q("range", **{self._max_field: {"gte": qmin}}))

        q = clauses[0]
        for c in clauses[1:]:
            q = q & c
        return q

    @staticmethod
    def _coerce(raw: str) -> Any:
        """Coerce a raw string bound to float if possible, else leave as string."""
        try:
            return float(raw)
        except ValueError:
            return raw


class RangeQueryFacet(Facet):
    """Arbitrary min/max range filter facet (no aggregation buckets).

    Accepts filter values of the form ``"min..max"``, ``"min.."``, or
    ``"..max"``. Values are passed through as-is to the OpenSearch range
    query (works for both numeric fields and lexicographically-sortable
    keyword strings).

    Copied verbatim from ``models/fram/facets.py`` (see that module's
    docstring for the full rationale); used here for
    ``metadata.number_of_events``.
    """

    #: Not a browsable facet: apply the filter directly rather than via
    #: post_filter, since there is no bucket list depending on it.
    post_filter = False

    def __init__(self, field: Any = None, label: Any = None, **kwargs: Any) -> None:
        """Constructor. See ``EnergyRangeOverlapFacet.__init__`` for rationale."""
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
    ``*...*``.

    Copied verbatim from ``models/fram/facets.py`` (see that module's
    docstring for the full rationale); used here for ``metadata.title``.
    Not registered via ``facet-def`` in metadata.yaml (``title`` is not
    our field, it comes from the CCMM/RDM preset); instead injected
    directly into ``RecordFacets`` via ``AddToDictionary`` in model.py.

    Special wildcard characters (``*``, ``?``) typed by the user are
    escaped before being embedded in the wildcard query, so they are
    matched as literal characters rather than being interpreted as
    additional wildcards.
    """

    #: Not a browsable facet: apply the filter directly rather than via
    #: post_filter, since there is no bucket list depending on it.
    post_filter = False

    def __init__(self, field: Any = None, label: Any = None, **kwargs: Any) -> None:
        """Constructor. See ``EnergyRangeOverlapFacet.__init__`` for rationale."""
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


class DatesTypeRangeFacet(Facet):
    """Date-range filter over ``metadata.dates``, restricted to one date type.

    ``metadata.dates`` (RDM/CCMM's ``RDMDates``/``RDMDate`` element) is
    an array of ``{date, type: {id}, description}`` objects. This facet
    filters records whose *matching-typed* entry (``type.id ==
    type_id``, e.g. ``"Created"``) has a ``date`` falling within a
    user-supplied ``"min..max"`` range (either bound may be omitted --
    same convention as ``RangeQueryFacet``/``EnergyRangeOverlapFacet``).

    Query shape: plain ``bool`` with ``must: [range on date_field, term
    on type_field]`` -- NOT an OpenSearch ``nested`` query. See this
    module's top-of-file docstring ("cross-object matching" section)
    for why this is an accepted simplification given current data
    (single-entry ``dates`` arrays), and what would need to change if
    that assumption stops holding.
    """

    #: Not a browsable facet: apply the filter directly rather than via
    #: post_filter, since there is no bucket list depending on it.
    post_filter = False

    def __init__(
        self,
        date_field: str = "metadata.dates.date",
        type_field: str = "metadata.dates.type.id",
        type_id: str = "Created",
        label: Any = None,
        **kwargs: Any,
    ) -> None:
        """Constructor.

        ``date_field``/``type_field`` are the two real sub-fields of
        ``metadata.dates`` this virtual facet spans; ``type_id`` is the
        vocabulary id (e.g. ``"Created"``) an entry's ``type.id`` must
        equal for its ``date`` to be checked against the query range.
        See ``EnergyRangeOverlapFacet.__init__`` (this module) for why
        these must be stored explicitly rather than relying on the base
        ``dsl.Facet``/``self._params``.
        """
        self._date_field = date_field
        self._type_field = type_field
        self._type_id = type_id
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
        """Construct a typed date-range filter query from "min..max" style values."""
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
        """Parse a single "min..max" value and build the combined dsl.Q.

        The ``date`` sub-field is an EDTF/date string (e.g.
        ``"2024-03-19"``); bounds are passed through as plain strings
        (no int/float coercion, unlike ``RangeQueryFacet``), since
        OpenSearch's ``date`` field type parses ISO date strings
        natively in a ``range`` query.
        """
        if not isinstance(value, str):
            return None

        value = value.strip()
        if not value:
            return None

        if ".." in value:
            start_raw, _, end_raw = value.partition("..")
        else:
            # single date: exact match via range (gte == lte)
            start_raw = end_raw = value

        start_raw = start_raw.strip()
        end_raw = end_raw.strip()

        es_range: dict[str, Any] = {}
        if start_raw:
            es_range["gte"] = start_raw
        if end_raw:
            es_range["lte"] = end_raw

        if not es_range:
            return None

        range_q = dsl.Q("range", **{self._date_field: es_range})
        type_q = dsl.Q("term", **{self._type_field: self._type_id})
        return range_q & type_q
