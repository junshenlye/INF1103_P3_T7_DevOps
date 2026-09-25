"""Standalone Flask frontend for the trimester pacing pipeline."""

import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from urllib import error as url_error
from urllib import request as url_request

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename


FRONTEND_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = FRONTEND_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import data_manager  # noqa: E402
from src import main as core_main  # noqa: E402


LOGGER = logging.getLogger(__name__)


def load_dashboard(api_url=None):
    """Read locally by default, retaining an explicit remote-API option."""
    if not api_url:
        return core_main.get_dashboard(), None
    try:
        with url_request.urlopen(f"{api_url}/api/dashboard", timeout=8) as response:
            return json.loads(response.read().decode("utf-8")), None
    except (OSError, ValueError, json.JSONDecodeError, url_error.HTTPError):
        return {
            "trimester_context": {},
            "current_week": None,
            "relative_assessment_ranking": [],
            "module_weight_coverage": [],
            "timeline": [],
            "pressure_by_week": [],
            "overlaps": [],
            "clusters": [],
            "overall_pacing": {},
            "comments": [],
            "user_checklist": [],
        }, f"The configured API is unavailable at {api_url}."


def save_uploaded_files(uploaded_files, target_directory, name_prefix=""):
    """Save uploads for the lifetime of one local extraction request."""
    paths = []
    for index, uploaded_file in enumerate(uploaded_files):
        if not uploaded_file or not uploaded_file.filename:
            continue
        safe_name = secure_filename(uploaded_file.filename) or f"upload-{index}"
        path = Path(target_directory) / f"{name_prefix}{index}-{safe_name}"
        uploaded_file.save(path)
        paths.append(str(path))
    return paths


def frontend_modules(form, files, target_directory):
    """Normalize indexed multipart module fields for Main.py."""
    try:
        module_count = int(form.get("module_count", "1"))
    except ValueError:
        module_count = 0
    return {
        "modules": [
            {
                "module_name": form.get(f"module_name_{index}", ""),
                "credit_units": form.get(f"credit_units_{index}", ""),
                "additional_context": form.get(
                    f"additional_context_{index}", ""
                ),
                "files": save_uploaded_files(
                    files.getlist(f"source_files_{index}"),
                    target_directory,
                    name_prefix=f"module-{index}-",
                ),
            }
            for index in range(max(0, min(module_count, 21)))
        ]
    }


def create_app(configured_api_url=None):
    """Create one standalone frontend and pipeline HTTP process."""
    load_dotenv(FRONTEND_ROOT.parent / ".env", override=False)
    api_url = configured_api_url.rstrip("/") if configured_api_url else None
    app = Flask(
        __name__,
        template_folder=str(FRONTEND_ROOT / "templates"),
        static_folder=str(FRONTEND_ROOT / "static"),
    )
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
    data_manager.initialize_storage()

    @app.get("/")
    def index():
        dashboard, connection_error = load_dashboard(api_url)
        return render_template(
            "index.html",
            **dashboard,
            api_base_url=api_url or "",
            connection_error=connection_error,
        )

    @app.post("/api/extractions")
    def extraction_api():
        try:
            with tempfile.TemporaryDirectory(prefix="assessment-upload-") as directory:
                result = core_main.process_request(
                    frontend_modules(request.form, request.files, directory)
                )
        except Exception:
            LOGGER.exception("Assessment extraction stopped unexpectedly")
            return jsonify(
                {"errors": ["The pacing timeline could not be created."]}
            ), 500
        return jsonify(result), (200 if result.get("ok") else 400)

    @app.get("/api/schedule")
    def schedule_api():
        dashboard, connection_error = load_dashboard(api_url)
        if connection_error:
            return jsonify({"errors": [connection_error]}), 503
        return jsonify(dashboard)

    @app.get("/health")
    def health():
        if api_url:
            _dashboard, connection_error = load_dashboard(api_url)
            ready = connection_error is None
        else:
            ready = data_manager.storage_is_ready()
        return jsonify({"ok": ready}), (200 if ready else 503)

    @app.errorhandler(RequestEntityTooLarge)
    def upload_too_large(_error):
        return jsonify(
            {"errors": ["Combined upload size must not exceed 100 MB."]}
        ), 413

    return app


if __name__ == "__main__":
    create_app().run(
        host="127.0.0.1",
        port=int(os.getenv("FRONTEND_PORT", "5050")),
        debug=False,
    )
