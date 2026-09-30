# Default search fields (`SetDefaultSearchFields`) — how it works, and the integer-field trap

## 1. What this is

Each model's search page has a plain search box (the one at the top of
`https://127.0.0.1:5000/<model>/`) that lets a user type a bare term
(e.g. `cta-n`) with no field qualifier and get matches across several
"default" fields, without needing to type `metadata.site:cta-n`.

This document explains how that default-field list is configured, how
it is applied to OpenSearch, and a subtle but serious trap discovered
while debugging FRAM's default search returning **zero results for
everything** (while Particles' equivalent search worked fine).

---

## 2. How it is implemented

Each model's `model.py` customizes it via `oarepo_model`'s
`SetDefaultSearchFields`, e.g. `models/fram/model.py`:

```python
SetDefaultSearchFields(
    "metadata.title",
    "metadata.description",
    "metadata.subjects.subject",
    "metadata.creators.person_or_org.name",
    "metadata.contributors.person_or_org.name",
    "metadata.experiment.id",
    "metadata.identifier.keyword",
    "metadata.target",
    "metadata.type",
    "metadata.related_resources",
    "metadata.site",
    "metadata.ccd",
    "metadata.camera_serial",
    "metadata.filter",
    "metadata.binning",
    "metadata.file_types",
    "metadata.filename",
),
```

Under the hood (`oarepo_model.customizations.high_level.add_search_fields.SetDefaultSearchFields`,
which subclasses `PatchIndexSettings`), this list is written verbatim
into the OpenSearch index setting `index.query.default_field` in the
model's generated mapping/settings JSON.

When a user submits an unqualified query (`?q=cta-n`, no field
prefix), Invenio's `QueryParser`
(`invenio_records_resources.services.records.queryparser.query.QueryParser`)
builds a single OpenSearch `query_string` DSL query with no explicit
`fields` argument. OpenSearch then expands that query across **every**
field listed in `index.query.default_field` — i.e. all the fields in
`SetDefaultSearchFields` are combined into one query, not queried
independently.

**Important operational note**: `index.query.default_field` is only
baked into the mapping/settings JSON that gets applied when an index
is **created**. Editing `SetDefaultSearchFields` in `model.py` and
just restarting the dev server does **not** update an already-existing
OpenSearch index — the old field list stays live until the index is
recreated (`./run.sh reset`, or another index-recreation step).

---

## 3. The integer-field trap (root cause of FRAM's broken default search)

### Symptom

FRAM's plain search box returned **zero results for every query**,
even for obviously-present values like `cta-n` (a `site` keyword
value). Particles' equivalent search worked fine. Someone had already
worked around it by removing `metadata.identifier` from FRAM's
`SetDefaultSearchFields` list — which stopped the crash but also
silently dropped identifier from default search entirely (a feature
regression, not a real fix).

### Root cause

`metadata.identifier` in `models/fram/metadata.yaml` is declared:

```yaml
identifier:
  type: int
  mapping:
    type: integer
    fields:
      keyword:
        type: keyword
```

i.e. a bare `integer`-mapped field (with a `.keyword` sub-field
available, but not used by default). When a bare integer field is
included in `index.query.default_field` (or any `query_string`
`fields` list) and the search term is **not** purely numeric,
OpenSearch throws a `number_format_exception`, e.g.:

```
POST physica-fram-metadata-v1.0.0-.../_search
{"query":{"query_string":{"query":"cta-n","fields":["metadata.site","metadata.identifier"]}}}

→ "number_format_exception","reason":"For input string: \"cta-n\""
```

Because `query_string` combines all `default_field` entries into a
**single** query, this exception fails the **entire** query — not just
the identifier portion — so a search for `cta-n` (which should have
matched via `metadata.site`) returned nothing at all. This is why
"default search finds nothing" affected every term, not just numeric
ones.

### The fix

Reference the field's `.keyword` sub-field instead of the bare integer
field:

```python
"metadata.identifier.keyword",   # NOT "metadata.identifier"
```

This was verified live: `metadata.identifier.keyword` in the `fields`
list does not throw on non-numeric terms (returns 0 hits, no error),
and a numeric term still correctly matches against it.

This is exactly the pattern **Particles already used** for its own
`int` fields (`models/particles/model.py`):

```python
"metadata.recid.keyword",
"metadata.number_of_events.keyword",
```

— which is why Particles' default search never exhibited this bug.

---

## 4. Rule of thumb / checklist for `SetDefaultSearchFields`

When adding or auditing entries in any model's `SetDefaultSearchFields(...)`:

1. **Never list a bare `int`/`float`-mapped field.** If the
   `metadata.yaml` field has `type: int` (or a custom
   `mapping: {type: integer, ...}` / `type: float`), and you want it
   searchable via the plain search box, either:
   - reference its `.keyword` sub-field if one exists (e.g.
     `metadata.identifier.keyword`), or
   - add a `keyword` sub-field mapping to the field if it doesn't
     already have one, or
   - leave it out of default search entirely (it will still be
     targetable via an explicit field-qualified query, e.g.
     `metadata.identifier:241`) if a keyword form doesn't make sense.
2. Plain `keyword` and `fulltext`/`text` fields (`metadata.site`,
   `metadata.title`, `metadata.filename`, etc.) are safe to list
   directly — no `.keyword` suffix needed/available issue for those.
3. After changing the list, **recreate the index**
   (`./run.sh reset`, or an equivalent index-recreation step) — a
   plain dev-server restart will not pick up the change on an
   existing index.
4. Verify with a quick manual check against OpenSearch directly
   (bypasses the app layer, isolates mapping/settings issues):
   ```bash
   curl -s http://127.0.0.1:<opensearch_port>/physica-<model>-metadata-v<version>-*/_settings?pretty
   ```
   confirm the new field appears correctly (with `.keyword` where
   needed) under `index.query.default_field`, then try both a
   non-numeric and numeric `query_string` search against it before
   trusting the app-level `/api/<model>?q=...` search box result.

---

## 5. Files touched by this investigation/fix

- `models/fram/model.py` — `SetDefaultSearchFields(...)` re-adds
  `metadata.identifier.keyword` (previously just `metadata.identifier`,
  which was removed entirely as a workaround for the crash described
  above), plus an inline comment explaining the trap for future
  editors.
- `models/particles/model.py` — unchanged; already used the correct
  `.keyword`-suffixed pattern for its own `int` fields, used here as
  the reference example.
