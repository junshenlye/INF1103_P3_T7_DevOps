"""Terminal input, validation, formatting, and output functions."""

import argparse
from datetime import date
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional


SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_BATCH_BYTES = 1024 * 1024
MAX_BATCH_RECORDS = 50
MAX_MODULE_CHARS = 32
MAX_ASSESSMENT_TYPE_CHARS = 120
MAX_PROMPT_CHARS = 4000
ASSESSMENT_INPUT_FIELDS = {
    "record_id",
    "module",
    "module_credits",
    "assessment_type",
    "deadline",
    "weightage",
    "prompt",
    "image_paths",
}


def parse_cli_arguments(argv: Optional[List[str]] = None) -> Dict[str, Any]:
    """Parse optional assessment fields from terminal arguments."""
    parser = argparse.ArgumentParser(
        description="Process an academic assessment through the AI pipeline."
    )
    parser.add_argument("--module")
    parser.add_argument("--module-credits", type=float)
    parser.add_argument("--assessment-type")
    parser.add_argument("--deadline")
    parser.add_argument("--weightage", type=float)
    parser.add_argument("--prompt", default="")
    parser.add_argument("--record-id")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        dest="image_paths",
        help="Local PNG, JPEG, WEBP, or GIF path; may be repeated.",
    )
    parser.add_argument("--data-file")
    parser.add_argument(
        "--batch-file",
        help="JSON file containing a list of assessment input records.",
    )
    return vars(parser.parse_args(argv))


def has_assessment_input(payload: Dict[str, Any]) -> bool:
    """Return whether CLI arguments request assessment processing."""
    fields = (
        "module",
        "module_credits",
        "assessment_type",
        "deadline",
        "weightage",
        "prompt",
        "image_paths",
        "record_id",
        "batch_file",
    )
    return any(payload.get(field) not in (None, "", []) for field in fields)


def validate_user_input(payload: Dict[str, Any]) -> List[str]:
    """Validate terminal input shape without applying business rules."""
    if not isinstance(payload, dict):
        return ["Assessment input must be a JSON object."]

    errors = []
    unexpected_fields = sorted(set(payload) - ASSESSMENT_INPUT_FIELDS)
    if unexpected_fields:
        errors.append(f"Unexpected input fields: {', '.join(unexpected_fields)}.")

    record_id = payload.get("record_id")
    if record_id is not None and (
        not isinstance(record_id, str) or not record_id.strip()
    ):
        errors.append("Record ID must be a non-empty string when supplied.")
    if not isinstance(payload.get("module"), str) or not payload["module"].strip():
        errors.append("Module is required.")
    elif len(payload["module"].strip()) > MAX_MODULE_CHARS:
        errors.append(f"Module may contain at most {MAX_MODULE_CHARS} characters.")
    module_credits = payload.get("module_credits")
    if module_credits is not None:
        if isinstance(module_credits, bool) or not isinstance(
            module_credits, (int, float)
        ):
            errors.append("Module credits must be a number or omitted.")
        elif not 0 < module_credits <= 60:
            errors.append("Module credits must be greater than 0 and at most 60.")
    if (
        not isinstance(payload.get("assessment_type"), str)
        or not payload["assessment_type"].strip()
    ):
        errors.append("Assessment type is required.")
    elif len(payload["assessment_type"].strip()) > MAX_ASSESSMENT_TYPE_CHARS:
        errors.append(
            f"Assessment type may contain at most {MAX_ASSESSMENT_TYPE_CHARS} "
            "characters."
        )

    deadline = payload.get("deadline")
    if deadline is not None:
        if not isinstance(deadline, str):
            errors.append("Deadline must be a string or omitted.")
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", deadline) is None:
            errors.append("Deadline must use YYYY-MM-DD format.")
        else:
            try:
                date.fromisoformat(deadline)
            except ValueError:
                errors.append("Deadline must use YYYY-MM-DD format.")

    weightage = payload.get("weightage")
    if weightage is not None:
        if isinstance(weightage, bool) or not isinstance(weightage, (int, float)):
            errors.append("Weightage must be a number or omitted.")
        elif not 0 <= weightage <= 100:
            errors.append("Weightage must be between 0 and 100.")

    prompt = payload.get("prompt", "")
    if not isinstance(prompt, str):
        errors.append("Prompt must be text.")
    elif len(prompt) > MAX_PROMPT_CHARS:
        errors.append(f"Prompt may contain at most {MAX_PROMPT_CHARS} characters.")

    image_paths = payload.get("image_paths", [])
    if not isinstance(image_paths, list):
        errors.append("Images must be supplied as a list of paths.")
    else:
        for image_path in image_paths:
            errors.extend(_validate_image_path(image_path))
    return errors


