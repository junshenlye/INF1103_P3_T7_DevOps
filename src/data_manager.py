"""JSON persistence functions for processed assessment records."""

import json
import logging
import os
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

    return _write_json_atomic(records, path)


def save_record_revision(record: Dict[str, Any], data_file: str) -> bool:
    """Append one valid record revision to the JSON store."""
    if contracts.validate_record_contract(record):
        LOGGER.error("Refused to save a record that violates the frozen contract")
        return False

    records, load_error = _load_records_for_update(data_file)
    if load_error:
        LOGGER.error(
            "Refused to overwrite unsafe data file %s: %s",
            data_file,
            load_error,
        )
        return False
    if any(
        existing["record_id"] == record["record_id"]
        and existing["revision"] == record["revision"]
        for existing in records
    ):
        LOGGER.error("Refused to save a duplicate record revision")
        return False

    expected_revision = next_revision(records, record["record_id"])
    if record["revision"] != expected_revision:
        LOGGER.error(
            "Refused revision %s; expected revision %s",
            record["revision"],
            expected_revision,
        )
        return False
    records.append(record)
    return save_records(records, data_file)


def save_record_revisions(records_to_add: List[Dict[str, Any]], data_file: str) -> bool:
    """Atomically append multiple valid revisions or append none of them."""
    if not isinstance(records_to_add, list) or not records_to_add:
        LOGGER.error("Refused an empty bulk record save")
        return False
    if any(contracts.validate_record_contract(record) for record in records_to_add):
        LOGGER.error("Refused bulk records that violate the frozen contract")
        return False

    existing_records, load_error = _load_records_for_update(data_file)
    if load_error:
        LOGGER.error(
            "Refused to overwrite unsafe data file %s: %s",
            data_file,
            load_error,
        )
        return False

    combined_records = list(existing_records)
    for record in records_to_add:
        if any(
            existing["record_id"] == record["record_id"]
            and existing["revision"] == record["revision"]
            for existing in combined_records
        ):
            LOGGER.error("Refused a duplicate record revision in bulk save")
            return False
        expected_revision = next_revision(combined_records, record["record_id"])
        if record["revision"] != expected_revision:
            LOGGER.error(
                "Refused bulk revision %s; expected revision %s",
                record["revision"],
                expected_revision,
            )
            return False
        combined_records.append(record)
    return save_records(combined_records, data_file)


def get_record_history(
    records: List[Dict[str, Any]],
    record_id: str,
) -> List[Dict[str, Any]]:
    """Return one record's revisions in ascending order."""
    return sorted(
        [record for record in records if record.get("record_id") == record_id],
        key=lambda record: record["revision"],
    )


def get_latest_record(
    records: List[Dict[str, Any]],
    record_id: str,
) -> Optional[Dict[str, Any]]:
    """Return the latest revision for one record ID."""
    history = get_record_history(records, record_id)
    return history[-1] if history else None


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


def load_module_profiles(module_file: str) -> Dict[str, Dict[str, float]]:
    """Load module-credit metadata safely from its separate JSON store."""
    profiles, load_error = _load_module_profiles_for_update(module_file)
    if load_error:
        LOGGER.error("Could not load module profiles %s: %s", module_file, load_error)
        return {}
    return {
        module.strip().upper(): {"credits": float(profile["credits"])}
        for module, profile in profiles.items()
    }


def save_module_profile(module: str, credits: float, module_file: str) -> bool:
    """Create or update one module-credit profile without changing records."""
    normalized_module = module.strip().upper()
    if (
        not normalized_module
        or isinstance(credits, bool)
        or not isinstance(credits, (int, float))
        or not 0 < credits <= 60
    ):
        LOGGER.error("Refused invalid module credit metadata")
        return False

    profiles, load_error = _load_module_profiles_for_update(module_file)
    if load_error:
        LOGGER.error(
            "Refused to overwrite unsafe module file %s: %s",
            module_file,
            load_error,
        )
        return False
    profiles[normalized_module] = {"credits": float(credits)}
    return _write_json_atomic(profiles, Path(module_file))


def _load_records_for_update(data_file: str):
    """Load an existing store strictly so corrupt data is never overwritten."""
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
        not isinstance(record, dict)
        or contracts.validate_record_contract(record)
        for record in payload
    ):
        return [], "existing data contains an invalid record"
    return payload, None


def _load_module_profiles_for_update(module_file: str):
    """Load module metadata strictly so corrupt profiles are not overwritten."""
    path = Path(module_file)
    if not path.exists():
        return {}, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, "existing module data is unreadable or corrupt"
    if not isinstance(payload, dict):
        return {}, "existing module data is not a JSON object"
    for module, profile in payload.items():
        if (
            not isinstance(module, str)
            or not module.strip()
            or not isinstance(profile, dict)
            or set(profile) != {"credits"}
            or isinstance(profile["credits"], bool)
            or not isinstance(profile["credits"], (int, float))
            or not 0 < profile["credits"] <= 60
        ):
            return {}, "existing module data contains an invalid profile"
    return payload, None


def _write_json_atomic(payload: Any, path: Path) -> bool:
    """Write one JSON payload privately and replace the destination atomically."""
    temporary_path = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as data_stream:
            data_stream.write(serialized)
            data_stream.flush()
            os.fsync(data_stream.fileno())
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
