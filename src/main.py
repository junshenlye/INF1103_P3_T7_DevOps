"""Pass one module request through the four procedural managers."""

from pathlib import Path

from dotenv import load_dotenv

from . import ai_manager, data_manager, io_manager, logic_manager


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def process_request(input_data, api_caller=None):
    """Run the complete single-module workflow."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    errors = io_manager.validate_input(input_data)
    module = str(input_data.get("module", "")).strip().upper()
    if errors:
        return {"ok": False, "errors": errors}

    extraction = ai_manager.extract_assessments(
        {**input_data, "module": module},
        api_caller=api_caller,
    )
    plan = logic_manager.build_plan(
        module,
        extraction["assessments"],
        extraction["comments"],
    )
    if not data_manager.save_plan(plan):
        return {"ok": False, "errors": ["The schedule could not be saved."]}

    return {
        "ok": True,
        "extracted_count": len(extraction["assessments"]),
        "model_used": extraction.get("model_used"),
        **plan,
    }


def get_dashboard():
    """Return the current schedule and checklist."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    return data_manager.load_plan()
