"""Send assessment evidence to an AI model and normalize its replies.

The active API extracts each module independently. ``extract_assessments``
keeps the original one-module API available for callers that still use it.
Transport, prompts, schemas, parsing, and normalization live together here so
both paths share one small set of model-facing helpers.
"""

import asyncio
import base64
import inspect
import json
import logging
import os
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree

from openai import AsyncOpenAI, OpenAIError


LOGGER = logging.getLogger(__name__)

DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
PRIMARY_MODEL = "qwen3.7-plus"
BACKUP_MODEL = "qwen3.7-flash"
SUPPORTED_IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
MAX_DOCUMENT_CHARS = 12_000
DEFAULT_CONCURRENT_REQUESTS = 5
MAX_CONCURRENT_REQUESTS = 8

PACING_SYSTEM_PROMPT = """Extract academic assessment facts into the supplied JSON schema.

Rules:
- Never invent dates, weeks, weights, recurrence, credits, or assessment status.
- Do not give study advice or calculate priority, pressure, or relative scores.
- Return partial facts when evidence is incomplete; use null for unknown fields.
- Keep feedback compact: one missing-information item per assessment and no more
  than three checklist items for the module. Do not repeat the same issue.
- Participation, attendance, tutorial engagement, and student engagement are
  participation assessments, not assignments.
- A percentage covering repeated participation is the total trimester weight.
  Use per_occurrence only when the source explicitly says each occurrence has
  that weight.
- Return JSON only. Use a hard error only when the request cannot be processed.
"""

LEGACY_SYSTEM_PROMPT = """Extract academic assessment facts without guessing.
Return every reliable fact and turn uncertainty into concise evidence requests.
"""


# Active multi-module API


def process(input_data, trimester_context, api_caller=None):
    """Synchronous entry point for the current Flask request path."""
    _require_no_running_loop("process", "process_async")
    return asyncio.run(process_async(input_data, trimester_context, api_caller))


async def process_async(input_data, trimester_context, api_caller=None):
    """Extract modules as concurrent network tasks, preserving input order."""
    requested_modules = input_data.get("modules", [])
    if not requested_modules:
        return _assemble_result([], [], [], [], [])

    request_limit = _concurrent_request_limit(len(requested_modules))
    LOGGER.info(
        "Extracting %d module(s) with up to %d concurrent request(s)",
        len(requested_modules),
        request_limit,
    )
    request_slots = asyncio.Semaphore(request_limit)
    results = await asyncio.gather(
        *(
            _extract_module(
                module,
                trimester_context,
                api_caller,
                request_slots,
            )
            for module in requested_modules
        )
    )

    modules = [result["module"] for result in results]
    global_comments = [
        comment
        for result in results
        for comment in result.get("global_comments", [])
    ]
    checklist = [
        item
        for result in results
        for item in result.get("user_checklist", [])
    ]
    models_used = [
        result["model_used"] for result in results if result.get("model_used")
    ]
    return _assemble_result(
        modules,
        requested_modules,
        global_comments,
        checklist,
        models_used,
    )


def validate_ai_output(ai_result, expected_modules=None):
    """Normalize an externally supplied active result.

    ``process`` already normalizes each module and therefore skips this public
    compatibility boundary. Keeping the paths separate prevents every live
    response from being normalized twice.
    """
    if not isinstance(ai_result, dict):
        raise ValueError("AI output must be an object.")

    expected_by_name = _modules_by_name(expected_modules or [])
    modules = []
    global_comments = _text_list(ai_result.get("global_comments"))
    for raw_module in _list_or_empty(ai_result.get("modules")):
        if not isinstance(raw_module, dict):
            global_comments.append(
                "One module result was malformed and could not be used."
            )
            continue
        name = _module_name(raw_module)
        if not name:
            global_comments.append("One module result had no module reference.")
            continue
        supplied = expected_by_name.get(
            name,
            {"module_name": name, "credit_units": None},
        )
        modules.append(_normalize_module_result(raw_module, supplied)["module"])

    return _assemble_result(
        modules,
        expected_modules or [],
        global_comments,
        _text_list(ai_result.get("user_checklist")),
        _text_list(ai_result.get("models_used")),
    )