def load_batch_input(batch_file: str) -> Dict[str, Any]:
    """Load a bounded JSON list and resolve its relative image paths."""
    path = Path(batch_file)
    if not path.is_file():
        return {"records": [], "errors": [f"Batch file was not found: {batch_file}"]}
    try:
        if path.stat().st_size > MAX_BATCH_BYTES:
            return {
                "records": [],
                "errors": ["Batch file exceeds the 1 MB MVP limit."],
            }
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"records": [], "errors": ["Batch file is not valid JSON."]}

    if not isinstance(payload, list) or not payload:
        return {
            "records": [],
            "errors": ["Batch file must contain a non-empty JSON list."],
        }
    if len(payload) > MAX_BATCH_RECORDS:
        return {
            "records": [],
            "errors": [f"Batch file may contain at most {MAX_BATCH_RECORDS} records."],
        }

    records = []
    for item in payload:
        if not isinstance(item, dict):
            records.append(item)
            continue
        record = dict(item)
        image_paths = record.get("image_paths", [])
        if isinstance(image_paths, list):
            record["image_paths"] = [
                str(path.parent / image_path)
                if isinstance(image_path, str)
                and image_path
                and not Path(image_path).is_absolute()
                else image_path
                for image_path in image_paths
            ]
        records.append(record)
    return {"records": records, "errors": []}


def _validate_image_path(image_path: Any) -> List[str]:
    """Return input errors for one local image path."""
    if not isinstance(image_path, str) or not image_path:
        return ["Each image path must be a non-empty string."]

    path = Path(image_path)
    if not path.is_file():
        return [f"Image file was not found: {image_path}"]
    if path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
        return [f"Unsupported image type: {image_path}"]
    if path.stat().st_size > MAX_IMAGE_BYTES:
        return [f"Image exceeds the 10 MB MVP limit: {image_path}"]
    return []


def format_startup_summary(summary: Dict[str, Any]) -> str:
    """Format the initial CLI status without producing output directly."""
    startup = (
        "Academic Assessment Prioritiser\n"
        f"Loaded {summary['records_loaded']} saved record(s).\n"
        "Supply --module and --assessment-type to process an assessment."
    )
    if summary.get("schedule") is None:
        return startup
    return f"{startup}\n{format_schedule(summary['schedule'])}"


def format_record(record: Dict[str, Any]) -> str:
    """Format one processed record for terminal display."""
    summary = (
        f"Record ID: {record['record_id']}\n"
        f"Module: {record['module']}\n"
        f"Assessment: {record['assessment_type']}\n"
        f"Deadline: {record['deadline']}\n"
        f"Weightage: {record['weightage']}\n"
        f"Status: {record['status']}\n"
        f"Priority: {record['priority']}\n"
        f"Revision: {record['revision']}"
    )
    issues = record.get("issues", [])
    if not issues:
        return summary

    feedback = "\n".join(
        f"- [{issue['severity']}] {issue['feedback']}" for issue in issues
    )
    return f"{summary}\nFeedback:\n{feedback}"


def format_schedule(schedule: Dict[str, Any]) -> str:
    """Format a derived multi-assessment schedule."""
    lines = ["Schedule blocks:"]
    blocks = schedule.get("blocks", [])
    if not blocks:
        lines.append("- No READY assessments can be scheduled yet.")
    for block in blocks:
        credit_summary = ""
        if block.get("module_credits") is not None:
            credit_summary = (
                f", {block['module_credits']:g} credits, "
                f"load {block['credit_weighted_load']:g}"
            )
        lines.append(
            f"- {block['start_date']} to {block['end_date']}: "
            f"{block['module']} {block['assessment_type']} "
            f"({block['priority']}, due {block['deadline']}, "
            f"{block['block_size_days']} day(s){credit_summary})"
        )
    warnings = schedule.get("warnings", [])
    if warnings:
        lines.append("Schedule warnings:")
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines)


def format_batch_result(result: Dict[str, Any]) -> str:
    """Format isolated per-record outcomes and their combined schedule."""
    lines = [
        f"Processed {len(result.get('results', []))} assessment record(s).",
        f"Saved {result.get('saved_count', 0)} record revision(s).",
    ]
    lines.extend(f"Error: {error}" for error in result.get("errors", []))
    for index, item_result in enumerate(result.get("results", []), start=1):
        record = item_result.get("record")
        if record is not None:
            record_line = (
                f"{index}. {record['module']} {record['assessment_type']}: "
                f"{record['status']}"
            )
            if not item_result.get("ok"):
                errors = "; ".join(item_result.get("errors", []))
                record_line = f"{record_line} (preserved: {errors})"
            lines.append(record_line)
        else:
            errors = "; ".join(item_result.get("errors", ["Unknown error."]))
            lines.append(f"{index}. Not saved: {errors}")
    lines.append(format_schedule(result.get("schedule", {})))
    return "\n".join(lines)


def display_startup_summary(summary: Dict[str, Any]) -> None:
    """Display the initial CLI status."""
    print(format_startup_summary(summary))


def display_processing_result(result: Dict[str, Any]) -> None:
    """Display either a processed record or safe errors."""
    if result.get("ok"):
        print(format_record(result["record"]))
        if result.get("schedule") is not None:
            print(format_schedule(result["schedule"]))
        return
    print("Processing failed:")
    for error in result.get("errors", ["Unknown error."]):
        print(f"- {error}")
    if result.get("record") is not None:
        print("Recoverable input was preserved:")
        print(format_record(result["record"]))
    if result.get("schedule") is not None:
        print(format_schedule(result["schedule"]))


def display_batch_result(result: Dict[str, Any]) -> None:
    """Display one multi-assessment batch result."""
    print(format_batch_result(result))


def display_message(message: str) -> None:
    """Display a user-facing message from another procedural module."""
    print(message)
