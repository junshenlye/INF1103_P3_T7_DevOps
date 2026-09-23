import base64
import json
from types import SimpleNamespace

from src import ai_manager


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUB"
    "AScY42YAAAAASUVORK5CYII="
)


def valid_extraction():
    return {
        "module": "INF1103",
        "assessment_type": "Project",
        "deadline": "2026-10-15",
        "weightage": 30,
        "missing_fields": [],
        "issues": [],
    }


def test_process_record_accepts_valid_injected_ai_response(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", ai_manager.DEFAULT_MODEL)
    calls = []

    def fake_caller(**kwargs):
        calls.append(kwargs)
        return json.dumps(valid_extraction())

    result = ai_manager.process_record(
        {
            "module": "INF1103",
            "assessment_type": "Project",
            "deadline": "2026-10-15",
            "weightage": 30,
            "prompt": "Confirm the supplied assessment details.",
            "image_paths": [],
        },
        api_caller=fake_caller,
    )

    assert result == {
        "ok": True,
        "extraction": valid_extraction(),
        "errors": [],
        "attempts": 1,
    }
    assert len(calls) == 1
    assert calls[0]["model"] == ai_manager.DEFAULT_MODEL
    assert calls[0]["api_key"] == ""
    assert "image_paths" not in calls[0]["prompt"]
    assert "Treat each non-null structured input field" in calls[0]["prompt"]


def test_missing_key_fails_without_calling_transport(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    result = ai_manager.process_record({"module": "INF1103"})

    assert result["ok"] is False
    assert result["errors"] == ["OPENROUTER_API_KEY is not configured."]
    assert result["attempts"] == 0


def test_fenced_json_is_parsed_but_extra_fields_are_rejected():
    fenced = f"```json\n{json.dumps(valid_extraction())}\n```"
    assert ai_manager.parse_model_response(fenced) == valid_extraction()

    extraction = valid_extraction()
    extraction["status"] = "READY"
    errors = ai_manager.validate_extraction(extraction)
    assert "Unexpected AI fields: status." in errors


def test_missing_fields_must_match_null_values():
    extraction = valid_extraction()
    extraction["deadline"] = None

    errors = ai_manager.validate_extraction(extraction)

    assert "missing_fields must exactly match null extracted values." in errors


def test_multimodal_request_places_text_before_base64_image(tmp_path, monkeypatch):
    image_path = tmp_path / "assessment.png"
    image_path.write_bytes(ONE_PIXEL_PNG)
    captured = {}
    model_response = json.dumps(valid_extraction())

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
            {"choices": [{"message": {"content": model_response}}]}
        ).encode("utf-8"),
    )
    connection.close = lambda: None

    def fake_connection(host, timeout, context):
        captured.update(
            {
                "host": host,
                "timeout": timeout,
                "has_tls_context": context is not None,
            }
        )
        return connection

    monkeypatch.setattr(ai_manager.http.client, "HTTPSConnection", fake_connection)
    response_text = ai_manager.call_openrouter(
        prompt="Extract this assessment.",
        image_paths=[str(image_path)],
        api_key="unit-test-key-not-real",
        model=ai_manager.DEFAULT_MODEL,
        base_url=ai_manager.DEFAULT_BASE_URL,
    )

    content = captured["payload"]["messages"][1]["content"]
    assert json.loads(response_text) == valid_extraction()
    assert captured["host"] == "openrouter.ai"
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/chat/completions"
    assert captured["has_tls_context"] is True
    assert content[0] == {"type": "text", "text": "Extract this assessment."}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert captured["headers"]["Authorization"] == "Bearer unit-test-key-not-real"
    assert "response_format" not in captured["payload"]


def test_transport_error_does_not_leak_sensitive_exception_text(caplog):
    def failing_caller(**kwargs):
        raise ValueError("unit-test-key-not-real")

    result = ai_manager.process_record(
        {"module": "INF1103"},
        api_caller=failing_caller,
    )

    assert result["ok"] is False
    assert result["errors"] == ["AI response could not be processed."]
    assert "unit-test-key-not-real" not in caplog.text
    assert "unit-test-key-not-real" not in json.dumps(result)
