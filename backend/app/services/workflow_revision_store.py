"""迭代过程落库：把每一轮修订稿与配套评审报告写入版本历史与评审表。

背景：迭代优化的中间稿与复评报告此前只存在于内存和日志里，章节一旦保存，
"第1轮改成什么样、为什么被丢弃、终稿评审说了什么"就再也查不到，复盘只能重跑工作流。
chapter_revisions 已被前端版本历史消费、reviews 已有整篇反馈字段，两表落库无需迁移。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.models.project import ChapterRevision
from app.models.review import Review
from app.services.prompts.narrative_quality import extract_unresolved_issues

logger = logging.getLogger("uvicorn.error")

# revision_note 列宽 500，超长直接截断
_REVISION_NOTE_LIMIT = 500
# 备注里最多列举的失败码条数，避免挤占评分与采用状态
_NOTE_FAILURE_CODE_LIMIT = 6

_ROUND_LABEL = "迭代第{round}轮"
_REVIEW_LABEL = "迭代第{round}轮复评"


def _word_count(content: str) -> int:
    """与章节保存口径一致：去掉空白后的字符数。"""
    return len(re.sub(r"\s", "", str(content or "")))


def _as_float(score: Any) -> Optional[float]:
    try:
        value = float(score)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return value


def _integer_score(score: Any) -> Optional[int]:
    """reviews.overall_score 是 1-10 整数列，精确分值留在版本备注里。"""
    value = _as_float(score)
    if value is None:
        return None
    return max(1, min(10, int(round(value))))


def _revision_note(
    *,
    label: str,
    score: Any,
    failure_codes: Sequence[str],
    adopted: bool,
) -> str:
    """版本备注回答三个问题：这是哪一轮的稿、当时多少分、本轮稿最后有没有被采用。"""
    parts = [label]
    value = _as_float(score)
    if value is not None:
        parts.append(f"评分{value:.1f}/10")
    codes = [str(code).strip() for code in (failure_codes or []) if str(code).strip()]
    parts.append(("失败码：" + "、".join(codes[:_NOTE_FAILURE_CODE_LIMIT])) if codes else "无剩余失败码")
    if not adopted:
        parts.append("本轮未采用")
    return "，".join(parts)[:_REVISION_NOTE_LIMIT]


def record_iteration_history(
    db: Session,
    *,
    chapter_id: int,
    initial_content: str = "",
    initial_review: str = "",
    initial_score: Any = None,
    rounds: Sequence[Mapping[str, Any]] = (),
    final_review: str = "",
    final_score: Any = None,
) -> Dict[str, int]:
    """登记迭代初稿、每轮修订稿与配套评审；任何失败只告警，不阻断章节产出。

    rounds 每条：round / content / review / score / failure_codes / adopted。
    """
    stats = {"revisions": 0, "reviews": 0}
    if not chapter_id:
        return stats

    revision_rows: List[ChapterRevision] = []
    review_entries: List[Tuple[str, str, Any]] = []
    try:
        if str(initial_content or "").strip():
            revision_rows.append(
                ChapterRevision(
                    chapter_id=chapter_id,
                    content=initial_content,
                    word_count=_word_count(initial_content),
                    revision_note=_revision_note(
                        label="迭代初稿", score=initial_score, failure_codes=(), adopted=True
                    ),
                )
            )
        if str(initial_review or "").strip():
            review_entries.append(("初评", str(initial_review), initial_score))

        for index, record in enumerate(rounds or [], start=1):
            content = str(record.get("content") or "")
            # 本轮没产出改稿（模型失败/被截断丢弃）时不留孤儿记录
            if not content.strip():
                continue
            round_no = record.get("round") or index
            revision_rows.append(
                ChapterRevision(
                    chapter_id=chapter_id,
                    content=content,
                    word_count=_word_count(content),
                    revision_note=_revision_note(
                        label=_ROUND_LABEL.format(round=round_no),
                        score=record.get("score"),
                        failure_codes=record.get("failure_codes") or [],
                        adopted=bool(record.get("adopted", True)),
                    ),
                )
            )
            review_text = str(record.get("review") or "")
            if review_text.strip():
                review_entries.append(
                    (_REVIEW_LABEL.format(round=round_no), review_text, record.get("score"))
                )

        recorded_texts = {text for _, text, _ in review_entries}
        final_text = str(final_review or "")
        if final_text.strip() and final_text not in recorded_texts:
            review_entries.append(("终稿评审", final_text, final_score))

        review_rows = [
            Review(
                chapter_id=chapter_id,
                overall_score=_integer_score(score),
                feedback=f"【{label}】\n{text}",
                suggestions="\n".join(extract_unresolved_issues(text)) or None,
            )
            for label, text, score in review_entries
        ]
        for row in [*revision_rows, *review_rows]:
            db.add(row)
        db.commit()
        stats = {"revisions": len(revision_rows), "reviews": len(review_rows)}
        logger.info(
            f"   🗂️ 迭代过程已落库：章节 {chapter_id} 版本 {stats['revisions']} 条、评审 {stats['reviews']} 条"
        )
    except Exception as exc:
        logger.warning(f"   ⚠️ 迭代过程落库失败（不影响本章产出）: {exc}")
        try:
            db.rollback()
        except Exception:
            pass
        stats = {"revisions": 0, "reviews": 0}
    return stats
