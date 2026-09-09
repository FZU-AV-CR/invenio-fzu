# Project overview — read this first

**Audience**: an LLM (or new developer) about to make *any* change to
this repository — not specific to the FITS preview feature. Read this
document before starting any task to understand what kind of project
this is, how it's structured, and the platform-specific conventions that
differ from a "vanilla" InvenioRDM instance.

For FITS-preview-specific work, see `docs/FITS_IMAGE_PREVIEW.md` (static
preview, what's built), `docs/FITS_DYNAMIC_VIEWER_HANDOFF.md` (original
interactive-viewer handoff/investigation, screenshot-based, superseded)
and `docs/FITS_VIEWER_V2_SUMMARY.md` (what was actually implemented for
the interactive toolbar + dark/flat links, verified against the real
fram.fzu.cz source and stakeholder guidance). For the
custom-facet/filter pattern (range queries, cone search, text-match
filters), see `docs/CUSTOM_FILTERS_HOWTO.md` and
`docs/SKY_POSITION_SEARCH.md`. For the "browse by experiment" homepage
feature, see `docs/HOMEPAGE_BROWSE_BY_EXPERIMENT.md`.

## 1. What this project is

This is **"Physica.science"** (`physica` in code) — a multi-model physics
data repository built on **InvenioRDM** (a research-data-management
platform), customized via the **OARepo** framework/toolchain (a CESNET
project that layers declarative model-building, UI generation, and
opinionated conventions on top of InvenioRDM/Flask). It hosts several
independent-but-related "models" (record types), each with its own
metadata schema, permissions, search facets, and UI:

- **FRAM** — astronomical observation data (FITS images) from a robotic
  telescope network (Photometric Robotic Atmospheric Monitor).
  `models/fram/`, `ui/fram/`.
- **SiPM** — silicon photomultiplier detector data. `models/sipm/`,
  `ui/sipm/`.
- **Particles** — particle physics (DELPHI experiment) data.
  `models/particles/`, `ui/particles/`.
- **ATLAS ITk** — ATLAS Inner Tracker detector data. `models/atlas_itk/`,
  `ui/atlas_itk/`.

All four models share the same underlying record lifecycle (draft →
published, community-based permissions, workflow-based requests) via
`common/workflows/default.py` and the CCMM ("Czech Core Metadata Model")
production preset from the `ccmm-invenio` package.

**This is not a from-scratch Flask/Invenio app.** Almost all
infrastructure (record CRUD REST API, drafts, file storage, search
indexing, permissions engine, UI page rendering, React search UI, deposit
forms) is provided by upstream packages (`invenio-*`, `oarepo*`,
`ccmm_invenio`) installed in `.venv`. **This repository's own code is
almost entirely *configuration and thin customization* of that
framework** — declarative YAML metadata schemas, small Python
customization classes/functions, Jinja template overrides, and React
component overrides. When making changes, always prefer finding the
right *extension point* in the framework over writing new infrastructure
from scratch — see section 5.

## 2. Top-level directory map

