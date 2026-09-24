import json

from src import io_manager


def test_input_validation_returns_errors_for_wrong_types():
    errors = io_manager.validate_user_input(
        {
            "module": "INF1103",
            "module_credits": "6",
            "assessment_type": "Project",
            "deadline": 20261015,
            "weightage": "30",
            "prompt": ["not text"],
            "image_paths": [],
        }
    )

    assert "Deadline must be a string or omitted." in errors
    assert "Module credits must be a number or omitted." in errors
    assert "Weightage must be a number or omitted." in errors
    assert "Prompt must be text." in errors


def test_batch_loader_resolves_relative_image_paths(tmp_path):
    image_path = tmp_path / "assessment.png"
    image_path.write_bytes(b"test-image")
    batch_file = tmp_path / "assessments.json"
    batch_file.write_text(
        json.dumps(
            [
                {
                    "module": "INF1103",
                    "assessment_type": "Project",
                    "deadline": "2026-10-15",
                    "weightage": 30,
                    "image_paths": ["assessment.png"],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = io_manager.load_batch_input(str(batch_file))

    assert result["errors"] == []
    assert result["records"][0]["image_paths"] == [str(image_path)]


def test_batch_loader_rejects_malformed_or_empty_json(tmp_path):
    malformed_file = tmp_path / "malformed.json"
    malformed_file.write_text("not-json", encoding="utf-8")
    empty_file = tmp_path / "empty.json"
    empty_file.write_text("[]", encoding="utf-8")

    malformed = io_manager.load_batch_input(str(malformed_file))
    empty = io_manager.load_batch_input(str(empty_file))

    assert malformed["errors"] == ["Batch file is not valid JSON."]
    assert empty["errors"] == ["Batch file must contain a non-empty JSON list."]


def test_prompt_length_is_bounded_for_free_api_usage():
    errors = io_manager.validate_user_input(
        {
            "module": "INF1103",
            "module_credits": 6,
            "assessment_type": "Project",
            "deadline": "2026-10-15",
            "weightage": 30,
            "prompt": "x" * (io_manager.MAX_PROMPT_CHARS + 1),
            "image_paths": [],
        }
    )

    assert "Prompt may contain at most 4000 characters." in errors


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
    errors = io_manager.validate_source_input(
        {
            "module": "INF1103",
            "module_credits": 6,
            "prompt": "Quiz 1 is due 2026-10-15 and worth 10%.",
            "image_paths": [],
        }
    )

    assert errors == []


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
