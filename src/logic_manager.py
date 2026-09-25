"""Build deterministic trimester pacing calculations from extracted facts."""

from datetime import date, datetime
from zoneinfo import ZoneInfo


PRESSURE_THRESHOLDS = (
    (15, "low"),
    (35, "moderate"),
    (65, "high"),
    (float("inf"), "very_high"),
)
MAX_FINAL_FEEDBACK_ITEMS = 10
TRIMESTER_WEEKS = (
    (1, date(2026, 8, 31), date(2026, 9, 6), False),
    (2, date(2026, 9, 7), date(2026, 9, 13), False),
    (3, date(2026, 9, 14), date(2026, 9, 20), False),
    (4, date(2026, 9, 21), date(2026, 9, 27), False),
    (5, date(2026, 9, 28), date(2026, 10, 4), False),
    (6, date(2026, 10, 5), date(2026, 10, 11), False),
    (7, date(2026, 10, 12), date(2026, 10, 18), True),
    (8, date(2026, 10, 19), date(2026, 10, 25), False),
    (9, date(2026, 10, 26), date(2026, 11, 1), False),
    (10, date(2026, 11, 2), date(2026, 11, 8), False),
    (11, date(2026, 11, 9), date(2026, 11, 15), False),
    (12, date(2026, 11, 16), date(2026, 11, 22), False),
    (13, date(2026, 11, 23), date(2026, 11, 29), False),
    (14, date(2026, 11, 30), date(2026, 12, 6), False),
)
# Public trimester API


def get_trimester_context(current_date=None):
    """Return the configured AY2026/27 Trimester 1 position."""
    value = current_date or datetime.now(ZoneInfo("Asia/Singapore")).date()
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, str):
        value = date.fromisoformat(value)
    if not isinstance(value, date):
        raise TypeError("current_date must be a date, datetime, ISO date, or None.")

    current_week = None
    is_recess = False
    for week, start, end, recess in TRIMESTER_WEEKS:
        if start <= value <= end:
            current_week = week
            is_recess = recess
            break

    status = "in_trimester"
    if value < TRIMESTER_WEEKS[0][1]:
        status = "before_trimester"
    elif value > TRIMESTER_WEEKS[-1][2]:
        status = "after_trimester"

    return {
        "academic_year": "2026/27",
        "trimester": 1,
        "current_date": value.isoformat(),
        "current_week": current_week,
        "total_weeks": len(TRIMESTER_WEEKS),
        "is_recess": is_recess,
        "status": status,
        "weeks": [
            {
                "week": week,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "is_recess": recess,
                "label": (
                    "Recess Week"
                    if recess
                    else "Final Assessment" if week == 14 else f"Week {week}"
                ),
            }
            for week, start, end, recess in TRIMESTER_WEEKS
        ],
    }


