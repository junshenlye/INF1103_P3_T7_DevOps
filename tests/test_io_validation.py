from src import io_manager


def test_input_validation_returns_errors_for_wrong_types():
    errors = io_manager.validate_user_input(
        {
            "module": "INF1103",
            "assessment_type": "Project",
            "deadline": 20261015,
            "weightage": "30",
            "prompt": ["not text"],
            "image_paths": [],
        }
    )

    assert "Deadline must be a string or omitted." in errors
    assert "Weightage must be a number or omitted." in errors
    assert "Prompt must be text." in errors
