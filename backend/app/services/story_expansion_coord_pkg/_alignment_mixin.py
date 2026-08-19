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
    append_preserved_outline_tail_sections,
    extract_outline_tail_sections,
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

class AlignmentMixin:
    @staticmethod
    def _collect_new_character_names(existing_characters: str, merged_characters: str) -> List[str]:
        before = {normalize_character_name(name) for name in extract_character_names(existing_characters or "")}
        after_names = extract_character_names(merged_characters or "")
        return [name for name in after_names if normalize_character_name(name) not in before]

    @staticmethod
    def _extract_character_delta_text(existing_characters: str, merged_characters: str) -> str:
        before = {normalize_character_name(name) for name in extract_character_names(existing_characters or "")}
        new_blocks = [
            block_text
            for block_name, block_text in extract_character_blocks(merged_characters or "")
            if normalize_character_name(block_name) not in before
        ]
        return "\n\n".join(block for block in new_blocks if block and block.strip())

    @staticmethod
    def _extract_outline_delta_text(
        previous_outline: str,
        current_outline: str,
        previous_chapter_count: int = 0,
    ) -> str:
        previous_text = str(previous_outline or "").strip()
        current_text = str(current_outline or "").strip()
        if not current_text or current_text == previous_text:
            return ""

        _, previous_blocks = parse_outline_blocks(previous_text)
        _, current_blocks = parse_outline_blocks(current_text)
        if current_blocks:
            previous_map = {
                int(block.original_number or 0): block
                for block in previous_blocks
                if int(block.original_number or 0) > 0
            }
            chapter_threshold = max(0, int(previous_chapter_count or 0))
            if chapter_threshold <= 0 and previous_map:
                chapter_threshold = max(previous_map)

            delta_blocks = [
                block
                for block in current_blocks
                if int(block.original_number or 0) > chapter_threshold
            ]

            if not delta_blocks and previous_map:
                for block in current_blocks:
                    chapter_number = int(block.original_number or 0)
                    previous_block = previous_map.get(chapter_number)
                    if previous_block is None:
                        delta_blocks.append(block)
                        continue
                    if (
                        (previous_block.title or "").strip() != (block.title or "").strip()
                        or (previous_block.body or "").strip() != (block.body or "").strip()
                    ):
                        delta_blocks.append(block)

            if delta_blocks:
                return render_outline_with_original_numbers("", delta_blocks)

        if previous_text and current_text.startswith(previous_text):
            return current_text[len(previous_text):].strip()
        return current_text

    @staticmethod
    def _stringify_structured_value(value: Any, item_separator: str = "；") -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (list, tuple, set)):
            parts = [
                str(item).strip()
                for item in value
                if str(item).strip()
            ]
            return item_separator.join(parts)
        if isinstance(value, dict):
            parts = []
            for key, item in value.items():
                key_text = str(key).strip()
                item_text = str(item).strip()
                if not key_text and not item_text:
                    continue
                parts.append(f"{key_text}：{item_text}" if key_text else item_text)
            return item_separator.join(parts)
        return str(value).strip()

    @classmethod
    def _pick_structured_value(
        cls,
        item: Dict[str, Any],
        keys: Tuple[str, ...],
        item_separator: str = "；",
    ) -> str:
        for key in keys:
            if key in item:
                text = cls._stringify_structured_value(item.get(key), item_separator=item_separator)
                if text:
                    return text
        return ""

    @classmethod
    def _render_structured_character_cards(
        cls,
        items: Any,
        *,
        existing_names: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> str:
        if not isinstance(items, list):
            return ""

        existing = {normalize_character_name(name) for name in list(existing_names or [])}
        seen: set[str] = set()
        cards: List[str] = []

        for raw_item in items:
            if not isinstance(raw_item, dict):
                continue
            name = normalize_character_name(raw_item.get("name") or raw_item.get("character_name") or "")
            if not name or name in existing or name in seen:
                continue
            seen.add(name)

            personality_anchor = cls._pick_structured_value(raw_item, ("personality_anchor",))
            if not personality_anchor:
                personality_anchor = _build_personality_anchor_text(
                    cls._pick_structured_value(raw_item, ("personality", "personality_traits")),
                    cls._pick_structured_value(raw_item, ("worldview_stance", "stance", "values")),
                )

            ability_and_limit = _build_ability_and_limit_text(
                cls._pick_structured_value(raw_item, ("ability_outline", "abilities", "skills", "specialty")),
                cls._pick_structured_value(raw_item, ("limitation", "flaw")),
            )

            mainline_binding = _build_mainline_binding_text(
                cls._pick_structured_value(raw_item, ("mainline_role", "story_function", "purpose")),
                cls._pick_structured_value(raw_item, ("mainline_clues", "story_threads")),
            )

            lines = [f"### 【姓名】：{name}"]
            field_pairs: List[Tuple[str, Optional[str]]] = [
                ("年龄/性别", cls._pick_structured_value(raw_item, ("age_gender", "demographics"))),
                ("故事立场", cls._pick_structured_value(raw_item, ("story_stance", "stance_alignment", "camp"))),
                ("角色定位", cls._pick_structured_value(raw_item, ("role_position", "role"))),
                ("所属势力", cls._pick_structured_value(raw_item, ("affiliation", "organization", "faction"))),
                ("外貌锚点", cls._pick_structured_value(raw_item, ("appearance_anchor", "appearance", "appearance_traits"))),
                ("性格锚点", personality_anchor),
                ("背景/当前处境", cls._pick_structured_value(raw_item, ("background_status", "background", "backstory"))),
                ("核心动机", cls._pick_structured_value(raw_item, ("motivation", "core_motivation"))),
                ("能力与限制", ability_and_limit),
                ("关键关系", cls._pick_structured_value(raw_item, ("key_relationships", "relationships_summary"))),
                ("主线绑定", mainline_binding),
                ("成长方向", cls._pick_structured_value(raw_item, ("growth_direction", "character_arc"))),
            ]
            for label, text in field_pairs:
                if text:
                    lines.append(f"【{label}】：{text}")

            cards.append("\n".join(lines))
            if limit is not None and len(cards) >= limit:
                break

        return "\n\n---\n\n".join(card for card in cards if card.strip())

    @classmethod
    def _render_structured_relationship_patch(cls, items: Any) -> str:
        if isinstance(items, str):
            return items.strip()
        if not isinstance(items, list):
            return ""

        lines: List[str] = []
        for raw_item in items:
            if not isinstance(raw_item, dict):
                continue
            source = cls._pick_structured_value(raw_item, ("source", "from"))
            target = cls._pick_structured_value(raw_item, ("target", "to"))
            relation_type = cls._pick_structured_value(raw_item, ("type", "relationship", "relation_type"))
            description = cls._pick_structured_value(raw_item, ("description", "summary", "detail"))
            if not source or not target:
                continue
            suffix = f"（{description}）" if description else ""
            lines.append(f"- {source} ↔ {target}：{relation_type or '关系'}{suffix}")

        return "\n".join(lines)

    @classmethod
    def _render_structured_chapter_blocks(cls, items: Any, *, detailed: bool) -> str:
        if not isinstance(items, list):
            return ""

        sections: List[str] = []
        for index, raw_item in enumerate(items, start=1):
            if not isinstance(raw_item, dict):
                continue

            title = cls._pick_structured_value(raw_item, ("title", "chapter_title"))
            if not title:
                title = f"新增章节{index}"

            involved_characters = cls._pick_structured_value(
                raw_item,
                ("involved_characters", "characters", "focus_characters"),
                item_separator="、",
            )
            scene_goal = cls._pick_structured_value(
                raw_item,
                ("scene_goal", "goal", "scene_objective"),
            )
            key_events = cls._pick_structured_value(raw_item, ("key_events", "events", "major_beats"))
            character_progress = cls._pick_structured_value(
                raw_item,
                ("character_progress", "character_arc", "relationship_shift"),
            )
            plot_function = cls._pick_structured_value(
                raw_item,
                ("plot_function", "story_function", "purpose"),
            )
            lines = [
                f"第{index}章：{title}",
                f"- 场景目标：{scene_goal or '待补充'}",
                f"- 冲突设计：{cls._pick_structured_value(raw_item, ('conflict_design', 'conflict', 'conflict_flow')) or '待补充'}",
                f"- 涉及人物：{involved_characters or '待定'}",
                f"- 关键事件：{key_events or '待补充'}",
                f"- 人物推进：{character_progress or '待补充'}",
                f"- 情节作用：{plot_function or '待补充'}",
                f"- 结尾钩子：{cls._pick_structured_value(raw_item, ('ending_hook', 'cliffhanger')) or '待补充'}",
            ]
            highlight_type = cls._pick_structured_value(raw_item, ('highlight_type', 'highlight', 'cool_point'))
            if highlight_type:
                lines.append(f"- 爽点类型：{highlight_type}")
            foreshadowing_item = cls._pick_structured_value(raw_item, ('foreshadowing_item', 'foreshadowing'))
            if foreshadowing_item:
                lines.append(f"- 伏笔事项：{foreshadowing_item}")
            sections.append("\n".join(lines))

        return "\n\n".join(section for section in sections if section.strip())

    @staticmethod
    def _append_unique_text(parts: List[str], text: str) -> None:
        value = str(text or "").strip()
        if not value or value in parts:
            return
        parts.append(value)

    @staticmethod
    def _build_alignment_warnings(
        new_character_names: List[str],
        validation: Optional[Dict[str, Any]],
    ) -> List[str]:
        if not new_character_names or not isinstance(validation, dict):
            return []

        unreferenced_names = {
            normalize_character_name(name): str(name).strip()
            for name in list(validation.get("unreferenced_characters") or [])
            if str(name).strip()
        }
        if not unreferenced_names:
            return []

        missing_new_names: List[str] = []
        for name in new_character_names:
            if normalize_character_name(name) in unreferenced_names:
                missing_new_names.append(name)

        if not missing_new_names:
            return []

        display_names = "、".join(missing_new_names[:5])
        if len(missing_new_names) > 5:
            display_names = f"{display_names} 等"
        return [
            (
                f"新增角色 {display_names} 尚未在更新后大纲中明确出场，"
                "建议下一轮优先补承接章节，或切换为人物优先策略。"
            )
        ]

    @staticmethod
    def _build_alignment_repair_note(repaired_names: List[str]) -> str:
        if not repaired_names:
            return ""

        display_names = "、".join(repaired_names[:5])
        if len(repaired_names) > 5:
            display_names = f"{display_names} 等"
        return f"已记录新增角色 {display_names} 的承接待补提示。"

    @staticmethod
    def _append_character_alignment_reminder_section(outline_text: str, names: List[str]) -> str:
        clean_names = []
        seen = set()
        for name in names:
            normalized = normalize_character_name(name)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            clean_names.append(str(name).strip())

        if not clean_names:
            return outline_text or ""

        reminder_lines = ["## 协同角色承接待补"]
        for name in clean_names:
            reminder_lines.append(f"- 协同角色承接待补：{name} 需在后续章节中正式出场，并与当前主线形成明确关联。")

        base_text = (outline_text or "").rstrip()
        if not base_text:
            return "\n".join(reminder_lines)

        heading_pattern = re.compile(r"(?m)^\s*##\s*(?:\*\*)?\s*(?:协同角色承接待补|人物承接待补)\s*(?:\*\*)?\s*$")
        matches = list(heading_pattern.finditer(base_text))
        if matches:
            match = matches[-1]
            next_heading = re.search(r"(?m)^\s*##\s+", base_text[match.end():])
            insert_at = match.end() + next_heading.start() if next_heading else len(base_text)
            new_lines = "\n".join(reminder_lines[1:])
            return (
                f"{base_text[:insert_at].rstrip()}\n{new_lines}\n\n"
                f"{base_text[insert_at:].lstrip()}"
            ).rstrip()

        return f"{base_text}\n\n{chr(10).join(reminder_lines)}"

    @staticmethod
    def _auto_repair_character_alignment(
        outline_text: str,
        new_character_names: List[str],
    ) -> Tuple[str, List[str]]:
        if not outline_text or not new_character_names:
            return outline_text or "", []

        preserved_tail_sections = extract_outline_tail_sections(outline_text or "")
        deduped_names: List[str] = []
        seen = set()
        for name in new_character_names:
            normalized = normalize_character_name(name)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped_names.append(str(name).strip())

        missing_names = [name for name in deduped_names if name and name not in outline_text]
        if not missing_names:
            return outline_text, []

        prefix, blocks = parse_outline_blocks(outline_text or "")
        if blocks:
            repaired_outline = render_outline(prefix, blocks)
            repaired_outline = append_preserved_outline_tail_sections(
                repaired_outline,
                preserved_tail_sections,
            )
            repaired_outline = AlignmentMixin._append_character_alignment_reminder_section(
                repaired_outline,
                missing_names,
            )
            return repaired_outline, missing_names

        repaired_text = AlignmentMixin._append_character_alignment_reminder_section("", missing_names)
        if outline_text.strip():
            return f"{outline_text.rstrip()}\n\n{repaired_text}", missing_names
        return repaired_text, missing_names

    @staticmethod
    def _rank_outline_blocks_for_reference_repair(blocks: List[OutlineBlock]) -> List[int]:
        ranked: List[Tuple[int, int, int]] = []

        for index, block in enumerate(blocks):
            fields, _ = _extract_outline_body_fields(block.body)
            involved_value = _normalize_outline_character_list(fields.get("involved_characters", ""))
            involved_names = [
                item for item in involved_value.split("、")
                if item and item != "待补充"
            ]
            ranked.append((len(involved_names), -index, index))

        ranked.sort()
        return [item[2] for item in ranked]

    @classmethod
    def _repair_outline_character_references(
        cls,
        outline_text: str,
        target_character_names: List[str],
        *,
        characters_text: str = "",
    ) -> Tuple[str, List[Dict[str, Any]]]:
        if not outline_text or not target_character_names:
            return outline_text or "", []

        preserved_tail_sections = extract_outline_tail_sections(outline_text or "")
        prefix, blocks = parse_outline_blocks(outline_text or "")
        if not blocks:
            return normalize_outline_text(outline_text or "", characters_text), []

        deduped_names: List[str] = []
        seen = set()
        for name in target_character_names:
            normalized = normalize_character_name(name)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped_names.append(normalized)

        if not deduped_names:
            return normalize_outline_text(outline_text or "", characters_text), []

        candidate_indexes = cls._rank_outline_blocks_for_reference_repair(blocks)
        if not candidate_indexes:
            return normalize_outline_text(outline_text or "", characters_text), []

        repairs: List[Dict[str, Any]] = []
        for offset, name in enumerate(deduped_names):
            block_index = candidate_indexes[offset % len(candidate_indexes)]
            target_block = blocks[block_index]
            if name in target_block.title or name in target_block.body:
                continue

            addition_line = f"- 涉及人物：{name}"
            target_body = str(target_block.body or "").rstrip()
            if target_body:
                # 最后一章的 block.body 可能延伸到文本末尾（含卷尾小节 / </details> 等
                # 尾部结构），直接追加会让注入行脱离章节字段区域、随后被 normalize
                # 丢弃；因此插入到首个尾部结构行之前。
                body_lines = target_body.splitlines()
                insert_at = len(body_lines)
                for line_index, line in enumerate(body_lines):
                    stripped_line = line.strip()
                    if (
                        stripped_line.startswith("## ")
                        or stripped_line.startswith("### ")
                        or stripped_line == "</details>"
                    ):
                        insert_at = line_index
                        break
                target_block.body = "\n".join(
                    body_lines[:insert_at] + [addition_line] + body_lines[insert_at:]
                )
            else:
                target_block.body = addition_line

            repairs.append(
                {
                    "character_name": name,
                    "chapter_number": int(target_block.original_number or block_index + 1),
                    "chapter_title": normalize_outline_title(target_block.title) or f"第{int(target_block.original_number or block_index + 1)}章",
                }
            )

        repaired_outline = normalize_outline_text(
            render_outline(prefix, blocks),
            characters_text,
        )
        repaired_outline = append_preserved_outline_tail_sections(
            repaired_outline,
            preserved_tail_sections,
        )
        return repaired_outline, repairs

    # ------------------------------------------------------------------
    # 对齐闸门：LLM 级增量修复（只增不改，保持 delta 锁定语义）
    # ------------------------------------------------------------------

    def _generate_alignment_repair_patch(
        self,
        plot_outline: str,
        characters: str,
        world_setting: str,
        issue_brief: str,
    ) -> Dict[str, Any]:
        """基于首轮对齐问题清单生成增量修复补丁。

        补丁只允许三类增量：缺失人物卡、既有章节的人物职责补充行、关系补丁；
        禁止改写已有章节或人物卡，与 delta 锁定语义一致。
        """
        prompt = f"""你是小说人物-情节协同修复师。以下是扩展后的大纲与人物设定，对齐验证发现问题。
请先对每个问题分类，再只输出"增量补丁"，禁止改写或复述已有内容。

【对齐验证问题清单】
{issue_brief}

【人物设定】
{(characters or "暂无")[:self.CONTEXT_BUDGET_CHARACTERS]}

【情节大纲】
{(plot_outline or "暂无")[:self.CONTEXT_BUDGET_OUTLINE]}

【世界观】
{(world_setting or "暂无")[:self.CONTEXT_BUDGET_WORLD]}

【修复原则】
1. 先分类：注记级问题（补人物卡/补职责行/补关系即可落地）才生成补丁；
   情节级问题（需要跨多章的主动行动线、渐进转变铺垫、承载新人物的情节节点——
   一行职责补充无法兑现）不要强行生成补丁，原样列入 plot_level_issues。
2. 缺失人物 → 确属注记级可解（补卡即有承接位）时生成完整人物卡（### 【姓名】：开头，含故事立场/角色定位/核心动机/关键关系/主线绑定等字段）；
   若需要为其新造情节节点才有意义，则列入 plot_level_issues。
3. 冗余人物 → 在其本应承担职责的既有章节追加"人物职责补充"（写清该章中此人推进什么/兑现什么，20-40字）。
4. 关系问题 → 在相关章节追加职责行落地该关系，或输出关系补丁。
5. chapter_marker 必须是大纲中真实存在的章节（形如"第12章"），不得虚构。

请只返回 JSON，结构如下：
{{
  "missing_character_cards": ["完整人物卡文本"],
  "chapter_duty_patches": [
    {{"chapter_marker": "第12章", "character": "角色名", "duty": "该章中此人的情节职责（20-40字）"}}
  ],
  "relationship_patches": [
    {{"source": "角色A", "target": "角色B", "type": "盟友/对手/师徒等", "description": "15字以内"}}
  ],
  "plot_level_issues": ["情节级问题原文（注记补丁无法落地，需下轮扩展新增章节承接）"]
}}
"""
        return self._invoke_json(
            prompt,
            fallback={"missing_character_cards": [], "chapter_duty_patches": [], "relationship_patches": []},
        )

    @staticmethod
    def _apply_alignment_repair_patch(
        result: Dict[str, Any],
        patch: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, int]]:
        """把闸门修复补丁增量合入扩展结果（只增不改），返回结果与实际应用计数。"""
        if not isinstance(patch, dict):
            return result, {"cards": 0, "duty_patches": 0, "relationship_patches": 0}

        applied = {"cards": 0, "duty_patches": 0, "relationship_patches": 0}

        # 1) 缺失人物卡 → 追加到人物文本末尾
        cards = [str(c).strip() for c in (patch.get("missing_character_cards") or []) if str(c).strip()]
        if cards:
            characters_text = str(result.get("characters") or "")
            separator = "\n\n" if characters_text.strip() else ""
            result["characters"] = characters_text + separator + "\n\n".join(cards)
            applied["cards"] = len(cards)

        # 2) 章节职责补充 → 按章节标题行定位，插入该章块内最后一行内容之后
        duty_patches = [p for p in (patch.get("chapter_duty_patches") or []) if isinstance(p, dict)]
        if duty_patches:
            outline_text = str(result.get("plot_outline") or "")
            if outline_text:
                lines = outline_text.splitlines()
                for patch_item in duty_patches:
                    marker = str(patch_item.get("chapter_marker") or "").strip()
                    character = str(patch_item.get("character") or "").strip()
                    duty = str(patch_item.get("duty") or "").strip()
                    if not (marker and character and duty):
                        continue
                    marker_match = re.search(r"第\s*(\d+)\s*章", marker)
                    if not marker_match:
                        continue
                    chapter_token = marker_match.group(1)
                    starts = [
                        index
                        for index, line in enumerate(lines)
                        if re.match(rf"^\s*第\s*{re.escape(chapter_token)}\s*章[\s：:]", line)
                    ]
                    if not starts:
                        continue
                    start_index = starts[0]
                    next_start = next(
                        (
                            index
                            for index, line in enumerate(lines)
                            if index > start_index and re.match(r"^\s*第\s*\d+\s*章[\s：:]", line)
                        ),
                        len(lines),
                    )
                    last_content = start_index
                    for index in range(start_index + 1, next_start):
                        if lines[index].strip():
                            last_content = index
                    lines.insert(last_content + 1, f"- 人物职责补充：{character}：{duty}")
                    applied["duty_patches"] += 1
                if applied["duty_patches"]:
                    result["plot_outline"] = "\n".join(lines)

        # 3) 关系补丁 → 追加到关系文本
        rel_patches = [p for p in (patch.get("relationship_patches") or []) if isinstance(p, dict)]
        if rel_patches:
            relationship_text = str(result.get("character_relationships") or "")
            new_lines = [
                f"{str(p.get('source') or '').strip()} → {str(p.get('target') or '').strip()}"
                f"（{str(p.get('type') or '').strip()}）：{str(p.get('description') or '').strip()}"
                for p in rel_patches
                if str(p.get("source") or "").strip() and str(p.get("target") or "").strip()
            ]
            if new_lines:
                separator = "\n" if relationship_text.strip() else ""
                result["character_relationships"] = relationship_text + separator + "\n".join(new_lines)
                applied["relationship_patches"] = len(new_lines)

        return result, applied

    @staticmethod
    def _select_balanced_round_order(
        remaining_chapters: int,
        target_chapter_count: int,
        remaining_characters: int,
        target_character_count: int,
    ) -> str:
        if remaining_chapters > 0 and remaining_characters <= 0:
            return "plot_first"
        if remaining_characters > 0 and remaining_chapters <= 0:
            return "character_first"

        chapter_ratio = remaining_chapters / max(target_chapter_count, 1)
        character_ratio = remaining_characters / max(target_character_count, 1)
        return "plot_first" if chapter_ratio >= character_ratio else "character_first"

    def _build_epic_validation(
        self,
        framework_text: str,
        characters_text: str,
        estimated_chapters: int,
    ) -> Dict[str, Any]:
        character_names = extract_character_names(characters_text or "")
        referenced_characters = [name for name in character_names if name and name in (framework_text or "")]
        character_count = len(character_names)
        coverage_ratio = (len(referenced_characters) / character_count) if character_count else 0.0

        score = 45
        score += int(min(35, coverage_ratio * 35))
        score += int(min(20, estimated_chapters / 50))
        score = max(0, min(100, score))

        suggestions: List[str] = []
        if character_count and coverage_ratio < 0.6:
            suggestions.append("长篇框架中提及的人物覆盖率偏低，建议在卷级细纲阶段显式绑定关键人物。")
        suggestions.append("当前结果为长篇框架级协同，后续展开单卷细纲时需要继续做章节级验证。")

        return {
            "score": score,
            "chapter_count": estimated_chapters,
            "character_count": character_count,
            "coverage_ratio": round(coverage_ratio, 3),
            "referenced_characters": referenced_characters,
            "unreferenced_characters": [name for name in character_names if name not in referenced_characters],
            "suggestions": suggestions,
            "validation_stage": "epic_framework",
        }

    @staticmethod
    def _estimate_total_chapters_from_volumes_data(volumes_data: Optional[Dict[str, Any]]) -> int:
        if not isinstance(volumes_data, dict):
            return 0
        try:
            from app.services.outline_merger import normalize_volume_detail_layout

            volumes_data = normalize_volume_detail_layout(volumes_data)
        except Exception:
            pass
        total = 0
        for vol_data in (volumes_data.get("volumes") or {}).values():
            if vol_data.get("type") != "detail":
                continue
            chapter_range = vol_data.get("chapters_range") or [0, 0]
            try:
                total = max(total, int(chapter_range[1] or 0))
            except Exception:
                continue
        return total

    @classmethod
    def _estimate_epic_volume_count(cls, target_total_chapters: int) -> int:
        estimated = round(max(target_total_chapters, cls.EPIC_CHAPTER_THRESHOLD) / cls.EPIC_DEFAULT_CHAPTERS_PER_VOLUME)
        return max(cls.EPIC_MIN_VOLUMES, min(cls.EPIC_MAX_VOLUMES, estimated))

    @classmethod
    def _estimate_epic_chapter_range(cls, target_total_chapters: int) -> Tuple[int, int]:
        lower = max(cls.FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD, int(target_total_chapters * 0.9))
        upper = max(lower + 60, int(target_total_chapters * 1.1))
        return lower, upper
