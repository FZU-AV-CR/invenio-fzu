# Technical handoff: interactive FITS viewer (Stretch/Scale/Zoom controls)

> **STATUS UPDATE (fitsview 2 round): implemented.** The interactive
> Stretch/Scale/Zoom/Grid toolbar described below has been built — see
> `docs/FITS_VIEWER_V2_SUMMARY.md` for what shipped, what changed vs.
> this document's original (screenshot-based) assumptions once the real
> fram.fzu.cz source (`fram-archive` Django app) and a stakeholder email
> exchange became available, and what remains deferred (Raw-toggle pixel
> calibration, "Processed FITS" download, linearization tables). The
> rest of this document is kept for historical/investigative reference
> (e.g. the "Gotchas already hit" section is still accurate), but treat
> `FITS_VIEWER_V2_SUMMARY.md` as authoritative for current parameter
> semantics (they differ from what's written below in a few places,
> notably `scale`'s asymmetric qmin/qmax semantics and `zoom` being real
> server-side crop+pan rather than a no-op).

**Audience**: a future chat/session implementing client-side interactive
controls (Stretch/Scale/Zoom dropdowns, grid/invert toggles, etc.) for the
FRAM FITS image preview, matching the fram.fzu.cz archive's viewer
toolbar. This document exists so that session does not need to re-run the
codebase investigation already completed for the static preview (see
`docs/FITS_IMAGE_PREVIEW.md` for the full design/rationale of what
already exists) — read that document first, then this one for the
specific technical details relevant to building the *dynamic* layer on
top.

**Read this whole document before writing any code.** Section 6
("Gotchas already hit") in particular documents real bugs already
diagnosed and fixed once — do not rediscover them.

## 0. Quick reference

| Thing | Where |
|---|---|
| FITS→JPEG rendering | `ui/fram/preview.py` — `render_fits_preview(fileobj, stretch=, scale=, zoom=)` |
| Disk cache | `ui/fram/preview_cache.py` — `get_or_render_preview(checksum, stretch, scale, zoom, render_fn)` |
| Preview HTTP endpoint | `ui/fram/views.py` — `fits_preview_view(pid_value)`, route `GET /fram/records/<pid_value>/preview/fits-image.jpg` (Flask endpoint name `fram_ui.fits_preview`) |
| Route registration | `ui/fram/__init__.py` — `create_blueprint(app)`, direct `blueprint.add_url_rule(...)` call |
| Template hook (current) | `ui/fram/templates/semantic-ui/fram/record_detail/main.html` — `record_files` block override |
| Template hook (for JS bundle, not yet created) | `ui/fram/templates/semantic-ui/fram/record_detail/javascript.html` |
| Webpack entries | `ui/fram/webpack.py` |
| Existing JS/JSX for this model | `ui/fram/semantic-ui/js/fram/{search,forms}/` |
| Design rationale + decisions log | `docs/FITS_IMAGE_PREVIEW.md` |
| Sample FITS file for testing | `sample_data/Fram/20260304093525-219-RA.fits` |

## 1. What already exists (do not re-implement)

- `ui/fram/preview.py`: `render_fits_preview(fileobj, stretch=, scale=,
  zoom=)` — pure function, FITS bytes → JPEG bytes. Already accepts and
  validates all three parameters against allow-lists (see
  `STRETCH_FUNCTIONS`, `SCALE_PERCENTILES`, `ZOOM_LEVELS` dicts/sets in
  that file). Unknown values log a warning and fall back to the default
  rather than raising — this means the backend is **already safe to call
  with arbitrary/malformed query params** from a not-yet-fully-tested
  frontend; you do not need to add extra validation in the view layer.
  **`zoom` is currently a documented no-op** (accepted, validated, but
  never actually changes the rendered image) — implementing real zoom is
  new work, see section 4.
