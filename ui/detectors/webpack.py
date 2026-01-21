from invenio_assets.webpack import WebpackThemeBundle

theme = WebpackThemeBundle(
    __name__,
    ".",
    default="semantic-ui",
    themes={
        "semantic-ui": dict(
            entry={
                "detectors_search": "./js/detectors/search/index.js",
                "detectors_deposit_form": "./js/detectors/forms/index.js",
            },
            dependencies={},
            devDependencies={},
            aliases={"@js/detectors": "./js/detectors"},
        )
    },
)
