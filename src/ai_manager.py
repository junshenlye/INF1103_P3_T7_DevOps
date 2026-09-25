"""Route module evidence through vision models and normalize one reply."""

import base64
import json
import logging
import os
from pathlib import Path
import re
import time
import uuid

from openai import OpenAI, OpenAIError


LOGGER = logging.getLogger(__name__)
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
PRIMARY_MODEL = "qwen/qwen3-vl-32b-instruct"
BACKUP_MODEL = "qwen/qwen3-vl-8b-instruct"


def extract_assessments(input_data, api_caller=None):
    """Return usable assessments plus comments about unclear evidence."""
    extraction_id = uuid.uuid4().hex[:12]
    module = str(input_data.get("module", "")).strip().upper()
    image_paths = input_data.get("image_paths", [])
    LOGGER.info(
        "ai_ingestion_started extraction_id=%s module=%s image_count=%d",
        extraction_id,
        module,
        len(image_paths),
    )
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if api_caller is None and not api_key:
        LOGGER.warning(
            "ai_ingestion_skipped extraction_id=%s reason=missing_api_key",
            extraction_id,
        )
        return {
            "assessments": [],
            "comments": ["The AI service is not configured, so no schedule was created."],
        }

    caller = api_caller or _call_qwen
    models = _model_route()
    best_result = None
    for attempt, model in enumerate(models, start=1):
        attempt_started = time.monotonic()
        response_mode = "json_schema" if attempt > 1 else "forced_tool"
        LOGGER.info(
            "ai_model_request_started extraction_id=%s model=%s attempt=%d "
            "max_attempts=%d image_count=%d response_mode=%s",
            extraction_id,
            model,
            attempt,
            len(models),
            len(image_paths),
            response_mode,
        )
        try:
            prompt = _build_prompt(input_data)
            if best_result:
                recovered_weight = sum(
                    item["weightage"] or 0
                    for item in best_result["assessments"]
                )
                prompt += (
                    f"\nA previous reading found only {len(best_result['assessments'])} "
                    f"component(s) totalling {recovered_weight:g}%. Re-scan the "
                    "original evidence for anything it missed."
                )
            reply = caller(
                prompt=prompt,
                image_paths=image_paths,
                api_key=api_key if api_caller is None else "",
                model=model,
                structured_output=attempt > 1,
            )
            output_mode = _model_output_mode(reply)
            LOGGER.info(
                "ai_model_output_received extraction_id=%s model=%s attempt=%d "
                "latency_ms=%d output_mode=%s",
                extraction_id,
                model,
                attempt,
                _elapsed_ms(attempt_started),
                output_mode,
            )
            parsed_reply = _parse_reply(reply)
            raw_assessments = parsed_reply.get("assessments", [])
            raw_assessment_count = (
                len(raw_assessments) if isinstance(raw_assessments, list) else 0
            )
            result = _normalize_reply(parsed_reply)
            _log_output_ingestion(
                extraction_id=extraction_id,
                model=model,
                attempt=attempt,
                output_mode=output_mode,
                raw_assessment_count=raw_assessment_count,
                result=result,
            )
            if result["assessments"] or result["comments"]:
                result["model_used"] = model
                if best_result is None or _result_score(result) > _result_score(
                    best_result
                ):
                    best_result = result
                if _has_complete_weight_set(result["assessments"]):
                    _log_ingestion_complete(extraction_id, result, attempt)
                    return result
        except (ConnectionError, OSError, TypeError, ValueError, KeyError) as error:
            LOGGER.warning(
                "ai_model_attempt_failed extraction_id=%s model=%s attempt=%d "
                "latency_ms=%d error_type=%s error=%s",
                extraction_id,
                model,
                attempt,
                _elapsed_ms(attempt_started),
                type(error).__name__,
                _safe_error(error),
            )

    if best_result:
        _log_ingestion_complete(extraction_id, best_result, len(models))
        return best_result
    LOGGER.error(
        "ai_ingestion_failed extraction_id=%s attempted_models=%d",
        extraction_id,
        len(models),
    )
    return {
        "assessments": [],
        "comments": [
            "The AI services did not return a usable reading of the evidence. "
            "No timetable blocks were created."
        ],
    }


