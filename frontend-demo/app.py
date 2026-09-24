"""Small host-run frontend for the Docker API."""

import json
import os
from pathlib import Path
from urllib import error as url_error
from urllib import request as url_request

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template


FRONTEND_ROOT = Path(__file__).resolve().parent


def load_dashboard(api_url):
    """Read the current module or return an empty offline page."""
    try:
        with url_request.urlopen(f"{api_url}/api/dashboard", timeout=8) as response:
            return json.loads(response.read().decode("utf-8")), None
    except (OSError, ValueError, json.JSONDecodeError, url_error.HTTPError):
        return {
            "module": None,
            "assessments": [],
            "records_loaded": 0,
            "schedule": {"blocks": [], "weeks": [], "warnings": []},
        }, f"Docker API is unavailable at {api_url}."


def create_app(configured_api_url=None):
    """Create the presentation-only Flask app."""
    load_dotenv(FRONTEND_ROOT.parent / ".env", override=False)
    api_url = (
        configured_api_url
        or os.getenv("STACKPLAN_API_URL", "http://127.0.0.1:8000")
    ).rstrip("/")
    app = Flask(
        __name__,
        template_folder=str(FRONTEND_ROOT / "templates"),
        static_folder=str(FRONTEND_ROOT / "static"),
    )

    @app.get("/")
    def index():
        dashboard, connection_error = load_dashboard(api_url)
        return render_template(
            "index.html",
            **dashboard,
            api_base_url=api_url,
            connection_error=connection_error,
        )

    @app.get("/api/schedule")
    def schedule_api():
        dashboard, connection_error = load_dashboard(api_url)
        if connection_error:
            return jsonify({"errors": [connection_error]}), 503
        return jsonify(dashboard)

    @app.get("/health")
    def health():
        _dashboard, connection_error = load_dashboard(api_url)
        return jsonify({"ok": connection_error is None}), (
            200 if connection_error is None else 503
        )

    return app


if __name__ == "__main__":
    create_app().run(
        host="127.0.0.1",
        port=int(os.getenv("FRONTEND_PORT", "5050")),
        debug=False,
    )
