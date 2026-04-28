"""
从 PostgreSQL 重建 Chroma 向量库。

默认仅预览统计，不写入。
只有显式传入 --apply 才会写入新的目标目录。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text

from app.db.base import SessionLocal
from app.models.character import Character
from app.models.project import Chapter
from app.models.setting import SettingCollection, SettingItem
from app.services.agents.knowledge_base import NovelKnowledgeBase
from app.services.setting_templates import build_project_settings_summary
from app.services.workflow_context_builder import (
    _decode_character_prompt_text,
    _decode_plot_outline_prompt_text,
    _decode_prompt_text,
)


@dataclass
class VectorDocument:
    kind: str
    title: str
    content: str
    metadata: dict[str, str]


def _resolve_target_dir(raw_path: str | None) -> Path:
    raw = (raw_path or "backend/chroma_db_rebuilt").strip()
    path = Path(raw)
    if path.is_absolute():
        return path
    return (ROOT_DIR / path).resolve()


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _decode_optional_json_tags(value: object) -> str:
    raw = _clean_text(value)
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except Exception:
        return raw
    if isinstance(parsed, list):
        return "，".join(str(item).strip() for item in parsed if str(item).strip())
    return _clean_text(parsed)


def _project_ids(db, project_id: int | None) -> list[int]:
    if project_id is not None:
        return [int(project_id)]

    rows = db.execute(
        text(
            """
            SELECT DISTINCT project_id
            FROM (
                SELECT project_id
                FROM project_settings
                WHERE COALESCE(concept, '') <> ''
                   OR COALESCE(world_setting, '') <> ''
                   OR COALESCE(plot_outline, '') <> ''

                UNION

                SELECT project_id
                FROM characters

                UNION

                SELECT project_id
                FROM chapters
                WHERE deleted_at IS NULL
                  AND (
                    COALESCE(content, '') <> ''
                    OR COALESCE(summary, '') <> ''
                  )

                UNION

                SELECT sc.project_id
                FROM setting_collections sc
                JOIN setting_items si ON si.collection_id = sc.id
                WHERE sc.category IS DISTINCT FROM 'candidate'
            ) src
            ORDER BY project_id ASC
            """
        )
    ).fetchall()
    return [int(row[0]) for row in rows]


def _load_project_settings_row(db, project_id: int):
    return db.execute(
        text(
            """
            SELECT concept, world_setting, characters, plot_outline
            FROM project_settings
            WHERE project_id = :project_id
            """
        ),
        {"project_id": int(project_id)},
    ).fetchone()


def _build_setting_item_content(item: SettingItem) -> str:
    parts: list[str] = []
    if item.summary and _clean_text(item.summary):
        parts.append(f"摘要：{_clean_text(item.summary)}")
    if item.content and _clean_text(item.content):
        parts.append(_clean_text(item.content))
    tags = _decode_optional_json_tags(item.tags)
    if tags:
        parts.append(f"标签：{tags}")
    relations = _clean_text(item.relations)
    if relations:
        parts.append(f"关系：{relations}")
    return "\n".join(part for part in parts if part)


def _build_character_content(character: Character) -> str:
    profile = _clean_text(character.profile)
    if profile:
        return profile

    parts: list[str] = [f"姓名：{character.name}"]
    if _clean_text(character.summary):
        parts.append(f"简介：{_clean_text(character.summary)}")
    if _clean_text(character.role):
        parts.append(f"阵营定位：{_clean_text(character.role)}")
    if _clean_text(character.role_position):
        parts.append(f"角色定位：{_clean_text(character.role_position)}")
    if _clean_text(character.importance_level):
        parts.append(f"重要程度：{_clean_text(character.importance_level)}")
    if _clean_text(character.faction):
        parts.append(f"所属势力：{_clean_text(character.faction)}")
    if character.age is not None:
        parts.append(f"年龄：{character.age}")
    if _clean_text(character.gender):
        parts.append(f"性别：{_clean_text(character.gender)}")
    if _clean_text(character.life_status):
        parts.append(f"当前状态：{_clean_text(character.life_status)}")
    if _clean_text(character.appearance_status):
        parts.append(f"出场状态：{_clean_text(character.appearance_status)}")
    if _clean_text(character.tags):
        parts.append(f"标签：{_decode_optional_json_tags(character.tags)}")
    if _clean_text(character.relations):
        parts.append(f"关系：{_clean_text(character.relations)}")
    return "\n".join(part for part in parts if part)


def _iter_setting_item_docs(db, project_id: int) -> Iterable[VectorDocument]:
    items = (
        db.query(SettingItem, SettingCollection)
        .join(SettingCollection, SettingItem.collection_id == SettingCollection.id)
        .filter(
            SettingCollection.project_id == project_id,
            SettingCollection.category != "candidate",
        )
        .order_by(SettingCollection.order, SettingCollection.id, SettingItem.order, SettingItem.id)
        .all()
    )

    for item, collection in items:
        content = _build_setting_item_content(item)
        if not content:
            continue
        yield VectorDocument(
            kind="world_setting",
            title=item.name,
            content=content,
            metadata={
                "project_id": str(project_id),
                "setting_id": str(item.id),
                "setting_name": item.name,
                "collection_id": str(collection.id),
                "collection_name": collection.name,
                "category": collection.category or "",
                "source": "setting_items",
            },
        )


def _iter_character_docs(db, project_id: int) -> Iterable[VectorDocument]:
    characters = (
        db.query(Character)
        .filter(Character.project_id == project_id)
        .order_by(Character.id.asc())
        .all()
    )

    for character in characters:
        content = _build_character_content(character).strip()
        if not content:
            continue
        yield VectorDocument(
            kind="character",
            title=character.name,
            content=content,
            metadata={
                "project_id": str(project_id),
                "character_id": str(character.id),
                "character_name": character.name,
                "importance_level": _clean_text(character.importance_level),
                "role": _clean_text(character.role),
                "source": "characters",
            },
        )


def _iter_chapter_docs(db, project_id: int) -> Iterable[VectorDocument]:
    chapters = (
        db.query(Chapter)
        .filter(
            Chapter.project_id == project_id,
            Chapter.deleted_at.is_(None),
        )
        .order_by(Chapter.chapter_number.asc(), Chapter.id.asc())
        .all()
    )

    for chapter in chapters:
        content = _clean_text(chapter.content) or _clean_text(chapter.summary)
        if not content:
            continue
        title = _clean_text(chapter.title) or f"第{chapter.chapter_number}章"
        yield VectorDocument(
            kind="chapter",
            title=title,
            content=content,
            metadata={
                "project_id": str(project_id),
                "chapter_id": str(chapter.id),
                "chapter_number": str(chapter.chapter_number),
                "source": "chapters",
            },
        )


def _build_project_documents(db, project_id: int) -> list[VectorDocument]:
    docs: list[VectorDocument] = []

    settings_row = _load_project_settings_row(db, project_id)
    if settings_row:
        raw_concept = _decode_prompt_text(settings_row[0]).strip()
        raw_world_setting = _decode_prompt_text(settings_row[1]).strip()
        raw_characters = _decode_character_prompt_text(settings_row[2]).strip()
        raw_plot_outline = _decode_plot_outline_prompt_text(
            settings_row[3],
            characters_text=raw_characters,
        ).strip()

        if raw_concept:
            docs.append(
                VectorDocument(
                    kind="world_setting",
                    title=f"project_{project_id}_concept",
                    content=raw_concept,
                    metadata={
                        "project_id": str(project_id),
                        "category": "concept",
                        "source": "project_settings.concept",
                    },
                )
            )

        summary_world_setting = build_project_settings_summary(
            project_id,
            db,
            max_content_length=400,
        ).strip()
        if summary_world_setting:
            docs.append(
                VectorDocument(
                    kind="world_setting",
                    title=f"project_{project_id}_world_summary",
                    content=summary_world_setting,
                    metadata={
                        "project_id": str(project_id),
                        "category": "world_summary",
                        "source": "setting_items.summary",
                    },
                )
            )

        if raw_world_setting:
            docs.append(
                VectorDocument(
                    kind="world_setting",
                    title=f"project_{project_id}_world_setting",
                    content=raw_world_setting,
                    metadata={
                        "project_id": str(project_id),
                        "category": "world_setting",
                        "source": "project_settings.world_setting",
                    },
                )
            )

        if raw_plot_outline:
            docs.append(
                VectorDocument(
                    kind="plot_outline",
                    title=f"project_{project_id}_plot_outline",
                    content=raw_plot_outline,
                    metadata={
                        "project_id": str(project_id),
                        "source": "project_settings.plot_outline",
                    },
                )
            )

    docs.extend(_iter_setting_item_docs(db, project_id))
    docs.extend(_iter_character_docs(db, project_id))
    docs.extend(_iter_chapter_docs(db, project_id))
    return docs


def _count_by_kind(docs: list[VectorDocument]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for doc in docs:
        counts[doc.kind] = counts.get(doc.kind, 0) + 1
    return counts


def _validate_target_dir_for_apply(target_dir: Path) -> None:
    if target_dir.exists() and any(target_dir.iterdir()):
        raise SystemExit(
            f"目标目录非空，拒绝写入: {target_dir}\n请改用新的 --target-dir，避免覆盖现有向量库。"
        )
    target_dir.mkdir(parents=True, exist_ok=True)


def _write_documents(kb: NovelKnowledgeBase, docs: list[VectorDocument]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for doc in docs:
        if doc.kind == "world_setting":
            kb.add_world_setting(doc.title, doc.content, dict(doc.metadata))
        elif doc.kind == "character":
            kb.add_character(doc.title, doc.content, dict(doc.metadata))
        elif doc.kind == "chapter":
            chapter_number = int(doc.metadata.get("chapter_number") or 0)
            kb.add_chapter(chapter_number, doc.title, doc.content, dict(doc.metadata))
        elif doc.kind == "plot_outline":
            kb.add_plot_outline(doc.title, doc.content, dict(doc.metadata))
        else:
            continue
        counts[doc.kind] = counts.get(doc.kind, 0) + 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="从 PostgreSQL 重建 Chroma 向量库（默认只预览）")
    parser.add_argument("--project-id", type=int, default=None, help="仅重建指定 project_id")
    parser.add_argument("--target-dir", default="backend/chroma_db_rebuilt", help="重建输出目录")
    parser.add_argument("--apply", action="store_true", help="实际写入新目录")
    args = parser.parse_args()

    target_dir = _resolve_target_dir(args.target_dir)
    db = SessionLocal()

    try:
        project_ids = _project_ids(db, args.project_id)
        print(f"projects: {len(project_ids)}")
        if not project_ids:
            print("没有可重建的项目")
            return 0

        project_docs: dict[int, list[VectorDocument]] = {}
        total_counts: dict[str, int] = {}
        for project_id in project_ids:
            docs = _build_project_documents(db, project_id)
            project_docs[project_id] = docs
            counts = _count_by_kind(docs)
            for kind, count in counts.items():
                total_counts[kind] = total_counts.get(kind, 0) + count
            print(
                f"- project_id={project_id}: "
                f"world={counts.get('world_setting', 0)} "
                f"plot={counts.get('plot_outline', 0)} "
                f"character={counts.get('character', 0)} "
                f"chapter={counts.get('chapter', 0)}"
            )

        print("total:")
        for kind in ("world_setting", "plot_outline", "character", "chapter"):
            print(f"  - {kind}: {total_counts.get(kind, 0)}")

        if not args.apply:
            print(f"preview only: 使用 --apply 才会写入 {target_dir}")
            return 0

        _validate_target_dir_for_apply(target_dir)
        kb = NovelKnowledgeBase(persist_directory=str(target_dir))

        written_counts: dict[str, int] = {}
        for project_id in project_ids:
            counts = _write_documents(kb, project_docs[project_id])
            for kind, count in counts.items():
                written_counts[kind] = written_counts.get(kind, 0) + count
            print(
                f"written project_id={project_id}: "
                f"world={counts.get('world_setting', 0)} "
                f"plot={counts.get('plot_outline', 0)} "
                f"character={counts.get('character', 0)} "
                f"chapter={counts.get('chapter', 0)}"
            )

        print(f"target_dir: {target_dir}")
        print(f"vectorstore_mode: {kb.vectorstore_mode}")
        print(f"active_persist_directory: {kb.active_persist_directory}")
        print("written total:")
        for kind in ("world_setting", "plot_outline", "character", "chapter"):
            print(f"  - {kind}: {written_counts.get(kind, 0)}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
