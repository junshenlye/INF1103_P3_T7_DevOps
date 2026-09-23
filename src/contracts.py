"""Frozen shared data contract and schema checks.

This module contains structure only. It deliberately contains no scheduling or
priority business rules.
"""

from datetime import date
import re
from typing import Any, Dict, List


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


def validate_record_contract(record: Dict[str, Any]) -> List[str]:
    """Return schema errors for a final persisted assessment record."""
    if not isinstance(record, dict):
        return ["Record must be a dictionary."]

    errors = []
    missing_fields = [field for field in RECORD_FIELDS if field not in record]
    extra_fields = [field for field in record if field not in RECORD_FIELDS]
    if missing_fields:
        errors.append(f"Missing contract fields: {', '.join(missing_fields)}.")
    if extra_fields:
        errors.append(f"Unexpected contract fields: {', '.join(extra_fields)}.")
    if errors:
        return errors

    if not isinstance(record["record_id"], str):
        errors.append("record_id must be a string.")
    if not isinstance(record["module"], str):
        errors.append("module must be a string.")
    if not isinstance(record["assessment_type"], str):
        errors.append("assessment_type must be a string.")

    deadline = record["deadline"]
    if deadline is not None:
        if not isinstance(deadline, str):
            errors.append("deadline must be an ISO date string or null.")
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", deadline) is None:
            errors.append("deadline must use YYYY-MM-DD format.")
        else:
            try:
                date.fromisoformat(deadline)
            except ValueError:
                errors.append("deadline must use YYYY-MM-DD format.")

    weightage = record["weightage"]
    if weightage is not None:
        if isinstance(weightage, bool) or not isinstance(weightage, (int, float)):
            errors.append("weightage must be a number or null.")
        elif not 0 <= weightage <= 100:
            errors.append("weightage must be between 0 and 100.")

    priority = record["priority"]
    if priority is not None and priority not in VALID_PRIORITIES:
        errors.append("priority must be HIGH, MEDIUM, LOW, or null.")
    if record["status"] not in VALID_STATUSES:
        errors.append("status is not an allowed value.")

    if not isinstance(record["missing_fields"], list) or not all(
        isinstance(field, str) for field in record["missing_fields"]
    ):
        errors.append("missing_fields must be a list of strings.")

    issues = record["issues"]
    if not isinstance(issues, list):
        errors.append("issues must be a list.")
    else:
        for index, issue in enumerate(issues):
            errors.extend(validate_issue_contract(issue, index))

    revision = record["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        errors.append("revision must be an integer starting at 1.")

    return errors


def validate_issue_contract(issue: Any, index: int = 0) -> List[str]:
    """Return schema errors for one issue entry."""
    label = f"issues[{index}]"
    if not isinstance(issue, dict):
        return [f"{label} must be a dictionary."]

    required_fields = ("type", "field", "severity", "feedback")
    if set(issue) != set(required_fields):
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
