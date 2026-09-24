"""Procedural orchestration: I/O -> AI -> Logic -> Data."""

from datetime import date
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv

from . import ai_manager, data_manager, io_manager, logic_manager


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_FILE = PROJECT_ROOT / "data" / "schedules.json"
DEFAULT_MODULE_FILE = PROJECT_ROOT / "data" / "modules.json"


def resolve_data_file_path(configured_path: Optional[str] = None) -> str:
    """Resolve the CLI JSON record path."""
    return _resolve_path(configured_path or os.getenv("DATA_FILE"), DEFAULT_DATA_FILE)


def resolve_module_file_path(configured_path: Optional[str] = None) -> str:
    """Resolve the CLI JSON module-profile path."""
    return _resolve_path(
        configured_path or os.getenv("MODULE_FILE"),
        DEFAULT_MODULE_FILE,
    )


def _resolve_path(configured_path: Optional[str], default_path: Path) -> str:
    """Resolve one optional path relative to the project root."""
    if not configured_path:
        return str(default_path)
    path = Path(configured_path)
    return str(path if path.is_absolute() else PROJECT_ROOT / path)


def start_application(
    data_file: Optional[str] = None,
    module_file: Optional[str] = None,
    today: Optional[date] = None,
    focus_module: Optional[str] = None,
) -> Dict[str, Any]:
    """Load the most recent module view for CLI or frontend output."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    record_path = resolve_data_file_path(data_file)
    module_path = resolve_module_file_path(module_file)
    records = data_manager.load_records(record_path)
    profiles = data_manager.load_module_profiles(module_path)
    selected_module = _select_module(records, focus_module)
    latest = data_manager.filter_records(
        data_manager.latest_records(records),
        module=selected_module,
    )
    visible_profiles = _select_profile(profiles, selected_module)
    return {
        "records": data_manager.filter_records(records, module=selected_module),
        "latest_records": latest,
        "records_loaded": len(latest),
        "data_file": record_path,
        "module_file": module_path,
        "focus_module": selected_module,
        "module_profiles": visible_profiles,
        "schedule": logic_manager.build_schedule(
            latest,
            today=today,
            module_profiles=visible_profiles,
        ),
    }


def process_assessment_source(
    input_source: Dict[str, Any],
    data_file: Optional[str] = None,
    module_file: Optional[str] = None,
    api_caller: Optional[Callable[..., str]] = None,
    today: Optional[date] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Pass one module evidence pack through every manager in order."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    source_module = _source_module(input_source)
    _emit_progress(progress_callback, "validating", "Checking the evidence pack.")
    input_errors = io_manager.validate_source_input(input_source)
    if input_errors:
        return _source_failure(source_module, input_errors, progress_callback)

    record_path = resolve_data_file_path(data_file)
    module_path = resolve_module_file_path(module_file)
    _emit_progress(
        progress_callback,
        "module_context",
        f"Saving credit context for {source_module}.",
    )
    if not data_manager.save_module_profile(
        source_module,
        input_source["module_credits"],
        module_path,
    ):
        return _source_failure(
            source_module,
            ["Module credit metadata could not be saved."],
            progress_callback,
        )

    normalized_source = dict(input_source)
    normalized_source["module"] = source_module
    ai_result = ai_manager.process_source(
        normalized_source,
        api_caller=api_caller,
        progress_callback=progress_callback,
    )
    if not ai_result["ok"]:
        return _source_failure(
            source_module,
            ai_result["errors"],
            progress_callback,
            ai_attempts=ai_result["attempts"],
        )

    _emit_progress(
        progress_callback,
        "building_records",
        f"Building {len(ai_result['extractions'])} assessment record(s).",
        event_count=len(ai_result["extractions"]),
    )
    records, errors = _build_records(
        ai_result["extractions"],
        data_manager.load_records(record_path),
        today,
    )
    if errors:
        return _source_failure(
            source_module,
            errors,
            progress_callback,
            ai_attempts=ai_result["attempts"],
        )
    if not data_manager.save_record_revisions(records, record_path):
        return _source_failure(
            source_module,
            ["Extracted assessments could not be saved."],
            progress_callback,
            ai_attempts=ai_result["attempts"],
        )

    _emit_progress(
        progress_callback,
        "scheduling",
        f"Building the {source_module} weekly timetable.",
    )
    return {
        "ok": True,
        "records": records,
        "extracted_count": len(records),
        "source_module": source_module,
        "errors": [],
        "ai_attempts": ai_result["attempts"],
        "preserved": False,
        "schedule": build_current_schedule(
            record_path,
            today=today,
            module_file=module_path,
            focus_module=source_module,
        ),
    }


def _build_records(extractions, existing_records, today):
    """Pass AI events through Logic Manager and validate its output."""
    used_ids = {record["record_id"] for record in existing_records}
    records = []
    errors = []
    for index, extraction in enumerate(extractions):
        record_id = data_manager.generate_record_id()
        while record_id in used_ids:
            record_id = data_manager.generate_record_id()
        used_ids.add(record_id)
        record = logic_manager.apply_business_rules(
            extraction,
            record_id=record_id,
            revision=1,
            today=today,
        )
        errors.extend(
            f"assessments[{index}]: {error}"
            for error in io_manager.validate_record(record)
        )
        records.append(record)
    return records, errors


def _source_failure(
    module,
    errors,
    progress_callback,
    ai_attempts=0,
):
    """Build one consistent source-processing failure result."""
    _emit_progress(
        progress_callback,
        "failed",
        errors[0] if errors else "The evidence pack could not be processed.",
    )
    return {
        "ok": False,
        "records": [],
        "extracted_count": 0,
        "source_module": module,
        "errors": errors,
        "ai_attempts": ai_attempts,
        "preserved": False,
    }


def _emit_progress(progress_callback, stage, message, **details):
    """Pass safe progress to an optional adapter callback."""
    if progress_callback is None:
        return
    event = {"stage": stage, "message": message}
    event.update(details)
    try:
        progress_callback(event)
    except Exception:
        logging.warning("Progress callback failed and was ignored")


def build_current_schedule(
    data_file: str,
    today: Optional[date] = None,
    module_file: Optional[str] = None,
    focus_module: Optional[str] = None,
) -> Dict[str, Any]:
    """Load and build the latest timetable for one module."""
    records = data_manager.load_records(data_file)
    selected_module = _select_module(records, focus_module)
    latest = data_manager.filter_records(
        data_manager.latest_records(records),
        module=selected_module,
    )
    profiles = data_manager.load_module_profiles(
        resolve_module_file_path(module_file)
    )
    return logic_manager.build_schedule(
        latest,
        today=today,
        module_profiles=_select_profile(profiles, selected_module),
    )


def correct_assessment(
    record_id: str,
    updates: Dict[str, Any],
    data_file: Optional[str] = None,
    module_file: Optional[str] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Append one human-reviewed revision without another AI request."""
    errors = io_manager.validate_correction_input(updates)
    if errors:
        return {"ok": False, "record": None, "errors": errors}

    record_path = resolve_data_file_path(data_file)
    module_path = resolve_module_file_path(module_file)
    records = data_manager.load_records(record_path)
    latest = data_manager.get_latest_record(records, record_id)
    if latest is None:
        return {
            "ok": False,
            "record": None,
            "errors": [f"Record ID was not found: {record_id}"],
        }

    corrected_fields = {field for field, value in updates.items() if value is not None}
    extraction = {
        "module": latest["module"],
        "assessment_type": updates.get("assessment_type", latest["assessment_type"]),
        "deadline": updates.get("deadline", latest["deadline"]),
        "weightage": updates.get("weightage", latest["weightage"]),
        "issues": [
            issue
            for issue in latest["issues"]
            if issue.get("field") not in corrected_fields
        ],
    }
    corrected_record = logic_manager.apply_business_rules(
        extraction,
        record_id=record_id,
        revision=data_manager.next_revision(records, record_id),
        today=today,
    )
    errors = io_manager.validate_record(corrected_record)
    if errors or not data_manager.save_record_revision(corrected_record, record_path):
        return {
            "ok": False,
            "record": None,
            "errors": errors or ["The corrected assessment could not be saved."],
        }
    return {
        "ok": True,
        "record": corrected_record,
        "errors": [],
        "schedule": build_current_schedule(
            record_path,
            today=today,
            module_file=module_path,
            focus_module=latest["module"],
        ),
    }


def _select_module(records, requested_module):
    """Select the requested or most recently written module."""
    if isinstance(requested_module, str) and requested_module.strip():
        return requested_module.strip().upper()
    return records[-1]["module"].strip().upper() if records else None


def _select_profile(profiles, module):
    """Return only the credit context for the active module."""
    if module in profiles:
        return {module: profiles[module]}
    return {}


def _source_module(input_source):
    """Read a safe normalized module name for result messages."""
    if isinstance(input_source, dict) and isinstance(input_source.get("module"), str):
        return input_source["module"].strip().upper()
    return ""


def main(argv: Optional[List[str]] = None) -> int:
    """Run the same one-module pipeline from the command line."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    arguments = io_manager.parse_cli_arguments(argv)
    data_file = arguments.pop("data_file")
    module_file = arguments.pop("module_file")
    if not io_manager.has_source_input(arguments):
        io_manager.display_startup_summary(
            start_application(data_file=data_file, module_file=module_file)
        )
        return 0
    result = process_assessment_source(
        arguments,
        data_file=data_file,
        module_file=module_file,
    )
    io_manager.display_source_result(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
