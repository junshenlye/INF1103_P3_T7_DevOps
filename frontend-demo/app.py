"""Host-run presentation layer for the Docker API."""

import json
import os
from pathlib import Path
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request


FRONTEND_ROOT = Path(__file__).resolve().parent


def empty_dashboard():
    """Return a renderable state while Docker is unavailable."""
    return {
        "schedule": {"blocks": [], "weeks": [], "excluded_records": [], "warnings": []},
        "module_profiles": {},
        "latest_records": [],
        "records_loaded": 0,
        "focus_module": None,
    }


def request_api(api_base_url, path, method="GET", payload=None):
    """Exchange one small JSON request with the Docker API."""
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    api_request = url_request.Request(
        f"{api_base_url}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with url_request.urlopen(api_request, timeout=8) as response:
            return json.loads(response.read().decode("utf-8")), response.status
    except url_error.HTTPError as api_error:
        try:
            response_payload = json.loads(api_error.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            response_payload = {"errors": ["The local API rejected the request."]}
        return response_payload, api_error.code


def load_dashboard(api_base_url, focus_module=None):
    """Read one module view from Docker with a friendly offline state."""
    query = ""
    if focus_module:
        query = "?" + url_parse.urlencode({"module": focus_module})
    try:
        summary, _status = request_api(api_base_url, f"/api/dashboard{query}")
        return summary, None
    except (OSError, ValueError, json.JSONDecodeError):
        return empty_dashboard(), (
            f"Docker API is unavailable at {api_base_url}. "
            "Start it with: docker compose up --build"
        )


def create_app(configured_api_url=None):
    """Create the host frontend without module-level application state."""
    load_dotenv(FRONTEND_ROOT.parent / ".env", override=False)
    api_base_url = (
        configured_api_url
        or os.getenv("STACKPLAN_API_URL", "http://127.0.0.1:8000")
    ).rstrip("/")
    app = Flask(
        __name__,
        template_folder=str(FRONTEND_ROOT / "templates"),
        static_folder=str(FRONTEND_ROOT / "static"),
    )

    def render_dashboard(result=None, status_code=200, focus_module=None):
        summary, connection_error = load_dashboard(api_base_url, focus_module)
        return (
            render_template(
                "index.html",
                **summary,
                result=result,
                form_values={},
                api_base_url=api_base_url,
                connection_error=connection_error,
            ),
            status_code,
        )

    @app.get("/")
    def index():
        return render_dashboard(focus_module=request.args.get("module"))

    @app.post("/review/<record_id>")
    def review_assessment(record_id):
        try:
            result, status_code = request_api(
                api_base_url,
                f"/api/assessments/{record_id}/review",
                method="POST",
                payload=request.form.to_dict(),
            )
        except (OSError, ValueError, json.JSONDecodeError):
            result = {"ok": False, "errors": ["The Docker API is unavailable."]}
            status_code = 503
        return render_dashboard(
            result,
            status_code=status_code,
            focus_module=(result.get("record") or {}).get("module"),
        )

    @app.get("/api/schedule")
    def schedule_api():
        summary, connection_error = load_dashboard(
            api_base_url,
            request.args.get("module"),
        )
        if connection_error:
            return jsonify({"errors": [connection_error]}), 503
        return jsonify(summary)

    @app.get("/health")
    def health():
        _summary, connection_error = load_dashboard(api_base_url)
        return jsonify({"ok": connection_error is None}), (
            200 if connection_error is None else 503
        )

    return app


def run_frontend():
    """Start the presentation layer on the host."""
    create_app().run(
        host="127.0.0.1",
        port=int(os.getenv("FRONTEND_PORT", "5050")),
        debug=False,
    )


if __name__ == "__main__":
    run_frontend()
