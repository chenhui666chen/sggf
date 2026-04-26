"""Outline expansion mixin."""
import json
import logging
import os
import re
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

from ..agents import CreativeDirectorAgent, PlotArchitectAgent, CharacterDesignerAgent
from core.langchain_bridge import create_task_llm, create_model_llm
from ..knowledge_base import NovelKnowledgeBase
from ..memory_manager import NovelMemoryManager
from ..agent_coordinator import GENRE_PROMPT_MODULES, DEFAULT_GENRE_MODULE, REALM_SPAN_WARNING_THRESHOLD, REALM_SPAN_RECOMMEND_SUBDIVISION
from ..layered_summarizer import LayeredSummarizer
from ...volume_connector import VolumeConnector
from ...foreshadowing_tracker import ForeshadowingTracker
from ...consistency_validator import ConsistencyValidator, get_consistency_validator, get_chapter_renumberer
from ..character_recognizer import CharacterRecognizer
from ..character_plot_validator import CharacterPlotValidator
from ...character_parser import (
    CharacterTextParser,
    ParsedCharacter,
    _build_ability_and_limit_text,
    _build_mainline_binding_text,
    _build_personality_anchor_text,
    _merge_parsed_character,
    normalize_character_name,
)
from ...character_runtime_context import build_character_prompt_context_from_text
from ._constants import *