def _assemble_result(
    modules,
    expected_modules,
    global_comments,
    checklist,
    models_used,
):
    """Add cross-module feedback without re-normalizing module contents."""
    expected_by_name = _modules_by_name(expected_modules)
    result_modules = list(modules)
    found = {_module_name(module) for module in result_modules}

    for module in result_modules:
        if module.get("credit_units") is None:
            checklist.append(
                f"{module['module_name']}: Provide the module credit units."
            )

    for name, supplied in expected_by_name.items():
        if name not in found:
            result_modules.append(
                _empty_module_result(
                    supplied,
                    "No AI result was returned for this module.",
                )
            )
            checklist.append(f"{name}: Provide clearer assessment information.")

    return {
        "modules": result_modules,
        "global_comments": _unique_text(global_comments),
        "user_checklist": _unique_text(checklist)[:10],
        "models_used": _unique_text(models_used),
    }


# Per-module extraction and evidence


def _concurrent_request_limit(module_count):
    try:
        configured = int(
            os.getenv(
                "AI_MAX_CONCURRENT_REQUESTS",
                os.getenv(
                    "AI_MAX_PARALLEL_MODULES",
                    str(DEFAULT_CONCURRENT_REQUESTS),
                ),
            )
        )
    except ValueError:
        configured = DEFAULT_CONCURRENT_REQUESTS
    return max(1, min(module_count, configured, MAX_CONCURRENT_REQUESTS))


async def _extract_module(module, trimester_context, api_caller, request_slots):
    module_name = module["module_name"]
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if api_caller is None and not api_key:
        return {
            "module": _empty_module_result(
                module,
                "The AI service is not configured, so assessment evidence was not extracted.",
            ),
            "global_comments": [],
            "user_checklist": [
                f"Configure the AI service to extract assessment details for {module_name}."
            ],
        }

    prompt, document_comments = _build_pacing_prompt(module, trimester_context)
    image_paths = [
        path
        for path in module.get("files", [])
        if Path(path).suffix.lower() in SUPPORTED_IMAGE_TYPES
    ]
    caller = api_caller or _call_pacing_model
    best_result = None
    for attempt, model in enumerate(_model_route(), start=1):
        try:
            async with request_slots:
                reply = await _invoke_caller(
                    caller,
                    prompt=prompt,
                    image_paths=image_paths,
                    api_key=api_key if api_caller is None else "",
                    model=model,
                    structured_output=attempt > 1,
                )
            parsed = _parse_model_reply(
                reply,
                tool_name="submit_module_facts",
                module_name=module_name,
            )
            result = _normalize_module_result(parsed, module)
            result["module"]["comments"] = _unique_text(
                result["module"]["comments"] + document_comments
            )
            result["model_used"] = model
            if best_result is None or _result_score(
                result["module"]["assessments"],
                weight_key="weightage_percent",
                timing_key="due_week",
            ) > _result_score(
                best_result["module"]["assessments"],
                weight_key="weightage_percent",
                timing_key="due_week",
            ):
                best_result = result
            if result["module"]["assessments"]:
                return result
        except (ConnectionError, OSError, TypeError, ValueError, KeyError) as error:
            LOGGER.warning(
                "Pacing extraction failed for %s via %s: %s",
                module_name,
                model,
                _safe_error(error),
            )

    if best_result:
        return best_result
    return {
        "module": _empty_module_result(
            module,
            "The AI service did not return usable structured assessment information.",
        ),
        "global_comments": [],
        "user_checklist": [
            f"Provide clearer assessment information for {module_name}."
        ],
    }


