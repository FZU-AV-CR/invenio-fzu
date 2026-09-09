# FRAM FITS image preview — implementation summary

## Goal

Show a dynamic, on-demand FITS image preview on the **FRAM record detail
page**, replicating the fram.fzu.cz archive's server-side rendering
approach (astropy percentile-interval + asinh stretch → JPEG), *without*
using Invenio's generic file previewer framework (which is built for
common office/image/video formats and content-negotiated JSON/HTML
routing, not this use case).

Scope/decisions locked in for this iteration (do not re-litigate without a
reason — see "Explicitly out of scope" below):

1. **Exactly one FITS file per record is assumed.** Other file types are
   ignored. Any deviation (zero FITS files, more than one, a `.zip`, a
   file still uploading/not `completed`, a corrupted FITS with no image
   HDU, ...) → **render nothing** — no `<img>` tag, no placeholder image,
   no broken-image icon. This is enforced at *two* independent layers (see
   "Two-layer 'exactly one file' guarantee" below) so that even if someone
   hits the raw preview URL directly, they get a clean 404, not a stack
   trace or an empty broken image.
2. **Scope is the UI record detail page only.** No search-results
   thumbnail integration (would need a different, response-size-sensitive
   design — thumbnails vs. full preview).
3. **Static preview image now, but the endpoint's query-parameter contract
   is designed for interactive controls later.** `stretch=`, `scale=`,
   `zoom=` query parameters are already accepted by the endpoint and
   validated against fixed allow-lists (unknown values log a warning and
   silently fall back to the default rather than erroring), mirroring
   fram.fzu.cz's own viewer toolbar (Stretch / Scale / Zoom dropdowns +
   grid/invert toggles, Full-size/Raw/Download/Processed FITS links,
   metadata table). Only `stretch=asinh`, `scale=99.5`, `zoom=1` are
   actually exercised by the current UI (no dropdowns exist yet client
   side) — but a future PR can add those dropdowns and pass the query
   params through to `<img src="...?stretch=log&scale=99">` without any
   backend API break.

## Files added/changed

