from datetime import date

from src import contracts, logic_manager


def test_logic_manager_owns_status_priority_and_final_shape():
    ai_record = {
        "module": "INF1103",
        "assessment_type": "Project",
        "deadline": "2026-10-15",
        "weightage": 30,
        "priority": "HIGH",
        "status": "READY",
        "missing_fields": [],
        "issues": [],
        "unexpected": "must not cross the manager boundary",
    }

    record = logic_manager.apply_business_rules(
        ai_record,
        record_id="record-001",
        revision=1,
        today=date(2026, 10, 10),
    )

    assert record["status"] == "READY"
    assert record["priority"] == "HIGH"
    assert "unexpected" not in record
    assert contracts.validate_record_contract(record) == []


def test_priority_uses_deadline_and_weightage_conditions():
    assert logic_manager.calculate_priority(
        "2026-10-30", 10, today=date(2026, 10, 1)
    ) == "LOW"
    assert logic_manager.calculate_priority(
        "2026-10-12", 20, today=date(2026, 10, 1)
    ) == "MEDIUM"
    assert logic_manager.calculate_priority(
        "2026-10-12", 50, today=date(2026, 10, 1)
    ) == "HIGH"


def test_error_issue_blocks_ready_status():
    ai_record = {
        "module": "INF1103",
        "assessment_type": "Project",
        "deadline": "2026-10-15",
        "weightage": 30,
        "missing_fields": [],
        "issues": [
            {
                "type": "UNRESOLVED_DETAIL",
                "field": "deadline",
                "severity": "error",
                "feedback": "The supplied evidence cannot be accepted.",
            }
        ],
    }

    record = logic_manager.apply_business_rules(
        ai_record,
        record_id="record-002",
        revision=1,
        today=date(2026, 10, 10),
    )

    assert record["status"] == "NEEDS_REVIEW"
    assert record["priority"] is None


def test_source_conflict_takes_precedence_over_missing_field():
    ai_record = {
        "module": "INF1103",
        "assessment_type": "Project",
        "deadline": None,
        "weightage": 30,
        "missing_fields": ["deadline"],
        "issues": [
            {
                "type": "SOURCE_CONFLICT",
                "field": "deadline",
                "severity": "error",
                "feedback": "Two supplied sources give different deadlines.",
            }
        ],
    }

    record = logic_manager.apply_business_rules(
        ai_record,
        record_id="record-conflict",
        revision=1,
        today=date(2026, 10, 1),
    )

    assert record["status"] == "CONFLICT"
    assert record["priority"] is None


def test_schedule_builds_multiple_blocks_and_excludes_incomplete_record():
    records = [
        {
            "record_id": "record-high",
            "module": "INF1103",
            "assessment_type": "Project",
            "deadline": "2026-10-10",
            "weightage": 50,
            "priority": "HIGH",
            "status": "READY",
            "missing_fields": [],
            "issues": [],
            "revision": 2,
        },
        {
            "record_id": "record-medium",
            "module": "INF1104",
            "assessment_type": "Quiz",
            "deadline": "2026-10-10",
            "weightage": 20,
            "priority": "MEDIUM",
            "status": "READY",
            "missing_fields": [],
            "issues": [],
            "revision": 1,
        },
        {
            "record_id": "record-incomplete",
            "module": "UCS1001",
            "assessment_type": "Essay",
            "deadline": None,
            "weightage": 30,
            "priority": None,
            "status": "INCOMPLETE",
            "missing_fields": ["deadline"],
            "issues": [],
            "revision": 1,
        },
    ]

    schedule = logic_manager.build_schedule(records, today=date(2026, 10, 1))

    assert [block["record_id"] for block in schedule["blocks"]] == [
        "record-high",
        "record-medium",
    ]
    assert schedule["blocks"][0]["block_size_days"] == 5
    assert schedule["blocks"][0]["revision"] == 2
    assert schedule["excluded_records"][0]["record_id"] == "record-incomplete"
    assert any("overlap" in warning for warning in schedule["warnings"])


def test_assessment_due_today_is_constrained():
    record = logic_manager.apply_business_rules(
        {
            "module": "INF1103",
            "assessment_type": "Project",
            "deadline": "2026-10-01",
            "weightage": 30,
            "missing_fields": [],
            "issues": [],
        },
        record_id="due-today",
        revision=1,
        today=date(2026, 10, 1),
    )

    assert record["status"] == "CONSTRAINED"
    assert record["priority"] is None