def _build_pacing_prompt(module, trimester_context):
    document_parts = []
    comments = []
    remaining_chars = MAX_DOCUMENT_CHARS
    for file_path in module.get("files", []):
        path = Path(file_path)
        if path.suffix.lower() in SUPPORTED_IMAGE_TYPES:
            continue
        try:
            text = _read_document_text(path)
            if not text.strip():
                comments.append(f"{path.name} did not contain readable text.")
                continue
            excerpt = text[:remaining_chars]
            if excerpt:
                document_parts.append(f"--- {path.name} ---\n{excerpt}")
                remaining_chars -= len(excerpt)
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
            LOGGER.warning(
                "Could not read uploaded document %s: %s",
                path.name,
                _safe_error(error),
            )
            comments.append(f"{path.name} could not be read as assessment evidence.")

    return (
        _format_pacing_prompt(
            module,
            trimester_context,
            "\n".join(document_parts),
        ),
        comments,
    )


def _read_document_text(path):
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".json"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise RuntimeError("PDF support is unavailable") from error
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    if suffix == ".docx":
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        return "\n".join(text for text in root.itertext() if text.strip())
    raise ValueError("Unsupported document type")


def _format_pacing_prompt(module, trimester_context, document_text):
    calendar_fields = ("week", "start_date", "end_date", "label")
    calendar = [
        {key: item[key] for key in calendar_fields}
        for item in trimester_context.get("weeks", [])
    ]
    return (
        "Extract every graded assessment from this module. Recognise quizzes, "
        "assignments, projects, reports, presentations, labs, practicals, "
        "midterms, final exams, and participation. Exclude make-up/replacement "
        "tests, optional activities, practice, and formative work unless clearly "
        "graded for this student. Keep items sharing one weight together. Split "
        "only independently weighted items. For recurring work, give exact weeks "
        "when known. For multi-week work, give start and end weeks. A weight of "
        "30 means 30%. Preserve supplied credits and use ISO YYYY-MM-DD dates.\n\n"
        f"Module: {module['module_name']}\n"
        f"Credit units: {module.get('credit_units')}\n"
        f"Additional context: {module.get('additional_context') or 'None'}\n"
        f"Trimester calendar: {json.dumps(calendar, separators=(',', ':'))}\n"
        f"Document text:\n{document_text or 'None; inspect supplied images.'}"
    )


# Shared model request and response contract


async def _call_pacing_model(
    prompt, image_paths, api_key, model, structured_output=False
):
    return await _call_model(
        prompt=prompt,
        image_paths=image_paths,
        api_key=api_key,
        model=model,
        structured_output=structured_output,
        system_prompt=PACING_SYSTEM_PROMPT,
        tool_name="submit_module_facts",
        tool_description="Submit extracted module assessment facts.",
        schema_name="module_pacing_facts",
        schema=_pacing_schema(),
        max_tokens=2_500,
    )


async def _call_legacy_model(
    prompt, image_paths, api_key, model, structured_output=False
):
    return await _call_model(
        prompt=prompt,
        image_paths=image_paths,
        api_key=api_key,
        model=model,
        structured_output=structured_output,
        system_prompt=LEGACY_SYSTEM_PROMPT,
        tool_name="submit_assessments",
        tool_description="Submit usable assessments and concise evidence comments.",
        schema_name="module_assessments",
        schema=_legacy_schema(),
        max_tokens=4_000 if structured_output else 2_000,
    )