| File | Purpose |
|---|---|
| `ui/fram/preview.py` | Pure rendering function: FITS bytes → JPEG bytes (astropy + Pillow + numpy, no Flask/Invenio imports — easy to unit test standalone). |
| `ui/fram/preview_cache.py` | Sharded, checksum-keyed disk cache for rendered JPEGs under `<instance_path>/fits_previews/<xx>/<yy>/<key>.jpg`, atomic writes. |
| `ui/fram/views.py` (new) | Flask view function `fits_preview_view(pid_value)` — resolves the record via the FRAM model's file service (permission-checked), re-verifies the "exactly one FITS file" invariant, renders/caches, and serves via `send_file`. |
| `ui/fram/__init__.py` | `create_blueprint(app)` now also calls `blueprint.add_url_rule(...)` directly (bypassing oarepo_ui's route-dict mechanism) to register the preview endpoint at `/fram/records/<pid_value>/preview/fits-image.jpg` under endpoint name `fram_ui.fits_preview`. |
| `ui/fram/templates/semantic-ui/fram/record_detail/main.html` | Overrides the `record_files` Jinja block (`{{ super() }}` first, so the normal file list/download UI is preserved) to conditionally emit an `<img>` tag pointing at the preview endpoint, but only when exactly one completed `.fits`/`.fit` file is visible to the current user. |
| `pyproject.toml` / `uv.lock` | Added explicit `astropy>=6.0` and `pillow>=10.0` dependencies (previously only available *transitively* via `healpy`'s own dependency chain — fragile since our code imports them directly; `numpy` was already an explicit/transitive dependency via multiple packages so no change needed there). |
| `docs/FITS_IMAGE_PREVIEW.md` | This document. |

## Architecture / request flow

```
Browser
  │  GET /fram/records/<pid_value>
  ▼
oarepo_ui RecordsUIResource.record_detail()   (unchanged, standard oarepo_ui route)
  │  renders record_detail/main.html, which overrides `record_files` block
  │  → does files.entries contain exactly one completed .fits/.fit entry?
  │     yes → emit <img src="/fram/records/<pid_value>/preview/fits-image.jpg">
  │     no  → emit nothing (no <img> tag at all)
  ▼
Browser requests the <img> src separately:
  GET /fram/records/<pid_value>/preview/fits-image.jpg[?stretch=&scale=&zoom=]
  ▼
ui/fram/views.py: fits_preview_view(pid_value)      ← plain Flask view, NOT
  │                                                     routed through oarepo_ui's
  │                                                     content-negotiation/response-
  │                                                     handler machinery (that's
  │                                                     built for JSON/HTML, not
  │                                                     raw binary image bytes)
  │
  │  1. current_runtime.models["fram"] → Model instance
  │  2. model.service.read(g.identity, pid_value)          (published)
  │     falls back to model.service.read_draft(...)         (draft/preview)
  │     → NoResultFound (both) → 404
  │  3. file_service.list_files(g.identity, record.id)      (permission-checked;
  │     raises PermissionDeniedError → 403 if the identity can't read files)
  │  4. filter entries: status == "completed" AND key ends with .fits/.fit
  │     → if count != 1 → 404  (this is the *second* independent check of
  │       the "exactly one FITS file" invariant — see below)
  │  5. size sanity check (> 512 MiB → 404, defensive DoS guard)
  │  6. preview_cache.get_or_render_preview(checksum, stretch, scale, zoom,
  │       render_fn=<reads file bytes + calls preview.render_fits_preview>)
  │     → cache hit: skip rendering entirely, just return cached path
  │     → cache miss: file_service.get_file_content(...).get_stream("rb").read()
  │       → preview.render_fits_preview() → JPEG bytes → atomically written
  │         to disk cache
  │  7. send_file(cache_path, mimetype="image/jpeg", conditional=True,
  │       etag=True, max_age=86400)
  ▼
Browser displays the JPEG.
```

### Two-layer "exactly one file" guarantee

Both the template (`main.html`) and the view (`views.py`) independently
recompute "is there exactly one completed FITS file for this record,
visible to this identity". This is intentional, not duplicated code to
clean up:

- The **template-level check** decides whether the `<img>` tag is emitted
  at all (this is what prevents a broken-image icon from ever appearing).
- The **view-level check** is the actual security/correctness boundary —
  it re-verifies permissions and file state fresh at request time (a file
  could be deleted/replaced between page render and image request), and
  is what a user hitting the raw preview URL directly (bypassing the
  template) is actually protected by.

If you ever refactor one of these, keep the other in sync, or better yet,
extract a shared "sole FITS file" helper importable from both `views.py`
and a Jinja global (not done here to keep this iteration's diff small).

## Important implementation findings (read before touching this code)

1. **`RecordsUIResource.create_blueprint()` does not set a Flask
   `url_prefix`** on the blueprint object (see
   `oarepo_ui/resources/records/resource.py`) — every route in
   `RecordsUIResourceConfig.routes` embeds its *own* full path (e.g.
   `/fram/records/<pid_value>`), because the same resource class also
   serves a second `/configs/...` endpoint namespace. This means it is
   safe (and is exactly what we do) to call
   `blueprint.add_url_rule("/fram/records/<pid_value>/preview/fits-image.jpg", ...)`
   directly on the blueprint returned by `as_blueprint()` inside
   `create_blueprint(app)` in `ui/fram/__init__.py` — no prefix
   double-application bug.

2. **`astropy.visualization.ImageNormalize` requires `matplotlib`.** It
   subclasses `matplotlib.colors.Normalize` and raises
   `ImportError: matplotlib is required in order to use this class` at
   construction time if matplotlib isn't installed. Rather than pull in
   matplotlib (a heavy dependency with no other use in this server-side
   JPEG-rendering codepath), `preview.py` computes the percentile
   interval limits directly via `PercentileInterval(...).get_limits(data)`
   and applies the stretch function manually:
   ```python
   vmin, vmax = interval.get_limits(data)
   normalized = np.clip((data - vmin) / (vmax - vmin), 0, 1)
   img = np.clip(stretch_fn(normalized), 0, 1)
   ```
   This produces the same visual result as `ImageNormalize` without the
   matplotlib dependency. If a future change wants to add matplotlib for
   some other reason, this manual normalization could be swapped back for
   `ImageNormalize` for readability, but it isn't required.

3. **`astropy`/`Pillow` were previously only *transitive* dependencies**
   (pulled in by `healpy`, which this repo already depends on explicitly
   for the sky-position/HEALPix search feature — see
   `docs/SKY_POSITION_SEARCH.md`). Since `ui/fram/preview.py` imports them
   directly, they were promoted to explicit dependencies in
   `pyproject.toml` (`astropy>=6.0`, `pillow>=10.0`) and `uv.lock`
   regenerated. `numpy` did not need to be added explicitly — it's already
   pulled in as an explicit/transitive dependency elsewhere. Locking
   required `UV_PRERELEASE=allow` and the CESNET extra index URL exported
   as env vars (both already set by `.runner.sh`, but need to be set
   manually if you ever run bare `uv lock` outside of `./run.sh`):
   ```bash
   UV_PRERELEASE=allow \
   UV_EXTRA_INDEX_URL='https://gitlab.cesnet.cz/api/v4/projects/1408/packages/pypi/simple' \
   uv lock
   ```

4. **File access API used**: `oarepo_runtime.current_runtime.models["fram"]`
   is a `Model` instance (see `oarepo_runtime/api.py`) exposing `.service`
   (record service), `.file_service` (published-record file service) and
   `.draft_file_service` (draft file service) — both populated
   automatically by the `ccmm_production_preset_1_1_0` preset used in
   `models/fram/model.py` (via oarepo_model's `ExtFilesPreset` /
   `ExtDraftFilesPreset`), no extra wiring needed on our part.
   - `file_service.list_files(identity, id_)` → `FileList` →
     `.to_dict()["entries"]` — a list of dicts with `key`, `status`,
     `checksum`, `size`, permission-checked (raises
     `PermissionDeniedError` if the identity can't read files, before
     even checking existence — so if you need a 404-vs-403 distinction,
     check file existence *first* using something you already have
     permission to read, or accept the 403 for this "list files" call as
     we do here).
   - `file_service.get_file_content(identity, id_, file_key)` → `FileItem`
     → `.get_stream("rb")` (context manager, caller must close/`with`) →
     returns the actual `invenio_files_rest` storage-backed binary stream.
     `.data["checksum"]` is also available on `FileItem.data` (dumped via
     the file schema) as an alternative to reading it from the
     `list_files` entry.

5. **`FramUIResourceConfig.model_name = "fram"`** matches the key used to
   register the model in `invenio.cfg` (`fram_model.register()`) — this is
   what `current_runtime.models["fram"]` looks up. If the FRAM model's
   `code=` in `models/fram/model.py`'s `model(...)` call is ever renamed,
   update both `ui/fram/__init__.py`'s `model_name` and the `"fram"` key
   literal used in `ui/fram/views.py`'s `current_runtime.models.get("fram")`
   call together.

6. **Sample FITS file used for manual verification**:
   `sample_data/Fram/20260304093525-219-RA.fits` (~34MB, single
   `PrimaryHDU`, `int16` data rescaled to `uint16`, shape `(4127, 4144)`).
   `render_fits_preview()` was verified standalone (no Flask/Invenio
   needed) against this file:
   ```python
   from io import BytesIO
   from ui.fram.preview import render_fits_preview
   with open("sample_data/Fram/20260304093525-219-RA.fits", "rb") as f:
       jpeg_bytes = render_fits_preview(BytesIO(f.read()))
   # → 3,031,217 bytes, Pillow reports (4144, 4127) "L" (8-bit grayscale)
   ```
   Visual inspection confirmed a correct star-field render (background sky
   glow + point-source stars, consistent with a raw un-dark-subtracted
   robotic-telescope frame under a fixed asinh/99.5-percentile stretch).

## Explicitly out of scope (do not assume these are "TODO bugs")

- No client-side Stretch/Scale/Zoom dropdown UI yet — only the backend
  query-parameter contract exists. Adding the dropdowns is a pure
  frontend (React/JSX, likely alongside `ui/fram/semantic-ui/js/fram/...`)
  + template change to pass query params into the `<img src>` — no backend
  changes needed for the currently-implemented stretch/scale values
  (`linear/asinh/log/sqrt/sinh/power` stretches; `95/99/99.5/99.9`
  percentile scales). `zoom=` is accepted but is a pure no-op today
  (always renders at full resolution) — implementing real zoom/pan would
  need either a tiled-image approach or client-side CSS/JS zoom of the
  full-resolution JPEG; no server-side resizing-by-zoom-level exists yet.
- No search-results-page thumbnail (see decision #2 above).
- No "Full-size image / Raw image / Download FITS / Processed FITS" link
  row or metadata table matching fram.fzu.cz's exact viewer layout — the
  existing FRAM `record_detail/main.html` metadata table (experiment,
  filename, site, identifier, observation time/night, ccd, type, binning,
  exposure, filter, target, radius, camera_serial, file_types, image_size,
  alt_az, center, footprint, healpix_idx, related_resources) already
  covers most of the same information; a "Download FITS" link already
  exists implicitly via the standard file list box rendered by
  `{{ super() }}` in the `record_files` block.
- No preview cache eviction/TTL/size-cap policy — the disk cache in
  `preview_cache.py` grows unbounded over time. Fine for now (JPEGs are
  small, ~1-3MB each per unique file+params combination), but if this
  becomes a concern, add a periodic cleanup task (e.g. Celery beat job)
  keyed on file mtime / an LRU policy, keyed by the same sharded directory
  layout already in place.

## Status

**Implemented and live-verified** (as of this writing): the preview image
was confirmed rendering correctly in the browser on a real record detail
page, logged in as a user with file-read permission on that record.
Records without exactly one accessible completed FITS file correctly show
no preview (verified against the bundled sample dataset, all of whose
records currently have restricted file access for anonymous/no-permission
identities — this is what exercises the "nothing rendered" path in
practice, not a separate contrived test).

**Next phase (interactive viewer matching fram.fzu.cz's toolbar) is not
started.** See `docs/FITS_DYNAMIC_VIEWER_HANDOFF.md` for a detailed
technical handoff aimed at a future chat/session implementing that phase,
so it does not need to re-derive the investigation already done here.

## How to manually re-verify after future changes

1. Ensure Docker services are up (`docker ps` — postgres/redis/rabbitmq/
   minio/opensearch containers named `physica-*`) and the dev server is
   running (`./run.sh run`, or equivalent `invenio-cli run` — do **not**
   run `./run.sh reset` just to test this feature; it does not touch the
   data model, index mappings, or DB schema, so a full reset is never
   required for this feature specifically).
2. If no FRAM record with a FITS file exists yet, upload the sample one:
   `sample_data/Fram/upload_sample_fram001.sh` (uses `nrp-cmd`, requires
   the `physica-local` repository alias to be configured — see the
   script's header comment).
3. `curl -sk https://127.0.0.1:5000/fram/records/<pid_value>` and confirm
   an `<img class="fits-preview-image" ...>` tag with a `src` pointing at
   `/fram/records/<pid_value>/preview/fits-image.jpg` appears in the HTML.
4. `curl -sk -o /tmp/preview.jpg -w '%{http_code} %{content_type}\n' https://127.0.0.1:5000/fram/records/<pid_value>/preview/fits-image.jpg`
   → expect `200 image/jpeg`; open `/tmp/preview.jpg` to visually confirm.
5. To test the "nothing rendered" path: upload a record with zero files,
   or two files (one FITS + one other), and confirm no `<img
   class="fits-preview-image">` appears in the detail page HTML, and that
   `GET .../preview/fits-image.jpg` for that record returns `404`.
