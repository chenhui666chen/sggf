"""correct character story stance false positives

Revision ID: correct_character_story_stance_false_positives
Revises: backfill_character_story_stance_from_text_evidence
Create Date: 2026-04-08

"""

from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa


revision = "correct_character_story_stance_false_positives"
down_revision = "backfill_character_story_stance_from_text_evidence"
branch_labels = None
depends_on = None


CANONICAL_STORY_STANCES = ("主角方", "反派方", "中立方", "亦正亦邪")
EXPLICIT_STORY_STANCE_PATTERNS = (
    re.compile(r"(?:\*\*)?【故事立场】(?:\*\*)?[：:]\s*(主角方|反派方|中立方|亦正亦邪)"),
    re.compile(r"故事立场[：:]\s*(主角方|反派方|中立方|亦正亦邪)"),
)
PRO_STORY_STANCE_PHRASES = (
    "从敌对到生死相托的战友",
    "互不背叛",
    "投资者与引路人",
    "镜像与救赎",
    "功能性伙伴",
    "精神导师",
    "现实导师",
    "核心护卫",
    "信任圈内",
    "向导与组织接口",
    "技术协作者",
    "数据遗产继承者",
    "生死相托",
)
ANTI_STORY_STANCE_PHRASES = (
    "主要追捕者",
    "武力对抗符号",
    "学术讨伐",
    "天道正义围剿",
    "秩序暴力",
    "污名为",
)
NEUTRAL_STORY_STANCE_PHRASES = (
    "记忆崩解受害者",
    "旁观者",
    "游离于多方",
)
AMBIGUOUS_STORY_STANCE_PHRASES = (
    "立场游移",
    "两面下注",
)


def _normalize_story_stance_label(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text in CANONICAL_STORY_STANCES:
        return text
    if "亦正亦邪" in text or any(phrase in text for phrase in AMBIGUOUS_STORY_STANCE_PHRASES):
        return "亦正亦邪"
    if any(keyword in text for keyword in ("中立", "旁观", "游离", "受害者")):
        return "中立方"
    if any(keyword in text for keyword in ("反派", "对手", "敌对", "宿敌", "追捕", "追杀", "围剿", "打压", "污名", "猎杀", "夺取")):
        return "反派方"
    if any(keyword in text for keyword in ("主角方", "主角阵营", "盟友", "战友", "同伴", "队友", "伙伴", "导师", "引路人", "护卫", "守护", "协作者", "向导", "助力")):
        return "主角方"
    return None


def _extract_story_stance_from_text(text: str | None) -> str | None:
    normalized_text = str(text or "").strip()
    if not normalized_text:
        return None
    for pattern in EXPLICIT_STORY_STANCE_PATTERNS:
        match = pattern.search(normalized_text)
        if match:
            return _normalize_story_stance_label(match.group(1))
    return None


def _infer_story_stance_from_evidence(role_position: str | None, summary: str | None, profile: str | None) -> str | None:
    texts = [str(value or "").strip() for value in (role_position, summary, profile) if str(value or "").strip()]
    if not texts:
        return None

    for text in texts:
        explicit = _extract_story_stance_from_text(text)
        if explicit:
            return explicit

    merged = "\n".join(texts)

    if any(phrase in merged for phrase in AMBIGUOUS_STORY_STANCE_PHRASES):
        return "亦正亦邪"
    if any(phrase in merged for phrase in PRO_STORY_STANCE_PHRASES):
        return "主角方"
    if any(phrase in merged for phrase in ANTI_STORY_STANCE_PHRASES):
        return "反派方"
    if any(phrase in merged for phrase in NEUTRAL_STORY_STANCE_PHRASES):
        return "中立方"

    for text in texts:
        if len(text) <= 40:
            normalized = _normalize_story_stance_label(text)
            if normalized:
                return normalized

    return None


def _looks_like_false_positive_antagonist(summary: str | None, profile: str | None) -> bool:
    merged = "\n".join(str(value or "").strip() for value in (summary, profile) if str(value or "").strip())
    if not merged:
        return False

    if not any(keyword in merged for keyword in ("唯一传人", "缔造者")):
        return False

    if any(
        keyword in merged
        for keyword in ("与主角冲突", "主要追捕者", "追捕林", "追杀", "围剿", "污名为", "夺取")
    ):
        return False

    return True


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("characters"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("characters")}
    required_columns = {"id", "role", "role_position", "summary", "profile"}
    if not required_columns.issubset(existing_columns):
        return

    characters = sa.table(
        "characters",
        sa.column("id", sa.Integer),
        sa.column("role", sa.String),
        sa.column("role_position", sa.String),
        sa.column("summary", sa.Text),
        sa.column("profile", sa.Text),
    )

    rows = bind.execute(
        sa.select(
            characters.c.id,
            characters.c.role,
            characters.c.role_position,
            characters.c.summary,
            characters.c.profile,
        ).where(characters.c.role.is_not(None))
    ).mappings().all()

    for row in rows:
        inferred = _infer_story_stance_from_evidence(
            row.get("role_position"),
            row.get("summary"),
            row.get("profile"),
        )
        current = row.get("role")
        if inferred and inferred != current:
            bind.execute(
                sa.update(characters)
                .where(characters.c.id == row["id"])
                .values(role=inferred)
            )
            continue

        if current == "反派方" and row.get("role_position") is None and _looks_like_false_positive_antagonist(
            row.get("summary"),
            row.get("profile"),
        ):
            bind.execute(
                sa.update(characters)
                .where(characters.c.id == row["id"])
                .values(role=None)
            )


def downgrade() -> None:
    # 纠偏迁移不做反向恢复，避免恢复成错误立场。
    return