async def _call_model(
    *,
    prompt,
    image_paths,
    api_key,
    model,
    structured_output,
    system_prompt,
    tool_name,
    tool_description,
    schema_name,
    schema,
    max_tokens,
):
    request = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _build_user_content(prompt, image_paths)},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "extra_body": {"enable_thinking": False},
    }
    if structured_output:
        request["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        }
    else:
        request["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_description,
                    "parameters": schema,
                },
            }
        ]
        request["tool_choice"] = {
            "type": "function",
            "function": {"name": tool_name},
        }

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=os.getenv("DASHSCOPE_BASE_URL", DASHSCOPE_BASE_URL).strip()
        or DASHSCOPE_BASE_URL,
        timeout=90.0,
        max_retries=2,
    )
    try:
        completion = await client.chat.completions.create(**request)
    except OpenAIError as error:
        status = getattr(error, "status_code", None)
        status_text = f" (HTTP {status})" if status else ""
        raise ConnectionError(
            f"Alibaba Model Studio request failed{status_text}: {error}"
        ) from error
    finally:
        await client.close()
    if not completion.choices:
        raise ValueError("Alibaba Model Studio returned no model message.")

    usage = getattr(completion, "usage", None)
    if usage is not None:
        LOGGER.info(
            "%s token usage: input=%s output=%s total=%s",
            model,
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None),
            getattr(usage, "total_tokens", None),
        )
    return completion.choices[0].message.model_dump(exclude_none=True)


def _build_user_content(prompt, image_paths):
    content = [{"type": "text", "text": prompt}]
    for image_path in image_paths:
        path = Path(image_path)
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": (
                        f"data:{IMAGE_MEDIA_TYPES[path.suffix.lower()]};base64,"
                        f"{encoded}"
                    )
                },
            }
        )
    return content


def _parse_model_reply(reply, *, tool_name, module_name=None):
    if isinstance(reply, dict) and "assessments" in reply:
        return reply
    if isinstance(reply, dict) and isinstance(reply.get("modules"), list):
        candidates = [item for item in reply["modules"] if isinstance(item, dict)]
        selected = next(
            (
                item
                for item in candidates
                if _module_name(item) == _clean_name(module_name)
            ),
            candidates[0] if candidates else None,
        )
        if selected is not None:
            return {
                **selected,
                "global_comments": reply.get("global_comments", []),
                "user_checklist": reply.get("user_checklist", []),
            }
    if not isinstance(reply, dict):
        return _parse_json_object(str(reply))
    for tool_call in _list_or_empty(reply.get("tool_calls")):
        function = (
            tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
        )
        if function.get("name") == tool_name:
            return _parse_json_object(function.get("arguments", ""))
    content = reply.get("content", "")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return _parse_json_object(content)


def _parse_json_object(text):
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


def _strict_object(properties, *, required=None):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else list(required),
        "additionalProperties": False,
    }


def _string_list(max_items=None):
    schema = {"type": "array", "items": {"type": "string"}}
    if max_items is not None:
        schema["maxItems"] = max_items
    return schema


def _pacing_schema():
    nullable_number = {"type": ["number", "null"]}
    nullable_integer = {"type": ["integer", "null"]}
    nullable_string = {"type": ["string", "null"]}
    recurrence = _strict_object(
        {
            "frequency": nullable_string,
            "weeks": {"type": "array", "items": {"type": "integer"}},
            "start_week": nullable_integer,
            "end_week": nullable_integer,
            "every_n_weeks": nullable_integer,
        }
    )
    recurrence["type"] = ["object", "null"]
    assessment = _strict_object(
        {
            "name": {"type": "string"},
            "type": {"type": "string"},
            "weightage_percent": nullable_number,
            "weightage_scope": {
                "type": "string",
                "enum": ["total", "per_occurrence", "unknown"],
            },
            "due_date": nullable_string,
            "due_week": nullable_integer,
            "recurring": {"type": "boolean"},
            "recurrence": recurrence,
            "spans_multiple_weeks": {"type": "boolean"},
            "start_week": nullable_integer,
            "end_week": nullable_integer,
            "confidence": nullable_number,
            "comments": _string_list(1),
            "missing_information": _string_list(1),
            "assumptions": _string_list(1),
        }
    )
    return _strict_object(
        {
            "module_name": {"type": "string"},
            "credit_units": nullable_number,
            "assessments": {"type": "array", "items": assessment},
            "comments": _string_list(3),
            "global_comments": _string_list(3),
            "user_checklist": _string_list(3),
        }
    )


