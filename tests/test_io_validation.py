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
