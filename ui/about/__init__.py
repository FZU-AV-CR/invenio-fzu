from flask import Blueprint, render_template

def create_blueprint(app):
    blueprint = Blueprint(
        "about",
        __name__,
        template_folder="../../templates",
    )

    @blueprint.route("/about")
    def about():
        return render_template("invenio_fzu/about.html")

    return blueprint