def _build_prompt(input_data):
    """Describe universal grouping rules without restricting assessment names."""
    module = input_data["module"].strip().upper()
    context = input_data.get("prompt", "").strip()
    return (
        f"Extract every graded component for module {module} from all supplied "
        "evidence. Assessment names are unrestricted: copy the name shown in "
        "the source, including unfamiliar formats such as placements, studios, "
        "internships, capstones, portfolios, or practical work.\n"
        "Create one assessment when repeated activities share one collective "
        "weightage. Create separate assessments only when the source gives them "
        "separate weights or identifies them as independent graded components. "
        "Scan every image and all extra context end-to-end before responding. "
        "Count the distinct visible weights and make sure every independently "
        "weighted component appears in the assessments array; do not stop after "
        "the first component.\n"
        "Use deadline Week N only when one exact module week is stated. For a "
        "range, recurrence, calendar date, conflict, or missing deadline, use "
        "null. Never guess or divide a shared weightage. Use issues only for "
        "unclear or missing facts, and phrase each issue as an actionable checklist "
        "item explaining what evidence the student should add next. Do not add an "
        "issue when the assessment name, week, grouping, and weight are clear. "
        "Weightage must use percentage points: return 15 for 15%, never 0.15. "
        "Never reject the whole request because one fact is unclear: return every "
        "safe assessment and explain uncertain evidence in comments. Never use "
        "comments to repeat confirmed facts or an assessment's existing issues. "
        "If nothing is "
        "readable, comments must say what part of the assessment material is missing "
        "or illegible. Keep comments short and do not ask the student questions. "
        "Return all visible components, or explain why none can "
        f"be extracted. Extra user context: {context or 'None'}"
    )


def _call_qwen(prompt, image_paths, api_key, model, structured_output=False):
    """Call a Qwen model through OpenRouter's OpenAI-compatible API."""
    request = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Extract academic assessment facts without guessing. "
                    "Turn uncertainty into concise, actionable evidence requests."
                ),
            },
            {"role": "user", "content": _user_content(prompt, image_paths)},
        ],
        "temperature": 0,
        "max_tokens": 4000 if structured_output else 2000,
    }
    if structured_output:
        request["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "module_assessments",
                "strict": True,
                "schema": _extraction_schema(),
            },
        }
    else:
        request["tools"] = [_extraction_tool()]
        request["tool_choice"] = {
            "type": "function",
            "function": {"name": "submit_assessments"},
        }

    base_url = (
        os.getenv("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL).strip()
        or OPENROUTER_BASE_URL
    )
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=90.0,
        max_retries=2,
    )
    request_started = time.monotonic()
    try:
        completion = client.chat.completions.create(**request)
    except OpenAIError as error:
        raise ConnectionError("The Qwen model request failed.") from error

    usage = completion.usage
    first_choice = completion.choices[0] if completion.choices else None
    LOGGER.info(
        "ai_provider_response model=%s response_id=%s latency_ms=%d "
        "finish_reason=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
        model,
        completion.id,
        _elapsed_ms(request_started),
        getattr(first_choice, "finish_reason", None),
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
        getattr(usage, "total_tokens", None),
    )
    if not completion.choices:
        raise ValueError("OpenRouter returned no model message.")
    return completion.choices[0].message.model_dump(exclude_none=True)


def _user_content(prompt, image_paths):
    """Build one multimodal message."""
    content = [{"type": "text", "text": prompt}]
    total_image_bytes = 0
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    for image_path in image_paths:
        path = Path(image_path)
        image_bytes = path.read_bytes()
        total_image_bytes += len(image_bytes)
        encoded = base64.b64encode(image_bytes).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{media_types[path.suffix.lower()]};base64,{encoded}"
                },
            }
        )
    LOGGER.info(
        "ai_input_ingested image_count=%d image_bytes=%d prompt_chars=%d",
        len(image_paths),
        total_image_bytes,
        len(prompt),
    )
    return content


def _extraction_tool():
    """Return the one stable schema used for every assessment format."""
    return {
        "type": "function",
        "function": {
            "name": "submit_assessments",
            "description": "Submit usable assessments and concise evidence comments.",
            "parameters": _extraction_schema(),
        },
    }


