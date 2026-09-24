"""Procedural PostgreSQL persistence for the containerised API."""

import json
import logging
import os
from typing import Any, Dict, List

from . import contracts


LOGGER = logging.getLogger(__name__)


def database_url() -> str:
    """Return the configured database URL or fail with a clear local error."""
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise ValueError("DATABASE_URL is not configured.")
    return value


def connect_database():
    """Open one short-lived PostgreSQL connection."""
    import psycopg

    return psycopg.connect(database_url())


def initialize_database() -> bool:
    """Create the two small MVP tables when the API container starts."""
    try:
        with connect_database() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS assessment_records (
                        storage_id BIGSERIAL PRIMARY KEY,
                        record_id TEXT NOT NULL,
                        module TEXT NOT NULL,
                        assessment_type TEXT NOT NULL,
                        deadline DATE,
                        weightage DOUBLE PRECISION,
                        priority TEXT,
                        status TEXT NOT NULL,
                        missing_fields JSONB NOT NULL,
                        issues JSONB NOT NULL,
                        revision INTEGER NOT NULL,
                        UNIQUE (record_id, revision)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS module_profiles (
                        module TEXT PRIMARY KEY,
                        credits DOUBLE PRECISION NOT NULL
                    )
                    """
                )
    except Exception:
        LOGGER.exception("Could not initialize PostgreSQL storage")
        return False
    return True


def database_is_ready() -> bool:
    """Return whether the API can execute a trivial database query."""
    try:
        with connect_database() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone()[0] == 1
    except Exception:
        return False


def load_records() -> List[Dict[str, Any]]:
    """Load frozen-contract records in insertion order."""
    try:
        with connect_database() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT record_id, module, assessment_type, deadline, weightage,
                           priority, status, missing_fields, issues, revision
                    FROM assessment_records
                    ORDER BY storage_id
                    """
                )
                rows = cursor.fetchall()
    except Exception:
        LOGGER.exception("Could not load assessment records from PostgreSQL")
        return []

    return [
        {
            "record_id": row[0],
            "module": row[1],
            "assessment_type": row[2],
            "deadline": row[3].isoformat() if row[3] is not None else None,
            "weightage": row[4],
            "priority": row[5],
            "status": row[6],
            "missing_fields": row[7],
            "issues": row[8],
            "revision": row[9],
        }
        for row in rows
    ]


def save_record_revision(record: Dict[str, Any]) -> bool:
    """Append one frozen-contract revision in a database transaction."""
    return save_record_revisions([record])


def save_record_revisions(records: List[Dict[str, Any]]) -> bool:
    """Append a complete extraction atomically or save none of it."""
    if not records or any(contracts.validate_record_contract(record) for record in records):
        LOGGER.error("Refused invalid PostgreSQL assessment records")
        return False
    try:
        with connect_database() as connection:
            with connection.cursor() as cursor:
                for record in records:
                    cursor.execute(
                        """
                        SELECT COALESCE(MAX(revision), 0)
                        FROM assessment_records
                        WHERE record_id = %s
                        """,
                        (record["record_id"],),
                    )
                    expected_revision = cursor.fetchone()[0] + 1
                    if record["revision"] != expected_revision:
                        raise ValueError("Assessment revision is out of sequence.")
                    cursor.execute(
                        """
                        INSERT INTO assessment_records (
                            record_id, module, assessment_type, deadline, weightage,
                            priority, status, missing_fields, issues, revision
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s
                        )
                        """,
                        (
                            record["record_id"],
                            record["module"],
                            record["assessment_type"],
                            record["deadline"],
                            record["weightage"],
                            record["priority"],
                            record["status"],
                            json.dumps(record["missing_fields"]),
                            json.dumps(record["issues"]),
                            record["revision"],
                        ),
                    )
    except Exception:
        LOGGER.exception("Could not append assessment records to PostgreSQL")
        return False
    return True


def load_module_profiles() -> Dict[str, Dict[str, float]]:
    """Load module-credit context keyed by normalized module code."""
    try:
        with connect_database() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT module, credits FROM module_profiles ORDER BY module"
                )
                rows = cursor.fetchall()
    except Exception:
        LOGGER.exception("Could not load module profiles from PostgreSQL")
        return {}
    return {row[0]: {"credits": float(row[1])} for row in rows}


def save_module_profile(module: str, credits: float) -> bool:
    """Create or update one normalized module-credit profile."""
    normalized_module = module.strip().upper()
    if (
        not normalized_module
        or isinstance(credits, bool)
        or not isinstance(credits, (int, float))
        or not 0 < credits <= 60
    ):
        return False
    try:
        with connect_database() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO module_profiles (module, credits)
                    VALUES (%s, %s)
                    ON CONFLICT (module)
                    DO UPDATE SET credits = EXCLUDED.credits
                    """,
                    (normalized_module, float(credits)),
                )
    except Exception:
        LOGGER.exception("Could not save a module profile to PostgreSQL")
        return False
    return True
