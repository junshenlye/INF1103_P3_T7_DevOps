"""Shared transport helpers for current and legacy AI extraction flows."""

import base64
import json
import os
from pathlib import Path


DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
PRIMARY_MODEL = "qwen3.7-plus"
BACKUP_MODEL = "qwen3.7-flash"
SUPPORTED_IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def build_user_content(prompt, image_paths):
    """Build one multimodal user message."""
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    content = [{"type": "text", "text": prompt}]
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


def parse_json_object(text):
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


def model_route():
    """Return one primary model followed by one distinct backup model."""
    primary = os.getenv("QWEN_MODEL", PRIMARY_MODEL).strip() or PRIMARY_MODEL
    backup = os.getenv("QWEN_BACKUP_MODEL", BACKUP_MODEL).strip() or BACKUP_MODEL
    return [primary] if primary == backup else [primary, backup]


def safe_error(error):
    """Return a short non-sensitive failure message."""
    if isinstance(error, ConnectionError):
        return str(error)
    if isinstance(error, OSError):
        return "An uploaded image could not be read."
    return str(error) or "The model response could not be processed."
