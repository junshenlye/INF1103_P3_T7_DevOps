"""Deterministic status, priority, and week-block rules."""

import re
from typing import Any, Dict, List


def deadline_week(deadline: str) -> int:
    """Convert a validated 'Week N' deadline into its week number."""
    return int(re.fullmatch(r"Week ([1-9]|[1-4][0-9]|5[0-2])", deadline).group(1))


def calculate_priority(deadline: str, weightage: float) -> str:
    """Prioritise earlier and heavier assessments with a small score."""
    week = deadline_week(deadline)
    urgency = 3 if week <= 3 else 2 if week <= 7 else 1
    impact = 3 if weightage >= 40 else 2 if weightage >= 20 else 1
    score = urgency + impact
    if score >= 5:
        return "HIGH"
    if score >= 3:
        return "MEDIUM"
    return "LOW"


def apply_business_rules(
    ai_record: Dict[str, Any],
    record_id: str,
    revision: int,
) -> Dict[str, Any]:
    """Turn one validated AI event into the frozen saved record."""
    missing_fields = [
        field
        for field in ("deadline", "weightage")
        if ai_record.get(field) is None
    ]
    error_issues = [
        issue
        for issue in ai_record.get("issues", [])
        if issue.get("severity") == "error"
    ]
    has_conflict = any(
        "conflict" in issue.get("type", "").lower()
        or "disagree" in issue.get("type", "").lower()
        for issue in error_issues
    )
    if has_conflict:
        status = "CONFLICT"
    elif missing_fields:
        status = "INCOMPLETE"
    elif error_issues:
        status = "NEEDS_REVIEW"
    else:
        status = "READY"

    priority = None
    if status == "READY":
        priority = calculate_priority(
            ai_record["deadline"],
            ai_record["weightage"],
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


def build_schedule(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Group one module's READY assessments into compact week columns."""
    blocks = []
    excluded_records = []
    for record in records:
        if record.get("status") != "READY":
            excluded_records.append(
                {
                    "record_id": record.get("record_id"),
                    "module": record.get("module"),
                    "status": record.get("status"),
                }
            )
            continue
        blocks.append(
            {
                "record_id": record["record_id"],
                "revision": record["revision"],
                "module": record["module"],
                "assessment_type": record["assessment_type"],
                "deadline": record["deadline"],
                "week_number": deadline_week(record["deadline"]),
                "priority": record["priority"],
                "assessment_weightage": record["weightage"],
            }
        )

    blocks.sort(
        key=lambda block: (
            block["week_number"],
            ("LOW", "MEDIUM", "HIGH").index(block["priority"]),
            block["assessment_weightage"],
            block["record_id"],
        )
    )
    _assign_stack_positions(blocks)
    warnings = []
    if excluded_records:
        warnings.append(
            f"{len(excluded_records)} assessment(s) need review before scheduling."
        )
    return {
        "blocks": blocks,
        "weeks": _build_week_columns(blocks),
        "excluded_records": excluded_records,
        "warnings": warnings,
    }


def _assign_stack_positions(blocks: List[Dict[str, Any]]) -> None:
    """Place higher-priority assessments lower in the same week."""
    week_counts = {}
    for block in blocks:
        week = block["week_number"]
        block["stack_index"] = week_counts.get(week, 0)
        week_counts[week] = block["stack_index"] + 1


def _build_week_columns(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Create a continuous Week 1 to final-deadline range."""
    if not blocks:
        return []
    final_week = max(block["week_number"] for block in blocks)
    return [
        {
            "week_number": week,
            "label": f"Week {week}",
            "blocks": [block for block in blocks if block["week_number"] == week],
        }
        for week in range(1, final_week + 1)
    ]