def build_timeline(ai_result, trimester_context):
    """Build ranking, weekly pressure, overlap, and cluster views.

    Weekly pressure is intentionally transparent: every occurrence contributes
    five density points plus its importance contribution / 10. Collective
    recurring importance is divided across its occurrence weeks. Missing
    importance still contributes density points, so incomplete items stay visible.
    """
    total_weeks = int(trimester_context.get("total_weeks") or 14)
    current_week = trimester_context.get("current_week")
    start_week = _timeline_start_week(trimester_context, total_weeks)
    week_metadata = {
        item["week"]: item for item in trimester_context.get("weeks", [])
    }
    weekly_occurrences = {week: [] for week in range(1, total_weeks + 1)}
    ranking = []
    comments = list(ai_result.get("global_comments", []))
    checklist = list(ai_result.get("user_checklist", []))
    unplaced = []
    past_assessments = []
    module_weight_coverage = []

    for module in ai_result.get("modules", []):
        module_name = str(module.get("module_name") or "Unknown module").strip()
        credits = _valid_number(module.get("credit_units"), minimum=0, maximum=60)
        comments.extend(
            f"{module_name}: {item}" for item in module.get("comments", [])[:2]
        )
        if credits is None:
            checklist.append(
                f"{module_name}: Provide valid credit units so academic importance "
                "can be calculated."
            )

        calculations = []
        for index, assessment in enumerate(module.get("assessments", []), start=1):
            calculation = _calculate_assessment(
                module_name, assessment, index, credits, start_week,
                total_weeks, week_metadata,
            )
            calculations.append(calculation)
            comments.extend(
                f"{calculation['reference']}: {warning}"
                for warning in calculation["warnings"]
            )
            comments.extend(
                f"{calculation['reference']}: {item}" for item in calculation["comments"]
            )
            if calculation["feedback"]:
                checklist.append(f"{calculation['reference']}: {calculation['feedback']}")
            if not calculation["weeks"]:
                unplaced.append(calculation["reference"])

            ranking.append(calculation["ranking"])
            for week in calculation["weeks"]:
                occurrence = calculation["occurrence"].copy()
                weekly_occurrences[week].append(occurrence)
                if week < start_week:
                    past_assessments.append({"week": week, **occurrence})

        coverage, coverage_feedback = _module_coverage(module_name, calculations)
        module_weight_coverage.append(coverage)
        if coverage_feedback:
            checklist.append(coverage_feedback)

    ranking.sort(
        key=lambda item: (
            item["relative_score"] is None,
            -(item["relative_score"] or 0),
            item["due_week"] is None,
            item["due_week"] or total_weeks + 1,
            item["module_name"],
            item["assessment_name"],
        )
    )
    for position, item in enumerate(ranking, start=1):
        item["rank"] = position if item["relative_score"] is not None else None

    timeline = _build_weekly_timeline(
        weekly_occurrences, week_metadata, start_week, total_weeks
    )
    overlaps = [
        {
            "week": item["week"],
            "assessment_count": item["assessment_count"],
            "assessments": [
                f"{assessment['module_name']} {assessment['assessment_name']}"
                for assessment in item["assessments"]
            ],
            "pressure": item["pressure"],
        }
        for item in timeline
        if item["assessment_count"] >= 2
    ]
    peak = max(timeline, key=lambda item: item["pressure_score"], default=None)
    return {
        "trimester_context": {
            key: trimester_context.get(key)
            for key in (
                "academic_year",
                "trimester",
                "current_date",
                "current_week",
                "total_weeks",
                "is_recess",
                "status",
            )
        },
        "current_week": current_week,
        "relative_assessment_ranking": ranking,
        "module_weight_coverage": module_weight_coverage,
        "timeline": timeline,
        "pressure_by_week": [
            {
                "week": item["week"],
                "pressure_score": item["pressure_score"],
                "pressure": item["pressure"],
                "assessment_count": item["assessment_count"],
            }
            for item in timeline
        ],
        "overlaps": overlaps,
        "clusters": _build_clusters(timeline),
        "overall_pacing": {
            "assessment_count": len(ranking),
            "future_occurrence_count": sum(item["assessment_count"] for item in timeline),
            "peak_week": peak["week"] if peak else None,
            "peak_pressure": peak["pressure"] if peak else None,
            "heavy_weeks": [
                item["week"]
                for item in timeline
                if item["pressure"] in {"high", "very_high"}
            ],
            "light_weeks": [
                item["week"]
                for item in timeline
                if item["pressure"] == "low"
            ],
        },
        "past_assessments": past_assessments,
        "unplaced_assessments": list(dict.fromkeys(unplaced)),
        "comments": _limit_feedback(comments),
        "user_checklist": _limit_feedback(checklist),
    }


# Timeline calculation helpers


def _timeline_start_week(trimester_context, total_weeks):
    status = trimester_context.get("status", "in_trimester")
    boundaries = {"before_trimester": 1, "after_trimester": total_weeks + 1}
    return boundaries.get(status, int(trimester_context.get("current_week") or 1))


def _calculate_assessment(
    module_name, assessment, index, credits, start_week, total_weeks, week_metadata
):
    """Validate once and return every derived view for one assessment."""
    name = str(assessment.get("name") or f"Assessment {index}").strip()
    weightage = _valid_number(assessment.get("weightage_percent"), 0, 100)
    weightage_scope = (
        "per_occurrence" if assessment.get("weightage_scope") == "per_occurrence"
        else "total"
    )
    recurring = bool(assessment.get("recurring"))
    importance = (
        round(weightage * credits, 4) if weightage is not None and credits is not None
        else None
    )
    weeks, warnings = _assessment_weeks(assessment, total_weeks, week_metadata)
    collective = recurring and weightage_scope == "total"
    ranking_week = _ranking_week(weeks, start_week, collective)
    weeks_remaining, proximity = _proximity(ranking_week, start_week)
    relative_score = (
        round(importance * proximity, 4) if importance is not None and proximity is not None
        else None
    )
    pressure_importance = (
        round(importance / len(weeks), 4) if collective and weeks and importance is not None
        else importance
    )
    common = {
        "module_name": module_name,
        "assessment_name": name,
        "assessment_type": assessment.get("type") or "assessment",
        "weightage_percent": weightage,
        "weightage_scope": weightage_scope,
    }
    coverage_weight = 0 if weightage is None else weightage
    if recurring and weightage_scope == "per_occurrence" and weightage is not None:
        coverage_weight *= max(len(weeks), 1)
    return {
        "reference": f"{module_name} {name}",
        "weightage": weightage,
        "coverage_weight": coverage_weight,
        "weeks": weeks,
        "warnings": warnings,
        "comments": assessment.get("comments", [])[:1],
        "feedback": _assessment_feedback(assessment, weightage, weeks),
        "ranking": {
            **common,
            "credit_units": credits,
            "academic_importance": importance,
            "due_date": assessment.get("due_date"),
            "due_week": assessment.get("due_week"),
            "occurrence_weeks": weeks,
            "timing_label": _timing_label(weeks, assessment.get("due_week")),
            "weeks_remaining": weeks_remaining,
            "proximity_score": proximity,
            "relative_score": relative_score,
            "confidence": assessment.get("confidence"),
            "recurring": recurring,
        },
        "occurrence": {
            **common,
            "academic_importance": importance,
            "pressure_importance": pressure_importance,
            "recurring": recurring,
        },
    }


