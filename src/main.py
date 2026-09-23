"""CLI entry point and procedural application orchestration."""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from . import data_manager, io_manager


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_FILE = PROJECT_ROOT / "data" / "schedules.json"


def resolve_data_file_path(configured_path: Optional[str] = None) -> str:
    """Resolve an environment or caller-provided data file path."""
    raw_path = configured_path or os.getenv("DATA_FILE")
    if not raw_path:
        return str(DEFAULT_DATA_FILE)

    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path)


def start_application(data_file: Optional[str] = None) -> Dict[str, Any]:
    """Load local configuration and existing records without starting a UI loop."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    resolved_data_file = resolve_data_file_path(data_file)
    records = data_manager.load_records(resolved_data_file)
    return {
        "records": records,
        "records_loaded": len(records),
        "data_file": resolved_data_file,
    }


def main() -> None:
    """Start the command-line skeleton."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    logging.info("Starting academic assessment prioritiser")
    summary = start_application()
    io_manager.display_startup_summary(summary)


if __name__ == "__main__":
    main()
