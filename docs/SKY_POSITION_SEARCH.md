# Sky-position (cone) search — implementation summary for next chat

## Context

Repo: `invenio-fzu` (InvenioRDM/oarepo-model based). FRAM model:
`models/fram/model.py`, `models/fram/metadata.yaml`, `models/fram/facets.py`.
UI filters: `ui/fram/semantic-ui/js/fram/search/CustomFilters.jsx`.

Goal: let users search FRAM records by sky position — RA (deg), Dec (deg),
search Radius (deg) — i.e. "give me all images whose field-of-view center is
within `radius` degrees of (RA, Dec)".

## What already exists (done, working or partially working)

1. **`metadata.yaml`** already has the necessary fields:
   - `center.ra` / `center.dec` (float) — original equatorial coords (0–360 RA).
   - `center_geo` (object: `lat`, `lon`) — "shadow" field meant for a
     `geo_point` OpenSearch mapping. `lon` = RA remapped to −180..+180,
     `lat` = Dec unchanged. **Verify this remap is actually computed and
     populated at upload time** (see "Remaining steps" #1 below).
   - `healpix_idx` (int) — HEALPix NSIDE=64 pixel index of image center,
     intended as an integer fallback/facet for cone search
     (`healpy.query_disc` → list of pixel indices → `terms` query).
   - `footprint` (declared as `dynamic-object` in YAML, `searchable: false`)
     — GeoJSON polygon of image corners, for optional second-pass exact
     containment checking. Mapped to `geo_shape` (see below). NOT required
     for basic cone search — can be skipped/deferred.

2. **`model.py`** already has:
   ```python
   PatchIndexPropertyMapping(
       "metadata.center_geo",
       {"type": "geo_point", "properties": None, "dynamic": None},
   ),
   PatchIndexPropertyMapping(
       "metadata.footprint",
       {"type": "geo_shape", "properties": None, "dynamic": None, "ignore_above": None},
   ),
   ```
   These override oarepo's default `object`/`dynamic-object` mapping so
   `center_geo` becomes a real OpenSearch `geo_point` field (enables
   `geo_distance` queries) and `footprint` becomes `geo_shape`.
   **NOT YET VERIFIED against a real index build** — run `./run.sh reset`
   (or equivalent reindex) and inspect the generated mapping JSON /
   `GET <index>/_mapping` to confirm `center_geo` is actually typed
   `geo_point` and not silently still `object`.

3. **UI** already has `ConeSearchInputsComponent` in `CustomFilters.jsx`
   (RA/Dec/Radius text inputs, "Search"/"Clear" buttons). On submit it
   pushes a filter into react-searchkit's `currentQueryState.filters`:
   ```js
   filters: withFilter(
     currentQueryState.filters,
     "cone_search",
     JSON.stringify({ lat: decNum, lon, radius: radiusNum })
   )
   ```
   RA is already remapped to lon (−180..180) client-side. **This filter key
   (`"cone_search"`) is NOT a real metadata.yaml field** — it's a virtual
   facet name that needs a matching server-side facet registered under
   that exact name (see below). This part is NOT yet wired up server-side.

## Root-cause pattern learned this session (IMPORTANT — apply to cone search too)

Two silent-failure traps were hit and fixed for the (now-working)
altitude/azimuth/observation_night range facets — the cone search facet
will need the same two fixes applied preemptively:

1. **`field` must be explicit in the `facet-def` YAML block.**
   `oarepo_model`'s `get_basic_facet()` (in
   `oarepo_model/datatypes/base.py` → `oarepo_runtime/services/facets/utils.py`)
   only auto-fills `field`/`label` kwargs when `facet-def` is *absent*
   (default facet class path). When you supply a custom `facet-def`, ONLY
   the keys you explicitly write inside it are passed as constructor
   kwargs. So every `facet-def` block MUST look like:
   ```yaml
   facet-def:
     facet: models.fram.facets.SomeFacetClass
     field: metadata.some.field.path
     label:
       en: ...
       cs: ...
   ```
   Forgetting `field:` causes the facet's `self._field` to end up `None`,
   which surfaces later as `TypeError: keywords must be strings` (from
   `dsl.Q("range", **{None: ...})`) — a confusing error far from the real
   cause.

   **For cone search:** `cone_search` is a *virtual* facet — there is no
   single `metadata.yaml` field named `cone_search` to attach a
   `facet-def` to. It must instead be registered directly as a Python
   facet object in the `AddFacetGroup`/`SearchOptions.facets` dict under
   the literal key `"cone_search"` (see "Remaining steps" #2/#3 below),
   constructed with whatever kwargs it needs (e.g. no `field=`, or
   `field="metadata.center_geo"` if using geo_distance) directly in
   Python, not via YAML `facet-def` at all.

2. **A facet not present in the server's registered facets dict is
   silently ignored — no error, filter has zero effect.**
   `FacetsParam.apply()` / `GroupedFacetsParam.apply()` does:
   ```python
   for name, values in facets_values.items():
       if name in self.facets:
           self.add_filter(name, values)
   ```
   If `"cone_search"` (or whatever key the JSX sends) is not a key in
   `config.facets` (i.e. not registered anywhere — not via `metadata.yaml`
   `facet-def`, and not manually injected into the search options facets
   dict), the browser sends the request, server returns `200 OK`, but the
   filter has literally no effect and ALL records are returned — this is
   exactly the same silently-broken symptom seen with azimuth (still
   unresolved as of this writing — likely also an `AddFacetGroup`
   registration issue, see the open bug note in "Remaining steps" #5 below).

   **CRITICAL: also double check the exact request wire format.** In this
   session's debugging, the actual browser request for a working range
   filter looked like:
   ```
   GET /api/fram?q=&sort=newest&page=1&size=10&metadata.altitude_azimuth.altitude=2..4
   ```
   i.e. **NOT** `facets[metadata.altitude_azimuth.altitude]=2..4`. Confirm
   with real browser DevTools Network tab (or server access log — visible
   directly in the `./run.sh run` terminal output) what query param name
   react-searchkit actually sends for `filters` entries, and make sure the
   server-side facet key matches EXACTLY (including whether it's a bare
   field path or wrapped in `facets[...]`). This project's react-searchkit
   config apparently uses bare field-path params, not the `facets[...]`
   PHP-style array syntax assumed at the start of this session — don't
   assume, verify directly from a real request.

## Remaining steps (in recommended order)

1. **Verify `center_geo` mapping** is really `geo_point` in the live index
   (`./run.sh reset` or reindex, then check `GET <fram-index>/_mapping`).
   If it's still `object`, the `PatchIndexPropertyMapping` customization
   isn't taking effect as expected — investigate before writing any geo
   query code, since `geo_distance` will silently error or no-op on a
   non-geo_point field.

2. **Verify the upload/ingestion pipeline actually populates
   `center_geo` (lat/lon) and `healpix_idx` at record-creation time** from
   `center.ra`/`center.dec`. Search for the FITS-header-to-metadata
   conversion code (likely something like `fram_async_upload.py` or
   similar — grep for `healpix_idx` or `center_geo` assignment in
   Python source, not just metadata.yaml). Confirm:
   - RA remap formula: `lon = ra - 360 if ra > 180 else ra` (or equivalent)
   - `healpix_idx = healpy.ang2pix(nside=64, lon=ra, lat=dec, lonlat=True)`
     (nside=64 per the field's docstring, "0–49151" range mentioned in
     earlier session notes)
   - Both fields are `null` for calibration frames (dark/flat/bias) with
     no real sky position, consistent with the YAML docstrings.
   If this pipeline code doesn't populate these fields yet, existing
   records will have `null` there and cone search will return zero
   results even once the facet plumbing works — need to backfill/reindex
   existing sample records after fixing the pipeline.

3. **Write a `ConeSearchFacet` class** in `models/fram/facets.py`, e.g.:
   ```python
   class ConeSearchFacet(Facet):
       """Cone search: filter value is JSON '{"lat":.., "lon":.., "radius":..}'."""
       post_filter = False

       def __init__(self, field="metadata.center_geo", label=None, **kwargs):
           self._field = field
           self._label = label or ""
           super().__init__(label=label, **kwargs)

       def get_aggregation(self):
           return dsl.A("filter", dsl.Q("match_all"))

       def get_values(self, data, filter_values):
           return {"buckets": []}

       def get_labelled_values(self, data, filter_values):
           return {"buckets": [], "label": str(self._label)}

       def add_filter(self, filter_values):
           if not filter_values:
               return None
           import json
           q = None
           for value in filter_values:
               try:
                   params = json.loads(value)
                   lat = float(params["lat"])
                   lon = float(params["lon"])
                   radius = float(params["radius"])
               except (ValueError, KeyError, TypeError):
                   continue
               rq = dsl.Q(
                   "geo_distance",
                   distance=f"{radius}deg",
                   **{self._field: {"lat": lat, "lon": lon}},
               )
               q = rq if q is None else q | rq
           return q
   ```
   This uses `geo_distance` against `center_geo` (requires step 1 to be
   confirmed working). If step 1 turns out to be broken/blocked, fall back
   to a `healpix_idx` `terms` query instead (see alternative below) —
   this has zero dependency on the geo_point mapping and can be
   implemented today regardless of mapping status:
   ```python
   # Fallback / no geo_point dependency:
   import healpy as hp
   def add_filter(self, filter_values):
       ...
       pix_list = hp.query_disc(
           nside=64,
           vec=hp.ang2vec(lon, lat, lonlat=True),
           radius=np.radians(radius),
       )
       return dsl.Q("terms", **{"metadata.healpix_idx": pix_list.tolist()})
   ```
   Requires `healpy` (and `numpy`) as a dependency — check `pyproject.toml`
   and add if missing.

4. **Register the facet under the literal key `"cone_search"`** so it
   matches the JSX's filter key. This is a *virtual* field name with no
   corresponding `metadata.yaml` property, so it can't go through the
   normal `facet-def` YAML mechanism — it must be injected directly into
   the model's generated `SearchOptions.facets` dict in Python. Look at
   how `AddFacetGroup`/`build_facet` populate `config.facets` in
   `oarepo_model` to find the right customization primitive (there may be
   an `AddFacet` or similar in `oarepo_model.customizations` — check
   `from oarepo_model.customizations import ...` available names) to add
   a facet entry keyed `"cone_search"` -> `ConeSearchFacet(field=...)`
   directly, bypassing the YAML-driven facet-def mechanism entirely, e.g.
   something conceptually like:
   ```python
   AddFacet("cone_search", ConeSearchFacet(field="metadata.center_geo")),
   ```
   (exact customization class name needs verification against
   `oarepo_model.customizations` source — this session did not get to
   this step).

5. **Re-verify the request wire format** for `"cone_search"` matches
   what's actually sent (see the CRITICAL note above re: bare
   `field=value` vs `facets[field]=value`). Given the azimuth bug (still
   unresolved as of end of this session — filter silently ignored, no
   error, all records returned even after fixing the `field`/`label`
   YAML issue that fixed altitude), **there may be a second, still-unknown
   bug** affecting some filters but not others (altitude reportedly works,
   azimuth doesn't, despite identical JSX code (`makeRangeFilter` factory)
   and identical YAML structure). Suspect candidates to check first in the
   next session, in order of likelihood:
   - `AddFacetGroup`'s `facets=[...]` list does NOT currently include
     either `metadata.altitude_azimuth.altitude` or
     `.azimuth` (confirmed by reading `model.py`) — yet altitude reportedly
     works and azimuth doesn't. This is contradictory and unresolved.
     Check whether `GroupedFacetsParam.identity_facets()` /
     `_filter_user_facets()` behaves differently between the two
     sub-fields of the same `altitude_azimuth` object — e.g. maybe there's
     a caching issue, a duplicate facet registration under one of the two
     names that shadows the correct one, or the object-type parent
     (`altitude_azimuth`) generates its OWN facet entry that collides with
     the two child facets.
   - Check for typos/case-sensitivity in the exact literal string key used
     server-side vs the `filterKey` string in `AzimuthFilter` in JSX
     (`"metadata.altitude_azimuth.azimuth"`).
   - Confirm with a fresh incognito browser session + DevTools Network tab
     the *exact* request URL sent for azimuth vs altitude side-by-side, to
     rule out any client-side state/caching artifact.
   Once this azimuth mystery is solved, apply the same fix pattern
   (whatever it turns out to be) preemptively to the new `cone_search`
   facet registration to avoid hitting the same bug a third time.

6. **End-to-end test**: upload/verify a sample record with known
   RA/Dec/center_geo/healpix_idx, then query cone search with a radius
   that should/shouldn't include it, confirm correct filtering both ways.

## Cost/efficiency note for next session

Don't re-derive the `field`/`label` YAML `facet-def` gotcha or the
silent-ignore-if-not-in-facets-dict behavior — both are now confirmed
root causes, documented above with fixes. Focus new session budget on
steps 1, 2, 4, and 5 (the azimuth mystery) — those are the genuinely
unresolved unknowns.
