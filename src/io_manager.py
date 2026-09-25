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

    return {"modules": _normalize_modules(input_data["modules"])}, []


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
    seen_module_names = set()
    duplicate_names = set()
    for index, module in enumerate(modules, start=1):
        module_errors, normalized_name = _validate_module(module, index)
        errors.extend(module_errors)
        if normalized_name is not None:
            if normalized_name in seen_module_names:
                duplicate_names.add(normalized_name)
            seen_module_names.add(normalized_name)

    if duplicate_names:
        errors.append(
            f"Remove duplicate modules: {', '.join(sorted(duplicate_names))}."
        )
    return errors


def _normalize_modules(raw_modules):
    """Return modules in the stable shape used by downstream services."""
    modules = []
    for raw_module in raw_modules:
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
    return modules


def _validate_module(module, index):
    """Return one module's errors and its normalized name when available."""
    prefix = f"Module {index}"
    errors = []
    if not isinstance(module, dict):
        return [f"{prefix} must be an object."], None

    name = module.get("module_name")
    normalized_name = None
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{prefix} needs a module name or code.")
    else:
        normalized_name = name.strip().upper()

    errors.extend(_validate_credit_units(module.get("credit_units"), prefix))

    context = module.get("additional_context", "")
    files = module.get("files", [])
    if not isinstance(context, str):
        errors.append(f"{prefix} additional context must be text.")
    if not isinstance(files, list):
        errors.append(f"{prefix} files must be supplied as a list.")
        return errors, normalized_name
    if (not isinstance(context, str) or not context.strip()) and not files:
        errors.append(f"{prefix} needs assessment information or a file.")
    errors.extend(_validate_files(files, prefix))
    return errors, normalized_name


def _validate_credit_units(credit_units, prefix):
    """Return an error when supplied credit units are outside the accepted range."""
    if credit_units in (None, ""):
        return []
    try:
        numeric_credits = float(credit_units)
        if not 0 < numeric_credits <= 60:
            raise ValueError
    except (TypeError, ValueError):
        return [f"{prefix} credit units must be a positive number."]
    return []


def _validate_files(files, prefix):
    """Return active-request errors for invalid evidence paths."""
    errors = []
    for file_path in files:
        path, issue = _check_file(file_path, SUPPORTED_FILES)
        if issue == "missing":
            errors.append(f"{prefix} file was not found: {file_path}")
        elif issue == "unsupported":
            errors.append(f"{prefix} has an unsupported file type: {path.name}")
        elif issue == "oversized":
            errors.append(f"{prefix} file exceeds 10 MB: {path.name}")
    return errors


def _check_file(file_path, supported_extensions):
    """Return a path and its first filesystem or extension issue."""
    path = Path(file_path) if isinstance(file_path, str) else None
    if path is None or not path.is_file():
        return path, "missing"
    if path.suffix.lower() not in supported_extensions:
        return path, "unsupported"
    if path.stat().st_size > MAX_FILE_BYTES:
        return path, "oversized"
    return path, None


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

    errors.extend(_validate_legacy_images(images))
    return errors


def _validate_legacy_images(images):
    """Return legacy-request errors for invalid image paths."""
    errors = []
    for image in images:
        _path, issue = _check_file(image, SUPPORTED_IMAGES)
        if issue == "missing":
            errors.append(f"Image was not found: {image}")
        elif issue == "unsupported":
            errors.append(f"Unsupported image type: {image}")
        elif issue == "oversized":
            errors.append(f"Image exceeds 10 MB: {image}")
    return errors
