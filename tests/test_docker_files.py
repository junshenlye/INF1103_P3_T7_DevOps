from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_dockerfile_runs_procedural_cli_as_non_root_user():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "USER appuser" in dockerfile
    assert 'ENTRYPOINT ["python", "-m", "src.main"]' in dockerfile
    assert "COPY .env" not in dockerfile


def test_compose_mounts_persistent_data_and_injects_env_file():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "./data:/app/data" in compose
    assert "DATA_FILE: /app/data/schedules.json" in compose
    assert "MODULE_FILE: /app/data/modules.json" in compose
    assert "- .env" in compose
    assert '"${WEB_PORT:-5050}:5000"' in compose
    assert "frontend-demo/app.py" in compose


def test_docker_context_excludes_local_secrets_and_tooling():
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert ".env" in dockerignore.splitlines()
    assert ".venv" in dockerignore.splitlines()
    assert ".git" in dockerignore.splitlines()
