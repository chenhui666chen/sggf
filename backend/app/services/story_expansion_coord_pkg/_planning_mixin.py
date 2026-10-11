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

class PlanningMixin:
    @classmethod
    def _build_total_mode_suitability(
        cls,
        *,
        current_chapter_count: int,
        target_chapter_count: int,
        chapters_needed: int,
        execution_mode: str,
    ) -> Dict[str, Any]:
        recommended_upper = cls.CONVENTIONAL_COLLABORATION_RECOMMENDED_MAX_CHAPTERS
        caution_lower = cls.FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD
        absolute_upper = cls.CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS
        effective_total = max(current_chapter_count, target_chapter_count)

        if effective_total > absolute_upper:
            request_band = "forbidden"
            request_band_label = "禁止常规协同"
            request_band_reason = (
                f"当前目标已超过常规协同硬上限 {absolute_upper} 章。"
                "必须改用长篇框架协同。"
            )
        elif effective_total >= caution_lower:
            request_band = "caution"
            request_band_label = "可执行但建议转框架"
            request_band_reason = (
                f"当前目标已进入 {caution_lower}-{absolute_upper} 章区间。"
                "常规协同仍可执行，但更建议先切换到长篇框架协同，再按卷滚动细化。"
            )
        else:
            request_band = "recommended"
            request_band_label = "推荐区间"
            request_band_reason = "当前目标仍在常规协同的稳定工作带内，适合直接进行单轮或分轮扩展。"

        summary = (
            f"常规协同推荐总规模不超过 {recommended_upper} 章；"
            f"{caution_lower}-{absolute_upper} 章仍可执行，但更建议先切换到长篇框架协同；"
            f"超过 {absolute_upper} 章后必须切换。"
        )

        return {
            "mode": "total",
            "request_band": request_band,
            "request_band_label": request_band_label,
            "request_band_reason": request_band_reason,
            "current_total_chapters": current_chapter_count,
            "target_total_chapters": target_chapter_count,
            "chapters_needed": chapters_needed,
            "execution_mode": execution_mode,
            "recommended_total_chapters_max": recommended_upper,
            "caution_total_chapters_min": caution_lower,
            "caution_total_chapters_max": absolute_upper,
            "framework_preferred_total_from": caution_lower,
            "epic_auto_switch_total_from": cls.EPIC_CHAPTER_THRESHOLD,
            "preferred_iterative_step": cls.ITERATIVE_CHAPTER_STEP,
            "single_round_delta_limit": cls.SHORT_CHAPTER_DELTA_LIMIT,
            "summary": summary,
            "bands": [
                {
                    "key": "recommended",
                    "label": "推荐区间",
                    "range_text": f"总规模 1-{recommended_upper} 章",
                    "detail": f"单次新增建议按 {cls.ITERATIVE_CHAPTER_STEP} 章左右推进，质量和稳定性更均衡。",
                },
                {
                    "key": "caution",
                    "label": "可执行但建议转框架",
                    "range_text": f"总规模 {caution_lower}-{absolute_upper} 章",
                    "detail": "仍可直接发起常规协同，但更建议先切换到长篇框架协同，再按卷滚动细化。",
                },
                {
                    "key": "forbidden",
                    "label": "禁止常规协同",
                    "range_text": f"总规模 >= {absolute_upper + 1} 章",
                    "detail": f"超过 {absolute_upper} 章后必须改用长篇框架协同，不能继续走常规协同。",
                },
            ],
        }

    @classmethod
    def _estimate_execution_rounds_from_mode_info(cls, mode_info: Dict[str, Any]) -> int:
        mode = str(mode_info.get("mode") or "delta").strip()
        chapters_needed = max(0, int(mode_info.get("chapters_needed") or 0))
        characters_needed = max(0, int(mode_info.get("characters_needed") or 0))

        if mode == "volume_detail":
            character_rounds = (characters_needed + cls.ITERATIVE_CHARACTER_STEP - 1) // cls.ITERATIVE_CHARACTER_STEP
            return min(cls.ITERATIVE_MAX_ROUNDS, max(1, 1 + character_rounds))
        if mode == "epic":
            # 长篇框架协同在一次任务内完成框架生成与必要的人物补足，
            # 不应按“分轮协同”展示为多轮任务。
            return 1
        if mode == "iterative":
            chapter_rounds = (chapters_needed + cls.ITERATIVE_CHAPTER_STEP - 1) // cls.ITERATIVE_CHAPTER_STEP
            character_rounds = (characters_needed + cls.ITERATIVE_CHARACTER_STEP - 1) // cls.ITERATIVE_CHARACTER_STEP
            return min(cls.ITERATIVE_MAX_ROUNDS, max(1, max(chapter_rounds, character_rounds)))
        return 1

    @classmethod
    def _estimate_duration_minutes_range_from_mode_info(
        cls,
        mode_info: Dict[str, Any],
        estimated_rounds: int,
    ) -> Tuple[int, int]:
        mode = str(mode_info.get("mode") or "delta").strip()
        current_chapter_count = max(0, int(mode_info.get("current_chapter_count") or 0))
        target_chapter_count = max(
            current_chapter_count,
            int(mode_info.get("target_chapter_count") or current_chapter_count),
        )
        current_character_count = max(0, int(mode_info.get("current_character_count") or 0))
        target_character_count = max(
            current_character_count,
            int(mode_info.get("target_character_count") or current_character_count),
        )
        chapter_delta = max(0, target_chapter_count - current_chapter_count)
        character_delta = max(0, target_character_count - current_character_count)
        rounds = max(1, int(estimated_rounds or 1))

        if mode == "iterative":
            min_estimate = 4.0 + rounds * 2.2 + max(0, character_delta - 5) * 0.15
            max_estimate = 8.0 + rounds * 3.3 + max(0, character_delta - 5) * 0.25
        elif mode == "epic":
            epic_total_volumes = max(
                cls.EPIC_MIN_VOLUMES,
                int(
                    mode_info.get("epic_total_volumes")
                    or math.ceil(
                        max(target_chapter_count, cls.EPIC_CHAPTER_THRESHOLD)
                        / cls.EPIC_DEFAULT_CHAPTERS_PER_VOLUME
                    )
                ),
            )
            min_estimate = (
                3.0
                + epic_total_volumes * 0.25
                + max(0, target_chapter_count - cls.CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS) * 0.002
                + max(0, character_delta - 8) * 0.08
            )
            max_estimate = (
                6.0
                + epic_total_volumes * 0.4
                + max(0, target_chapter_count - cls.CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS) * 0.004
                + max(0, character_delta - 8) * 0.15
            )
        elif mode == "volume_detail":
            volume_range = mode_info.get("volume_chapter_range")
            if isinstance(volume_range, (list, tuple)) and len(volume_range) == 2:
                try:
                    volume_span = max(1, int(volume_range[1]) - int(volume_range[0]) + 1)
                except Exception:
                    volume_span = max(1, chapter_delta or cls.ITERATIVE_CHAPTER_STEP)
            else:
                volume_span = max(1, chapter_delta or cls.ITERATIVE_CHAPTER_STEP)

            min_estimate = 7.0 + volume_span * 0.2 + character_delta * 0.4
            max_estimate = 12.0 + volume_span * 0.35 + character_delta * 0.6
        else:
            min_estimate = 4.0 + chapter_delta * 0.18 + character_delta * 0.25
            max_estimate = 7.0 + chapter_delta * 0.28 + character_delta * 0.4

        min_minutes = max(5, int(math.ceil(min_estimate)))
        max_minutes = max(min_minutes + 3, int(math.ceil(max_estimate)))
        return min_minutes, max_minutes

    @staticmethod
    def _normalize_expansion_mode(expansion_mode: str) -> str:
        normalized = str(expansion_mode or "auto").strip()
        if normalized in {"auto", "total", "epic_framework", "volume_detail"}:
            return normalized
        return "auto"

    @staticmethod
    def _normalize_epic_config(epic_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {
            "total_volumes": None,
            "chapter_range": None,
        }
        if not isinstance(epic_config, dict):
            return normalized

        total_volumes = epic_config.get("total_volumes")
        if total_volumes is not None:
            try:
                normalized["total_volumes"] = max(1, int(total_volumes))
            except Exception:
                normalized["total_volumes"] = None

        chapter_range = epic_config.get("chapter_range")
        if isinstance(chapter_range, (list, tuple)) and len(chapter_range) == 2:
            try:
                lower = max(1, int(chapter_range[0]))
                upper = max(lower, int(chapter_range[1]))
                normalized["chapter_range"] = (lower, upper)
            except Exception:
                normalized["chapter_range"] = None

        return normalized

    @staticmethod
    def _normalize_volume_detail_config(
        volume_detail_config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {
            "framework_content": "",
            "target_volume_index": None,
            "chapters_count_range": None,
            "start_chapter_num": None,
            "framework_header": "",
            "framework_footer": "",
            "volumes_data": None,
            "previous_volume_detail": "",
            "existing_volume_detail": "",
            "planned_chapter_count": None,
            "planned_chapter_range": None,
            "planned_total_chapter_count": None,
            "expected_chapter_range": None,
            "expected_total_chapter_count": None,
            "current_total_chapter_count": None,
            "total_volumes": None,
        }
        if not isinstance(volume_detail_config, dict):
            return normalized

        normalized["framework_content"] = str(volume_detail_config.get("framework_content") or "")
        normalized["framework_header"] = str(volume_detail_config.get("framework_header") or "")
        normalized["framework_footer"] = str(volume_detail_config.get("framework_footer") or "")
        normalized["previous_volume_detail"] = str(volume_detail_config.get("previous_volume_detail") or "")
        normalized["existing_volume_detail"] = str(volume_detail_config.get("existing_volume_detail") or "")
        normalized["volumes_data"] = volume_detail_config.get("volumes_data")

        for int_key in [
            "target_volume_index",
            "start_chapter_num",
            "planned_chapter_count",
            "planned_total_chapter_count",
            "expected_total_chapter_count",
            "current_total_chapter_count",
            "total_volumes",
        ]:
            value = volume_detail_config.get(int_key)
            if value is None:
                continue
            try:
                normalized[int_key] = int(value)
            except Exception:
                normalized[int_key] = None

        for tuple_key in ["chapters_count_range", "planned_chapter_range", "expected_chapter_range"]:
            value = volume_detail_config.get(tuple_key)
            if isinstance(value, (list, tuple)) and len(value) == 2:
                try:
                    lower = int(value[0])
                    upper = int(value[1])
                    normalized[tuple_key] = (lower, upper)
                except Exception:
                    normalized[tuple_key] = None

        chapter_window = normalized.get("chapters_count_range")
        start_chapter_num = normalized.get("start_chapter_num")
        if isinstance(chapter_window, tuple) and start_chapter_num:
            lower = max(1, int(chapter_window[0] or 1))
            upper = max(lower, int(chapter_window[1] or lower))
            planned_count = normalized.get("planned_chapter_count")
            try:
                planned_count = int(planned_count or 0)
            except Exception:
                planned_count = 0
            planned_range = normalized.get("planned_chapter_range")
            if planned_count <= 0 and isinstance(planned_range, tuple):
                planned_count = max(1, int(planned_range[1]) - int(planned_range[0]) + 1)
            if planned_count <= 0:
                planned_count = lower + max(0, (upper - lower) // 2)
            normalized["planned_chapter_count"] = max(lower, min(upper, planned_count))

            if not isinstance(normalized.get("planned_chapter_range"), tuple):
                start = max(1, int(start_chapter_num))
                normalized["planned_chapter_range"] = (
                    start,
                    start + int(normalized["planned_chapter_count"]) - 1,
                )

            if normalized.get("planned_total_chapter_count") is None:
                current_total = int(normalized.get("current_total_chapter_count") or 0)
                normalized["planned_total_chapter_count"] = max(
                    current_total,
                    int(normalized["planned_chapter_range"][1]),
                )

        return normalized

    @staticmethod
    def _recommend_intent(
        validation: Dict[str, Any],
        chapters_needed: int,
        characters_needed: int,
    ) -> Tuple[str, str]:
        chapter_count = int(validation.get("chapter_count") or 0)
        character_count = int(validation.get("character_count") or 0)
        coverage_ratio = _safe_float(validation.get("coverage_ratio") or 0.0)
        unreferenced_characters = list(validation.get("unreferenced_characters") or [])

        if chapters_needed > 0 and characters_needed <= 0:
            if character_count <= 0:
                return "outline_led", "当前以补章节为主，同时人物底盘偏薄，建议以大纲侧为主导推进。"
            return "outline_led", "本次主要目标是补章节，优先走大纲主导更符合当前诉求。"

        if characters_needed > 0 and chapters_needed <= 0:
            if chapter_count <= 0:
                return "character_led", "本次主要目标是补人物，先建立人物体系更贴近当前目标。"
            if coverage_ratio < 0.35:
                return "outline_led", "现有人物在大纲中的承接偏弱，建议先补情节锚点再扩人物。"
            return "character_led", "本次主要目标是补人物，优先走人物主导更符合当前诉求。"

        if chapter_count <= 0 and chapters_needed > 0:
            return "outline_led", "当前缺少可定位章节结构，建议先由大纲侧建立承接框架。"
        if character_count <= 0 and characters_needed > 0:
            return "character_led", "当前人物体系偏空，建议先补关键角色再做协同扩展。"
        if coverage_ratio < 0.55 or unreferenced_characters:
            return "outline_led", "当前人物与章节覆盖率偏低，建议先由大纲侧补承接与登场位。"
        return "balanced", "章节与人物都存在增量空间，适合做平衡协同扩展。"

    def _build_cross_support_plan(
        self,
        *,
        current_chapter_count: int,
        current_character_count: int,
        characters_text: str,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        validation: Dict[str, Any],
        expansion_mode: str = "auto",
        volume_detail_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        plan = {
            "suggested_target_chapters": target_total_chapters,
            "suggested_target_characters": target_total_characters,
            "chapter_delta": 0,
            "character_delta": 0,
            "character_plan": None,
            "reasons": [],
        }

        coverage_ratio = _safe_float(validation.get("coverage_ratio") or 0.0)
        chapter_count = int(validation.get("chapter_count") or current_chapter_count or 0)
        character_count = int(validation.get("character_count") or current_character_count or 0)

        if expansion_mode == "volume_detail" and target_total_chapters is not None and target_total_characters is None:
            character_plan = self._estimate_volume_detail_auto_character_increment(
                current_character_count=character_count,
                characters_text=characters_text,
                volume_detail_config=volume_detail_config,
            )
            suggested_characters = int(character_plan["increment"] or 0)
            volume_span = max(
                0,
                int(character_plan.get("volume_span") or 0),
            )
            growth_plan = self._build_auto_character_growth_plan(
                current_character_count=character_count,
                suggested_increment=suggested_characters,
                recommended_min=int(character_plan["recommended_min"] or 0),
                recommended_max=int(character_plan["recommended_max"] or 0),
                expansion_mode=expansion_mode,
                chapter_delta=volume_span,
            )
            plan["character_plan"] = growth_plan
            if suggested_characters > 0:
                plan["character_delta"] = suggested_characters
                plan["suggested_target_characters"] = growth_plan["stage_target_characters"]
                plan["reasons"].append(
                    f"按本卷新增章节规模与题材倾向，全书结构化人物建议规模约为 {growth_plan['recommended_range_text']} 人。"
                    f"{growth_plan['stage_label']}先补到 {growth_plan['stage_target_characters']} 人"
                    f"（本次新增 {suggested_characters} 人），优先承接当前卷剧情；"
                    f"剩余角色将在{growth_plan['follow_up_phase']}继续补齐。"
                )

        if (
            expansion_mode != "volume_detail"
            and target_total_chapters is not None
            and target_total_characters is None
        ):
            character_plan = self._estimate_auto_character_increment(
                current_chapter_count=current_chapter_count,
                current_character_count=character_count,
                target_chapter_count=int(target_total_chapters),
                coverage_ratio=coverage_ratio,
                expansion_mode=expansion_mode,
            )
            suggested_characters = int(character_plan["increment"] or 0)
            growth_plan = self._build_auto_character_growth_plan(
                current_character_count=character_count,
                suggested_increment=suggested_characters,
                recommended_min=int(character_plan["recommended_min"] or 0),
                recommended_max=int(character_plan["recommended_max"] or 0),
                expansion_mode=expansion_mode,
                chapter_delta=max(0, int(target_total_chapters) - current_chapter_count),
            )
            plan["character_plan"] = growth_plan
            if suggested_characters > 0:
                plan["character_delta"] = suggested_characters
                plan["suggested_target_characters"] = growth_plan["stage_target_characters"]
                if expansion_mode == "epic_framework":
                    plan["reasons"].append(
                        f"按目标章节规模与题材倾向，全书结构化人物建议规模约为 {growth_plan['recommended_range_text']} 人。"
                        f"当前为长篇框架协同，{growth_plan['stage_label']}先补到 {growth_plan['stage_target_characters']} 人"
                        f"（本次新增 {suggested_characters} 人），优先搭起主线、阵营与关键承接角色；"
                        f"剩余角色将在{growth_plan['follow_up_phase']}继续补齐。"
                    )
                else:
                    plan["reasons"].append(
                        f"按目标章节规模与题材倾向，全书结构化人物建议规模约为 {growth_plan['recommended_range_text']} 人。"
                        f"点击一次开始协同后，系统会在同一次任务里自动分轮推进；首轮先补到 {growth_plan['stage_target_characters']} 人"
                        f"（首轮新增 {suggested_characters} 人），剩余角色会在{growth_plan['follow_up_phase']}继续补齐。"
                    )
                if growth_plan["task_target_characters"] > growth_plan["stage_target_characters"]:
                    plan["reasons"].append(
                        f"点击开始协同后，系统会在同一次任务里自动连续执行多轮；首轮先补到 {growth_plan['stage_target_characters']} 人，"
                        f"若推进顺利，本次任务预计补到 {growth_plan['task_target_characters']} 人。"
                    )
            elif coverage_ratio < 0.45 and character_count > 0:
                plan["reasons"].append(
                    "当前人物覆盖率偏低，系统本轮不继续自动加人，建议优先补足现有人物在新增章节中的职责与出场。"
                )

        if target_total_characters is not None and target_total_chapters is None:
            characters_needed = max(0, int(target_total_characters) - current_character_count)
            if characters_needed > 0:
                estimated_target_chapters, capped_by_conventional_limit = (
                    self._estimate_total_chapters_for_character_target(
                        current_chapter_count=current_chapter_count,
                        target_character_count=int(target_total_characters),
                        expansion_mode=expansion_mode,
                    )
                )
                suggested_chapters = max(0, estimated_target_chapters - current_chapter_count)
                plan["chapter_delta"] = suggested_chapters
                plan["suggested_target_chapters"] = estimated_target_chapters
                plan["reasons"].append(
                    f"本次以扩人物为主，系统已按目标人物规模同步推算章节承接量，建议先补到 {estimated_target_chapters} 章再扩展角色体系。"
                )
                if capped_by_conventional_limit:
                    plan["reasons"].append(
                        f"当前为常规协同，按目标人物规模推算的章节总量已触达常规协同上限 {self.CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS} 章；如需更高承载角色规模，建议切换到长篇框架协同。"
                    )

        if (
            expansion_mode in {"auto", "total"}
            and target_total_chapters is None
            and target_total_characters is None
        ):
            if chapter_count <= 0:
                suggested_chapters = 8
            elif chapter_count < 20:
                suggested_chapters = 8
            elif chapter_count < 80:
                suggested_chapters = 6
            else:
                suggested_chapters = max(4, min(12, chapter_count // 8))

            target_chapter_count = current_chapter_count + suggested_chapters
            character_plan = self._estimate_auto_character_increment(
                current_chapter_count=current_chapter_count,
                current_character_count=character_count,
                target_chapter_count=target_chapter_count,
                coverage_ratio=coverage_ratio,
                expansion_mode="total",
            )
            suggested_characters = int(character_plan["increment"] or 0)
            growth_plan = self._build_auto_character_growth_plan(
                current_character_count=character_count,
                suggested_increment=suggested_characters,
                recommended_min=int(character_plan["recommended_min"] or 0),
                recommended_max=int(character_plan["recommended_max"] or 0),
                expansion_mode="total",
                chapter_delta=suggested_chapters,
            )

            plan["chapter_delta"] = suggested_chapters
            plan["suggested_target_chapters"] = current_chapter_count + suggested_chapters
            if suggested_characters > 0:
                plan["character_delta"] = suggested_characters
                plan["suggested_target_characters"] = growth_plan["stage_target_characters"]
                plan["character_plan"] = growth_plan
            plan["reasons"].append(
                "本次未显式填写目标，系统已按当前章节密度与人物覆盖状况自动估算建议目标。"
            )

        return plan

    def analyze_expansion_request(
        self,
        current_outline: str,
        characters: str,
        world_setting: str,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        strategy: str = "auto",
        intent: str = "auto",
        enable_auto_supplement: bool = False,
        expansion_mode: str = "auto",
        volume_character_increment: Optional[int] = None,
        epic_config: Optional[Dict[str, Any]] = None,
        volume_detail_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        current_outline = sanitize_outline_alignment_placeholders(current_outline or "")
        validation = evaluate_story_coordination(current_outline or "", characters or "")
        normalized_expansion_mode = self._normalize_expansion_mode(expansion_mode)
        normalized_epic_config = self._normalize_epic_config(epic_config)
        normalized_volume_detail_config = self._normalize_volume_detail_config(volume_detail_config)
        requested_mode_info = self.determine_execution_mode(
            current_outline=current_outline,
            characters=characters,
            target_total_chapters=target_total_chapters,
            target_total_characters=target_total_characters,
            expansion_mode=normalized_expansion_mode,
            epic_config=normalized_epic_config,
            volume_detail_config=normalized_volume_detail_config,
        )

        recommended_intent, intent_reason = self._recommend_intent(
            validation=validation,
            chapters_needed=int(requested_mode_info.get("chapters_needed") or 0),
            characters_needed=int(requested_mode_info.get("characters_needed") or 0),
        )
        effective_intent = intent if intent in {"outline_led", "character_led", "balanced"} else recommended_intent

        support_plan = self._build_cross_support_plan(
            current_chapter_count=int(requested_mode_info.get("current_chapter_count") or 0),
            current_character_count=int(requested_mode_info.get("current_character_count") or 0),
            characters_text=characters or "",
            target_total_chapters=target_total_chapters,
            target_total_characters=target_total_characters,
            validation=validation,
            expansion_mode=normalized_expansion_mode,
            volume_detail_config=normalized_volume_detail_config,
        )

        effective_target_chapters = target_total_chapters
        effective_target_characters = target_total_characters
        auto_supplement_applied = False

        if enable_auto_supplement:
            if effective_target_chapters is None and support_plan.get("suggested_target_chapters") is not None:
                effective_target_chapters = int(support_plan["suggested_target_chapters"])
                auto_supplement_applied = auto_supplement_applied or int(support_plan.get("chapter_delta") or 0) > 0
            if effective_target_characters is None and support_plan.get("suggested_target_characters") is not None:
                effective_target_characters = int(support_plan["suggested_target_characters"])
                auto_supplement_applied = auto_supplement_applied or int(support_plan.get("character_delta") or 0) > 0

        effective_mode_info = self.determine_execution_mode(
            current_outline=current_outline,
            characters=characters,
            target_total_chapters=effective_target_chapters,
            target_total_characters=effective_target_characters,
            expansion_mode=normalized_expansion_mode,
            epic_config=normalized_epic_config,
            volume_detail_config=normalized_volume_detail_config,
        )

        recommended_strategy = self._resolve_strategy(
            strategy=strategy,
            validation=validation,
            chapters_needed=int(effective_mode_info.get("chapters_needed") or 0),
            characters_needed=int(effective_mode_info.get("characters_needed") or 0),
        )
        effective_strategy = (
            strategy
            if strategy in {"balanced", "plot_first", "character_first"}
            else self._intent_to_strategy(effective_intent)
        )
        if strategy == "auto" and effective_intent == "balanced":
            effective_strategy = recommended_strategy

        target_chapter_count = int(
            effective_mode_info.get("target_chapter_count")
            or effective_mode_info.get("current_chapter_count")
            or 0
        )
        target_character_count = int(
            effective_mode_info.get("target_character_count")
            or effective_mode_info.get("current_character_count")
            or 0
        )
        current_character_count = int(effective_mode_info.get("current_character_count") or 0)
        execution_mode = str(effective_mode_info.get("mode") or "delta").strip()
        estimated_rounds = self._estimate_execution_rounds_from_mode_info(effective_mode_info)
        estimated_duration_minutes_min, estimated_duration_minutes_max = (
            self._estimate_duration_minutes_range_from_mode_info(
                effective_mode_info,
                estimated_rounds,
            )
        )
        effective_expansion_mode = (
            "epic_framework"
            if execution_mode == "epic"
            else (
                "volume_detail"
                if execution_mode == "volume_detail"
                else (
                    normalized_expansion_mode
                    if normalized_expansion_mode in {"total", "epic_framework", "volume_detail"}
                    else "total"
                )
            )
        )

        runtime_model_selection = self._configure_story_expansion_runtime_models(
            current_outline=current_outline,
            characters=characters,
            world_setting=world_setting,
            validation=validation,
            mode_info=effective_mode_info,
            estimated_rounds=estimated_rounds,
            expansion_mode=effective_expansion_mode,
            volume_detail_config=normalized_volume_detail_config,
        )

        outline_plan_model = self._estimate_outline_model_for_plan(
            execution_mode=execution_mode,
            target_chapter_count=target_chapter_count,
            volume_detail_config=normalized_volume_detail_config,
        )
        character_plan_model = self._estimate_character_model_for_plan(target_character_count)

        model_plan = {
            "coordinator_planner_model": self._get_llm_model_name(getattr(self, "planner_llm", None), "unknown"),
            "coordinator_writer_model": self._get_llm_model_name(getattr(self, "writer_llm", None), "unknown"),
            "coordinator_planner_max_tokens": runtime_model_selection.get("planner", {}).get("requested_max_tokens"),
            "coordinator_writer_max_tokens": runtime_model_selection.get("writer", {}).get("requested_max_tokens"),
            "coordinator_planner_timeout_seconds": runtime_model_selection.get("planner", {}).get("timeout_seconds"),
            "coordinator_writer_timeout_seconds": runtime_model_selection.get("writer", {}).get("timeout_seconds"),
            "coordinator_planner_estimated_output_tokens": runtime_model_selection.get("planner", {}).get("estimated_output_tokens"),
            "coordinator_writer_estimated_output_tokens": runtime_model_selection.get("writer", {}).get("estimated_output_tokens"),
            "outline_expansion_model": outline_plan_model,
            "character_expansion_model": character_plan_model,
            "estimated_rounds": estimated_rounds,
            "selection_reason": runtime_model_selection.get("selection_reason"),
            "selection_quality_guard": runtime_model_selection.get("selection_quality_guard"),
            "selection_cost_hint": runtime_model_selection.get("selection_cost_hint"),
            "notes": [],
        }

        if not (current_outline or "").strip():
            model_plan["notes"].append("当前缺少结构化大纲，协同会优先从人物侧补强，并仅补充最小必要的承接情节。")
        if not (characters or "").strip():
            model_plan["notes"].append("当前缺少结构化人物体系，协同会先从大纲中识别角色需求，再补齐人物卡与关系。")

        warnings: List[str] = []
        if auto_supplement_applied and support_plan.get("reasons"):
            warnings.extend(list(dict.fromkeys(support_plan["reasons"])))
        if intent in {"outline_led", "character_led", "balanced"} and intent != recommended_intent:
            warnings.append("当前执行方向与系统建议不同，可能影响协同效率与结果稳定性。")
        if execution_mode == "iterative":
            warnings.append(
                f"当前会走分轮扩展；点击一次开始后，系统会在同一次任务里自动连续执行多轮，"
                f"单次任务最多自动推进 {self.ITERATIVE_MAX_ROUNDS} 轮，逐步逼近目标，而不是只执行首轮。"
            )
            if (
                int(effective_mode_info.get("chapters_needed") or 0) > self.ITERATIVE_CHAPTER_STEP * self.ITERATIVE_MAX_ROUNDS
                or int(effective_mode_info.get("characters_needed") or 0) > self.ITERATIVE_CHARACTER_STEP * self.ITERATIVE_MAX_ROUNDS
            ):
                warnings.append(
                    f"当前目标已超过单次后台任务的自动分轮上限（最多 {self.ITERATIVE_MAX_ROUNDS} 轮）；"
                    "本次会先推进可安全完成的部分，如仍有缺口可继续发起下一次协同。"
                )
        if execution_mode == "epic":
            warnings.append("当前会先生成长篇框架，再逐步细化，不会一次性产出完整卷级细纲。")
            model_plan["outline_expansion_model"] = self._estimate_stage_model("concept", outline_plan_model)
            estimated_volume_model = self._estimate_volume_detail_outline_model(
                normalized_volume_detail_config.get("chapters_count_range")
            )
            model_plan["notes"].append(
                f"卷级细化会按单次章节规模在 deepseek-pro 与 qwen-plus 之间动态选择，当前预估为 {estimated_volume_model}。"
            )
            model_plan["notes"].append(
                f"长篇框架阶段预计使用 {model_plan['outline_expansion_model']} 生成总卷框架，再进入后续卷级细化。"
            )
            if (
                normalized_expansion_mode == "auto"
                and target_chapter_count >= self.EPIC_CHAPTER_THRESHOLD
            ):
                warnings.append("目标章节规模已进入超长篇区间，系统在自动判断模式下切换为长篇框架协同。")
        if normalized_expansion_mode == "epic_framework" and execution_mode == "epic":
            warnings.append("当前为显式长篇框架协同，会优先保证总卷框架与角色体系匹配，再进入卷级细化。")
        if execution_mode == "volume_detail":
            warnings.append("当前会聚焦单卷细化，并同步检查该卷所需角色是否齐备。")
            volume_range = effective_mode_info.get("volume_chapter_range")
            if volume_range:
                model_plan["notes"].append(
                    f"当前聚焦第{effective_mode_info.get('target_volume_index')}卷，预计细化第{int(volume_range[0])}-{int(volume_range[1])}章。"
                )
            model_plan["outline_expansion_model"] = self._estimate_volume_detail_outline_model(
                normalized_volume_detail_config.get("chapters_count_range")
            )
            if normalized_volume_detail_config.get("existing_volume_detail"):
                warnings.append("目标卷已有细纲，本次协同会覆盖该卷现有细纲。")
        if target_chapter_count >= self.EPIC_CHAPTER_THRESHOLD:
            if execution_mode == "epic":
                model_plan["notes"].append(
                    f"目标章节规模较大，当前框架生成阶段会先用 {model_plan['outline_expansion_model']} 收敛总卷结构，再进入后续卷级细化。"
                )
            else:
                model_plan["notes"].append(
                    f"目标章节规模较大，大纲扩展预计使用 {model_plan['outline_expansion_model']}，协同会分阶段收敛而非一次性铺满全部细纲。"
                )
        if target_character_count >= 60:
            model_plan["character_expansion_model"] = self._estimate_character_model_for_plan(target_character_count)
            model_plan["notes"].append(
                f"目标人物规模较大，人物扩展预计使用 {model_plan['character_expansion_model']}，并建议分轮补齐关系与剧情职责。"
            )

        model_plan["notes"] = list(dict.fromkeys(item for item in model_plan["notes"] if item))
        mode_suitability = (
            self._build_total_mode_suitability(
                current_chapter_count=int(effective_mode_info.get("current_chapter_count") or 0),
                target_chapter_count=target_chapter_count,
                chapters_needed=int(effective_mode_info.get("chapters_needed") or 0),
                execution_mode=execution_mode,
            )
            if normalized_expansion_mode in {"auto", "total"}
            else None
        )

        intent_labels = {
            "outline_led": "大纲主导",
            "character_led": "人物主导",
            "balanced": "平衡协同",
            "auto": "自动判断",
        }
        mode_labels = {
            "delta": "单轮增量",
            "iterative": "分轮协同",
            "epic": "长篇框架",
            "volume_detail": "单卷细化",
        }
        summary_parts = [
            f"推荐采用{intent_labels.get(effective_intent, effective_intent)}",
            f"执行模式为{mode_labels.get(execution_mode, execution_mode)}",
            f"预计 {estimated_rounds} 轮",
        ]
        if auto_supplement_applied:
            if int(support_plan.get("chapter_delta") or 0) > 0:
                summary_parts.append(f"自动补足 {int(support_plan['chapter_delta'])} 章承接剧情")
            if int(support_plan.get("character_delta") or 0) > 0:
                character_plan = support_plan.get("character_plan") or {}
                task_target_characters = self._coerce_non_negative_int(
                    character_plan.get("task_target_characters"),
                )
                stage_target_characters = self._coerce_non_negative_int(
                    character_plan.get("stage_target_characters"),
                )
                if task_target_characters > stage_target_characters > 0:
                    summary_parts.append(
                        f"自动分轮补人：点击一次开始后系统会自动连续推进，首轮补足 {int(support_plan['character_delta'])} 个配套人物，本次任务预计补到 {task_target_characters} 人"
                    )
                else:
                    summary_parts.append(f"自动补足 {int(support_plan['character_delta'])} 个配套人物")
        if execution_mode == "epic":
            epic_range = effective_mode_info.get("epic_chapter_range")
            epic_volumes = effective_mode_info.get("epic_total_volumes")
            if epic_volumes and epic_range:
                summary_parts.append(
                    f"框架规模 {int(epic_volumes)} 卷 / {int(epic_range[0])}-{int(epic_range[1])} 章"
                )
        if execution_mode == "volume_detail":
            volume_range = effective_mode_info.get("volume_chapter_range")
            if volume_range:
                summary_parts.append(
                    f"聚焦第{int(effective_mode_info.get('target_volume_index') or 0)}卷 / 第{int(volume_range[0])}-{int(volume_range[1])}章"
                )

        return {
            "validation": validation,
            "execution_mode": execution_mode,
            "execution_mode_reason": effective_mode_info.get("reason", ""),
            "requested_target_chapter_count": target_total_chapters,
            "requested_target_character_count": target_total_characters,
            "effective_target_chapter_count": effective_target_chapters,
            "effective_target_character_count": effective_target_characters,
            "requested_volume_character_increment": volume_character_increment,
            "effective_volume_character_increment": (
                max(0, target_character_count - current_character_count)
                if execution_mode == "volume_detail"
                else None
            ),
            "recommended_strategy": recommended_strategy,
            "effective_strategy": effective_strategy,
            "recommended_intent": recommended_intent,
            "effective_intent": effective_intent,
            "requested_expansion_mode": normalized_expansion_mode,
            "effective_expansion_mode": effective_expansion_mode,
            "intent_reason": intent_reason,
            "auto_supplement_applied": auto_supplement_applied,
            "auto_supplement": support_plan,
            "estimated_rounds": estimated_rounds,
            "estimated_duration_minutes_min": estimated_duration_minutes_min,
            "estimated_duration_minutes_max": estimated_duration_minutes_max,
            "mode_suitability": mode_suitability,
            "model_plan": model_plan,
            "warnings": warnings,
            "epic_config": {
                "total_volumes": effective_mode_info.get("epic_total_volumes"),
                "chapter_range": list(effective_mode_info["epic_chapter_range"])
                if effective_mode_info.get("epic_chapter_range")
                else None,
            },
            "volume_detail": {
                "target_volume_index": effective_mode_info.get("target_volume_index"),
                "chapter_range": list(effective_mode_info["volume_chapter_range"])
                if effective_mode_info.get("volume_chapter_range")
                else None,
                "character_increment": (
                    max(0, target_character_count - current_character_count)
                    if execution_mode == "volume_detail"
                    else None
                ),
                "target_character_count": target_character_count if execution_mode == "volume_detail" else None,
                "existing_detail": bool(normalized_volume_detail_config.get("existing_volume_detail")),
            },
            "analysis_summary": "；".join(summary_parts),
        }

    def determine_execution_mode(
        self,
        current_outline: str,
        characters: str,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        expansion_mode: str = "auto",
        epic_config: Optional[Dict[str, Any]] = None,
        volume_detail_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        _, outline_blocks = parse_outline_blocks(current_outline or "")
        current_chapter_count = len(outline_blocks)
        current_character_count = len(extract_character_names(characters or ""))
        normalized_expansion_mode = self._normalize_expansion_mode(expansion_mode)
        normalized_epic_config = self._normalize_epic_config(epic_config)
        normalized_volume_detail_config = self._normalize_volume_detail_config(volume_detail_config)

        target_chapter_count = (
            max(current_chapter_count, int(target_total_chapters))
            if target_total_chapters is not None
            else current_chapter_count
        )
        target_character_count = (
            max(current_character_count, int(target_total_characters))
            if target_total_characters is not None
            else current_character_count
        )

        chapters_needed = max(0, target_chapter_count - current_chapter_count)
        characters_needed = max(0, target_character_count - current_character_count)
        explicit_epic_range = normalized_epic_config.get("chapter_range")
        explicit_epic_volumes = normalized_epic_config.get("total_volumes")
        framework_reference = max(target_chapter_count, self.planned_chapters_max or 0)

        if normalized_expansion_mode == "volume_detail":
            volume_range = (
                normalized_volume_detail_config.get("planned_chapter_range")
                or normalized_volume_detail_config.get("expected_chapter_range")
            )
            current_total_count = int(normalized_volume_detail_config.get("current_total_chapter_count") or current_chapter_count)
            planned_total_count = int(
                normalized_volume_detail_config.get("planned_total_chapter_count")
                or normalized_volume_detail_config.get("expected_total_chapter_count")
                or target_chapter_count
                or current_total_count
            )
            target_chapter_count = max(target_chapter_count, planned_total_count)
            current_chapter_count = max(current_chapter_count, current_total_count)
            chapters_needed = max(0, target_chapter_count - current_chapter_count)
            characters_needed = max(0, target_character_count - current_character_count)
            return {
                "mode": "volume_detail",
                "reason": "已显式选择单卷细化协同，优先细化目标卷并同步补齐相关角色。",
                "current_chapter_count": current_chapter_count,
                "current_character_count": current_character_count,
                "target_chapter_count": target_chapter_count,
                "target_character_count": target_character_count,
                "chapters_needed": chapters_needed,
                "characters_needed": characters_needed,
                "requested_expansion_mode": normalized_expansion_mode,
                "target_volume_index": normalized_volume_detail_config.get("target_volume_index"),
                "volume_chapter_range": volume_range,
                "current_total_chapter_count": current_total_count,
            }

        if normalized_expansion_mode == "epic_framework":
            if explicit_epic_range:
                target_chapter_count = max(target_chapter_count, int(explicit_epic_range[1]))
            else:
                target_chapter_count = max(
                    target_chapter_count,
                    self.planned_chapters_max or 0,
                    self.EPIC_CHAPTER_THRESHOLD,
                )
            chapters_needed = max(0, target_chapter_count - current_chapter_count)
            characters_needed = max(0, target_character_count - current_character_count)
            return {
                "mode": "epic",
                "reason": "已显式选择长篇框架协同，优先生成可扩展的总卷框架。",
                "current_chapter_count": current_chapter_count,
                "current_character_count": current_character_count,
                "target_chapter_count": target_chapter_count,
                "target_character_count": target_character_count,
                "chapters_needed": chapters_needed,
                "characters_needed": characters_needed,
                "requested_expansion_mode": normalized_expansion_mode,
                "epic_total_volumes": explicit_epic_volumes,
                "epic_chapter_range": explicit_epic_range,
            }

        epic_reference = framework_reference
        if normalized_expansion_mode == "auto" and target_total_chapters is not None and epic_reference >= self.EPIC_CHAPTER_THRESHOLD:
            return {
                "mode": "epic",
                "reason": f"目标规模约 {epic_reference} 章，已进入超长篇范围，自动判断模式切换为长篇框架协同。",
                "current_chapter_count": current_chapter_count,
                "current_character_count": current_character_count,
                "target_chapter_count": target_chapter_count,
                "target_character_count": target_character_count,
                "chapters_needed": chapters_needed,
                "characters_needed": characters_needed,
                "requested_expansion_mode": normalized_expansion_mode,
                "epic_total_volumes": explicit_epic_volumes,
                "epic_chapter_range": explicit_epic_range,
            }

        if (
            chapters_needed > self.SHORT_CHAPTER_DELTA_LIMIT
            or characters_needed > self.SHORT_CHARACTER_DELTA_LIMIT
        ):
            return {
                "mode": "iterative",
                "reason": (
                    f"本次需新增 {chapters_needed} 章、{characters_needed} 人，"
                    "超出单轮 delta 适用范围，切换为分轮协同。"
                ),
                "current_chapter_count": current_chapter_count,
                "current_character_count": current_character_count,
                "target_chapter_count": target_chapter_count,
                "target_character_count": target_character_count,
                "chapters_needed": chapters_needed,
                "characters_needed": characters_needed,
                "requested_expansion_mode": normalized_expansion_mode,
            }

        return {
            "mode": "delta",
            "reason": (
                f"本次需新增 {chapters_needed} 章、{characters_needed} 人，"
                "适合直接做单轮 delta 协同。"
            ),
            "current_chapter_count": current_chapter_count,
            "current_character_count": current_character_count,
            "target_chapter_count": target_chapter_count,
            "target_character_count": target_character_count,
            "chapters_needed": chapters_needed,
            "characters_needed": characters_needed,
            "requested_expansion_mode": normalized_expansion_mode,
        }

    @staticmethod
    def _resolve_strategy(
        strategy: str,
        validation: Dict[str, Any],
        chapters_needed: int,
        characters_needed: int,
    ) -> str:
        normalized = str(strategy or "auto").strip()
        if normalized in {"balanced", "plot_first", "character_first"}:
            return normalized

        if chapters_needed > 0 and characters_needed <= 0:
            return "plot_first"
        if characters_needed > 0 and chapters_needed <= 0:
            return "character_first"
        if validation.get("character_count", 0) <= 0 and characters_needed > 0:
            return "character_first"
        if validation.get("chapter_count", 0) <= 0 and chapters_needed > 0:
            return "plot_first"
        if validation.get("coverage_ratio", 1.0) < 0.55:
            return "plot_first"
        if validation.get("unreferenced_characters"):
            return "plot_first"
        return "balanced"

