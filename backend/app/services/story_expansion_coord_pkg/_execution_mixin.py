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

class ExecutionMixin:
    def build_story_expansion_plan(
        self,
        current_outline: str,
        characters: str,
        world_setting: str,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        strategy: str = "auto",
    ) -> Dict[str, Any]:
        _, outline_blocks = parse_outline_blocks(current_outline or "")
        character_names = extract_character_names(characters or "")

        current_chapter_count = len(outline_blocks)
        current_character_count = len(character_names)
        chapters_needed = max(0, (target_total_chapters or current_chapter_count) - current_chapter_count)
        characters_needed = max(0, (target_total_characters or current_character_count) - current_character_count)

        fallback_plan = {
            "strategy": strategy if strategy != "auto" else "balanced",
            "summary": "使用默认增量计划补足目标章节和角色。",
            "outline_ops": [],
            "character_ops": [],
            "relationship_ops": [],
        }

        if chapters_needed <= 0 and characters_needed <= 0:
            fallback_plan["summary"] = "目标章节数和目标人物数均不高于当前内容，无需新增。"
            return {
                **fallback_plan,
                "current_chapter_count": current_chapter_count,
                "current_character_count": current_character_count,
                "chapters_needed": chapters_needed,
                "characters_needed": characters_needed,
            }

        prompt = f"""
你是小说协同拓展架构师。请只做“delta 计划”，禁止重写旧大纲与旧人物。

【协同原则】
1. 已有章节全部视为锁定内容，只能新增章节。
2. 新章节允许插在中段，操作类型仅限 append 或 insert_after。
3. 已有人物全部视为锁定档案，只能新增角色、补关系、补章节职责。
4. 计划必须围绕“大纲拓展 + 人物拓展协同”输出。

【当前章节索引】
{self._summarize_outline_blocks(outline_blocks)}

【当前人物名单】
{("、".join(character_names) if character_names else "暂无")}

【世界观摘要】
{(world_setting or "暂无")[:3000]}

【当前大纲原文】
{(current_outline or "暂无")[:8000]}

【当前人物原文】
{(characters or "暂无")[:6000]}

【目标】
- 当前章节数：{current_chapter_count}
- 目标章节数：{target_total_chapters if target_total_chapters is not None else current_chapter_count}
- 需新增章节：{chapters_needed}
- 当前人物数：{current_character_count}
- 目标人物数：{target_total_characters if target_total_characters is not None else current_character_count}
- 需新增人物：{characters_needed}
- 偏好策略：{strategy}

请只返回 JSON，对象结构如下：
{{
  "strategy": "balanced",
  "summary": "一句话说明本轮协同拓展目的",
  "outline_ops": [
    {{
      "action": "append 或 insert_after",
      "after_chapter": 12,
      "count": 4,
      "goal": "这几章解决什么剧情缺口",
      "focus_characters": ["角色A", "角色B"],
      "notes": "为什么要插在这里"
    }}
  ],
  "character_ops": [
    {{
      "role_position": "导师/对手/盟友/信息角色/世界观角色",
      "purpose": "该角色补什么缺口",
      "related_existing": ["角色A"],
      "serve_chapter_hint": "第13-16章"
    }}
  ],
  "relationship_ops": [
    {{
      "source": "角色A",
      "target": "角色B",
      "type": "盟友/怀疑/利用/师徒/对手",
      "description": "15字以内"
    }}
  ]
}}
"""

        plan = self._invoke_json(prompt, fallback_plan)
        normalized_strategy = str(plan.get("strategy") or fallback_plan["strategy"]).strip()
        if strategy != "auto":
            normalized_strategy = strategy

        normalized_plan = {
            "strategy": normalized_strategy or "balanced",
            "summary": str(plan.get("summary") or fallback_plan["summary"]).strip(),
            "outline_ops": self._normalize_outline_ops(
                list(plan.get("outline_ops") or []),
                chapters_needed,
                current_chapter_count,
            ),
            "character_ops": list(plan.get("character_ops") or []),
            "relationship_ops": list(plan.get("relationship_ops") or []),
            "current_chapter_count": current_chapter_count,
            "current_character_count": current_character_count,
            "chapters_needed": chapters_needed,
            "characters_needed": characters_needed,
        }

        return normalized_plan

    def generate_character_delta(
        self,
        existing_characters: str,
        current_outline: str,
        world_setting: str,
        plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        characters_needed = int(plan.get("characters_needed") or 0)
        if characters_needed <= 0:
            return {
                "character_delta": "",
                "character_relationships": "",
                "new_characters": [],
            }

        existing_names = extract_character_names(existing_characters)
        op_summary_lines = []
        for index, op in enumerate(plan.get("character_ops") or [], start=1):
            role_type = op.get("role_position") or op.get("role_type") or "功能角色"
            purpose = op.get("purpose") or "补足人物职责"
            related = "、".join(op.get("related_existing") or []) or "暂无"
            chapter_hint = op.get("serve_chapter_hint") or "由你判断"
            op_summary_lines.append(
                f"{index}. 类型：{role_type}；目的：{purpose}；关联旧角色：{related}；服务章节：{chapter_hint}"
            )

        relationship_hints = []
        for item in plan.get("relationship_ops") or []:
            relationship_hints.append(
                f"- {item.get('source', '角色A')} ↔ {item.get('target', '角色B')}："
                f"{item.get('type', '关系')}（{item.get('description', '')}）"
            )

        json_prompt = f"""
你是小说人物协同设计师。请只新增 {characters_needed} 个角色，禁止重写旧角色。

【旧角色名单】
{("、".join(existing_names) if existing_names else "暂无")}

【人物缺口计划】
{chr(10).join(op_summary_lines) if op_summary_lines else "请根据大纲缺口自行补足角色功能"}

【关系补丁提示】
{chr(10).join(relationship_hints) if relationship_hints else "请自行补充与旧角色或新角色之间的关键关系"}

【世界观】
{(world_setting or "暂无")[:2500]}

【大纲摘要】
{(current_outline or "暂无")[:5000]}

请只返回 JSON，对象结构如下：
{{
  "characters": [
    {{
      "name": "角色名",
      "age_gender": "年龄/性别",
      "story_stance": "主角方/反派方/中立方/亦正亦邪",
      "role_position": "角色定位",
      "affiliation": "所属势力",
      "appearance_anchor": "外貌锚点",
      "personality_anchor": "性格锚点",
      "background_status": "背景/当前处境",
      "motivation": "核心动机",
      "ability_outline": "角色能力/特长",
      "limitation": "能力代价/短板",
      "key_relationships": "关键关系",
      "mainline_role": "主线剧情职责",
      "mainline_clues": "关联线索",
      "growth_direction": "成长方向"
    }}
  ],
  "relationship_patch": [
    {{
      "source": "角色A",
      "target": "角色B",
      "type": "关系类型",
      "description": "关系简述"
    }}
  ]
}}
"""

        structured_payload = self._invoke_json(
            json_prompt,
            fallback={"characters": [], "relationship_patch": []},
        )
        cards_text = self._render_structured_character_cards(
            structured_payload.get("characters"),
            existing_names=existing_names,
            limit=characters_needed,
        )
        relationships_text = self._render_structured_relationship_patch(
            structured_payload.get("relationship_patch")
        )

        if not cards_text:
            text_prompt = f"""
你是小说人物协同设计师。请只新增 {characters_needed} 个角色，禁止重写旧角色。

【旧角色名单】
{("、".join(existing_names) if existing_names else "暂无")}

【人物缺口计划】
{chr(10).join(op_summary_lines) if op_summary_lines else "请根据大纲缺口自行补足角色功能"}

【关系补丁提示】
{chr(10).join(relationship_hints) if relationship_hints else "请自行补充与旧角色或新角色之间的关键关系"}

【世界观】
{(world_setting or "暂无")[:2500]}

【大纲摘要】
{(current_outline or "暂无")[:5000]}

输出要求：
1. 只输出新增角色，不要复述旧角色。
2. 严格输出 {characters_needed} 个角色卡。
3. 角色卡使用统一格式，便于后续同步：

### 【姓名】：角色名
【年龄/性别】：...
【故事立场】：...
【角色定位】：...
【所属势力】：...
【外貌锚点】：...
【性格锚点】：性格：...
价值倾向：...
【背景/当前处境】：...
【核心动机】：...
【能力与限制】：能力：...
限制：...
【关键关系】：...
【主线绑定】：剧情职责：...
关联线索：...
【成长方向】：...
---

最后另起一节，输出：
## 关系补丁
- 角色A ↔ 角色B：关系类型（简述）
"""

            raw_text = self._invoke_text(text_prompt)
            split_pattern = re.split(r"(?m)^##\s*关系补丁\s*$", raw_text, maxsplit=1)
            if len(split_pattern) == 2:
                cards_text, relationships_text = split_pattern[0].strip(), split_pattern[1].strip()
            else:
                cards_text, relationships_text = raw_text.strip(), ""

        new_character_names = extract_character_names(cards_text)
        return {
            "character_delta": cards_text,
            "character_relationships": relationships_text,
            "new_characters": new_character_names,
        }

    @staticmethod
    def _find_insert_index(blocks: List[OutlineBlock], after_chapter: int) -> int:
        fallback = len(blocks)
        last_anchor_index: Optional[int] = None

        for index, block in enumerate(blocks):
            if block.source == "generated" and block.anchor_after == after_chapter:
                last_anchor_index = index
                fallback = index + 1
                continue
            if block.original_number == after_chapter:
                last_anchor_index = index
                fallback = index + 1
                continue
            if block.source == "existing" and block.original_number > after_chapter:
                return (last_anchor_index + 1) if last_anchor_index is not None else index

        return fallback

    def _generate_new_chapters_for_op(
        self,
        op: Dict[str, Any],
        blocks: List[OutlineBlock],
        world_setting: str,
        characters_text: str,
        new_character_cards: str,
    ) -> Tuple[List[OutlineBlock], str]:
        count = int(op.get("count") or 0)
        if count <= 0:
            return [], ""

        after_chapter = op.get("after_chapter")
        action = op.get("action") or "append"

        anchor_block = None
        next_block = None
        if after_chapter:
            for block in blocks:
                if block.source == "existing" and block.original_number == after_chapter:
                    anchor_block = block
                if (
                    block.source == "existing"
                    and block.original_number > after_chapter
                    and next_block is None
                ):
                    next_block = block
                    break

        placement = "接在当前大纲末尾"
        if action == "insert_after" and after_chapter:
            placement = f"插入到第{after_chapter}章之后"

        anchor_summary = (
            f"第{after_chapter}章：{anchor_block.title}\n{anchor_block.body[:800]}"
            if anchor_block
            else "无明确锚点"
        )
        next_summary = (
            f"第{next_block.original_number}章：{next_block.title}\n{next_block.body[:800]}"
            if next_block
            else "无，表示可在结尾延展"
        )

        json_prompt = f"""
你是小说章节拓展策划师。请只生成 {count} 个新增章节，不允许改写旧章节。

【插入位置】
{placement}

【当前锚点章节】
{anchor_summary}

【后继锁定章节】
{next_summary}

【本次剧情目标】
{op.get("goal") or "补强剧情推进"}

【本次重点人物】
{("、".join(op.get("focus_characters") or []) if op.get("focus_characters") else "请按剧情自行分配")}

【新增角色卡】
{(new_character_cards or "本轮未新增角色")[:3500]}

【完整人物上下文】
{(characters_text or "暂无")[:4000]}

【世界观】
{(world_setting or "暂无")[:2500]}

请只返回 JSON，对象结构如下：
{{
      "chapters": [
        {{
          "title": "章节标题",
          "scene_goal": "场景目标",
          "conflict_design": "冲突设计",
          "key_events": "关键事件",
          "involved_characters": ["角色A", "角色B"],
          "character_progress": "人物推进",
          "plot_function": "情节作用",
          "ending_hook": "结尾钩子",
          "highlight_type": "爽点类型",
          "foreshadowing_item": "伏笔事项"
        }}
      ]
}}
"""

        structured_payload = self._invoke_json(
            json_prompt,
            fallback={"chapters": []},
        )
        raw_text = self._render_structured_chapter_blocks(
            structured_payload.get("chapters"),
            detailed=True,
        )

        if not raw_text:
            prompt = f"""
你是小说章节拓展策划师。请只生成 {count} 个新增章节，不允许改写旧章节。

【插入位置】
{placement}

【当前锚点章节】
{anchor_summary}

【后继锁定章节】
{next_summary}

【本次剧情目标】
{op.get("goal") or "补强剧情推进"}

【本次重点人物】
{("、".join(op.get("focus_characters") or []) if op.get("focus_characters") else "请按剧情自行分配")}

【新增角色卡】
{(new_character_cards or "本轮未新增角色")[:3500]}

【完整人物上下文】
{(characters_text or "暂无")[:4000]}

【世界观】
{(world_setting or "暂无")[:2500]}

输出要求：
1. 只输出新增章节。
2. 严格输出 {count} 个章节。
3. 每章使用以下格式：

第1章：章节标题
- 场景目标：[地点] + [在场人物] + [要达成什么]（30-40字）
- 冲突设计：① 初始障碍 → ② 升级转折 → ③ 爽点爆发（60-80字）
- 关键事件：按 2-4 个关键节点概括本章必发生的事
- 涉及人物：角色A、角色B
- 人物推进：主角或关键配角发生了什么变化，关系如何推进
- 情节作用：本章在整段剧情中的职责（承接/升级/埋伏笔/爆点前置等）
- 结尾钩子：[悬念/危机/反转]（20-30字）
- 爽点类型：[如本章存在明确爽点再写]
- 伏笔事项：[本章埋设或回收的伏笔，如无则写"无"]

4. 若是插入式拓展，新增章节必须自然衔接锚点章节与后继章节。
"""

            raw_text = self._invoke_text(prompt)
        _, generated_blocks = parse_outline_blocks(raw_text)

        for block in generated_blocks:
            block.locked = False
            block.source = "generated"
            block.anchor_after = after_chapter if isinstance(after_chapter, int) else None
            block.original_number = after_chapter if isinstance(after_chapter, int) else 0

        return generated_blocks, raw_text.strip()

    def generate_outline_delta(
        self,
        current_outline: str,
        characters_text: str,
        world_setting: str,
        plan: Dict[str, Any],
        new_character_cards: str,
    ) -> Dict[str, Any]:
        prefix, blocks = parse_outline_blocks(current_outline or "")
        chapters_needed = int(plan.get("chapters_needed") or 0)

        if chapters_needed <= 0:
            return {
                "plot_outline": current_outline or "",
                "outline_delta": "",
                "outline_ops": [],
                "current_chapter_count": len(blocks),
            }

        if not blocks:
            structured_payload = self._invoke_json(
                f"""
你是小说章节拓展策划师。当前原版大纲没有显式章节，视为锁定总纲。
请基于它新增 {chapters_needed} 个章节卡，不要重写原文。

【锁定原版大纲】
{(current_outline or "暂无")[:6000]}

【人物上下文】
{(characters_text or "暂无")[:4000]}

【新增角色卡】
{(new_character_cards or "本轮未新增角色")[:3000]}

【世界观】
{(world_setting or "暂无")[:2500]}

请只返回 JSON，对象结构如下：
{{
  "chapters": [
    {{
      "title": "章节标题",
      "scene_goal": "场景目标",
      "conflict_design": "冲突设计",
      "key_events": "关键事件",
      "involved_characters": ["角色A", "角色B"],
      "character_progress": "人物推进",
      "plot_function": "情节作用",
      "ending_hook": "结尾钩子",
      "highlight_type": "爽点类型",
      "foreshadowing_item": "伏笔事项"
    }}
  ]
}}
""",
                fallback={"chapters": []},
            )
            raw_text = self._render_structured_chapter_blocks(
                structured_payload.get("chapters"),
                detailed=True,
            )
            if not raw_text:
                raw_text = self._invoke_text(
                    f"""
你是小说章节拓展策划师。当前原版大纲没有显式章节，视为锁定总纲。
请基于它新增 {chapters_needed} 个章节卡，不要重写原文。

【锁定原版大纲】
{(current_outline or "暂无")[:6000]}

【人物上下文】
{(characters_text or "暂无")[:4000]}

【新增角色卡】
{(new_character_cards or "本轮未新增角色")[:3000]}

【世界观】
{(world_setting or "暂无")[:2500]}

请严格输出 {chapters_needed} 个章节，格式如下：
第1章：章节标题
- 场景目标：...
- 冲突设计：...
- 关键事件：...
- 涉及人物：...
- 人物推进：...
- 情节作用：...
- 结尾钩子：...
- 爽点类型：...
- 伏笔事项：...
"""
                )
            _, generated_blocks = parse_outline_blocks(raw_text)
            merged_outline = build_outline_delta_section(current_outline or "", raw_text)
            chapter_count = len(generated_blocks)
            outline_ops_executed = [
                {
                    "action": "append",
                    "after_chapter": None,
                    "requested_count": chapters_needed,
                    "generated_count": chapter_count,
                    "generated_titles": [block.title for block in generated_blocks],
                }
            ]
            return {
                "plot_outline": merged_outline,
                "outline_delta": raw_text.strip(),
                "outline_ops": outline_ops_executed,
                "current_chapter_count": chapter_count,
            }

        outline_delta_parts: List[str] = []
        outline_ops_executed: List[Dict[str, Any]] = []
        mutable_blocks = list(blocks)

        for op in plan.get("outline_ops") or []:
            generated_blocks, raw_text = self._generate_new_chapters_for_op(
                op=op,
                blocks=mutable_blocks,
                world_setting=world_setting,
                characters_text=characters_text,
                new_character_cards=new_character_cards,
            )
            if raw_text:
                outline_delta_parts.append(raw_text)

            after_chapter = op.get("after_chapter")
            if generated_blocks:
                if isinstance(after_chapter, int):
                    insert_index = self._find_insert_index(mutable_blocks, after_chapter)
                else:
                    insert_index = len(mutable_blocks)
                mutable_blocks[insert_index:insert_index] = generated_blocks

            outline_ops_executed.append(
                {
                    "action": op.get("action") or "append",
                    "after_chapter": after_chapter,
                    "requested_count": int(op.get("count") or 0),
                    "generated_count": len(generated_blocks),
                    "generated_titles": [block.title for block in generated_blocks],
                    "goal": op.get("goal") or "",
                }
            )

        plot_outline = render_outline(prefix, mutable_blocks)
        return {
            "plot_outline": plot_outline,
            "outline_delta": "\n\n".join(part for part in outline_delta_parts if part.strip()),
            "outline_ops": outline_ops_executed,
            "current_chapter_count": len(mutable_blocks),
        }

    def _run_outline_round(
        self,
        current_outline: str,
        world_setting: str,
        characters: str,
        current_chapter_count: int,
        increment: int,
        target_total_chapters: int,
        overall_target_chapters: Optional[int] = None,
    ) -> Dict[str, Any]:
        expander = self._get_expander()
        return expander.expand_plot_outline_incremental(
            current_outline=current_outline,
            world_setting=world_setting,
            characters=characters,
            current_chapter_count=current_chapter_count,
            increment=increment,
            target_total_chapters=target_total_chapters,
            overall_target_chapters=overall_target_chapters,
        )

    @classmethod
    def _resolve_iterative_outline_round_text(
        cls,
        previous_outline: str,
        result: Dict[str, Any],
        previous_chapter_count: int,
    ) -> Tuple[str, str]:
        previous_text = str(previous_outline or "")
        next_outline_text = str(result.get("expanded_outline") or previous_text)
        round_outline_delta = str(result.get("outline_delta") or "").strip()

        if not round_outline_delta:
            chapter_breakdown = str(result.get("chapter_breakdown") or "").strip()
            if chapter_breakdown:
                chapter_breakdown_delta = cls._extract_outline_delta_text(
                    previous_text,
                    chapter_breakdown,
                    previous_chapter_count,
                )
                if chapter_breakdown_delta:
                    round_outline_delta = chapter_breakdown_delta
                    next_outline_text = build_outline_delta_section(previous_text, chapter_breakdown_delta)

        if not round_outline_delta:
            round_outline_delta = cls._extract_outline_delta_text(
                previous_text,
                next_outline_text,
                previous_chapter_count,
            )

        return next_outline_text, round_outline_delta

    def _run_character_round(
        self,
        current_characters: str,
        world_setting: str,
        plot_outline: str,
        current_character_count: int,
        increment: int,
        target_total_characters: int,
    ) -> Dict[str, Any]:
        expander = self._get_expander()
        return expander.expand_characters_incremental(
            main_characters=current_characters,
            world_setting=world_setting,
            plot_outline=plot_outline,
            current_character_count=current_character_count,
            increment=increment,
            target_total_characters=target_total_characters,
        )

    def _expand_characters_to_target(
        self,
        current_characters: str,
        world_setting: str,
        plot_outline: str,
        current_character_count: int,
        target_total_characters: int,
    ) -> Dict[str, Any]:
        rounds: List[Dict[str, Any]] = []
        stop_reasons: List[str] = []
        relationship_parts: List[str] = []
        character_delta_parts: List[str] = []
        characters_text = current_characters or ""
        current_count = current_character_count

        if target_total_characters <= current_count:
            return {
                "characters_text": characters_text,
                "current_character_count": current_count,
                "character_delta": "",
                "character_relationships": "",
                "rounds": rounds,
                "stop_reasons": stop_reasons,
            }

        for iteration in range(1, self.ITERATIVE_MAX_ROUNDS + 1):
            if current_count >= target_total_characters:
                break

            increment = min(self.ITERATIVE_CHARACTER_STEP, target_total_characters - current_count)
            round_result = self._run_character_round(
                current_characters=characters_text,
                world_setting=world_setting,
                plot_outline=plot_outline,
                current_character_count=current_count,
                increment=increment,
                target_total_characters=target_total_characters,
            )
            next_characters = round_result.get("all_characters") or characters_text
            next_count = self._resolve_character_count(
                next_characters,
                round_result.get("current_character_count"),
                current_count,
            )
            round_character_delta = self._extract_character_delta_text(characters_text, next_characters)
            self._append_unique_text(character_delta_parts, round_character_delta)
            self._append_unique_text(relationship_parts, round_result.get("character_relationships") or "")

            rounds.append(
                {
                    "round": iteration,
                    "before_character_count": current_count,
                    "after_character_count": next_count,
                    "increment_requested": increment,
                    "post_validation_score": round_result.get("post_validation_score", 0),
                    "cards_response_mode": round_result.get("cards_response_mode"),
                    "cards_retry_used": bool(round_result.get("cards_retry_used", False)),
                    "recognized_new_character_count": int(round_result.get("recognized_new_character_count") or 0),
                    "recognized_new_character_names": list(round_result.get("recognized_new_character_names") or []),
                }
            )

            characters_text = next_characters

            if next_count <= current_count:
                stop_reasons.append("人物扩展未产生新增内容，为避免空转已提前停止。")
                break

            current_count = next_count

            if round_result.get("should_optimize_first"):
                stop_reasons.append("人物-情节匹配度偏低，已停止继续新增人物。")
                break

            validation_score = int(round_result.get("post_validation_score") or 0)
            if 0 < validation_score < 60:
                stop_reasons.append(f"人物-情节匹配度降至 {validation_score}/100，已停止继续新增人物。")
                break

            if not round_result.get("should_continue", True) and current_count < target_total_characters:
                reason = str(round_result.get("continue_reason") or "").strip()
                stop_reasons.append(reason or "人物侧模型建议停止继续扩展。")
                break

        if current_count < target_total_characters and len(rounds) >= self.ITERATIVE_MAX_ROUNDS:
            stop_reasons.append(
                f"已达到单次任务的自动分轮上限（最多 {self.ITERATIVE_MAX_ROUNDS} 轮），"
                "剩余人物目标需继续发起下一次协同。"
            )

        return {
            "characters_text": characters_text,
            "current_character_count": current_count,
            "character_delta": "\n\n".join(character_delta_parts),
            "character_relationships": "\n\n".join(relationship_parts),
            "rounds": rounds,
            "stop_reasons": stop_reasons,
        }

    def _execute_delta_mode(
        self,
        current_outline: str,
        characters: str,
        world_setting: str,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        strategy: str = "auto",
        mode_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        validation_before = evaluate_story_coordination(current_outline or "", characters or "")
        initial_chapter_count = max(
            self._coerce_non_negative_int((mode_info or {}).get("current_chapter_count")),
            self._coerce_non_negative_int(validation_before.get("chapter_count")),
        )
        initial_character_count = max(
            self._coerce_non_negative_int((mode_info or {}).get("current_character_count")),
            self._coerce_non_negative_int(validation_before.get("character_count")),
            len(extract_character_names(characters or "")),
        )
        plan = self.build_story_expansion_plan(
            current_outline=current_outline,
            characters=characters,
            world_setting=world_setting,
            target_total_chapters=target_total_chapters,
            target_total_characters=target_total_characters,
            strategy=strategy,
        )

        chapters_needed = int(plan.get("chapters_needed") or 0)
        characters_needed = int(plan.get("characters_needed") or 0)
        target_chapter_count = max(
            initial_chapter_count,
            self._coerce_non_negative_int(target_total_chapters),
        )
        target_character_count = max(
            initial_character_count,
            self._coerce_non_negative_int(target_total_characters),
        )
        resolved_strategy = self._resolve_strategy(
            strategy=strategy,
            validation=validation_before,
            chapters_needed=chapters_needed,
            characters_needed=characters_needed,
        )
        plan["strategy"] = resolved_strategy

        if chapters_needed > self.SHORT_CHAPTER_DELTA_LIMIT:
            raise ValueError(
                f"协同拓展一次最多新增 {self.SHORT_CHAPTER_DELTA_LIMIT} 章，请切换为分轮模式执行。"
            )
        if characters_needed > self.SHORT_CHARACTER_DELTA_LIMIT:
            raise ValueError(
                f"协同拓展一次最多新增 {self.SHORT_CHARACTER_DELTA_LIMIT} 个角色，请切换为分轮模式执行。"
            )
        if chapters_needed <= 0 and characters_needed <= 0:
            raise ValueError("目标章节数和目标人物数均不高于当前内容，无需协同拓展。")

        if resolved_strategy == "plot_first":
            outline_delta = self.generate_outline_delta(
                current_outline=current_outline,
                characters_text=characters or "",
                world_setting=world_setting,
                plan=plan,
                new_character_cards="",
            )
            character_delta = self.generate_character_delta(
                existing_characters=characters,
                current_outline=outline_delta["plot_outline"],
                world_setting=world_setting,
                plan=plan,
            )
            merged_characters = merge_character_delta(
                existing_characters=characters or "",
                new_character_cards=character_delta["character_delta"],
                relationship_patch=character_delta["character_relationships"],
            )
        else:
            character_delta = self.generate_character_delta(
                existing_characters=characters,
                current_outline=current_outline,
                world_setting=world_setting,
                plan=plan,
            )

            merged_characters = merge_character_delta(
                existing_characters=characters or "",
                new_character_cards=character_delta["character_delta"],
                relationship_patch=character_delta["character_relationships"],
            )

            outline_delta = self.generate_outline_delta(
                current_outline=current_outline,
                characters_text=merged_characters,
                world_setting=world_setting,
                plan=plan,
                new_character_cards=character_delta["character_delta"],
            )

        new_characters = self._collect_new_character_names(characters or "", merged_characters)
        generated_chapter_count = sum(
            self._coerce_non_negative_int(item.get("generated_count"))
            for item in outline_delta["outline_ops"]
            if isinstance(item, dict)
        )
        chapter_count_floor = (
            initial_chapter_count + generated_chapter_count
            if generated_chapter_count > 0
            else initial_chapter_count
        )
        current_chapter_count = self._resolve_outline_count(
            outline_delta["plot_outline"],
            outline_delta.get("current_chapter_count"),
            chapter_count_floor,
        )
        current_character_count = self._resolve_character_count(
            merged_characters,
            initial_character_count + len(new_characters),
            initial_character_count,
        )
        repaired_plot_outline, alignment_repairs = self._auto_repair_character_alignment(
            outline_delta["plot_outline"],
            new_characters,
        )
        outline_delta["plot_outline"] = repaired_plot_outline
        if outline_delta["outline_delta"] and outline_delta["outline_delta"].strip():
            repaired_outline_delta, delta_alignment_repairs = self._auto_repair_character_alignment(
                outline_delta["outline_delta"],
                new_characters,
            )
            outline_delta["outline_delta"] = repaired_outline_delta
            alignment_repairs = list(dict.fromkeys([*alignment_repairs, *delta_alignment_repairs]))
        outline_delta["plot_outline"] = normalize_outline_text(
            outline_delta["plot_outline"],
            merged_characters,
        )
        if outline_delta["outline_delta"] and outline_delta["outline_delta"].strip():
            outline_delta["outline_delta"] = normalize_outline_text(
                outline_delta["outline_delta"],
                merged_characters,
        )
        validation_after = evaluate_story_coordination(
            outline_delta["plot_outline"],
            merged_characters,
        )
        current_chapter_count = self._resolve_outline_count(
            outline_delta["plot_outline"],
            validation_after.get("chapter_count"),
            current_chapter_count,
        )
        current_character_count = self._resolve_character_count(
            merged_characters,
            validation_after.get("character_count"),
            current_character_count,
        )
        alignment_warnings = self._build_alignment_warnings(new_characters, validation_after)
        pending_parts: List[str] = []
        stop_reasons: List[str] = []
        if current_chapter_count < target_chapter_count:
            chapter_gap = target_chapter_count - current_chapter_count
            pending_parts.append(f"章节尚差 {chapter_gap} 章")
            stop_reasons.append(f"章节尚差 {chapter_gap} 章，需继续发起下一次协同。")
        if current_character_count < target_character_count:
            character_gap = target_character_count - current_character_count
            pending_parts.append(f"人物尚差 {character_gap} 人")
            stop_reasons.append(f"人物尚差 {character_gap} 人，需继续发起下一次协同。")
        goal_reached = len(pending_parts) <= 0
        plan["target_chapter_count"] = target_chapter_count
        plan["target_character_count"] = target_character_count
        coordination_summary = (
            plan["summary"]
            if goal_reached
            else f"单轮协同已完成当前可确认增量，{'，'.join(pending_parts)}。"
        )
        repair_note = self._build_alignment_repair_note(alignment_repairs)
        if repair_note:
            coordination_summary = f"{coordination_summary} {repair_note}"
        if alignment_warnings:
            coordination_summary = f"{coordination_summary} {' '.join(alignment_warnings)}"

        return {
            "execution_mode": "delta",
            "execution_mode_reason": (mode_info or {}).get("reason", ""),
            "strategy": resolved_strategy,
            "coordination_summary": coordination_summary,
            "plan": plan,
            "plot_outline": outline_delta["plot_outline"],
            "characters": merged_characters,
            "outline_delta": outline_delta["outline_delta"],
            "character_delta": character_delta["character_delta"],
            "character_relationships": character_delta["character_relationships"],
            "outline_ops": outline_delta["outline_ops"],
            "execution_rounds": [
                {
                    "round": 1,
                    "mode": "delta",
                    "strategy": resolved_strategy,
                    "chapters_generated": sum(
                        int(item.get("generated_count") or 0)
                        for item in outline_delta["outline_ops"]
                    ),
                    "characters_generated": len(new_characters),
                }
            ],
            "new_characters": new_characters,
            "alignment_repairs": alignment_repairs,
            "current_chapter_count": current_chapter_count,
            "current_character_count": current_character_count,
            "validation_before": validation_before,
            "validation_after": validation_after,
            "alignment_warnings": alignment_warnings,
            "stop_reasons": stop_reasons,
        }

    def _execute_iterative_mode(
        self,
        current_outline: str,
        characters: str,
        world_setting: str,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        strategy: str,
        mode_info: Dict[str, Any],
        auto_supplement_plan: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        validation_before = evaluate_story_coordination(current_outline or "", characters or "")
        resolved_strategy = self._resolve_strategy(
            strategy=strategy,
            validation=validation_before,
            chapters_needed=int(mode_info.get("chapters_needed") or 0),
            characters_needed=int(mode_info.get("characters_needed") or 0),
        )

        current_outline_text = current_outline or ""
        current_characters = characters or ""
        current_chapter_count = int(mode_info.get("current_chapter_count") or 0)
        current_character_count = int(mode_info.get("current_character_count") or 0)
        initial_chapter_count = current_chapter_count
        target_chapter_count = int(mode_info.get("target_chapter_count") or current_chapter_count)
        target_character_count = int(mode_info.get("target_character_count") or current_character_count)
        stage_target_character_count = target_character_count

        rounds: List[Dict[str, Any]] = []
        stop_reasons: List[str] = []
        outline_delta_parts: List[str] = []
        relationship_parts: List[str] = []
        character_delta_parts: List[str] = []
        outline_active = target_chapter_count > current_chapter_count
        character_active = target_character_count > current_character_count
        dynamic_character_task_target = self._coerce_non_negative_int(
            ((auto_supplement_plan or {}).get("character_plan") or {}).get("task_target_characters"),
        )

        def refresh_target_character_count() -> int:
            nonlocal target_character_count, character_active
            if dynamic_character_task_target <= target_character_count:
                return target_character_count
            total_chapter_delta = max(0, target_chapter_count - initial_chapter_count)
            if total_chapter_delta <= 0:
                return target_character_count
            completed_chapter_delta = min(
                total_chapter_delta,
                max(0, current_chapter_count - initial_chapter_count),
            )
            progress = completed_chapter_delta / total_chapter_delta
            dynamic_target = stage_target_character_count + int(
                math.ceil((dynamic_character_task_target - stage_target_character_count) * progress)
            )
            if dynamic_target > target_character_count:
                target_character_count = min(dynamic_character_task_target, dynamic_target)
            if target_character_count > current_character_count:
                character_active = True
            return target_character_count

        for iteration in range(1, self.ITERATIVE_MAX_ROUNDS + 1):
            refresh_target_character_count()
            remaining_chapters = max(0, target_chapter_count - current_chapter_count)
            remaining_characters = max(0, target_character_count - current_character_count)
            if remaining_chapters <= 0 and remaining_characters <= 0:
                break

            round_strategy = resolved_strategy
            if round_strategy == "balanced":
                round_strategy = self._select_balanced_round_order(
                    remaining_chapters=remaining_chapters,
                    target_chapter_count=target_chapter_count,
                    remaining_characters=remaining_characters,
                    target_character_count=target_character_count,
                )

            before_chapter_count = current_chapter_count
            before_character_count = current_character_count
            round_record: Dict[str, Any] = {
                "round": iteration,
                "mode": "iterative",
                "strategy": round_strategy,
                "before_chapter_count": before_chapter_count,
                "before_character_count": before_character_count,
            }

            def run_plot_side() -> Optional[Dict[str, Any]]:
                nonlocal current_outline_text, current_chapter_count, outline_active
                if not outline_active:
                    return None
                before_round_chapter_count = current_chapter_count
                pending = max(0, target_chapter_count - current_chapter_count)
                if pending <= 0:
                    outline_active = False
                    return None
                increment = min(self.ITERATIVE_CHAPTER_STEP, pending)
                result = self._run_outline_round(
                    current_outline=current_outline_text,
                    world_setting=world_setting,
                    characters=current_characters,
                    current_chapter_count=current_chapter_count,
                    increment=increment,
                    target_total_chapters=current_chapter_count + increment,
                    overall_target_chapters=target_chapter_count,
                )
                next_outline_text, round_outline_delta = self._resolve_iterative_outline_round_text(
                    current_outline_text,
                    result,
                    current_chapter_count,
                )
                self._append_unique_text(outline_delta_parts, round_outline_delta)
                current_outline_text = next_outline_text
                current_chapter_count = self._resolve_outline_count(
                    next_outline_text,
                    result.get("current_chapter_count"),
                    current_chapter_count,
                )
                if current_chapter_count <= before_round_chapter_count and not round_outline_delta:
                    outline_active = False
                    stop_reasons.append(
                        self._normalize_outline_stop_reason(
                            str(result.get("continue_reason") or ""),
                            before_chapter_count=before_round_chapter_count,
                            after_chapter_count=current_chapter_count,
                            outline_delta=round_outline_delta,
                        )
                    )
                elif (
                    not result.get("should_continue", True)
                    and current_chapter_count < target_chapter_count
                    and current_chapter_count <= before_round_chapter_count
                ):
                    outline_active = False
                    stop_reasons.append(
                        self._normalize_outline_stop_reason(
                            str(result.get("continue_reason") or ""),
                            before_chapter_count=before_round_chapter_count,
                            after_chapter_count=current_chapter_count,
                            outline_delta=round_outline_delta,
                        )
                    )
                return {
                    "increment_requested": increment,
                    "after_chapter_count": current_chapter_count,
                    "outline_delta": round_outline_delta,
                    "continue_reason": result.get("continue_reason", ""),
                }

            def run_character_side() -> Optional[Dict[str, Any]]:
                nonlocal current_characters, current_character_count, character_active, target_character_count
                if not character_active:
                    return None
                before_round_character_count = current_character_count
                refresh_target_character_count()
                pending = max(0, target_character_count - current_character_count)
                if pending <= 0:
                    character_active = False
                    return None
                increment = min(self.ITERATIVE_CHARACTER_STEP, pending)
                result = self._run_character_round(
                    current_characters=current_characters,
                    world_setting=world_setting,
                    plot_outline=current_outline_text,
                    current_character_count=current_character_count,
                    increment=increment,
                    target_total_characters=target_character_count,
                )
                next_characters = result.get("all_characters") or current_characters
                next_count = self._resolve_character_count(
                    next_characters,
                    result.get("current_character_count"),
                    current_character_count,
                )
                round_character_delta = self._extract_character_delta_text(current_characters, next_characters)
                self._append_unique_text(character_delta_parts, round_character_delta)
                self._append_unique_text(relationship_parts, result.get("character_relationships") or "")

                current_characters = next_characters

                if next_count <= before_round_character_count:
                    character_active = False
                    stop_reasons.append(
                        self._normalize_character_stop_reason(
                            str(result.get("continue_reason") or ""),
                            before_character_count=before_round_character_count,
                            after_character_count=before_round_character_count,
                            target_character_count=target_character_count,
                        )
                    )
                else:
                    current_character_count = next_count

                if next_count > before_round_character_count and result.get("should_optimize_first"):
                    character_active = False
                    stop_reasons.append("人物-情节匹配度偏低，已停止继续新增人物。")

                validation_score = int(result.get("post_validation_score") or 0)
                if (
                    next_count > before_round_character_count
                    and 0 < validation_score < 60
                    and current_character_count < target_character_count
                ):
                    character_active = False
                    stop_reasons.append(f"人物-情节匹配度降至 {validation_score}/100，已停止继续新增人物。")

                if (
                    next_count > before_round_character_count
                    and not result.get("should_continue", True)
                    and current_character_count < target_character_count
                ):
                    character_active = False
                    stop_reasons.append(
                        self._normalize_character_stop_reason(
                            str(result.get("continue_reason") or ""),
                            before_character_count=before_round_character_count,
                            after_character_count=current_character_count,
                            target_character_count=target_character_count,
                        )
                    )

                return {
                    "increment_requested": increment,
                    "target_character_count": target_character_count,
                    "after_character_count": current_character_count,
                    "post_validation_score": result.get("post_validation_score", 0),
                    "continue_reason": result.get("continue_reason", ""),
                    "cards_response_mode": result.get("cards_response_mode"),
                    "cards_retry_used": bool(result.get("cards_retry_used", False)),
                    "recognized_new_character_count": int(result.get("recognized_new_character_count") or 0),
                    "recognized_new_character_names": list(result.get("recognized_new_character_names") or []),
                }

            if round_strategy == "plot_first":
                round_record["plot"] = run_plot_side()
                round_record["character"] = run_character_side()
            else:
                round_record["character"] = run_character_side()
                round_record["plot"] = run_plot_side()

            round_record["after_chapter_count"] = current_chapter_count
            round_record["after_character_count"] = current_character_count

            if (
                current_chapter_count == before_chapter_count
                and current_character_count == before_character_count
            ):
                if not outline_active and not character_active:
                    break
                round_record["validation"] = evaluate_story_coordination(current_outline_text, current_characters)
                rounds.append(round_record)
                stop_reasons.append("本轮协同未产生任何新增内容，已提前停止。")
                break

            round_record["validation"] = evaluate_story_coordination(current_outline_text, current_characters)
            rounds.append(round_record)

            if not outline_active and not character_active:
                break

        if (
            (outline_active or character_active)
            and (
                current_chapter_count < target_chapter_count
                or current_character_count < target_character_count
            )
        ):
            stop_reasons.append(
                f"已达到单次任务的自动分轮上限（最多 {self.ITERATIVE_MAX_ROUNDS} 轮），"
                "剩余目标需继续发起下一次协同。"
            )

        new_character_names = self._collect_new_character_names(characters or "", current_characters)
        current_outline_text, alignment_repairs = self._auto_repair_character_alignment(
            current_outline_text,
            new_character_names,
        )
        current_outline_text = normalize_outline_text(current_outline_text, current_characters)
        normalized_outline_delta = "\n\n".join(outline_delta_parts)
        if normalized_outline_delta.strip():
            normalized_outline_delta = normalize_outline_text(normalized_outline_delta, current_characters)
        validation_after = evaluate_story_coordination(current_outline_text, current_characters)
        current_chapter_count = self._resolve_outline_count(
            current_outline_text,
            validation_after.get("chapter_count"),
            current_chapter_count,
        )
        current_character_count = self._resolve_character_count(
            current_characters,
            validation_after.get("character_count"),
            current_character_count,
        )
        alignment_warnings = self._build_alignment_warnings(new_character_names, validation_after)
        reached_target = (
            current_chapter_count >= target_chapter_count
            and current_character_count >= target_character_count
        )

        if reached_target:
            summary = "已通过分轮协同达到目标章节数和人物数。"
        else:
            pending_parts = []
            if current_chapter_count < target_chapter_count:
                pending_parts.append(f"章节尚差 {target_chapter_count - current_chapter_count} 章")
            if current_character_count < target_character_count:
                pending_parts.append(f"人物尚差 {target_character_count - current_character_count} 人")
            reason_text = "；".join(dict.fromkeys([reason for reason in stop_reasons if reason]))
            summary = "分轮协同已执行完当前可安全推进的部分"
            if pending_parts:
                summary += f"，{', '.join(pending_parts)}"
            if reason_text:
                summary += f"。停止原因：{reason_text}"
        repair_note = self._build_alignment_repair_note(alignment_repairs)
        if repair_note:
            summary += f" {repair_note}"
        if alignment_warnings:
            summary += f" {' '.join(alignment_warnings)}"

        return {
            "execution_mode": "iterative",
            "execution_mode_reason": mode_info.get("reason", ""),
            "strategy": resolved_strategy,
            "coordination_summary": summary,
            "plan": {
                "strategy": resolved_strategy,
                "mode": "iterative",
                "target_chapter_count": target_chapter_count,
                "target_character_count": target_character_count,
            },
            "plot_outline": current_outline_text,
            "characters": current_characters,
            "outline_delta": normalized_outline_delta,
            "character_delta": "\n\n".join(character_delta_parts),
            "character_relationships": "\n\n".join(relationship_parts),
            "outline_ops": rounds,
            "execution_rounds": rounds,
            "new_characters": new_character_names,
            "alignment_repairs": alignment_repairs,
            "current_chapter_count": current_chapter_count,
            "current_character_count": current_character_count,
            "validation_before": validation_before,
            "validation_after": validation_after,
            "alignment_warnings": alignment_warnings,
            "stop_reasons": stop_reasons,
        }

    def _execute_epic_mode(
        self,
        current_outline: str,
        characters: str,
        world_setting: str,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        strategy: str,
        mode_info: Dict[str, Any],
        epic_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from app.services.outline_merger import build_epic_volumes_json, parse_framework_to_volumes

        validation_before = evaluate_story_coordination(current_outline or "", characters or "")
        resolved_strategy = self._resolve_strategy(
            strategy=strategy,
            validation=validation_before,
            chapters_needed=int(mode_info.get("chapters_needed") or 0),
            characters_needed=int(mode_info.get("characters_needed") or 0),
        )

        normalized_epic_config = self._normalize_epic_config(epic_config)
        target_chapter_count = max(
            int(target_total_chapters or 0),
            self.planned_chapters_max or 0,
            self.EPIC_CHAPTER_THRESHOLD,
        )
        target_character_count = int(
            mode_info.get("target_character_count")
            or target_total_characters
            or mode_info.get("current_character_count")
            or 0
        )

        current_characters = characters or ""
        current_character_count = int(mode_info.get("current_character_count") or 0)
        character_relationships = ""
        character_delta = ""
        execution_rounds: List[Dict[str, Any]] = []
        stop_reasons: List[str] = []

        if resolved_strategy == "character_first" and target_character_count > current_character_count:
            character_program = self._expand_characters_to_target(
                current_characters=current_characters,
                world_setting=world_setting,
                plot_outline=current_outline or "",
                current_character_count=current_character_count,
                target_total_characters=target_character_count,
            )
            current_characters = character_program["characters_text"]
            current_character_count = character_program["current_character_count"]
            character_relationships = character_program["character_relationships"]
            character_delta = character_program["character_delta"]
            stop_reasons.extend(character_program["stop_reasons"])
            for item in character_program["rounds"]:
                execution_rounds.append({"stage": "character_expand", **item})

        framework_world_setting = world_setting or ""
        if current_outline and current_outline.strip():
            outline_context = current_outline[:6000]
            framework_world_setting = (
                f"{framework_world_setting}\n\n【现有主线与基础大纲】\n{outline_context}"
                if framework_world_setting
                else f"【现有主线与基础大纲】\n{outline_context}"
            )

        explicit_range = normalized_epic_config.get("chapter_range")
        chapter_range = (
            explicit_range
            if explicit_range
            else self._estimate_epic_chapter_range(target_chapter_count)
        )
        total_volumes = int(
            normalized_epic_config.get("total_volumes")
            or self._estimate_epic_volume_count(target_chapter_count)
        )
        framework_result = self._get_expander().generate_epic_framework(
            world_setting=framework_world_setting,
            characters=current_characters,
            total_volumes=total_volumes,
            total_chapters_range=chapter_range,
        )

        plot_outline = framework_result.get("expanded_outline") or current_outline or ""
        estimated_chapters = int(framework_result.get("estimated_chapters") or target_chapter_count)
        try:
            volumes_data = parse_framework_to_volumes(plot_outline, total_volumes)
            epic_volumes_detail = build_epic_volumes_json(volumes_data)
        except Exception:
            volumes_data = {
                "total_volumes": total_volumes,
                "framework_header": plot_outline,
                "framework_footer": "",
                "volumes": {},
            }
            epic_volumes_detail = build_epic_volumes_json(volumes_data)
        execution_rounds.append(
            {
                "stage": "epic_framework",
                "volumes": total_volumes,
                "target_chapter_range": list(chapter_range),
                "estimated_chapters": estimated_chapters,
            }
        )

        if resolved_strategy != "character_first" and target_character_count > current_character_count:
            character_program = self._expand_characters_to_target(
                current_characters=current_characters,
                world_setting=world_setting,
                plot_outline=plot_outline,
                current_character_count=current_character_count,
                target_total_characters=target_character_count,
            )
            current_characters = character_program["characters_text"]
            current_character_count = character_program["current_character_count"]
            character_relationships = character_program["character_relationships"] or character_relationships
            character_delta = character_program["character_delta"] or character_delta
            stop_reasons.extend(character_program["stop_reasons"])
            for item in character_program["rounds"]:
                execution_rounds.append({"stage": "character_expand", **item})

        new_character_names = self._collect_new_character_names(characters or "", current_characters)
        plot_outline, alignment_repairs = self._auto_repair_character_alignment(
            plot_outline,
            new_character_names,
        )
        validation_after = self._build_epic_validation(
            framework_text=plot_outline,
            characters_text=current_characters,
            estimated_chapters=estimated_chapters,
        )
        alignment_warnings = self._build_alignment_warnings(new_character_names, validation_after)

        summary = (
            f"已切换为长篇框架优先协同，规划约 {estimated_chapters} 章、{total_volumes} 卷，"
            "后续建议按卷继续展开细纲。"
        )
        if stop_reasons:
            summary += f" 当前已记录阶段性停止原因：{'；'.join(dict.fromkeys(stop_reasons))}"
        repair_note = self._build_alignment_repair_note(alignment_repairs)
        if repair_note:
            summary += f" {repair_note}"
        if alignment_warnings:
            summary += f" {' '.join(alignment_warnings)}"

        return {
            "execution_mode": "epic",
            "execution_mode_reason": mode_info.get("reason", ""),
            "strategy": resolved_strategy,
            "coordination_summary": summary,
            "plan": {
                "strategy": resolved_strategy,
                "mode": "epic",
                "total_volumes": total_volumes,
                "target_chapter_range": list(chapter_range),
            },
            "plot_outline": plot_outline,
            "characters": current_characters,
            "outline_delta": plot_outline,
            "character_delta": character_delta,
            "character_relationships": character_relationships,
            "outline_ops": execution_rounds,
            "execution_rounds": execution_rounds,
            "new_characters": new_character_names,
            "alignment_repairs": alignment_repairs,
            "current_chapter_count": estimated_chapters,
            "current_character_count": current_character_count,
            "validation_before": validation_before,
            "validation_after": validation_after,
            "alignment_warnings": alignment_warnings,
            "epic_framework": plot_outline,
            "epic_volumes_detail": epic_volumes_detail,
            "epic_total_volumes": total_volumes,
            "epic_chapter_range": list(chapter_range),
            "stop_reasons": stop_reasons,
        }

    def _execute_volume_detail_mode(
        self,
        current_outline: str,
        characters: str,
        world_setting: str,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        strategy: str,
        mode_info: Dict[str, Any],
        volume_detail_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from app.services.outline_merger import (
            build_epic_volumes_json,
            merge_volumes_to_outline,
            update_volume_detail,
        )
        from app.services.volume_connector import VolumeConnector

        normalized_volume_detail_config = self._normalize_volume_detail_config(volume_detail_config)
        if not normalized_volume_detail_config.get("framework_content"):
            raise ValueError("单卷细化协同缺少长篇框架上下文。")
        if not normalized_volume_detail_config.get("target_volume_index"):
            raise ValueError("单卷细化协同缺少目标卷编号。")
        if not normalized_volume_detail_config.get("chapters_count_range"):
            raise ValueError("单卷细化协同缺少本卷章节范围。")
        if not normalized_volume_detail_config.get("start_chapter_num"):
            raise ValueError("单卷细化协同缺少起始章节号。")

        validation_before = evaluate_story_coordination(current_outline or "", characters or "")
        resolved_strategy = self._resolve_strategy(
            strategy=strategy,
            validation=validation_before,
            chapters_needed=int(mode_info.get("chapters_needed") or 0),
            characters_needed=int(mode_info.get("characters_needed") or 0),
        )

        current_characters = characters or ""
        current_character_count = len(extract_character_names(current_characters))
        target_character_count = int(
            mode_info.get("target_character_count")
            or target_total_characters
            or current_character_count
        )
        target_volume_index = int(normalized_volume_detail_config["target_volume_index"])
        chapters_count_range = normalized_volume_detail_config["chapters_count_range"]
        start_chapter_num = int(normalized_volume_detail_config["start_chapter_num"])
        stop_reasons: List[str] = []
        execution_rounds: List[Dict[str, Any]] = []
        character_relationships = ""
        character_delta = ""

        if resolved_strategy == "character_first" and target_character_count > current_character_count:
            character_program = self._expand_characters_to_target(
                current_characters=current_characters,
                world_setting=world_setting,
                plot_outline=current_outline or normalized_volume_detail_config["framework_content"],
                current_character_count=current_character_count,
                target_total_characters=target_character_count,
            )
            current_characters = character_program["characters_text"]
            current_character_count = character_program["current_character_count"]
            character_relationships = character_program["character_relationships"]
            character_delta = character_program["character_delta"]
            stop_reasons.extend(character_program["stop_reasons"])
            for item in character_program["rounds"]:
                execution_rounds.append({"stage": "character_expand", **item})

        prev_volume_summary = None
        previous_volume_detail = normalized_volume_detail_config.get("previous_volume_detail")
        if previous_volume_detail and target_volume_index > 1:
            try:
                connector = VolumeConnector(llm=self._get_expander().llm)
                prev_volume_summary = connector.extract_volume_summary(
                    previous_volume_detail,
                    target_volume_index - 1,
                )
            except Exception:
                prev_volume_summary = None

        volume_result = self._get_expander().expand_volume_detail(
            framework_content=normalized_volume_detail_config["framework_content"],
            target_volume_index=target_volume_index,
            world_setting=world_setting,
            characters=current_characters,
            start_chapter_num=start_chapter_num,
            chapters_count_range=chapters_count_range,
            prev_volume_summary=prev_volume_summary,
            framework_header=normalized_volume_detail_config.get("framework_header") or None,
            framework_footer=normalized_volume_detail_config.get("framework_footer") or None,
        )

        chapters_start = int(volume_result.get("chapters_start") or start_chapter_num)
        chapters_end = int(
            volume_result.get("chapters_end")
            or (chapters_start + int(chapters_count_range[1]) - 1)
        )
        execution_rounds.append(
            {
                "stage": "volume_detail",
                "volume_index": target_volume_index,
                "chapter_range": [chapters_start, chapters_end],
            }
        )

        volumes_data = normalized_volume_detail_config.get("volumes_data") or {}
        volumes_data = json.loads(json.dumps(volumes_data, ensure_ascii=False))
        volumes_data = update_volume_detail(
            volumes_data,
            target_volume_index,
            volume_result["expanded_outline"],
            [chapters_start, chapters_end],
        )
        plot_outline = merge_volumes_to_outline(volumes_data)

        if resolved_strategy != "character_first" and target_character_count > current_character_count:
            character_focus_outline = str(volume_result.get("expanded_outline") or "").strip() or plot_outline
            character_program = self._expand_characters_to_target(
                current_characters=current_characters,
                world_setting=world_setting,
                plot_outline=character_focus_outline,
                current_character_count=current_character_count,
                target_total_characters=target_character_count,
            )
            current_characters = character_program["characters_text"]
            current_character_count = character_program["current_character_count"]
            character_relationships = character_program["character_relationships"] or character_relationships
            character_delta = character_program["character_delta"] or character_delta
            stop_reasons.extend(character_program["stop_reasons"])
            for item in character_program["rounds"]:
                execution_rounds.append({"stage": "character_expand", **item})

        new_character_names = self._collect_new_character_names(characters or "", current_characters)
        repaired_volume_detail, alignment_repairs = self._auto_repair_character_alignment(
            volume_result["expanded_outline"],
            new_character_names,
        )
        if repaired_volume_detail != volume_result["expanded_outline"]:
            volume_result["expanded_outline"] = repaired_volume_detail
            volumes_data = update_volume_detail(
                volumes_data,
                target_volume_index,
                volume_result["expanded_outline"],
                [chapters_start, chapters_end],
            )
            plot_outline = merge_volumes_to_outline(volumes_data)
        validation_after = evaluate_story_coordination(plot_outline, current_characters)
        alignment_warnings = self._build_alignment_warnings(new_character_names, validation_after)
        total_chapter_count = max(
            chapters_end,
            self._estimate_total_chapters_from_volumes_data(volumes_data),
        )

        summary = (
            f"已细化第{target_volume_index}卷，生成第{chapters_start}-{chapters_end}章的卷级细纲，"
            "并同步校准相关人物承接。"
        )
        if normalized_volume_detail_config.get("existing_volume_detail"):
            summary += " 本次覆盖了该卷原有细纲。"
        if stop_reasons:
            summary += f" 当前已记录阶段性停止原因：{'；'.join(dict.fromkeys(stop_reasons))}"
        repair_note = self._build_alignment_repair_note(alignment_repairs)
        if repair_note:
            summary += f" {repair_note}"
        if alignment_warnings:
            summary += f" {' '.join(alignment_warnings)}"

        return {
            "execution_mode": "volume_detail",
            "execution_mode_reason": mode_info.get("reason", ""),
            "strategy": resolved_strategy,
            "coordination_summary": summary,
            "plan": {
                "strategy": resolved_strategy,
                "mode": "volume_detail",
                "target_volume_index": target_volume_index,
                "chapter_range": [chapters_start, chapters_end],
            },
            "plot_outline": plot_outline,
            "characters": current_characters,
            "outline_delta": volume_result["expanded_outline"],
            "character_delta": character_delta,
            "character_relationships": character_relationships,
            "outline_ops": execution_rounds,
            "execution_rounds": execution_rounds,
            "new_characters": new_character_names,
            "alignment_repairs": alignment_repairs,
            "current_chapter_count": total_chapter_count,
            "current_character_count": current_character_count,
            "validation_before": validation_before,
            "validation_after": validation_after,
            "alignment_warnings": alignment_warnings,
            "epic_framework": normalized_volume_detail_config["framework_content"],
            "epic_volumes_detail": build_epic_volumes_json(volumes_data),
            "epic_total_volumes": normalized_volume_detail_config.get("total_volumes"),
            "volume_index": target_volume_index,
            "volume_chapter_range": [chapters_start, chapters_end],
            "stop_reasons": stop_reasons,
        }

    def execute(
        self,
        current_outline: str,
        characters: str,
        world_setting: str,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        strategy: str = "auto",
        expansion_mode: str = "auto",
        epic_config: Optional[Dict[str, Any]] = None,
        volume_detail_config: Optional[Dict[str, Any]] = None,
        auto_supplement_plan: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        current_outline = sanitize_outline_alignment_placeholders(current_outline or "")
        mode_info = self.determine_execution_mode(
            current_outline=current_outline,
            characters=characters,
            target_total_chapters=target_total_chapters,
            target_total_characters=target_total_characters,
            expansion_mode=expansion_mode,
            epic_config=epic_config,
            volume_detail_config=volume_detail_config,
        )
        estimated_rounds = self._estimate_execution_rounds_from_mode_info(mode_info)
        validation = evaluate_story_coordination(current_outline or "", characters or "")
        normalized_volume_detail_config = self._normalize_volume_detail_config(volume_detail_config)
        effective_expansion_mode = (
            "epic_framework"
            if str(mode_info.get("mode") or "").strip() == "epic"
            else (
                "volume_detail"
                if str(mode_info.get("mode") or "").strip() == "volume_detail"
                else (
                    expansion_mode
                    if expansion_mode in {"total", "epic_framework", "volume_detail"}
                    else "total"
                )
            )
        )
        self._configure_story_expansion_runtime_models(
            current_outline=current_outline,
            characters=characters,
            world_setting=world_setting,
            validation=validation,
            mode_info=mode_info,
            estimated_rounds=estimated_rounds,
            expansion_mode=effective_expansion_mode,
            volume_detail_config=normalized_volume_detail_config,
        )

        chapters_needed = int(mode_info.get("chapters_needed") or 0)
        characters_needed = int(mode_info.get("characters_needed") or 0)
        allow_volume_regeneration = (
            mode_info.get("mode") == "volume_detail"
            and bool(normalized_volume_detail_config.get("existing_volume_detail"))
        )
        if chapters_needed <= 0 and characters_needed <= 0 and not allow_volume_regeneration:
            raise ValueError("目标章节数和目标人物数均不高于当前内容，无需协同拓展。")

        mode = mode_info["mode"]
        if mode == "volume_detail":
            return self._execute_volume_detail_mode(
                current_outline=current_outline,
                characters=characters,
                world_setting=world_setting,
                target_total_chapters=target_total_chapters,
                target_total_characters=target_total_characters,
                strategy=strategy,
                mode_info=mode_info,
                volume_detail_config=volume_detail_config,
            )
        if mode == "epic":
            return self._execute_epic_mode(
                current_outline=current_outline,
                characters=characters,
                world_setting=world_setting,
                target_total_chapters=target_total_chapters,
                target_total_characters=target_total_characters,
                strategy=strategy,
                mode_info=mode_info,
                epic_config=epic_config,
            )
        if mode == "iterative":
            return self._execute_iterative_mode(
                current_outline=current_outline,
                characters=characters,
                world_setting=world_setting,
                target_total_chapters=target_total_chapters,
                target_total_characters=target_total_characters,
                strategy=strategy,
                mode_info=mode_info,
                auto_supplement_plan=auto_supplement_plan,
            )
        return self._execute_delta_mode(
            current_outline=current_outline,
            characters=characters,
            world_setting=world_setting,
            target_total_chapters=target_total_chapters,
            target_total_characters=target_total_characters,
            strategy=strategy,
            mode_info=mode_info,
        )
