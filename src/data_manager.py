"""Persistence and record-history functions for JSON or PostgreSQL."""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from . import io_manager


LOGGER = logging.getLogger(__name__)


def database_enabled() -> bool:
    """Return whether Docker supplied a PostgreSQL connection."""
    return bool(os.getenv("DATABASE_URL", "").strip())


def initialize_storage() -> bool:
    """Prepare PostgreSQL; JSON needs no startup work."""
    if not database_enabled():
        return True
    try:
        with _connect_database() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS assessment_records (
                        storage_id BIGSERIAL PRIMARY KEY,
                        record_id TEXT NOT NULL,
                        module TEXT NOT NULL,
                        assessment_type TEXT NOT NULL,
                        deadline SMALLINT,
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
    except Exception:
        LOGGER.exception("Could not initialize PostgreSQL storage")
        return False
    return True


def storage_is_ready() -> bool:
    """Return whether the selected storage can be reached."""
    if not database_enabled():
        return True
    try:
        with _connect_database() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone()[0] == 1
    except Exception:
        return False


def generate_record_id() -> str:
    """Generate an opaque record identifier without shared mutable state."""
    return str(uuid4())


def load_records(data_file: str) -> List[Dict[str, Any]]:
    """Load records from PostgreSQL in Docker or JSON for the CLI."""
    if database_enabled():
        return _load_database_records()
    return _load_json_records(data_file)


def save_record_revision(record: Dict[str, Any], data_file: str) -> bool:
    """Append one validated revision to the selected store."""
    return save_record_revisions([record], data_file)


def save_record_revisions(
    records_to_add: List[Dict[str, Any]],
    data_file: str,
) -> bool:
    """Append a complete extraction atomically or save none of it."""
    if not records_to_add or any(
        io_manager.validate_record(record) for record in records_to_add
    ):
        LOGGER.error("Refused records that violate the frozen contract")
        return False
    if database_enabled():
        return _save_database_records(records_to_add)
    return _save_json_revisions(records_to_add, data_file)


def get_latest_record(
    records: List[Dict[str, Any]],
    record_id: str,
) -> Optional[Dict[str, Any]]:
    """Return the latest revision for one record ID."""
    matching = [
        record for record in records if record.get("record_id") == record_id
    ]
    return max(matching, key=lambda record: record["revision"], default=None)


def latest_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return only the latest revision of every record ID."""
    latest_by_id = {}
    for record in records:
        current = latest_by_id.get(record["record_id"])
        if current is None or record["revision"] > current["revision"]:
            latest_by_id[record["record_id"]] = record
    return list(latest_by_id.values())


def next_revision(records: List[Dict[str, Any]], record_id: str) -> int:
    """Return the next append-only revision number for a record ID."""
    latest = get_latest_record(records, record_id)
    return 1 if latest is None else latest["revision"] + 1


def _connect_database():
    """Open one short-lived PostgreSQL connection."""
    import psycopg

    return psycopg.connect(os.environ["DATABASE_URL"])


def _load_database_records() -> List[Dict[str, Any]]:
    """Load frozen records from PostgreSQL in insertion order."""
    try:
        with _connect_database() as connection:
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
    return [_database_row_to_record(row) for row in rows]


def _database_row_to_record(row) -> Dict[str, Any]:
    """Convert one database row back to the frozen record shape."""
    return {
        "record_id": row[0],
        "module": row[1],
        "assessment_type": row[2],
        "deadline": f"Week {row[3]}" if row[3] is not None else None,
        "weightage": row[4],
        "priority": row[5],
        "status": row[6],
        "missing_fields": row[7],
        "issues": row[8],
        "revision": row[9],
    }


def _save_database_records(records: List[Dict[str, Any]]) -> bool:
    """Append validated records in one PostgreSQL transaction."""
    try:
        with _connect_database() as connection:
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
                    if record["revision"] != cursor.fetchone()[0] + 1:
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
                            (
                                int(record["deadline"].split()[1])
                                if record["deadline"] is not None
                                else None
                            ),
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


def _load_json_records(data_file: str) -> List[Dict[str, Any]]:
    """Load valid records safely from the CLI JSON store."""
    records, error = _load_json_records_strict(data_file)
    if error:
        LOGGER.error("Could not load data file %s: %s", data_file, error)
        return []
    return records


def _save_json_revisions(
    records_to_add: List[Dict[str, Any]],
    data_file: str,
) -> bool:
    """Append validated records atomically to the CLI JSON store."""
    existing_records, error = _load_json_records_strict(data_file)
    if error:
        LOGGER.error("Refused unsafe data file %s: %s", data_file, error)
        return False

    combined_records = list(existing_records)
    for record in records_to_add:
        duplicate = any(
            saved["record_id"] == record["record_id"]
            and saved["revision"] == record["revision"]
            for saved in combined_records
        )
        if duplicate or record["revision"] != next_revision(
            combined_records,
            record["record_id"],
        ):
            LOGGER.error("Refused duplicate or out-of-sequence record revision")
            return False
        combined_records.append(record)
    return _write_json(combined_records, Path(data_file))


def _load_json_records_strict(data_file: str):
    """Load JSON records without ever overwriting corrupt content."""
    path = Path(data_file)
    if not path.exists():
        return [], None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], "existing data is unreadable or corrupt"
    if not isinstance(payload, list):
        return [], "existing data is not a JSON list"
    if any(
        not isinstance(record, dict) or io_manager.validate_record(record)
        for record in payload
    ):
        return [], "existing data contains an invalid record"
    return payload, None


def _write_json(payload: Any, path: Path) -> bool:
    """Write JSON privately and replace the destination atomically."""
    temporary_path = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    except (OSError, TypeError, ValueError) as error:
        LOGGER.error("Could not save JSON file %s: %s", path, error)
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True