def _extraction_schema():
    """Describe generic assessment facts without naming module-specific types."""
    assessment = {
        "type": "object",
        "properties": {
            "assessment_type": {
                "type": "string",
                "description": "The assessment name copied from the evidence.",
            },
            "deadline": {
                "type": ["string", "null"],
                "description": "One exact Week N deadline, otherwise null.",
            },
            "weightage": {
                "type": ["number", "null"],
                "description": (
                    "The total percentage in percentage points: 15 means 15%, "
                    "never 0.15. Use null when unclear."
                ),
            },
            "issues": {
                "type": "array",
                "description": "Actionable evidence requests for unclear facts only.",
                "items": {"type": "string"},
            },
        },
        "required": ["assessment_type", "deadline", "weightage", "issues"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "assessments": {"type": "array", "items": assessment},
            "comments": {
                "type": "array",
                "description": (
                    "Concise explanations of missing, conflicting, or unreadable "
                    "evidence. Do not ask questions."
                ),
                "items": {"type": "string"},
            },
        },
        "required": ["assessments", "comments"],
        "additionalProperties": False,
    }


def _parse_reply(reply):
    """Read tool arguments, plain JSON, or a JSON object inside model text."""
    if isinstance(reply, dict) and "assessments" in reply:
        return reply
    if not isinstance(reply, dict):
        return _json_object(str(reply))

    for tool_call in reply.get("tool_calls", []):
        function = tool_call.get("function", {})
        if function.get("name") == "submit_assessments":
            return _json_object(function.get("arguments", ""))

    content = reply.get("content", "")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return _json_object(content)


def _json_object(text):
    """Return the first complete JSON object found in model text."""
    if not isinstance(text, str):
        raise ValueError("The model response was not text.")
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("The model did not return usable structured data.")


def _normalize_reply(reply):
    """Normalize harmless formatting differences and preserve uncertainty."""
    if not isinstance(reply, dict) or not isinstance(reply.get("assessments"), list):
        raise ValueError("The model result did not contain an assessments list.")

    comment_source = reply.get("comments", reply.get("errors", []))
    comments = [
        str(comment).strip()
        for comment in comment_source
        if str(comment).strip()
    ] if isinstance(comment_source, list) else []
    assessments = []
    for index, item in enumerate(reply["assessments"]):
        if not isinstance(item, dict):
            comments.append(f"Assessment {index + 1} could not be read clearly.")
            continue
        name = str(item.get("assessment_type") or item.get("name") or "").strip()
        if not name:
            comments.append(f"Assessment {index + 1} had no readable name.")
            continue

        issues = _issue_text(item.get("issues", []))
        deadline = item.get("deadline")
        week_match = (
            re.fullmatch(
                r"\s*week\s*([1-9]|[1-4][0-9]|5[0-2])\s*",
                deadline,
                flags=re.IGNORECASE,
            )
            if isinstance(deadline, str)
            else None
        )
        if week_match:
            deadline = f"Week {int(week_match.group(1))}"
        elif deadline is not None:
            issues.append(
                f"Add deadline evidence in Week N format for {name}; found: {deadline}."
            )
            deadline = None

        weightage = item.get("weightage")
        if isinstance(weightage, str):
            try:
                weightage = float(weightage.strip().rstrip("%"))
            except ValueError:
                issues.append(
                    f"Add evidence giving one percentage weight for {name}; found: {weightage}."
                )
                weightage = None
        if isinstance(weightage, bool) or not isinstance(weightage, (int, float)):
            weightage = None
        elif not 0 <= weightage <= 100:
            issues.append(
                f"Add evidence giving a weight from 0% to 100% for {name}."
            )
            weightage = None

        if deadline is None and not any("deadline" in issue.lower() for issue in issues):
            issues.append("Add evidence showing one exact deadline as Week N.")
        if weightage is None and not any("weight" in issue.lower() for issue in issues):
            issues.append("Add evidence showing this assessment's percentage weight.")
        assessments.append(
            {
                "assessment_type": name,
                "deadline": deadline,
                "weightage": weightage,
                "issues": issues,
            }
        )
    _convert_fractional_weight_set(assessments)
    return {"assessments": assessments, "comments": comments}


