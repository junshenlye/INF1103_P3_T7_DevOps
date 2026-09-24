"""Hand one module request from I/O to AI to Logic to Data."""

import logging
from pathlib import Path

from dotenv import load_dotenv

from . import ai_manager, data_manager, io_manager, logic_manager


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def process_request(input_data, api_caller=None, progress_callback=None):
    """Run the complete single-module workflow."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    _progress(progress_callback, "validating", "Checking the module evidence.")
    errors = io_manager.validate_input(input_data)
    module = str(input_data.get("module", "")).strip().upper()
    if errors:
        return _failure(module, errors)

    extraction = ai_manager.extract_assessments(
        {**input_data, "module": module},
        api_caller=api_caller,
        progress_callback=progress_callback,
    )
    if extraction["errors"] and not extraction["assessments"]:
        return _failure(module, extraction["errors"])

    _progress(progress_callback, "planning", "Building the weekly plan.")
    plan = logic_manager.build_plan(module, extraction["assessments"])
    _progress(progress_callback, "saving", "Saving the current module plan.")
    if not data_manager.save_plan(plan):
        return _failure(module, ["The assessment plan could not be saved."])

    return {
        "ok": True,
        "source_module": module,
        "extracted_count": len(plan["assessments"]),
        "errors": extraction["errors"],
        **plan,
    }


def get_dashboard():
    """Return the one currently stored module plan."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    assessments = data_manager.load_assessments()
    module = assessments[0]["module"] if assessments else None
    plan = logic_manager.build_plan(module, assessments)
    return {**plan, "records_loaded": len(assessments)}


def _failure(module, errors):
    """Return one small failure shape used by API and frontend."""
    return {
        "ok": False,
        "source_module": module,
        "extracted_count": 0,
        "errors": list(errors),
    }


def _progress(callback, stage, message):
    """Report optional progress without owning job storage."""
    if callback:
        try:
            callback({"stage": stage, "message": message})
        except Exception:
            logging.warning("Progress callback failed and was ignored")
