"""章节级人物动态状态快照服务（P2）

职责：
- 保存章节生成后的人物动态状态（当前目标/信念/情绪/关系/已知信息/变更记录）；
- 同一角色同一章节幂等（重复保存覆盖更新，不产生重复行）；
- 快照绝不写回 Character 基线列（基线与动态状态分离）。

后续 P3 的章节事件提取 / 生成后校验将通过本模块落库；
调用方只需传入结构化状态字段，JSON 序列化在本模块内完成。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("uvicorn.error")


def _to_json_text(value: Any) -> Optional[str]:
    """dict/list 序列化为 JSON 文本；None/空返回 None；纯文本原样返回。"""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    text = str(value).strip()
    return text or None


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def save_character_state_snapshot(
    db_session: Any,
    *,
    project_id: int,
    character_id: int,
    chapter_id: int,
    chapter_number: Optional[int] = None,
    current_motivation: Optional[str] = None,
    current_belief: Optional[str] = None,
    emotional_state: Optional[str] = None,
    relationship_state: Optional[Dict[str, Any]] = None,
    known_information: Optional[str] = None,
    state_changes: Optional[List[Dict[str, Any]]] = None,
    evidence_text: Optional[str] = None,
) -> Any:
    """保存（幂等）某个角色在某章节的动态状态快照。

    同一 (project_id, character_id, chapter_id) 已存在快照时覆盖更新，
    不生成重复行；快照只写 character_state_snapshots，不触碰 Character 基线列。
    """
    from app.models.character import CharacterStateSnapshot

    snapshot = (
        db_session.query(CharacterStateSnapshot)
        .filter(
            CharacterStateSnapshot.project_id == project_id,
            CharacterStateSnapshot.character_id == character_id,
            CharacterStateSnapshot.chapter_id == chapter_id,
        )
        .first()
    )

    fields = {
        "chapter_number": chapter_number,
        "current_motivation": _clean_text(current_motivation),
        "current_belief": _clean_text(current_belief),
        "emotional_state": _clean_text(emotional_state),
        "relationship_state_json": _to_json_text(relationship_state),
        "known_information": _clean_text(known_information),
        "state_changes_json": _to_json_text(state_changes),
        "evidence_text": _clean_text(evidence_text),
    }

    if snapshot is None:
        snapshot = CharacterStateSnapshot(
            project_id=project_id,
            character_id=character_id,
            chapter_id=chapter_id,
            **fields,
        )
        db_session.add(snapshot)
        logger.debug(
            "   📸 新建人物状态快照: character_id=%s chapter_id=%s",
            character_id,
            chapter_id,
        )
    else:
        for key, value in fields.items():
            setattr(snapshot, key, value)
        logger.debug(
            "   📸 覆盖人物状态快照: character_id=%s chapter_id=%s",
            character_id,
            chapter_id,
        )

    try:
        db_session.commit()
    except Exception as exc:  # pragma: no cover - 数据库异常兜底
        db_session.rollback()
        logger.error(
            "❌ 保存人物状态快照失败: character_id=%s chapter_id=%s error=%s",
            character_id,
            chapter_id,
            exc,
        )
        raise

    return snapshot


def get_character_state_snapshots(
    db_session: Any,
    project_id: int,
    character_id: int,
) -> List[Any]:
    """按章节号升序返回某角色的全部状态快照（用于恢复某一章节的人物状态）。"""
    from app.models.character import CharacterStateSnapshot

    return (
        db_session.query(CharacterStateSnapshot)
        .filter(
            CharacterStateSnapshot.project_id == project_id,
            CharacterStateSnapshot.character_id == character_id,
        )
        .order_by(
            CharacterStateSnapshot.chapter_number.is_(None).asc(),
            CharacterStateSnapshot.chapter_number.asc(),
            CharacterStateSnapshot.chapter_id.asc(),
        )
        .all()
    )


def get_latest_character_states_before_chapter(
    db_session: Any,
    project_id: int,
    before_chapter_number: int,
) -> Dict[int, Any]:
    """取每个角色在指定章节号之前的最新一条快照。

    返回 {character_id: snapshot}；无快照的角色不出现。
    """
    from sqlalchemy import func

    from app.models.character import CharacterStateSnapshot

    subquery = (
        db_session.query(
            CharacterStateSnapshot.character_id,
            func.max(CharacterStateSnapshot.chapter_number).label("max_chapter"),
        )
        .filter(
            CharacterStateSnapshot.project_id == project_id,
            CharacterStateSnapshot.chapter_number < before_chapter_number,
        )
        .group_by(CharacterStateSnapshot.character_id)
        .subquery()
    )

    rows = (
        db_session.query(CharacterStateSnapshot)
        .join(
            subquery,
            (CharacterStateSnapshot.character_id == subquery.c.character_id)
            & (CharacterStateSnapshot.chapter_number == subquery.c.max_chapter)
            & (CharacterStateSnapshot.project_id == project_id),
        )
        .all()
    )

    latest: Dict[int, Any] = {}
    for row in rows:
        current = latest.get(row.character_id)
        if current is None or (row.chapter_id or 0) >= (current.chapter_id or 0):
            latest[row.character_id] = row
    return latest


def build_character_state_context_from_snapshots(
    db_session: Any,
    *,
    project_id: int,
    before_chapter_number: int,
    max_characters: int = 6,
    max_length: int = 900,
) -> str:
    """把最新人物状态快照编译为写作上下文片段（读取端注入）。

    生成第 N 章时传入 before_chapter_number=N，注入第 N-1 章及更早的最新状态。
    无快照时返回空字符串。
    """
    from app.models.character import Character

    try:
        latest = get_latest_character_states_before_chapter(
            db_session, project_id, before_chapter_number
        )
    except Exception:
        return ""

    if not latest:
        return ""

    characters = (
        db_session.query(Character)
        .filter(Character.id.in_(list(latest.keys())))
        .all()
    )
    name_by_id = {char.id: (char.name or "").strip() for char in characters}

    lines: List[str] = []
    current_length = 0
    for character_id, snapshot in sorted(
        latest.items(),
        key=lambda item: name_by_id.get(item[0], "") or "",
    ):
        name = name_by_id.get(character_id)
        if not name:
            continue

        parts: List[str] = []
        if snapshot.current_motivation:
            parts.append(f"当前动机：{snapshot.current_motivation}")
        if snapshot.current_belief:
            parts.append(f"信念：{snapshot.current_belief}")
        if snapshot.emotional_state:
            parts.append(f"情绪：{snapshot.emotional_state}")
        if snapshot.relationship_state_json:
            parts.append(f"关系：{snapshot.relationship_state_json}")
        if snapshot.known_information:
            parts.append(f"已知信息：{snapshot.known_information}")
        if not parts:
            continue

        chapter_label = (
            f"第{snapshot.chapter_number}章" if snapshot.chapter_number is not None else "近期章节"
        )
        line = f"- {name}（{chapter_label}后）：{'；'.join(parts)}"
        projected = current_length + len(line) + (1 if lines else 0)
        if lines and projected > max_length:
            break
        lines.append(line)
        current_length = projected
        if len(lines) >= max_characters:
            break

    if not lines:
        return ""
    return "【人物当前状态】（优先承接最新状态，再遵循人物基线约束）\n" + "\n".join(lines)


def merge_character_state_context(
    state_context: Any,
    runtime_context: Any,
) -> str:
    """合并状态快照上下文与人物运行态上下文（动态状态在前，稳定基线在后）。"""
    state_text = str(state_context or "").strip()
    runtime_text = str(runtime_context or "").strip()
    if not state_text:
        return runtime_text
    if not runtime_text:
        return state_text
    return f"{state_text}\n\n{runtime_text}"