```
invenio-fzu/
├── invenio.cfg          # Main Flask/Invenio config (Python). Registers all
│                         # 4 models, sets sidebar templates, theme options,
│                         # rate limits, OIDC/EInfra auth, matomo analytics.
│                         # Symlinked into the running instance's instance_path.
├── pyproject.toml        # Project deps + ALL entry points (webpack themes,
│                         # blueprints, finalize_app hooks, i18n, alembic).
│                         # This is how ui/<model>/create_blueprint gets
│                         # discovered/registered by Invenio at all.
├── uv.lock               # Locked dependency versions (uv package manager).
│                         # Needs UV_PRERELEASE=allow + CESNET extra index to
│                         # regenerate (see section 7).
├── run.sh / .runner.sh   # Dev workflow CLI wrapper (see section 6). .runner.sh
│                         # is auto-downloaded from the oarepo GitHub repo, do
│                         # not hand-edit it (self_update overwrites it anyway).
├── models/                # One subpackage per record type (see section 3).
│   ├── __init__.py         # imports+exports all 4 model() instances.
│   ├── fram/
│   ├── sipm/
│   ├── particles/
│   └── atlas_itk/
├── ui/                     # One subpackage per record type's UI (see section 4),
│   │                       # PLUS shared UI subpackages:
│   ├── fram/ / sipm/ / particles/ / atlas_itk/
│   ├── components/          # Shared React components used across models,
│   │                         # e.g. record-management sidebar menu.
│   └── about/                # Simple static "About" page blueprint.
├── common/                 # Shared Python code importable as `from common import x`
│   │                       # by any model/ui package. Currently just workflow
│   └── workflows/            # permission/request policies (see section 5).
├── i18n/                   # Backend (Python/Jinja) translation catalogs +
│                           # webpack entry for the i18n JS bundle.
├── translations/           # Compiled .po/.mo message catalogs (generated by
│                           # `./run.sh translations`, mostly not hand-edited).
├── templates/              # SITE-WIDE (non-model-specific) Jinja overrides:
│                           # header/footer/frontpage/page layout, About page
│                           # content. See templates/README.md.
├── app_data/               # Static vocabulary fixture data (controlled
│                           # vocabularies loaded at `./run.sh reset` time),
│                           # e.g. experiments.yaml, particle_category.yaml.
├── docker/                 # docker-compose.yml for local dev services
│                           # (postgres/redis/rabbitmq/minio/opensearch), plus
│                           # dev TLS cert/key used by `invenio run --cert/--key`.
├── sample_data/            # Per-model sample record JSON + upload shell
│                           # scripts (using `nrp-cmd`) + real sample data
│                           # files (e.g. an actual .fits file for FRAM).
├── tests/                  # Currently a small number of standalone Python
│                           # test scripts (not a full pytest suite with
│                           # fixtures) — see section 8 for how to run them.
├── docs/                   # THIS documentation set (Markdown design docs,
│                           # not auto-generated, hand-maintained knowledge
│                           # base for humans/LLMs working on this repo).
├── static/, assets/        # Static asset directories (icons, build output).
└── variables               # Shell env-var file sourced by .runner.sh for
                            # local port configuration.
```

## 3. The "model" concept (`oarepo_model`)

Each `models/<name>/` package declares one **record type** using the
`oarepo_model` library's declarative builder. Files, by convention:

- **`metadata.yaml`** — declarative field schema for the record's
  `metadata` object. Each field has a `type` (e.g. `keyword`, `float`,
  `int`, `datetime`, `object`, `array`, `vocabulary`,
  `dynamic-object`...), a `label` (en/cs), optional `description`,
  `example`, `pattern` (regex validation), and — for fields that should
  be filterable in the search UI beyond a default checkbox facet — a
  `facet-def` block naming a custom `Facet` class + explicit `field`/
  `label` (see `docs/CUSTOM_FILTERS_HOWTO.md` for the full pattern and
  its gotchas — **`field`/`label` must always be explicit when a custom
  `facet-def` is given**, a silent-failure trap already hit and
  documented there). This YAML is loaded via `from_yaml("metadata.yaml",
  __file__)` in `model.py` and drives generated JSON Schema, OpenSearch
  mapping, marshmallow (de)serialization, and the UI's field
  label/rendering metadata — one source of truth, not three.
- **`model.py`** — the actual `model(...)` builder call (from
  `oarepo_model.api`), specifying: `code` (short machine name, must match
  what's registered in `invenio.cfg` and looked up via
  `current_runtime.models["<code>"]`), `version`, `description`,
  `presets=` (reusable behavior bundles — all 4 models here use
  `ccmm_production_preset_1_1_0` from `ccmm_invenio.models`, which wires
  up drafts, files, DOI/PID assignment, workflows, and RDM-compatible
  serializers), `types=` (the metadata schema from step above),
  `customizations=` (a list of `oarepo_model.customizations.*` objects —
  this is where model-specific deviations from the preset defaults live:
  permission-policy mixins, custom exports, facet registration for
  virtual/foreign fields that can't carry a YAML `facet-def`, OpenSearch
  index-mapping patches via `PatchIndexPropertyMapping`, etc.), and
  `configuration={"ui_blueprint_name": ...}` linking it to its `ui/`
  package's Flask blueprint name.
