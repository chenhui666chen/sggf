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

class EstimationMixin:
    def _reason_claims_target_already_satisfied(reason: str) -> bool:
        text = str(reason or "").strip()
        if not text:
            return False
        keywords = (
            "已包含",
            "已达到",
            "远超",
            "数量充足",
            "无需继续",
            "角色数量充足",
            "人物数充足",
            "目标已达成",
        )
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _reason_claims_no_effective_character_growth(reason: str) -> bool:
        text = str(reason or "").strip()
        if not text:
            return False
        keywords = (
            "未新增有效角色",
            "未产生新增内容",
            "本轮未新增",
            "没有新增角色",
        )
        return any(keyword in text for keyword in keywords)

    @classmethod
    def _normalize_outline_stop_reason(
        cls,
        reason: str,
        *,
        before_chapter_count: int,
        after_chapter_count: int,
        outline_delta: str,
    ) -> str:
        text = str(reason or "").strip()
        if after_chapter_count <= before_chapter_count and not str(outline_delta or "").strip():
            return "大纲扩展未产生新增章节，为避免空转已提前停止。"
        if "未提供具体的上下文或主题" in text:
            return "大纲扩展未产生可用章节规划，建议补充更明确的章节目标或承接点后再继续。"
        return text or "大纲侧模型建议停止继续扩展。"

    @classmethod
    def _normalize_character_stop_reason(
        cls,
        reason: str,
        *,
        before_character_count: int,
        after_character_count: int,
        target_character_count: int,
    ) -> str:
        text = str(reason or "").strip()
        if after_character_count <= before_character_count:
            return "人物扩展未产生新增内容，为避免空转已提前停止。"
        if cls._reason_claims_no_effective_character_growth(text):
            added_count = max(0, after_character_count - before_character_count)
            remaining = max(0, target_character_count - after_character_count)
            return (
                f"人物扩展已暂时停止，本轮仅新增 {added_count} 人，"
                f"距离目标仍差 {remaining} 人，建议继续补充关键角色并同步章节承接。"
            )
        if after_character_count < target_character_count and cls._reason_claims_target_already_satisfied(text):
            return "人物扩展已暂停，但当前目标尚未达成，建议先复核现有人物职责与剧情承接。"
        return text or "人物侧模型建议停止继续扩展。"

    @staticmethod
    def _intent_to_strategy(intent: str) -> str:
        mapping = {
            "outline_led": "plot_first",
            "character_led": "character_first",
            "balanced": "balanced",
        }
        return mapping.get(str(intent or "").strip(), "balanced")

    @staticmethod
    def _estimate_stage_model(task_type: str, fallback: str = "unknown") -> str:
        try:
            from core.model_runtime import resolve_model_for_task

            return resolve_model_for_task(task_type, None) or fallback
        except Exception:
            return fallback

    @staticmethod
    def _estimate_context_model(scenario: str, current_count: int, fallback: str = "unknown") -> str:
        try:
            from app.services.agents.layered_summarizer import LayeredSummarizer

            return LayeredSummarizer.estimate_selected_model(scenario, current_count)
        except Exception:
            return fallback

    @classmethod
    def _should_upgrade_total_to_epic(
        cls,
        target_total_reference: int,
        chapters_needed: int,
    ) -> bool:
        return (
            int(target_total_reference or 0) >= cls.FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD
            and int(chapters_needed or 0) > 0
        )

    @staticmethod
    def _estimate_volume_detail_outline_model(
        chapters_count_range: Optional[Tuple[int, int]],
        fallback: str = "deepseek-pro",
    ) -> str:
        try:
            from app.services.agents.outline_expander import OutlineExpander

            return OutlineExpander.estimate_volume_detail_model(chapters_count_range or (0, 0))
        except Exception:
            return fallback

    def _estimate_outline_model_for_plan(
        self,
        *,
        execution_mode: str,
        target_chapter_count: int,
        volume_detail_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        if execution_mode == "epic":
            return self._estimate_stage_model("concept", "qwen-plus")
        if execution_mode == "volume_detail":
            chapter_range = None
            if isinstance(volume_detail_config, dict):
                chapter_range = volume_detail_config.get("chapters_count_range")
            return self._estimate_volume_detail_outline_model(chapter_range)
        return self._estimate_context_model("outline_expand", target_chapter_count, "qwen-plus")

    def _estimate_character_model_for_plan(self, target_character_count: int) -> str:
        return self._estimate_context_model("character_expand", target_character_count, "deepseek-pro")

    def _estimate_character_density_multiplier(self) -> float:
        genre_text = normalize_story_text(self.genre or "").lower()
        if not genre_text:
            return 1.0

        high_density_keywords = (
            "玄幻",
            "奇幻",
            "仙侠",
            "武侠",
            "权谋",
            "宫斗",
            "群像",
            "史诗",
            "西幻",
            "科幻",
            "赛博",
            "无限",
            "冒险",
            "fantasy",
            "epic",
            "ensemble",
            "wuxia",
            "xianxia",
            "sci-fi",
            "scifi",
        )
        low_density_keywords = (
            "言情",
            "恋爱",
            "悬疑",
            "推理",
            "治愈",
            "校园",
            "青春",
            "成长",
            "日常",
            "romance",
            "mystery",
            "slice of life",
            "coming-of-age",
        )

        has_high_density_signal = any(keyword in genre_text for keyword in high_density_keywords)
        has_low_density_signal = any(keyword in genre_text for keyword in low_density_keywords)

        if has_high_density_signal and not has_low_density_signal:
            return 1.15
        if has_low_density_signal and not has_high_density_signal:
            return 0.9
        return 1.0

    def _estimate_character_target_range(self, chapter_count: int) -> Tuple[int, int]:
        effective_chapter_count = max(1, self._coerce_non_negative_int(chapter_count, 1))
        density_multiplier = self._estimate_character_density_multiplier()
        recommended_min = max(
            1,
            int(
                math.ceil(
                    (effective_chapter_count / self.CHARACTER_TARGET_MIN_CHAPTERS_PER_ROLE)
                    * density_multiplier
                )
            ),
        )
        recommended_max = max(
            recommended_min,
            int(
                math.ceil(
                    (effective_chapter_count / self.CHARACTER_TARGET_MAX_CHAPTERS_PER_ROLE)
                    * density_multiplier
                )
            ),
        )
        return recommended_min, recommended_max

    def _estimate_total_chapters_for_character_target(
        self,
        *,
        current_chapter_count: int,
        target_character_count: int,
        expansion_mode: str,
    ) -> Tuple[int, bool]:
        current_count = max(0, self._coerce_non_negative_int(current_chapter_count))
        target_count = max(0, self._coerce_non_negative_int(target_character_count))
        if target_count <= 0:
            return current_count, False

        estimated_target = max(
            current_count,
            target_count * self.CHARACTER_TARGET_MAX_CHAPTERS_PER_ROLE,
        )
        capped_by_conventional_limit = False
        if (
            expansion_mode in {"auto", "total"}
            and current_count <= self.CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS
            and estimated_target > self.CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS
        ):
            estimated_target = self.CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS
            capped_by_conventional_limit = True

        return estimated_target, capped_by_conventional_limit

    @staticmethod
    def _format_character_target_range_text(recommended_min: int, recommended_max: int) -> str:
        if recommended_min >= recommended_max:
            return f"{recommended_min}"
        return f"{recommended_min}-{recommended_max}"

    def _estimate_character_increment_cap(
        self,
        chapter_delta: int,
        *,
        expansion_mode: str,
    ) -> int:
        effective_delta = max(0, self._coerce_non_negative_int(chapter_delta))
        if effective_delta <= 0:
            return 0
        if expansion_mode == "volume_detail":
            return max(2, min(6, int(math.ceil(effective_delta / 8))))
        if expansion_mode == "epic_framework":
            return max(
                self.EPIC_FRAMEWORK_AUTO_CHARACTER_INCREMENT_FLOOR,
                min(
                    self.EPIC_FRAMEWORK_AUTO_CHARACTER_INCREMENT_SOFT_CAP,
                    int(math.ceil(effective_delta / 24)),
                ),
            )
        return max(2, min(self.AUTO_CHARACTER_INCREMENT_SOFT_CAP, int(math.ceil(effective_delta / 6))))

    @classmethod
    def _resolve_volume_detail_target_span(
        cls,
        volume_detail_config: Optional[Dict[str, Any]],
    ) -> int:
        normalized = cls._normalize_volume_detail_config(volume_detail_config)
        planned_count = normalized.get("planned_chapter_count")
        if planned_count is not None:
            try:
                return max(1, int(planned_count))
            except Exception:
                pass

        planned_range = normalized.get("planned_chapter_range")
        if isinstance(planned_range, tuple) and len(planned_range) == 2:
            try:
                start = int(planned_range[0])
                end = int(planned_range[1])
                return max(1, end - start + 1)
            except Exception:
                pass

        chapter_window = normalized.get("chapters_count_range")
        if isinstance(chapter_window, tuple) and len(chapter_window) == 2:
            try:
                lower = max(1, int(chapter_window[0]))
                upper = max(lower, int(chapter_window[1]))
                return max(lower, min(upper, lower + max(0, (upper - lower) // 2)))
            except Exception:
                pass

        chapter_range = normalized.get("expected_chapter_range")
        if isinstance(chapter_range, tuple) and len(chapter_range) == 2:
            try:
                start = int(chapter_range[0])
                end = int(chapter_range[1])
                return max(1, end - start + 1)
            except Exception:
                pass

        expected_total = max(0, int(normalized.get("expected_total_chapter_count") or 0))
        current_total = max(0, int(normalized.get("current_total_chapter_count") or 0))
        if expected_total > current_total:
            return expected_total - current_total

        return 0

    def _build_volume_detail_reference_text(
        self,
        volume_detail_config: Optional[Dict[str, Any]],
    ) -> str:
        normalized = self._normalize_volume_detail_config(volume_detail_config)
        parts: List[str] = []

        existing_volume_detail = str(normalized.get("existing_volume_detail") or "").strip()
        if existing_volume_detail:
            parts.append(existing_volume_detail)

        target_volume_index = normalized.get("target_volume_index")
        volumes_data = normalized.get("volumes_data")
        if isinstance(volumes_data, dict) and target_volume_index:
            volume_data = ((volumes_data.get("volumes") or {}) or {}).get(str(target_volume_index)) or {}
            for key in ("title", "summary", "detail"):
                value = str(volume_data.get(key) or "").strip()
                if value:
                    parts.append(value)

        if not parts:
            framework_content = str(normalized.get("framework_content") or "").strip()
            if framework_content:
                parts.append(framework_content)

        deduped_parts: List[str] = []
        seen = set()
        for value in parts:
            normalized_value = normalize_story_text(value or "").strip()
            if not normalized_value or normalized_value in seen:
                continue
            seen.add(normalized_value)
            deduped_parts.append(normalized_value)

        return "\n\n".join(deduped_parts)

    def _estimate_volume_detail_auto_character_increment(
        self,
        *,
        current_character_count: int,
        characters_text: str,
        volume_detail_config: Optional[Dict[str, Any]],
    ) -> Dict[str, int]:
        volume_span = max(0, self._resolve_volume_detail_target_span(volume_detail_config))
        recommended_min, recommended_max = self._estimate_character_target_range(max(1, volume_span))
        if volume_span <= 0:
            return {
                "increment": 0,
                "recommended_min": recommended_min,
                "recommended_max": recommended_max,
                "volume_span": 0,
                "referenced_character_count": 0,
            }

        reference_text = self._build_volume_detail_reference_text(volume_detail_config)
        known_character_names = extract_character_names(characters_text or "")
        referenced_character_names = [
            name for name in known_character_names if name and name in reference_text
        ]
        referenced_character_count = len(referenced_character_names)
        increment_cap = self._estimate_character_increment_cap(
            volume_span,
            expansion_mode="volume_detail",
        )
        has_existing_detail = bool(
            str(self._normalize_volume_detail_config(volume_detail_config).get("existing_volume_detail") or "").strip()
        )

        if has_existing_detail:
            base_required = max(0, recommended_min - referenced_character_count)
        else:
            conservative_floor = max(2, int(math.ceil(recommended_min * 0.6)))
            base_required = max(0, conservative_floor - referenced_character_count)

        minimum_increment = 0
        if volume_span >= 24:
            minimum_increment = 2
        if volume_span >= 32:
            minimum_increment = 3
        if referenced_character_count >= max(2, recommended_min - 1):
            minimum_increment = 0

        if not reference_text.strip() and current_character_count <= 1:
            minimum_increment = max(minimum_increment, 3 if volume_span >= 30 else 2)

        suggested_increment = min(
            increment_cap,
            max(0, base_required, minimum_increment),
        )

        return {
            "increment": max(0, suggested_increment),
            "recommended_min": recommended_min,
            "recommended_max": recommended_max,
            "volume_span": volume_span,
            "referenced_character_count": referenced_character_count,
        }

    def _build_auto_character_growth_plan(
        self,
        *,
        current_character_count: int,
        suggested_increment: int,
        recommended_min: int,
        recommended_max: int,
        expansion_mode: str,
        chapter_delta: int,
    ) -> Dict[str, Any]:
        current_count = self._coerce_non_negative_int(current_character_count)
        increment = max(0, self._coerce_non_negative_int(suggested_increment))
        stage_target_characters = current_count + increment
        recommended_floor = max(
            stage_target_characters,
            self._coerce_non_negative_int(recommended_min, stage_target_characters),
        )
        recommended_ceiling = max(
            recommended_floor,
            self._coerce_non_negative_int(recommended_max, recommended_floor),
        )
        remaining_to_floor = max(0, self._coerce_non_negative_int(recommended_min) - stage_target_characters)
        task_target_characters = stage_target_characters
        if expansion_mode not in {"epic_framework", "volume_detail"} and chapter_delta > 0:
            progressive_increment = max(0, int(math.ceil(self._coerce_non_negative_int(chapter_delta) / 12)))
            task_target_characters = max(
                stage_target_characters,
                min(recommended_floor, stage_target_characters + progressive_increment),
            )

        if expansion_mode == "epic_framework":
            stage_label = "框架阶段"
            follow_up_phase = "后续卷级细化或后续协同"
        elif expansion_mode == "volume_detail":
            stage_label = "本卷"
            follow_up_phase = "后续单卷细化"
        else:
            stage_label = "首轮"
            follow_up_phase = "后续协同轮次"

        return {
            "recommended_min": recommended_floor,
            "recommended_max": recommended_ceiling,
            "recommended_range_text": self._format_character_target_range_text(
                recommended_floor,
                recommended_ceiling,
            ),
            "recommended_additional_min": max(0, recommended_floor - current_count),
            "recommended_additional_max": max(0, recommended_ceiling - current_count),
            "stage_label": stage_label,
            "suggested_increment": increment,
            "stage_target_characters": stage_target_characters,
            "task_target_characters": task_target_characters,
            "task_target_increment": max(0, task_target_characters - current_count),
            "remaining_to_recommended_min": remaining_to_floor,
            "follow_up_phase": follow_up_phase,
            "is_phased": remaining_to_floor > 0,
        }

    def _estimate_auto_character_increment(
        self,
        *,
        current_chapter_count: int,
        current_character_count: int,
        target_chapter_count: int,
        coverage_ratio: float,
        expansion_mode: str,
    ) -> Dict[str, int]:
        target_total_chapters = max(
            self._coerce_non_negative_int(current_chapter_count),
            self._coerce_non_negative_int(target_chapter_count),
        )
        recommended_min, recommended_max = self._estimate_character_target_range(target_total_chapters)
        chapter_delta = max(0, target_total_chapters - self._coerce_non_negative_int(current_chapter_count))

        if chapter_delta <= 0:
            return {
                "increment": 0,
                "recommended_min": recommended_min,
                "recommended_max": recommended_max,
            }

        if coverage_ratio < 0.45 and current_character_count >= recommended_min:
            return {
                "increment": 0,
                "recommended_min": recommended_min,
                "recommended_max": recommended_max,
            }

        gap_to_floor = max(0, recommended_min - self._coerce_non_negative_int(current_character_count))
        if gap_to_floor <= 0:
            return {
                "increment": 0,
                "recommended_min": recommended_min,
                "recommended_max": recommended_max,
            }

        increment_cap = self._estimate_character_increment_cap(
            chapter_delta,
            expansion_mode=expansion_mode,
        )
        suggested_increment = min(gap_to_floor, increment_cap)

        if current_character_count <= 0 and suggested_increment > 0:
            baseline_increment = 3 if self._estimate_character_density_multiplier() > 1.05 else 2
            suggested_increment = max(suggested_increment, baseline_increment)

        if coverage_ratio < 0.45 and current_character_count >= max(1, recommended_min - 1):
            suggested_increment = min(suggested_increment, 1)

        return {
            "increment": max(0, suggested_increment),
            "recommended_min": recommended_min,
            "recommended_max": recommended_max,
        }

