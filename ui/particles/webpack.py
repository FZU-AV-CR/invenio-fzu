from invenio_assets.webpack import WebpackThemeBundle

theme = WebpackThemeBundle(
    __name__,
    ".",
    default="semantic-ui",
    themes={
        "semantic-ui": dict(
            entry={
                "particles_search": "./js/particles/search/index.js",
                "particles_deposit_form": "./js/particles/forms/index.js",
            },
            dependencies={},
            devDependencies={},
            aliases={"@js/particles": "./js/particles"},
        )
    },
)
