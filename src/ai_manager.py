"""Route module evidence through vision models and normalize one reply."""

from concurrent.futures import ThreadPoolExecutor
import logging
import os
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree

from openai import OpenAI, OpenAIError

from .ai_support import (
    DASHSCOPE_BASE_URL,
    SUPPORTED_IMAGE_TYPES,
    build_user_content,
    model_route,
    parse_json_object,
    safe_error,
)
from .system_prompts import (
    PACING_SYSTEM_PROMPT,
    build_pacing_prompt,
)


LOGGER = logging.getLogger(__name__)
MAX_DOCUMENT_CHARS = 12000
DEFAULT_PARALLEL_MODULES = 5


# Public multi-module API


def process(input_data, trimester_context, api_caller=None):
    """Extract modules independently and concurrently, preserving input order."""
    requested_modules = input_data.get("modules", [])
    if not requested_modules:
        return validate_ai_output(
            {"modules": [], "global_comments": [], "user_checklist": []},
            expected_modules=[],
        )

    worker_limit = _parallel_module_limit(len(requested_modules))
    LOGGER.info(
        "Extracting %d module(s) with up to %d parallel request(s)",
        len(requested_modules),
        worker_limit,
    )
    with ThreadPoolExecutor(max_workers=worker_limit) as executor:
        results = list(
            executor.map(
                lambda module: _extract_module(
                    module, trimester_context, api_caller
                ),
                requested_modules,
            )
        )

    modules = []
    global_comments = []
    checklist = []
    models_used = []
    for result in results:
        modules.append(result["module"])
        global_comments.extend(result.get("global_comments", []))
        checklist.extend(result.get("user_checklist", []))
        if result.get("model_used"):
            models_used.append(result["model_used"])
    return validate_ai_output(
        {
            "modules": modules,
            "global_comments": _unique_text(global_comments),
            "user_checklist": _unique_text(checklist),
            "models_used": list(dict.fromkeys(models_used)),
        },
        expected_modules=requested_modules,
    )


# Per-module extraction


def _parallel_module_limit(module_count):
    """Bound parallel model calls to avoid one large multi-module context."""
    try:
        configured = int(
            os.getenv("AI_MAX_PARALLEL_MODULES", str(DEFAULT_PARALLEL_MODULES))
        )
    except ValueError:
        configured = DEFAULT_PARALLEL_MODULES
    return max(1, min(module_count, configured, 8))


