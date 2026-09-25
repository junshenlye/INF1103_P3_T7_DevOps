"""Coordinate the IO, AI, logic, and data managers."""

from pathlib import Path

from dotenv import load_dotenv

from . import ai_manager, data_manager, io_manager, logic_manager


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def process_request(input_data, api_caller=None, current_date=None):
    """Run the complete workflow, retaining the legacy one-module contract."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    if isinstance(input_data, dict) and "modules" in input_data:
        normalized_input, errors = io_manager.process_input(input_data)
        if errors:
            return {"ok": False, "errors": errors}

        trimester_context = logic_manager.get_trimester_context(current_date)
        ai_result = ai_manager.process(
            normalized_input,
            trimester_context,
            api_caller=api_caller,
        )
        pacing_result = logic_manager.build_timeline(ai_result, trimester_context)
        if not data_manager.save(
            input_data=normalized_input,
            ai_result=ai_result,
            pacing_result=pacing_result,
        ):
            return {
                "ok": False,
                "errors": ["The trimester pacing result could not be saved."],
            }
        return {
            "ok": True,
            "extracted_count": sum(
                len(module["assessments"]) for module in ai_result["modules"]
            ),
            "models_used": ai_result.get("models_used", []),
            **pacing_result,
        }

    errors = io_manager.validate_input(input_data)
    if errors:
        return {"ok": False, "errors": errors}

    module = str(input_data.get("module", "")).strip().upper()
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
