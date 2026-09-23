"""JSON persistence functions for processed assessment records."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from . import contracts


LOGGER = logging.getLogger(__name__)


def generate_record_id() -> str:
    """Generate an opaque record identifier without shared mutable state."""
    return str(uuid4())


def load_records(data_file: str) -> List[Dict[str, Any]]:
    """Load records safely, returning an empty list for missing or corrupt data."""
    path = Path(data_file)
    if not path.exists():
        LOGGER.info("Data file does not exist yet: %s", path)
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        LOGGER.error("Could not load data file %s: %s", path, error)
        return []

    if not isinstance(payload, list):
        LOGGER.error("Data file %s must contain a JSON list", path)
        return []

    records = [
        record
        for record in payload
        if isinstance(record, dict)
        and contracts.validate_record_contract(record) == []
    ]
    if len(records) != len(payload):
        LOGGER.warning("Ignored invalid record entries in data file %s", path)
    return records


def save_records(records: List[Dict[str, Any]], data_file: str) -> bool:
    """Save a complete record list to JSON and report success without crashing."""
    path = Path(data_file)
    if not isinstance(records, list) or any(
        contracts.validate_record_contract(record) for record in records
    ):
        LOGGER.error("Refused to save records that violate the frozen contract")
        return False

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(records, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, TypeError, ValueError) as error:
        LOGGER.error("Could not save data file %s: %s", path, error)
        return False
    return True


def save_record_revision(record: Dict[str, Any], data_file: str) -> bool:
    """Append one valid record revision to the JSON store."""
    if contracts.validate_record_contract(record):
        LOGGER.error("Refused to save a record that violates the frozen contract")
        return False

    records = load_records(data_file)
    records.append(record)
    return save_records(records, data_file)


def filter_records(
    records: List[Dict[str, Any]],
    module: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return records matching the optional module and status filters."""
    return [
        record
        for record in records
        if (module is None or record.get("module") == module)
        and (status is None or record.get("status") == status)
    ]
