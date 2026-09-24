from io import BytesIO
import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_PATH = PROJECT_ROOT / "frontend-demo" / "app.py"


def load_frontend_module():
    spec = importlib.util.spec_from_file_location("frontend_demo_app", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dashboard_summary():
    return {
        "records": [],
        "latest_records": [],
        "records_loaded": 0,
        "data_file": "/tmp/schedules.json",
        "module_profiles": {"INF1103": {"credits": 6.0}},
        "module_file": "/tmp/modules.json",
        "schedule": {
            "blocks": [],
            "weeks": [],
            "excluded_records": [],
            "warnings": [],
        },
    }


def test_frontend_get_renders_drag_drop_and_schedule_shell(monkeypatch):
    frontend = load_frontend_module()
    monkeypatch.setattr(
        frontend.core_main,
        "start_application",
        lambda: dashboard_summary(),
    )
    client = frontend.app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert b"Drop all snapshots for this module" in response.data
    assert b"Extract every assessment" in response.data
    assert b"Weekly preparation blocks" in response.data
    assert b"INF1103" in response.data
    assert b'name="assessment_type"' not in response.data


def test_frontend_post_adapts_upload_prompt_and_credits_to_core(monkeypatch):
    frontend = load_frontend_module()
    captured = {}

    def fake_process_source(input_record):
        captured.update(input_record)
        captured["upload_exists_during_call"] = Path(
            input_record["image_paths"][0]
        ).is_file()
        return {
            "ok": True,
            "records": [],
            "extracted_count": 3,
            "source_module": "INF1103",
            "errors": [],
            "ai_attempts": 1,
            "preserved": False,
        }

    monkeypatch.setattr(
        frontend.core_main,
        "process_assessment_source",
        fake_process_source,
    )
    monkeypatch.setattr(
        frontend.core_main,
        "start_application",
        lambda: dashboard_summary(),
    )
    client = frontend.app.test_client()

    response = client.post(
        "/process",
        data={
            "module": "INF1103",
            "module_credits": "12",
            "prompt": "Use this screenshot as supporting evidence.",
            "source_files": (BytesIO(b"image-bytes"), "assessment.png"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert captured["module_credits"] == 12.0
    assert captured["prompt"] == "Use this screenshot as supporting evidence."
    assert "assessment_type" not in captured
    assert "deadline" not in captured
    assert "weightage" not in captured
    assert captured["upload_exists_during_call"] is True
    assert Path(captured["image_paths"][0]).exists() is False
    assert b"3 assessments extracted" in response.data


def test_frontend_review_routes_corrections_without_ai(monkeypatch):
    frontend = load_frontend_module()
    captured = {}

    def fake_correct_assessment(record_id, updates):
        captured["record_id"] = record_id
        captured["updates"] = updates
        return {
            "ok": True,
            "record": {
                "module": "INF1103",
                "assessment_type": "Quiz 1",
                "status": "READY",
            },
            "errors": [],
            "preserved": False,
        }

    monkeypatch.setattr(
        frontend.core_main,
        "correct_assessment",
        fake_correct_assessment,
    )
    monkeypatch.setattr(
        frontend.core_main,
        "start_application",
        lambda: dashboard_summary(),
    )
    client = frontend.app.test_client()

    response = client.post(
        "/review/record-001",
        data={
            "assessment_type": "Quiz 1",
            "deadline": "2026-10-20",
            "weightage": "15",
        },
    )

    assert response.status_code == 200
    assert captured == {
        "record_id": "record-001",
        "updates": {
            "assessment_type": "Quiz 1",
            "deadline": "2026-10-20",
            "weightage": 15.0,
        },
    }


def test_schedule_api_returns_procedural_core_state(monkeypatch):
    frontend = load_frontend_module()
    monkeypatch.setattr(
        frontend.core_main,
        "start_application",
        lambda: dashboard_summary(),
    )
    client = frontend.app.test_client()

    response = client.get("/api/schedule")

    assert response.status_code == 200
    assert response.get_json()["module_profiles"]["INF1103"]["credits"] == 6.0
