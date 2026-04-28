"""
批量规范化 project_settings.plot_outline。

默认只预览，不写库；需要显式加 `--apply` 才会更新数据库。

用法：
  - 预览全部项目：python "scripts/normalize_project_outlines.py"
  - 只看单个项目：python "scripts/normalize_project_outlines.py" --project-id 15
  - 实际写入：python "scripts/normalize_project_outlines.py" --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text

from app.db.base import SessionLocal
from app.services.workflow_context_builder import (
    WorkflowContextBuilder,
    _decode_character_prompt_text,
    _decode_prompt_text,
    _decode_plot_outline_prompt_text,
)


def _iter_outline_rows(db, project_id: int | None) -> list[tuple[int, str, str]]:
    if project_id is not None:
        rows = db.execute(
            text(
                """
                SELECT project_id, plot_outline, characters
                FROM project_settings
                WHERE project_id = :project_id
                """
            ),
            {"project_id": int(project_id)},
        ).fetchall()
    else:
        rows = db.execute(
            text(
                """
                SELECT project_id, plot_outline, characters
                FROM project_settings
                WHERE plot_outline IS NOT NULL AND plot_outline <> ''
                ORDER BY project_id ASC
                """
            )
        ).fetchall()

    return [
        (int(row[0]), str(row[1] or ""), str(row[2] or ""))
        for row in rows
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="批量规范化 project_settings.plot_outline")
    parser.add_argument("--project-id", type=int, default=None, help="仅处理单个项目")
    parser.add_argument("--apply", action="store_true", help="实际写入数据库")
    args = parser.parse_args()

    db = SessionLocal()
    builder = WorkflowContextBuilder(db)
    changed_rows: list[tuple[int, str, str, str]] = []

    try:
        for project_id, raw_outline, raw_characters in _iter_outline_rows(db, args.project_id):
            current_outline = _decode_prompt_text(raw_outline).strip()
            if not current_outline:
                continue

            normalized_outline = _decode_plot_outline_prompt_text(
                raw_outline,
                characters_text=_decode_character_prompt_text(raw_characters),
            ).strip()
            if not normalized_outline or normalized_outline == current_outline:
                continue

            changed_rows.append((project_id, raw_outline, raw_characters, normalized_outline))

        print(f"matched: {len(changed_rows)}")
        for project_id, raw_outline, _, normalized_outline in changed_rows[:20]:
            before_len = len(_decode_prompt_text(raw_outline).strip())
            after_len = len(normalized_outline)
            print(f"- project_id={project_id}: {before_len} -> {after_len} chars")

        if not args.apply:
            print("preview only: 使用 --apply 才会写入数据库")
            return 0

        for project_id, raw_outline, raw_characters, _ in changed_rows:
            builder.update_project_settings_fields(
                project_id,
                plot_outline=raw_outline,
                characters=raw_characters,
            )

        print(f"updated: {len(changed_rows)}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
