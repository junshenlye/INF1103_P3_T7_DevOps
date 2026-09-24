"""Thin local HTTP adapter for the procedural core."""

import logging
import os
from pathlib import Path
import sys
import tempfile

from flask import Flask, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import data_manager  # noqa: E402
from src import main as core_main  # noqa: E402


LOGGER = logging.getLogger(__name__)


def save_uploaded_images(uploaded_files, target_directory):
    """Save uploads only for the lifetime of one extraction."""
    image_paths = []
    for index, uploaded_file in enumerate(uploaded_files):
        if not uploaded_file or not uploaded_file.filename:
            continue
        safe_name = secure_filename(uploaded_file.filename) or f"upload-{index}"
        target_path = Path(target_directory) / f"{index}-{safe_name}"
        uploaded_file.save(target_path)
        image_paths.append(str(target_path))
    return image_paths


def create_app():
    """Create the thin API without module-level application state."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 35 * 1024 * 1024

    @app.after_request
    def add_local_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    @app.get("/")
    def api_index():
        return jsonify(
            {
                "name": "Stackplan development API",
                "health": "/health",
                "dashboard": "/api/dashboard",
                "frontend": "Run python frontend-demo/app.py on the host.",
            }
        )

    @app.get("/health")
    def health():
        database_ready = data_manager.storage_is_ready()
        return jsonify({"ok": database_ready, "database": database_ready}), (
            200 if database_ready else 503
        )

    @app.get("/api/dashboard")
    def dashboard_api():
        return jsonify(core_main.get_dashboard())

    @app.post("/api/extractions")
    def extraction_api():
        try:
            with tempfile.TemporaryDirectory(prefix="assessment-upload-") as directory:
                result = core_main.process_request(
                    {
                        "module": request.form.get("module", ""),
                        "prompt": request.form.get("prompt", ""),
                        "image_paths": save_uploaded_images(
                            request.files.getlist("source_files"), directory
                        ),
                    }
                )
        except Exception:
            LOGGER.exception("Assessment extraction stopped unexpectedly")
            return jsonify({"errors": ["The schedule could not be created."]}), 500
        return jsonify(result), (200 if result.get("ok") else 400)

    @app.errorhandler(RequestEntityTooLarge)
    def upload_too_large(_error):
        return jsonify({"errors": ["Combined upload size must not exceed 35 MB."]}), 413

    return app


def run_api():
    """Initialize storage, then expose the local API."""
    logging.basicConfig(level=logging.INFO)
    if not data_manager.initialize_storage():
        raise RuntimeError("PostgreSQL storage could not be initialized.")
    create_app().run(
        host="0.0.0.0",
        port=int(os.getenv("API_PORT", "8000")),
        debug=False,
        threaded=True,
    )


if __name__ == "__main__":
    run_api()