def _extract_module(module, trimester_context, api_caller):
    """Extract one module so its uploaded evidence remains clearly associated."""
    module_name = module["module_name"]
    file_paths = module.get("files", [])
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
        path for path in file_paths if Path(path).suffix.lower() in SUPPORTED_IMAGE_TYPES
    ]
    caller = api_caller or _call_pacing_model
    best_result = None
    for attempt, model in enumerate(model_route(), start=1):
        try:
            reply = caller(
                prompt=prompt,
                image_paths=image_paths,
                api_key=api_key if api_caller is None else "",
                model=model,
                structured_output=attempt > 1,
            )
            parsed = _parse_pacing_reply(reply, module_name)
            result = _normalize_module_result(parsed, module)
            result["module"]["comments"] = _unique_text(
                result["module"].get("comments", []) + document_comments
            )
            result["model_used"] = model
            if best_result is None or _pacing_result_score(result) > _pacing_result_score(
                best_result
            ):
                best_result = result
            if result["module"]["assessments"]:
                return result
        except (ConnectionError, OSError, TypeError, ValueError, KeyError) as error:
            LOGGER.warning(
                "Pacing extraction failed for %s via %s: %s",
                module_name,
                model,
                safe_error(error),
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


# Evidence preparation


def _build_pacing_prompt(module, trimester_context):
    """Read non-image evidence, then delegate prompt wording to system_prompts."""
    document_parts = []
    comments = []
    remaining_document_chars = MAX_DOCUMENT_CHARS
    for file_path in module.get("files", []):
        path = Path(file_path)
        if path.suffix.lower() in SUPPORTED_IMAGE_TYPES:
            continue
        try:
            text = _read_document_text(path)
            if text.strip():
                excerpt = text[:remaining_document_chars]
                if excerpt:
                    document_parts.append(f"--- {path.name} ---\n{excerpt}")
                    remaining_document_chars -= len(excerpt)
            else:
                comments.append(f"{path.name} did not contain readable text.")
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
            LOGGER.warning(
                "Could not read uploaded document %s: %s",
                path.name,
                safe_error(error),
            )
            comments.append(f"{path.name} could not be read as assessment evidence.")

    document_text = "\n".join(document_parts)
    return build_pacing_prompt(module, trimester_context, document_text), comments


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


# Model request and response contract


def _call_pacing_model(prompt, image_paths, api_key, model, structured_output=False):
    request = {
        "model": model,
        "messages": [
            {"role": "system", "content": PACING_SYSTEM_PROMPT},
            {"role": "user", "content": build_user_content(prompt, image_paths)},
        ],
        "temperature": 0,
        "max_tokens": 2500,
        "extra_body": {"enable_thinking": False},
    }
    if structured_output:
        request["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "module_pacing_facts",
                "strict": True,
                "schema": _pacing_schema(),
            },
        }
    else:
        request["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": "submit_module_facts",
                    "description": "Submit extracted module assessment facts.",
                    "parameters": _pacing_schema(),
                },
            }
        ]
        request["tool_choice"] = {
            "type": "function",
            "function": {"name": "submit_module_facts"},
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
        raise ConnectionError(
            f"Alibaba Model Studio request failed{f' (HTTP {status})' if status else ''}: {error}"
        ) from error
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


def _pacing_schema():
    nullable_number = {"type": ["number", "null"]}
    nullable_integer = {"type": ["integer", "null"]}
    nullable_string = {"type": ["string", "null"]}
    one_item_list = {
        "type": "array",
        "items": {"type": "string"},
        "maxItems": 1,
    }
    three_item_list = {
        "type": "array",
        "items": {"type": "string"},
        "maxItems": 3,
    }
    assessment = {
        "type": "object",
        "properties": {
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
            "recurrence": {
                "type": ["object", "null"],
                "properties": {
                    "frequency": nullable_string,
                    "weeks": {"type": "array", "items": {"type": "integer"}},
                    "start_week": nullable_integer,
                    "end_week": nullable_integer,
                    "every_n_weeks": nullable_integer,
                },
                "required": [
                    "frequency",
                    "weeks",
                    "start_week",
                    "end_week",
                    "every_n_weeks",
                ],
                "additionalProperties": False,
            },
            "spans_multiple_weeks": {"type": "boolean"},
            "start_week": nullable_integer,
            "end_week": nullable_integer,
            "confidence": nullable_number,
            "comments": one_item_list,
            "missing_information": one_item_list,
            "assumptions": one_item_list,
        },
        "required": [
            "name",
            "type",
            "weightage_percent",
            "weightage_scope",
            "due_date",
            "due_week",
            "recurring",
            "recurrence",
            "spans_multiple_weeks",
            "start_week",
            "end_week",
            "confidence",
            "comments",
            "missing_information",
            "assumptions",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "module_name": {"type": "string"},
            "credit_units": nullable_number,
            "assessments": {"type": "array", "items": assessment},
            "comments": three_item_list,
            "global_comments": three_item_list,
            "user_checklist": three_item_list,
        },
        "required": [
            "module_name",
            "credit_units",
            "assessments",
            "comments",
            "global_comments",
            "user_checklist",
        ],
        "additionalProperties": False,
    }


# Response parsing and normalization


def _parse_pacing_reply(reply, module_name=None):
    if isinstance(reply, dict) and "assessments" in reply:
        return reply
    if isinstance(reply, dict) and isinstance(reply.get("modules"), list):
        selected = next(
            (
                item
                for item in reply["modules"]
                if isinstance(item, dict)
                and str(item.get("module_name", "")).strip().upper()
                == str(module_name or "").strip().upper()
            ),
            reply["modules"][0] if reply["modules"] else None,
        )
        if isinstance(selected, dict):
            return {
                **selected,
                "global_comments": reply.get("global_comments", []),
                "user_checklist": reply.get("user_checklist", []),
            }
    if not isinstance(reply, dict):
        return parse_json_object(str(reply))
    for tool_call in reply.get("tool_calls", []):
        function = tool_call.get("function", {})
        if function.get("name") == "submit_module_facts":
            return parse_json_object(function.get("arguments", ""))
    content = reply.get("content", "")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict)
        )
    return parse_json_object(content)


