"""CLI entry point and procedural application orchestration."""

from datetime import date
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv

from . import (
    ai_manager,
    contracts,
    data_manager,
    io_manager,
    logic_manager,
    storage_manager,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_FILE = PROJECT_ROOT / "data" / "schedules.json"
DEFAULT_MODULE_FILE = PROJECT_ROOT / "data" / "modules.json"


def resolve_data_file_path(configured_path: Optional[str] = None) -> str:
    """Resolve an environment or caller-provided data file path."""
    raw_path = configured_path or os.getenv("DATA_FILE")
    if not raw_path:
        return str(DEFAULT_DATA_FILE)

    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path)


def resolve_module_file_path(configured_path: Optional[str] = None) -> str:
    """Resolve the separate module-credit metadata file path."""
    raw_path = configured_path or os.getenv("MODULE_FILE")
    if not raw_path:
        return str(DEFAULT_MODULE_FILE)

    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path)


def start_application(
    data_file: Optional[str] = None,
    module_file: Optional[str] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Load local configuration and existing records without starting a UI loop."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    resolved_data_file = resolve_data_file_path(data_file)
    resolved_module_file = resolve_module_file_path(module_file)
    records = storage_manager.load_records(resolved_data_file)
    module_profiles = storage_manager.load_module_profiles(resolved_module_file)
    latest = data_manager.latest_records(records)
    return {
        "records": records,
        "latest_records": latest,
        "records_loaded": len(records),
        "data_file": resolved_data_file,
        "module_profiles": module_profiles,
        "module_file": resolved_module_file,
        "schedule": logic_manager.build_schedule(
            latest,
            today=today,
            module_profiles=module_profiles,
        ),
    }


def process_assessment(
    input_record: Dict[str, Any],
    data_file: Optional[str] = None,
    module_file: Optional[str] = None,
    api_caller: Optional[Callable[..., str]] = None,
    today: Optional[date] = None,
    record_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Run one assessment through AI, Logic, validation, and persistence."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    input_errors = io_manager.validate_user_input(input_record)
    if input_errors:
        return {
            "ok": False,
            "record": None,
            "errors": input_errors,
            "ai_attempts": 0,
        }

    resolved_data_file = resolve_data_file_path(data_file)
    resolved_module_file = resolve_module_file_path(module_file)
    module_credits = input_record.get("module_credits")
    if module_credits is not None and not storage_manager.save_module_profile(
        input_record["module"],
        module_credits,
        resolved_module_file,
    ):
        return {
            "ok": False,
            "record": None,
            "errors": ["Module credit metadata could not be saved."],
            "ai_attempts": 0,
            "preserved": False,
        }
    existing_records = storage_manager.load_records(resolved_data_file)
    resolved_record_id = (
        record_id
        or input_record.get("record_id")
        or data_manager.generate_record_id()
    )
    revision = data_manager.next_revision(existing_records, resolved_record_id)
    ai_result = ai_manager.process_record(input_record, api_caller=api_caller)
    if not ai_result["ok"]:
        if ai_result["attempts"] == 0:
            return {
                "ok": False,
                "record": None,
                "errors": ai_result["errors"],
                "ai_attempts": ai_result["attempts"],
                "preserved": False,
            }
        recoverable_record = logic_manager.build_recoverable_record(
            input_record,
            processing_errors=ai_result["errors"],
            record_id=resolved_record_id,
            revision=revision,
            today=today,
        )
        if not storage_manager.save_record_revision(
            recoverable_record,
            resolved_data_file,
        ):
            return {
                "ok": False,
                "record": None,
                "errors": ["AI failed and recoverable input could not be saved."],
                "ai_attempts": ai_result["attempts"],
                "preserved": False,
            }
        schedule = build_current_schedule(
            resolved_data_file,
            today=today,
            module_file=resolved_module_file,
        )
        return {
            "ok": False,
            "record": recoverable_record,
            "errors": ai_result["errors"],
            "ai_attempts": ai_result["attempts"],
            "preserved": True,
            "schedule": schedule,
        }

    final_record = logic_manager.apply_business_rules(
        ai_result["extraction"],
        record_id=resolved_record_id,
        revision=revision,
        today=today,
    )
    contract_errors = contracts.validate_record_contract(final_record)
    if contract_errors:
        logging.error("Logic output failed the frozen contract: %s", contract_errors)
        return {
            "ok": False,
            "record": None,
            "errors": contract_errors,
            "ai_attempts": ai_result["attempts"],
        }

    if not storage_manager.save_record_revision(final_record, resolved_data_file):
        return {
            "ok": False,
            "record": None,
            "errors": ["The processed record could not be saved."],
            "ai_attempts": ai_result["attempts"],
        }

    schedule = build_current_schedule(
        resolved_data_file,
        today=today,
        module_file=resolved_module_file,
    )
    return {
        "ok": True,
        "record": final_record,
        "errors": [],
        "ai_attempts": ai_result["attempts"],
        "preserved": False,
        "schedule": schedule,
    }


def process_assessment_source(
    input_source: Dict[str, Any],
    data_file: Optional[str] = None,
    module_file: Optional[str] = None,
    api_caller: Optional[Callable[..., str]] = None,
    today: Optional[date] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Extract and atomically persist all events from one module evidence pack."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    _emit_progress(
        progress_callback,
        "validating",
        "Checking module context and uploaded evidence.",
    )
    source_errors = io_manager.validate_source_input(input_source)
    source_module = (
        input_source.get("module", "").strip().upper()
        if isinstance(input_source, dict)
        and isinstance(input_source.get("module"), str)
        else ""
    )
    if source_errors:
        _emit_progress(
            progress_callback,
            "failed",
            "The evidence pack did not pass input validation.",
        )
        return {
            "ok": False,
            "records": [],
            "extracted_count": 0,
            "source_module": source_module,
            "errors": source_errors,
            "ai_attempts": 0,
            "preserved": False,
        }

    resolved_data_file = resolve_data_file_path(data_file)
    resolved_module_file = resolve_module_file_path(module_file)
    _emit_progress(
        progress_callback,
        "module_context",
        f"Saving credit context for {source_module}.",
    )
    if not storage_manager.save_module_profile(
        source_module,
        input_source["module_credits"],
        resolved_module_file,
    ):
        return {
            "ok": False,
            "records": [],
            "extracted_count": 0,
            "source_module": source_module,
            "errors": ["Module credit metadata could not be saved."],
            "ai_attempts": 0,
            "preserved": False,
        }

    normalized_source = dict(input_source)
    normalized_source["module"] = source_module
    ai_result = ai_manager.process_source(
        normalized_source,
        api_caller=api_caller,
        progress_callback=progress_callback,
    )
    if not ai_result["ok"]:
        return {
            "ok": False,
            "records": [],
            "extracted_count": 0,
            "source_module": source_module,
            "errors": ai_result["errors"],
            "ai_attempts": ai_result["attempts"],
            "preserved": False,
        }

    existing_records = storage_manager.load_records(resolved_data_file)
    used_record_ids = {record["record_id"] for record in existing_records}
    final_records = []
    contract_errors = []
    _emit_progress(
        progress_callback,
        "building_records",
        f"Building {len(ai_result['extractions'])} validated assessment record(s).",
        event_count=len(ai_result["extractions"]),
    )
    for index, extraction in enumerate(ai_result["extractions"]):
        record_id = data_manager.generate_record_id()
        while record_id in used_record_ids:
            record_id = data_manager.generate_record_id()
        used_record_ids.add(record_id)
        final_record = logic_manager.apply_business_rules(
            extraction,
            record_id=record_id,
            revision=1,
            today=today,
        )
        item_errors = contracts.validate_record_contract(final_record)
        contract_errors.extend(
            f"assessments[{index}]: {error}" for error in item_errors
        )
        final_records.append(final_record)

    if contract_errors:
        logging.error(
            "Multi-event logic output failed the frozen contract: %s",
            contract_errors,
        )
        return {
            "ok": False,
            "records": [],
            "extracted_count": 0,
            "source_module": source_module,
            "errors": contract_errors,
            "ai_attempts": ai_result["attempts"],
            "preserved": False,
        }

    if not storage_manager.save_record_revisions(final_records, resolved_data_file):
        return {
            "ok": False,
            "records": [],
            "extracted_count": 0,
            "source_module": source_module,
            "errors": ["Extracted assessments could not be saved."],
            "ai_attempts": ai_result["attempts"],
            "preserved": False,
        }

    _emit_progress(
        progress_callback,
        "scheduling",
        "Recalculating the combined multi-module schedule.",
    )
    schedule = build_current_schedule(
        resolved_data_file,
        today=today,
        module_file=resolved_module_file,
    )
    return {
        "ok": True,
        "records": final_records,
        "extracted_count": len(final_records),
        "source_module": source_module,
        "errors": [],
        "ai_attempts": ai_result["attempts"],
        "preserved": False,
        "schedule": schedule,
    }


def _emit_progress(
    progress_callback: Optional[Callable[[Dict[str, Any]], None]],
    stage: str,
    message: str,
    **details: Any,
) -> None:
    """Send one non-sensitive orchestration progress event when requested."""
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
) -> Dict[str, Any]:
    """Build a schedule from only the latest persisted record revisions."""
    records = storage_manager.load_records(data_file)
    latest = data_manager.latest_records(records)
    module_profiles = storage_manager.load_module_profiles(
        resolve_module_file_path(module_file)
    )
    return logic_manager.build_schedule(
        latest,
        today=today,
        module_profiles=module_profiles,
    )


def correct_assessment(
    record_id: str,
    updates: Dict[str, Any],
    data_file: Optional[str] = None,
    module_file: Optional[str] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Append one deterministic human-reviewed revision without another AI call."""
    correction_errors = io_manager.validate_correction_input(updates)
    if correction_errors:
        return {
            "ok": False,
            "record": None,
            "errors": correction_errors,
            "preserved": False,
        }

    resolved_data_file = resolve_data_file_path(data_file)
    resolved_module_file = resolve_module_file_path(module_file)
    records = storage_manager.load_records(resolved_data_file)
    latest = data_manager.get_latest_record(records, record_id)
    if latest is None:
        return {
            "ok": False,
            "record": None,
            "errors": [f"Record ID was not found: {record_id}"],
            "preserved": False,
        }

    corrected_fields = {
        field
        for field, value in updates.items()
        if value is not None
    }
    extraction = {
        "module": latest["module"],
        "assessment_type": updates.get(
            "assessment_type",
            latest["assessment_type"],
        ),
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
    contract_errors = contracts.validate_record_contract(corrected_record)
    if contract_errors:
        return {
            "ok": False,
            "record": None,
            "errors": contract_errors,
            "preserved": False,
        }
    if not storage_manager.save_record_revision(corrected_record, resolved_data_file):
        return {
            "ok": False,
            "record": None,
            "errors": ["The corrected assessment could not be saved."],
            "preserved": False,
        }

    return {
        "ok": True,
        "record": corrected_record,
        "errors": [],
        "preserved": False,
        "schedule": build_current_schedule(
            resolved_data_file,
            today=today,
            module_file=resolved_module_file,
        ),
    }


def reprocess_assessment(
    record_id: str,
    updates: Dict[str, Any],
    data_file: Optional[str] = None,
    module_file: Optional[str] = None,
    api_caller: Optional[Callable[..., str]] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Merge updates into the latest saved input fields and append a revision."""
    if not isinstance(updates, dict):
        return {
            "ok": False,
            "record": None,
            "errors": ["Assessment updates must be a JSON object."],
            "ai_attempts": 0,
            "preserved": False,
        }
    unexpected_fields = sorted(set(updates) - io_manager.ASSESSMENT_INPUT_FIELDS)
    if unexpected_fields:
        return {
            "ok": False,
            "record": None,
            "errors": [
                f"Unexpected input fields: {', '.join(unexpected_fields)}."
            ],
            "ai_attempts": 0,
            "preserved": False,
        }

    resolved_data_file = resolve_data_file_path(data_file)
    resolved_module_file = resolve_module_file_path(module_file)
    records = storage_manager.load_records(resolved_data_file)
    latest = data_manager.get_latest_record(records, record_id)
    if latest is None:
        return {
            "ok": False,
            "record": None,
            "errors": [f"Record ID was not found: {record_id}"],
            "ai_attempts": 0,
            "preserved": False,
        }

    merged_input = {
        "record_id": record_id,
        "module": latest["module"],
        "assessment_type": latest["assessment_type"],
        "deadline": latest["deadline"],
        "weightage": latest["weightage"],
        "prompt": "",
        "image_paths": [],
    }
    module_profiles = storage_manager.load_module_profiles(resolved_module_file)
    module_profile = module_profiles.get(latest["module"].strip().upper())
    if module_profile is not None:
        merged_input["module_credits"] = module_profile["credits"]
    for field in io_manager.ASSESSMENT_INPUT_FIELDS - {"record_id"}:
        if field in updates and updates[field] not in (None, "", []):
            merged_input[field] = updates[field]
    return process_assessment(
        merged_input,
        data_file=resolved_data_file,
        module_file=resolved_module_file,
        api_caller=api_caller,
        today=today,
        record_id=record_id,
    )


def process_batch(
    input_records: List[Any],
    data_file: Optional[str] = None,
    module_file: Optional[str] = None,
    api_caller: Optional[Callable[..., str]] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Process multiple isolated assessments and return one combined schedule."""
    resolved_data_file = resolve_data_file_path(data_file)
    resolved_module_file = resolve_module_file_path(module_file)
    if not isinstance(input_records, list) or not input_records:
        return {
            "ok": False,
            "results": [],
            "saved_count": 0,
            "schedule": build_current_schedule(
                resolved_data_file,
                today=today,
                module_file=resolved_module_file,
            ),
            "errors": ["Batch input must be a non-empty list."],
        }
    if len(input_records) > io_manager.MAX_BATCH_RECORDS:
        return {
            "ok": False,
            "results": [],
            "saved_count": 0,
            "schedule": build_current_schedule(
                resolved_data_file,
                today=today,
                module_file=resolved_module_file,
            ),
            "errors": [
                f"Batch input may contain at most {io_manager.MAX_BATCH_RECORDS} "
                "records."
            ],
        }

    results = []
    for input_record in input_records:
        if not isinstance(input_record, dict):
            results.append(
                {
                    "ok": False,
                    "record": None,
                    "errors": ["Assessment input must be a JSON object."],
                    "ai_attempts": 0,
                    "preserved": False,
                }
            )
            continue

        record_id = input_record.get("record_id")
        existing_records = storage_manager.load_records(resolved_data_file)
        if record_id and data_manager.get_latest_record(existing_records, record_id):
            result = reprocess_assessment(
                record_id,
                input_record,
                data_file=resolved_data_file,
                module_file=resolved_module_file,
                api_caller=api_caller,
                today=today,
            )
        else:
            result = process_assessment(
                input_record,
                data_file=resolved_data_file,
                module_file=resolved_module_file,
                api_caller=api_caller,
                today=today,
                record_id=record_id,
            )
        results.append(result)

    schedule = build_current_schedule(
        resolved_data_file,
        today=today,
        module_file=resolved_module_file,
    )
    return {
        "ok": all(result["ok"] for result in results),
        "results": results,
        "saved_count": sum(result.get("record") is not None for result in results),
        "schedule": schedule,
    }


def main(argv: Optional[List[str]] = None) -> int:
    """Start the command-line application."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    logging.info("Starting academic assessment prioritiser")
    arguments = io_manager.parse_cli_arguments(argv)

    if not io_manager.has_assessment_input(arguments):
        io_manager.display_startup_summary(
            start_application(data_file=arguments.get("data_file"))
        )
        return 0

    data_file = arguments.pop("data_file", None)
    batch_file = arguments.pop("batch_file", None)
    if batch_file:
        single_input_supplied = any(
            arguments.get(field) not in (None, "", [])
            for field in io_manager.ASSESSMENT_INPUT_FIELDS
        )
        if single_input_supplied:
            io_manager.display_processing_result(
                {
                    "ok": False,
                    "errors": [
                        "Use either --batch-file or single-assessment arguments."
                    ],
                }
            )
            return 2
        batch_input = io_manager.load_batch_input(batch_file)
        if batch_input["errors"]:
            io_manager.display_processing_result(
                {"ok": False, "errors": batch_input["errors"]}
            )
            return 2
        batch_result = process_batch(
            batch_input["records"],
            data_file=data_file,
        )
        io_manager.display_batch_result(batch_result)
        return 0 if batch_result["ok"] else 1

    record_id = arguments.get("record_id")
    if record_id:
        result = reprocess_assessment(
            record_id,
            arguments,
            data_file=data_file,
        )
    else:
        result = process_assessment(arguments, data_file=data_file)
    io_manager.display_processing_result(result)
    if result["ok"]:
        return 0
    return 2 if result.get("ai_attempts") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
