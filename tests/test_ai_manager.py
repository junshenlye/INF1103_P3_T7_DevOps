import base64
import json
from types import SimpleNamespace

from src import ai_manager


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUB"
    "AScY42YAAAAASUVORK5CYII="
)


def valid_extraction(assessment_type="Project", deadline="2026-10-15", weightage=30):
    return {
        "module": "INF1103",
        "assessment_type": assessment_type,
        "deadline": deadline,
        "weightage": weightage,
        "missing_fields": [],
        "issues": [],
    }


def test_multimodal_request_places_text_before_image(tmp_path, monkeypatch):
    image_path = tmp_path / "assessment.png"
    image_path.write_bytes(ONE_PIXEL_PNG)
    captured = {}
    connection = SimpleNamespace()

    def fake_request(method, path, body, headers):
        captured.update(
            {
                "method": method,
                "path": path,
                "headers": headers,
                "payload": json.loads(body.decode("utf-8")),
            }
        )

    connection.request = fake_request
    connection.getresponse = lambda: SimpleNamespace(
        status=200,
        read=lambda: json.dumps(
            {"choices": [{"message": {"content": json.dumps(valid_extraction())}}]}
        ).encode("utf-8"),
    )
    connection.close = lambda: None
    monkeypatch.setattr(
        ai_manager.http.client,
        "HTTPSConnection",
        lambda *args, **kwargs: connection,
    )

    ai_manager.call_openrouter(
        prompt="Extract assessments.",
        image_paths=[str(image_path)],
        api_key="unit-test-key-not-real",
        model=ai_manager.DEFAULT_MODEL,
        base_url=ai_manager.DEFAULT_BASE_URL,
    )

    content = captured["payload"]["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "Extract assessments."}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert captured["headers"]["Authorization"] == "Bearer unit-test-key-not-real"


def test_source_prompt_requests_all_events_and_trusts_module_context():
    prompt = ai_manager.build_source_prompt(
        {
            "module": "inf1103",
            "module_credits": 12,
            "prompt": "The images are from Trimester 2.",
            "image_paths": ["one.png", "two.png"],
        }
    )

    assert "every distinct graded assessment event" in prompt
    assert "Every event must use exactly INF1103" in prompt
    assert '"attached_image_count": 2' in prompt
    assert "module_credits" not in prompt


def test_process_source_accepts_multiple_events_and_reports_progress(monkeypatch):
    monkeypatch.setenv("AI_MAX_RETRIES", "1")
    assessments = [
        valid_extraction("Quiz 1", "2026-10-15", 10),
        valid_extraction("Assignment 1", "2026-10-22", 25),
    ]
    progress = []

    result = ai_manager.process_source(
        {
            "module": "INF1103",
            "module_credits": 6,
            "prompt": "Extract the whole module schedule.",
            "image_paths": [],
        },
        api_caller=lambda **kwargs: json.dumps({"assessments": assessments}),
        progress_callback=progress.append,
    )

    assert result["extractions"] == assessments
    assert [event["stage"] for event in progress] == [
        "ai_request",
        "ai_validation",
        "ai_complete",
    ]


def test_source_normalization_preserves_missing_events_for_review():
    normalized = ai_manager.normalize_source_response(
        {
            "assessments": [
                {
                    "module": "wrong-module",
                    "assessment_type": "Quiz 1",
                    "deadline": None,
                    "weightage": None,
                    "missing_fields": [],
                    "issues": [],
                }
            ]
        },
        "INF1103",
    )

    event = normalized["assessments"][0]
    assert event["module"] == "INF1103"
    assert event["missing_fields"] == ["deadline", "weightage"]
    assert {issue["field"] for issue in event["issues"]} == {
        "deadline",
        "weightage",
    }
    assert ai_manager.validate_source_extraction(normalized, "INF1103") == []


def test_source_schema_rejects_duplicate_event():
    event = valid_extraction()

    errors = ai_manager.validate_source_extraction(
        {"assessments": [event, dict(event)]},
        "INF1103",
    )

    assert "assessments[1]: duplicate assessment event." in errors


def test_malformed_source_retries_with_visible_safe_error(monkeypatch):
    monkeypatch.setenv("AI_MAX_RETRIES", "2")
    progress = []
    responses = ["not-json", json.dumps({"assessments": [valid_extraction()]})]

    result = ai_manager.process_source(
        {
            "module": "INF1103",
            "module_credits": 6,
            "prompt": "Extract all events.",
            "image_paths": [],
        },
        api_caller=lambda **kwargs: responses.pop(0),
        progress_callback=progress.append,
    )

    assert result["ok"] is True
    assert result["attempts"] == 2
    assert any(event["stage"] == "retrying" for event in progress)
    assert all("unit-test-key" not in event["message"] for event in progress)