def _legacy_schema():
    assessment = _strict_object(
        {
            "assessment_type": {"type": "string"},
            "deadline": {"type": ["string", "null"]},
            "weightage": {"type": ["number", "null"]},
            "issues": _string_list(),
        }
    )
    return _strict_object(
        {
            "assessments": {"type": "array", "items": assessment},
            "comments": _string_list(),
        }
    )


# Active normalization


def _normalize_module_result(reply, supplied_module):
    if not isinstance(reply, dict):
        raise ValueError("The model result was not an object.")

    raw_assessments = reply.get("assessments", [])
    comments = _text_list(reply.get("comments"))
    if not isinstance(raw_assessments, list):
        comments.append("The model result did not contain a readable assessment list.")
        raw_assessments = []

    assessments = []
    for index, raw in enumerate(raw_assessments, start=1):
        if not isinstance(raw, dict):
            comments.append(f"Assessment {index} could not be interpreted.")
            continue
        name = str(raw.get("name") or raw.get("assessment_type") or "").strip()
        if not name:
            comments.append(f"Assessment {index} has no readable title.")
            continue

        weight = _number_or_none(
            raw.get("weightage_percent", raw.get("weightage"))
        )
        item_comments = _text_list(raw.get("comments"))
        missing = _text_list(raw.get("missing_information"))[:1]
        if weight is not None and not 0 <= weight <= 100:
            item_comments.append(
                f"The reported weightage for {name} is outside 0–100%."
            )
            missing = ["Valid assessment weightage"]
            weight = None

        due_week = _week_or_none(raw.get("due_week"))
        if due_week is None:
            due_week = _week_from_deadline(raw.get("deadline"))

        recurrence = _normalize_recurrence(raw.get("recurrence"))
        confidence = _number_or_none(raw.get("confidence"))
        if confidence is not None:
            confidence = min(max(confidence, 0), 1)
        raw_scope = str(raw.get("weightage_scope") or "").strip().lower()

        assessments.append(
            {
                "name": name,
                "type": str(raw.get("type") or "assessment").strip().lower(),
                "weightage_percent": weight,
                "weightage_scope": (
                    raw_scope
                    if raw_scope in {"total", "per_occurrence"}
                    else "total"
                ),
                "due_date": str(raw.get("due_date") or "").strip() or None,
                "due_week": due_week,
                "recurring": bool(raw.get("recurring", False)),
                "recurrence": recurrence,
                "spans_multiple_weeks": bool(raw.get("spans_multiple_weeks", False)),
                "start_week": _week_or_none(raw.get("start_week")),
                "end_week": _week_or_none(raw.get("end_week")),
                "confidence": confidence,
                "comments": _unique_text(item_comments),
                "missing_information": _unique_text(missing),
                "assumptions": _unique_text(_text_list(raw.get("assumptions")))[:1],
            }
        )

    _convert_fractional_weights(assessments, "weightage_percent")
    supplied_credits = supplied_module.get("credit_units")
    credits = (
        supplied_credits
        if supplied_credits is not None
        else _number_or_none(reply.get("credit_units"))
    )
    return {
        "module": {
            "module_name": supplied_module["module_name"],
            "credit_units": credits,
            "assessments": assessments,
            "comments": _unique_text(comments),
        },
        "global_comments": _text_list(reply.get("global_comments"))[:3],
        "user_checklist": _text_list(reply.get("user_checklist"))[:3],
    }


def _normalize_recurrence(value):
    if not isinstance(value, dict):
        return None
    return {
        "frequency": str(value.get("frequency") or "").strip() or None,
        "weeks": [
            week
            for week in (
                _week_or_none(item)
                for item in _list_or_empty(value.get("weeks"))
            )
            if week is not None
        ],
        "start_week": _week_or_none(value.get("start_week")),
        "end_week": _week_or_none(value.get("end_week")),
        "every_n_weeks": _week_or_none(value.get("every_n_weeks")),
    }