- **`facets.py`** — custom `Facet` subclasses referenced by
  `facet-def` blocks or `AddToDictionary(...)` customizations in
  `model.py`, for filter behaviors the default OpenSearch `terms`
  aggregation facet can't express (ranges, substring match, exact match
  on foreign/CCMM-owned fields, virtual multi-field filters like FRAM's
  sky-position cone search). See `docs/CUSTOM_FILTERS_HOWTO.md` section 3
  for the base patterns (`RangeQueryFacet`, `TextMatchFacet`,
  `ExactMatchFacet`) before writing a new one from scratch.
- **`serializers.py`** — export-format serializers (e.g. DataCite JSON),
  registered via `AddMetadataExport(...)` in `model.py`'s
  `customizations=`.
- **`.copier-answers.yml`** — **this model package was originally
  scaffolded from the `nrp-model-copier` Copier template.** It records
  the template commit/answers used. Re-running `./run.sh model update
  <model-name>` (or the underlying `nrp` tooling) against this file could
  regenerate/overwrite scaffolded files based on the template — check
  what the template actually touches before assuming hand-written
  customizations in `model.py`/`facets.py` are safe from being clobbered
  by a template update. This was not deeply investigated in this
  session; treat it as a caution flag, not a fully-mapped hazard.

Models are **registered** (made active in the running app) in
`invenio.cfg`:
```python
from models import atlas_itk_model, sipm_model, fram_model, particles_model
particles_model.register()
sipm_model.register()
fram_model.register()
atlas_itk_model.register()
```
After registration, `oarepo_runtime.current_runtime.models["<code>"]`
(a `Model` instance) is the canonical way to access a model's record
service, file service(s), draft service, record/draft classes, etc. from
anywhere in the codebase (see `docs/FITS_IMAGE_PREVIEW.md` section
"Important implementation findings" item 4 for a concrete usage example
against the FRAM file service).

## 4. The "UI" concept (`oarepo_ui`)

Each `ui/<name>/` package provides the **HTML/React frontend** for one
model. Files, by convention:

- **`__init__.py`** — defines `<Name>UIResourceConfig` (subclassing
  `CCMMRecordsUIResourceConfig` → `RDMRecordsUIResourceConfig` →
  `RecordsUIResourceConfig`, from `oarepo_ui`/`oarepo_rdm`/`ccmm_invenio`)
  and `<Name>UIResource` (usually just `class XUIResource(CCMMRecordsUIResource): pass`
  — no behavior override needed unless you need custom routes, as FRAM's
  FITS preview does). Also defines the three entry-point functions
  wired up in `pyproject.toml`:
  - `create_blueprint(app)` — instantiates the resource/config and calls
    `.as_blueprint()`. **This is the correct place to register any extra
    custom Flask routes** (see `ui/fram/__init__.py`'s FITS preview route
    for a working example) — `RecordsUIResource.create_blueprint()`
    deliberately does *not* set a Flask `url_prefix` on the blueprint
    (every route embeds its own full path), so calling
    `blueprint.add_url_rule("/modelname/...", ...)` directly after
    `as_blueprint()` is safe and does not risk prefix double-application.
  - `finalize_app(app)` — called once at app startup; typically
    registers the model's search-results-list React component override
    (`ui_overrides`) and a "New <Model>" entry in the deposit-creation
    menu (`init_menu`).
  - (implicitly via the config class) `RecordsUIResourceConfig.routes`
    defines the standard page routes every model gets for free:
    `search`, `deposit_create`, `deposit_edit`, `record_detail`,
    `record_latest`, `record_export`, `published_file_preview`,
    `draft_file_preview`, plus a `/configs/<model>/form` route for the
    React deposit form's config JSON. You do not need to (and normally
    should not) touch these — customize behavior via template overrides
    and `components=` instead (see below).
