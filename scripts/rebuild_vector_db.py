"""向量库全量重建工具：从 PostgreSQL 重新灌入章节/人物/设定/世界观/情节大纲。

背景：Chroma 向量库是派生数据（源数据全部在 PostgreSQL），当向量目录被清空
或 chromadb 版本迁移导致不可读时，用本脚本一键回填，恢复 RAG 语义召回。

幂等性：sync_to_vector_db / upsert_* 写入前都会先删除同实体的旧向量，
重复执行结果不变。

用法：
    python scripts/rebuild_vector_db.py                # 重建全部项目
    python scripts/rebuild_vector_db.py --project-id 145   # 只重建指定项目
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "backend", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "backend" / ".env", override=False)

from sqlalchemy import text  # noqa: E402

from app.db.base import SessionLocal  # noqa: E402
from app.models.character import Character  # noqa: E402
from app.models.project import Chapter, Project  # noqa: E402
from app.models.setting import SettingCollection  # noqa: E402


def _rebuild_project(db, project_id: int) -> dict[str, int]:
    from app.services.character_text_generator import CharacterTextGenerator
    from app.services.vector_sync import (
        sync_to_vector_db,
        upsert_character_to_vector_db,
        upsert_setting_to_vector_db,
    )
    from app.services.workflow_context_builder import WorkflowContextBuilder

    counts = {"chapter": 0, "character": 0, "setting": 0, "world": 0, "plot": 0}

    # 1) 章节正文（与 chapter_post_save 步骤0 同口径）
    chapters = (
        db.query(Chapter)
        .filter(
            Chapter.project_id == project_id,
            Chapter.deleted_at.is_(None),
        )
        .order_by(Chapter.chapter_number)
        .all()
    )
    for chapter in chapters:
        if not (chapter.content or "").strip():
            continue
        sync_to_vector_db(
            kb_type="chapter",
            name=f"第{chapter.chapter_number}章 {chapter.title}".strip(),
            content=chapter.content,
            metadata={
                "project_id": str(project_id),
                "chapter_number": str(chapter.chapter_number),
            },
        )
        counts["chapter"] += 1

    # 2) 人物卡（与 characters.py 保存路径同口径：含关系与功法）
    for char in db.query(Character).filter(Character.project_id == project_id).all():
        vector_content = CharacterTextGenerator.generate_single_character_text(
            char,
            db=db,
            include_relations=True,
            include_techniques=True,
        )
        upsert_character_to_vector_db(
            character_id=char.id,
            character_name=char.name,
            content=vector_content,
            project_id=project_id,
        )
        counts["character"] += 1

    # 3) 设定项（与 execute_background 概念阶段同步同口径）
    for collection in (
        db.query(SettingCollection)
        .filter(SettingCollection.project_id == project_id)
        .all()
    ):
        for setting in collection.items:
            setting_content = (
                f"**设定名称**: {setting.name}\n"
                f"**类别**: {collection.category or ''}\n"
                f"**详细描述**: {setting.content or ''}"
            ).strip()
            upsert_setting_to_vector_db(
                setting_id=setting.id,
                setting_name=setting.name,
                content=setting_content,
                project_id=project_id,
                category=collection.category or "unknown",
                metadata={
                    "setting_id": str(setting.id),
                    "name": setting.name,
                    "category": collection.category or "",
                },
            )
            counts["setting"] += 1

    # 4) 世界观与情节大纲（read_stage_content 负责解码/史诗卷重建）
    builder = WorkflowContextBuilder(db)
    world_text = builder.read_stage_content(project_id, "world_builder")
    if world_text.strip():
        sync_to_vector_db(
            kb_type="world",
            name="世界观设定",
            content=world_text,
            metadata={
                "project_id": str(project_id),
                "title": "世界观设定",
                "category": "world_setting",
            },
        )
        counts["world"] += 1

    plot_text = builder.read_stage_content(project_id, "structure")
    if plot_text.strip():
        sync_to_vector_db(
            kb_type="plot",
            name="情节大纲",
            content=plot_text,
            metadata={
                "project_id": str(project_id),
                "title": "情节大纲",
                "type": "plot_outline",
            },
        )
        counts["plot"] += 1

    return counts


def main() -> int:
    # Windows GBK 控制台无法编码 emoji 输出，统一切到 UTF-8 + 兜底替换
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="从 PostgreSQL 全量重建 Chroma 向量库")
    parser.add_argument("--project-id", type=int, default=None, help="仅重建指定项目")
    args = parser.parse_args()

    from app.services.vector_sync import get_vector_kb

    kb = get_vector_kb()
    if kb is None or kb.vectorstore_mode != "persistent":
        print("❌ 向量库未能以持久化模式初始化，请检查 chromadb 与目录状态", file=sys.stderr)
        return 1
    print(f"🔮 向量库: {kb.active_persist_directory}（模式 {kb.vectorstore_mode}）")

    db = SessionLocal()
    try:
        if args.project_id is not None:
            project_ids = [args.project_id]
        else:
            project_ids = [
                row[0] for row in db.execute(text("SELECT id FROM projects ORDER BY id")).fetchall()
            ]

        for project_id in project_ids:
            title_row = db.execute(
                text("SELECT title FROM projects WHERE id = :pid"), {"pid": project_id}
            ).fetchone()
            if not title_row:
                print(f"⚠️ 项目 {project_id} 不存在，跳过")
                continue
            counts = _rebuild_project(db, project_id)
            summary = "、".join(f"{k}×{v}" for k, v in counts.items() if v)
            print(f"✅ 项目 {project_id}《{title_row[0]}》回填完成：{summary or '无可回填内容'}")

        collection = getattr(kb.vectorstore, "_collection", None)
        if collection is not None:
            print(f"📊 向量库当前文档总数: {collection.count()}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