# Legacy one-module compatibility API


def extract_assessments(input_data, api_caller=None):
    """Synchronous entry point for the original one-module request path."""
    _require_no_running_loop("extract_assessments", "extract_assessments_async")
    return asyncio.run(extract_assessments_async(input_data, api_caller))


async def extract_assessments_async(input_data, api_caller=None):
    """Return assessments using the original one-module response contract."""
    module = _clean_name(input_data.get("module"))
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

    caller = api_caller or _call_legacy_model
    best_result = None
    for attempt, model in enumerate(_model_route(), start=1):
        try:
            prompt = _format_legacy_prompt(input_data)
            if best_result:
                recovered_weight = sum(
                    item["weightage"] or 0 for item in best_result["assessments"]
                )
                prompt += (
                    f"\nA previous reading found {len(best_result['assessments'])} "
                    f"component(s) totalling {recovered_weight:g}%. Re-scan the "
                    "evidence for anything it missed."
                )
            reply = await _invoke_caller(
                caller,
                prompt=prompt,
                image_paths=image_paths,
                api_key=api_key if api_caller is None else "",
                model=model,
                structured_output=attempt > 1,
            )
            result = _normalize_legacy_reply(
                _parse_model_reply(reply, tool_name="submit_assessments")
            )
            if result["assessments"] or result["comments"]:
                result["model_used"] = model
                if best_result is None or _result_score(
                    result["assessments"],
                    weight_key="weightage",
                    timing_key="deadline",
                ) > _result_score(
                    best_result["assessments"],
                    weight_key="weightage",
                    timing_key="deadline",
                ):
                    best_result = result
                if _has_complete_weight_set(result["assessments"]):
                    return result
        except (ConnectionError, OSError, TypeError, ValueError, KeyError) as error:
            LOGGER.warning(
                "Legacy AI model %s failed on attempt %d: %s",
                model,
                attempt,
                _safe_error(error),
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


def _format_legacy_prompt(input_data):
    context = str(input_data.get("prompt", "")).strip()
    return (
        f"Extract every graded component for module {_clean_name(input_data['module'])} "
        "from all evidence. Copy source names, including unfamiliar assessment "
        "formats. Keep repeated activities together when they share one collective "
        "weight; split only independently weighted components. Scan all evidence "
        "before responding. Use deadline Week N only for one exact stated week; "
        "otherwise use null. Never guess or divide a shared weight. A weight of "
        "15% must be returned as 15, not 0.15. Return all reliable components even "
        "when some facts are unclear. Keep comments and actionable evidence requests "
        "short, and do not repeat confirmed facts. "
        f"Additional context: {context or 'None'}"
    )


def _normalize_legacy_reply(reply):
    if not isinstance(reply, dict) or not isinstance(reply.get("assessments"), list):
        raise ValueError("The model result did not contain an assessments list.")

    comments = _text_list(reply.get("comments", reply.get("errors", [])))
    assessments = []
    for index, item in enumerate(reply["assessments"], start=1):
        if not isinstance(item, dict):
            comments.append(f"Assessment {index} could not be read clearly.")
            continue
        name = str(item.get("assessment_type") or item.get("name") or "").strip()
        if not name:
            comments.append(f"Assessment {index} had no readable name.")
            continue

        issues = _issue_text(item.get("issues"))
        deadline = item.get("deadline")
        due_week = _week_from_deadline(deadline, maximum=52)
        if due_week is not None:
            deadline = f"Week {due_week}"
        elif deadline is not None:
            issues.append(
                f"Add deadline evidence in Week N format for {name}; found: {deadline}."
            )
            deadline = None

        weight = _number_or_none(item.get("weightage"))
        if weight is None:
            if item.get("weightage") not in (None, ""):
                issues.append(f"Add one percentage weight for {name}.")
        elif not 0 <= weight <= 100:
            issues.append(f"Add a weight from 0% to 100% for {name}.")
            weight = None
        if deadline is None and not _contains_word(issues, "deadline"):
            issues.append("Add evidence showing one exact deadline as Week N.")
        if weight is None and not _contains_word(issues, "weight"):
            issues.append("Add evidence showing this assessment's percentage weight.")

        assessments.append(
            {
                "assessment_type": name,
                "deadline": deadline,
                "weightage": weight,
                "issues": _unique_text(issues),
            }
        )

    _convert_fractional_weights(assessments, "weightage")
    return {"assessments": assessments, "comments": _unique_text(comments)}


# Small shared helpers


async def _invoke_caller(caller, **arguments):
    """Accept native async callers while retaining simple synchronous test fakes."""
    result = caller(**arguments)
    return await result if inspect.isawaitable(result) else result


def _require_no_running_loop(sync_name, async_name):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RuntimeError(
        f"{sync_name} cannot run inside an active event loop; await {async_name} instead."
    )


def _empty_module_result(module, comment):
    return {
        "module_name": module["module_name"],
        "credit_units": module.get("credit_units"),
        "assessments": [],
        "comments": [comment],
    }


def _model_route():
    primary = os.getenv("QWEN_MODEL", PRIMARY_MODEL).strip() or PRIMARY_MODEL
    backup = os.getenv("QWEN_BACKUP_MODEL", BACKUP_MODEL).strip() or BACKUP_MODEL
    return [primary] if primary == backup else [primary, backup]


def _result_score(assessments, *, weight_key, timing_key):
    known_facts = sum(
        item.get(weight_key) is not None for item in assessments
    ) + sum(item.get(timing_key) is not None for item in assessments)
    return len(assessments), known_facts


def _convert_fractional_weights(assessments, key):
    weights = [item[key] for item in assessments if item.get(key) is not None]
    if len(weights) >= 2 and max(weights) <= 1 and 0.99 <= sum(weights) <= 1.01:
        for item in assessments:
            if item.get(key) is not None:
                item[key] = round(item[key] * 100, 4)


def _has_complete_weight_set(assessments):
    weights = [
        item["weightage"]
        for item in assessments
        if item.get("weightage") is not None
    ]
    return bool(weights) and 99.5 <= sum(weights) <= 100.5


def _week_from_deadline(value, *, maximum=None):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*week\s*(\d{1,2})\s*", value, re.IGNORECASE)
    if not match:
        return None
    week = int(match.group(1))
    return week if maximum is None or 1 <= week <= maximum else None


def _issue_text(value):
    issues = []
    for item in _list_or_empty(value):
        if isinstance(item, str) and item.strip():
            issues.append(item.strip())
        elif isinstance(item, dict):
            text = item.get("feedback") or item.get("message")
            if isinstance(text, str) and text.strip():
                issues.append(text.strip())
    return issues


def _contains_word(items, word):
    return any(word in item.lower() for item in items)


def _modules_by_name(modules):
    return {
        name: {**item, "module_name": name}
        for item in modules
        if isinstance(item, dict) and (name := _module_name(item))
    }


def _module_name(module):
    return _clean_name(module.get("module_name")) if isinstance(module, dict) else ""


def _clean_name(value):
    return str(value or "").strip().upper()


def _list_or_empty(value):
    return value if isinstance(value, list) else []


def _text_list(value):
    return [
        str(item).strip()
        for item in _list_or_empty(value)
        if str(item).strip()
    ]


def _unique_text(items):
    return list(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))


def _number_or_none(value):
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None


def _week_or_none(value):
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_error(error):
    if isinstance(error, ConnectionError):
        return str(error)
    if isinstance(error, OSError):
        return "An uploaded file could not be read."
    return str(error) or "The model response could not be processed."
