from src import io_manager


def test_format_record_includes_ai_feedback():
    record = {
        "record_id": "record-001",
        "module": "UCS1001",
        "assessment_type": "Reader Response Essay",
        "deadline": "2026-10-15",
        "weightage": 30,
        "priority": "MEDIUM",
        "status": "READY",
        "missing_fields": [],
        "issues": [
            {
                "type": "SOURCE_NOTE",
                "field": "deadline",
                "severity": "warning",
                "feedback": "The exact date came from the supplied prompt.",
            }
        ],
        "revision": 1,
    }

    output = io_manager.format_record(record)

    assert "Status: READY" in output
    assert "Feedback:" in output
    assert "[warning] The exact date came from the supplied prompt." in output
