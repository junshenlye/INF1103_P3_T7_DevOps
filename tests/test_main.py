import json

from src import main


def test_start_application_loads_existing_records(tmp_path):
    data_file = tmp_path / "schedules.json"
    record = {
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
    data_file.write_text(json.dumps([record]), encoding="utf-8")

    summary = main.start_application(str(data_file))

    assert summary["records_loaded"] == 1
    assert summary["records"] == [record]
    assert summary["data_file"] == str(data_file)
