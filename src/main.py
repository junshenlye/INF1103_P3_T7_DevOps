"""CLI entry point and procedural application orchestration."""

from datetime import date
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv

from . import ai_manager, contracts, data_manager, io_manager, logic_manager


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_FILE = PROJECT_ROOT / "data" / "schedules.json"


def resolve_data_file_path(configured_path: Optional[str] = None) -> str:
    """Resolve an environment or caller-provided data file path."""
    raw_path = configured_path or os.getenv("DATA_FILE")
    if not raw_path:
        return str(DEFAULT_DATA_FILE)

    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path)


def start_application(data_file: Optional[str] = None) -> Dict[str, Any]:
    """Load local configuration and existing records without starting a UI loop."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    resolved_data_file = resolve_data_file_path(data_file)
    records = data_manager.load_records(resolved_data_file)
    return {
        "records": records,
        "records_loaded": len(records),
        "data_file": resolved_data_file,
    }


def process_assessment(
    input_record: Dict[str, Any],
    data_file: Optional[str] = None,
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

    ai_result = ai_manager.process_record(input_record, api_caller=api_caller)
    if not ai_result["ok"]:
        return {
            "ok": False,
            "record": None,
            "errors": ai_result["errors"],
            "ai_attempts": ai_result["attempts"],
        }

    final_record = logic_manager.apply_business_rules(
        ai_result["extraction"],
        record_id=record_id or data_manager.generate_record_id(),
        revision=1,
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

    resolved_data_file = resolve_data_file_path(data_file)
    if not data_manager.save_record_revision(final_record, resolved_data_file):
        return {
            "ok": False,
            "record": None,
            "errors": ["The processed record could not be saved."],
            "ai_attempts": ai_result["attempts"],
        }

    return {
        "ok": True,
        "record": final_record,
        "errors": [],
        "ai_attempts": ai_result["attempts"],
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
    result = process_assessment(arguments, data_file=data_file)
    io_manager.display_processing_result(result)
    if result["ok"]:
        return 0
    return 2 if result.get("ai_attempts") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
