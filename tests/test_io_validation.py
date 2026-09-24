from src import io_manager


def test_source_input_requires_module_credits_and_evidence():
    errors = io_manager.validate_source_input(
        {
            "module": "INF1103",
            "module_credits": None,
            "prompt": "",
            "image_paths": [],
        }
    )

    assert "Module credits are required and must be a number." in errors
    assert "Add at least one screenshot or a context prompt." in errors


def test_source_input_accepts_prompt_only_evidence():
    assert io_manager.validate_source_input(
        {
            "module": "INF1103",
            "module_credits": 6,
            "prompt": "Quiz 1 is due 2026-10-15 and worth 10%.",
            "image_paths": [],
        }
    ) == []


def test_source_input_rejects_oversized_prompt():
    errors = io_manager.validate_source_input(
        {
            "module": "INF1103",
            "module_credits": 6,
            "prompt": "x" * (io_manager.MAX_PROMPT_CHARS + 1),
            "image_paths": [],
        }
    )

    assert "Prompt may contain at most 4000 characters." in errors


def test_correction_input_rejects_unknown_or_invalid_fields():
    errors = io_manager.validate_correction_input(
        {
            "module": "INF1103",
            "assessment_type": "",
            "deadline": "Week 8",
            "weightage": 101,
        }
    )

    assert "Unexpected correction fields: module." in errors
    assert "Assessment type is required." in errors
    assert "Deadline must use YYYY-MM-DD format." in errors
    assert "Weightage must be between 0 and 100." in errors
