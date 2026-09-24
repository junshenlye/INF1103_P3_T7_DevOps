"""Thin local HTTP adapter for the procedural core."""

import json
import logging
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
from uuid import UUID, uuid4

from flask import Flask, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import data_manager  # noqa: E402
from src import main as core_main  # noqa: E402


LOGGER = logging.getLogger(__name__)
MAX_ACTIVE_JOBS = 4
JOB_TTL_SECONDS = 15 * 60


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


def job_directory():
    """Return the disposable progress directory inside the API container."""
    path = Path(tempfile.gettempdir()) / "stackplan-jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_path(job_id):
    """Resolve only valid opaque job identifiers."""
    try:
        normalized_id = str(UUID(str(job_id)))
    except ValueError:
        return None
    return job_directory() / f"{normalized_id}.json"


def write_job(job):
    """Replace one progress file atomically."""
    path = job_path(job["id"])
    temporary_path = path.with_suffix(f".{uuid4().hex}.tmp")
    temporary_path.write_text(json.dumps(job), encoding="utf-8")
    temporary_path.replace(path)


def read_job(job_id):
    """Read one progress file without keeping process-global state."""
    path = job_path(job_id)
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def create_job():
    """Create one disposable progress record."""
    job_id = str(uuid4())
    now = time.time()
    job = {
        "id": job_id,
        "status": "queued",
        "stage": "queued",
        "message": "Evidence pack queued for processing.",
        "attempt": 0,
        "max_attempts": None,
        "event_count": None,
        "created_at": now,
        "updated_at": now,
        "events": [
            {
                "stage": "queued",
                "message": "Evidence pack queued for processing.",
                "elapsed_seconds": 0.0,
            }
        ],
        "result": None,
    }
    write_job(job)
    return job_id


def update_job(job_id, progress_event=None, **changes):
    """Update one file-backed progress record."""
    job = read_job(job_id)
    if job is None:
        return
    now = time.time()
    if progress_event:
        job["stage"] = progress_event.get("stage", job["stage"])
        job["message"] = progress_event.get("message", job["message"])
        for key in ("attempt", "max_attempts", "event_count"):
            if progress_event.get(key) is not None:
                job[key] = progress_event[key]
        event = {
            "stage": job["stage"],
            "message": job["message"],
            "elapsed_seconds": round(now - job["created_at"], 1),
        }
        if progress_event.get("attempt") is not None:
            event["attempt"] = progress_event["attempt"]
        previous = job["events"][-1] if job["events"] else None
        if previous is None or any(
            previous.get(key) != event.get(key)
            for key in ("stage", "message", "attempt")
        ):
            job["events"].append(event)
    job.update(changes)
    job["updated_at"] = now
    write_job(job)


def public_job(job_id):
    """Return safe progress data without submitted content or local paths."""
    job = read_job(job_id)
    if job is None:
        return None
    return {
        key: job[key]
        for key in (
            "id",
            "status",
            "stage",
            "message",
            "attempt",
            "max_attempts",
            "event_count",
            "events",
            "result",
        )
    } | {"elapsed_seconds": round(time.time() - job["created_at"], 1)}


def cleanup_jobs():
    """Delete finished progress files after the short debugging window."""
    cutoff = time.time() - JOB_TTL_SECONDS
    for path in job_directory().glob("*.json"):
        job = read_job(path.stem)
        if job and job["status"] in ("complete", "failed"):
            if job["updated_at"] < cutoff:
                path.unlink(missing_ok=True)


def active_job_count():
    """Count queued and running jobs from their disposable files."""
    jobs = (read_job(path.stem) for path in job_directory().glob("*.json"))
    return sum(
        job is not None and job["status"] in ("queued", "running")
        for job in jobs
    )


def run_extraction_job(job_id, input_source, upload_directory):
    """Pass source through the core and persist visible progress."""
    update_job(
        job_id,
        {"stage": "starting", "message": "Starting procedural extraction."},
        status="running",
    )

    def report_progress(event):
        update_job(job_id, event)

    try:
        result = core_main.process_request(
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
        update_job(
            job_id,
            {
                "stage": "complete",
                "message": f"Extracted {summary['extracted_count']} assessment(s).",
                "event_count": summary["extracted_count"],
            },
            status="complete",
            result=summary,
        )
        return
    message = summary["errors"][0] if summary["errors"] else "Extraction failed."
    update_job(
        job_id,
        {"stage": "failed", "message": message},
        status="failed",
        result=summary,
    )


def start_extraction_worker(job_id, input_source, upload_directory):
    """Start the bounded local worker without retaining the thread globally."""
    threading.Thread(
        target=run_extraction_job,
        args=(job_id, input_source, upload_directory),
        daemon=True,
    ).start()


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
    def start_extraction_api():
        cleanup_jobs()
        if active_job_count() >= MAX_ACTIVE_JOBS:
            return jsonify({"errors": ["Too many extractions are running."]}), 429

        upload_directory = tempfile.mkdtemp(prefix="assessment-upload-")
        try:
            input_source = {
                "module": request.form.get("module", ""),
                "prompt": request.form.get("prompt", ""),
                "image_paths": save_uploaded_images(
                    request.files.getlist("source_files"),
                    upload_directory,
                ),
            }
            job_id = create_job()
            start_extraction_worker(job_id, input_source, upload_directory)
        except Exception:
            shutil.rmtree(upload_directory, ignore_errors=True)
            LOGGER.exception("Could not queue assessment extraction")
            return jsonify({"errors": ["Extraction could not be started."]}), 500
        return jsonify(
            {"job_id": job_id, "status_url": f"/api/extractions/{job_id}"}
        ), 202

    @app.get("/api/extractions/<job_id>")
    def extraction_status_api(job_id):
        job = public_job(job_id)
        if job is None:
            return jsonify({"errors": ["Extraction job was not found."]}), 404
        return jsonify(job)

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
