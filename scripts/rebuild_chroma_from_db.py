from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for path in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from sqlalchemy import text

from app.db.base import SessionLocal
from app.services.agents.knowledge_base import NovelKnowledgeBase
from app.services.workflow_context_builder import WorkflowContextBuilder


def _iter_project_ids(db) -> list[int]:
    rows = db.execute(
        text(
            """
            SELECT project_id
            FROM project_settings
            ORDER BY project_id
            """
        )
    ).fetchall()
    return [int(row[0]) for row in rows if row and row[0] is not None]


def _build_character_content(row) -> str:
    profile = str(row.profile or "").strip()
    summary = str(row.summary or "").strip()
    relations = str(row.relations or "").strip()
    tags = str(row.tags or "").strip()

    parts: list[str] = []
    if profile:
        parts.append(profile)
    elif summary:
        parts.append(summary)

    if relations and relations not in parts:
        parts.append(f"【关系】\n{relations}")
    if tags:
        parts.append(f"【标签】\n{tags}")

    return "\n\n".join(part for part in parts if part).strip()


def _rebuild_vector_store(
    target_directory: Path,
    *,
    project_ids: Iterable[int] | None = None,
) -> dict[str, int]:
    if target_directory.exists():
        raise RuntimeError(f"目标目录已存在，已停止以避免覆盖: {target_directory}")

    target_directory.parent.mkdir(parents=True, exist_ok=True)
    knowledge_base = NovelKnowledgeBase(persist_directory=str(target_directory))
    stats = {
        "projects": 0,
        "world_settings": 0,
        "plot_outlines": 0,
        "characters": 0,
        "chapters": 0,
    }

    db = SessionLocal()
    try:
        builder = WorkflowContextBuilder(db)
        selected_project_ids = list(project_ids) if project_ids else _iter_project_ids(db)
        for project_id in selected_project_ids:
            snapshot = builder.load_stage_contents_snapshot(project_id, pretty_json=False)
            world_setting = str(snapshot.get("world_setting") or "").strip()
            plot_outline = str(snapshot.get("plot_outline") or "").strip()

            if world_setting:
                knowledge_base.add_world_setting(
                    f"project_{project_id}_world_setting",
                    world_setting,
                    {
                        "project_id": str(project_id),
                        "category": "project_world_setting",
                    },
                )
                stats["world_settings"] += 1

            if plot_outline:
                knowledge_base.add_plot_outline(
                    f"project_{project_id}_plot_outline",
                    plot_outline,
                    {
                        "project_id": str(project_id),
                        "type": "plot_outline",
                    },
                )
                stats["plot_outlines"] += 1

            stats["projects"] += 1

        character_rows = db.execute(
            text(
                """
                SELECT id, project_id, name, profile, summary, relations, tags
                FROM characters
                ORDER BY project_id, id
                """
            )
        ).fetchall()
        for row in character_rows:
            content = _build_character_content(row)
            if not content:
                continue
            knowledge_base.add_character(
                str(row.name or f"character_{row.id}"),
                content,
                {
                    "type": "character",
                    "project_id": str(row.project_id),
                    "character_id": str(row.id),
                    "character_name": str(row.name or ""),
                },
            )
            stats["characters"] += 1

        chapter_rows = db.execute(
            text(
                """
                SELECT project_id, chapter_number, title, content, summary
                FROM chapters
                WHERE deleted_at IS NULL
                ORDER BY project_id, chapter_number
                """
            )
        ).fetchall()
        for row in chapter_rows:
            chapter_content = str(row.content or "").strip() or str(row.summary or "").strip()
            if not chapter_content:
                continue
            chapter_title = str(row.title or f"第{row.chapter_number}章")
            knowledge_base.add_chapter(
                int(row.chapter_number or 0),
                chapter_title,
                chapter_content,
                {
                    "project_id": str(row.project_id),
                    "type": "chapter",
                    "chapter_number": str(row.chapter_number or 0),
                    "title": chapter_title,
                },
            )
            stats["chapters"] += 1
    except Exception:
        if target_directory.exists():
            shutil.rmtree(target_directory, ignore_errors=True)
        raise
    finally:
        db.close()

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="从数据库权威源重建 Chroma 向量库")
    parser.add_argument(
        "--target-dir",
        default=str(PROJECT_ROOT / "backend" / "chroma_db_rebuilt_clean"),
        help="目标向量库目录，必须不存在",
    )
    parser.add_argument(
        "--project-id",
        action="append",
        type=int,
        dest="project_ids",
        help="仅重建指定 project_id，可重复传入",
    )
    args = parser.parse_args()

    target_directory = Path(args.target_dir).resolve()
    stats = _rebuild_vector_store(
        target_directory,
        project_ids=args.project_ids,
    )
    print(f"target_directory={target_directory}")
    for key, value in stats.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
