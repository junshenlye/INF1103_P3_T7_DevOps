from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_dockerfile_runs_procedural_api_as_non_root_user():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "USER appuser" in dockerfile
    assert 'ENTRYPOINT ["python", "helpers/api_server.py"]' in dockerfile
    assert "COPY --chown=appuser:appuser helpers ./helpers" in dockerfile
    assert "frontend-demo" not in dockerfile
    assert "COPY .env" not in dockerfile


def test_compose_exposes_api_and_ephemeral_postgres():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "postgres:16-alpine" in compose
    assert "/var/lib/postgresql/data" in compose
    assert "tmpfs:" in compose
    assert '"${API_PORT:-8000}:8000"' in compose
    assert '"${POSTGRES_PORT:-5433}:5432"' in compose
    assert "DATABASE_URL:" in compose
    assert "- .env" in compose
    assert "./data:/app/data" not in compose


def test_docker_context_excludes_local_secrets_and_tooling():
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert ".env" in dockerignore.splitlines()
    assert ".venv" in dockerignore.splitlines()
    assert ".git" in dockerignore.splitlines()
