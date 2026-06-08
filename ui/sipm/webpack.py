from invenio_assets.webpack import WebpackThemeBundle

theme = WebpackThemeBundle(
    __name__,
    ".",
    default="semantic-ui",
    themes={
        "semantic-ui": dict(
            entry={
                "sipm_search": "./js/sipm/search/index.js",
                "sipm_deposit_form": "./js/sipm/forms/index.js",
            },
            dependencies={},
            devDependencies={},
            aliases={"@js/sipm": "./js/sipm"},
        )
    },
)
