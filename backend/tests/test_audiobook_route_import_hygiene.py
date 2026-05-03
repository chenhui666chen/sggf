from __future__ import annotations

import ast
from pathlib import Path


ROUTES_DIR = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "audiobook_api"


def _route_files() -> list[Path]:
    return sorted(ROUTES_DIR.glob("routes_*.py"))


def _imported_top_level_names(tree: ast.Module) -> dict[str, int]:
    imported: dict[str, int] = {}

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".", 1)[0]
                imported[name] = node.lineno
            continue

        if isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                continue
            for alias in node.names:
                name = alias.asname or alias.name
                imported[name] = node.lineno

    return imported


def _is_type_checking_guard(node: ast.If) -> bool:
    return isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"


def _used_names(tree: ast.Module) -> set[str]:
    used: set[str] = set()

    class UsedNameVisitor(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import) -> None:
            return None

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            return None

        def visit_If(self, node: ast.If) -> None:
            self.visit(node.test)
            if _is_type_checking_guard(node):
                return
            for child in node.body:
                self.visit(child)
            for child in node.orelse:
                self.visit(child)

        def visit_Name(self, node: ast.Name) -> None:
            used.add(node.id)

    visitor = UsedNameVisitor()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        visitor.visit(node)

    return used


def test_audiobook_route_modules_do_not_keep_unused_top_level_imports():
    route_files = _route_files()
    assert route_files, f"未找到有声书路由文件: {ROUTES_DIR}"

    unused_by_file: dict[str, list[str]] = {}
    for route_file in route_files:
        tree = ast.parse(route_file.read_text(encoding="utf-8"), filename=str(route_file))
        imported = _imported_top_level_names(tree)
        used = _used_names(tree)

        unused = [
            f"{name} (line {lineno})"
            for name, lineno in sorted(imported.items(), key=lambda item: (item[1], item[0]))
            if name not in used
        ]
        if unused:
            unused_by_file[route_file.name] = unused

    assert unused_by_file == {}
