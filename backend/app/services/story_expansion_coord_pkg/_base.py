from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from core.langchain_bridge import create_task_llm
from app.services.character_parser import (
    _build_ability_and_limit_text,
    _build_mainline_binding_text,
    _build_personality_anchor_text,
)
from app.services.story_text_utils import (
    normalize_story_text,
    parse_chapter_number_token,
)
from app.services.story_expansion_coord_pkg._standalone import (
    OutlineBlock,
    normalize_character_name,
    parse_outline_blocks,
    render_outline,
    render_outline_with_original_numbers,
    normalize_outline_title,
    _same_outline_value,
    _extract_outline_body_fields,
    _normalize_outline_character_list,
    _extract_outline_involved_characters,
    _normalize_key_event_lines,
    _summarize_key_events,
    normalize_outline_text,
    extract_character_names,
    extract_character_blocks,
    build_delta_section_title,
    merge_character_delta,
    build_outline_delta_section,
    sanitize_outline_alignment_placeholders,
    is_character_alignment_placeholder_line,
    _safe_float,
    evaluate_story_coordination,
    CHINESE_CHAPTER_NUMBER_PATTERN,
    CHAPTER_HEADING_PATTERN,
    CHARACTER_NAME_PATTERN,
    LEGACY_ALIGNMENT_PLACEHOLDER_PATTERN,
    OUTLINE_ROUND_SECTION_HEADING_PATTERN,
    OUTLINE_FIELD_ALIASES,
    OUTLINE_FIELD_LINE_PATTERN,
)

logger = logging.getLogger(__name__)