- `ui/fram/preview_cache.py`: disk cache keyed on
  `sha256(f"{checksum}:{stretch}:{scale}:{zoom}")`. Adding new
  stretch/scale/zoom combinations automatically gets its own cache
  bucket — no cache-related changes needed when wiring up the dropdowns,
  *unless* you change what "zoom" means (see section 4, which would
  require the cache key scheme to actually matter, since right now zoom
  is a no-op the key doesn't visually affect anything).
- `ui/fram/views.py`: `fits_preview_view(pid_value)` — reads `stretch`,
  `scale`, `zoom` from `request.args` (with defaults), already wired
  end-to-end. **No backend changes needed to support new dropdown values
  that use the already-implemented stretch/scale options** — just start
  passing `?stretch=log&scale=99` etc. as query string params on the
  `<img>` src (or via `fetch`, see section 3).
- `ui/fram/templates/semantic-ui/fram/record_detail/main.html`: overrides
  the `record_files` Jinja block to conditionally emit:
  ```html
  <img class="ui fluid image fits-preview-image"
       src="{{ url_for('fram_ui.fits_preview', pid_value=record_ui['id']) }}"
       alt="{{ _('FITS image preview') }}" loading="lazy" />
  ```
  wrapped in `<section id="record-fits-preview" ...>`, only when exactly
  one completed `.fits`/`.fit` file is visible to the current user
  (server-side check, see `docs/FITS_IMAGE_PREVIEW.md` for the full
  two-layer permission logic). **This `<section id="record-fits-preview">`
  is the mount point you should target** for injecting a React toolbar
  next to/replacing the plain `<img>` (see section 3 for how other
  React-in-Jinja integrations in this codebase do this).

## 2. The full fram.zu.cz toolbar this feature is ultimately targeting

(Reconstructed from screenshots reviewed during the static-preview
design phase — not currently implemented anywhere in this codebase.)

- **Stretch** dropdown: linear / asinh / log / sqrt / sinh / power — all
  six already implemented server-side in `preview.py`'s
  `STRETCH_FUNCTIONS` dict (values map to `astropy.visualization`
  stretch classes: `LinearStretch`, `AsinhStretch`, `LogStretch`,
  `SqrtStretch`, `SinhStretch`, `PowerStretch(2.0)` — note `PowerStretch`
  needs a positional exponent argument, hardcoded to `2.0` in
  `_resolve_stretch()`; if the UI ever needs a variable exponent, that
  function's signature will need to grow a parameter).
- **Scale** dropdown: percentile interval — already implemented as
  `"95"`, `"99"`, `"99.5"`, `"99.9"` in `SCALE_PERCENTILES`. fram.fzu.cz's
  actual dropdown labels/values are not confirmed 1:1 against these keys
  (they were inferred from typical astronomy-viewer conventions) — if the
  real fram.fzu.cz UI uses different scale semantics (e.g. min/max
  z-scale, sigma-clipping), that would be a `preview.py` change, not just
  a frontend change.
- **Zoom** dropdown: x1 through x32 — accepted as a string in
  `ZOOM_LEVELS = {"1","2","4","8","16","32"}` but **completely
  unimplemented** — always renders full-resolution regardless of value.
  See section 4 for what actually needs to be built.
- Grid / invert icon toggles — not represented anywhere yet, neither
  backend nor frontend. Likely a pure client-side CSS filter
  (`filter: invert(1)`) for invert, and an SVG/CSS overlay grid — no
  server-side rendering changes anticipated, but not investigated in
  detail.
- Below the image: **Full-size image / Raw image / Download FITS /
  Processed FITS** links, and a metadata table (Id, Filename, Dark, Flat,
  Time, Night). Our existing `record_detail/main.html` metadata table
  already exposes filename/observation time/observation night/etc.
  (see that file's `record_content` block override) — "Dark"/"Flat" are
  not currently modeled in `metadata.yaml` at all (would need a
  metadata-model change, out of scope for a purely client-side viewer
  feature). "Download FITS" already exists implicitly via the standard
  Invenio file-list-box UI (rendered by `{{ super() }}` in the
  `record_files` block before our preview `<section>`). "Raw image" most
  likely maps directly to our new `/preview/fits-image.jpg` endpoint
  itself (already exists) or a `?zoom=1` full-res variant of it.
  "Processed FITS" has no clear existing analog — clarify requirements
  with stakeholders before assuming it needs new backend work.

## 3. How to add a React island to the record detail page (patterns already in this repo)

This repo has **two different existing patterns** for mounting React
components onto a server-rendered Jinja page. Both are viable for the
Stretch/Scale/Zoom toolbar; pick based on whether react-searchkit
integration is needed (it is not, for this feature) — pattern (a) below
is the simpler, more directly applicable one.

**(a) Plain "data-attribute div + manual ReactDOM.render" pattern** — used
by `ui/components/semantic-ui/js/record-management/index.js` /
`RecordManagement.jsx` for the sidebar "manage record" menu. This is the
closest existing analog to what the FITS viewer needs:

1. In the Jinja template (`main.html`'s `record_files` override), instead
   of (or alongside) the plain `<img>`, render an empty mount `<div>` with
   the data needed by React baked in as JSON `data-*` attributes, e.g.:
   ```html
   <div id="fitsPreviewViewer"
        data-preview-url="{{ url_for('fram_ui.fits_preview', pid_value=record_ui['id']) }}"
        data-stretch-options='["linear","asinh","log","sqrt","sinh","power"]'
        data-scale-options='["95","99","99.5","99.9"]'
        data-zoom-options='["1","2","4","8","16","32"]'>
   </div>
   ```
   (Mirrors `templates/manage_menu.html`'s
   `<div id="recordManagementMenu" data-record='{{ record_ui | tojson }}' ...>`
   pattern exactly — use `| tojson` for structured data, not manual
   `json.dumps` string interpolation, to get correct HTML-escaping.)
2. Add a new webpack entry in `ui/fram/webpack.py`'s `entry={...}` dict,
   e.g. `"fram_fits_viewer": "./js/fram/preview/index.js"`, and create
   `ui/fram/semantic-ui/js/fram/preview/index.js` +
   `FitsPreviewViewer.jsx` (new directory, following the existing
   `js/fram/search/` and `js/fram/forms/` sibling directory convention).
   The `index.js` entry point looks up
   `document.getElementById("fitsPreviewViewer")`, reads the
   `data-*` attributes, and calls `ReactDOM.render(<FitsPreviewViewer ... />, mountDiv)` —
   copy the `if (mountDiv) { ... }` guard pattern from
   `record-management/index.js` so the bundle is a no-op on pages without
   the mount point.
3. Include the new bundle by creating
   `ui/fram/templates/semantic-ui/fram/record_detail/javascript.html`
   (this override point **does not exist yet** for FRAM — verified by
   checking `find ui/fram/templates -name javascript.html`, only the
   generic scaffold comment in `record_detail.html` references it) with:
   ```html
   {{ webpack["fram_fits_viewer.js"] }}
   ```
   This is picked up automatically by
   `oarepo_ui/record_detail.html`'s `{%- block javascript %} ...
   {% include model_name ~ "/record_detail/javascript.html" ignore missing %}
   {%- endblock javascript %}` — no other wiring needed.
4. **React version note**: this repo uses the React 17-style
   `import ReactDOM from "react-dom"; ReactDOM.render(<X/>, el)` API (see
   both `record-management/index.js` and all four models'
   `forms/index.js` — none use React 18's `createRoot`). Follow the same
   API for consistency unless there's a deliberate reason to upgrade.

**(b) react-searchkit `componentOverrides` pattern** — used for
`ResultsListItem`/`CustomFilters` on the *search* page (see
`ui/fram/semantic-ui/js/fram/search/index.js`,
`docs/CUSTOM_FILTERS_HOWTO.md`). **Not applicable here** — this pattern
is specifically for overriding named slots inside react-searchkit's
`SearchApp` component tree (facets, result list items), which only
exists on the search page, not the record detail page. Do not try to
force the FITS viewer through this mechanism.

**Webpack/build notes**:
- `ui/fram/webpack.py` uses `WebpackThemeBundle` with an `aliases`
  dict (`"@js/fram": "./js/fram"`) — new files under
  `ui/fram/semantic-ui/js/fram/preview/` are importable elsewhere as
  `@js/fram/preview/...` if ever needed (mirrors how
  `ui/fram/__init__.py`'s `search_component` references
  `"@js/fram/search/ResultsListItem"`).
- After adding a new webpack entry, assets need to be rebuilt via the
  same asset pipeline used for existing entries — check `.runner.sh` for
  the `assets`/`build` subcommand (search for `webpack` or `assets_path`
  in that script) rather than assuming a specific command; it was not
  re-verified during this investigation.

## 4. Implementing real Zoom support

`zoom=` is currently accepted end-to-end (query param → cache key →
rendering call) but semantically a no-op — `render_fits_preview()` never
resamples or crops based on it. Two fundamentally different approaches,
pick based on actual UX requirements (not decided yet):

**(a) "Zoom = client-side CSS/JS zoom of the full-resolution JPEG"** —
simplest, no backend changes at all. The full JPEG rendered at `zoom=1`
(current behavior, e.g. 4144×4127px for the sample file) is already
larger than any reasonable display size, so a JS pan/zoom library
(e.g. wrapping the `<img>` in a CSS `transform: scale(...)` +
drag-to-pan, or a small library like `panzoom`/`react-zoom-pan-pinch`) can
provide the x1–x32 zoom experience entirely client-side against the one
already-cached image. **Recommended starting point** — avoids all
server-side complexity below, and the existing `preview.py`/cache
contract does not need to change (the `zoom` param could even be dropped
from the backend entirely, or kept purely for forward-compatibility/URL
bookmarking of a zoom level without actually varying the rendered
bytes).

**(b) "Zoom = server-side crop + resample at higher native resolution"**
— matches literal fram.fzu.cz semantics more closely if their zoom
actually re-renders a cropped region at full sensor resolution (not
verified — was inferred from the dropdown label "x1-x32", not confirmed
against actual fram.fzu.cz network requests). Would require:
- New query params for crop center + zoom level (`zoom` alone is
  insufficient — you'd also need pan/center coordinates, e.g. `cx=`,
  `cy=`, or pixel-space `x=`, `y=`, `w=`, `h=`).
- Changes to `render_fits_preview()` to crop the numpy array (from
  `preview.py`'s `data` variable, right after the HDU/dimensionality
  reduction, before normalization) to the requested region before
  normalizing/stretching — cropping *before* the percentile normalization
  step matters for correctness (a crop should re-compute percentiles
  over just the visible region, or fram.fzu.cz's zoom may keep the same
  global stretch — clarify which before implementing).
- Cache key changes in `preview_cache.py` to include the crop
  region/pan coordinates (currently only `stretch:scale:zoom`) — as-is,
  the cache key function accepts arbitrary strings already, so this is a
  call-site change (`_cache_key(checksum, stretch, scale, zoom)` args),
  not a redesign, but every distinct pan position would create its own
  cache entry — consider whether that's acceptable cache growth, or
  whether zoom regions should be snapped to a fixed tile grid instead
  (proper "tiled image" approach, e.g. like OpenSeadragon/IIIF deep zoom
  — much bigger undertaking, only justified if pixel-level zoom fidelity
  on very large frames is a hard requirement).

**Recommendation**: default to (a) unless there's a specific stated
requirement for pixel-level re-rendering at high zoom (the current JPEG
quality=90, 8-bit grayscale output should already look fine even zoomed
in via CSS scaling, since it's derived from a single already-stretched
image, not raw sensor data needing separate reprocessing per zoom level).

## 5. Backend/API considerations if you make this genuinely interactive

- **Avoid full page reloads.** The current design's `<img src=...>` is
  the simplest possible integration, but every dropdown change would
  require either (a) client-side JS setting `img.src = newUrl` directly
  (simplest, no React state management needed even), or (b) full React
  state + `<img src={computedUrl}>` re-render. Either way, **the browser
  will issue a fresh GET to `/preview/fits-image.jpg?stretch=...` — this
  already works today with zero backend changes**, since the view
  function reads `stretch`/`scale`/`zoom` from `request.args` on every
  request. **You do not need a new API/JSON endpoint for this** — just
  point the `<img>` (or an `<img>`-like element) at the same URL with
  different query params.
- **Loading state / flicker**: since each dropdown change triggers a new
  image request (rendered synchronously server-side on cache miss — see
  `preview_cache.get_or_render_preview()`, which blocks until
  `render_fn()` returns), consider a brief loading spinner/opacity
  transition in the JS layer for the (first-time, uncached) request
  latency. Render time for the sample 34MB FITS file was not benchmarked
  precisely, but involves opening the file, one array copy for
  dimensionality reduction, one percentile computation, one stretch
  application, and one JPEG encode of a ~4000x4000px image — expect low
  hundreds of milliseconds to a couple seconds depending on hardware;
  cached requests (`cache_path.exists()` short-circuit in
  `preview_cache.py`) are just a disk read + `send_file`, effectively
  free.
- **CORS/same-origin**: not a concern — the preview endpoint is served
  from the same origin as the record detail page, no cross-origin
  `fetch()` complications.
- **No JSON metadata endpoint exists for "what stretch/scale/zoom options
  are available"** — the frontend will need to hardcode the same
  allow-lists as `preview.py`'s `STRETCH_FUNCTIONS.keys()` /
  `SCALE_PERCENTILES.keys()` / `ZOOM_LEVELS`, or (cleaner) expose them via
  a small new read-only endpoint/context variable if keeping the two in
  sync manually proves error-prone. Not implemented either way currently
  — a reasonable first task for this phase if going the React-component
  route (pattern (a) in section 3), since the `data-*` attributes on the
  mount div could be populated from `record_detail/main.html` reading
  Python constants from `ui.fram.preview` directly (Jinja can access
  arbitrary Python module attributes if passed into the template context
  — would need a small `RecordsUIResourceConfig`/component change to make
  `preview.STRETCH_FUNCTIONS.keys()` etc. available as Jinja globals or
  passed via `extra_context`, following the existing `FilesComponent`
  pattern in `oarepo_ui/resources/components/files.py` — see
  `docs/FITS_IMAGE_PREVIEW.md` section "Important implementation
  findings" item 4 for how that component populates `extra_context`).

## 6. Gotchas already hit (do not rediscover these)

1. **`astropy.visualization.ImageNormalize` requires `matplotlib`** (it
   subclasses `matplotlib.colors.Normalize`) and raises `ImportError` at
   construction time if matplotlib isn't installed. `preview.py`
   deliberately avoids `ImageNormalize` and does the percentile-interval
   normalization + stretch application manually with plain numpy (see
   `render_fits_preview()`'s body). If you need to touch that function,
   keep doing it manually rather than reaching for `ImageNormalize` —
   matplotlib is not a dependency of this project and adding it just for
   this would be a meaningful, unnecessary dependency-weight increase.
2. **`RecordsUIResource.create_blueprint()` does not set a Flask
   `url_prefix`** on the blueprint (see
   `oarepo_ui/resources/records/resource.py`) — every route already
   embeds its own full path. Relevant if you ever add *new* Flask routes
   (e.g. a hypothetical tile-serving endpoint for approach 4b) — register
   them the same way the existing preview route is registered, via
   `blueprint.add_url_rule(...)` directly in `create_blueprint(app)` in
   `ui/fram/__init__.py`, with the full `/fram/...` path spelled out.
3. **`astropy`/`Pillow` needed to be promoted from transitive to explicit
   dependencies** in `pyproject.toml` (previously only pulled in via
   `healpy`). If this phase adds new dependencies (e.g. a JS zoom/pan
   library — that's an npm/package.json-equivalent concern, not
   `pyproject.toml`, but mentioned for completeness), remember to check
   `uv.lock` needs regenerating with:
   ```bash
   UV_PRERELEASE=allow \
   UV_EXTRA_INDEX_URL='https://gitlab.cesnet.cz/api/v4/projects/1408/packages/pypi/simple' \
   uv lock
   ```
   (both env vars are set automatically by `.runner.sh`, only needed
   manually if running bare `uv lock`/`uv sync` outside of `./run.sh`).
4. **Two independent "exactly one FITS file" checks exist** (template +
   view, see `docs/FITS_IMAGE_PREVIEW.md`'s "Two-layer guarantee"
   section) — if this phase changes what counts as "the/a previewable
   file" (e.g. supporting multiple FITS files with a file-picker
   dropdown, which is plausible given fram.fzu.cz's UI shows a single
   "Filename" field per viewed image, implying their archive may have
   more files per observation than we currently assume), **both checks
   need to change together**, plus the "Filename" facet/exact-match
   filter in `models/fram/facets.py`/`metadata.yaml` may need
   reconsideration if the underlying "exactly one file" assumption
   changes project-wide (not just for the preview feature).
5. **Do not run `./run.sh reset` to test changes to this feature.** It
   drops/rebuilds the DB, search indices, and file storage — none of
   which this feature touches at the schema/mapping level. Use
   `./run.sh run` (or equivalent `invenio-cli run`) against the existing
   Docker containers (`physica-db-1`, `physica-search-1`, etc.) and the
   already-uploaded sample data.
6. **Sample data caveat**: all FRAM records currently in the bundled
   sample/dev dataset have **restricted file access** for anonymous
   users. To visually test the preview (static or interactive) you must
   be logged in as a user with `can_read_files` permission on the
   specific record, or explicitly create/use a record with public file
   access. Do not conclude the feature is broken if `curl` without
   authentication shows no preview `<img>`/mount div — that is the
   correct, intended behavior of the permission check, not a bug.

## 7. Suggested first implementation checklist

A reasonable, low-risk order of operations for this phase, informed by
everything above:

1. Confirm actual requirements against real fram.fzu.cz behavior where
   this document says "not verified" / "inferred" (scale semantics, zoom
   semantics, "Processed FITS" link, Dark/Flat metadata fields) — several
   open questions above are guesses from screenshots, not confirmed specs.
2. Build the Stretch + Scale dropdowns first (zero backend changes
   needed, per section 1/5) using pattern (a) from section 3 — this is
   the highest-value, lowest-risk slice since it's 100% already supported
   server-side.
3. Add zoom as client-side CSS/JS zoom (section 4, approach (a)) — still
   zero backend changes.
4. Only if requirements genuinely demand server-side pixel-level
   re-rendering per zoom level, revisit section 4 approach (b) — this is
   a substantially bigger effort (new params, cache key redesign,
   possible tiling) and should not be started speculatively.
5. Add grid/invert toggles (pure client-side CSS, no backend involvement
   expected).
6. Revisit the "Full-size image / Raw image / Download FITS / Processed
   FITS" links row and Id/Filename/Dark/Flat/Time/Night metadata table
   only after clarifying with stakeholders which of these map to
   already-existing functionality (see section 2's per-item notes) vs.
   genuinely new backend/metadata-model work.
7. Manually re-verify using the same steps as
   `docs/FITS_IMAGE_PREVIEW.md`'s "How to manually re-verify" section,
   extended to cover each new interactive control.
