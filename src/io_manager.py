"""Validate and normalize frontend evidence before it reaches the model."""

from pathlib import Path


SUPPORTED_IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
SUPPORTED_DOCUMENTS = {".pdf", ".txt", ".md", ".csv", ".json", ".docx"}
SUPPORTED_FILES = SUPPORTED_IMAGES | SUPPORTED_DOCUMENTS
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_MODULES = 20


def process_input(input_data):
    """Return one stable multi-module request or its validation errors."""
    errors = validate_modules_input(input_data)
    if errors:
        return None, errors

    modules = []
    for raw_module in input_data["modules"]:
        raw_credits = raw_module.get("credit_units")
        credits = float(raw_credits) if raw_credits not in (None, "") else None
        if credits is not None and credits.is_integer():
            credits = int(credits)
        modules.append(
            {
                "module_name": str(raw_module["module_name"]).strip().upper(),
                "credit_units": credits,
                "files": list(raw_module.get("files", [])),
                "additional_context": str(
                    raw_module.get("additional_context", "")
                ).strip(),
            }
        )
    return {"modules": modules}, []


def validate_modules_input(input_data):
    """Return user-facing errors for a multi-module request."""
    if not isinstance(input_data, dict):
        return ["The request must be an object."]
    modules = input_data.get("modules")
    if not isinstance(modules, list) or not modules:
        return ["Add at least one module."]
    if len(modules) > MAX_MODULES:
        return [f"A maximum of {MAX_MODULES} modules can be processed at once."]

    errors = []
    names = []
    for index, module in enumerate(modules, start=1):
        prefix = f"Module {index}"
        if not isinstance(module, dict):
            errors.append(f"{prefix} must be an object.")
            continue
        name = module.get("module_name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{prefix} needs a module name or code.")
        else:
            names.append(name.strip().upper())

        credits = module.get("credit_units")
        if credits not in (None, ""):
            try:
                numeric_credits = float(credits)
                if not 0 < numeric_credits <= 60:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(f"{prefix} credit units must be a positive number.")

        context = module.get("additional_context", "")
        files = module.get("files", [])
        if not isinstance(context, str):
            errors.append(f"{prefix} additional context must be text.")
        if not isinstance(files, list):
            errors.append(f"{prefix} files must be supplied as a list.")
            continue
        if (not isinstance(context, str) or not context.strip()) and not files:
            errors.append(f"{prefix} needs assessment information or a file.")
        errors.extend(_validate_files(files, prefix))

    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        errors.append(f"Remove duplicate modules: {', '.join(duplicates)}.")
    return errors


def _validate_files(files, prefix):
    errors = []
    for file_path in files:
        path = Path(file_path) if isinstance(file_path, str) else None
        if path is None or not path.is_file():
            errors.append(f"{prefix} file was not found: {file_path}")
        elif path.suffix.lower() not in SUPPORTED_FILES:
            errors.append(f"{prefix} has an unsupported file type: {path.name}")
        elif path.stat().st_size > MAX_FILE_BYTES:
            errors.append(f"{prefix} file exceeds 10 MB: {path.name}")
    return errors


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
        elif path.stat().st_size > MAX_FILE_BYTES:
            errors.append(f"Image exceeds 10 MB: {image}")
    return errors
