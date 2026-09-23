"""Deterministic assessment status and priority business rules."""

from datetime import date
from typing import Any, Dict, Optional


def calculate_priority(
    deadline: str,
    weightage: float,
    today: Optional[date] = None,
) -> str:
    """Calculate a simple priority from deadline proximity and weightage."""
    reference_date = today or date.today()
    days_remaining = (date.fromisoformat(deadline) - reference_date).days

    if days_remaining <= 7:
        urgency_score = 3
    elif days_remaining <= 14:
        urgency_score = 2
    else:
        urgency_score = 1

    if weightage >= 40:
        weightage_score = 3
    elif weightage >= 20:
        weightage_score = 2
    else:
        weightage_score = 1

    total_score = urgency_score + weightage_score
    if total_score >= 5:
        return "HIGH"
    if total_score >= 3:
        return "MEDIUM"
    return "LOW"


def apply_business_rules(
    ai_record: Dict[str, Any],
    record_id: str,
    revision: int,
    scheduling_context: Optional[Dict[str, Any]] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Construct an exact contract record with authoritative business fields."""
    missing_fields = [
        field
        for field in ("deadline", "weightage")
        if ai_record.get(field) is None
    ]
    blocking_issues = [
        issue
        for issue in ai_record.get("issues", [])
        if issue.get("severity") == "error"
    ]
    if missing_fields:
        status = "INCOMPLETE"
    elif blocking_issues:
        status = "NEEDS_REVIEW"
    else:
        status = "READY"
    priority = None
    if status == "READY":
        priority = calculate_priority(
            ai_record["deadline"],
            ai_record["weightage"],
            today=today,
        )

    return {
        "record_id": record_id,
        "module": ai_record.get("module", ""),
        "assessment_type": ai_record.get("assessment_type", ""),
        "deadline": ai_record.get("deadline"),
        "weightage": ai_record.get("weightage"),
        "priority": priority,
        "status": status,
        "missing_fields": missing_fields,
        "issues": list(ai_record.get("issues", [])),
        "revision": revision,
    }
