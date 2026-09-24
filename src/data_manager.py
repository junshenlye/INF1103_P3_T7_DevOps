"""Store one finished single-module plan in PostgreSQL."""

import json
import logging
import os


LOGGER = logging.getLogger(__name__)


def initialize_storage():
    """Create one JSON slot for the current plan."""
    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS current_plan (
                        slot BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (slot),
                        plan JSONB NOT NULL
                    )
                    """
                )
    except Exception:
        LOGGER.exception("Could not initialize PostgreSQL")
        return False
    return True


def storage_is_ready():
    """Return whether PostgreSQL can answer a small query."""
    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone()[0] == 1
    except Exception:
        return False


def save_plan(plan):
    """Replace the single disposable plan."""
    try:
        with _connect() as connection:
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


def load_plan():
    """Load the current plan or an empty dashboard."""
    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT plan FROM current_plan WHERE slot = TRUE")
                row = cursor.fetchone()
    except Exception:
        LOGGER.exception("Could not load the assessment plan")
        return _empty_plan()
    if row is None:
        return _empty_plan()
    return json.loads(row[0]) if isinstance(row[0], str) else row[0]


def _empty_plan():
    """Return the only empty output shape used by the UI."""
    return {"module": None, "schedule": {"weeks": [], "blocks": []}, "checklist": []}


def _connect():
    """Open one short-lived database connection."""
    import psycopg

    return psycopg.connect(os.environ["DATABASE_URL"])
