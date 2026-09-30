# FRAM search page model description

## 1. What this is

On the FRAM search page (`https://127.0.0.1:5000/fram/`), right above
the search bar / facets sidebar / results list, there are two short
lines of text introducing what the FRAM model contains: who operates
the data, which community/license it belongs to, and what kind of
files/observations it holds.

This doc explains how it is implemented, and how to:

- change the text,
- add a translation for a new language,
- add the same pattern to another model (SiPM, ATLAS ITk, Particles),
- rebuild/restart the app so changes actually show up.

---

## 2. How it is implemented

### 2.1 Template override

Each model's search page is rendered through a small model-owned
template that exists purely to be extended — normally an empty stub:

```jinja
{% extends "oarepo_ui/record_search.html" %}
```

This is the file at `ui/<model>/templates/semantic-ui/<model>/record_search.html`,
sitting at the path expected by `_TEMPLATE_MAP["search"]` and extended
by the `oarepo_ui.pages.RecordSearch` JinjaX component. The parent
template (`oarepo_ui/record_search.html`) defines the `page_body` block
that ultimately renders the single `<div data-invenio-search-config=...>`
mount point that the React search app (`SearchApp`) attaches to:

```jinja
{%- block page_body %}
<div class="ui main container rel-mt-3">
  <div data-invenio-search-config='{{ search_app_config | tojson }}'></div>
</div>
{%- endblock page_body %}
```

For FRAM, `ui/fram/templates/semantic-ui/fram/record_search.html`
overrides that same `page_body` block, prepends the two description
lines, then calls `{{ super() }}` so the original search-config `<div>`
still renders immediately below (the `{% extends %}` + block-override +
`{{ super() }}` convention used throughout this repo, e.g. for the
"Browse by experiment" homepage buttons — see
`docs/HOMEPAGE_BROWSE_BY_EXPERIMENT.md`):

```jinja
{% extends "oarepo_ui/record_search.html" %}

{%- block page_body %}
<div class="ui container rel-mt-3">
  <p class="search-page-intro standard-line-height">{{ _("fram_search_intro_line1") }}</p>
  <p class="search-page-intro standard-line-height rel-mb-2">{{ _("fram_search_intro_line2") }}</p>
</div>
{{ super() }}
{%- endblock page_body %}
```

Because `page_body` is rendered server-side by Jinja before the React
search app mounts, the two lines appear above *everything* the search
app renders (search bar, facets, active filters, result count/sort,
results list) — no JS/React changes were needed for this.

`standard-line-height` already existed in
`assets/less/site/globals/site.overrides` (used elsewhere for
record-detail small text). `search-page-intro` is a new small LESS
rule added specifically for this feature, to center the text and make
it 1.5x the base font size:

```less
.search-page-intro {
  text-align: center;
  font-size: 1.5em;
}
```

Since this is a LESS/CSS change (not a plain Jinja/HTML change), it
requires a webpack rebuild to take effect — see section 5.

### 2.2 Text / translations

The two lines are translatable strings, defined as `msgid`/`msgstr`
pairs in:

- `translations/en/LC_MESSAGES/messages.po` (English)
- `translations/cs/LC_MESSAGES/messages.po` (Czech)

under a `## FRAM search page` section:

```po
msgid "fram_search_intro_line1"
msgstr "FRAM observation data, operated by the Institute of Physics of the Czech Academy of Sciences (FZÚ) — part of the \"fram\" community, licensed under CC-BY 4.0."

msgid "fram_search_intro_line2"
msgstr "FITS images (plus calibration darks/master-flats) from the robotic telescope network at sites cta-n, cta-s0, cta-s1, auger and auger2, capturing atmospheric and astronomical-object observations."
```

and the Czech equivalents:

```po
msgid "fram_search_intro_line1"
msgstr "Pozorovací data FRAM, provozovaná Fyzikálním ústavem AV ČR (FZÚ) — součást komunity „fram“, licencováno CC-BY 4.0."

msgid "fram_search_intro_line2"
msgstr "FITS snímky (včetně kalibračních temných snímků a master-flatů) ze sítě robotických dalekohledů na stanovištích cta-n, cta-s0, cta-s1, auger a auger2, zachycující atmosférická a astronomická pozorování."
```

Line 1 covers ownership/governance (FZÚ, the `fram` community, CC-BY
4.0 license — note the data/metadata itself is public, but that does
not imply the `fram` community is open to everyone, so line 1
deliberately avoids the word "public" next to "community"); line 2
covers content (FITS images plus calibration darks/master-flats, the
five observatory sites, atmospheric/astronomical observation purpose).

---

## 3. How to change the text

1. Edit the `msgstr` value for `fram_search_intro_line1` /
   `fram_search_intro_line2` in both `.po` files (keep them in sync —
   the Czech version should be a translation of the same idea, not new
   content, unless you intend the two languages to diverge).
2. Recompile the `.mo` catalogs (Flask-Babel reads the compiled binary
   `.mo` files, not the `.po` source):

   ```bash
   cd /home/erutherford/invenio-fzu
   .venv/bin/pybabel compile -d translations -D messages
   ```

3. **Restart the Invenio dev server** — Flask-Babel caches loaded
   catalogs in memory, so a simple browser refresh will not pick up
   the new `.mo` content even though the file on disk changed.

---

## 4. How to add the same pattern to another model

The same recipe generalizes to SiPM / ATLAS ITk / Particles:

1. In `ui/<model>/templates/semantic-ui/<model>/record_search.html`,
   add a `page_body` block override following the FRAM example above
   (swap the two `msgid` keys for model-specific ones, e.g.
   `sipm_search_intro_line1`).
2. Add the corresponding `msgid`/`msgstr` pairs to both `.po` files.
3. Recompile (`pybabel compile -d translations -D messages`) and
   restart the dev server.

---

## 5. Rebuilding / restarting after changes

| You changed... | You must run... |
|---|---|
| `ui/<model>/templates/semantic-ui/<model>/record_search.html` (Jinja/HTML) | Nothing extra — Flask's dev reloader re-reads `.html` templates on every request. Just refresh the browser. |
| `translations/**/messages.po` (the two lines' text) | 1. `.venv/bin/pybabel compile -d translations -D messages` to regenerate the `.mo` files. 2. **Restart the Invenio dev server** (`Ctrl+C` then `./run.sh run` again) — translation catalogs are cached in memory. |
| `assets/less/site/globals/site.overrides` (`.search-page-intro` size/alignment) | `.venv/bin/invenio webpack build` to recompile the LESS/CSS bundle, then hard-refresh the browser (`Ctrl+Shift+R`) in case the compiled CSS asset was cached. |

```bash
cd /home/erutherford/invenio-fzu
.venv/bin/pybabel compile -d translations -D messages
.venv/bin/invenio webpack build
# stop the currently running ./run.sh run (Ctrl+C), then:
./run.sh run
```

---

## 6. Files touched by this feature (for reference)

- `ui/fram/templates/semantic-ui/fram/record_search.html` — the
  `page_body` block override adding the two `<p>` lines above
  `{{ super() }}`.
- `translations/en/LC_MESSAGES/messages.po` /
  `translations/cs/LC_MESSAGES/messages.po` — `fram_search_intro_line1`
  / `fram_search_intro_line2` msgid/msgstr entries (English/Czech),
  plus their compiled `.mo` counterparts.
- `assets/less/site/globals/site.overrides` — the `.search-page-intro`
  class (centered, 1.5x font size).