def _normalize_module_result(reply, supplied_module):
    if not isinstance(reply, dict):
        raise ValueError("The model result was not an object.")
    assessments = []
    comments = _text_list(reply.get("comments"))
    for index, raw in enumerate(reply.get("assessments", [])):
        if not isinstance(raw, dict):
            comments.append(f"Assessment {index + 1} could not be interpreted.")
            continue
        name = str(raw.get("name") or raw.get("assessment_type") or "").strip()
        if not name:
            comments.append(f"Assessment {index + 1} has no readable title.")
            continue
        missing = _compact_missing_information(
            _text_list(raw.get("missing_information"))
        )
        assumptions = _text_list(raw.get("assumptions"))
        item_comments = _text_list(raw.get("comments"))
        weight = _number_or_none(raw.get("weightage_percent", raw.get("weightage")))
        if weight is not None and not 0 <= weight <= 100:
            item_comments.append(f"The reported weightage for {name} is outside 0–100%.")
            missing.append("Valid assessment weightage")
            weight = None
        due_week = _week_or_none(raw.get("due_week"))
        if due_week is None and isinstance(raw.get("deadline"), str):
            match = re.fullmatch(
                r"\s*week\s*(\d{1,2})\s*",
                raw["deadline"],
                re.IGNORECASE,
            )
            due_week = int(match.group(1)) if match else None
        confidence = _number_or_none(raw.get("confidence"))
        if confidence is not None:
            confidence = min(max(confidence, 0), 1)
        recurrence = (
            raw.get("recurrence")
            if isinstance(raw.get("recurrence"), dict)
            else None
        )
        if recurrence:
            recurrence = {
                "frequency": str(recurrence.get("frequency") or "").strip() or None,
                "weeks": [
                    week
                    for week in (
                        _week_or_none(value)
                        for value in recurrence.get("weeks", [])
                    )
                    if week is not None
                ],
                "start_week": _week_or_none(recurrence.get("start_week")),
                "end_week": _week_or_none(recurrence.get("end_week")),
                "every_n_weeks": _week_or_none(recurrence.get("every_n_weeks")),
            }
        assessment_type = str(raw.get("type") or "assessment").strip().lower()
        recurring = bool(raw.get("recurring", False))
        raw_scope = str(raw.get("weightage_scope") or "").strip().lower()
        weightage_scope = (
            raw_scope if raw_scope in {"total", "per_occurrence"} else "total"
        )
        assessments.append(
            {
                "name": name,
                "type": assessment_type,
                "weightage_percent": weight,
                "weightage_scope": weightage_scope,
                "due_date": str(raw.get("due_date") or "").strip() or None,
                "due_week": due_week,
                "recurring": recurring,
                "recurrence": recurrence,
                "spans_multiple_weeks": bool(raw.get("spans_multiple_weeks", False)),
                "start_week": _week_or_none(raw.get("start_week")),
                "end_week": _week_or_none(raw.get("end_week")),
                "confidence": confidence,
                "comments": _unique_text(item_comments),
                "missing_information": _unique_text(missing),
                "assumptions": _unique_text(assumptions),
            }
        )
    known_weights = [
        item["weightage_percent"]
        for item in assessments
        if item["weightage_percent"] is not None
    ]
    fractional_weight_set = (
        len(known_weights) >= 2
        and max(known_weights) <= 1
        and 0.99 <= sum(known_weights) <= 1.01
    )
    if fractional_weight_set:
        for item in assessments:
            if item["weightage_percent"] is not None:
                item["weightage_percent"] = round(item["weightage_percent"] * 100, 4)
    supplied_credits = supplied_module.get("credit_units")
    extracted_credits = _number_or_none(reply.get("credit_units"))
    credits = supplied_credits if supplied_credits is not None else extracted_credits
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


