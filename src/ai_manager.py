"""OpenRouter communication and AI extraction schema validation."""

from datetime import date
import base64
import http.client
import json
import logging
import os
import re
import ssl
from typing import Any, Callable, Dict, List, Optional

from . import contracts


LOGGER = logging.getLogger(__name__)
DEFAULT_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MAX_ATTEMPTS = 3
MAX_ALLOWED_ATTEMPTS = 5
MAX_EXTRACTED_ASSESSMENTS = 30
EXTRACTION_FIELDS = (
    "module",
    "assessment_type",
    "deadline",
    "weightage",
    "missing_fields",
    "issues",
)


def build_prompt(input_record: Dict[str, Any]) -> str:
    """Build a strict extraction prompt without adding business rules."""
    prompt_input = {
        key: value
        for key, value in input_record.items()
        if key not in ("image_paths", "record_id", "module_credits")
    }
    schema_example = {
        "module": "INF1103",
        "assessment_type": "Project",
        "deadline": "2026-10-15",
        "weightage": 30,
        "missing_fields": [],
        "issues": [],
    }
    return (
        "Extract assessment information from the supplied input record.\n"
        "Return exactly one JSON object with no markdown or commentary.\n"
        f"Use exactly these keys: {', '.join(EXTRACTION_FIELDS)}.\n"
        "Do not calculate status or priority.\n"
        "Treat each non-null structured input field as a user-supplied fact. "
        "Preserve it unless an attached source explicitly gives a different "
        "value. A teaching-week label alone does not contradict an exact date "
        "when no academic calendar is supplied.\n"
        "Do not invent missing information. Use null for a missing deadline or "
        "weightage and list its field name in missing_fields.\n"
        "Dates must use YYYY-MM-DD when an exact date is supplied. A teaching "
        "week such as 'Week 6' is not an exact date and must become null.\n"
        "Each issue must contain type, field, severity, and feedback. Severity "
        "must be info, warning, or error.\n"
        f"Example shape: {json.dumps(schema_example, separators=(',', ':'))}\n"
        f"Input record: {json.dumps(prompt_input, ensure_ascii=False)}"
    )


def build_source_prompt(input_source: Dict[str, Any]) -> str:
    """Build the one-to-many extraction prompt for a module evidence pack."""
    module = input_source["module"].strip().upper()
    source_context = {
        "module": module,
        "prompt": input_source.get("prompt", ""),
        "attached_image_count": len(input_source.get("image_paths", [])),
    }
    assessment_example = {
        "module": module,
        "assessment_type": "Quiz 1",
        "deadline": "2026-10-15",
        "weightage": 10,
        "missing_fields": [],
        "issues": [],
    }
    response_example = {"assessments": [assessment_example]}
    return (
        "Inspect all supplied images and context as one module evidence pack.\n"
        "Find every distinct graded assessment event visible or explicitly "
        "described, including quizzes, assignments, projects, presentations, "
        "practical tests, exams, and submission milestones.\n"
        "Return exactly one JSON object with exactly one key: assessments. "
        "assessments must be a non-empty JSON list with one object per event.\n"
        f"Return at most {MAX_EXTRACTED_ASSESSMENTS} events and do not duplicate "
        "the same event across images.\n"
        f"The module is a trusted user fact. Every event must use exactly {module}.\n"
        f"Each event must use exactly these keys: {', '.join(EXTRACTION_FIELDS)}.\n"
        "Do not calculate status, priority, preparation dates, or module credits.\n"
        "Do not invent missing information. Use null for a missing deadline or "
        "weightage and list its field name in missing_fields.\n"
        "Dates must use YYYY-MM-DD only when an exact calendar date is supplied. "
        "A teaching-week label without an academic calendar must become null.\n"
        "Each issue must contain type, field, severity, and feedback. Severity "
        "must be info, warning, or error. Conflicting source values must be "
        "reported as an error issue instead of silently choosing one.\n"
        f"Example shape: {json.dumps(response_example, separators=(',', ':'))}\n"
        f"Source context: {json.dumps(source_context, ensure_ascii=False)}"
    )


