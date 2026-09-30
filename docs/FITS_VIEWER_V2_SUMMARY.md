# FITS viewer v2 — interactive toolbar + dark/flat links (implementation summary)

## 1. What this round did

Follow-up to `docs/FITS_IMAGE_PREVIEW.md` (static preview) and
`docs/FITS_DYNAMIC_VIEWER_HANDOFF.md` (original interactive-viewer
handoff, written from fram.fzu.cz screenshots only). This round had
access to the **actual fram.fzu.cz source** (the real `fram-archive`
Django app, a local git checkout at
`~/Python WSL/Archive/v1/FRAM/Scripts/Sergeygit/fram-archive/`) and a
**stakeholder email exchange** (`FRAM_topics.docx`, provided by the
project owner) confirming exact semantics that were previously only
guessed from screenshots. Several of the original handoff doc's
assumptions turned out to be wrong once checked against the real
source — see section 3 for the corrections.

Implemented:

1. **Stretch/Scale dropdowns**, with corrected semantics (see section 3).
2. **Real server-side Zoom + click-to-pan** (not a CSS/JS no-op as
   originally planned — the real archive does an actual pixel crop).
3. **Grid overlay** — simplified (Pillow-drawn lines), not the real
   archive's matplotlib/axes/colorbar pipeline (deliberately, to avoid
   adding a matplotlib dependency for a cosmetic feature).
