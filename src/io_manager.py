"""Validate one module evidence pack before it reaches the model."""

from pathlib import Path


SUPPORTED_IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def validate_input(input_data):
    """Return user-facing errors for one module request."""
    if not isinstance(input_data, dict):
        return ["The request must be an object."]

    errors = []
    module = input_data.get("module")
    prompt = input_data.get("prompt", "")
    images = input_data.get("image_paths", [])

    if not isinstance(module, str) or not module.strip():
        errors.append("Module code is required.")
    if not isinstance(prompt, str):
        errors.append("Extra context must be text.")
    if not isinstance(images, list):
        return errors + ["Images must be supplied as a list."]
    if not prompt.strip() and not images:
        errors.append("Add at least one screenshot or some context.")

    for image in images:
        path = Path(image) if isinstance(image, str) else None
        if path is None or not path.is_file():
            errors.append(f"Image was not found: {image}")
        elif path.suffix.lower() not in SUPPORTED_IMAGES:
            errors.append(f"Unsupported image type: {image}")
        elif path.stat().st_size > MAX_IMAGE_BYTES:
            errors.append(f"Image exceeds 10 MB: {image}")
    return errors