def encode_image_data_url(image_path: str) -> str:
    """Encode one supported local image for an OpenRouter multimodal request."""
    path = os.path.abspath(image_path)
    extension = os.path.splitext(path)[1].lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    if extension not in media_types:
        raise ValueError("Image must be PNG, JPEG, WEBP, or GIF.")

    with open(path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("ascii")
    return f"data:{media_types[extension]};base64,{encoded}"


def build_user_content(prompt: str, image_paths: List[str]) -> List[Dict[str, Any]]:
    """Build text-first multimodal content for OpenRouter."""
    content = [{"type": "text", "text": prompt}]
    for image_path in image_paths:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": encode_image_data_url(image_path)},
            }
        )
    return content


def call_openrouter(
    prompt: str,
    image_paths: List[str],
    api_key: str,
    model: str,
    base_url: str,
    timeout_seconds: int = 45,
) -> str:
    """Call the OpenRouter chat-completions endpoint and return message text."""
    if base_url.rstrip("/") != DEFAULT_BASE_URL:
        raise ValueError("OpenRouter base URL is not the official HTTPS endpoint.")

    request_body = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You extract academic assessment data and return only "
                        "the requested JSON object."
                    ),
                },
                {
                    "role": "user",
                    "content": build_user_content(prompt, image_paths),
                },
            ],
            "temperature": 0,
            "max_tokens": 3000,
        }
    ).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    connection = http.client.HTTPSConnection(
        "openrouter.ai",
        timeout=timeout_seconds,
        context=ssl.create_default_context(),
    )
    try:
        connection.request(
            "POST",
            "/api/v1/chat/completions",
            body=request_body,
            headers=headers,
        )
        response = connection.getresponse()
        response_body = response.read()
    except (OSError, http.client.HTTPException) as error:
        raise ConnectionError("OpenRouter request failed.") from error
    finally:
        connection.close()

    if not 200 <= response.status < 300:
        raise ConnectionError("OpenRouter request failed.")

    payload = json.loads(response_body.decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise ValueError("OpenRouter returned an empty model response.")
    return content


def parse_model_response(response_text: str) -> Dict[str, Any]:
    """Parse a plain or fenced JSON object returned by the model."""
    text = response_text.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()

    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("AI response must be one JSON object.")
    return parsed


def validate_extraction(extraction: Dict[str, Any]) -> List[str]:
    """Return schema errors for AI-extracted fields."""
    if not isinstance(extraction, dict):
        return ["AI extraction must be a dictionary."]

    errors = []
    missing_fields = [field for field in EXTRACTION_FIELDS if field not in extraction]
    extra_fields = [field for field in extraction if field not in EXTRACTION_FIELDS]
    if missing_fields:
        errors.append(f"Missing AI fields: {', '.join(missing_fields)}.")
    if extra_fields:
        errors.append(f"Unexpected AI fields: {', '.join(extra_fields)}.")
    if errors:
        return errors

    if not isinstance(extraction["module"], str) or not extraction["module"].strip():
        errors.append("module must be a non-empty string.")
    if (
        not isinstance(extraction["assessment_type"], str)
        or not extraction["assessment_type"].strip()
    ):
        errors.append("assessment_type must be a non-empty string.")

    deadline = extraction["deadline"]
    if deadline is not None:
        if not isinstance(deadline, str):
            errors.append("deadline must be an ISO date string or null.")
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", deadline) is None:
            errors.append("deadline must use YYYY-MM-DD format.")
        else:
            try:
                date.fromisoformat(deadline)
            except ValueError:
                errors.append("deadline must use YYYY-MM-DD format.")

    weightage = extraction["weightage"]
    if weightage is not None:
        if isinstance(weightage, bool) or not isinstance(weightage, (int, float)):
            errors.append("weightage must be a number or null.")
        elif not 0 <= weightage <= 100:
            errors.append("weightage must be between 0 and 100.")

    extracted_missing_fields = extraction["missing_fields"]
    allowed_missing_fields = {
        "module",
        "assessment_type",
        "deadline",
        "weightage",
    }
    if not isinstance(extracted_missing_fields, list) or not all(
        isinstance(field, str) and field in allowed_missing_fields
        for field in extracted_missing_fields
    ):
        errors.append("missing_fields must contain only known field names.")
    else:
        expected_missing_fields = {
            field
            for field in ("deadline", "weightage")
            if extraction[field] is None
        }
        if set(extracted_missing_fields) != expected_missing_fields:
            errors.append("missing_fields must exactly match null extracted values.")

    issues = extraction["issues"]
    if not isinstance(issues, list):
        errors.append("issues must be a list.")
    else:
        for index, issue in enumerate(issues):
            errors.extend(contracts.validate_issue_contract(issue, index))
        if isinstance(extracted_missing_fields, list):
            for field in ("deadline", "weightage"):
                if field in extracted_missing_fields and not any(
                    isinstance(issue, dict)
                    and issue.get("field") == field
                    and isinstance(issue.get("feedback"), str)
                    and issue["feedback"].strip()
                    for issue in issues
                ):
                    errors.append(
                        f"A feedback issue is required for missing {field}."
                    )

    return errors


def validate_source_extraction(
    response: Dict[str, Any],
    expected_module: str,
) -> List[str]:
    """Validate one model response containing many assessment events."""
    if not isinstance(response, dict):
        return ["AI source extraction must be a dictionary."]
    if set(response) != {"assessments"}:
        return ["AI source extraction must contain only assessments."]

    assessments = response["assessments"]
    if not isinstance(assessments, list) or not assessments:
        return ["AI source extraction must contain at least one assessment."]
    if len(assessments) > MAX_EXTRACTED_ASSESSMENTS:
        return [
            "AI source extraction exceeded the assessment event limit of "
            f"{MAX_EXTRACTED_ASSESSMENTS}."
        ]

    errors = []
    seen_events = set()
    normalized_module = expected_module.strip().upper()
    for index, assessment in enumerate(assessments):
        item_errors = validate_extraction(assessment)
        errors.extend(
            f"assessments[{index}]: {error}" for error in item_errors
        )
        if item_errors:
            continue
        if assessment["module"].strip().upper() != normalized_module:
            errors.append(
                f"assessments[{index}]: module must match the supplied module."
            )
        event_key = (
            assessment["assessment_type"].strip().casefold(),
            assessment["deadline"],
            assessment["weightage"],
        )
        if event_key in seen_events:
            errors.append(f"assessments[{index}]: duplicate assessment event.")
        seen_events.add(event_key)
    return errors


def process_source(
    input_source: Dict[str, Any],
    api_caller: Optional[Callable[..., str]] = None,
) -> Dict[str, Any]:
    """Extract and validate every assessment in one module evidence pack."""
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    base_url = (
        os.getenv("OPENROUTER_BASE_URL", DEFAULT_BASE_URL).strip()
        or DEFAULT_BASE_URL
    )

    if api_caller is None and not api_key:
        return {
            "ok": False,
            "extractions": [],
            "errors": ["OPENROUTER_API_KEY is not configured."],
            "attempts": 0,
        }
    if api_caller is None and base_url.rstrip("/") != DEFAULT_BASE_URL:
        return {
            "ok": False,
            "extractions": [],
            "errors": ["OPENROUTER_BASE_URL must use the official HTTPS endpoint."],
            "attempts": 0,
        }

    caller = api_caller or call_openrouter
    caller_api_key = api_key if api_caller is None else ""
    max_attempts = _read_max_attempts()
    last_errors = ["AI response could not be processed."]

    for attempt in range(1, max_attempts + 1):
        LOGGER.info("AI source request attempt %s using model %s", attempt, model)
        try:
            response_text = caller(
                prompt=build_source_prompt(input_source),
                image_paths=list(input_source.get("image_paths", [])),
                api_key=caller_api_key,
                model=model,
                base_url=base_url,
            )
            response = parse_model_response(response_text)
            schema_errors = validate_source_extraction(
                response,
                input_source["module"],
            )
        except (
            OSError,
            http.client.HTTPException,
            IndexError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            last_errors = [_safe_processing_error(error)]
            LOGGER.error(
                "AI source request or parsing failed on attempt %s: %s",
                attempt,
                last_errors[0],
            )
            continue

        if schema_errors:
            last_errors = schema_errors
            LOGGER.error(
                "AI source response failed schema validation on attempt %s: %s",
                attempt,
                schema_errors,
            )
            continue

        return {
            "ok": True,
            "extractions": response["assessments"],
            "errors": [],
            "attempts": attempt,
        }

    return {
        "ok": False,
        "extractions": [],
        "errors": last_errors,
        "attempts": max_attempts,
    }


def process_record(
    input_record: Dict[str, Any],
    api_caller: Optional[Callable[..., str]] = None,
) -> Dict[str, Any]:
    """Send one record through the AI and return validated extraction data."""
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    base_url = (
        os.getenv("OPENROUTER_BASE_URL", DEFAULT_BASE_URL).strip()
        or DEFAULT_BASE_URL
    )

    if api_caller is None and not api_key:
        return {
            "ok": False,
            "extraction": None,
            "errors": ["OPENROUTER_API_KEY is not configured."],
            "attempts": 0,
        }
    if api_caller is None and base_url.rstrip("/") != DEFAULT_BASE_URL:
        return {
            "ok": False,
            "extraction": None,
            "errors": ["OPENROUTER_BASE_URL must use the official HTTPS endpoint."],
            "attempts": 0,
        }

    caller = api_caller or call_openrouter
    caller_api_key = api_key if api_caller is None else ""
    max_attempts = _read_max_attempts()
    last_errors = ["AI response could not be processed."]

    for attempt in range(1, max_attempts + 1):
        LOGGER.info("AI request attempt %s using model %s", attempt, model)
        try:
            response_text = caller(
                prompt=build_prompt(input_record),
                image_paths=list(input_record.get("image_paths", [])),
                api_key=caller_api_key,
                model=model,
                base_url=base_url,
            )
            extraction = parse_model_response(response_text)
            schema_errors = validate_extraction(extraction)
        except (
            OSError,
            http.client.HTTPException,
            IndexError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            last_errors = [_safe_processing_error(error)]
            LOGGER.error(
                "AI request or parsing failed on attempt %s: %s",
                attempt,
                last_errors[0],
            )
            continue

        if schema_errors:
            last_errors = schema_errors
            LOGGER.error(
                "AI response failed schema validation on attempt %s: %s",
                attempt,
                schema_errors,
            )
            continue

        return {
            "ok": True,
            "extraction": extraction,
            "errors": [],
            "attempts": attempt,
        }

    return {
        "ok": False,
        "extraction": None,
        "errors": last_errors,
        "attempts": max_attempts,
    }


def _read_max_attempts() -> int:
    """Read a small bounded attempt count from local configuration."""
    raw_value = os.getenv("AI_MAX_RETRIES", str(DEFAULT_MAX_ATTEMPTS)).strip()
    try:
        configured_attempts = int(raw_value)
    except ValueError:
        return DEFAULT_MAX_ATTEMPTS
    return max(1, min(configured_attempts, MAX_ALLOWED_ATTEMPTS))


def _safe_processing_error(error: Exception) -> str:
    """Convert transport and parsing failures into non-sensitive messages."""
    if isinstance(error, (ConnectionError, http.client.HTTPException)):
        return "OpenRouter request failed."
    if isinstance(error, OSError):
        return "An assessment image could not be read."
    if isinstance(error, json.JSONDecodeError):
        return "AI response was not valid JSON."
    if isinstance(error, (IndexError, KeyError)):
        return "OpenRouter response shape was invalid."
    return "AI response could not be processed."
