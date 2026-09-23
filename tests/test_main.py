import json
from datetime import date

from src import data_manager, main


def test_start_application_loads_existing_records(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "load_dotenv", lambda *args, **kwargs: False)
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


def test_happy_path_processes_and_persists_one_record(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "load_dotenv", lambda *args, **kwargs: False)
    data_file = tmp_path / "schedules.json"

    def fake_caller(**kwargs):
        return json.dumps(
            {
                "module": "INF1103",
                "assessment_type": "Project",
                "deadline": "2026-10-15",
                "weightage": 30,
                "missing_fields": [],
                "issues": [],
            }
        )

    result = main.process_assessment(
        {
            "module": "INF1103",
            "assessment_type": "Project",
            "deadline": "2026-10-15",
            "weightage": 30,
            "prompt": "Confirm the supplied details.",
            "image_paths": [],
        },
        data_file=str(data_file),
        api_caller=fake_caller,
        today=date(2026, 10, 10),
        record_id="record-001",
    )

    assert result["ok"] is True
    assert result["record"]["status"] == "READY"
    assert result["record"]["priority"] == "HIGH"
    assert result["ai_attempts"] == 1
    assert data_manager.load_records(str(data_file)) == [result["record"]]


def test_cli_routes_batch_file_to_multi_record_pipeline(tmp_path, monkeypatch, capsys):
    batch_file = tmp_path / "batch.json"
    batch_file.write_text(
        json.dumps(
            [
                {
                    "module": "INF1103",
                    "assessment_type": "Project",
                    "deadline": "2026-10-15",
                    "weightage": 30,
                }
            ]
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_process_batch(records, data_file=None):
        calls.append((records, data_file))
        return {
            "ok": True,
            "results": [],
            "saved_count": 0,
            "schedule": {"blocks": [], "excluded_records": [], "warnings": []},
        }

    monkeypatch.setattr(main, "process_batch", fake_process_batch)

    exit_code = main.main(
        ["--batch-file", str(batch_file), "--data-file", str(tmp_path / "data.json")]
    )

    assert exit_code == 0
    assert calls[0][0][0]["module"] == "INF1103"
    assert "Processed 0 assessment record(s)." in capsys.readouterr().out
