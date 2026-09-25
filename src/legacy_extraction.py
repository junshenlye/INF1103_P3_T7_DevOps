"""Compatibility path for the original one-module assessment workflow.

The active application uses :mod:`src.ai_manager`. This module keeps the old
request and response contract available without mixing its schema into the
multi-module pacing flow.
"""

import logging
import os
import re

from openai import OpenAI, OpenAIError

from .ai_support import (
    DASHSCOPE_BASE_URL,
    build_user_content,
    model_route,
    parse_json_object,
    safe_error,
)
from .system_prompts import LEGACY_SYSTEM_PROMPT, build_legacy_prompt


LOGGER = logging.getLogger(__name__)


def extract_assessments(input_data, api_caller=None):
    """Return assessments using the former one-module response contract."""
    module = str(input_data.get("module", "")).strip().upper()
    image_paths = input_data.get("image_paths", [])
    LOGGER.info(
        "Starting legacy assessment extraction for %s with %d image(s)",
        module,
        len(image_paths),
    )
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if api_caller is None and not api_key:
        return {
            "assessments": [],
            "comments": ["The AI service is not configured, so no schedule was created."],
        }

    caller = api_caller or _call_qwen
    models = model_route()
    best_result = None
    for attempt, model in enumerate(models, start=1):
        try:
            prompt = build_legacy_prompt(input_data)
            if best_result:
                recovered_weight = sum(
                    item["weightage"] or 0 for item in best_result["assessments"]
                )
                prompt += (
                    f"\nA previous reading found {len(best_result['assessments'])} "
                    f"component(s) totalling {recovered_weight:g}%. Re-scan the "
                    "evidence for anything it missed."
                )
            reply = caller(
                prompt=prompt,
                image_paths=image_paths,
                api_key=api_key if api_caller is None else "",
                model=model,
                structured_output=attempt > 1,
            )
            result = _normalize_reply(_parse_reply(reply))
            if result["assessments"] or result["comments"]:
                result["model_used"] = model
                if best_result is None or _result_score(result) > _result_score(
                    best_result
                ):
                    best_result = result
                if _has_complete_weight_set(result["assessments"]):
                    return result
        except (ConnectionError, OSError, TypeError, ValueError, KeyError) as error:
            LOGGER.warning(
                "Legacy AI model %s failed on attempt %d: %s",
                model,
                attempt,
                safe_error(error),
            )

    if best_result:
        return best_result
    return {
        "assessments": [],
        "comments": [
            "The AI services did not return a usable reading of the evidence. "
            "No timetable blocks were created."
        ],
    }


def _call_qwen(prompt, image_paths, api_key, model, structured_output=False):
    """Call Qwen through Alibaba Model Studio's OpenAI-compatible API."""
    request = {
        "model": model,
        "messages": [
            {"role": "system", "content": LEGACY_SYSTEM_PROMPT},
            {"role": "user", "content": build_user_content(prompt, image_paths)},
        ],
        "temperature": 0,
        "max_tokens": 4000 if structured_output else 2000,
        "extra_body": {"enable_thinking": False},
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

    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("DASHSCOPE_BASE_URL", DASHSCOPE_BASE_URL).strip()
        or DASHSCOPE_BASE_URL,
        timeout=90.0,
        max_retries=2,
    )
    try:
        completion = client.chat.completions.create(**request)
    except OpenAIError as error:
        status = getattr(error, "status_code", None)
        status_text = f" (HTTP {status})" if status else ""
        raise ConnectionError(
            f"Alibaba Model Studio request failed{status_text}: {error}"
        ) from error
    if not completion.choices:
        raise ValueError("Alibaba Model Studio returned no model message.")
    return completion.choices[0].message.model_dump(exclude_none=True)


def _extraction_tool():
    return {
        "type": "function",
        "function": {
            "name": "submit_assessments",
            "description": "Submit usable assessments and concise evidence comments.",
            "parameters": _extraction_schema(),
        },
    }


def _extraction_schema():
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
                "description": "Percentage points: 15 means 15%, never 0.15.",
            },
            "issues": {
                "type": "array",
                "description": "Evidence requests for unclear facts only.",
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
                "items": {"type": "string"},
            },
        },
        "required": ["assessments", "comments"],
        "additionalProperties": False,
    }


def _parse_reply(reply):
    if isinstance(reply, dict) and "assessments" in reply:
        return reply
    if not isinstance(reply, dict):
        return parse_json_object(str(reply))
    for tool_call in reply.get("tool_calls", []):
        function = tool_call.get("function", {})
        if function.get("name") == "submit_assessments":
            return parse_json_object(function.get("arguments", ""))
    content = reply.get("content", "")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return parse_json_object(content)


def _normalize_reply(reply):
    if not isinstance(reply, dict) or not isinstance(reply.get("assessments"), list):
        raise ValueError("The model result did not contain an assessments list.")

    comment_source = reply.get("comments", reply.get("errors", []))
    comments = (
        [str(comment).strip() for comment in comment_source if str(comment).strip()]
        if isinstance(comment_source, list)
        else []
    )
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
                issues.append(f"Add one percentage weight for {name}.")
                weightage = None
        if isinstance(weightage, bool) or not isinstance(weightage, (int, float)):
            weightage = None
        elif not 0 <= weightage <= 100:
            issues.append(f"Add a weight from 0% to 100% for {name}.")
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
    weights = [
        assessment["weightage"]
        for assessment in assessments
        if assessment["weightage"] is not None
    ]
    if len(weights) >= 2 and max(weights) <= 1 and 0.99 <= sum(weights) <= 1.01:
        for assessment in assessments:
            if assessment["weightage"] is not None:
                assessment["weightage"] = round(assessment["weightage"] * 100, 4)


def _has_complete_weight_set(assessments):
    weights = [
        assessment["weightage"]
        for assessment in assessments
        if assessment.get("weightage") is not None
    ]
    return bool(weights) and 99.5 <= sum(weights) <= 100.5


def _result_score(result):
    assessments = result["assessments"]
    known_facts = sum(
        assessment.get("deadline") is not None for assessment in assessments
    ) + sum(assessment.get("weightage") is not None for assessment in assessments)
    return len(assessments), known_facts


def _issue_text(issues):
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