def _convert_fractional_weight_set(assessments):
    """Convert an obvious 0–1 model weight set into percentage points."""
    weights = [
        assessment["weightage"]
        for assessment in assessments
        if assessment["weightage"] is not None
    ]
    if len(weights) >= 2 and max(weights) <= 1 and 0.99 <= sum(weights) <= 1.01:
        for assessment in assessments:
            if assessment["weightage"] is not None:
                assessment["weightage"] = round(assessment["weightage"] * 100, 4)
        LOGGER.info("Converted fractional model weights to percentage points")


def _has_complete_weight_set(assessments):
    """Recognise a complete module without knowing its assessment types."""
    weights = [
        assessment["weightage"]
        for assessment in assessments
        if assessment.get("weightage") is not None
    ]
    return bool(weights) and 99.5 <= sum(weights) <= 100.5


def _result_score(result):
    """Prefer the route that recovered more usable timetable facts."""
    assessments = result["assessments"]
    known_facts = sum(
        assessment.get("deadline") is not None
        for assessment in assessments
    ) + sum(
        assessment.get("weightage") is not None
        for assessment in assessments
    )
    return len(assessments), known_facts


def _model_output_mode(reply):
    """Describe the response shape without logging model-generated content."""
    if not isinstance(reply, dict):
        return type(reply).__name__
    if "assessments" in reply:
        return "direct_json"
    if reply.get("tool_calls"):
        return "tool_call"
    if reply.get("content"):
        return "message_content"
    return "empty_message"


def _log_output_ingestion(
    extraction_id,
    model,
    attempt,
    output_mode,
    raw_assessment_count,
    result,
):
    """Record normalized output quality without exposing extracted details."""
    assessments = result["assessments"]
    issue_count = sum(len(item["issues"]) for item in assessments)
    known_deadlines = sum(item["deadline"] is not None for item in assessments)
    known_weights = sum(item["weightage"] is not None for item in assessments)
    LOGGER.info(
        "ai_model_output_ingested extraction_id=%s model=%s attempt=%d "
        "output_mode=%s raw_assessment_count=%d assessment_count=%d "
        "discarded_count=%d comment_count=%d issue_count=%d "
        "known_deadline_count=%d known_weight_count=%d complete_weight_set=%s",
        extraction_id,
        model,
        attempt,
        output_mode,
        raw_assessment_count,
        len(assessments),
        max(raw_assessment_count - len(assessments), 0),
        len(result["comments"]),
        issue_count,
        known_deadlines,
        known_weights,
        str(_has_complete_weight_set(assessments)).lower(),
    )


def _log_ingestion_complete(extraction_id, result, attempts):
    """Record the selected route and final ingestion counts."""
    LOGGER.info(
        "ai_ingestion_completed extraction_id=%s selected_model=%s attempts=%d "
        "assessment_count=%d comment_count=%d complete_weight_set=%s",
        extraction_id,
        result.get("model_used"),
        attempts,
        len(result["assessments"]),
        len(result["comments"]),
        str(_has_complete_weight_set(result["assessments"])).lower(),
    )


def _elapsed_ms(started_at):
    """Return a monotonic elapsed time suitable for operational logs."""
    return round((time.monotonic() - started_at) * 1000)


def _issue_text(issues):
    """Reduce model issue objects or strings to user-facing comments."""
    if not isinstance(issues, list):
        return []
    result = []
    for issue in issues:
        if isinstance(issue, str) and issue.strip():
            result.append(issue.strip())
        elif isinstance(issue, dict):
            text = issue.get("feedback") or issue.get("message")
            if isinstance(text, str) and text.strip():
                result.append(text.strip())
    return result


def _model_route():
    """Return one primary model followed by one distinct backup model."""
    primary = os.getenv("OPENROUTER_MODEL", PRIMARY_MODEL).strip() or PRIMARY_MODEL
    backup = os.getenv("OPENROUTER_BACKUP_MODEL", BACKUP_MODEL).strip() or BACKUP_MODEL
    return [primary] if primary == backup else [primary, backup]


def _safe_error(error):
    """Return a short non-sensitive failure message."""
    if isinstance(error, ConnectionError):
        return str(error)
    if isinstance(error, OSError):
        return "An uploaded image could not be read."
    return str(error) or "The model response could not be processed."
