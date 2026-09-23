"""Deterministic assessment business rules.

Milestone 2 will replace the safe placeholder defaults with the first complete
READY-path rules while preserving this procedural interface.
"""

from typing import Any, Dict, Optional


def apply_business_rules(
    ai_record: Dict[str, Any],
    record_id: str,
    revision: int,
    scheduling_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build an exact contract record with safe placeholder business fields."""
    return {
        "record_id": record_id,
        "module": ai_record.get("module", ""),
        "assessment_type": ai_record.get("assessment_type", ""),
        "deadline": ai_record.get("deadline"),
        "weightage": ai_record.get("weightage"),
        "priority": None,
        "status": "NEEDS_REVIEW",
        "missing_fields": list(ai_record.get("missing_fields", [])),
        "issues": list(ai_record.get("issues", [])),
        "revision": revision,
    }
