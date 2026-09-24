"""Thin Flask adapter for the procedural academic planning core."""

import os
from pathlib import Path
import sys
import tempfile

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import main as core_main  # noqa: E402


FRONTEND_ROOT = Path(__file__).resolve().parent
app = Flask(
    __name__,
    template_folder=str(FRONTEND_ROOT / "templates"),
    static_folder=str(FRONTEND_ROOT / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = 35 * 1024 * 1024


def render_dashboard(result=None, form_values=None, status_code=200):
    """Render current persisted state and an optional processing result."""
    summary = core_main.start_application()
    return (
        render_template(
            "index.html",
            schedule=summary["schedule"],
            module_profiles=summary["module_profiles"],
            records_loaded=summary["records_loaded"],
            result=result,
            form_values=form_values or {},
        ),
        status_code,
    )


def parse_optional_number(raw_value, field_label, errors):
    """Convert one optional form number without applying domain rules."""
    if raw_value is None or not raw_value.strip():
        return None
    try:
        return float(raw_value)
    except ValueError:
        errors.append(f"{field_label} must be a number.")
        return None


def save_uploaded_images(uploaded_files, target_directory):
    """Save request-scoped uploads for the core I/O validator."""
    image_paths = []
    for index, uploaded_file in enumerate(uploaded_files):
        if not uploaded_file or not uploaded_file.filename:
            continue
        safe_name = secure_filename(uploaded_file.filename)
        if not safe_name:
            safe_name = f"upload-{index}"
        target_path = Path(target_directory) / f"{index}-{safe_name}"
        uploaded_file.save(target_path)
        image_paths.append(str(target_path))
    return image_paths


@app.get("/")
def index():
    """Show module profiles, assessment input, and the current schedule."""
    return render_dashboard()


@app.post("/process")
def process_assessment():
    """Adapt one multipart form submission to the procedural core."""
    form_values = request.form.to_dict()
    conversion_errors = []
    module_credits = parse_optional_number(
        request.form.get("module_credits"),
        "Module credits",
        conversion_errors,
    )
    weightage = parse_optional_number(
        request.form.get("weightage"),
        "Weightage",
        conversion_errors,
    )
    if conversion_errors:
        result = {
            "ok": False,
            "record": None,
            "errors": conversion_errors,
            "ai_attempts": 0,
        }
        return render_dashboard(result, form_values, status_code=400)

    with tempfile.TemporaryDirectory(prefix="assessment-upload-") as upload_dir:
        image_paths = save_uploaded_images(
            request.files.getlist("source_files"),
            upload_dir,
        )
        input_record = {
            "module": request.form.get("module", ""),
            "module_credits": module_credits,
            "assessment_type": request.form.get("assessment_type", ""),
            "deadline": request.form.get("deadline") or None,
            "weightage": weightage,
            "prompt": request.form.get("prompt", ""),
            "image_paths": image_paths,
        }
        result = core_main.process_assessment(input_record)

    status_code = 200 if result.get("ok") or result.get("preserved") else 400
    return render_dashboard(result, form_values, status_code=status_code)


@app.get("/api/schedule")
def schedule_api():
    """Return the same derived schedule used by the server-rendered page."""
    summary = core_main.start_application()
    return jsonify(
        {
            "schedule": summary["schedule"],
            "module_profiles": summary["module_profiles"],
            "records_loaded": summary["records_loaded"],
        }
    )


@app.get("/health")
def health():
    """Return a minimal container health response."""
    return jsonify({"ok": True})


@app.errorhandler(RequestEntityTooLarge)
def upload_too_large(_error):
    """Return an ordinary dashboard error for oversized multipart requests."""
    result = {
        "ok": False,
        "record": None,
        "errors": ["Combined upload size must not exceed 35 MB."],
        "ai_attempts": 0,
    }
    return render_dashboard(result, status_code=413)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=False,
    )
