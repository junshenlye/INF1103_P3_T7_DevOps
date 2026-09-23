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
