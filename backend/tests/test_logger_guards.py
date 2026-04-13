import ast
import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DEBUG", "false")


def _file_uses_logger_calls(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"debug", "info", "warning", "error", "exception", "critical"}:
            if isinstance(node.value, ast.Name) and node.value.id == "logger":
                return True
    return False


def _file_has_logger_definition(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "logger":
                    return True
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "logger":
                return True
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported_name = alias.asname or alias.name
                if imported_name == "logger":
                    return True
    return False


def test_python_files_using_logger_have_logger_definition() -> None:
    offenders: list[str] = []

    for path in Path("backend/app").rglob("*.py"):
        source = path.read_text(encoding="utf-8-sig", errors="ignore")
        tree = ast.parse(source)
        if not _file_uses_logger_calls(tree):
            continue
        if not _file_has_logger_definition(tree):
            offenders.append(path.as_posix())

    assert offenders == []