def validate_ai_output(ai_result, expected_modules=None):
    """Validate/normalize extraction output before deterministic calculations."""
    if not isinstance(ai_result, dict):
        raise ValueError("AI output must be an object.")
    expected_by_name = {
        item["module_name"]: item
        for item in (expected_modules or [])
        if isinstance(item, dict)
    }
    modules = []
    global_comments = _text_list(ai_result.get("global_comments"))
    checklist = _text_list(ai_result.get("user_checklist"))
    for raw_module in ai_result.get("modules", []):
        if not isinstance(raw_module, dict):
            global_comments.append(
                "One module result was malformed and could not be used."
            )
            continue
        name = str(raw_module.get("module_name") or "").strip().upper()
        if not name:
            global_comments.append("One module result had no module reference.")
            continue
        supplied = expected_by_name.get(
            name,
            {"module_name": name, "credit_units": None},
        )
        normalized = _normalize_module_result(raw_module, supplied)["module"]
        modules.append(normalized)
        if normalized["credit_units"] is None:
            checklist.append(f"{name}: Provide the module credit units.")

    found = {module["module_name"] for module in modules}
    for name, supplied in expected_by_name.items():
        if name not in found:
            modules.append(
                _empty_module_result(
                    supplied,
                    "No AI result was returned for this module.",
                )
            )
            checklist.append(f"{name}: Provide clearer assessment information.")
    return {
        "modules": modules,
        "global_comments": _unique_text(global_comments),
        "user_checklist": _unique_text(checklist)[:10],
        "models_used": ai_result.get("models_used", []),
    }


# Normalization helpers


def _empty_module_result(module, comment):
    return {
        "module_name": module["module_name"],
        "credit_units": module.get("credit_units"),
        "assessments": [],
        "comments": [comment],
    }


def _pacing_result_score(result):
    assessments = result["module"]["assessments"]
    known = sum(item["weightage_percent"] is not None for item in assessments)
    known += sum(item["due_week"] is not None for item in assessments)
    return len(assessments), known


def _text_list(value):
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _compact_missing_information(items):
    """Keep one useful uncertainty signal instead of an exhaustive field list."""
    if not items:
        return []
    text = " ".join(items).lower()
    has_weight = bool(re.search(r"\b(weight|weightage|percentage)\b", text))
    has_timing = bool(
        re.search(r"\b(date|dates|week|weeks|deadline|timing)\b", text)
    )
    has_recurrence = bool(re.search(r"\b(recurrence|frequency)\b", text))
    if not any((has_weight, has_timing, has_recurrence)):
        return ["Assessment details are incomplete."]
    categories = set()
    if has_weight:
        categories.add("weight")
    if has_timing:
        categories.add("timing")
    if has_recurrence:
        categories.add("recurrence")
    if categories == {"weight"}:
        return ["Assessment weightage is missing."]
    if categories == {"timing"}:
        return ["Assessment timing is missing."]
    if categories == {"recurrence"}:
        return ["Recurrence details are incomplete."]
    return ["Assessment details are incomplete."]


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


# Legacy one-module compatibility API


def extract_assessments(input_data, api_caller=None):
    """Proxy the former one-module API to its isolated compatibility module."""
    from .legacy_extraction import extract_assessments as legacy_extract

    return legacy_extract(input_data, api_caller=api_caller)
