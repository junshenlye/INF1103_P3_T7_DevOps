"""Send module evidence to Nemotron and normalize its structured reply."""

import base64
import http.client
import json
import logging
import os
from pathlib import Path
import re
import ssl


LOGGER = logging.getLogger(__name__)
MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"


def extract_assessments(input_data, api_caller=None, progress_callback=None):
    """Return every extracted assessment or a short list of errors."""
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model = os.getenv("OPENROUTER_MODEL", MODEL).strip() or MODEL
    if api_caller is None and not api_key:
        return {"assessments": [], "errors": ["OPENROUTER_API_KEY is missing."]}

    caller = api_caller or _call_openrouter
    attempts = _attempt_count()
    last_error = "The model could not process this evidence."
    for attempt in range(1, attempts + 1):
        _progress(
            progress_callback,
            "ai_request",
            "Nemotron is reading the module evidence.",
            attempt=attempt,
            max_attempts=attempts,
        )
        try:
            reply = caller(
                prompt=_build_prompt(input_data),
                image_paths=input_data.get("image_paths", []),
                api_key=api_key if api_caller is None else "",
                model=model,
            )
            _progress(
                progress_callback,
                "ai_validation",
                "Nemotron replied; checking the structured result.",
                attempt=attempt,
                max_attempts=attempts,
            )
            result = _normalize_reply(_parse_reply(reply))
            if result["assessments"] or result["errors"]:
                _progress(
                    progress_callback,
                    "ai_complete",
                    f"Received {len(result['assessments'])} assessment(s).",
                    attempt=attempt,
                    max_attempts=attempts,
                    event_count=len(result["assessments"]),
                )
                return result
            last_error = "The model returned no assessments or explanation."
        except (ConnectionError, OSError, TypeError, ValueError, KeyError) as error:
            last_error = _safe_error(error)
            LOGGER.warning("Nemotron attempt %s failed: %s", attempt, last_error)

        _progress(
            progress_callback,
            "retrying" if attempt < attempts else "failed",
            last_error,
            attempt=attempt,
            max_attempts=attempts,
        )
    return {"assessments": [], "errors": [last_error]}


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
        "separate weights or identifies them as independent graded components.\n"
        "Use deadline Week N only when one exact module week is stated. For a "
        "range, recurrence, calendar date, conflict, or missing deadline, use "
        "null and explain the source wording in issues. Never guess or divide a "
        "shared weightage. Return all visible components, or explain why none can "
        f"be extracted. Extra user context: {context or 'None'}"
    )


def _call_openrouter(prompt, image_paths, api_key, model):
    """Call OpenRouter and return its assistant message."""
    request_body = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Extract academic assessment facts without guessing.",
                },
                {"role": "user", "content": _user_content(prompt, image_paths)},
            ],
            "tools": [_extraction_tool()],
            "tool_choice": {
                "type": "function",
                "function": {"name": "submit_assessments"},
            },
            "reasoning": {"enabled": False},
            "temperature": 0,
            "max_tokens": 2000,
        }
    ).encode("utf-8")
    connection = http.client.HTTPSConnection(
        "openrouter.ai",
        timeout=90,
        context=ssl.create_default_context(),
    )
    try:
        connection.request(
            "POST",
            "/api/v1/chat/completions",
            body=request_body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
    except (OSError, http.client.HTTPException, json.JSONDecodeError) as error:
        raise ConnectionError("OpenRouter request failed.") from error
    finally:
        connection.close()

    if not 200 <= response.status < 300 or payload.get("error"):
        raise ConnectionError("OpenRouter could not serve the model request.")
    choices = payload.get("choices")
    if not choices or not isinstance(choices[0].get("message"), dict):
        raise ValueError("OpenRouter returned no model message.")
    return choices[0]["message"]


def _user_content(prompt, image_paths):
    """Build one multimodal message."""
    content = [{"type": "text", "text": prompt}]
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    for image_path in image_paths:
        path = Path(image_path)
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{media_types[path.suffix.lower()]};base64,{encoded}"
                },
            }
        )
    return content


def _extraction_tool():
    """Return the one stable schema used for every assessment format."""
    assessment = {
        "type": "object",
        "properties": {
            "assessment_type": {"type": "string"},
            "deadline": {"type": ["string", "null"]},
            "weightage": {"type": ["number", "null"]},
            "issues": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["assessment_type", "deadline", "weightage", "issues"],
        "additionalProperties": False,
    }
    return {
        "type": "function",
        "function": {
            "name": "submit_assessments",
            "description": "Submit every extracted assessment or extraction error.",
            "parameters": {
                "type": "object",
                "properties": {
                    "assessments": {"type": "array", "items": assessment},
                    "errors": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["assessments", "errors"],
                "additionalProperties": False,
            },
        },
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

    errors = [str(error) for error in reply.get("errors", []) if str(error).strip()]
    assessments = []
    for index, item in enumerate(reply["assessments"]):
        if not isinstance(item, dict):
            errors.append(f"Assessment {index + 1} was not structured correctly.")
            continue
        name = str(item.get("assessment_type") or item.get("name") or "").strip()
        if not name:
            errors.append(f"Assessment {index + 1} had no name.")
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
            issues.append(f"Deadline needs review: {deadline}")
            deadline = None

        weightage = item.get("weightage")
        if isinstance(weightage, str):
            try:
                weightage = float(weightage.strip().rstrip("%"))
            except ValueError:
                issues.append(f"Weightage needs review: {weightage}")
                weightage = None
        if isinstance(weightage, bool) or not isinstance(weightage, (int, float)):
            weightage = None
        elif not 0 <= weightage <= 100:
            issues.append(f"Weightage needs review: {weightage}")
            weightage = None

        if deadline is None and not any("deadline" in issue.lower() for issue in issues):
            issues.append("Deadline was not found as one exact module week.")
        if weightage is None and not any("weight" in issue.lower() for issue in issues):
            issues.append("Weightage was not found.")
        assessments.append(
            {
                "assessment_type": name,
                "deadline": deadline,
                "weightage": weightage,
                "issues": issues,
            }
        )
    return {"assessments": assessments, "errors": errors}


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


def _attempt_count():
    """Keep free-model retries deliberately small."""
    try:
        return max(1, min(int(os.getenv("AI_MAX_RETRIES", "2")), 2))
    except ValueError:
        return 2


def _safe_error(error):
    """Return a short non-sensitive failure message."""
    if isinstance(error, ConnectionError):
        return str(error)
    if isinstance(error, OSError):
        return "An uploaded image could not be read."
    return str(error) or "The model response could not be processed."


def _progress(callback, stage, message, **details):
    """Send optional progress without coupling the manager to Flask."""
    if callback:
        try:
            callback({"stage": stage, "message": message, **details})
        except Exception:
            LOGGER.warning("Progress callback failed and was ignored")
