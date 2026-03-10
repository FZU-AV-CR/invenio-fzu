from invenio_assets.webpack import WebpackThemeBundle

theme = WebpackThemeBundle(
    __name__,
    ".",
    default="semantic-ui",
    themes={
        "semantic-ui": dict(
            entry={
                "fram_search": "./js/fram/search/index.js",
                "fram_deposit_form": "./js/fram/forms/index.js",
            },
            dependencies={},
            devDependencies={},
            aliases={
                "@js/fram": "./js/fram"
            },
        )
    },
)
