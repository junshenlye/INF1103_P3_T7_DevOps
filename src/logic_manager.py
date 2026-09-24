"""Convert extracted assessments into a single-module weekly plan."""


def build_plan(module, assessments):
    """Add deterministic status and priority, then build week columns."""
    records = []
    for assessment in assessments:
        ready = (
            assessment.get("deadline") is not None
            and assessment.get("weightage") is not None
        )
        records.append(
            {
                "module": module,
                "assessment_type": assessment["assessment_type"],
                "deadline": assessment.get("deadline"),
                "weightage": assessment.get("weightage"),
                "priority": (
                    _priority(assessment["deadline"], assessment["weightage"])
                    if ready
                    else None
                ),
                "status": "READY" if ready else "REVIEW",
                "issues": list(assessment.get("issues", [])),
            }
        )

    blocks = [
        {
            "assessment_type": record["assessment_type"],
            "deadline": record["deadline"],
            "week_number": int(record["deadline"].split()[1]),
            "priority": record["priority"],
            "weightage": record["weightage"],
        }
        for record in records
        if record["status"] == "READY"
    ]
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
    review_count = sum(record["status"] == "REVIEW" for record in records)
    return {
        "module": module,
        "assessments": records,
        "schedule": {
            "weeks": weeks,
            "blocks": blocks,
            "warnings": (
                [f"{review_count} assessment(s) need review before scheduling."]
                if review_count
                else []
            ),
        },
    }


def _priority(deadline, weightage):
    """Prioritise earlier and heavier assessments."""
    week = int(deadline.split()[1])
    score = (3 if week <= 3 else 2 if week <= 7 else 1) + (
        3 if weightage >= 40 else 2 if weightage >= 20 else 1
    )
    return "HIGH" if score >= 5 else "MEDIUM" if score >= 3 else "LOW"
