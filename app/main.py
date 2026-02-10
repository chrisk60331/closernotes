"""Flask application factory for CloserNotes."""

import re

from flask import Flask, render_template

from app.config import get_settings

# Matches a trailing space + exactly 6 hex chars at end of string
_HEX_SUFFIX_RE = re.compile(r"\s+[0-9a-fA-F]{6}$")


def create_app() -> Flask:
    """Create and configure the Flask application."""
    settings = get_settings()

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    app.secret_key = settings.flask_secret_key

    # Store settings in app config
    app.config["SETTINGS"] = settings

    # Register blueprints
    from app.api.ingest import ingest_bp
    from app.api.customers import customers_bp
    from app.api.meetings import meetings_bp
    from app.api.crm import crm_bp
    from app.api.followup import followup_bp
    from app.api.action_items import action_items_bp
    from app.api.transcribe import transcribe_bp
    from app.api.auth import auth_bp
    from app.api.users import users_bp
    from app.api.health import health_bp

    app.register_blueprint(ingest_bp, url_prefix="/api")
    app.register_blueprint(customers_bp, url_prefix="/api")
    app.register_blueprint(meetings_bp, url_prefix="/api")
    app.register_blueprint(crm_bp, url_prefix="/api")
    app.register_blueprint(followup_bp, url_prefix="/api")
    app.register_blueprint(action_items_bp, url_prefix="/api")
    app.register_blueprint(transcribe_bp, url_prefix="/api")
    app.register_blueprint(users_bp, url_prefix="/api")

    # Register auth routes (no /api prefix for login/signup pages)
    app.register_blueprint(auth_bp)

    # Register health check route for App Runner
    app.register_blueprint(health_bp)

    # Register UI routes
    from app.api.ui import ui_bp

    app.register_blueprint(ui_bp)

    # Jinja filter: strip trailing 6-char hex dedup suffix from company names
    @app.template_filter("display_name")
    def display_name_filter(value: str | None) -> str:
        if not value:
            return "Unknown"
        return _HEX_SUFFIX_RE.sub("", value)

    # ---- Custom error pages ----
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template("500.html"), 500

    return app
