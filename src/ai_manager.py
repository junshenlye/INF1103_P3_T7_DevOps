"""AI boundary for prompt construction and OpenRouter communication.

The live OpenRouter integration is intentionally deferred to Milestone 2. This
module defines the procedural interface that the pipeline will call.
"""

import logging
from typing import Any, Callable, Dict, Optional


LOGGER = logging.getLogger(__name__)


def process_record(
    input_record: Dict[str, Any],
    api_caller: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return a safe placeholder result for the future AI integration."""
    LOGGER.info("AI processing requested while the integration is a placeholder")
    return {
        "ok": False,
        "record": None,
        "errors": ["AI integration is not implemented in the skeleton."],
    }