def _proximity(ranking_week, start_week):
    if ranking_week is None:
        return None, None
    weeks_remaining = ranking_week - start_week
    proximity = 0 if weeks_remaining < 0 else round(1 / max(weeks_remaining, 1), 4)
    return weeks_remaining, proximity


def _module_coverage(module_name, calculations):
    known_weight = round(sum(item["coverage_weight"] for item in calculations), 2)
    unknown_count = sum(item["weightage"] is None for item in calculations)
    assessment_count = len(calculations)
    complete = assessment_count > 0 and unknown_count == 0 and 99.5 <= known_weight <= 100.5
    coverage = {
        "module_name": module_name,
        "known_weightage_percent": known_weight,
        "unknown_weight_count": unknown_count,
        "assessment_count": assessment_count,
        "complete": complete,
    }
    if not assessment_count or complete:
        return coverage, None
    if unknown_count:
        detail = f"are incomplete ({known_weight:g}% known)"
    else:
        detail = f"total {known_weight:g}%, not 100%"
    return coverage, f"{module_name}: Assessment weights {detail}."


def _build_weekly_timeline(
    weekly_occurrences, week_metadata, start_week, total_weeks
):
    timeline = []
    for week in range(start_week, total_weeks + 1):
        assessments = weekly_occurrences[week]
        importance_total = sum(item["pressure_importance"] or 0 for item in assessments)
        score = round(len(assessments) * 5 + importance_total / 10, 2)
        metadata = week_metadata.get(week, {})
        timeline.append(
            {
                "week": week,
                "label": metadata.get("label", f"Week {week}"),
                "start_date": metadata.get("start_date"),
                "end_date": metadata.get("end_date"),
                "is_recess": bool(metadata.get("is_recess", False)),
                "assessment_count": len(assessments),
                "pressure_score": score,
                "pressure": _pressure_label(score),
                "assessments": assessments,
            }
        )
    return timeline


def _assessment_weeks(assessment, total_weeks, week_metadata):
    warnings = []
    candidates = []
    recurrence = assessment.get("recurrence")
    if assessment.get("recurring") and isinstance(recurrence, dict):
        candidates.extend(recurrence.get("weeks") or [])
        if not candidates:
            interval = recurrence.get("every_n_weeks") or 1
            candidates.extend(
                _week_range(
                    recurrence.get("start_week"),
                    recurrence.get("end_week"),
                    interval,
                )
            )
    if assessment.get("spans_multiple_weeks"):
        candidates.extend(
            _week_range(
                assessment.get("start_week"), assessment.get("end_week")
            )
        )
    if not candidates and assessment.get("due_week") is not None:
        candidates.append(assessment.get("due_week"))
    if not candidates and assessment.get("due_date"):
        due_date = str(assessment["due_date"]).strip()
        matching_week = next(
            (
                week
                for week, metadata in week_metadata.items()
                if metadata.get("start_date")
                and metadata.get("end_date")
                and metadata["start_date"] <= due_date <= metadata["end_date"]
            ),
            None,
        )
        if matching_week is not None:
            candidates.append(matching_week)
        else:
            warnings.append(
                f"Due date {due_date} could not be matched to a trimester week."
            )

    weeks = []
    for value in candidates:
        if isinstance(value, bool):
            warnings.append(f"Invalid due week {value!r} was ignored.")
            continue
        try:
            week = int(value)
        except (TypeError, ValueError):
            warnings.append(f"Invalid due week {value!r} was ignored.")
            continue
        if not 1 <= week <= total_weeks:
            warnings.append(
                f"Week {week} is outside this {total_weeks}-week trimester and "
                "was not placed."
            )
            continue
        weeks.append(week)
    return sorted(set(weeks)), _unique(warnings)


def _week_range(start, end, interval=1):
    if not all(isinstance(value, int) for value in (start, end, interval)) or interval <= 0:
        return ()
    return range(start, end + 1, interval)


def _ranking_week(weeks, start_week, collective_recurring=False):
    if not weeks:
        return None
    upcoming = [week for week in weeks if week >= start_week]
    if not upcoming:
        return max(weeks)
    return max(upcoming) if collective_recurring else min(upcoming)


