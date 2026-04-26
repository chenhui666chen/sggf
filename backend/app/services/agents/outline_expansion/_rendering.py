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

class RenderingMixin:
    @staticmethod
    def _story_is_valid_volume_detail_chapter_count(
        chapter_count: int,
        chapters_count_range: Tuple[int, int],
    ) -> bool:
        try:
            lower = max(1, int(chapters_count_range[0] or 1))
        except Exception:
            lower = 1
        try:
            upper = max(lower, int(chapters_count_range[1] or lower))
        except Exception:
            upper = lower
        return lower <= int(chapter_count or 0) <= upper

    @staticmethod
    def _story_format_prev_volume_summary(prev_volume_summary: Optional[Dict[str, Any]]) -> str:
        if not isinstance(prev_volume_summary, dict) or not prev_volume_summary:
            return "（暂无上一卷摘要，可直接从当前卷切入，但仍需遵守全书框架。）"

        parts: List[str] = []
        for key, label in (
            ("core_plot_completed", "上一卷已完成"),
            ("ending_hook", "上一卷卷尾钩子"),
            ("next_volume_target", "本卷开局目标"),
            ("character_status_update", "人物状态变化"),
        ):
            text = str(prev_volume_summary.get(key) or "").strip()
            if text:
                parts.append(f"- {label}：{text}")

        foreshadowings_text = ""
        foreshadowings = prev_volume_summary.get("new_foreshadowings")
        if isinstance(foreshadowings, list):
            lines: List[str] = []
            for item in foreshadowings:
                if isinstance(item, dict):
                    content = str(item.get("content") or "未知伏笔").strip()
                    planted_volume = str(item.get("planted_volume") or "").strip()
                    reveal_volume = str(item.get("reveal_volume") or "").strip()
                    extras = "；".join(
                        part
                        for part in (
                            planted_volume and f"埋设于第{planted_volume}卷",
                            reveal_volume and f"预计第{reveal_volume}卷回收",
                        )
                        if part
                    )
                    lines.append(f"{content}" + (f"（{extras}）" if extras else ""))
                else:
                    text = str(item or "").strip()
                    if text:
                        lines.append(text)
            foreshadowings_text = "；".join(lines)
        elif foreshadowings:
            foreshadowings_text = str(foreshadowings).strip()
        if foreshadowings_text:
            parts.append(f"- 上一卷遗留伏笔：{foreshadowings_text}")

        return "\n".join(parts) if parts else "（暂无可用的上一卷衔接信息。）"

    @staticmethod
    def _story_format_pending_foreshadowings(pending_foreshadowings: Optional[List[Dict[str, Any]]]) -> str:
        if not pending_foreshadowings:
            return "（当前没有强制回收项，但至少保留1条可延续线索，并避免与总纲冲突。）"

        lines: List[str] = []
        for item in pending_foreshadowings:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "处理").strip()
            content = str(item.get("content") or "").strip()
            planted_volume = str(item.get("planted_volume") or "").strip()
            reveal_volume = str(item.get("reveal_volume") or "").strip()
            extras = "；".join(
                part
                for part in (
                    planted_volume and f"埋设卷：第{planted_volume}卷",
                    reveal_volume and f"目标回收卷：第{reveal_volume}卷",
                )
                if part
            )
            if content:
                lines.append(f"- {action}：{content}" + (f"（{extras}）" if extras else ""))

        return "\n".join(lines) if lines else "（当前没有可识别的伏笔任务。）"

    @classmethod
    def _story_extract_chapters_payload(cls, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return []

        direct_chapters = payload.get("chapters")
        if isinstance(direct_chapters, list):
            return [chapter for chapter in direct_chapters if isinstance(chapter, dict)]

        chapter_plans = payload.get("chapter_plans")
        if isinstance(chapter_plans, list):
            return [chapter for chapter in chapter_plans if isinstance(chapter, dict)]

        novel_plan = payload.get("novel_plan")
        if isinstance(novel_plan, dict):
            nested_chapters = novel_plan.get("chapters")
            if isinstance(nested_chapters, list):
                return [chapter for chapter in nested_chapters if isinstance(chapter, dict)]

        volume_plan = payload.get("volume_plan")
        if isinstance(volume_plan, dict):
            volume_chapters = volume_plan.get("chapters")
            if isinstance(volume_chapters, list):
                return [chapter for chapter in volume_chapters if isinstance(chapter, dict)]

        return []

    @classmethod
    def _story_contains_premature_finale_signal(
        cls,
        payload: Dict[str, Any],
        *,
        current_round_target: int,
        overall_target_chapters: Optional[int],
    ) -> bool:
        if not isinstance(payload, dict):
            return False
        if not overall_target_chapters or overall_target_chapters <= current_round_target:
            return False

        serialized = json.dumps(payload, ensure_ascii=False)
        finale_keywords = (
            "大结局",
            "最终章",
            "终章",
            "终局",
            "完结",
            "收官",
            "尾声",
            "最终决战",
            "终战",
            "全书完结",
        )
        return any(keyword in serialized for keyword in finale_keywords)

    def _story_rewrite_payload_without_premature_finale(
        self,
        *,
        payload: Dict[str, Any],
        current_outline: str,
        characters: str,
        world_setting: str,
        new_chapter_start: int,
        target_chapters: int,
        story_target_chapters: int,
        chapter_schema: str,
    ) -> Dict[str, Any]:
        remaining_chapters = max(0, int(story_target_chapters or 0) - int(target_chapters or 0))
        rewrite_prompt = f"""你是小说章节修正师，请修正下面这份“常规协同”的章节 JSON。

【修正目标】
1. 当前只是在推进第 {new_chapter_start}-{target_chapters} 章，距离全书目标仍至少还有 {remaining_chapters} 章。
2. 禁止出现“终章 / 大结局 / 完结 / 终局 / 尾声 / 最终决战”等提前收官信号。
3. 本轮只能写成“阶段性高潮 / 转折 / 危机升级 / 新阶段开口”，不能写成全书完结。
4. 保留章节编号范围不变，只修正阶段定位、标题、关键事件、情节作用和结尾钩子中的提前完结表达。
5. 继续保持纯章节式 JSON，禁止卷级结构。

【当前大纲】
{current_outline}

【人物体系】
{characters}

【世界观】
{world_setting}

【待修正 JSON】
{json.dumps(payload, ensure_ascii=False, indent=2)}

【输出 JSON Schema】
{chapter_schema}

只返回合法 JSON，不要解释。"""
        return self._story_invoke_llm_json(
            self.llm,
            "你是小说章节修正师，请移除提前完结信号并保留阶段推进。",
            rewrite_prompt,
            fallback=payload,
        )

    @staticmethod
    def _story_normalize_incremental_continue_reason(
        reason: str,
        *,
        current_total: int,
        target_chapters: int,
        story_target_chapters: int,
    ) -> str:
        normalized_reason = str(reason or "").strip()
        if story_target_chapters > target_chapters and current_total >= target_chapters:
            return (
                f"当前可确认章节数（{current_total}）已达本轮目标章节数（{target_chapters}），"
                f"本轮阶段性细纲已完成，后续仍需继续朝全书目标 {story_target_chapters} 章推进。"
            )
        return normalized_reason

    @staticmethod
    def _story_count_rendered_outline_chapters(outline_text: str) -> int:
        if not outline_text or not str(outline_text).strip():
            return 0

        matches = re.findall(r"(?m)^(?:#{1,6}\s*)?第\s*(\d+)\s*章(?:[：:《\s]|$)", str(outline_text))
        chapter_numbers: List[int] = []
        for value in matches:
            try:
                chapter_numbers.append(int(value))
            except Exception:
                continue
        return max(chapter_numbers, default=0)

    @classmethod
    def _story_extract_incremental_overview(cls, payload: Dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            return ""

        for key in (
            "story_overview",
            "stage_summary",
            "current_arc_summary",
            "future_outline_reservation",
            "structure_overview",
            "arc_summary",
        ):
            text = str(payload.get(key) or "").strip()
            if text:
                return text

        planning_metadata = payload.get("planning_metadata") if isinstance(payload.get("planning_metadata"), dict) else {}
        if planning_metadata:
            for key in ("current_arc_name", "arc_goal", "summary"):
                text = str(planning_metadata.get(key) or "").strip()
                if text:
                    return text

        novel_plan = payload.get("novel_plan") if isinstance(payload.get("novel_plan"), dict) else {}
        if novel_plan:
            for key in ("story_overview", "core_theme", "summary", "title"):
                text = str(novel_plan.get(key) or "").strip()
                if text:
                    return text

        volume_plan = payload.get("volume_plan") if isinstance(payload.get("volume_plan"), dict) else {}
        if volume_plan:
            for key in ("plot_arc_summary", "core_theme", "volume_title"):
                text = str(volume_plan.get(key) or "").strip()
                if text:
                    return text

        return ""

    @classmethod
    def _story_render_incremental_outline(cls, payload: Dict[str, Any], chapter_breakdown: str) -> str:
        overview = cls._story_extract_incremental_overview(payload)
        parts: List[str] = []

        if overview:
            parts.append("## 本轮阶段摘要")
            parts.append(overview)

        if chapter_breakdown and chapter_breakdown.strip():
            parts.append("## 新增章节规划")
            parts.append(chapter_breakdown.strip())

        return "\n".join(parts).strip()

    @classmethod
    def _story_render_outline_overview(cls, payload: Dict[str, Any]) -> str:
        story_overview = str(
            payload.get("story_overview")
            or payload.get("structure_overview")
            or payload.get("future_outline_reservation")
            or payload.get("novel_title")
            or ""
        ).strip()
        volumes = payload.get("volumes") if isinstance(payload.get("volumes"), list) else []
        novel_plan = payload.get("novel_plan") if isinstance(payload.get("novel_plan"), dict) else {}
        volume_plan = payload.get("volume_plan") if isinstance(payload.get("volume_plan"), dict) else {}
        planning_metadata = payload.get("planning_metadata") if isinstance(payload.get("planning_metadata"), dict) else {}
        if planning_metadata and not story_overview:
            story_overview = str(
                planning_metadata.get("current_arc_name")
                or planning_metadata.get("arc_goal")
                or planning_metadata.get("summary")
                or ""
            ).strip()
        if volume_plan and not story_overview:
            story_overview = str(
                volume_plan.get("plot_arc_summary")
                or volume_plan.get("core_theme")
                or volume_plan.get("volume_title")
                or ""
            ).strip()
        if novel_plan:
            if not story_overview:
                story_overview = str(
                    novel_plan.get("story_overview")
                    or novel_plan.get("core_theme")
                    or novel_plan.get("summary")
                    or novel_plan.get("title")
                    or ""
                ).strip()
            if not volumes:
                nested_volumes = novel_plan.get("volumes")
                if isinstance(nested_volumes, list):
                    volumes = nested_volumes
        if volume_plan and not volumes:
            volumes = [volume_plan]

        chapters = cls._story_extract_chapters_payload(payload)
        if not story_overview and not volumes and not chapters:
            return ""

        parts: List[str] = ["## 故事概述"]
        if story_overview:
            parts.append(story_overview)

        for volume in volumes:
            if not isinstance(volume, dict):
                continue
            volume_index = volume.get("volume_index") or "?"
            title = str(volume.get("title") or f"第{volume_index}卷").strip()
            parts.append(f"### 【第{volume_index}卷】「{title}」")
            for key, label in (
                ("stage_goal", "卷目标"),
                ("core_conflict", "核心冲突"),
                ("ending_climax", "卷末爆点"),
                ("new_chapter_direction", "新增章节方向"),
            ):
                text = str(volume.get(key) or "").strip()
                if text:
                    parts.append(f"- {label}：{text}")
            key_characters = cls._format_names(volume.get("key_characters"))
            if key_characters:
                parts.append(f"- 关键人物：{key_characters}")

        if chapters:
            chapter_breakdown, _ = cls._story_render_chapter_breakdown("", {"chapters": chapters})
            if chapter_breakdown:
                parts.append("## 章节规划")
                parts.append(chapter_breakdown)
        return "\n".join(parts).strip()

    @classmethod
    def _story_render_chapter_breakdown(cls, current_outline: str, payload: Dict[str, Any]) -> Tuple[str, int]:
        sections = cls._story_parse_outline_sections(current_outline)
        chapters = cls._story_extract_chapters_payload(payload)
        blocks: List[str] = []
        max_chapter = 0

        for chapter in chapters:
            try:
                chapter_number = int(chapter.get("chapter_number") or 0)
            except Exception:
                chapter_number = 0
            if chapter_number <= 0:
                continue
            max_chapter = max(max_chapter, chapter_number)
            title = str(chapter.get("title") or f"第{chapter_number}章").strip()
            status = str(chapter.get("status") or "").strip().lower()
            suffix = " [已写]" if status == "written" else ""
            lines = [f"#### 第{chapter_number}章：《{title}》{suffix}"]

            existing_body = sections.get(chapter_number, "").strip()
            if status == "written" and existing_body:
                lines.append(existing_body)
                blocks.append("\n".join(lines))
                continue

            for key, label in (
                ("scene_goal", "场景目标"),
                ("conflict_design", "冲突设计"),
                ("key_events", "关键事件"),
                ("character_progress", "人物推进"),
                ("plot_function", "情节作用"),
                ("ending_hook", "结尾钩子"),
            ):
                text = str(chapter.get(key) or "").strip()
                if text:
                    lines.append(f"- **{label}**：{text}")
            involved_characters = cls._format_names(
                chapter.get("involved_characters") or chapter.get("characters_involved")
            )
            if involved_characters:
                lines.append(f"- **涉及人物**：{involved_characters}")
            highlight_type = str(chapter.get("highlight_type") or "").strip()
            if highlight_type:
                lines.append(f"- **爽点类型**：{highlight_type}")
            foreshadowing_item = str(chapter.get("foreshadowing_item") or "").strip()
            if foreshadowing_item:
                lines.append(f"- **伏笔事项**：{foreshadowing_item}")
            if len(lines) == 1 and existing_body:
                lines.append(existing_body)
            blocks.append("\n".join(lines))

        return "\n\n".join(blocks).strip(), max_chapter

    @classmethod
    def _story_render_character_cards(cls, items: Any) -> Tuple[str, List[str]]:
        if not isinstance(items, list):
            return "", []

        blocks: List[str] = []
        names: List[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            names.append(name)
            personality_anchor = str(item.get("personality_anchor") or "").strip()
            if not personality_anchor:
                personality_anchor = _build_personality_anchor_text(
                    item.get("personality"),
                    item.get("worldview_stance"),
                )
            ability_and_limits = _build_ability_and_limit_text(
                item.get("ability_outline") or item.get("abilities"),
                item.get("limitation"),
            )
            mainline_binding = _build_mainline_binding_text(
                item.get("mainline_role"),
                item.get("mainline_clues"),
            )
            lines = [f"### 【姓名】：{name}"]
            for text, label in (
                (str(item.get("age_gender") or "").strip(), "年龄/性别"),
                (str(item.get("story_stance") or "").strip(), "故事立场"),
                (str(item.get("role_position") or "").strip(), "角色定位"),
                (str(item.get("affiliation") or "").strip(), "所属势力"),
                (str(item.get("appearance_anchor") or item.get("appearance") or "").strip(), "外貌锚点"),
                (personality_anchor, "性格锚点"),
                (str(item.get("background_status") or item.get("background") or "").strip(), "背景/当前处境"),
                (str(item.get("motivation") or "").strip(), "核心动机"),
                (ability_and_limits, "能力与限制"),
                (str(item.get("key_relationships") or "").strip(), "关键关系"),
                (mainline_binding, "主线绑定"),
                (str(item.get("growth_direction") or "").strip(), "成长方向"),
            ):
                if text:
                    lines.append(f"【{label}】：{text}")
            blocks.append("\n".join(lines))

        return "\n\n".join(blocks).strip(), names

    @classmethod
    def _story_parse_character_cards_response(
        cls,
        response_text: Any,
        *,
        existing_names: Optional[List[str]] = None,
    ) -> Tuple[str, List[str], str]:
        content = str(response_text or "").strip()
        if not content:
            return "", [], "empty"

        payload = cls._story_extract_json(content)
        if isinstance(payload, dict):
            rendered_cards, names = cls._story_render_character_cards(payload.get("characters"))
            if rendered_cards.strip():
                return rendered_cards, names, "json"

        parser = CharacterTextParser()
        parsed_characters = parser.parse_all_characters(content)
        if not parsed_characters:
            return "", [], "empty"

        existing_name_keys = {
            normalize_character_name(name) or cls._story_normalize_name(name)
            for name in (existing_names or [])
            if str(name or "").strip()
        }
        rendered_blocks: List[str] = []
        names: List[str] = []
        seen_keys: set[str] = set()

        for character in parsed_characters:
            normalized_name = normalize_character_name(character.name) or cls._story_normalize_name(character.name)
            if not normalized_name or normalized_name in existing_name_keys or normalized_name in seen_keys:
                continue
            seen_keys.add(normalized_name)
            names.append(character.name)
            rendered_blocks.append(cls._story_render_parsed_character_card(character))

        if rendered_blocks:
            return "\n\n".join(rendered_blocks).strip(), names, "raw_cards"
        return "", [], "empty"

    @classmethod
    def _story_render_existing_character_patch(cls, payload: Dict[str, Any]) -> str:
        updates = payload.get("updates") if isinstance(payload.get("updates"), list) else []
        if not updates:
            return ""

        parts = ["## 已有角色关系更新"]
        for item in updates:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name:
                parts.append(f"### {name}")
            relation_updates = item.get("relationship_updates") if isinstance(item.get("relationship_updates"), list) else []
            relation_texts = []
            for relation in relation_updates:
                if not isinstance(relation, dict):
                    continue
                target = str(relation.get("target") or "").strip()
                description = str(relation.get("description") or "").strip()
                if target and description:
                    relation_texts.append(f"{target}：{description}")
            if relation_texts:
                parts.append(f"【关键关系·补充】：{'；'.join(relation_texts)}")
            for key, label in (
                ("mainline_clues_patch", "关联线索·补充"),
                ("mainline_role_patch", "剧情职责·补充"),
                ("growth_direction_patch", "成长方向·补充"),
            ):
                text = str(item.get(key) or "").strip()
                if text:
                    parts.append(f"【{label}】：{text}")
        return "\n".join(parts).strip()

    @staticmethod
    def _story_extract_existing_character_patch_field(block: str, label: str) -> str:
        pattern = re.compile(
            rf"(?ms)^\s*【{re.escape(label)}】[：:]\s*(.+?)(?=^\s*【|^\s*###\s+|\Z)"
        )
        match = pattern.search(block or "")
        return str(match.group(1) or "").strip() if match else ""

    @staticmethod
    def _story_split_inline_segments(text: Any) -> List[str]:
        content = str(text or "").strip()
        if not content:
            return []
        return [
            segment.strip()
            for segment in re.split(r"[；;\n]+", content)
            if segment and segment.strip()
        ]

    @classmethod
    def _story_merge_inline_segments(cls, *values: Any, separator: str = "；") -> str:
        merged: List[str] = []
        seen: set[str] = set()
        for value in values:
            for segment in cls._story_split_inline_segments(value):
                key = re.sub(r"\s+", "", segment)
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(segment)
        return separator.join(merged).strip()

    @classmethod
    def _story_upsert_existing_character_patch(
        cls,
        patch_map: Dict[str, Dict[str, str]],
        *,
        name: str,
        relationships: str = "",
        mainline_clues: str = "",
        mainline_role: str = "",
        growth_direction: str = "",
    ) -> None:
        display_name = str(name or "").strip()
        normalized_name = normalize_character_name(display_name) or cls._story_normalize_name(display_name)
        if not display_name or not normalized_name:
            return

        entry = patch_map.setdefault(normalized_name, {"name": display_name})
        if not entry.get("name"):
            entry["name"] = display_name

        for key, value in (
            ("relationships", relationships),
            ("mainline_clues", mainline_clues),
            ("mainline_role", mainline_role),
            ("growth_direction", growth_direction),
        ):
            merged_value = cls._story_merge_inline_segments(entry.get(key, ""), value)
            if merged_value:
                entry[key] = merged_value

    @classmethod
    def _story_collect_existing_character_patch_map_from_payload(
        cls,
        payload: Dict[str, Any],
    ) -> Dict[str, Dict[str, str]]:
        patch_map: Dict[str, Dict[str, str]] = {}
        updates = payload.get("updates") if isinstance(payload.get("updates"), list) else []
        for item in updates:
            if not isinstance(item, dict):
                continue
            relationship_updates = (
                item.get("relationship_updates")
                if isinstance(item.get("relationship_updates"), list)
                else []
            )
            relation_texts: List[str] = []
            for relation in relationship_updates:
                if not isinstance(relation, dict):
                    continue
                target = str(relation.get("target") or "").strip()
                description = str(relation.get("description") or "").strip()
                if target and description:
                    relation_texts.append(f"{target}：{description}")

            cls._story_upsert_existing_character_patch(
                patch_map,
                name=str(item.get("name") or "").strip(),
                relationships="；".join(relation_texts),
                mainline_clues=str(item.get("mainline_clues_patch") or "").strip(),
                mainline_role=str(item.get("mainline_role_patch") or "").strip(),
                growth_direction=str(item.get("growth_direction_patch") or "").strip(),
            )
        return patch_map

    @classmethod
    def _story_collect_existing_character_patch_map_from_text(
        cls,
        text: str,
    ) -> Tuple[str, Dict[str, Dict[str, str]]]:
        content = str(text or "")
        if not content.strip():
            return "", {}

        patch_map: Dict[str, Dict[str, str]] = {}
        pattern = re.compile(r"(?ms)^##\s*已有角色关系更新\s*\n?(.*?)(?=^##\s|\Z)")
        cleaned_parts: List[str] = []
        cursor = 0

        for match in pattern.finditer(content):
            leading = content[cursor:match.start()].strip()
            if leading:
                cleaned_parts.append(leading)

            section_body = str(match.group(1) or "").strip()
            for block in re.split(r"(?m)(?=^###\s+)", section_body):
                block_text = str(block or "").strip()
                if not block_text:
                    continue
                name_match = re.search(r"(?m)^###\s*(.+?)\s*$", block_text)
                if not name_match:
                    continue
                cls._story_upsert_existing_character_patch(
                    patch_map,
                    name=name_match.group(1).strip(),
                    relationships=cls._story_extract_existing_character_patch_field(block_text, "关键关系·补充"),
                    mainline_clues=cls._story_extract_existing_character_patch_field(block_text, "关联线索·补充"),
                    mainline_role=cls._story_extract_existing_character_patch_field(block_text, "剧情职责·补充"),
                    growth_direction=cls._story_extract_existing_character_patch_field(block_text, "成长方向·补充"),
                )

            cursor = match.end()

        trailing = content[cursor:].strip()
        if trailing:
            cleaned_parts.append(trailing)

        cleaned_text = "\n\n".join(part for part in cleaned_parts if part).strip()
        return cleaned_text, patch_map

    @classmethod
    def _story_render_parsed_character_card(cls, character: ParsedCharacter) -> str:
        age_gender_parts: List[str] = []
        if character.age is not None:
            age_gender_parts.append(f"{character.age}岁")
        if character.gender:
            age_gender_parts.append(character.gender)
        personality_anchor = _build_personality_anchor_text(character.personality, character.worldview)
        ability_and_limits = _build_ability_and_limit_text(character.abilities, character.limitation)
        mainline_binding = _build_mainline_binding_text(character.mainline_role, character.mainline_clues)
        lines = [f"### 【姓名】：{character.name}"]
        for text, label in (
            ("/".join(age_gender_parts), "年龄/性别"),
            (character.role or "", "故事立场"),
            (character.role_position or "", "角色定位"),
            (character.faction or "", "所属势力"),
            (character.appearance or "", "外貌锚点"),
            (personality_anchor, "性格锚点"),
            (character.background or "", "背景/当前处境"),
            (character.motivation or "", "核心动机"),
            (ability_and_limits, "能力与限制"),
            (character.relationships or "", "关键关系"),
            (mainline_binding, "主线绑定"),
            (character.growth_direction or "", "成长方向"),
        ):
            if str(text or "").strip():
                lines.append(f"【{label}】：{str(text).strip()}")
        return "\n".join(lines)

    @classmethod
    def _story_apply_existing_character_patch(
        cls,
        character: ParsedCharacter,
        patch: Dict[str, str],
    ) -> ParsedCharacter:
        character.relationships = cls._story_merge_inline_segments(
            character.relationships,
            patch.get("relationships"),
        )
        character.mainline_clues = cls._story_merge_inline_segments(
            character.mainline_clues,
            patch.get("mainline_clues"),
        )
        character.mainline_role = cls._story_merge_inline_segments(
            character.mainline_role,
            patch.get("mainline_role"),
        )
        character.growth_direction = cls._story_merge_inline_segments(
            character.growth_direction,
            patch.get("growth_direction"),
        )
        return character

    @classmethod
    def _story_merge_character_cards_with_patches(
        cls,
        main_characters: str,
        new_cards: str,
        patch_payload: Dict[str, Any],
    ) -> str:
        cleaned_main_characters, historical_patch_map = cls._story_collect_existing_character_patch_map_from_text(
            main_characters
        )
        current_patch_map = cls._story_collect_existing_character_patch_map_from_payload(patch_payload)
        patch_map = dict(historical_patch_map)
        for patch in current_patch_map.values():
            cls._story_upsert_existing_character_patch(
                patch_map,
                name=patch.get("name", ""),
                relationships=patch.get("relationships", ""),
                mainline_clues=patch.get("mainline_clues", ""),
                mainline_role=patch.get("mainline_role", ""),
                growth_direction=patch.get("growth_direction", ""),
            )

        parser = CharacterTextParser()
        existing_parsed = parser.parse_all_characters(cleaned_main_characters)
        new_parsed = parser.parse_all_characters(new_cards)
        merged_characters: Dict[str, ParsedCharacter] = {}
        ordered_keys: List[str] = []

        for character in [*existing_parsed, *new_parsed]:
            normalized_name = normalize_character_name(character.name) or cls._story_normalize_name(character.name)
            if not normalized_name:
                continue
            if normalized_name in merged_characters:
                merged_characters[normalized_name] = _merge_parsed_character(
                    merged_characters[normalized_name],
                    character,
                )
                continue
            merged_characters[normalized_name] = character
            ordered_keys.append(normalized_name)

        for normalized_name, patch in patch_map.items():
            character = merged_characters.get(normalized_name)
            if not character:
                continue
            merged_characters[normalized_name] = cls._story_apply_existing_character_patch(character, patch)

        rendered_cards = "\n\n".join(
            cls._story_render_parsed_character_card(merged_characters[key])
            for key in ordered_keys
            if key in merged_characters
        ).strip()

        fallback_parts: List[str] = []
        if cleaned_main_characters.strip() and not existing_parsed:
            fallback_parts.append(cleaned_main_characters.strip())
        if rendered_cards:
            fallback_parts.append(rendered_cards)
        if new_cards.strip() and not new_parsed:
            fallback_parts.append(new_cards.strip())
        return "\n\n".join(part for part in fallback_parts if part).strip()

    @classmethod
    def _story_render_relationships(cls, payload: Dict[str, Any]) -> str:
        groups = payload.get("relationship_groups") if isinstance(payload.get("relationship_groups"), list) else []
        if not groups:
            return ""

        parts: List[str] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_name = str(group.get("group") or "关系网络").strip()
            parts.append(f"**{group_name}**：")
            relationships = group.get("relationships") if isinstance(group.get("relationships"), list) else []
            for relation in relationships:
                if not isinstance(relation, dict):
                    continue
                source = str(relation.get("source") or "").strip()
                target = str(relation.get("target") or "").strip()
                relation_type = str(relation.get("type") or "").strip()
                description = str(relation.get("description") or "").strip()
                if source and target and relation_type and description:
                    parts.append(f"- {source} ↔ {target}：{relation_type}（{description}）")
        return "\n".join(parts).strip()

    @classmethod
    def _story_render_epic_framework(cls, payload: Dict[str, Any], total_volumes: int) -> str:
        if not isinstance(payload, dict) or not payload:
            return ""

        story_positioning = payload.get("story_positioning") if isinstance(payload.get("story_positioning"), dict) else {}
        stage_roadmap = (
            payload.get("stage_roadmap")
            if isinstance(payload.get("stage_roadmap"), list)
            else payload.get("story_phases")
        )
        rolling_strategy = payload.get("rolling_strategy") if isinstance(payload.get("rolling_strategy"), dict) else {}
        volumes = payload.get("volumes") if isinstance(payload.get("volumes"), list) else []
        power_progression = payload.get("power_progression") if isinstance(payload.get("power_progression"), list) else []
        foreshadowings = payload.get("foreshadowings") if isinstance(payload.get("foreshadowings"), list) else []
        lifecycle = payload.get("character_lifecycle") if isinstance(payload.get("character_lifecycle"), list) else []

        parts: List[str] = ["## 一、故事总纲与终局"]
        story_positioning_lines = [
            ("genre_type", "题材类型"),
            ("global_theme", "全局主题"),
            ("story_premise", "故事总纲"),
            ("core_hook", "核心卖点"),
            ("core_contradiction", "核心矛盾"),
            ("endgame_direction", "终局方向"),
        ]
        added_positioning = False
        for key, label in story_positioning_lines:
            text = str(story_positioning.get(key) or payload.get(key) or "").strip()
            if text:
                parts.append(f"- {label}：{text}")
                added_positioning = True
        if not added_positioning:
            parts.append("- 以长篇总纲统一约束世界观、主线终局与人物成长。")

        parts.append("")
        parts.append("## 二、阶段路线图")
        added_stage = False
        for phase in stage_roadmap if isinstance(stage_roadmap, list) else []:
            if not isinstance(phase, dict):
                continue
            added_stage = True
            stage_name = str(phase.get("stage") or phase.get("phase") or "阶段").strip()
            parts.append(f"### {stage_name}")
            for key, label in (
                ("volume_span", "覆盖卷段"),
                ("chapter_span", "覆盖章节"),
                ("phase_goal", "阶段目标"),
                ("main_conflict", "阶段主冲突"),
                ("growth_focus", "成长重点"),
                ("focus", "阶段重点"),
                ("ending_signal", "阶段收束标记"),
            ):
                text = str(phase.get(key) or "").strip()
                if text:
                    suffix = "章" if key == "chapter_span" and not text.endswith("章") else ""
                    parts.append(f"- {label}：{text}{suffix}")
        if not added_stage:
            parts.append("- 暂未给出明确的阶段路线图。")

        parts.append("")
        parts.append("## 三、力量与冲突升级路线")
        added_progression = False
        for item in power_progression:
            if not isinstance(item, dict):
                continue
            added_progression = True
            title = str(item.get("volume_span") or item.get("stage") or "阶段").strip()
            realm_stage = str(item.get("realm_stage") or "").strip()
            chapter_span = str(item.get("chapter_span") or "").strip()
            line = f"- {title}"
            if realm_stage:
                line += f"：{realm_stage}"
            if chapter_span:
                line += f"（{chapter_span if chapter_span.endswith('章') else chapter_span + '章'}）"
            parts.append(line)
            for key, label in (
                ("conflict_upgrade", "冲突升级"),
                ("notes", "说明"),
            ):
                text = str(item.get(key) or "").strip()
                if text:
                    parts.append(f"  - {label}：{text}")
        if not added_progression:
            parts.append("- 本书以阶段冲突升级代替单点爆发，保证长线成长不断档。")

        parts.append("")
        parts.append("## 四、滚动细化策略")
        added_strategy = False
        for key, label in (
            ("planning_principle", "规划原则"),
            ("detail_window", "细化窗口"),
            ("continuity_focus", "连续性重点"),
        ):
            text = str(rolling_strategy.get(key) or "").strip()
            if text:
                parts.append(f"- {label}：{text}")
                added_strategy = True

        anti_drift_rules = rolling_strategy.get("anti_drift_rules") if isinstance(rolling_strategy.get("anti_drift_rules"), list) else []
        if anti_drift_rules:
            added_strategy = True
            parts.append("- 防漂移规则：")
            for rule in anti_drift_rules:
                text = str(rule or "").strip()
                if text:
                    parts.append(f"  - {text}")

        character_collaboration = (
            rolling_strategy.get("character_collaboration")
            if isinstance(rolling_strategy.get("character_collaboration"), list)
            else []
        )
        if character_collaboration:
            added_strategy = True
            parts.append("- 人物协同方式：")
            for item in character_collaboration:
                text = str(item or "").strip()
                if text:
                    parts.append(f"  - {text}")

        if not added_strategy:
            parts.append("- 先锁定总纲与阶段目标，再按卷滚动细化，后续只展开当前卷与下卷接口。")
            parts.append("- 每次细化都要回看上一卷收束、活跃人物状态和伏笔任务，降低长篇漂移。")

        parts.append("")
        parts.append(f"## 五、分卷规划（共{total_volumes}卷）")
        if not volumes:
            parts.append("- 待补充分卷规划。")
        for volume in volumes:
            if not isinstance(volume, dict):
                continue
            volume_index = volume.get("volume_index") or "?"
            title = str(volume.get("title") or f"第{volume_index}卷").strip()
            parts.append(f"【第{volume_index}卷】{title}")
            for key, label in (
                ("chapter_span", "章节规模"),
                ("stage_positioning", "卷定位"),
                ("core_goal", "核心目标"),
                ("main_conflict", "主冲突"),
                ("character_focus", "人物焦点"),
                ("foreshadowing_task", "伏笔任务"),
                ("realm_stage", "力量/阶段进展"),
                ("major_enemy", "主要对手"),
                ("ending_climax", "卷末爆点"),
                ("next_volume_hook", "下卷交接"),
            ):
                text = str(volume.get(key) or "").strip()
                if text:
                    suffix = "章" if key == "chapter_span" and not text.endswith("章") else ""
                    parts.append(f"- {label}：{text}{suffix}")

        parts.append("")
        parts.append("## 六、关键伏笔布局")
        added_foreshadowings = False
        for item in foreshadowings:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            plant_at = str(item.get("plant_at") or "").strip()
            pave_at = cls._format_names(item.get("pave_at"))
            reveal_at = str(item.get("reveal_at") or "").strip()
            purpose = str(item.get("purpose") or "").strip()
            if content:
                detail = "；".join(
                    part
                    for part in (
                        plant_at and f"埋设：{plant_at}",
                        pave_at and f"铺垫：{pave_at}",
                        reveal_at and f"揭示：{reveal_at}",
                        purpose and f"作用：{purpose}",
                    )
                    if part
                )
                parts.append(f"- {content}（{detail}）" if detail else f"- {content}")
                added_foreshadowings = True
        if not added_foreshadowings:
            parts.append("- 暂无明确伏笔。")

        parts.append("")
        parts.append("## 七、核心人物生命周期")
        added_lifecycle = False
        for item in lifecycle:
            if not isinstance(item, dict):
                continue
            character = str(item.get("character") or "").strip()
            detail = "；".join(
                part
                for part in (
                    item.get("debut") and f"初登场：{item['debut']}",
                    item.get("active_span") and f"活跃跨度：{item['active_span']}",
                    item.get("transition") and f"阶段变化：{item['transition']}",
                    item.get("volume_role") and f"卷级职责：{item['volume_role']}",
                )
                if part
            )
            if character and detail:
                parts.append(f"- {character}：{detail}")
                added_lifecycle = True
        if not added_lifecycle:
            parts.append("- 核心人物随卷推进持续补齐。")
        return "\n".join(parts).strip()

    @classmethod
    def _story_render_volume_detail(
        cls,
        payload: Dict[str, Any],
        target_volume_index: int,
        start_chapter_num: int,
        chapters_count_range: Tuple[int, int],
        pending_foreshadowings: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[str, int]:
        if not isinstance(payload, dict) or not payload:
            return "", 0

        volume_positioning = payload.get("volume_positioning") if isinstance(payload.get("volume_positioning"), dict) else {}
        chapter_groups = payload.get("chapter_groups") if isinstance(payload.get("chapter_groups"), list) else []

        parts: List[str] = ["## 一、故事概述"]
        parts.append(str(payload.get("story_overview") or "").strip() or "本卷承接上一卷线索，继续推进主线。")
        positioning_lines: List[str] = []
        for key, label in (
            ("volume_title", "本卷标题"),
            ("phase_role", "本卷定位"),
            ("stage_goal", "阶段目标"),
            ("inheritance_from_prev", "承接上一卷"),
            ("main_conflict", "本卷主冲突"),
            ("character_coordination", "角色协同"),
            ("ending_handoff", "卷末交接"),
        ):
            text = str(volume_positioning.get(key) or "").strip()
            if text:
                positioning_lines.append(f"- {label}：{text}")
        if positioning_lines:
            parts.append("")
            parts.extend(positioning_lines)

        parts.append("")
        parts.append(f"## 二、第{target_volume_index}卷详细规划（预计{chapters_count_range[0]}-{chapters_count_range[1]}章，从第{start_chapter_num}章开始）")
        if chapter_groups:
            parts.append("- 本卷剧情段落：")
            for group in chapter_groups:
                if not isinstance(group, dict):
                    continue
                arc = str(group.get("arc") or "剧情段").strip()
                details = "；".join(
                    part
                    for part in (
                        group.get("chapter_span") and f"章节：{group['chapter_span']}",
                        group.get("stage_task") and f"任务：{group['stage_task']}",
                        group.get("conflict_upgrade") and f"冲突升级：{group['conflict_upgrade']}",
                        group.get("character_focus") and f"人物焦点：{group['character_focus']}",
                        group.get("foreshadowing_task") and f"伏笔任务：{group['foreshadowing_task']}",
                    )
                    if part
                )
                parts.append(f"  - {arc}" + (f"（{details}）" if details else ""))

        count = 0
        chapters = payload.get("chapters") if isinstance(payload.get("chapters"), list) else []
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            count += 1
            try:
                chapter_number = int(chapter.get("chapter_number") or (start_chapter_num + count - 1))
            except Exception:
                chapter_number = start_chapter_num + count - 1
            title = str(chapter.get("title") or f"第{chapter_number}章").strip()
            parts.append("")
            parts.append(f"### 第{chapter_number}章：《{title}》")
            for key, label in (
                ("scene_goal", "场景目标"),
                ("conflict_design", "冲突设计"),
                ("key_events", "关键事件"),
                ("character_progress", "人物推进"),
                ("plot_function", "情节作用"),
                ("ending_hook", "结尾钩子"),
            ):
                text = str(chapter.get(key) or "").strip()
                if text:
                    parts.append(f"- **{label}**：{text}")
            involved_characters = cls._format_names(chapter.get("involved_characters"))
            if involved_characters:
                parts.append(f"- **涉及人物**：{involved_characters}")
            highlight_type = str(chapter.get("highlight_type") or "").strip()
            if highlight_type:
                parts.append(f"- **爽点类型**：{highlight_type}")
            foreshadowing_item = str(chapter.get("foreshadowing_item") or "").strip()
            if foreshadowing_item:
                parts.append(f"- **伏笔事项**：{foreshadowing_item}")

        parts.append("")
        parts.append("## 三、伏笔埋设检查")
        checks = payload.get("foreshadowing_checks") if isinstance(payload.get("foreshadowing_checks"), list) else []
        if checks:
            for item in checks:
                if not isinstance(item, dict):
                    continue
                chapter = str(item.get("chapter") or "待定章节").strip()
                action = str(item.get("action") or "处理").strip()
                content = str(item.get("content") or "").strip()
                if content:
                    parts.append(f"- {chapter}：{action} {content}")
        elif pending_foreshadowings:
            for item in pending_foreshadowings:
                if not isinstance(item, dict):
                    continue
                action = str(item.get("action") or "处理").strip()
                content = str(item.get("content") or "").strip()
                if content:
                    parts.append(f"- 待定章节：{action} {content}")
        else:
            parts.append("- 当前卷暂无强制伏笔任务。")

        parts.append("")
        parts.append("## 四、卷尾衔接检查")
        connection = payload.get("volume_connection_check") if isinstance(payload.get("volume_connection_check"), dict) else {}
        for key, label in (
            ("core_task_completion", "本卷任务完成"),
            ("next_volume_opening", "下卷开局场景"),
            ("ending_hook", "卷尾钩子"),
        ):
            text = str(connection.get(key) or "").strip()
            if text:
                parts.append(f"✅ {label}：{text}")
        if parts[-1] == "## 四、卷尾衔接检查":
            parts.append("✅ 当前卷已形成基本承接结构。")

        return "\n".join(parts).strip(), count

    @classmethod
    def _story_normalize_volume_detail_response(
        cls,
        raw_response: Any,
        *,
        target_volume_index: int,
        start_chapter_num: int,
        chapters_count_range: Tuple[int, int],
        pending_foreshadowings: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        content = cls._story_trim_volume_detail_preamble(str(raw_response or ""))
        if not content:
            return ""

        payload = cls._story_extract_json(content)
        if isinstance(payload, dict) and payload:
            rendered_content, _ = cls._story_render_volume_detail(
                payload,
                target_volume_index=target_volume_index,
                start_chapter_num=start_chapter_num,
                chapters_count_range=chapters_count_range,
                pending_foreshadowings=pending_foreshadowings,
            )
            return cls._story_trim_volume_detail_preamble(rendered_content or content)

        return content

