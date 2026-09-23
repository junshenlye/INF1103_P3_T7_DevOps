import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_MODULES = (
    "main.py",
    "io_manager.py",
    "ai_manager.py",
    "logic_manager.py",
    "data_manager.py",
)


def project_python_files():
    ignored_parts = {".git", ".venv", "__pycache__"}
    return [
        path
        for path in PROJECT_ROOT.rglob("*.py")
        if not ignored_parts.intersection(path.parts)
    ]


def test_required_manager_modules_exist():
    for filename in REQUIRED_MODULES:
        assert (PROJECT_ROOT / "src" / filename).is_file()


def test_project_defines_no_classes():
    for path in project_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        class_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        assert class_nodes == [], f"Class definition found in {path}"


def test_output_calls_are_confined_to_io_manager():
    allowed_file = PROJECT_ROOT / "src" / "io_manager.py"
    for path in project_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        output_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ]
        if path != allowed_file:
            assert output_calls == [], f"Output call found outside I/O Manager: {path}"