- **`webpack.py`** — a `WebpackThemeBundle` declaring JS entry points
  (e.g. `<model>_search.js`, `<model>_deposit_form.js`) built from
  `semantic-ui/js/<model>/...`, plus optional `aliases` (e.g.
  `"@js/fram": "./js/fram"`) so other bundles can import from this
  model's JS tree. Registered as an `invenio_assets.webpack` entry point
  in `pyproject.toml`.
- **`templates/semantic-ui/<model>/`** — Jinja **template overrides**.
  oarepo_ui resolves templates via `model_name ~ "/record_detail/..."`
  path lookup with fallback to its own `oarepo_ui/record_detail/...`
  defaults (Jinja's template-loader search-path mechanism, not a Python
  inheritance mechanism) — so a file only needs to exist here if you're
  actually overriding something; anything not present falls back to the
  oarepo_ui/invenio_app_rdm default. The convention for page-level files
  (`record_detail.html`, `record_search.html`, `deposit_create.html`,
  `deposit_edit.html`, `not_found.html`, `tombstone.html`) is to
  `{% extends "oarepo_ui/<same-name>.html" %}` and override named Jinja
  **blocks** inside subdirectories matching the parent's own block
  structure, e.g. `record_detail/main.html` overriding blocks like
  `record_content`, `record_files`, `record_title` (each block override
  should normally call `{{ super() }}` first to preserve the default
  behavior and then append/prepend custom markup — see
  `ui/fram/templates/semantic-ui/fram/record_detail/main.html` for a
  worked example with `record_content` — the additional-metadata-table
  case — and `record_files` — the FITS preview `<img>` case). Read the
  large comment block at the top of any `oarepo_ui`-inheriting template
  in this repo (e.g. `record_detail/main.html`) — it enumerates every
  available block and what context variables (`record`, `record_ui`,
  `files`, `permissions`, `metadata`, `is_preview`, `is_draft`, ...) are
  available inside it; **do not guess** at available blocks/variables,
  they're documented right there or in the actual
  `.venv/.../oarepo_ui/templates/oarepo_ui/...` source (which you should
  read directly when the local comment isn't enough — never modify files
  under `.venv`, they're managed by CESNET/upstream and get overwritten
  on every dependency upgrade).
