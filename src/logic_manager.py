"""Deterministic assessment status and priority business rules."""

from datetime import date, timedelta
from typing import Any, Dict, List, Optional


PREPARATION_DAYS = {
    "HIGH": 5,
    "MEDIUM": 3,
    "LOW": 2,
}
BASELINE_MODULE_CREDITS = 6
STACK_ORDER = {
    "LOW": 0,
    "MEDIUM": 1,
    "HIGH": 2,
}


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
    conflict_issues = [
        issue
        for issue in blocking_issues
        if "conflict" in issue.get("type", "").lower()
        or "disagree" in issue.get("type", "").lower()
    ]
    reference_date = today or date.today()
    deadline = ai_record.get("deadline")
    if conflict_issues:
        status = "CONFLICT"
    elif missing_fields:
        status = "INCOMPLETE"
    elif date.fromisoformat(deadline) <= reference_date:
        status = "CONSTRAINED"
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


def build_recoverable_record(
    input_record: Dict[str, Any],
    processing_errors: List[str],
    record_id: str,
    revision: int,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Preserve trusted input after the AI exhausts its bounded attempts."""
    feedback = " ".join(processing_errors) or "AI processing failed."
    extraction = {
        "module": input_record["module"],
        "assessment_type": input_record["assessment_type"],
        "deadline": input_record.get("deadline"),
        "weightage": input_record.get("weightage"),
        "missing_fields": [
            field
            for field in ("deadline", "weightage")
            if input_record.get(field) is None
        ],
        "issues": [
            {
                "type": "AI_PROCESSING_FAILURE",
                "field": None,
                "severity": "error",
                "feedback": feedback,
            }
        ],
    }
    return apply_business_rules(
        extraction,
        record_id=record_id,
        revision=revision,
        today=today,
    )


def build_schedule(
    records: List[Dict[str, Any]],
    today: Optional[date] = None,
    module_profiles: Optional[Dict[str, Dict[str, float]]] = None,
) -> Dict[str, Any]:
    """Build deterministic preparation blocks from the latest READY records."""
    reference_date = today or date.today()
    profiles = module_profiles or {}
    blocks = []
    excluded_records = []
    warnings = []

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

        deadline = date.fromisoformat(record["deadline"])
        preparation_end = deadline - timedelta(days=1)
        if preparation_end < reference_date:
            excluded_records.append(
                {
                    "record_id": record["record_id"],
                    "module": record["module"],
                    "status": "CONSTRAINED",
                }
            )
            warnings.append(
                f"{record['module']} {record['assessment_type']} has no future "
                "preparation day available."
            )
            continue

        module_profile = profiles.get(record["module"].strip().upper(), {})
        module_credits = module_profile.get("credits")
        schedule_priority = record["priority"]
        effective_weightage = record["weightage"]
        credit_weighted_load = None
        if module_credits is not None:
            credit_weighted_load = round(
                record["weightage"] * module_credits / 100,
                2,
            )
            effective_weightage = min(
                100,
                record["weightage"]
                * module_credits
                / BASELINE_MODULE_CREDITS,
            )
            schedule_priority = calculate_priority(
                record["deadline"],
                effective_weightage,
                today=reference_date,
            )

        requested_days = PREPARATION_DAYS[schedule_priority]
        preparation_start = preparation_end - timedelta(days=requested_days - 1)
        if preparation_start < reference_date:
            preparation_start = reference_date
            warnings.append(
                f"{record['module']} {record['assessment_type']} has a shortened "
                "preparation block."
            )

        actual_days = (preparation_end - preparation_start).days + 1
        week_start = deadline - timedelta(days=deadline.weekday())
        blocks.append(
            {
                "record_id": record["record_id"],
                "revision": record["revision"],
                "module": record["module"],
                "assessment_type": record["assessment_type"],
                "deadline": record["deadline"],
                "start_date": preparation_start.isoformat(),
                "end_date": preparation_end.isoformat(),
                "block_size_days": actual_days,
                "priority": schedule_priority,
                "record_priority": record["priority"],
                "assessment_weightage": record["weightage"],
                "module_credits": module_credits,
                "credit_weighted_load": credit_weighted_load,
                "effective_weightage": round(effective_weightage, 2),
                "week_start": week_start.isoformat(),
                "week_end": (week_start + timedelta(days=6)).isoformat(),
            }
        )

    blocks.sort(
        key=lambda block: (
            block["week_start"],
            STACK_ORDER[block["priority"]],
            block["deadline"],
            block["record_id"],
        )
    )
    _assign_stack_positions(blocks)
    if _has_overlapping_blocks(blocks):
        warnings.append(
            "Some preparation blocks overlap and should be displayed as "
            "competing workload."
        )
    if excluded_records:
        warnings.append(
            f"{len(excluded_records)} record(s) were preserved but excluded "
            "from the schedule."
        )

    return {
        "blocks": blocks,
        "weeks": _build_week_columns(blocks),
        "excluded_records": excluded_records,
        "warnings": warnings,
    }


def _assign_stack_positions(blocks: List[Dict[str, Any]]) -> None:
    """Assign low-to-high vertical positions so HIGH sits at the bottom."""
    week_counts = {}
    for block in blocks:
        week_start = block["week_start"]
        block["stack_index"] = week_counts.get(week_start, 0)
        week_counts[week_start] = block["stack_index"] + 1


def _build_week_columns(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build bounded horizontal columns for weeks containing schedule blocks."""
    if not blocks:
        return []

    weeks = []
    week_starts = sorted(
        {date.fromisoformat(block["week_start"]) for block in blocks}
    )
    for week_start in week_starts:
        week_key = week_start.isoformat()
        weeks.append(
            {
                "week_start": week_key,
                "week_end": (week_start + timedelta(days=6)).isoformat(),
                "label": week_start.strftime("Week of %d %b"),
                "blocks": [
                    block for block in blocks if block["week_start"] == week_key
                ],
            }
        )
    return weeks


def _has_overlapping_blocks(blocks: List[Dict[str, Any]]) -> bool:
    """Return whether any two inclusive preparation ranges overlap."""
    for index, block in enumerate(blocks):
        start = date.fromisoformat(block["start_date"])
        end = date.fromisoformat(block["end_date"])
        for other in blocks[index + 1 :]:
            other_start = date.fromisoformat(other["start_date"])
            other_end = date.fromisoformat(other["end_date"])
            if start <= other_end and other_start <= end:
                return True
    return False