class StoryHelperMixin:
    @staticmethod
    def estimate_volume_detail_model(chapters_count_range: Tuple[int, int]) -> str:
        """根据单卷章节规模估算更合适的细化模型。"""
        lower = 0
        upper = 0
        if isinstance(chapters_count_range, (list, tuple)) and len(chapters_count_range) >= 2:
            try:
                lower = max(0, int(chapters_count_range[0] or 0))
            except Exception:
                lower = 0
            try:
                upper = max(lower, int(chapters_count_range[1] or 0))
            except Exception:
                upper = lower
        # 🚀 统一使用 deepseek-v4-pro（384K 输出），不再按卷规模切换
        _ = upper  # 保留参数兼容性
        if upper > VOLUME_DETAIL_MODEL_SWITCH_THRESHOLD:
            return "qwen3.5-plus"
        return "deepseek-v4-pro"

    @staticmethod
    def _story_trim_volume_detail_preamble(volume_content: str) -> str:
        content = str(volume_content or "").strip()
        if not content:
            return ""

        for pattern in (
            r"(?m)^##\s*(?:(?:一|1)[、.．]?\s*)?(?:故事概述|本卷概述)\s*$",
            r"(?m)^##\s*(?:二|2)[、.．].*$",
        ):
            match = re.search(pattern, content)
            if match:
                return content[match.start():].lstrip()

        return content

    @staticmethod
    def _story_extract_json(text: str) -> Optional[Any]:
        if not text:
            return None
        content = str(text).strip()
        try:
            return json.loads(content)
        except Exception:
            pass

        for opener, closer in (("{", "}"), ("[", "]")):
            start = content.find(opener)
            end = content.rfind(closer)
            if start < 0 or end < start:
                continue
            candidate = content[start : end + 1]
            try:
                return json.loads(candidate)
            except Exception:
                continue
        return None

    @staticmethod
    def _story_stringify(value: Any, limit: int = 300) -> str:
        if value is None:
            return "N/A"
        if isinstance(value, str):
            text = value.strip()
        else:
            text = json.dumps(value, ensure_ascii=False)
        return text if len(text) <= limit else text[:limit] + "..."

    @staticmethod
    def _story_parse_outline_sections(outline: str) -> Dict[int, str]:
        sections: Dict[int, str] = {}
        if not outline or not outline.strip():
            return sections

        pattern = re.compile(r"(?m)^第\s*(\d+)\s*章[：:]\s*(.*)$")
        matches = list(pattern.finditer(outline))
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(outline)
            sections[int(match.group(1))] = outline[start:end].strip()
        return sections

    def _story_invoke_llm_json(
        self,
        llm: Any,
        system_prompt: str,
        user_prompt: str,
        fallback: Dict[str, Any],
    ) -> Dict[str, Any]:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            response = llm.invoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ]
            )
        except Exception:
            response = llm.invoke(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
            )
        parsed = self._story_extract_json(getattr(response, "content", response))
        return parsed if isinstance(parsed, dict) else fallback

    def _story_invoke_agent_json(self, agent: Any, prompt: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
        parsed = self._story_extract_json(agent.process(prompt, {}))
        return parsed if isinstance(parsed, dict) else fallback

    @staticmethod
    def _format_names(value: Any) -> str:
        if isinstance(value, list):
            return "、".join(str(item).strip() for item in value if str(item).strip())
        return str(value or "").strip()

    @staticmethod
    def _story_extract_character_names(text: str) -> List[str]:
        names: List[str] = []
        seen = set()
        for match in re.finditer(r"(?m)^(?:###\s*)?【姓名】[：:]\s*(.+?)\s*$", text or ""):
            name = match.group(1).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
        return names

    @staticmethod
    def _story_normalize_name(name: str) -> str:
        return re.sub(r"\s+", "", str(name or "").strip())

    @staticmethod
    def _story_truncate_text(text: Any, limit: int = 2000) -> str:
        content = str(text or "").strip()
        if not content:
            return ""
        return content if len(content) <= limit else content[:limit].rstrip() + "\n...(已截断)"

    @staticmethod
    def _story_match_volume_heading(line: str) -> Optional[int]:
        stripped = str(line or "").strip()
        if not stripped:
            return None

        arabic_patterns = (
            re.compile(r"^(?:#{1,6}\s*)?【第\s*(\d+)\s*卷】(?:\s*[《「『]?.*)?$"),
            re.compile(r"^(?:#{1,6}\s*)?(?:\*\*)?第\s*(\d+)\s*卷(?:\*\*)?(?:\s*[:：]\s*.*|\s+.+)?$"),
        )
        for pattern in arabic_patterns:
            match = pattern.match(stripped)
            if not match:
                continue
            try:
                volume_index = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if volume_index > 0:
                return volume_index

        cn_num_map = {
            "一": 1,
            "二": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
            "十一": 11,
            "十二": 12,
            "十三": 13,
            "十四": 14,
            "十五": 15,
            "十六": 16,
            "十七": 17,
            "十八": 18,
            "十九": 19,
            "二十": 20,
        }
        chinese_patterns = (
            re.compile(r"^(?:#{1,6}\s*)?【第\s*([一二三四五六七八九十]+)\s*卷】(?:\s*[《「『]?.*)?$"),
            re.compile(r"^(?:#{1,6}\s*)?(?:\*\*)?第\s*([一二三四五六七八九十]+)\s*卷(?:\*\*)?(?:\s*[:：]\s*.*|\s+.+)?$"),
        )
        for pattern in chinese_patterns:
            match = pattern.match(stripped)
            if not match:
                continue
            volume_index = cn_num_map.get(match.group(1).strip())
            if volume_index:
                return volume_index

        return None

    @staticmethod
    def _story_is_global_footer_heading(line: str) -> bool:
        stripped = str(line or "").strip()
        if not stripped:
            return False
        footer_patterns = (
            re.compile(r"^(?:#{1,6}\s*)?[四五六七八九十0-9]+[、.．，,]?\s*(关键伏笔|伏笔布局|核心人物|人物生命周期|人物关系|\w+周期)"),
            re.compile(r"^(?:#{1,6}\s*)?(关键伏笔|伏笔布局|核心人物|人物生命周期|人物关系|\w+周期)"),
        )
        return any(pattern.match(stripped) for pattern in footer_patterns)

    @classmethod
    def _story_list_volume_heading_positions(cls, framework_content: str) -> List[Tuple[int, int]]:
        positions: List[Tuple[int, int]] = []
        for line_index, line in enumerate(str(framework_content or "").splitlines()):
            volume_index = cls._story_match_volume_heading(line)
            if volume_index is None:
                continue
            positions.append((volume_index, line_index))
        return positions

    @classmethod
    def _story_extract_volume_block(cls, framework_content: str, target_volume_index: int) -> str:
        if not framework_content or target_volume_index <= 0:
            return ""

        lines = str(framework_content or "").splitlines()
        if not lines:
            return ""

        start_index: Optional[int] = None
        end_index = len(lines)

        for line_index, line in enumerate(lines):
            volume_index = cls._story_match_volume_heading(line)
            if volume_index == target_volume_index:
                start_index = line_index
                continue
            if start_index is None:
                continue
            if volume_index is not None or cls._story_is_global_footer_heading(line):
                end_index = line_index
                break

        if start_index is None:
            return ""

        return "\n".join(lines[start_index:end_index]).strip()

    @staticmethod
    def _story_has_parseable_volume_sections(framework_content: str) -> bool:
        if not framework_content or not framework_content.strip():
            return False
        if "待补充分卷规划" in framework_content:
            return False
        return bool(OutlineExpander._story_list_volume_heading_positions(framework_content))

    @classmethod
    def _story_list_parseable_volume_indexes(cls, framework_content: str) -> List[int]:
        indexes: List[int] = []
        seen: set[int] = set()
        for volume_index, _line_index in cls._story_list_volume_heading_positions(framework_content):
            if volume_index in seen:
                continue
            seen.add(volume_index)
            indexes.append(volume_index)
        return indexes

    @classmethod
    def _story_has_expected_volume_sections(cls, framework_content: str, total_volumes: int) -> bool:
        expected_total = max(1, int(total_volumes or 0))
        if expected_total <= 0:
            return cls._story_has_parseable_volume_sections(framework_content)
        found_indexes = cls._story_list_parseable_volume_indexes(framework_content)
        expected_indexes = list(range(1, expected_total + 1))
        return found_indexes == expected_indexes