4. **Raw FITS header dump** on the record detail page (collapsible
   `<details>`, matching the real archive's own header rendering, per
   the stakeholder's provided extraction snippet).
5. **Dark/Flat calibration-frame links** in the metadata table, found
   via a **runtime OpenSearch lookup** (no metadata.yaml schema change),
   per explicit stakeholder guidance (see section 4).

Explicitly **not** implemented this round (see section 5 for the
reasoning and what a follow-up would need):

- Dark/flat-subtraction pixel calibration ("Raw" checkbox actually doing
  something, "Processed FITS" download).
- Per-camera-serial sensor linearization tables.
- Background/FWHM/WCS/Filters/Zero-point diagnostic popups, obj/cat
  overlays (photometry-pipeline features, no underlying data modeled in
  this repo at all).
- Bias+dcurrent-reconstruction fallback in the calibration lookup (only
  the direct `masterdark`/`masterflat` match is implemented).

## 2. Files added/changed

| File | Change |
|---|---|
| `ui/fram/preview.py` | Rewrote stretch/scale semantics to match the real archive (see section 3); added real zoom+pan crop; added `histeq` stretch; added grid overlay. |
| `ui/fram/preview_cache.py` | Cache key extended to include `dx`/`dy`/`grid`. (Later in this round -- see section 7 -- rewritten to use `invenio_cache.current_cache`/Redis instead of local disk, to fix a Kubernetes/test1 deployment bug.) |
| `ui/fram/views.py` | `fits_preview_view` reads/passes through `dx`/`dy`/`grid`; extracted `_resolve_record_and_sole_fits_file`/`_read_fits_file_bytes` helpers (shared with the new header-dump component). |
| `ui/fram/calibration.py` (new) | `find_calibration_frame()` — runtime dark/flat lookup, see section 4. |
| `ui/fram/components.py` (new) | `FramFitsMetadataComponent` — a `UIResourceComponent` populating `extra_context["dark_frame"]`/`["flat_frame"]`/`["fits_header_cards"]` for the detail page, registered via `FramUIResourceConfig.components` (the standard oarepo_ui extension point — no upstream files touched). |
| `ui/fram/__init__.py` | Registers `FramFitsMetadataComponent` in `FramUIResourceConfig.components`. |
| `ui/fram/templates/semantic-ui/fram/record_detail/main.html` | `record_files` block now emits a mount `<div id="fits-preview-toolbar-root">` (React-driven) instead of a static `<img>`; added Dark/Flat metadata rows; added collapsible FITS header dump section. |
| `ui/fram/templates/semantic-ui/fram/record_detail/javascript.html` (new) | Includes the new `fram_fits_preview.js` webpack bundle (this template hook previously didn't exist for this model). |
| `ui/fram/semantic-ui/js/fram/preview/FitsPreviewToolbar.jsx` (new) | React component: Stretch/Scale/Zoom selects + Grid checkbox, click-to-pan, builds the `<img>` src query string client-side. |
| `ui/fram/semantic-ui/js/fram/preview/index.js` (new) | Mounts `FitsPreviewToolbar` via `ReactDOM.render` against the `data-preview-url`-carrying mount div (same pattern as `invenio_app_rdm`'s `landing_page/access.js`). |
| `ui/fram/webpack.py` | New `fram_fits_preview` entry. |
| `tests/test_fits_preview.py` (new) | Standalone pytest tests for `render_fits_preview()` against the bundled sample FITS file — all stretch/scale options, zoom+pan, grid, and fallback-on-invalid-param behaviour. |
| `docs/FITS_DYNAMIC_VIEWER_HANDOFF.md` | Marked as superseded by this document (kept for historical reference). |

## 3. Corrected semantics vs. the original (screenshot-based) handoff doc

The original handoff doc's guesses, and what the real fram-archive
source (`archive/views_images.py`, `archive/static/image_overlay.js`)
actually does:

| Control | Original guess | Real fram.fzu.cz (now implemented) |
|---|---|---|
| Stretch | 6 options, no `histeq` | **7 options**: `linear/asinh/log/sqrt/sinh/power/histeq`. `histeq` uses astropy's `HistEqStretch(data)` — confirmed to need only the data array, not matplotlib. |
| Scale | Query param `scale=`, symmetric `PercentileInterval(scale)` (e.g. `99.5` → clip `[0.25, 99.75]`) | Query param is actually `qmax` server-side, and it's **asymmetric**: fixed `qmin=0.5`, variable `qmax` in `{90, 95, 99, 99.5, 99.9, 99.95, 99.995, 100}`. Our `preview.py` keeps the query param named `scale` (matching this repo's existing endpoint contract/URL already in use), but internally applies it as the real archive's asymmetric `qmax` semantics. |
| Zoom | Documented no-op; recommended pure CSS/JS zoom of the full-res JPEG | **Real server-side pixel crop+pan.** The real archive crops a `width/zoom x height/zoom` box centered on the image (or on a `dx`/`dy`-panned position), then resizes/encodes. Click-to-pan: clicking a quadrant of the image shifts by `1/zoom` in that direction. Implemented faithfully (minus the real archive's OpenCV/skimage dependency -- done with pure numpy/Pillow instead, see `_crop_zoom_pan`/`_resolve_pan` in `preview.py`). |
| Grid | Unknown/guessed | Real archive switches to an **entirely different rendering pipeline** (matplotlib + STDPipe `imshow`, with axes/colorbar) when grid is on. We deliberately implemented a **much simpler** Pillow-drawn line overlay instead, to avoid a new matplotlib dependency for what is a cosmetic feature -- a real design tradeoff, not an oversight. |
| Toolbar scope | Assumed possibly 8+ controls (stretch/scale/zoom/grid/smooth/raw/obj/cat/mark-ra-dec) | The actual `image.html` template only sets `data-stretch=1 data-zoom=1 data-grid=1 data-raw=1` -- so the real toolbar on *this* page is just **Stretch, Scale, Zoom, Grid, Raw** (smooth/obj/cat/mark-ra-dec exist in the shared JS but are used on other pages, e.g. cutouts). We implemented Stretch/Scale/Zoom/Grid; Raw is deferred (see section 5). |

## 4. Dark/Flat calibration-frame lookup

Per **direct stakeholder guidance** (email exchange, `FRAM_topics.docx`):

> "these calibration images do not need to be explicitly linked to the
> original image as dedicated fields. Instead, they may be located at
> runtime using the metadata."

So **no `metadata.yaml` schema change was made** -- `ui/fram/calibration.py`'s
`find_calibration_frame(record_metadata, frame_type)` runs an OpenSearch
query (via `model.service.search(..., extra_filter=...)`, the same
`invenio_search.engine.dsl.Q` pattern already used in
`models/fram/facets.py`) against already-indexed fields:

- `metadata.type` must equal `"masterdark"`/`"masterflat"`.
- `metadata.site`, `metadata.ccd`, `metadata.camera_serial`,
  `metadata.binning`, `metadata.image_size.usable_width`/`usable_height`
  must match exactly.
- For flats: `metadata.filter` must also match. For darks:
  `metadata.exposure` must also match.
- Among matches, prefer the latest `observation_time` not after the
  science record's own time; fall back to the closest later one.

This is the same algorithm as the real `find_calibration_image()` in
`fram-archive/archive/views_images.py`, **except** the bias+dcurrent
reconstruction fallback (used when no direct `masterdark` exists) is
**not** implemented -- deferred along with the rest of the pixel
calibration work (section 5), since it's calibration math, not a
metadata lookup.

`FramFitsMetadataComponent.before_ui_detail` calls this for both frame
types and stuffs the results into `extra_context["dark_frame"]`/
`["flat_frame"]`; `main.html` renders a "Dark"/"Flat" table row with a
link to that record only when a match is found -- if not (e.g. the
current single-record sample dataset, which has no calibration frames
uploaded yet), the rows are simply omitted, matching this repo's
established "render nothing rather than a placeholder" convention.

**Verified live** against the running dev stack: `find_calibration_frame`
correctly returns `None`/`None` for the one existing sample record (no
calibration frames exist in the dataset yet) without erroring -- see
section 6 for the full verification log.

## 5. Deferred: Raw toggle / Processed FITS / linearization tables

Per stakeholder guidance:

> "The dark and flat are only relevant if you wish to actually display
> the image in pre-processed / science-ready form, or allow downloading
> it like that... it will only be needed if your portal will also allow
> displaying images like that."

This is explicitly optional, and doing it properly (dark-subtract +
flat-field, optionally full per-camera-serial linearization) is
calibration *math*, not template/metadata work -- a meaningfully bigger
and riskier effort than this round's scope, and one that can't be
properly validated without real calibration-frame sample data (which
does not exist in this repo's dataset yet -- the workflow described by
the project owner is monthly per-site uploads where darks/flats land
alongside science frames, so this becomes testable once such a batch is
uploaded). A follow-up session should:

1. Confirm real calibration-frame sample data is available to test
   against (upload a `type: masterdark`/`masterflat` record matching
   the sample science record's site/ccd/camera_serial/binning/etc.).
2. Extend `find_calibration_frame` with the bias+dcurrent fallback.
3. Decide whether to port `fram/calibrate.py`'s linearization tables
   verbatim (bit-exact parity, large effort) or implement a
   simplified dark-subtract+flat-field-only calibration (visually
   close, much smaller effort) for the "Raw" toggle and a new
   "Processed FITS" download endpoint.

## 6. How to manually re-verify

Same preconditions as `docs/FITS_IMAGE_PREVIEW.md` (`./run.sh run`,
never `reset`, for this feature). After any further Python changes to
`ui/fram/*.py`, the Flask reloader picks them up automatically. After
any JS/JSX change, **you must re-run**:

```bash
.venv/bin/invenio webpack build
```

(If a *new* webpack entry point is ever added to `webpack.py`, run
`invenio webpack create` once first -- `build` alone will not pick up a
brand-new entry name, only re-compile already-registered ones. This was
hit and fixed during this round.)

Verification performed this round (against the existing sample record
`fggq5-y3894`, a public/`files: public` record uploaded during this
session):

1. `curl -H 'Accept: text/html' https://127.0.0.1:5000/fram/records/fggq5-y3894`
   -> `200`, contains `<div id="fits-preview-toolbar-root" data-preview-url="...">`,
   the `<details><summary>Original FITS header</summary>` section with
   real parsed FITS keywords, and a `<script src="/static/dist/js/fram_fits_preview.....js">`
   include. No Dark/Flat rows (correct -- no calibration frames in the
   dataset).
2. `curl .../preview/fits-image.jpg?stretch=histeq&scale=90` -> `200 image/jpeg`, valid JPEG, full native resolution (4144x4127).
3. `curl .../preview/fits-image.jpg?zoom=4&dx=0.3&dy=-0.2` -> `200 image/jpeg`, valid JPEG, correctly quartered (1036x1032).
4. `curl .../preview/fits-image.jpg?grid=1` -> `200 image/jpeg`, valid JPEG, pixel content differs from the no-grid render (grid lines present).
5. `curl .../preview/fits-image.jpg` (defaults) -> `200 image/jpeg`.
6. Nonexistent record pid -> `404` (unchanged behaviour).
7. `.venv/bin/python -m pytest tests/test_fits_preview.py` -> 27/27 passed (all stretch options, all scale options, fallback-on-invalid-param, zoom crop-size correctness, pan-changes-output, grid-changes-output).
8. `invenio shell`-based direct call to `find_calibration_frame` against
   the real record/index -> returns `None`/`None` without error (expected,
   dataset has no calibration frames yet).

## 7. Follow-up fix: preview cache moved from local disk to Redis (`invenio_cache`)

**Problem reported**: the FITS preview worked correctly locally, but
failed on the `test1` Kubernetes deployment. Root cause: `preview_cache.py`
originally cached rendered JPEGs as files under
`<instance_path>/fits_previews/<xx>/<yy>/<key>.jpg` on local disk. On
Kubernetes, pods commonly run with a read-only and/or ephemeral,
non-shared root filesystem, so writes to `instance_path` either fail
outright or silently don't persist/aren't shared across replicas -- the
opposite of the local dev setup (a single long-lived process with a
writable `.venv/var/instance` directory), which is why the bug wasn't
visible locally.

**Fix**: `preview_cache.py` was rewritten to use
`invenio_cache.current_cache` (`from invenio_cache import current_cache`)
instead of the filesystem. This is a Flask-Caching-backed cache that
InvenioRDM already configures to use **Redis** by default
(`CACHE_TYPE = "flask_caching.backends.redis"`,
`CACHE_REDIS_URL`) -- the same Redis instance InvenioRDM already requires
for sessions/rate-limiting, confirmed already wired up in this repo via
`variables`' `INVENIO_REDIS_HOST`/`INVENIO_REDIS_PORT`/
`INVENIO_REDIS_CACHE_DB` (a dedicated DB index, separate from the
session/celery/communities DBs) and `docker/docker-compose.yml`'s
`redis:7` service locally. No new infrastructure was needed for this fix,
either locally or on test1/production, since a working Redis is already
a hard requirement for any InvenioRDM deployment.

Changes:

- `_cache_key(...)` (sha256 of `checksum:stretch:scale:zoom:dx:dy:grid`)
  is unchanged -- only the storage backend changed, not the keying
  scheme. A `CACHE_KEY_PREFIX = "fits_preview::"` was added so cache keys
  can't collide with unrelated values in the same shared Redis-backed
  cache (sessions, other subsystems, etc.).
- `get_or_render_preview(...)` now returns raw JPEG **`bytes`** (previously
  a `Path` to a cached file on disk) -- `current_cache.get(key)` /
  `current_cache.set(key, jpeg_bytes, timeout=CACHE_TIMEOUT)` replace all
  `os`/`tempfile`/`Path` disk logic.
- A new `cache_key_for(...)` helper (same key derivation, public) lets
  `views.py` compute the ETag without needing the cache module to also
  expose a filesystem path.
- `views.py`'s `fits_preview_view` no longer calls `send_file(cache_path,
  conditional=True, etag=True, ...)` (which requires a real filesystem
  path for those convenience features) -- it now builds a plain
  `flask.Response(jpeg_bytes, mimetype="image/jpeg")` and sets `ETag`
  (the quoted cache key) / `Cache-Control: public, max-age=86400` headers
  manually, and manually short-circuits to a `304` when the incoming
  `If-None-Match` header matches, preserving the same conditional-request
  behavior `send_file` used to provide for free.
- **Cache eviction**: a 24h TTL (`CACHE_TIMEOUT` in `preview_cache.py`,
  matching `PREVIEW_MAX_AGE` in `views.py`) is now passed to
  `current_cache.set(...)`, so Redis expires stale entries automatically.
  The old disk cache had no eviction/TTL at all (acceptable there since
  disk is comparatively cheap/plentiful); an explicit TTL was added here
  because Redis memory is shared with other Invenio subsystems and more
  worth reclaiming proactively.

**Not changed**: `preview.py`'s rendering logic (stretch/scale/zoom/pan/
grid math) is completely untouched -- this was purely a caching-layer
swap. The "exactly one FITS file, permission-checked" resolution logic in
`views.py` is also untouched.

**How to manually re-verify this fix**:

1. Locally (`./run.sh run`, Redis already up via `docker/docker-compose.yml`):
   request a FITS preview twice (`curl .../preview/fits-image.jpg` twice)
   and confirm the second request is fast (cache hit) while **no new
   files appear under `.venv/var/instance/fits_previews/`** (that
   directory should no longer be created/written to at all).
2. Confirm a repeat request with `-H 'If-None-Match: "<etag-from-first-response>"'`
   returns `304 Not Modified` with an empty body.
3. On test1 (or any Kubernetes-deployed environment with a read-only
   filesystem), confirm the preview now renders successfully where it
   previously failed.

## 8. Colormap + vertical-orientation fix (post-v2)

A later visual comparison against real fram.fzu.cz screenshots found the
preview here rendered flat grayscale and upside-down relative to the real
archive. Root-caused directly against the real archive's
`image_response()` (`fram-archive`'s `archive/views_images.py`):

- The real archive always applies a colormap, `cmap = colormaps[cmap]`,
  defaulting to **`cmap='Blues_r'`** -- not plain grayscale.
- The real archive calls `cv2.flip(data, 0)` right before JPEG encoding,
  since FITS row 0 is conventionally the *bottom* of the sky image while
  PIL/JPEG assume row 0 is the top.

**Fix** (in `ui/fram/preview.py`, no new dependency added):

- Added `CMAP_STOPS`, a small dict of hardcoded 9-point ColorBrewer
  "Blues"/"Greys" (+ `_r` reversed variants) RGB control points,
  transcribed verbatim from matplotlib's own `lib/matplotlib/_cm.py`
  (`_Blues_data`/`_Greys_data`) -- chosen specifically so results are
  numerically identical to `matplotlib.colormaps[name]` for these names,
  without adding matplotlib as a project dependency (same rationale as
  the existing stretch/normalization code in this module).
- Added `_apply_colormap(normalized, cmap_name)`, interpolating each RGB
  channel independently via `np.interp` across the chosen colormap's
  stops, replacing the old plain `(img * 255).astype(np.uint8)`
  single-channel path.
- Added `np.flipud(rgb)` right before `Image.fromarray(rgb, mode="RGB")`.
- `render_fits_preview(..., cmap=DEFAULT_CMAP)` -- `DEFAULT_CMAP =
  "Blues_r"`, matching the real archive's default. `cmap=` is validated
  against `CMAP_STOPS` the same way `stretch=`/`scale=`/`zoom=` already
  were (`_resolve_cmap_name`, unknown values log a warning and fall back
  to the default rather than erroring).
- `preview_cache.py`'s `_cache_key`/`get_or_render_preview`/
  `cache_key_for` extended to include `cmap` (mechanically, same pattern
  as the existing `grid` parameter) so different colormaps don't collide
  in the Redis cache.
- `views.py`'s `fits_preview_view` reads `cmap=` off `request.args`
  (default `DEFAULT_CMAP`) and threads it through to rendering, caching,
  and the ETag computation.
- `FitsPreviewToolbar.jsx` got a `Colormap` `<Form.Select>` (options
  `Blues_r`/`Blues`/`Greys_r`/`Greys`), following the exact same
  state/`useMemo`/`searchParams.set` pattern already used for
  Stretch/Scale/Zoom.

**Not changed**: stretch/scale/zoom/pan/grid math, the cache backend
(still Redis via `invenio_cache`), and the "exactly one FITS file"
resolution logic are all untouched -- this was purely a colormap +
orientation fix.

**Tests**: see `tests/test_fits_preview.py`'s
`test_default_render_is_colored_not_grayscale`,
`test_all_cmap_options_render`, `test_unknown_cmap_falls_back_to_default`,
`test_different_cmaps_produce_different_output`,
`test_blues_r_is_dark_at_low_values_and_light_at_high_values`, and
`test_output_is_vertically_flipped_relative_to_raw_fits_data`.