class StoryExpansionCoordinatorBase:
    def __init__(
        self,
        project_id: Optional[int] = None,
        genre: str = "",
        planned_chapters_max: int = 0,
    ) -> None:
        self.project_id = project_id
        self.genre = genre or ""
        try:
            self.planned_chapters_max = max(0, int(planned_chapters_max or 0))
        except Exception:
            self.planned_chapters_max = 0

        # 🔥 动态模型选择：根据计划章节数选择合适的模型
        if self.planned_chapters_max > self.SUPER_LARGE_PROJECT_CHAPTER_THRESHOLD:
            # 超大规模项目（>200章）：使用 qwen3.5-plus（65K输出能力）
            model_type = "outline_expand"  # qwen3.5-plus
            logger.debug(f"🔄 检测到超大规模项目（{self.planned_chapters_max}章），使用 qwen3.5-plus 模型")
        elif self.planned_chapters_max > self.LARGE_PROJECT_CHAPTER_THRESHOLD:
            # 大规模项目（100-200章）：使用 deepseek-reasoner（推理能力强）
            model_type = "volume_detail_expand"  # deepseek-reasoner
            logger.debug(f"✅ 检测到大规模项目（{self.planned_chapters_max}章），使用 deepseek-reasoner 模型")
        else:
            # 常规项目（≤100章）：使用 qwen3.5-plus（输出能力强）
            model_type = "outline_expand"  # qwen3.5-plus
            logger.debug(f"✅ 常规项目（{self.planned_chapters_max}章），使用 qwen3.5-plus 模型")

        self.planner_llm = create_task_llm(task_type=model_type, temperature=0.2)
        self.writer_llm = create_task_llm(task_type=model_type, temperature=0.45)
        self._outline_expander: Optional[Any] = None

    def _invoke_text(self, prompt: str, *, use_planner: bool = False) -> str:
        llm = self.planner_llm if use_planner else self.writer_llm
        response = llm.invoke(prompt)
        return response.content if hasattr(response, "content") else str(response)

    def _invoke_json(self, prompt: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
        raw_text = self._invoke_text(prompt, use_planner=True)
        parsed = self._extract_json(raw_text)
        if isinstance(parsed, dict):
            return parsed
        return fallback

    @staticmethod
    def _extract_json(text: str) -> Optional[Any]:
        if not text:
            return None

        text = text.strip()
        for candidate in (text, *re.findall(r"\{[\s\S]*\}", text)):
            try:
                return json.loads(candidate)
            except Exception:
                continue
        return None

    @staticmethod
    def _summarize_outline_blocks(blocks: List[OutlineBlock], limit: int = 60) -> str:
        if not blocks:
            return "暂无已分章内容"
        lines = []
        for block in blocks[:limit]:
            title = block.title or "未命名章节"
            lines.append(f"- 第{block.original_number}章：{title}")
        if len(blocks) > limit:
            lines.append(f"- ……其余 {len(blocks) - limit} 章已省略")
        return "\n".join(lines)

    @staticmethod
    def _normalize_outline_ops(
        outline_ops: List[Dict[str, Any]],
        chapters_needed: int,
        current_chapter_count: int,
    ) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        remaining = max(0, chapters_needed)

        for raw_op in outline_ops:
            if remaining <= 0:
                break

            action = str(raw_op.get("action") or "append").strip()
            if action not in {"append", "insert_after"}:
                action = "append"

            try:
                count = int(raw_op.get("count") or 0)
            except Exception:
                count = 0

            if count <= 0:
                continue

            count = min(count, remaining)
            after_chapter = raw_op.get("after_chapter")
            if action == "append":
                after_chapter = current_chapter_count if current_chapter_count > 0 else None
            else:
                try:
                    after_chapter = int(after_chapter)
                except Exception:
                    after_chapter = current_chapter_count if current_chapter_count > 0 else None
                if current_chapter_count <= 0:
                    action = "append"
                    after_chapter = None
                else:
                    after_chapter = max(1, min(current_chapter_count, after_chapter))

            normalized.append(
                {
                    "action": action,
                    "after_chapter": after_chapter,
                    "count": count,
                    "goal": str(raw_op.get("goal") or "补充关键剧情推进").strip(),
                    "focus_characters": list(raw_op.get("focus_characters") or []),
                    "notes": str(raw_op.get("notes") or "").strip(),
                }
            )
            remaining -= count

        if remaining > 0:
            normalized.append(
                {
                    "action": "append",
                    "after_chapter": current_chapter_count if current_chapter_count > 0 else None,
                    "count": remaining,
                    "goal": "补充新增章节并延续主线",
                    "focus_characters": [],
                    "notes": "自动补足缺失章节数",
                }
            )

        return normalized

    def _get_expander(self) -> Any:
        if self._outline_expander is None:
            from .agents.outline_expander import create_outline_expander

            self._outline_expander = create_outline_expander(
                genre=self.genre,
                planned_chapters_max=self.planned_chapters_max,
                project_id=self.project_id,
            )
        return self._outline_expander

    @staticmethod
    def _get_llm_model_name(llm: Any, fallback: str = "unknown") -> str:
        return (
            getattr(llm, "model_name", None)
            or getattr(llm, "model", None)
            or fallback
        )

    @staticmethod
    def _coerce_non_negative_int(value: Any, fallback: int = 0) -> int:
        try:
            return max(0, int(value))
        except Exception:
            return max(0, int(fallback or 0))

    @classmethod
    def _resolve_outline_count(
        cls,
        outline_text: str,
        reported_count: Any,
        fallback_count: int,
    ) -> int:
        _, blocks = parse_outline_blocks(outline_text or "")
        parsed_max_number = max((int(block.original_number or 0) for block in blocks), default=0)
        fallback_value = cls._coerce_non_negative_int(fallback_count)
        reported_value = cls._coerce_non_negative_int(reported_count)
        if parsed_max_number > 0:
            return max(fallback_value, parsed_max_number)
        return max(fallback_value, reported_value)

    @classmethod
    def _resolve_character_count(
        cls,
        characters_text: str,
        reported_count: Any,
        fallback_count: int,
    ) -> int:
        parsed_count = len(extract_character_names(characters_text or ""))
        fallback_value = cls._coerce_non_negative_int(fallback_count)
        reported_value = cls._coerce_non_negative_int(reported_count)
        if parsed_count > 0:
            return max(fallback_value, parsed_count)
        return max(fallback_value, reported_value)

