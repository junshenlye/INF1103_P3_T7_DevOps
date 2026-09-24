"""Readable local HTTP API for the Dockerised procedural core."""

import logging
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading

from flask import Flask, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers import progress_tracker  # noqa: E402
from src import main as core_main  # noqa: E402
from src import storage_manager  # noqa: E402


LOGGER = logging.getLogger(__name__)
MAX_ACTIVE_JOBS = 4
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 35 * 1024 * 1024


def parse_optional_number(raw_value, field_label, errors):
    """Convert one optional form number without applying domain rules."""
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        errors.append(f"{field_label} must be a number.")
        return None
    normalized_value = str(raw_value).strip()
    if not normalized_value:
        return None
    try:
        return float(normalized_value)
    except ValueError:
        errors.append(f"{field_label} must be a number.")
        return None


def save_uploaded_images(uploaded_files, target_directory):
    """Save uploads only for the lifetime of one background extraction."""
    image_paths = []
    for index, uploaded_file in enumerate(uploaded_files):
        if not uploaded_file or not uploaded_file.filename:
            continue
        safe_name = secure_filename(uploaded_file.filename) or f"upload-{index}"
        target_path = Path(target_directory) / f"{index}-{safe_name}"
        uploaded_file.save(target_path)
        image_paths.append(str(target_path))
    return image_paths


def dashboard_payload():
    """Return the core state required by the separate host frontend."""
    summary = core_main.start_application()
    return {
        "schedule": summary["schedule"],
        "module_profiles": summary["module_profiles"],
        "latest_records": summary["latest_records"],
        "records_loaded": summary["records_loaded"],
    }


def run_extraction_job(job_id, input_source, upload_directory):
    """Run the synchronous core while the frontend polls safe progress."""
    progress_tracker.update_job(
        job_id,
        {"stage": "starting", "message": "Starting procedural extraction."},
        status="running",
    )

    def report_progress(event):
        progress_tracker.update_job(job_id, event)

    try:
        result = core_main.process_assessment_source(
            input_source,
            progress_callback=report_progress,
        )
    except Exception:
        LOGGER.exception("Background assessment extraction failed")
        result = {
            "ok": False,
            "source_module": input_source.get("module", ""),
            "extracted_count": 0,
            "errors": ["The extraction worker stopped unexpectedly."],
        }
    finally:
        shutil.rmtree(upload_directory, ignore_errors=True)

    summary = {
        "ok": bool(result.get("ok")),
        "source_module": result.get("source_module", ""),
        "extracted_count": result.get("extracted_count", 0),
        "errors": list(result.get("errors", [])),
    }
    if summary["ok"]:
        progress_tracker.update_job(
            job_id,
            {
                "stage": "complete",
                "message": (
                    f"Extracted and scheduled {summary['extracted_count']} "
                    "assessment event(s)."
                ),
                "event_count": summary["extracted_count"],
            },
            status="complete",
            result=summary,
        )
        return

    message = summary["errors"][0] if summary["errors"] else "Extraction failed."
    progress_tracker.update_job(
        job_id,
        {"stage": "failed", "message": message},
        status="failed",
        result=summary,
    )


def start_extraction_worker(job_id, input_source, upload_directory):
    """Start one daemon worker for the local MVP API."""
    worker = threading.Thread(
        target=run_extraction_job,
        args=(job_id, input_source, upload_directory),
        daemon=True,
    )
    worker.start()


@app.after_request
def add_local_cors_headers(response):
    """Allow the host-run frontend to call this local development API."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.get("/")
def api_index():
    """Show readable local endpoints at the published Docker address."""
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
    """Report both API and PostgreSQL readiness."""
    database_ready = storage_manager.storage_is_ready()
    return jsonify({"ok": database_ready, "database": database_ready}), (
        200 if database_ready else 503
    )


@app.get("/api/dashboard")
def dashboard_api():
    """Return current assessments, modules, and derived schedule."""
    return jsonify(dashboard_payload())


@app.post("/api/extractions")
def start_extraction_api():
    """Queue one module evidence pack and return its progress address."""
    progress_tracker.cleanup_finished_jobs()
    if progress_tracker.active_job_count() >= MAX_ACTIVE_JOBS:
        return jsonify({"errors": ["Too many extractions are already running."]}), 429

    conversion_errors = []
    module_credits = parse_optional_number(
        request.form.get("module_credits"),
        "Module credits",
        conversion_errors,
    )
    if conversion_errors:
        return jsonify({"errors": conversion_errors}), 400

    upload_directory = tempfile.mkdtemp(prefix="assessment-upload-")
    try:
        input_source = {
            "module": request.form.get("module", ""),
            "module_credits": module_credits,
            "prompt": request.form.get("prompt", ""),
            "image_paths": save_uploaded_images(
                request.files.getlist("source_files"),
                upload_directory,
            ),
        }
        job_id = progress_tracker.create_job()
        start_extraction_worker(job_id, input_source, upload_directory)
    except Exception:
        shutil.rmtree(upload_directory, ignore_errors=True)
        LOGGER.exception("Could not queue assessment extraction")
        return jsonify({"errors": ["Extraction could not be started."]}), 500

    return jsonify(
        {
            "job_id": job_id,
            "status_url": f"/api/extractions/{job_id}",
        }
    ), 202


@app.get("/api/extractions/<job_id>")
def extraction_status_api(job_id):
    """Return stage, elapsed time, attempts, and safe diagnostics."""
    job = progress_tracker.public_job(job_id)
    if job is None:
        return jsonify({"errors": ["Extraction job was not found."]}), 404
    return jsonify(job)


@app.post("/api/assessments/<record_id>/review")
def review_assessment_api(record_id):
    """Append reviewed fields without another AI request."""
    payload = request.get_json(silent=True) or request.form.to_dict()
    errors = []
    assessment_type = str(payload.get("assessment_type") or "").strip()
    deadline = str(payload.get("deadline") or "").strip()
    raw_weightage = payload.get("weightage")
    weightage = parse_optional_number(raw_weightage, "Weightage", errors)
    if errors:
        return jsonify({"errors": errors}), 400
    updates = {"assessment_type": assessment_type}
    if deadline:
        updates["deadline"] = deadline
    if raw_weightage is not None and str(raw_weightage).strip():
        updates["weightage"] = weightage
    result = core_main.correct_assessment(record_id, updates)
    return jsonify(result), (200 if result.get("ok") else 400)


@app.errorhandler(RequestEntityTooLarge)
def upload_too_large(_error):
    """Return a small JSON error for oversized local uploads."""
    return jsonify({"errors": ["Combined upload size must not exceed 35 MB."]}), 413


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if not storage_manager.initialize_storage():
        raise RuntimeError("PostgreSQL storage could not be initialized.")
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("API_PORT", "8000")),
        debug=False,
        threaded=True,
    )
