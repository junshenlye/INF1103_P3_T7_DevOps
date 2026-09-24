"""Store the current single-module assessment plan in PostgreSQL."""

import json
import logging
import os


LOGGER = logging.getLogger(__name__)


def initialize_storage():
    """Create the one table used by the MVP."""
    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS assessment_records (
                        id BIGSERIAL PRIMARY KEY,
                        module TEXT NOT NULL,
                        assessment_type TEXT NOT NULL,
                        deadline SMALLINT,
                        weightage DOUBLE PRECISION,
                        priority TEXT,
                        status TEXT NOT NULL,
                        issues JSONB NOT NULL
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
    """Replace the disposable store with the latest single-module result."""
    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM assessment_records")
                for record in plan["assessments"]:
                    deadline = record["deadline"]
                    cursor.execute(
                        """
                        INSERT INTO assessment_records (
                            module, assessment_type, deadline, weightage,
                            priority, status, issues
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            record["module"],
                            record["assessment_type"],
                            int(deadline.split()[1]) if deadline else None,
                            record["weightage"],
                            record["priority"],
                            record["status"],
                            json.dumps(record["issues"]),
                        ),
                    )
    except Exception:
        LOGGER.exception("Could not save the assessment plan")
        return False
    return True


def load_assessments():
    """Load the current module assessments in insertion order."""
    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT module, assessment_type, deadline, weightage,
                           priority, status, issues
                    FROM assessment_records
                    ORDER BY id
                    """
                )
                rows = cursor.fetchall()
    except Exception:
        LOGGER.exception("Could not load the assessment plan")
        return []
    return [
        {
            "module": row[0],
            "assessment_type": row[1],
            "deadline": f"Week {row[2]}" if row[2] is not None else None,
            "weightage": row[3],
            "priority": row[4],
            "status": row[5],
            "issues": row[6],
        }
        for row in rows
    ]


def _connect():
    """Open one short-lived database connection."""
    import psycopg

    return psycopg.connect(os.environ["DATABASE_URL"])