def _timing_label(weeks, due_week):
    if due_week is not None:
        return f"Week {due_week}"
    if not weeks:
        return "Unknown"
    if len(weeks) == 1:
        return f"Week {weeks[0]}"
    continuous = weeks == list(range(weeks[0], weeks[-1] + 1))
    return (
        f"Weeks {weeks[0]}–{weeks[-1]}"
        if continuous
        else "Weeks " + ", ".join(str(week) for week in weeks)
    )


def _assessment_feedback(assessment, weightage, weeks):
    """Return one compact, material feedback item for an assessment."""
    model_missing = assessment.get("missing_information", [])
    if model_missing and (weightage is None or not weeks):
        return "Assessment details are incomplete."
    if weightage is None:
        return "Assessment weightage is missing."
    if not weeks:
        return "Assessment timing is missing."
    if model_missing:
        return str(model_missing[0]).strip() or "Assessment details are incomplete."
    return None


def _limit_feedback(items, limit=MAX_FINAL_FEEDBACK_ITEMS):
    unique = _unique(items)
    if len(unique) <= limit:
        return unique
    omitted = len(unique) - limit
    return unique[:limit] + [
        f"{omitted} additional assessment detail(s) are incomplete."
    ]


def _pressure_label(score):
    for upper_bound, label in PRESSURE_THRESHOLDS:
        if score < upper_bound:
            return label
    return "very_high"


def _build_clusters(timeline):
    busy = [item for item in timeline if item["assessment_count"]]
    groups = []
    for week in busy:
        if not groups or week["week"] > groups[-1][-1]["week"] + 1:
            groups.append([week])
        else:
            groups[-1].append(week)

    result = []
    for group in groups:
        names = _unique(
            f"{assessment['module_name']} {assessment['assessment_name']}"
            for week in group
            for assessment in week["assessments"]
        )
        occurrence_count = sum(week["assessment_count"] for week in group)
        if occurrence_count < 2:
            continue
        peak = max(group, key=lambda week: week["pressure_score"])
        result.append(
            {
                "start_week": group[0]["week"],
                "end_week": group[-1]["week"],
                "weeks": [week["week"] for week in group],
                "assessment_count": occurrence_count,
                "assessments": names,
                "peak_pressure": peak["pressure"],
            }
        )
    return result


def _valid_number(value, minimum, maximum):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if minimum <= number <= maximum else None


def _unique(items):
    return list(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))


# Legacy one-module pacing API


def build_plan(module, assessments, comments=None):
    """Build schedulable blocks and one concise missing-information list."""
    blocks = []
    checklist = []

    for assessment in assessments:
        issues = list(assessment.get("issues", []))
        if assessment.get("deadline") is None and not any(
            "deadline" in issue.lower() for issue in issues
        ):
            issues.append("The deadline week is missing.")
        if assessment.get("weightage") is None and not any(
            "weight" in issue.lower() for issue in issues
        ):
            issues.append("The assessment weight is missing.")

        if issues:
            checklist.append(
                {"title": assessment["assessment_type"], "items": issues}
            )
            continue

        blocks.append(
            {
                "assessment_type": assessment["assessment_type"],
                "deadline": assessment["deadline"],
                "week_number": int(assessment["deadline"].split()[1]),
                "weightage": assessment["weightage"],
                "priority": _priority(
                    assessment["deadline"], assessment["weightage"]
                ),
            }
        )

    blocks.sort(
        key=lambda block: (
            block["week_number"],
            ("LOW", "MEDIUM", "HIGH").index(block["priority"]),
            block["weightage"],
        )
    )
    final_week = max((block["week_number"] for block in blocks), default=0)
    weeks = [
        {
            "week_number": week,
            "label": f"Week {week}",
            "blocks": [block for block in blocks if block["week_number"] == week],
        }
        for week in range(1, final_week + 1)
    ]
    known_weights = [
        assessment["weightage"]
        for assessment in assessments
        if assessment.get("weightage") is not None
    ]
    total_weight = sum(known_weights)
    if known_weights and not 99.5 <= total_weight <= 100.5:
        checklist.append(
            {
                "title": "Module coverage",
                "items": [
                    f"Visible assessment weights total {total_weight:g}%, not 100%. "
                    "Add the missing assessment information."
                ],
            }
        )
    if comments and not checklist:
        checklist.append({"title": "Evidence summary", "items": list(comments)})

    return {
        "module": module,
        "checklist": checklist,
        "schedule": {"weeks": weeks, "blocks": blocks},
    }


def _priority(deadline, weightage):
    """Prioritise earlier and heavier assessments."""
    week = int(deadline.split()[1])
    score = (3 if week <= 3 else 2 if week <= 7 else 1) + (
        3 if weightage >= 40 else 2 if weightage >= 20 else 1
    )
    return "HIGH" if score >= 5 else "MEDIUM" if score >= 3 else "LOW"
