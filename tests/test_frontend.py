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
    assert b"Drop module screenshots here" in response.data
    assert b"Weekly preparation blocks" in response.data
    assert b"INF1103" in response.data


def test_frontend_post_adapts_upload_prompt_and_credits_to_core(monkeypatch):
    frontend = load_frontend_module()
    captured = {}

    def fake_process_assessment(input_record):
        captured.update(input_record)
        captured["upload_exists_during_call"] = Path(
            input_record["image_paths"][0]
        ).is_file()
        return {
            "ok": True,
            "record": {
                "module": "INF1103",
                "assessment_type": "Project",
                "status": "READY",
            },
            "errors": [],
            "preserved": False,
        }

    monkeypatch.setattr(frontend.core_main, "process_assessment", fake_process_assessment)
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
            "assessment_type": "Project",
            "deadline": "2026-10-12",
            "weightage": "30",
            "prompt": "Use this screenshot as supporting evidence.",
            "source_files": (BytesIO(b"image-bytes"), "assessment.png"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert captured["module_credits"] == 12.0
    assert captured["weightage"] == 30.0
    assert captured["prompt"] == "Use this screenshot as supporting evidence."
    assert captured["upload_exists_during_call"] is True
    assert Path(captured["image_paths"][0]).exists() is False


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
