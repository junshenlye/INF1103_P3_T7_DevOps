"""Terminal input, validation, formatting, and output functions."""

import argparse
from datetime import date
from pathlib import Path
import re
from typing import Any, Dict, List, Optional


SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def parse_cli_arguments(argv: Optional[List[str]] = None) -> Dict[str, Any]:
    """Parse optional assessment fields from terminal arguments."""
    parser = argparse.ArgumentParser(
        description="Process an academic assessment through the AI pipeline."
    )
    parser.add_argument("--module")
    parser.add_argument("--assessment-type")
    parser.add_argument("--deadline")
    parser.add_argument("--weightage", type=float)
    parser.add_argument("--prompt", default="")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        dest="image_paths",
        help="Local PNG, JPEG, WEBP, or GIF path; may be repeated.",
    )
    parser.add_argument("--data-file")
    return vars(parser.parse_args(argv))


def has_assessment_input(payload: Dict[str, Any]) -> bool:
    """Return whether CLI arguments request assessment processing."""
    fields = (
        "module",
        "assessment_type",
        "deadline",
        "weightage",
        "prompt",
        "image_paths",
    )
    return any(payload.get(field) not in (None, "", []) for field in fields)


def validate_user_input(payload: Dict[str, Any]) -> List[str]:
    """Validate terminal input shape without applying business rules."""
    errors = []
    if not isinstance(payload.get("module"), str) or not payload["module"].strip():
        errors.append("Module is required.")
    if (
        not isinstance(payload.get("assessment_type"), str)
        or not payload["assessment_type"].strip()
    ):
        errors.append("Assessment type is required.")

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

    image_paths = payload.get("image_paths", [])
    if not isinstance(image_paths, list):
        errors.append("Images must be supplied as a list of paths.")
    else:
        for image_path in image_paths:
            errors.extend(_validate_image_path(image_path))
    return errors


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
    return (
        "Academic Assessment Prioritiser\n"
        f"Loaded {summary['records_loaded']} saved record(s).\n"
        "Supply --module and --assessment-type to process an assessment."
    )


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


def display_startup_summary(summary: Dict[str, Any]) -> None:
    """Display the initial CLI status."""
    print(format_startup_summary(summary))


def display_processing_result(result: Dict[str, Any]) -> None:
    """Display either a processed record or safe errors."""
    if result.get("ok"):
        print(format_record(result["record"]))
        return
    print("Processing failed:")
    for error in result.get("errors", ["Unknown error."]):
        print(f"- {error}")


def display_message(message: str) -> None:
    """Display a user-facing message from another procedural module."""
    print(message)
