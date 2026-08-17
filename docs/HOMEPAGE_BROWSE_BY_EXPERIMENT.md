# Homepage "Browse by experiment" buttons

## 1. What this is

On the frontpage (`https://127.0.0.1:5000/`), between the intro/welcome
section and the "Recent uploads" records list, there is a small section
titled **"Browse by experiment:"** with one button per model/schema
registered in this repository (currently `Fram`, `ITk`, `Particles`,
`SiPM`). Each button links directly to that model's search page, e.g.
FRAM's button links to `https://127.0.0.1:5000/fram/?q=&l=list&p=1&s=10`.

This doc explains how it is implemented, and how to:

- add a button for a new model/experiment,
- change the button color,
- change the button labels / translations,
- rebuild and restart the app so changes actually show up.

---

## 2. How it is implemented

### 2.1 Template override

The frontpage template in this repo (`templates/frontpage.html`) extends
the frontpage template that ships with `oarepo_ui`/`invenio_app_rdm`
(`oarepo_ui/templates/oarepo_ui/frontpage.html`, which itself extends
`invenio_app_rdm/frontpage.html`). That parent template exposes several
overridable Jinja blocks (see the comment at the bottom of
`templates/frontpage.html` for the full list). We use the `top_banner`
block, which renders right after the intro section and right before the
"Recent uploads" grid — exactly where we want our links:

```jinja
{% extends "oarepo_ui/frontpage.html" %}

{%- block top_banner %}
  {{ super() }}
  <div class="ui container rel-mt-2 rel-mb-2">
    <h2 class="ui header text-align-center">{{ _("browse_by_experiment_title") }}</h2>
    <div class="ui four stackable buttons rel-mt-2" role="navigation" aria-label="{{ _('browse_by_experiment_title') }}">
      <a class="ui button browse-experiment-button" href="{{ url_for('fram_ui.search') }}">{{ _("browse_by_experiment_fram") }}</a>
      <a class="ui button browse-experiment-button" href="{{ url_for('atlas_itk_ui.search') }}">{{ _("browse_by_experiment_atlas_itk") }}</a>
      <a class="ui button browse-experiment-button" href="{{ url_for('particles_ui.search') }}">{{ _("browse_by_experiment_particles") }}</a>
      <a class="ui button browse-experiment-button" href="{{ url_for('sipm_ui.search') }}">{{ _("browse_by_experiment_sipm") }}</a>
    </div>
  </div>
{%- endblock top_banner %}
```

`{{ super() }}` keeps whatever the parent template already renders in
that block (e.g. the communities carousel), so we only *add* content,
we don't replace anything.

Each link uses Flask's `url_for()` with the Invenio blueprint endpoint
name for that model's UI search page, instead of a hardcoded URL. Every
model's UI blueprint (see `ui/<model>/__init__.py`, e.g.
`ui/fram/__init__.py`) registers a `RecordsUIResource` with a
`blueprint_name` (e.g. `fram_ui`), and `oarepo_ui` automatically wires
up a `search` view for it, so the resulting endpoint is
`"<blueprint_name>.search"` (e.g. `fram_ui.search` → `/fram/`). Using
`url_for()` means the links stay correct even if a model's `url_prefix`
changes later.

### 2.2 Labels / translations

The title and the four button labels are translatable strings, defined
as `msgid`/`msgstr` pairs in:

- `translations/en/LC_MESSAGES/messages.po` (English)
- `translations/cs/LC_MESSAGES/messages.po` (Czech)

under the `## Browse by experiment (frontpage)` section:

```po
msgid "browse_by_experiment_title"
msgstr "Browse by experiment:"

msgid "browse_by_experiment_fram"
msgstr "Fram"

msgid "browse_by_experiment_atlas_itk"
msgstr "ITk"

msgid "browse_by_experiment_particles"
msgstr "Particles"

msgid "browse_by_experiment_sipm"
msgstr "SiPM"
```

These `.po` files are human-editable source files. They must be
**compiled** into binary `.mo` catalogs before Flask-Babel/invenio-i18n
will actually use the new text (see section 5).

### 2.3 Button color

By default Semantic UI's `ui button` class renders a plain grey button.
To make these four buttons light blue, a dedicated CSS class
`browse-experiment-button` was added and applied to each `<a>` tag.

The color itself is defined as a LESS variable in
`assets/less/site/globals/site.variables`, derived from the theme's
existing brand blue (`@secondaryColour`) so it stays visually consistent
with the rest of the site:

```less
@lightBlueColor: lighten(@secondaryColour, 25);
@lightBlueColorHover: darken(@lightBlueColor, 10, relative);
```

And the class itself is defined in
`assets/less/site/globals/site.overrides`:

```less
.browse-experiment-button {
  background-color: @lightBlueColor !important;
  color: @white !important;

  &:hover, &:focus {
    background-color: @lightBlueColorHover !important;
    color: @white !important;
  }
}
```

