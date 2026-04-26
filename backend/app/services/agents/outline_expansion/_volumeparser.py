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

def _resolve_chapter_renumberer():
    try:
        from .. import outline_expander as outline_expander_module

        factory = getattr(outline_expander_module, "get_chapter_renumberer", None)
        if callable(factory):
            return factory()
    except Exception:
        pass
    return get_chapter_renumberer()


class VolumeParserMixin:
    @staticmethod
    def _story_count_rendered_volume_detail_chapters(volume_content: str) -> int:
        if not volume_content or not volume_content.strip():
            return 0
        return len(VolumeParserMixin._story_extract_rendered_volume_detail_chapter_numbers(volume_content))

    @staticmethod
    def _story_extract_volume_detail_main_section(volume_content: str) -> str:
        content = str(volume_content or "").strip()
        if not content:
            return ""

        code_fence_match = re.match(
            r"^\s*```(?:markdown|md|text)?\s*([\s\S]*?)\s*```\s*$",
            content,
            re.IGNORECASE,
        )
        if code_fence_match:
            content = code_fence_match.group(1).strip()

        detail_section_match = re.search(r"(?m)^##\s*(?:二|2)[、.．].*$", content)
        if detail_section_match:
            content = content[detail_section_match.start():]

        return re.split(r"(?m)^##\s*(?:三|3)[、.．].*$", content, maxsplit=1)[0].rstrip()

    @classmethod
    def _story_extract_rendered_volume_detail_chapter_numbers(cls, volume_content: str) -> List[int]:
        content = cls._story_extract_volume_detail_main_section(volume_content) or str(volume_content or "").strip()
        if not content:
            return []

        seen: set[int] = set()
        chapter_numbers: List[int] = []
        for match in VOLUME_DETAIL_CHAPTER_HEADING_PATTERN.finditer(content):
            try:
                chapter_number = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if chapter_number in seen:
                continue
            seen.add(chapter_number)
            chapter_numbers.append(chapter_number)
        return chapter_numbers

    @classmethod
    def _story_extract_rendered_volume_detail_chapter_range(
        cls,
        volume_content: str,
    ) -> Tuple[int, int]:
        chapter_numbers = cls._story_extract_rendered_volume_detail_chapter_numbers(volume_content)
        if not chapter_numbers:
            return (0, 0)
        return (chapter_numbers[0], chapter_numbers[-1])

    @staticmethod
    def _story_expected_volume_detail_chapter_end(
        *,
        start_chapter_num: int,
        chapters_count_range: Tuple[int, int],
    ) -> int:
        try:
            expected_start = max(1, int(start_chapter_num or 1))
        except Exception:
            expected_start = 1
        try:
            expected_lower_count = max(1, int(chapters_count_range[0] or 1))
        except Exception:
            expected_lower_count = 1
        try:
            expected_upper_count = max(expected_lower_count, int(chapters_count_range[1] or expected_lower_count))
        except Exception:
            expected_upper_count = expected_lower_count
        return expected_start + max(0, expected_upper_count - 1)

    @classmethod
    def _story_find_volume_detail_range_shortcuts(
        cls,
        volume_content: str,
        *,
        start_chapter_num: int,
        chapters_count_range: Tuple[int, int],
    ) -> List[Tuple[int, int]]:
        content = cls._story_extract_volume_detail_main_section(volume_content)
        if not content:
            return []

        try:
            expected_start = max(1, int(start_chapter_num or 1))
        except Exception:
            expected_start = 1
        expected_end = cls._story_expected_volume_detail_chapter_end(
            start_chapter_num=expected_start,
            chapters_count_range=chapters_count_range,
        )
        rendered_chapter_numbers = cls._story_extract_rendered_volume_detail_chapter_numbers(content)
        rendered_chapters = set(rendered_chapter_numbers)
        actual_chapter_count = len(rendered_chapter_numbers)
        try:
            required_min_count = max(1, int(chapters_count_range[0] or 1))
        except Exception:
            required_min_count = 1
        last_rendered_chapter = rendered_chapter_numbers[-1] if rendered_chapter_numbers else expected_start - 1
        shortcuts: List[Tuple[int, int]] = []

        for pattern in (VOLUME_DETAIL_RANGE_SHORTCUT_PATTERN, VOLUME_DETAIL_GROUP_RANGE_PATTERN):
            for match in pattern.finditer(content):
                try:
                    range_start = int(match.group("start"))
                    range_end = int(match.group("end"))
                except (TypeError, ValueError):
                    continue
                if range_end < range_start:
                    range_start, range_end = range_end, range_start

                overlap_start = max(range_start, expected_start)
                overlap_end = min(range_end, expected_end)
                if overlap_start > overlap_end:
                    continue

                missing_numbers = [
                    chapter_number
                    for chapter_number in range(overlap_start, overlap_end + 1)
                    if chapter_number not in rendered_chapters
                ]
                if not missing_numbers:
                    continue
                if (
                    actual_chapter_count >= required_min_count
                    and all(chapter_number > last_rendered_chapter for chapter_number in missing_numbers)
                ):
                    continue

                shortcut = (range_start, range_end)
                if shortcut not in shortcuts:
                    shortcuts.append(shortcut)

        return shortcuts

    @classmethod
    def _story_extract_volume_detail_chapter_block_map(
        cls,
        volume_content: str,
        *,
        min_chapter_number: int = 1,
        max_chapter_number: Optional[int] = None,
    ) -> Dict[int, str]:
        content = cls._story_extract_volume_detail_main_section(volume_content) or str(volume_content or "").strip()
        if not content:
            return {}

        matches = list(VOLUME_DETAIL_CHAPTER_HEADING_PATTERN.finditer(content))
        blocks: Dict[int, str] = {}
        min_number = max(1, int(min_chapter_number or 1))
        max_number = int(max_chapter_number) if max_chapter_number is not None else None
        for index, match in enumerate(matches):
            try:
                chapter_number = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if chapter_number < min_number:
                continue
            if max_number is not None and chapter_number > max_number:
                continue
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            block = content[start:end].strip()
            if block:
                blocks[chapter_number] = block
        return blocks

    @classmethod
    def _story_extract_missing_volume_detail_chapter_ranges(
        cls,
        volume_content: str,
        *,
        start_chapter_num: int,
        chapters_count_range: Tuple[int, int],
    ) -> List[Tuple[int, int]]:
        try:
            expected_start = max(1, int(start_chapter_num or 1))
        except Exception:
            expected_start = 1
        expected_end = cls._story_expected_volume_detail_chapter_end(
            start_chapter_num=expected_start,
            chapters_count_range=chapters_count_range,
        )
        rendered_chapters = set(cls._story_extract_rendered_volume_detail_chapter_numbers(volume_content))
        missing_numbers = [
            chapter_number
            for chapter_number in range(expected_start, expected_end + 1)
            if chapter_number not in rendered_chapters
        ]
        if not missing_numbers:
            return []

        ranges: List[Tuple[int, int]] = []
        range_start = missing_numbers[0]
        range_end = missing_numbers[0]
        for chapter_number in missing_numbers[1:]:
            if chapter_number == range_end + 1:
                range_end = chapter_number
                continue
            ranges.append((range_start, range_end))
            range_start = chapter_number
            range_end = chapter_number
        ranges.append((range_start, range_end))
        return ranges

    @staticmethod
    def _story_chunk_volume_detail_chapter_ranges(
        missing_ranges: List[Tuple[int, int]],
        *,
        chunk_size: int = 15,
    ) -> List[Tuple[int, int]]:
        normalized_chunk_size = max(1, int(chunk_size or 1))
        chunked_ranges: List[Tuple[int, int]] = []
        for range_start, range_end in missing_ranges:
            current_start = int(range_start)
            current_end = int(range_end)
            while current_start <= current_end:
                chunk_end = min(current_end, current_start + normalized_chunk_size - 1)
                chunked_ranges.append((current_start, chunk_end))
                current_start = chunk_end + 1
        return chunked_ranges

    @classmethod
    def _story_split_volume_detail_content(
        cls,
        volume_content: str,
    ) -> Tuple[str, str]:
        content = str(volume_content or "").strip()
        if not content:
            return "", ""

        code_fence_match = re.match(
            r"^\s*```(?:markdown|md|text)?\s*([\s\S]*?)\s*```\s*$",
            content,
            re.IGNORECASE,
        )
        if code_fence_match:
            content = code_fence_match.group(1).strip()

        tail_match = re.search(r"(?m)^##\s*(?:三|3)[、.．].*$", content)
        if tail_match:
            main_content = content[: tail_match.start()].rstrip()
            tail_content = content[tail_match.start() :].lstrip()
        else:
            main_content = content.rstrip()
            tail_content = ""

        matches = list(VOLUME_DETAIL_CHAPTER_HEADING_PATTERN.finditer(main_content))
        if matches:
            head_content = main_content[: matches[0].start()].rstrip()
        else:
            head_content = main_content.rstrip()

        return head_content, tail_content

    @classmethod
    def _story_strip_volume_detail_range_shortcut_lines(cls, volume_content: str) -> str:
        content = str(volume_content or "").strip()
        if not content:
            return ""

        cleaned_lines: List[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                cleaned_lines.append(line)
                continue
            if stripped.startswith("##") or VOLUME_DETAIL_CHAPTER_HEADING_PATTERN.search(stripped):
                cleaned_lines.append(line)
                continue
            if VOLUME_DETAIL_RANGE_SHORTCUT_PATTERN.search(stripped) or VOLUME_DETAIL_GROUP_RANGE_PATTERN.search(stripped):
                continue
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines).strip()

    @staticmethod
    def _story_extract_volume_detail_chapter_blocks(
        volume_content: str,
        *,
        min_chapter_number: int = 1,
    ) -> str:
        block_map = VolumeParserMixin._story_extract_volume_detail_chapter_block_map(
            volume_content,
            min_chapter_number=min_chapter_number,
        )
        return "\n\n".join(block_map[number] for number in sorted(block_map))

    @classmethod
    def _story_merge_volume_detail_supplement(
        cls,
        base_content: str,
        supplement_content: str,
        *,
        next_chapter_number: int,
        max_chapter_number: Optional[int] = None,
    ) -> str:
        base_text = str(base_content or "").strip()
        if not base_text:
            return base_text

        supplement_text = str(supplement_content or "").strip()
        if not supplement_text:
            return base_text

        supplement_block_map = cls._story_extract_volume_detail_chapter_block_map(
            supplement_text,
            min_chapter_number=next_chapter_number,
            max_chapter_number=max_chapter_number,
        )
        if not supplement_block_map:
            try:
                expected_max_count = (
                    max(1, int(max_chapter_number or next_chapter_number) - int(next_chapter_number) + 1)
                    if max_chapter_number is not None
                    else 20
                )
            except Exception:
                expected_max_count = 20
            renumber_result = _resolve_chapter_renumberer().detect_and_fix(
                content=supplement_text,
                expected_start=next_chapter_number,
                expected_count_range=(1, expected_max_count),
            )
            supplement_block_map = cls._story_extract_volume_detail_chapter_block_map(
                renumber_result.get("fixed_content") or supplement_text,
                min_chapter_number=next_chapter_number,
                max_chapter_number=max_chapter_number,
            )
        if not supplement_block_map:
            return base_text

        base_block_map = cls._story_extract_volume_detail_chapter_block_map(base_text)
        merged_block_map = dict(base_block_map)
        merged_block_map.update(supplement_block_map)

        head_content, tail_content = cls._story_split_volume_detail_content(base_text)
        head_content = cls._story_strip_volume_detail_range_shortcut_lines(head_content)
        chapter_blocks = "\n\n".join(
            merged_block_map[number]
            for number in sorted(merged_block_map)
        ).strip()

        parts: List[str] = []
        if head_content:
            parts.append(head_content.strip())
        if chapter_blocks:
            parts.append(chapter_blocks)
        if tail_content:
            parts.append(tail_content.strip())
        return "\n\n".join(part for part in parts if part).strip()


