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
| `ui/fram/preview_cache.py` | Cache key extended to include `dx`/`dy`/`grid`. |
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
