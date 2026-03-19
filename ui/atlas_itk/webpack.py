from invenio_assets.webpack import WebpackThemeBundle

theme = WebpackThemeBundle(
    __name__,
    ".",
    default="semantic-ui",
    themes={
        "semantic-ui": dict(
            entry={
                "atlas_itk_search": "./js/atlas_itk/search/index.js",
                "atlas_itk_deposit_form": "./js/atlas_itk/forms/index.js",
            },
            dependencies={},
            devDependencies={},
            aliases={
                "@js/atlas_itk": "./js/atlas_itk"
            },
        )
    },
)
