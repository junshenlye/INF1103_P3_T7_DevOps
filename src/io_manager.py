"""Input validation and user-facing output functions."""

import argparse
from datetime import date
from pathlib import Path
import re
from typing import Any, Dict, List, Optional


SUPPORTED_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_MODULE_CHARS = 32
MAX_ASSESSMENT_TYPE_CHARS = 120
MAX_PROMPT_CHARS = 4000
SOURCE_INPUT_FIELDS = frozenset(
    {"module", "module_credits", "prompt", "image_paths"}
)
CORRECTION_INPUT_FIELDS = frozenset(
    {"assessment_type", "deadline", "weightage"}
)
RECORD_FIELDS = (
    "record_id",
    "module",
    "assessment_type",
    "deadline",
    "weightage",
    "priority",
    "status",
    "missing_fields",
    "issues",
    "revision",
)
VALID_PRIORITIES = ("HIGH", "MEDIUM", "LOW")
VALID_STATUSES = (
    "READY",
    "INCOMPLETE",
    "NEEDS_REVIEW",
    "CONFLICT",
    "CONSTRAINED",
)
VALID_SEVERITIES = ("info", "warning", "error")


def parse_cli_arguments(argv: Optional[List[str]] = None) -> Dict[str, Any]:
    """Parse one module evidence pack from terminal arguments."""
    parser = argparse.ArgumentParser(
        description="Extract one module's assessments and build its timetable."
    )
    parser.add_argument("--module")
    parser.add_argument("--module-credits", type=float)
    parser.add_argument("--prompt", default="")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        dest="image_paths",
        help="PNG, JPEG, WEBP, or GIF path; may be repeated.",
    )
    parser.add_argument("--data-file")
    parser.add_argument("--module-file")
    return vars(parser.parse_args(argv))


def has_source_input(payload: Dict[str, Any]) -> bool:
    """Return whether CLI arguments contain a module evidence pack."""
    return any(
        payload.get(field) not in (None, "", [])
        for field in SOURCE_INPUT_FIELDS
    )


def validate_source_input(payload: Dict[str, Any]) -> List[str]:
    """Validate one module evidence pack before AI processing."""
    if not isinstance(payload, dict):
        return ["Module evidence must be a JSON object."]

    errors = []
    unexpected_fields = sorted(set(payload) - SOURCE_INPUT_FIELDS)
    if unexpected_fields:
        errors.append(f"Unexpected source fields: {', '.join(unexpected_fields)}.")

    module = payload.get("module")
    if not isinstance(module, str) or not module.strip():
        errors.append("Module is required.")
    elif len(module.strip()) > MAX_MODULE_CHARS:
        errors.append(f"Module may contain at most {MAX_MODULE_CHARS} characters.")

    module_credits = payload.get("module_credits")
    if isinstance(module_credits, bool) or not isinstance(
        module_credits,
        (int, float),
    ):
        errors.append("Module credits are required and must be a number.")
    elif not 0 < module_credits <= 60:
        errors.append("Module credits must be greater than 0 and at most 60.")

    prompt = payload.get("prompt", "")
    if not isinstance(prompt, str):
        errors.append("Prompt must be text.")
    elif len(prompt) > MAX_PROMPT_CHARS:
        errors.append(f"Prompt may contain at most {MAX_PROMPT_CHARS} characters.")

    image_paths = payload.get("image_paths", [])
    if not isinstance(image_paths, list):
        errors.append("Images must be supplied as a list of paths.")
        image_paths = []
    else:
        for image_path in image_paths:
            errors.extend(_validate_image_path(image_path))
    if isinstance(prompt, str) and not prompt.strip() and not image_paths:
        errors.append("Add at least one screenshot or a context prompt.")
    return errors


def validate_correction_input(payload: Dict[str, Any]) -> List[str]:
    """Validate human corrections for one extracted assessment."""
    if not isinstance(payload, dict):
        return ["Assessment corrections must be a JSON object."]

    errors = []
    unexpected_fields = sorted(set(payload) - CORRECTION_INPUT_FIELDS)
    if unexpected_fields:
        errors.append(f"Unexpected correction fields: {', '.join(unexpected_fields)}.")
    if not payload:
        errors.append("At least one assessment correction is required.")

    if "assessment_type" in payload:
        assessment_type = payload["assessment_type"]
        if not isinstance(assessment_type, str) or not assessment_type.strip():
            errors.append("Assessment type is required.")
        elif len(assessment_type.strip()) > MAX_ASSESSMENT_TYPE_CHARS:
            errors.append(
                f"Assessment type may contain at most {MAX_ASSESSMENT_TYPE_CHARS} "
                "characters."
            )
    errors.extend(_validate_optional_date(payload.get("deadline"), "Deadline"))
    errors.extend(
        _validate_optional_percentage(payload.get("weightage"), "Weightage")
    )
    return errors


