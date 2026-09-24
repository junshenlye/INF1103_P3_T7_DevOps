"""Convert extracted assessments into a single-module weekly plan."""


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
