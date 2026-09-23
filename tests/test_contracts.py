from src import contracts


def build_valid_record():
    return {
        "record_id": "record-001",
        "module": "INF1103",
        "assessment_type": "Project",
        "deadline": "2026-10-15",
        "weightage": 30,
        "priority": "HIGH",
        "status": "READY",
        "missing_fields": [],
        "issues": [],
        "revision": 1,
    }


def test_valid_record_matches_frozen_contract():
    assert contracts.validate_record_contract(build_valid_record()) == []


def test_contract_rejects_missing_and_extra_fields():
    record = build_valid_record()
    record.pop("deadline")
    record["unexpected"] = True

    errors = contracts.validate_record_contract(record)

    assert any("Missing contract fields: deadline" in error for error in errors)
    assert any("Unexpected contract fields: unexpected" in error for error in errors)


def test_contract_rejects_invalid_nested_issue():
    record = build_valid_record()
    record["issues"] = [
        {
            "type": "MISSING_DETAIL",
            "field": "deadline",
            "severity": "urgent",
            "feedback": "No deadline was supplied.",
        }
    ]

    errors = contracts.validate_record_contract(record)

    assert "issues[0].severity is not an allowed value." in errors


def test_contract_requires_exact_deadline_format():
    record = build_valid_record()
    record["deadline"] = "20261015"

    errors = contracts.validate_record_contract(record)

    assert "deadline must use YYYY-MM-DD format." in errors