def validate_record(record: Dict[str, Any]) -> List[str]:
    """Validate the frozen record passed from Logic to Data Manager."""
    if not isinstance(record, dict):
        return ["Record must be a dictionary."]

    errors = []
    missing = [field for field in RECORD_FIELDS if field not in record]
    extra = [field for field in record if field not in RECORD_FIELDS]
    if missing:
        errors.append(f"Missing contract fields: {', '.join(missing)}.")
    if extra:
        errors.append(f"Unexpected contract fields: {', '.join(extra)}.")
    if errors:
        return errors

    if not isinstance(record["record_id"], str):
        errors.append("record_id must be a string.")
    if not isinstance(record["module"], str):
        errors.append("module must be a string.")
    if not isinstance(record["assessment_type"], str):
        errors.append("assessment_type must be a string.")
    errors.extend(_validate_optional_date(record["deadline"], "deadline"))
    errors.extend(_validate_optional_percentage(record["weightage"], "weightage"))
    if record["priority"] is not None and record["priority"] not in VALID_PRIORITIES:
        errors.append("priority must be HIGH, MEDIUM, LOW, or null.")
    if record["status"] not in VALID_STATUSES:
        errors.append("status is not an allowed value.")
    if not isinstance(record["missing_fields"], list) or not all(
        isinstance(field, str) for field in record["missing_fields"]
    ):
        errors.append("missing_fields must be a list of strings.")
    if not isinstance(record["issues"], list):
        errors.append("issues must be a list.")
    else:
        for index, issue in enumerate(record["issues"]):
            errors.extend(validate_issue(issue, index))
    revision = record["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        errors.append("revision must be an integer starting at 1.")
    return errors


def validate_issue(issue: Any, index: int = 0) -> List[str]:
    """Validate one structured data-quality issue."""
    label = f"issues[{index}]"
    if not isinstance(issue, dict):
        return [f"{label} must be a dictionary."]
    if set(issue) != {"type", "field", "severity", "feedback"}:
        return [f"{label} must contain type, field, severity, and feedback."]

    errors = []
    if not isinstance(issue["type"], str):
        errors.append(f"{label}.type must be a string.")
    if issue["field"] is not None and not isinstance(issue["field"], str):
        errors.append(f"{label}.field must be a string or null.")
    if issue["severity"] not in VALID_SEVERITIES:
        errors.append(f"{label}.severity is not an allowed value.")
    if not isinstance(issue["feedback"], str):
        errors.append(f"{label}.feedback must be a string.")
    return errors


def _validate_image_path(image_path: Any) -> List[str]:
    """Validate one local image path."""
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


def _validate_optional_date(value: Any, field: str) -> List[str]:
    """Validate one optional ISO date."""
    if value is None:
        return []
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        return [f"{field} must use YYYY-MM-DD format or null."]
    try:
        date.fromisoformat(value)
    except ValueError:
        return [f"{field} must use YYYY-MM-DD format or null."]
    return []


def _validate_optional_percentage(value: Any, field: str) -> List[str]:
    """Validate one optional percentage."""
    if value is None:
        return []
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return [f"{field} must be a number or null."]
    if not 0 <= value <= 100:
        return [f"{field} must be between 0 and 100."]
    return []


def format_schedule(schedule: Dict[str, Any]) -> str:
    """Format one module's derived timetable."""
    lines = ["Timetable blocks:"]
    blocks = schedule.get("blocks", [])
    if not blocks:
        lines.append("- No READY assessments can be scheduled yet.")
    for block in blocks:
        lines.append(
            f"- {block['start_date']} to {block['end_date']}: "
            f"{block['assessment_type']} ({block['priority']}, "
            f"due {block['deadline']})"
        )
    lines.extend(f"Warning: {warning}" for warning in schedule.get("warnings", []))
    return "\n".join(lines)


def format_startup_summary(summary: Dict[str, Any]) -> str:
    """Format the current CLI state."""
    module = summary.get("focus_module") or "No module"
    return (
        "Academic Assessment Prioritiser\n"
        f"{module}: {summary['records_loaded']} assessment(s).\n"
        f"{format_schedule(summary['schedule'])}"
    )


def format_source_result(result: Dict[str, Any]) -> str:
    """Format one complete module extraction result."""
    if not result.get("ok"):
        errors = "\n".join(f"- {error}" for error in result.get("errors", []))
        return f"Processing failed:\n{errors}"
    return (
        f"{result['source_module']}: extracted "
        f"{result['extracted_count']} assessment(s).\n"
        f"{format_schedule(result['schedule'])}"
    )


def display_startup_summary(summary: Dict[str, Any]) -> None:
    """Display current CLI state."""
    print(format_startup_summary(summary))


def display_source_result(result: Dict[str, Any]) -> None:
    """Display one module extraction result."""
    print(format_source_result(result))
