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


def test_module_credits_are_saved_and_affect_derived_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "load_dotenv", lambda *args, **kwargs: False)
    data_file = tmp_path / "schedules.json"
    module_file = tmp_path / "modules.json"

    result = main.process_assessment(
        {
            "module": "INF1103",
            "module_credits": 12,
            "assessment_type": "Project",
            "deadline": "2026-10-12",
            "weightage": 30,
            "prompt": "Use the supplied assessment details.",
            "image_paths": [],
        },
        data_file=str(data_file),
        module_file=str(module_file),
        api_caller=lambda **kwargs: json.dumps(
            {
                "module": "INF1103",
                "assessment_type": "Project",
                "deadline": "2026-10-12",
                "weightage": 30,
                "missing_fields": [],
                "issues": [],
            }
        ),
        today=date(2026, 10, 1),
        record_id="credit-heavy",
    )

    assert result["record"]["priority"] == "MEDIUM"
    assert result["schedule"]["blocks"][0]["priority"] == "HIGH"
    assert data_manager.load_module_profiles(str(module_file)) == {
        "INF1103": {"credits": 12.0}
    }


def test_module_evidence_extracts_and_persists_multiple_events(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("AI_MAX_RETRIES", "1")
    data_file = tmp_path / "schedules.json"
    module_file = tmp_path / "modules.json"
    missing_issue = {
        "type": "MISSING_DETAIL",
        "field": "deadline",
        "severity": "warning",
        "feedback": "Only a teaching week was visible.",
    }
    assessments = [
        {
            "module": "INF1103",
            "assessment_type": "Quiz 1",
            "deadline": "2026-10-10",
            "weightage": 10,
            "missing_fields": [],
            "issues": [],
        },
        {
            "module": "INF1103",
            "assessment_type": "Assignment 1",
            "deadline": "2026-10-18",
            "weightage": 30,
            "missing_fields": [],
            "issues": [],
        },
        {
            "module": "INF1103",
            "assessment_type": "Project checkpoint",
            "deadline": None,
            "weightage": 20,
            "missing_fields": ["deadline"],
            "issues": [missing_issue],
        },
    ]
    calls = []

    def fake_caller(**kwargs):
        calls.append(kwargs)
        return json.dumps({"assessments": assessments})

    result = main.process_assessment_source(
        {
            "module": "inf1103",
            "module_credits": 12,
            "prompt": "Extract every assessment in this module.",
            "image_paths": [],
        },
        data_file=str(data_file),
        module_file=str(module_file),
        api_caller=fake_caller,
        today=date(2026, 10, 1),
    )

    assert result["ok"] is True
    assert result["extracted_count"] == 3
    assert result["source_module"] == "INF1103"
    assert len(calls) == 1
    assert len({record["record_id"] for record in result["records"]}) == 3
    assert len(data_manager.load_records(str(data_file))) == 3
    assert len(result["schedule"]["blocks"]) == 2
    assert len(result["schedule"]["excluded_records"]) == 1
    assert data_manager.load_module_profiles(str(module_file)) == {
        "INF1103": {"credits": 12.0}
    }


def test_human_correction_appends_revision_without_ai(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "load_dotenv", lambda *args, **kwargs: False)
    data_file = tmp_path / "schedules.json"
    missing_record = {
        "record_id": "record-001",
        "module": "INF1103",
        "assessment_type": "Quiz 1",
        "deadline": None,
        "weightage": 10,
        "priority": None,
        "status": "INCOMPLETE",
        "missing_fields": ["deadline"],
        "issues": [
            {
                "type": "MISSING_DETAIL",
                "field": "deadline",
                "severity": "warning",
                "feedback": "No exact deadline was visible.",
            }
        ],
        "revision": 1,
    }
    assert data_manager.save_records([missing_record], str(data_file)) is True

    result = main.correct_assessment(
        "record-001",
        {
            "assessment_type": "Quiz 1",
            "deadline": "2026-10-20",
            "weightage": 10,
        },
        data_file=str(data_file),
        module_file=str(tmp_path / "modules.json"),
        today=date(2026, 10, 1),
    )

    assert result["ok"] is True
    assert result["record"]["revision"] == 2
    assert result["record"]["status"] == "READY"
    assert result["record"]["issues"] == []
    assert [
        record["revision"]
        for record in data_manager.load_records(str(data_file))
    ] == [1, 2]


def test_failed_source_keeps_module_context_without_partial_records(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(main, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("AI_MAX_RETRIES", "1")
    data_file = tmp_path / "schedules.json"
    module_file = tmp_path / "modules.json"

    result = main.process_assessment_source(
        {
            "module": "INF1104",
            "module_credits": 6,
            "prompt": "Extract every visible assessment.",
            "image_paths": [],
        },
        data_file=str(data_file),
        module_file=str(module_file),
        api_caller=lambda **kwargs: "not-json",
    )

    assert result["ok"] is False
    assert result["source_module"] == "INF1104"
    assert result["records"] == []
    assert data_file.exists() is False
    assert data_manager.load_module_profiles(str(module_file)) == {
        "INF1104": {"credits": 6.0}
    }
