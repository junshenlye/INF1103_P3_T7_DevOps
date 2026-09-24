"""Select JSON locally or PostgreSQL inside the Docker API."""

import os
from typing import Any, Dict, List

from . import data_manager, postgres_manager


def uses_postgres() -> bool:
    """Return whether runtime persistence is configured for PostgreSQL."""
    return bool(os.getenv("DATABASE_URL", "").strip())


def initialize_storage() -> bool:
    """Initialize the selected persistence backend."""
    if uses_postgres():
        return postgres_manager.initialize_database()
    return True


def storage_is_ready() -> bool:
    """Return whether the selected persistence backend can be reached."""
    if uses_postgres():
        return postgres_manager.database_is_ready()
    return True


def load_records(data_file: str) -> List[Dict[str, Any]]:
    """Load records from the selected backend."""
    if uses_postgres():
        return postgres_manager.load_records()
    return data_manager.load_records(data_file)


def save_record_revision(record: Dict[str, Any], data_file: str) -> bool:
    """Append one revision to the selected backend."""
    if uses_postgres():
        return postgres_manager.save_record_revision(record)
    return data_manager.save_record_revision(record, data_file)


def save_record_revisions(records: List[Dict[str, Any]], data_file: str) -> bool:
    """Append multiple revisions atomically to the selected backend."""
    if uses_postgres():
        return postgres_manager.save_record_revisions(records)
    return data_manager.save_record_revisions(records, data_file)


def load_module_profiles(module_file: str) -> Dict[str, Dict[str, float]]:
    """Load module credits from the selected backend."""
    if uses_postgres():
        return postgres_manager.load_module_profiles()
    return data_manager.load_module_profiles(module_file)


def save_module_profile(module: str, credits: float, module_file: str) -> bool:
    """Save module credits to the selected backend."""
    if uses_postgres():
        return postgres_manager.save_module_profile(module, credits)
    return data_manager.save_module_profile(module, credits, module_file)