- **`templates/semantic-ui/<model>/record_detail/javascript.html`**
  (optional, not present for any model as of this writing) — the hook
  point for including a model's own webpack JS bundle on the record
  detail page specifically (picked up automatically by
  `oarepo_ui/record_detail.html`'s `javascript` block via `{% include
  model_name ~ "/record_detail/javascript.html" ignore missing %}`).
- **`semantic-ui/js/<model>/`** — React/JSX source. Existing convention:
  `search/` (custom result-list item + custom facet filter inputs,
  wired into react-searchkit via `componentOverrides` — see
  `docs/CUSTOM_FILTERS_HOWTO.md`) and `forms/` (deposit form
  customization, mounted via classic `ReactDOM.render(<DepositFormApp
  config={...}/>, el)` against a server-rendered config JSON). **There
  are two genuinely different React-mounting patterns already in use in
  this codebase** — react-searchkit's `componentOverrides` (search-page
  slots only) vs. plain "data-attribute div + manual
  `ReactDOM.render`" (any other page, e.g. the sidebar "manage record"
  menu in `ui/components/semantic-ui/js/record-management/`) — pick the
  one matching where on the page you're injecting UI, do not force
  react-searchkit's mechanism onto a non-search page.

## 5. Where to find things / "don't reinvent this" pointers

- **Permissions & workflows**: `common/workflows/default.py` defines
  `DefaultWorkflowPermissions` (subclassing
  `oarepo_communities.CommunityDefaultWorkflowPermissions`) — the
  `can_read`, `can_read_files`, `can_create`, `can_update`, etc.
  attributes that determine who can do what to a record depending on its
  state (`draft`/`submitted`/`published`/`retracting`/`deleted`) and
  community role (`submitter`/`curator`/`owner`, or
  `RecordOwners()`/`AnyUser()`/`PrimaryCommunityMembers()` generators
  from `invenio_records_permissions`/`oarepo_communities`/
  `oarepo_runtime`). Also defines `WorkflowRequest`/
  `WorkflowRequestPolicy` objects for the request-approval workflow
  (delete, DOI assignment, community migration, etc.), each with
  `requesters=`/`recipients=`/`transitions=`/`escalations=`. A model can
  override/extend this via a `PrependMixin("PermissionPolicy", ...)`
  customization in its `model.py` (see `FramPermissionPolicyMixin` in
  `models/fram/model.py` for a minimal example — adding
  `can_view_deposit_page` for authenticated users). **Before writing a
  permission check anywhere else** (a Flask view, a component, etc.),
  check whether it should instead be expressed as one of these
  declarative generators/attributes — see
  `docs/FITS_IMAGE_PREVIEW.md`'s FITS-preview view for an example of a
  Flask view that *does* need its own permission check (because it's a
  raw non-content-negotiated route, not going through the standard
  service layer) vs. relying on `service.read()`/`file_service.list_files()`
  to raise `PermissionDeniedError` for the common case.
- **Custom search filters/facets**: `docs/CUSTOM_FILTERS_HOWTO.md` (in
  Czech) is the definitive howto — read section 8 ("Časté chyby") for
  four already-diagnosed silent-failure traps before writing a new
  facet. Reference implementations: `models/fram/facets.py`,
  `models/sipm/facets.py`, `models/atlas_itk/facets.py`.
- **Sky-position/geospatial search**: `docs/SKY_POSITION_SEARCH.md` — a
  session handoff document (written mid-implementation, so it contains
  some "not yet verified"/"unresolved" notes — check current
  `models/fram/facets.py`/`model.py` state before trusting anything
  marked unresolved there, it may have been fixed since).
- **Vocabularies** (controlled term lists, e.g. resource types,
  experiments, particle categories): declared in `app_data/*.yaml` +
  `app_data/vocabularies/*.yaml` data files, loaded via
  `config.configure_vocabulary(...)` calls in `invenio.cfg` (currently
  commented out/example-only for custom ones) or the
  `PrioritizedVocabulariesFixtures` mechanism patched in `invenio.cfg`
  to load synchronously instead of via background task (see the
  `new_vocabulary_fixtures_init` monkey-patch at the bottom of
  `invenio.cfg` — a deliberate workaround, not accidental cruft).
- **Translations**: `i18n/` (backend catalog + i18n JS webpack entry) +
  `translations/` (compiled output) + per-model `.po` files potentially
  under each model/ui package (not exhaustively inventoried this
  session) — managed via `./run.sh translations` (extract/merge/compile
  through `oarepo-tools`), not hand-edited `.mo` files.
- **Site-wide (non-model) template overrides**: `templates/` —
  header/footer/frontpage/page layout, the About page. See
  `templates/README.md`. Distinct from `ui/<model>/templates/` which are
  model-specific.
- **Homepage customization** (e.g. "browse by experiment" widget):
  `docs/HOMEPAGE_BROWSE_BY_EXPERIMENT.md` (not reviewed in depth this
  session — consult it directly for that feature).

## 6. Local dev environment & tooling (`run.sh` / `.runner.sh`)

`./run.sh <subcommand>` is a thin wrapper that auto-downloads
`.runner.sh` from the upstream `oarepo` GitHub repo on first use (do not
hand-edit `.runner.sh`, `self-update` overwrites it). Key subcommands
(confirmed by reading `.runner.sh` source directly, not just `--help`
text):

- **`./run.sh run [--no-services] [--no-celery]`** — starts Docker
  services (unless `--no-services`), then either runs the full
  `invenio-cli run` stack (dev server + Celery worker/beat, the default)
  or (with `--no-celery`) just `invenio run --cert ... --key ...`
  directly via `activate_venv`. This is what you use for routine
  dev/testing — **never `reset` just to restart the server**, this
  subcommand is what you actually want almost always. The server listens
  on `https://127.0.0.1:5000` (self-signed dev cert in `docker/`).
- **`./run.sh reset`** — **destructive**: prompts for confirmation, then
  `services destroy` (removes Docker containers/volumes for
  postgres/opensearch/redis/rabbitmq/minio — **all data lost**), removes
  `.venv`, `uv.lock`, `.invenio.private`, cleans the `uv` cache, then
  fully reinstalls (`install_repository`) and re-runs `services setup`,
  creates an `administration` role and a default `user@demo.org` account.
  **Only use this when you actually need a from-scratch environment**
  (e.g. after a major dependency/model schema change that can't be
  reconciled incrementally) — it is not a "restart the server" command
  and was mistakenly reached for during this session's own FITS-preview
  work before being corrected; do not repeat that mistake.
- **`./run.sh install`** — `uv sync` + `invenio-cli install` (installs
  Python deps, builds webpack assets, sets up instance config) without
  wiping existing data — this is what actually triggers a webpack
  asset rebuild after adding/changing a `webpack.py` entry or JS/JSX
  source file. (`./run.sh upgrade` does the same but first wipes
  `.venv`/`uv.lock`/`uv` cache — a "clean reinstall" short of a full
  data-destroying `reset`.)
- **`./run.sh model create <name> [config-file]`** /
  **`./run.sh model update <name> [answers-file]`** — invokes the
  Copier-based `nrp-model-copier` scaffolding tool referenced by each
  model's `.copier-answers.yml` (see section 3's caution note about this).
- **`./run.sh services {start|stop|destroy|setup}`** — Docker Compose
  lifecycle for `docker/docker-compose.yml` (postgres/opensearch/redis/
  rabbitmq/minio, container names `physica-db-1`, `physica-search-1`,
  `physica-cache-1`, `physica-mq-1`, `physica-s3-1` — confirm via `docker
  ps`).
- **`./run.sh index rebuild`** — `invenio index destroy --yes-i-know` +
  `invenio index init` + custom-fields init + `invenio rdm
  rebuild-all-indices`. Only touches search indices, not the DB/files —
  use this (not a full `reset`) if OpenSearch mappings/indices need
  regenerating after a model's `metadata.yaml`/`PatchIndexPropertyMapping`
  changes.
- **`./run.sh cli <subcommand>`** — passthrough to the underlying
  `invenio-cli` tool.
- **`./run.sh translations [compile]`** — extract/merge/compile
  translations via `oarepo-tools`.

**MinIO note** (from `README.md`): after a fresh `reset`, you must
manually create a bucket named `default` in the MinIO web console
(`http://localhost:9001`, credentials `aa-physica-aa`/`aaa-physica-aaa`)
before file uploads will work.

**Uploading sample/test records**: use `nrp-cmd` (installed via `uvx`,
not a repo dependency) against a configured repository alias (see
`README.md`'s "Get the token" section for `nrp-cmd add repository`).
Each model has a `sample_data/<Model>/upload_sample_*.sh` script showing
the create-draft → upload-file → publish sequence via `nrp-cmd create
record` / `nrp-cmd upload file` / `nrp-cmd publish record`. Use these as
the reference pattern for any new sample-data upload script, rather than
inventing a different upload mechanism.

**Running one-off Python against the live app context**: `invenio shell
/path/to/script.py` (as used throughout this session's own FITS-preview
verification) gives you a Flask app context with all models registered —
useful for direct `current_runtime.models[...]`/service-layer
inspection/testing without going through HTTP. `g.identity` is not set
in a bare invenio-shell script; use `invenio_access.permissions.
system_identity` for full-access scripted checks, or build a
`current_app.test_request_context(...)` + set `g.identity` manually if
you need to exercise an actual Flask view function directly (as opposed
to the service layer) outside of a real HTTP request.

## 7. Key package versions in use (captured from the live `.venv`)

Python **3.14** (`requires-python = ">=3.14,<3.15"` in `pyproject.toml`).
This project tracks **pre-release** versions of the oarepo/Invenio stack:

| Package | Version |
|---|---|
| `oarepo` | 14.2.1rc2+5.rdm.14.0.0rc2 |
| `oarepo-app` | 6.3.0 |
| `oarepo-runtime` | 7.3.0 |
| `oarepo-ui` | 13.5.1 |
| `oarepo-model` | 5.3.0 |
| `oarepo-rdm` | 8.4.1 |
| `ccmm-invenio` | 1.1.21 |
| `invenio-app-rdm` | 14.0.0rc2+oarepo.1... |
| `invenio-rdm-records` | 32.0.2+oarepo.1... |
| `flask` | 3.1.3 |
| `flask-resources` | 1.3.1 |

Because of the pre-release versions and a private CESNET package index,
**`uv lock`/`uv sync` require extra env vars** when run outside of
`./run.sh` (which sets them automatically — see `.runner.sh` lines near
`UV_PRERELEASE`/`UV_EXTRA_INDEX_URL`):
```bash
UV_PRERELEASE=allow \
UV_EXTRA_INDEX_URL='https://gitlab.cesnet.cz/api/v4/projects/1408/packages/pypi/simple' \
uv lock   # or: uv sync
```
Without these, `uv lock` fails with `No solution found ... oarepo-app[production]==6.3.0`
(the exact error hit and diagnosed during this session's FITS-preview
dependency work).

**Reading upstream source**: since so much behavior lives in installed
packages rather than this repo, expect to frequently need to read
`.venv/lib/python3.14/site-packages/<package>/...` directly to
understand available extension points, base classes, and config options
— this repo's own code is often just a thin customization layer whose
correct usage can only be understood by reading what it's customizing.
Never edit files under `.venv` — changes there are silently lost on the
next `uv sync`/dependency upgrade; always find the intended
extension/customization point instead (subclassing, `customizations=`
lists, Jinja block overrides, component classes, entry points).

## 8. Tests

`tests/` currently contains a small number of **standalone Python
scripts** (e.g. `test_cone_search.py`, `test_custom_filter_config.py`),
not a full pytest fixture-based suite with a conftest/app-context setup.
Some (like `test_cone_search.py`) are explicitly designed to test pure
query-building logic without needing a running OpenSearch/Docker stack —
check each test file's own module docstring for how it's meant to be
run before assuming a standard `pytest tests/` invocation works
end-to-end for every file in this directory. When adding a new test,
match the style of the nearest existing analog rather than introducing a
new testing convention/framework choice unprompted.

## 9. Summary: mental model for making a change here

1. Identify which of the 4 models (or "site-wide"/`common`) the change
   belongs to.
2. Check whether the desired behavior is a **preset feature** already
   provided by `ccmm_production_preset_1_1_0` / `oarepo_model` /
   `oarepo_ui` / `oarepo_rdm` before writing new code — read the
   relevant `.venv/.../oarepo_*` source to confirm what's already there.
3. If it's metadata/schema/facet-related → `models/<name>/metadata.yaml`
   (+ `facets.py` if a custom facet class is needed) + `model.py`
   `customizations=` for anything that can't be expressed in YAML.
4. If it's page-rendering/HTML-related → a template override under
   `ui/<name>/templates/semantic-ui/<name>/...`, following the
   `{% extends %}` + block-override + `{{ super() }}` convention.
5. If it's interactive/React-related → JS/JSX under
   `ui/<name>/semantic-ui/js/<name>/...` + a `webpack.py` entry, using
   whichever of the two mounting patterns (react-searchkit
   `componentOverrides` vs. plain mount-div) matches the target page.
6. If it needs a genuinely new HTTP endpoint outside the standard
   record/search/deposit routes (rare) → register it directly on the
   model's UI blueprint inside `create_blueprint(app)` in
   `ui/<name>/__init__.py` (see the FITS preview endpoint for a complete
   worked example, documented in `docs/FITS_IMAGE_PREVIEW.md`).
7. If it's a dependency change → update `pyproject.toml`, then regenerate
   `uv.lock` with the `UV_PRERELEASE`/`UV_EXTRA_INDEX_URL` env vars from
   section 7.
8. Test using `./run.sh run` against the existing Docker services and
   sample data — reserve `./run.sh reset` for genuinely
   schema/environment-breaking changes, and remember the bundled sample
   records currently have **restricted file access** by default (so
   anonymous/no-permission requests correctly see reduced UI — that's
   expected, not a bug, when manually verifying file-related features).
