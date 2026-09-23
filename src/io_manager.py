"""Terminal input and output boundary for the procedural application."""

from typing import Any, Dict


def format_startup_summary(summary: Dict[str, Any]) -> str:
    """Format the initial CLI status without producing output directly."""
    return (
        "Academic Assessment Prioritiser\n"
        f"Loaded {summary['records_loaded']} saved record(s).\n"
        "Procedural skeleton is ready."
    )


def display_startup_summary(summary: Dict[str, Any]) -> None:
    """Display the initial CLI status."""
    print(format_startup_summary(summary))


def display_message(message: str) -> None:
    """Display a user-facing message from another procedural module."""
    print(message)
