"""Persist pipeline inputs and outputs without owning business logic."""

import json
import logging
import os


LOGGER = logging.getLogger(__name__)


def initialize_storage():
    """Create one disposable PostgreSQL slot for the current plan."""
    if not _database_configured():
        LOGGER.error("DATABASE_URL is required; local file persistence is disabled")
        return False
    try:
        with _connect() as connection:
            _ensure_schema(connection)
    except Exception:
        LOGGER.exception("Could not initialize PostgreSQL")
        return False
    return True


def storage_is_ready():
    """Return whether PostgreSQL can answer a small query."""
    if not _database_configured():
        return False
    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone()[0] == 1
    except Exception:
        return False


def save_plan(plan):
    """Replace the single disposable plan."""
    if not _database_configured():
        LOGGER.error("Cannot save a plan without DATABASE_URL")
        return False
    try:
        with _connect() as connection:
            _ensure_schema(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO current_plan (slot, plan)
                    VALUES (TRUE, %s::jsonb)
                    ON CONFLICT (slot) DO UPDATE SET plan = EXCLUDED.plan
                    """,
                    (json.dumps(plan),),
                )
    except Exception:
        LOGGER.exception("Could not save the assessment plan")
        return False
    return True


def save(input_data, ai_result, pacing_result):
    """Store the latest normalized input, AI output, and final pacing result."""
    safe_input = {
        "modules": [
            {
                "module_name": module.get("module_name"),
                "credit_units": module.get("credit_units"),
                "additional_context": module.get("additional_context", ""),
                "files": [
                    {"name": os.path.basename(path)}
                    for path in module.get("files", [])
                ],
            }
            for module in input_data.get("modules", [])
        ]
    }
    record = {
        "input_data": safe_input,
        "ai_result": ai_result,
        "pacing_result": pacing_result,
    }
    return save_plan(record)


def load_plan():
    """Load the current plan or an empty dashboard."""
    if not _database_configured():
        return _empty_plan()
    try:
        with _connect() as connection:
            _ensure_schema(connection)
            with connection.cursor() as cursor:
                cursor.execute("SELECT plan FROM current_plan WHERE slot = TRUE")
                row = cursor.fetchone()
    except Exception:
        LOGGER.exception("Could not load the assessment plan")
        return _empty_plan()
    if row is None:
        return _empty_plan()
    record = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    if isinstance(record, dict) and isinstance(record.get("pacing_result"), dict):
        return record["pacing_result"]
    return record


def _empty_plan():
    """Return an empty pacing dashboard."""
    return {
        "trimester_context": {},
        "current_week": None,
        "relative_assessment_ranking": [],
        "module_weight_coverage": [],
        "timeline": [],
        "pressure_by_week": [],
        "overlaps": [],
        "clusters": [],
        "overall_pacing": {},
        "comments": [],
        "user_checklist": [],
    }


def _connect():
    """Open one short-lived database connection."""
    import psycopg

    return psycopg.connect(os.environ["DATABASE_URL"])


def _ensure_schema(connection):
    """Recreate the disposable table after a database restart when needed."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS current_plan (
                slot BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (slot),
                plan JSONB NOT NULL
            )
            """
        )


def _database_configured():
    return bool(os.getenv("DATABASE_URL", "").strip())