Like all LESS changes, this must be **rebuilt** with webpack before it
shows up in the browser (see section 5).

---

## 3. How to add a button for a new model/experiment

Say a new model `ccd` is added under `models/ccd/` with its own UI
blueprint `ui/ccd/__init__.py` (`blueprint_name = "ccd_ui"`, registered
in `pyproject.toml` under `[project.entry-points."invenio_base.blueprints"]`
as `ui_ccd = "ui.ccd:create_blueprint"`).

1. **Add the button markup** in `templates/frontpage.html`, inside the
   `.ui.buttons` div (and update the `ui four stackable buttons` class
   to `ui five stackable buttons` — the leading number should match the
   total number of buttons so Semantic UI sizes them evenly):

   ```jinja
   <a class="ui button browse-experiment-button" href="{{ url_for('ccd_ui.search') }}">{{ _("browse_by_experiment_ccd") }}</a>
   ```

2. **Add the translation strings** to both `.po` files
   (`translations/en/LC_MESSAGES/messages.po` and
   `translations/cs/LC_MESSAGES/messages.po`), next to the other
   `browse_by_experiment_*` entries:

   ```po
   msgid "browse_by_experiment_ccd"
   msgstr "CCD"
   ```

   (use the appropriate Czech label in the `cs` file).

3. **Compile translations, rebuild assets and restart** — see section 5
   below. Without these steps the new button/label will not appear
   even though the source files are correct.

4. **Verify the endpoint name** if unsure: the endpoint is always
   `"<blueprint_name>.search"`. You can check any model's
   `blueprint_name` in its `ui/<model>/__init__.py` (`*UIResourceConfig`
   class), or dump all registered routes from a shell:

   ```bash
   .venv/bin/invenio shell -c "
   from flask import current_app
   for rule in current_app.url_map.iter_rules():
       if rule.endpoint.endswith('.search'):
           print(rule.endpoint, rule.rule)
   "
   ```

---

## 4. How to change the button color

1. Edit the LESS variable(s) in
   `assets/less/site/globals/site.variables`:

   ```less
   @lightBlueColor: lighten(@secondaryColour, 25);
   @lightBlueColorHover: darken(@lightBlueColor, 10, relative);
   ```

   Change the base color/formula here (e.g. use a different theme
   variable, or a plain hex value like `#4fb0ff`), or rename the
   variable if you like — just make sure the name matches what
   `site.overrides` references.

2. The actual class applied to the buttons lives in
   `assets/less/site/globals/site.overrides`:

   ```less
   .browse-experiment-button {
     background-color: @lightBlueColor !important;
     color: @white !important;

     &:hover, &:focus {
       background-color: @lightBlueColorHover !important;
       color: @white !important;
     }
   }
   ```

   You can also make individual buttons different colors by adding a
   second class (e.g. `browse-experiment-button--fram`) to a specific
   `<a>` in `templates/frontpage.html` and a matching LESS rule.

3. **Rebuild assets** (`invenio webpack build`, see section 5) — plain
   CSS/LESS changes are NOT picked up automatically like Jinja
   templates are; they must be recompiled.

---

## 5. Rebuilding / restarting after changes

Two independent caches need to be refreshed depending on what you
changed:

| You changed... | You must run... |
|---|---|
| `templates/frontpage.html` (Jinja/HTML) | Nothing extra — Flask's dev reloader re-reads `.html` templates on every request. Just refresh the browser. |
| `translations/**/messages.po` (labels) | 1. `.venv/bin/pybabel compile -d translations -D messages` to regenerate the `.mo` files. 2. **Restart the Invenio dev server** (`Ctrl+C` then `./run.sh run` again, or restart however you normally run it) — Flask-Babel caches loaded catalogs in memory, so translation text does not refresh on a simple browser reload, even though the `.mo` file on disk changed. |
| `assets/less/**/*.less` or `*.overrides`/`*.variables` (CSS/colors) | `.venv/bin/invenio webpack build` to recompile the LESS/JS bundles, then hard-refresh the browser (`Ctrl+Shift+R`) in case the compiled CSS asset was cached. |

If you changed both translations and LESS (as we did for this feature),
run both steps, then restart the server:

```bash
cd /home/erutherford/invenio-fzu
.venv/bin/pybabel compile -d translations -D messages
.venv/bin/invenio webpack build
# stop the currently running ./run.sh run (Ctrl+C), then:
./run.sh run
```

---

## 6. Files touched by this feature (for reference)

- `templates/frontpage.html` — the `top_banner` block override with the
  four buttons.
- `translations/en/LC_MESSAGES/messages.po` /
  `translations/cs/LC_MESSAGES/messages.po` — `browse_by_experiment_*`
  msgid/msgstr entries (English/Czech).
- `assets/less/site/globals/site.variables` — `@lightBlueColor` /
  `@lightBlueColorHover` LESS variables.
- `assets/less/site/globals/site.overrides` — `.browse-experiment-button`
  CSS class.
