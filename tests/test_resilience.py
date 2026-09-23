import json
from datetime import date

from src import data_manager, main


def extraction(
    module,
    assessment_type,
    deadline,
    weightage,
    issues=None,
):
    missing_fields = [
        field
        for field, value in (("deadline", deadline), ("weightage", weightage))
        if value is None
    ]
    return {
        "module": module,
        "assessment_type": assessment_type,
        "deadline": deadline,
        "weightage": weightage,
        "missing_fields": missing_fields,
        "issues": issues or [],
    }


def assessment_input(module, assessment_type, deadline, weightage):
    return {
        "module": module,
        "assessment_type": assessment_type,
        "deadline": deadline,
        "weightage": weightage,
        "prompt": "Process this assessment.",
        "image_paths": [],
    }


def test_missing_weightage_is_saved_with_feedback(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("AI_MAX_RETRIES", "1")
    data_file = tmp_path / "schedules.json"
    issue = {
        "type": "MISSING_DETAIL",
        "field": "weightage",
        "severity": "warning",
        "feedback": "No assessment weightage was supplied.",
    }

    result = main.process_assessment(
        assessment_input("INF1104", "Quiz", "2026-10-20", None),
        data_file=str(data_file),
        api_caller=lambda **kwargs: json.dumps(
            extraction("INF1104", "Quiz", "2026-10-20", None, [issue])
        ),
        today=date(2026, 10, 1),
        record_id="missing-weightage",
    )

    assert result["ok"] is True
    assert result["record"]["status"] == "INCOMPLETE"
    assert result["record"]["issues"] == [issue]
    assert data_manager.load_records(str(data_file)) == [result["record"]]


def test_conflicting_sources_are_saved_without_silent_choice(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("AI_MAX_RETRIES", "1")
    data_file = tmp_path / "schedules.json"
    conflict_issue = {
        "type": "SOURCE_CONFLICT",
        "field": "deadline",
        "severity": "error",
        "feedback": "The prompt and image contain different deadlines.",
    }

    result = main.process_assessment(
        assessment_input("INF1103", "Project", None, 30),
        data_file=str(data_file),
        api_caller=lambda **kwargs: json.dumps(
            extraction("INF1103", "Project", None, 30, [conflict_issue])
        ),
        today=date(2026, 10, 1),
        record_id="conflicting-deadline",
    )

    assert result["record"]["status"] == "CONFLICT"
    assert result["record"]["deadline"] is None
    assert result["record"]["priority"] is None
    assert result["schedule"]["blocks"] == []


def test_malformed_ai_exhaustion_preserves_recoverable_input(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("AI_MAX_RETRIES", "2")
    data_file = tmp_path / "schedules.json"
    calls = []

    def malformed_caller(**kwargs):
        calls.append(kwargs)
        return "not-json"

    result = main.process_assessment(
        assessment_input("INF1103", "Project", "2026-10-15", 30),
        data_file=str(data_file),
        api_caller=malformed_caller,
        today=date(2026, 10, 1),
        record_id="recoverable-record",
    )

    assert result["ok"] is False
    assert result["preserved"] is True
    assert result["ai_attempts"] == 2
    assert len(calls) == 2
    assert result["record"]["status"] == "NEEDS_REVIEW"
    assert result["record"]["issues"][0]["type"] == "AI_PROCESSING_FAILURE"
    assert data_manager.load_records(str(data_file)) == [result["record"]]


def test_partial_batch_schedules_three_and_preserves_one_incomplete(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(main, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("AI_MAX_RETRIES", "1")
    data_file = tmp_path / "schedules.json"
    missing_deadline_issue = {
        "type": "MISSING_DETAIL",
        "field": "deadline",
        "severity": "warning",
        "feedback": "The source provides only a teaching week.",
    }
    responses = [
        extraction("INF1102", "Project", "2026-10-10", 50),
        extraction("INF1103", "Quiz", "2026-10-15", 20),
        extraction("INF1104", "Exam", "2026-10-30", 50),
        extraction(
            "UCS1001",
            "Essay",
            None,
            30,
            [missing_deadline_issue],
        ),
    ]

    def ordered_caller(**kwargs):
        return json.dumps(responses.pop(0))

    result = main.process_batch(
        [
            assessment_input("INF1102", "Project", "2026-10-10", 50),
            assessment_input("INF1103", "Quiz", "2026-10-15", 20),
            assessment_input("INF1104", "Exam", "2026-10-30", 50),
            assessment_input("UCS1001", "Essay", None, 30),
        ],
        data_file=str(data_file),
        api_caller=ordered_caller,
        today=date(2026, 10, 1),
    )

    assert result["ok"] is True
    assert result["saved_count"] == 4
    assert len(data_manager.load_records(str(data_file))) == 4
    assert len(result["schedule"]["blocks"]) == 3
    assert len(result["schedule"]["excluded_records"]) == 1
    assert any("excluded" in warning for warning in result["schedule"]["warnings"])


def test_revisit_appends_revision_and_only_latest_is_scheduled(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("AI_MAX_RETRIES", "1")
    data_file = tmp_path / "schedules.json"
    missing_issue = {
        "type": "MISSING_DETAIL",
        "field": "deadline",
        "severity": "warning",
        "feedback": "No exact deadline was supplied.",
    }
    first_result = main.process_assessment(
        assessment_input("INF1103", "Project", None, 30),
        data_file=str(data_file),
        api_caller=lambda **kwargs: json.dumps(
            extraction("INF1103", "Project", None, 30, [missing_issue])
        ),
        today=date(2026, 10, 1),
        record_id="revisited-record",
    )

    second_result = main.reprocess_assessment(
        "revisited-record",
        {"deadline": "2026-10-15", "prompt": "The exact date is now known."},
        data_file=str(data_file),
        api_caller=lambda **kwargs: json.dumps(
            extraction("INF1103", "Project", "2026-10-15", 30)
        ),
        today=date(2026, 10, 1),
    )

    history = data_manager.get_record_history(
        data_manager.load_records(str(data_file)),
        "revisited-record",
    )
    assert first_result["record"]["status"] == "INCOMPLETE"
    assert second_result["record"]["status"] == "READY"
    assert [record["revision"] for record in history] == [1, 2]
    assert len(second_result["schedule"]["blocks"]) == 1
    assert second_result["schedule"]["blocks"][0]["revision"] == 2


def test_invalid_batch_item_does_not_block_valid_item(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("AI_MAX_RETRIES", "1")
    data_file = tmp_path / "schedules.json"

    result = main.process_batch(
        [
            "not-an-object",
            assessment_input("INF1103", "Project", "2026-10-15", 30),
        ],
        data_file=str(data_file),
        api_caller=lambda **kwargs: json.dumps(
            extraction("INF1103", "Project", "2026-10-15", 30)
        ),
        today=date(2026, 10, 1),
    )

    assert result["ok"] is False
    assert result["saved_count"] == 1
    assert result["results"][0]["record"] is None
    assert len(result["schedule"]["blocks"]) == 1


def test_empty_batch_is_rejected_without_writing(tmp_path):
    data_file = tmp_path / "schedules.json"

    result = main.process_batch([], data_file=str(data_file))

    assert result["ok"] is False
    assert result["errors"] == ["Batch input must be a non-empty list."]
    assert result["saved_count"] == 0
    assert data_file.exists() is False
