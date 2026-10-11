"""章节人物动态状态提取服务（闭环写入端）。

职责：
- 章节保存后，用 LLM 从章节正文提取出场人物的动态状态
  （当前动机/信念/情绪/关系变化/已知信息/证据）；
- 经 save_character_state_snapshot 幂等落库（character_state_snapshots）；
- 供下一章生成时通过 build_character_state_context_from_snapshots 注入。

提取失败（LLM 异常/JSON 损坏）返回空结果或空统计，绝不阻断章节后处理。
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from core.langchain_bridge import create_model_llm
from app.services.exact_model_guard import require_exact_model

logger = logging.getLogger("uvicorn.error")


class CharacterStateExtractionService:
    """章节人物动态状态提取器"""

    @staticmethod
    async def extract_character_states_from_chapter(
        chapter_title: str,
        chapter_content: str,
        project_id: int,
        character_names: List[str],
        model: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """从章节正文提取指定人物的动态状态。

        Returns:
            [{"name", "current_motivation", "current_belief", "emotional_state",
              "relationship_state", "known_information", "state_changes", "evidence"}]
            失败时返回 []。
        """
        names = [str(name).strip() for name in (character_names or []) if str(name).strip()]
        content = str(chapter_content or "").strip()
        if not names or not content:
            return []

        model_id = require_exact_model(model) or (
            os.getenv("CHARACTER_STATE_EXTRACTION_MODEL")
            or os.getenv("UNIFIED_EXTRACTION_MODEL")
            or os.getenv("DEEPSEEK_MODEL")
            or os.getenv("MODEL_NAME")
            or "deepseek-pro"
        )
        llm = create_model_llm(model=model_id, temperature=0.3)

        prompt = f"""你是小说人物状态分析师。请根据章节内容，提取出场人物在本章结束时的动态状态。

【出场人物】
{'、'.join(names)}

【章节标题】
{str(chapter_title or '').strip()}

【章节内容】
{content[:6000]}

请只为状态有实际变化或信息更新的人物输出记录，JSON 数组格式：
[
  {{
    "name": "人物名（必须是出场人物之一）",
    "current_motivation": "本章结束时的当前目标/动机",
    "current_belief": "当前信念/判断",
    "emotional_state": "情绪状态",
    "relationship_state": {{"对方名字": "关系变化描述"}},
    "known_information": "本章获知的关键新信息",
    "state_changes": [{{"field": "motivation", "from": "旧值", "to": "新值"}}],
    "evidence": "支撑判断的原文片段（50字内）"
  }}
]

要求：
1. 只输出出场人物列表中的人物，其他人物一律不输出
2. 状态没有实质变化的人物不要输出
3. state_changes 记录相对上一状态的变化，无变化时为空数组
4. 确保返回的是合法 JSON 数组，不要输出其他说明文字"""

        try:
            response = await llm.ainvoke(prompt)
            raw = response.content if hasattr(response, "content") else str(response)
        except Exception as exc:
            logger.warning("人物状态提取 LLM 调用失败: %s", exc)
            return []

        cleaned = re.sub(r"```json\s*", "", str(raw))
        cleaned = re.sub(r"```\s*$", "", cleaned).strip()
        try:
            result = json.loads(cleaned)
        except Exception:
            logger.warning("人物状态提取返回内容不是合法 JSON，已跳过")
            return []

        if not isinstance(result, list):
            return []

        known_names = set(names)
        validated: List[Dict[str, Any]] = []
        for item in result:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name not in known_names:
                continue
            validated.append(
                {
                    "name": name,
                    "current_motivation": str(item.get("current_motivation") or "").strip(),
                    "current_belief": str(item.get("current_belief") or "").strip(),
                    "emotional_state": str(item.get("emotional_state") or "").strip(),
                    "relationship_state": item.get("relationship_state")
                    if isinstance(item.get("relationship_state"), dict)
                    else {},
                    "known_information": str(item.get("known_information") or "").strip(),
                    "state_changes": item.get("state_changes")
                    if isinstance(item.get("state_changes"), list)
                    else [],
                    "evidence": str(item.get("evidence") or "").strip(),
                }
            )
        return validated


async def run_character_state_extraction_flow(
    db_session: Any,
    *,
    project_id: int,
    chapter_id: int,
    chapter_number: int,
    chapter_title: str,
    chapter_content: str,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """章节保存后的人物状态提取落库流程（闭环写入端）。

    查询项目角色 → LLM 提取 → 幂等保存快照。
    任何失败只记录日志并返回空统计，不抛异常（调用方另有兜底）。
    """
    result: Dict[str, Any] = {"extracted": 0, "saved": 0}

    try:
        from app.models.character import Character
        from app.services.character_state_snapshot import save_character_state_snapshot

        characters = (
            db_session.query(Character)
            .filter(
                Character.project_id == project_id,
                Character.archived_at.is_(None),
            )
            .all()
        )
        if not characters:
            return result

        name_to_id = {
            (char.name or "").strip(): char.id for char in characters if (char.name or "").strip()
        }
        if not name_to_id:
            return result

        states = await CharacterStateExtractionService.extract_character_states_from_chapter(
            chapter_title=chapter_title,
            chapter_content=chapter_content,
            project_id=project_id,
            character_names=list(name_to_id.keys()),
            model=model,
        )
        result["extracted"] = len(states)

        for state in states:
            character_id = name_to_id.get(state["name"])
            if character_id is None:
                continue
            save_character_state_snapshot(
                db_session,
                project_id=project_id,
                character_id=character_id,
                chapter_id=chapter_id,
                chapter_number=chapter_number,
                current_motivation=state["current_motivation"] or None,
                current_belief=state["current_belief"] or None,
                emotional_state=state["emotional_state"] or None,
                relationship_state=state["relationship_state"] or None,
                known_information=state["known_information"] or None,
                state_changes=state["state_changes"] or None,
                evidence_text=state["evidence"] or None,
            )
            result["saved"] += 1

        if result["saved"] > 0:
            logger.info(
                f"   📸 人物状态快照已保存：第{chapter_number}章 "
                f"{result['saved']} 个角色（提取 {result['extracted']} 条）"
            )
    except Exception as exc:
        logger.warning(f"   ⚠️ 人物状态提取落库失败（不影响主流程）: {exc}")

    return result
