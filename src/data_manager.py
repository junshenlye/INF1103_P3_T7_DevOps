"""JSON persistence functions for processed assessment records."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import contracts


LOGGER = logging.getLogger(__name__)


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
