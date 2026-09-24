from io import BytesIO
import importlib.util
from pathlib import Path

from helpers import api_server, progress_tracker


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_PATH = PROJECT_ROOT / "frontend-demo" / "app.py"


def load_frontend_module():
    spec = importlib.util.spec_from_file_location("frontend_demo_app", FRONTEND_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dashboard_summary():
    return {
        "latest_records": [],
        "records_loaded": 0,
        "module_profiles": {"INF1103": {"credits": 6.0}},
        "schedule": {
            "blocks": [],
            "weeks": [],
            "excluded_records": [],
            "warnings": [],
        },
    }


def test_host_frontend_renders_state_read_from_docker_api(monkeypatch):
    frontend = load_frontend_module()
    monkeypatch.setattr(
        frontend,
        "load_dashboard",
        lambda: (dashboard_summary(), None),
    )

    response = frontend.app.test_client().get("/")

    assert response.status_code == 200
    assert b"Extract every assessment" in response.data
    assert b"Drop all snapshots for this module" in response.data
    assert b"INF1103" in response.data
    assert b'name="assessment_type"' not in response.data
    assert b'http://127.0.0.1:8000/api/extractions' in response.data


def test_host_frontend_forwards_human_review_to_api(monkeypatch):
    frontend = load_frontend_module()
    captured = {}

    def fake_request(path, method="GET", payload=None):
        captured.update({"path": path, "method": method, "payload": payload})
        return {"ok": True, "record": {"module": "INF1103"}}, 200

    monkeypatch.setattr(frontend, "request_api", fake_request)
    monkeypatch.setattr(
        frontend,
        "load_dashboard",
        lambda: (dashboard_summary(), None),
    )

    response = frontend.app.test_client().post(
        "/review/record-001",
        data={
            "assessment_type": "Quiz 1",
            "deadline": "2026-10-20",
            "weightage": "10",
        },
    )

    assert response.status_code == 200
    assert captured["path"] == "/api/assessments/record-001/review"
    assert captured["method"] == "POST"
    assert captured["payload"]["deadline"] == "2026-10-20"


def test_docker_api_reports_background_extraction_progress(monkeypatch):
    progress_tracker.JOBS.clear()
    captured = {}

    def fake_process_source(input_source, progress_callback=None):
        captured.update(input_source)
        captured["upload_exists"] = Path(input_source["image_paths"][0]).is_file()
        progress_callback(
            {
                "stage": "ai_request",
                "message": "Waiting for Nemotron.",
                "attempt": 1,
                "max_attempts": 3,
            }
        )
        return {
            "ok": True,
            "source_module": "INF1103",
            "extracted_count": 2,
            "errors": [],
        }

    monkeypatch.setattr(api_server.core_main, "process_assessment_source", fake_process_source)
    monkeypatch.setattr(
        api_server,
        "start_extraction_worker",
        lambda job_id, source, upload_dir: api_server.run_extraction_job(
            job_id,
            source,
            upload_dir,
        ),
    )
    client = api_server.app.test_client()

    response = client.post(
        "/api/extractions",
        data={
            "module": "INF1103",
            "module_credits": "6",
            "prompt": "Extract all events.",
            "source_files": (BytesIO(b"image"), "assessment.png"),
        },
        content_type="multipart/form-data",
    )
    status = client.get(response.get_json()["status_url"]).get_json()

    assert response.status_code == 202
    assert captured["upload_exists"] is True
    assert Path(captured["image_paths"][0]).exists() is False
    assert status["status"] == "complete"
    assert status["result"]["extracted_count"] == 2
    assert any(event["stage"] == "ai_request" for event in status["events"])
