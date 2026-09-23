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
    )

    assert record["status"] == "NEEDS_REVIEW"
    assert record["priority"] is None
    assert "unexpected" not in record
    assert contracts.validate_record_contract(record) == []
