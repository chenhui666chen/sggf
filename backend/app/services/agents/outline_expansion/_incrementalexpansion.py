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
from ...story_expansion_coord_pkg import normalize_outline_text
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


OUTLINE_PLAIN_FIELD_LINE_PATTERN = re.compile(
    r"^\s*-\s*(场景目标|冲突设计|关键事件|涉及人物|人物推进|情节作用|结尾钩子|爽点类型|伏笔事项)\s*[：:]\s*(.*)$"
)


def _render_normalized_outline_as_markdown(text: str) -> str:
    lines: List[str] = []
    for raw_line in str(text or "").splitlines():
        stripped = raw_line.strip()
        if re.match(r"^第\s*\d+\s*章\s*[：:]", stripped):
            lines.append(f"### {stripped}")
            continue

        field_match = OUTLINE_PLAIN_FIELD_LINE_PATTERN.match(stripped)
        if field_match:
            label = field_match.group(1)
            value = field_match.group(2)
            lines.append(f"- **{label}**：{value}")
            continue

        lines.append(raw_line)

    return "\n".join(lines).strip()


def _resolve_chapter_renumberer():
    try:
        from .. import outline_expander as outline_expander_module

        factory = getattr(outline_expander_module, "get_chapter_renumberer", None)
        if callable(factory):
            return factory()
    except Exception:
        pass
    return get_chapter_renumberer()


def _resolve_consistency_validator(*, strict_mode: bool = True):
    try:
        from .. import outline_expander as outline_expander_module

        factory = getattr(outline_expander_module, "get_consistency_validator", None)
        if callable(factory):
            return factory(strict_mode=strict_mode)
    except Exception:
        pass
    return get_consistency_validator(strict_mode=strict_mode)


class IncrementalExpansionMixin:
    def expand_plot_outline(self, current_outline: str, world_setting: str,
                          characters: str, target_chapters: int = 50) -> Dict[str, Any]:
        current_count = self.count_chapters_in_outline(current_outline)
        if target_chapters <= current_count:
            return {
                "expanded_outline": current_outline,
                "chapter_breakdown": "",
                "plot_arcs": {},
                "current_chapter_count": current_count,
                "target_chapters": target_chapters,
                "should_continue": False,
                "continue_reason": "目标章节数未超过当前章节数，无需继续扩展。",
                "expansion_analysis": "目标章节数未超过当前章节数，无需继续扩展。",
            }

        result = self.expand_plot_outline_incremental(
            current_outline=current_outline,
            world_setting=world_setting,
            characters=characters,
            current_chapter_count=current_count,
            increment=target_chapters - current_count,
            target_total_chapters=target_chapters,
        )
        result["target_chapters"] = target_chapters
        result["expansion_analysis"] = result.get("continue_reason") or result.get("expansion_analysis", "")
        return result

    def expand_characters(self, main_characters: str, world_setting: str,
                        plot_outline: str, target_count: int = 15) -> Dict[str, Any]:
        current_count = self.count_characters_in_text(main_characters)
        if target_count <= current_count:
            return {
                "all_characters": main_characters,
                "character_relationships": "",
                "role_distribution": {},
                "current_character_count": current_count,
                "target_count": target_count,
                "should_continue": False,
                "continue_reason": "目标人物数未超过当前人物数，无需继续扩展。",
                "character_analysis": "目标人物数未超过当前人物数，无需继续扩展。",
            }

        result = self.expand_characters_incremental(
            main_characters=main_characters,
            world_setting=world_setting,
            plot_outline=plot_outline,
            current_character_count=current_count,
            increment=target_count - current_count,
            target_total_characters=target_count,
        )
        result["target_count"] = target_count
        result["character_analysis"] = result.get("continue_reason") or result.get("character_analysis", "")
        return result

    def generate_expansion_summary(self, outline_expansion: Dict[str, Any],
                                  character_expansion: Dict[str, Any]) -> str:
        return f"""
{'='*70}
【长篇小说扩展总结报告】
{'='*70}

## 一、情节大纲扩展

### 目标章节数
{outline_expansion.get('target_chapters', 'N/A')} 章

### 扩展策略
{self._story_stringify(outline_expansion.get('expansion_analysis'))}

### 情节线索
{self._story_stringify(outline_expansion.get('plot_arcs'))}

### 章节分解（示例前5章）
{self._story_stringify(outline_expansion.get('chapter_breakdown'), limit=500)}

---

## 二、人物体系扩展

### 目标人物数
{character_expansion.get('target_count', 'N/A')} 个

### 角色定位
{self._story_stringify(character_expansion.get('role_distribution'))}

### 人物关系网络
{self._story_stringify(character_expansion.get('character_relationships'))}

{'='*70}
""".strip()

    def expand_plot_outline_incremental(self, current_outline: str, world_setting: str,
                                       characters: str, current_chapter_count: int,
                                       increment: int = 15,
                                       target_total_chapters: Optional[int] = None,
                                       overall_target_chapters: Optional[int] = None) -> Dict[str, Any]:
        target_chapters = target_total_chapters or (current_chapter_count + increment)
        story_target_chapters = max(
            int(target_chapters or 0),
            int(overall_target_chapters or 0),
            int(getattr(self, "planned_chapters_max", 0) or 0),
            int(current_chapter_count or 0) + int(increment or 0),
        )
        new_chapter_start = max(int(current_chapter_count or 0), 0) + 1
        anti_finale_instruction = ""
        if story_target_chapters > target_chapters:
            anti_finale_instruction = (
                f"\n10. 当前距离全书目标仍至少还有 {story_target_chapters - target_chapters} 章，"
                "严禁出现“终章 / 大结局 / 完结 / 终局 / 尾声 / 最终决战”等提前收官字样；"
                "只能写阶段性高潮和下一阶段钩子。"
            )

        chapter_schema = json.dumps(
            {
                "story_overview": "本轮阶段摘要，可留空",
                "chapters": [
                    {
                        "chapter_number": 1,
                        "title": "章节标题",
                        "scene_goal": "场景目标",
                        "conflict_design": "冲突设计",
                        "key_events": "关键事件",
                        "involved_characters": ["角色A", "角色B"],
                        "character_progress": "人物推进",
                        "plot_function": "情节作用",
                        "ending_hook": "结尾钩子",
                        "highlight_type": "爽点类型",
                        "foreshadowing_item": "伏笔事项",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        characters_excerpt = self._story_build_character_context(
            characters,
            detail_limit=CHARACTER_EXPANSION_CARD_CONTEXT_LIMIT,
        ) or "（暂无人物体系）"
        chapter_user_prompt = f"""请基于当前大纲执行“常规协同”的纯章节式扩展。

【协同模式约束】
1. 当前模式是常规协同，禁止使用卷级结构。
2. 不要输出 `volumes`、`novel_plan.volumes`、`volume_plan`、`stage_roadmap`、`total_volumes`、`chapter_span` 等分卷/卷级字段。
3. 如需概括本轮阶段目标，只能写在 `story_overview` 中，且控制在 120 字以内。

【全书目标】
- 全书目标规模：约 {story_target_chapters} 章

【本轮目标】
- 当前已有章节数：{current_chapter_count}
- 本轮只新增：第 {new_chapter_start} 章到第 {target_chapters} 章
- 本轮补齐后，总章节数达到：{target_chapters}

【当前大纲】
{current_outline}

【人物体系】
{characters_excerpt}

【世界观】
{world_setting}

【输出 JSON Schema】
{chapter_schema}

要求：
1. `chapters` 中的 chapter_number 必须从现有章节后连续延伸，只输出第 {new_chapter_start} 章到第 {target_chapters} 章。
2. 不要改写已存在的章节，不要重写第 1 章到第 {current_chapter_count} 章。
3. 虽然本轮只写到第 {target_chapters} 章，但全书目标约 {story_target_chapters} 章，不要提前收束终局或写成完结篇。
4. 每章必须包含：场景目标、冲突设计、关键事件、涉及人物、人物推进、情节作用、结尾钩子；可选补充爽点类型、伏笔事项。
5. `关键事件` 请概括 2-4 个本章必须发生的节点，不要写成空泛总结。
6. `人物推进` 要明确主角或关键配角发生了什么变化，关系如何前进。
7. `情节作用` 要说明本章在整段剧情中的职责，例如承接、升级、爆点前置、伏笔回收。
8. 返回结构必须以 `chapters` 为核心，不要把结果包进卷级结构后再嵌套输出。
9. 只返回 JSON，不要解释，不要 Markdown 代码块。{anti_finale_instruction}"""
        chapter_payload = self._story_invoke_llm_json(
            self.llm,
            "你是小说章节规划师，请按常规协同输出纯章节式 JSON。",
            chapter_user_prompt,
            fallback={"story_overview": "", "chapters": []},
        )
        if not self._story_extract_chapters_payload(chapter_payload):
            retry_chapter_payload = self._story_invoke_llm_json(
                self.llm,
                "你是小说章节规划师，请按常规协同输出纯章节式 JSON。",
                chapter_user_prompt
                + f"\n\n补充要求：必须返回 `chapters` 数组，并直接给出第 {new_chapter_start} 章到第 {target_chapters} 章的可执行新增章节规划；不要只写概述，不要改用卷级结构。",
                fallback={"story_overview": "", "chapters": []},
            )
            if self._story_extract_chapters_payload(retry_chapter_payload):
                chapter_payload = retry_chapter_payload

        if self._story_contains_premature_finale_signal(
            chapter_payload,
            current_round_target=target_chapters,
            overall_target_chapters=story_target_chapters,
        ):
            repaired_payload = self._story_rewrite_payload_without_premature_finale(
                payload=chapter_payload,
                current_outline=current_outline,
                characters=characters,
                world_setting=world_setting,
                new_chapter_start=new_chapter_start,
                target_chapters=target_chapters,
                story_target_chapters=story_target_chapters,
                chapter_schema=chapter_schema,
            )
            if self._story_extract_chapters_payload(repaired_payload):
                chapter_payload = repaired_payload

        chapter_breakdown, max_chapter = self._story_render_chapter_breakdown(current_outline, chapter_payload)
        expanded_outline = self._story_render_incremental_outline(chapter_payload, chapter_breakdown) or current_outline
        current_total = max(
            int(current_chapter_count or 0),
            self._story_count_rendered_outline_chapters(current_outline),
            self._story_count_rendered_outline_chapters(chapter_breakdown),
            max_chapter,
        )

        decision_payload = self._story_invoke_llm_json(
            self.llm,
            "请输出是否继续扩展的 JSON。",
            f"""请基于以下真实上下文判断当前章节扩展是否还需要继续。

【当前状态】
- 扩展前章节数：{current_chapter_count}
- 目标章节数：{target_chapters}
- 当前可确认章节数：{current_total}

【当前大纲】
{current_outline}

【本轮阶段摘要】
{expanded_outline}

【章节细纲】
{chapter_breakdown}

请只返回 JSON：
{{
  "should_continue": true,
  "reason": "100字以内说明"
}}

判断原则：
1. 若当前可确认章节数仍小于目标章节数，且细纲没有补齐，优先返回 true。
2. 若本轮没有产生可用的新章节规划，返回 false，并明确说明需要补什么上下文。
3. 不要脱离上述上下文泛泛而谈。
4. 若全书目标仍高于本轮目标，只能说明“本轮阶段性规划已完成，可继续下一轮扩展”，不要使用全书完结、终章、终局、收官、大结局等措辞。""",
            fallback={"should_continue": False, "reason": ""},
        )
        continue_reason = self._story_normalize_incremental_continue_reason(
            str(decision_payload.get("reason") or "").strip(),
            current_total=current_total,
            target_chapters=target_chapters,
            story_target_chapters=story_target_chapters,
        )

        return {
            "expanded_outline": expanded_outline,
            "chapter_breakdown": chapter_breakdown,
            "plot_arcs": chapter_payload,
            "current_chapter_count": current_total,
            "target_chapters": target_chapters,
            "should_continue": bool(decision_payload.get("should_continue", False)),
            "continue_reason": continue_reason,
            "expansion_analysis": continue_reason,
        }

    def expand_characters_incremental(self, main_characters: str, world_setting: str,
                                     plot_outline: str, current_character_count: int,
                                     increment: int = 5,
                                     target_total_characters: Optional[int] = None) -> Dict[str, Any]:
        existing_names = self._story_extract_character_names(main_characters)
        current_character_count = max(int(current_character_count or 0), len(existing_names))
        target_count = target_total_characters or (current_character_count + increment)
        characters_needed = max(0, int(target_count) - int(current_character_count))
        existing_names_text = "、".join(existing_names) if existing_names else "暂无"
        world_excerpt = self._story_truncate_text(world_setting, limit=2800) or "（暂无世界观补充）"
        outline_excerpt = self._story_truncate_text(
            plot_outline,
            limit=CHARACTER_EXPANSION_OUTLINE_CONTEXT_LIMIT,
        ) or "（暂无当前大纲）"
        characters_excerpt = self._story_build_character_context(
            main_characters,
            detail_limit=CHARACTER_EXPANSION_CARD_CONTEXT_LIMIT,
        ) or "（暂无现有人物卡）"

        cards_prompt = f"""你是小说人物协同设计师，请为当前故事阶段补充“新增角色卡”。

【目标】
- 当前人物数：{current_character_count}
- 目标人物数：{target_count}
- 本轮需新增：{characters_needed} 个

【现有角色名单】
{existing_names_text}

【现有人物卡】
{characters_excerpt}

【当前大纲】
{outline_excerpt}

【世界观】
{world_excerpt}

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
  ]
}}

要求：
1. 严格新增 {characters_needed} 个角色，禁止复写现有角色卡。
2. 新角色姓名不得与现有角色重复，且必须符合当前题材。
3. 每个新角色都必须承担明确剧情职责，至少与一个现有角色或主线冲突形成关系。
4. `key_relationships` 只保留当前最关键的 3-5 条关系，不要写已解决或纯历史背景关系总账。
5. `mainline_role` / `mainline_clues` 只保留当前阶段仍驱动剧情的内容，不要把多个阶段职责堆在一起。
6. 不要输出 Markdown，不要解释，只返回合法 JSON。"""

        cards_retry_used = False
        cards_response = self.character_designer.process(cards_prompt, {})
        new_cards, new_names, cards_response_mode = self._story_parse_character_cards_response(
            cards_response,
            existing_names=existing_names,
        )
        if characters_needed > 0 and not new_names:
            cards_retry_used = True
            retry_cards_response = self.character_designer.process(
                cards_prompt
                + f"""

补充要求：
1. 上次结果未识别到有效新增角色，本次必须至少补出 {characters_needed} 个新角色。
2. 优先返回合法 JSON；如果仍无法稳定输出 JSON，允许直接输出标准人物卡正文，但每个新角色都必须以 `### 【姓名】：` 开头。
3. 禁止只返回分析、建议、阵营标题或人物名单，必须给出可直接并入人物体系的完整角色卡。""",
                {},
            )
            new_cards, new_names, cards_response_mode = self._story_parse_character_cards_response(
                retry_cards_response,
                existing_names=existing_names,
            )
        elif characters_needed > 0 and len(new_names) < characters_needed:
            cards_retry_used = True
            remaining_count = max(0, characters_needed - len(new_names))
            recognized_names_text = "、".join(new_names) if new_names else "无"
            retry_cards_response = self.character_designer.process(
                cards_prompt
                + f"""

补充要求：
1. 上次仅识别到 {len(new_names)} 个有效新增角色，仍缺 {remaining_count} 个。
2. 本次只补足剩余 {remaining_count} 个新角色，禁止重复输出已经给出的角色：{recognized_names_text}。
3. 优先返回合法 JSON；如果仍无法稳定输出 JSON，允许直接输出标准人物卡正文，但每个新角色都必须以 `### 【姓名】：` 开头。
4. 禁止只返回分析、建议、阵营标题或人物名单，必须补齐可直接并入人物体系的完整角色卡。""",
                {},
            )
            retry_cards, retry_names, retry_mode = self._story_parse_character_cards_response(
                retry_cards_response,
                existing_names=[*existing_names, *new_names],
            )
            if retry_cards.strip():
                new_cards = (
                    f"{new_cards.rstrip()}\n\n{retry_cards.strip()}"
                    if new_cards.strip()
                    else retry_cards.strip()
                )
            if retry_names:
                new_names = list(dict.fromkeys([*new_names, *retry_names]))
            if retry_mode and not cards_response_mode:
                cards_response_mode = retry_mode

        new_cards_excerpt = self._story_build_character_context(
            new_cards,
            detail_limit=CHARACTER_EXPANSION_NEW_CARD_CONTEXT_LIMIT,
        ) or "（本轮未新增结构化角色卡）"
        patch_prompt = f"""你是小说人物统筹编辑，请只补充“已有角色需要新增的关系/职责补丁”。

【现有角色名单】
{existing_names_text}

【现有人物卡】
{characters_excerpt}

【本轮新增角色卡】
{new_cards_excerpt}

【当前大纲】
{outline_excerpt}

请只返回 JSON：
{{
  "updates": [
    {{
      "name": "已有角色名",
      "relationship_updates": [
        {{
          "target": "目标角色名",
          "description": "新增关系变化"
        }}
      ],
      "mainline_clues_patch": "需补充的关联线索",
      "mainline_role_patch": "需补充的剧情职责",
      "growth_direction_patch": "需补充的成长方向"
    }}
  ]
}}

要求：
1. 只对确有必要的已有角色输出补丁，没有必要可返回空数组。
2. 不要重写完整人物卡，不要新增不存在的角色名。
3. 重点补“新增角色引入后，老角色需要怎样承接”。"""

        patch_payload = self._story_invoke_agent_json(
            self.character_designer,
            patch_prompt,
            fallback={"updates": []},
        )
        merged_characters = self._story_merge_character_cards_with_patches(
            main_characters,
            new_cards,
            patch_payload,
        )
        merged_excerpt = self._story_build_character_context(
            merged_characters,
            detail_limit=CHARACTER_EXPANSION_MERGED_CONTEXT_LIMIT,
        ) or "（暂无完整人物体系）"
        relationship_prompt = f"""你是小说人物关系规划师，请基于当前完整人物体系输出关系网络 JSON。

【人物体系】
{merged_excerpt}

【当前大纲】
{outline_excerpt}

请只返回 JSON：
{{
  "relationship_groups": [
    {{
      "group": "主角阵营内部/对手阵营内部/跨阵营关系/支持角色关系",
      "relationships": [
        {{
          "source": "角色A",
          "target": "角色B",
          "type": "盟友/对手/师徒/利用/怀疑/亲人等",
          "description": "20字以内关系说明"
        }}
      ]
    }}
  ]
}}

要求：
1. 重点输出与本轮新增角色有关的关键关系。
2. 不要编造人物体系中不存在的角色。
3. 关系分组可以为空，但 JSON 结构必须合法。"""

        relationship_payload = self._story_invoke_agent_json(
            self.character_designer,
            relationship_prompt,
            fallback={"relationship_groups": []},
        )
        character_relationships = self._story_render_relationships(relationship_payload)

        distribution_prompt = f"""请基于以下人物体系统计角色分布，只返回 JSON。

【人物体系】
{merged_excerpt}

返回格式：
{{
  "主角": 数量,
  "配角": 数量,
  "对手": 数量,
  "支持角色": 数量,
  "中立角色": 数量
}}"""

        role_distribution = self._story_invoke_agent_json(
            self.character_designer,
            distribution_prompt,
            fallback={},
        )

        unique_new_names: List[str] = []
        normalized_existing = {self._story_normalize_name(name) for name in existing_names}
        normalized_unique_new_names: set[str] = set()
        for name in new_names:
            normalized_name = self._story_normalize_name(name)
            if not normalized_name or normalized_name in normalized_existing:
                continue
            if normalized_name in normalized_unique_new_names:
                continue
            unique_new_names.append(name)
            normalized_unique_new_names.add(normalized_name)

        decision_prompt = f"""你是小说人物协同审校员，请判断当前人物扩展是否还需要继续。

【当前状态】
- 扩展前人物数：{current_character_count}
- 目标人物数：{target_count}
- 本轮实际新增：{len(unique_new_names)}
- 当前可确认人物数：{max(current_character_count + len(unique_new_names), len(set(existing_names) | set(unique_new_names)))}
- 新增角色：{'、'.join(unique_new_names) if unique_new_names else '无'}

【当前大纲】
{outline_excerpt}

【完整人物体系】
{merged_excerpt}

请只返回 JSON：
{{
  "should_continue": true,
  "reason": "100字以内说明"
}}

判断原则：
1. 若目标人数已达到，通常返回 false。
2. 若本轮未新增有效角色，返回 false，并说明缺口原因。
3. 若大纲仍存在明显角色槽位缺口且目标人数未达到，可返回 true。
4. “当前可确认人物数”只能按结构化人物卡数量计算，不要把关系网提及、补丁提及、阵营引用重复计入。"""

        current_confirmed_count = max(
            current_character_count + len(unique_new_names),
            len(set(existing_names) | set(unique_new_names)),
        )
        decision_payload = self._story_invoke_agent_json(
            self.character_designer,
            decision_prompt,
            fallback={
                "should_continue": bool(unique_new_names) and current_confirmed_count < target_count,
                "reason": "",
            },
        )

        return {
            "all_characters": merged_characters,
            "character_relationships": character_relationships,
            "role_distribution": role_distribution if isinstance(role_distribution, dict) else {},
            "current_character_count": current_confirmed_count,
            "target_count": target_count,
            "should_continue": bool(decision_payload.get("should_continue", False)),
            "continue_reason": str(decision_payload.get("reason") or "").strip(),
            "should_optimize_first": False,
            "optimization_suggestions": [],
            "cards_response_mode": cards_response_mode,
            "cards_retry_used": cards_retry_used,
            "recognized_new_character_count": len(unique_new_names),
            "recognized_new_character_names": unique_new_names,
        }

    def generate_epic_framework(self, world_setting: str, characters: str,
                               total_volumes: int, total_chapters_range: tuple[int, int]) -> Dict[str, Any]:
        chapter_lower = max(1, int(total_chapters_range[0] or 1))
        chapter_upper = max(chapter_lower, int(total_chapters_range[1] or chapter_lower))
        world_excerpt = self._story_truncate_text(world_setting, limit=4000) or "（暂无世界观补充）"
        characters_excerpt = self._story_build_character_context(
            characters,
            detail_limit=EPIC_FRAMEWORK_CHARACTER_CONTEXT_LIMIT,
        ) or "（暂无核心人物卡）"
        schema = json.dumps(
            {
                "story_positioning": {
                    "genre_type": "题材类型",
                    "global_theme": "全局主题",
                    "story_premise": "故事总纲",
                    "core_hook": "核心卖点",
                    "endgame_direction": "终局方向",
                    "core_contradiction": "核心矛盾",
                },
                "stage_roadmap": [
                    {
                        "stage": "阶段名称",
                        "volume_span": "第1-3卷",
                        "chapter_span": "1-180",
                        "phase_goal": "阶段目标",
                        "main_conflict": "阶段主冲突",
                        "growth_focus": "成长重点",
                        "ending_signal": "阶段收束标记",
                    }
                ],
                "power_progression": [
                    {
                        "volume_span": "第1-2卷",
                        "chapter_span": "1-120",
                        "realm_stage": "力量或地位成长",
                        "conflict_upgrade": "冲突升级方式",
                        "notes": "说明",
                    }
                ],
                "rolling_strategy": {
                    "planning_principle": "总纲到卷纲再到当前卷细化",
                    "detail_window": "后续只细化当前卷，并保留下一卷接口",
                    "continuity_focus": "如何保持连续性",
                    "anti_drift_rules": [
                        "每次细化前回看上一卷结尾和人物状态",
                        "严格对齐当前阶段目标与卷末交接"
                    ],
                    "character_collaboration": [
                        "主角线负责推动主冲突",
                        "盟友线负责情报/情感/支线承接"
                    ],
                },
                "volumes": [
                    {
                        "volume_index": 1,
                        "title": "卷名",
                        "chapter_span": "60-80",
                        "stage_positioning": "本卷在全书中的定位",
                        "core_goal": "本卷核心目标",
                        "main_conflict": "本卷主冲突",
                        "character_focus": "本卷重点人物协同",
                        "foreshadowing_task": "本卷伏笔任务",
                        "ending_climax": "卷末爆点",
                        "next_volume_hook": "下卷交接"
                    }
                ],
                "foreshadowings": [
                    {
                        "content": "伏笔内容",
                        "plant_at": "第1卷",
                        "pave_at": ["第2卷"],
                        "reveal_at": "第4卷",
                        "purpose": "这条伏笔承担的作用"
                    }
                ],
                "character_lifecycle": [
                    {
                        "character": "角色名",
                        "debut": "第1卷",
                        "active_span": "1-6卷",
                        "transition": "阶段变化",
                        "volume_role": "卷级职责"
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        framework_prompt = f"""你是长篇网文总策划，请先做“总纲 -> 阶段路线图 -> 分卷规划 -> 滚动细化策略”的分层规划。

【目标】
- 总卷数：{total_volumes}卷
- 总章节规模：{chapter_lower}-{chapter_upper}章
- 当前阶段只做长篇框架，不输出逐章细纲

【规划原则】
1. 必须先明确全书总纲、终局方向和核心矛盾，再拆阶段路线图。
2. 每个阶段都要说明覆盖卷段、章节规模、阶段目标、主冲突和收束标记。
3. 每卷必须是可独立成立的故事阶段，写清卷定位、核心目标、人物协同、伏笔任务、卷末爆点和下卷交接。
4. 必须给出“滚动细化策略”，说明后续如何只细化当前卷，并通过上一卷摘要、人物状态和伏笔清单控制漂移。
5. 这是长篇框架，不要输出逐章清单，不要泛泛而谈。
6. 只返回合法 JSON 对象，不要解释，不要 Markdown 代码块。
7. `volumes` 数组长度必须严格等于 {total_volumes}，且 `volume_index` 必须从 1 连续覆盖到 {total_volumes}，不得缺卷、跳卷或只给示例卷。
8. 如果篇幅紧张，请压缩每卷描述，但绝不能减少卷数。

【世界观】
{world_excerpt}

【人物体系】
{characters_excerpt}

【输出 JSON Schema】
{schema}
"""

        payload = self._story_invoke_agent_json(
            self.creative_director,
            framework_prompt,
            fallback={"volumes": []},
        )
        framework_text = self._story_render_epic_framework(payload, total_volumes)
        if not self._story_has_expected_volume_sections(framework_text, total_volumes):
            existing_indexes = self._story_list_parseable_volume_indexes(framework_text)
            existing_indexes_text = "、".join(str(index) for index in existing_indexes) if existing_indexes else "无"
            fallback_prompt = f"""你是长篇网文总策划，请按以下结构输出长篇框架：

## 一、故事总纲与终局
- 题材类型
- 全局主题
- 故事总纲
- 核心卖点
- 核心矛盾
- 终局方向

## 二、阶段路线图
- 按阶段拆分全书，每个阶段写清覆盖卷段、章节规模、阶段目标、主冲突、成长重点、收束标记

## 三、力量与冲突升级路线
- 写清各阶段的力量/地位/冲突升级路径

## 四、滚动细化策略
- 说明后续如何只细化当前卷
- 说明如何通过上一卷摘要、人物状态、伏笔任务控制漂移
- 说明主角线、盟友线、对手线如何协同

## 五、分卷规划（共{total_volumes}卷）
【第1卷】卷名
- 章节规模
- 卷定位
- 核心目标
- 主冲突
- 人物焦点
- 伏笔任务
- 卷末爆点
- 下卷交接

## 六、关键伏笔布局
- 至少列出核心跨卷伏笔

## 七、核心人物生命周期
- 说明主要人物的登场、活跃跨度、阶段变化和卷级职责

强约束：
1. 总章节规模约 {chapter_lower}-{chapter_upper} 章。
2. 卷标题必须使用“【第X卷】标题”格式。
3. 必须完整列出【第1卷】到【第{total_volumes}卷】，总数严格等于 {total_volumes} 卷，不能缺少任何一卷。
4. 如果已有草稿只覆盖了部分卷（当前仅检测到：{existing_indexes_text}），请直接补全并重写完整的 1-{total_volumes} 卷分卷规划，不要只保留前几卷。
5. 若输出长度受限，请压缩每卷描述，但不要减少卷数。"""
            framework_text = self.creative_director.process(fallback_prompt, {})
        return {
            "expanded_outline": framework_text,
            "framework_type": "epic",
            "total_volumes": total_volumes,
            "total_chapters_range": total_chapters_range,
            "estimated_chapters": (chapter_lower + chapter_upper) // 2,
        }

    @staticmethod
    def _story_should_chunk_volume_detail(chapters_count_range: Tuple[int, int]) -> bool:
        try:
            upper = max(0, int(chapters_count_range[1] or 0))
        except Exception:
            upper = 0
        return upper >= VOLUME_DETAIL_CHUNKING_THRESHOLD

    @staticmethod
    def _story_resolve_volume_detail_chunk_size(chapters_count_range: Tuple[int, int]) -> int:
        try:
            upper = max(1, int(chapters_count_range[1] or 1))
        except Exception:
            upper = 1
        return max(1, min(VOLUME_DETAIL_CHUNK_SIZE, upper))

    @staticmethod
    def _story_resolve_volume_detail_primary_target_count(
        chapters_count_range: Tuple[int, int],
    ) -> int:
        try:
            lower = max(1, int(chapters_count_range[0] or 1))
        except Exception:
            lower = 1
        try:
            upper = max(lower, int(chapters_count_range[1] or lower))
        except Exception:
            upper = lower
        return max(lower, min(upper, lower + max(0, (upper - lower) // 2)))

    @classmethod
    def _story_build_volume_detail_chunk_ranges(
        cls,
        *,
        start_chapter_num: int,
        target_chapter_count: int,
        chunk_size: int,
    ) -> List[Tuple[int, int]]:
        ranges: List[Tuple[int, int]] = []
        current_start = max(1, int(start_chapter_num or 1))
        normalized_target_count = max(1, int(target_chapter_count or 1))
        normalized_chunk_size = max(1, int(chunk_size or 1))
        target_end = current_start + normalized_target_count - 1
        while current_start <= target_end:
            current_end = min(target_end, current_start + normalized_chunk_size - 1)
            ranges.append((current_start, current_end))
            current_start = current_end + 1
        return ranges

    def _story_generate_chunked_volume_detail(
        self,
        *,
        selected_architect: Any,
        detail_prompt: str,
        target_volume_index: int,
        start_chapter_num: int,
        chapters_count_range: Tuple[int, int],
        volume_outline_excerpt: str,
        prev_volume_text: str,
        pending_foreshadowings_text: str,
        core_storyline_text: str,
        pending_foreshadowings: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        target_chapter_count = self._story_resolve_volume_detail_primary_target_count(chapters_count_range)
        target_end_chapter = max(1, int(start_chapter_num or 1)) + target_chapter_count - 1
        chunk_ranges = self._story_build_volume_detail_chunk_ranges(
            start_chapter_num=start_chapter_num,
            target_chapter_count=target_chapter_count,
            chunk_size=self._story_resolve_volume_detail_chunk_size(chapters_count_range),
        )
        if not chunk_ranges:
            return ""

        chunk_size = self._story_resolve_volume_detail_chunk_size(chapters_count_range)
        logger.info(
            "📚 单卷细化进入分块模式：第%s卷从第%s章开始，目标范围 %s-%s 章，系统规划约 %s 章（到第%s章），共 %s 轮，每轮最多 %s 章",
            target_volume_index,
            start_chapter_num,
            chapters_count_range[0],
            chapters_count_range[1],
            target_chapter_count,
            target_end_chapter,
            len(chunk_ranges),
            chunk_size,
        )
        first_start, first_end = chunk_ranges[0]
        logger.info(
            "🧩 单卷细化分块生成：第%s卷第 1/%s 轮，输出第%s章到第%s章",
            target_volume_index,
            len(chunk_ranges),
            first_start,
            first_end,
        )
        first_prompt = f"""{detail_prompt}

【分块输出要求】
1. 本卷章节规模较大，请先完成整卷规划，但本次只展开第{first_start}章到第{first_end}章。
2. 本卷总要求仍是至少 {chapters_count_range[0]} 章、最多 {chapters_count_range[1]} 章。系统当前按约 {target_chapter_count} 章（到第{target_end_chapter}章）规划分块，但只要整体落在区间内且结构完整即可，不要机械凑满上限。
3. `story_overview`、`volume_positioning`、`chapter_groups`、`foreshadowing_checks`、`volume_connection_check` 仍需面向整卷填写。
4. `chapters` 里只能保留第{first_start}章到第{first_end}章，章节号必须连续，不得越界。
5. 不要提前输出第{first_end + 1}章及之后的章节正文块，后续章节将分段继续补写。
6. 如果输出任何小于第{first_start}章或大于第{first_end}章的 `chapter_number`，该批输出视为无效。
"""
        first_response = selected_architect.process(first_prompt, {})
        first_payload = self._story_extract_json(first_response)
        if isinstance(first_payload, dict) and first_payload:
            volume_content, _ = self._story_render_volume_detail(
                first_payload,
                target_volume_index=target_volume_index,
                start_chapter_num=start_chapter_num,
                chapters_count_range=chapters_count_range,
                pending_foreshadowings=pending_foreshadowings,
            )
        else:
            volume_content = self._story_normalize_volume_detail_response(
                first_response,
                target_volume_index=target_volume_index,
                start_chapter_num=start_chapter_num,
                chapters_count_range=chapters_count_range,
                pending_foreshadowings=pending_foreshadowings,
            )

        for chunk_index, (chunk_start, chunk_end) in enumerate(chunk_ranges[1:], start=2):
            logger.info(
                "🧩 单卷细化分块生成：第%s卷第 %s/%s 轮，补写第%s章到第%s章",
                target_volume_index,
                chunk_index,
                len(chunk_ranges),
                chunk_start,
                chunk_end,
            )
            main_section_excerpt = self._story_truncate_text(
                self._story_extract_volume_detail_main_section(volume_content),
                limit=6500,
            ) or "（当前已生成章节摘录为空，请严格承接已规划卷结构继续补写。）"
            chunk_prompt = f"""你正在分块补写第{target_volume_index}卷细纲。本卷总要求仍为从第{start_chapter_num}章开始、至少 {chapters_count_range[0]} 章、最多 {chapters_count_range[1]} 章；系统当前按约 {target_chapter_count} 章（到第{target_end_chapter}章）规划分块，但最终只要落在区间内且结构完整即可。

本次只补写第{chunk_start}章到第{chunk_end}章：
- 只输出这一段章节区块
- 严禁重写第{chunk_start}章之前的任何章节
- 严禁输出第{chunk_end}章之后的任何章节
- 如果输出的 `chapter_number` 小于 {chunk_start} 或大于 {chunk_end}，该输出视为无效
- 不要重复已写章节
- 不要输出“故事概述 / 伏笔埋设检查 / 卷尾衔接检查 / 解释 / 代码块”
- 每章必须包含：场景目标、冲突设计、关键事件、涉及人物、人物推进、情节作用、结尾钩子；可选补充爽点类型、伏笔事项
- 第{chunk_start}章必须紧接前文推进，不得重新从第{start_chapter_num}章起叙述
- 第{chunk_end}章需要为下一段保留承接空间

【全书核心主线】
{core_storyline_text}

【当前卷框架摘要】
{volume_outline_excerpt}

【上一卷承接信息】
{prev_volume_text}

【本卷待处理伏笔】
{pending_foreshadowings_text}

【当前已生成正文规划区摘录】
{main_section_excerpt}
"""
            supplemented_content = self._story_merge_volume_detail_supplement(
                volume_content,
                selected_architect.process(chunk_prompt, {}),
                next_chapter_number=chunk_start,
                max_chapter_number=chunk_end,
            )
            if supplemented_content != volume_content:
                volume_content = supplemented_content

        return volume_content

    def expand_volume_detail(self, framework_content: str, target_volume_index: int,
                            world_setting: str, characters: str,
                            start_chapter_num: int,
                            chapters_count_range: tuple[int, int],
                            prev_volume_summary: Optional[Dict[str, Any]] = None,
                            pending_foreshadowings: Optional[List[Dict[str, Any]]] = None,
                            core_storyline: Optional[str] = None,
                            framework_header: Optional[str] = None,
                            framework_footer: Optional[str] = None) -> Dict[str, Any]:
        selected_model = self.estimate_volume_detail_model(chapters_count_range)
        selected_architect = self.plot_architect_plus if selected_model == "qwen3.7-plus" else self.plot_architect_r1
        target_volume_block = self._story_extract_volume_block(framework_content, target_volume_index)
        header_excerpt = self._story_truncate_text(framework_header, limit=1800) if framework_header else ""
        footer_excerpt = self._story_truncate_text(framework_footer, limit=1800) if framework_footer else ""
        world_excerpt = self._story_truncate_text(world_setting, limit=2500) or "（暂无额外世界观补充）"
        characters_excerpt = self._story_build_character_context(
            characters,
            detail_limit=VOLUME_DETAIL_CHARACTER_CONTEXT_LIMIT,
        ) or "（暂无核心人物信息）"
        core_storyline_text = self._story_truncate_text(
            core_storyline or self._extract_core_storyline_from_framework(framework_content),
            limit=1200,
        ) or "（请从当前卷框架中自行提炼核心主线，不得偏离全书目标。）"
        prev_volume_text = self._story_format_prev_volume_summary(prev_volume_summary)
        pending_foreshadowings_text = self._story_format_pending_foreshadowings(pending_foreshadowings)
        volume_outline_excerpt = self._story_truncate_text(
            target_volume_block or framework_content,
            limit=2000,
        ) or "（未能抽取到目标卷摘要，请结合全书框架自行聚焦当前卷。）"
        schema = json.dumps(
            {
                "story_overview": "本卷的起承转合摘要",
                "volume_positioning": {
                    "volume_title": "卷名",
                    "phase_role": "本卷在全书中的定位",
                    "stage_goal": "本卷阶段目标",
                    "inheritance_from_prev": "如何承接上一卷",
                    "main_conflict": "本卷主冲突",
                    "character_coordination": "主角/盟友/对手如何协同",
                    "ending_handoff": "如何交给下一卷"
                },
                "chapter_groups": [
                    {
                        "arc": "剧情段名称",
                        "chapter_span": f"{start_chapter_num}-{start_chapter_num + 4}",
                        "stage_task": "这一段完成什么任务",
                        "conflict_upgrade": "冲突如何升级",
                        "character_focus": "本段人物焦点",
                        "foreshadowing_task": "本段伏笔任务"
                    }
                ],
                "chapters": [
                    {
                        "chapter_number": start_chapter_num,
                        "title": "章节标题",
                        "scene_goal": "本章核心目标",
                        "conflict_design": "本章冲突推进",
                        "key_events": "关键事件",
                        "highlight_type": "爽点类型",
                        "character_progress": "人物推进",
                        "plot_function": "情节作用",
                        "ending_hook": "结尾钩子",
                        "foreshadowing_item": "伏笔事项",
                        "involved_characters": ["角色A", "角色B"]
                    }
                ],
                "foreshadowing_checks": [
                    {
                        "chapter": f"第{start_chapter_num}章",
                        "action": "埋设/铺垫/回收",
                        "content": "对应伏笔内容"
                    }
                ],
                "volume_connection_check": {
                    "core_task_completion": "本卷完成了什么",
                    "next_volume_opening": "下卷开局场景",
                    "ending_hook": "卷尾钩子"
                }
            },
            ensure_ascii=False,
            indent=2,
        )
        detail_prompt = f"""你是长篇网文章节策划，请将第{target_volume_index}卷细化为可执行的卷级细纲。

【任务范围】
- 目标卷：第{target_volume_index}卷
- 章节编号：从第{start_chapter_num}章开始
- 章节数量：至少{chapters_count_range[0]}章，最多{chapters_count_range[1]}章
- 章节规划原则：系统需在该范围内自主判断合适章数，既不要机械压到最小值，也不要默认凑满到上限
- 当前目标：讲清一个完整故事阶段，并和上一卷、下一卷无缝衔接

【硬性要求】
1. 只返回合法 JSON 对象，不要解释，不要 Markdown 代码块。
2. `chapters` 中的 chapter_number 必须连续，从第{start_chapter_num}章开始。
3. 本卷必须明确起点承接、中段升级、卷末爆点、下卷开口，不能只列散点事件。
4. `chapter_groups` 要覆盖本卷主要剧情段，通常拆成3-5段，每段都要标明任务、冲突升级、人物焦点和伏笔任务。
5. 人物协同必须具体：主角负责推进主冲突，盟友/配角承担信息、关系、资源或情绪维度，对手线要形成压迫或反制。
6. 每章必须写清：关键事件、人物推进、情节作用，避免只有情绪描述没有结构职责。
7. 若新增人物，必须让其承担清晰剧情职责，不能为“凑人物卡”而出现。
8. 必须严格服从全书主线、当前卷摘要、上一卷承接与伏笔任务，避免长篇漂移。
9. 章节总数只要落在范围内即可，不要为了对齐某个边界值而生硬拉长或压缩剧情。

【全书核心主线】
{core_storyline_text}

【全局框架头部约束】
{header_excerpt or '（暂无额外头部约束）'}

【当前卷框架摘要】
{volume_outline_excerpt}

【全局伏笔与人物生命周期】
{footer_excerpt or '（暂无额外尾部约束）'}

【上一卷承接信息】
{prev_volume_text}

【本卷待处理伏笔】
{pending_foreshadowings_text}

【世界观补充】
{world_excerpt}

【当前人物体系】
{characters_excerpt}

【输出 JSON Schema】
{schema}
"""

        volume_content = ""
        chapter_count = 0
        if self._story_should_chunk_volume_detail(chapters_count_range):
            volume_content = self._story_generate_chunked_volume_detail(
                selected_architect=selected_architect,
                detail_prompt=detail_prompt,
                target_volume_index=target_volume_index,
                start_chapter_num=start_chapter_num,
                chapters_count_range=chapters_count_range,
                volume_outline_excerpt=volume_outline_excerpt,
                prev_volume_text=prev_volume_text,
                pending_foreshadowings_text=pending_foreshadowings_text,
                core_storyline_text=core_storyline_text,
                pending_foreshadowings=pending_foreshadowings,
            )
            chapter_count = self._story_count_rendered_volume_detail_chapters(volume_content)
        else:
            initial_response = selected_architect.process(detail_prompt, {})
            initial_payload = self._story_extract_json(initial_response)
            if isinstance(initial_payload, dict) and initial_payload:
                volume_content, chapter_count = self._story_render_volume_detail(
                    initial_payload,
                    target_volume_index=target_volume_index,
                    start_chapter_num=start_chapter_num,
                    chapters_count_range=chapters_count_range,
                    pending_foreshadowings=pending_foreshadowings,
                )
            else:
                volume_content = self._story_normalize_volume_detail_response(
                    initial_response,
                    target_volume_index=target_volume_index,
                    start_chapter_num=start_chapter_num,
                    chapters_count_range=chapters_count_range,
                    pending_foreshadowings=pending_foreshadowings,
                )
                chapter_count = self._story_count_rendered_volume_detail_chapters(volume_content)
        fallback_prompt = f"""请详细扩展第{target_volume_index}卷，并严格按以下结构输出 Markdown：

## 一、故事概述
- 写清本卷承接、阶段目标、主冲突、角色协同和卷末交接

## 二、第{target_volume_index}卷详细规划（预计{chapters_count_range[0]}-{chapters_count_range[1]}章，从第{start_chapter_num}章开始）
- 可先写本卷剧情段落设计
- 然后从第{start_chapter_num}章起逐章输出，由系统在 {chapters_count_range[0]}-{chapters_count_range[1]} 章之间自主判断合适总量；只要结构完整即可，不必机械贴边到最小值或最大值
- 每章必须包含：场景目标、冲突设计、关键事件、涉及人物、人物推进、情节作用、结尾钩子；可选补充爽点类型、伏笔事项

## 三、伏笔埋设检查
- 明确本卷埋设/铺垫/回收了哪些伏笔

## 四、卷尾衔接检查
- 明确本卷任务完成情况、下卷开局场景、卷尾钩子

必须严格服从以下约束：
【全书核心主线】
{core_storyline_text}

【当前卷框架摘要】
{volume_outline_excerpt}

【上一卷承接信息】
{prev_volume_text}

【本卷待处理伏笔】
{pending_foreshadowings_text}
"""
        if not volume_content or not self._story_is_valid_volume_detail_chapter_count(chapter_count, chapters_count_range):
            retry_reason = ""
            if chapter_count > 0:
                retry_reason = (
                    f"\n\n补充纠偏：你上一版只输出了 {chapter_count} 章，"
                    f"未满足至少 {chapters_count_range[0]} 章、至多 {chapters_count_range[1]} 章的要求。"
                    "请整卷重写，不要只补摘要。"
                )
            volume_content = self._story_normalize_volume_detail_response(
                selected_architect.process(fallback_prompt + retry_reason, {}),
                target_volume_index=target_volume_index,
                start_chapter_num=start_chapter_num,
                chapters_count_range=chapters_count_range,
                pending_foreshadowings=pending_foreshadowings,
            )

        renumberer = _resolve_chapter_renumberer()
        renumber_result = renumberer.detect_and_fix(
            content=volume_content,
            expected_start=start_chapter_num,
            expected_count_range=chapters_count_range,
        )
        volume_content = renumber_result["fixed_content"]

        actual_chapter_count = self._story_count_rendered_volume_detail_chapters(volume_content)
        range_shortcuts = self._story_find_volume_detail_range_shortcuts(
            volume_content,
            start_chapter_num=start_chapter_num,
            chapters_count_range=chapters_count_range,
        )
        supplement_architect = self.plot_architect_r1 if selected_model == "qwen3.7-plus" else selected_architect
        if (
            not self._story_is_valid_volume_detail_chapter_count(actual_chapter_count, chapters_count_range)
            or range_shortcuts
        ):
            repair_reasons: List[str] = []
            if not self._story_is_valid_volume_detail_chapter_count(actual_chapter_count, chapters_count_range):
                repair_reasons.append(
                    f"上一版仍只识别到 {actual_chapter_count} 章，目标范围是 {chapters_count_range[0]}-{chapters_count_range[1]} 章。"
                )
            if range_shortcuts:
                shortcut_text = "、".join(f"第{start}-{end}章" for start, end in range_shortcuts)
                repair_reasons.append(
                    f"检测到你使用 {shortcut_text} 这类范围摘要代替逐章细纲。"
                    "禁止使用“第A-B章 / A-B章 / 第A至B章”这种写法概括多章，"
                    "目标范围内的每一章都必须单独写出章节标题与全部字段。"
                )
            repair_prompt = (
                fallback_prompt
                + "\n\n强制纠偏："
                + "".join(repair_reasons)
                + "请完整重写，并逐章输出，不得省略，不得用范围摘要代替缺失章节。"
            )
            volume_content = self._story_normalize_volume_detail_response(
                selected_architect.process(repair_prompt, {}),
                target_volume_index=target_volume_index,
                start_chapter_num=start_chapter_num,
                chapters_count_range=chapters_count_range,
                pending_foreshadowings=pending_foreshadowings,
            )
            renumber_result = renumberer.detect_and_fix(
                content=volume_content,
                expected_start=start_chapter_num,
                expected_count_range=chapters_count_range,
            )
            volume_content = renumber_result["fixed_content"]
            actual_chapter_count = self._story_count_rendered_volume_detail_chapters(volume_content)
            range_shortcuts = self._story_find_volume_detail_range_shortcuts(
                volume_content,
                start_chapter_num=start_chapter_num,
                chapters_count_range=chapters_count_range,
            )

        if range_shortcuts:
            missing_ranges = self._story_extract_missing_volume_detail_chapter_ranges(
                volume_content,
                start_chapter_num=start_chapter_num,
                chapters_count_range=chapters_count_range,
            )
            chunked_missing_ranges = self._story_chunk_volume_detail_chapter_ranges(
                missing_ranges,
                chunk_size=15,
            )
            for missing_start, missing_end in chunked_missing_ranges:
                main_section_excerpt = self._story_truncate_text(
                    self._story_extract_volume_detail_main_section(volume_content),
                    limit=6000,
                ) or "（当前正文规划区提取失败，请严格按框架补齐缺失章节。）"
                missing_prompt = f"""你上一版第{target_volume_index}卷细纲在第{missing_start}-{missing_end}章仍未逐章展开，当前文本存在范围摘要或缺失章节。

请不要重写整卷，只补写这段缺失章节：
- 只输出第{missing_start}章到第{missing_end}章的章节区块
- 不要重复已经写出的章节
- 不要输出“故事概述 / 伏笔埋设检查 / 卷尾衔接检查 / 解释 / 代码块”
- 禁止使用“第A-B章 / A-B章 / 第A至B章 / 章节：A-B”这类范围摘要代替任何单章
- 每一章都必须单独写出：场景目标、冲突设计、关键事件、涉及人物、人物推进、情节作用、结尾钩子；可选补充爽点类型、伏笔事项

【当前卷框架摘要】
{volume_outline_excerpt}

【上一卷承接信息】
{prev_volume_text}

【当前已生成正文规划区摘录】
{main_section_excerpt}
"""
                supplemented_content = self._story_merge_volume_detail_supplement(
                    volume_content,
                    supplement_architect.process(missing_prompt, {}),
                    next_chapter_number=missing_start,
                    max_chapter_number=missing_end,
                )
                if supplemented_content == volume_content:
                    continue
                volume_content = supplemented_content
                renumber_result = renumberer.detect_and_fix(
                    content=volume_content,
                    expected_start=start_chapter_num,
                    expected_count_range=chapters_count_range,
                )
                volume_content = renumber_result["fixed_content"]
                actual_chapter_count = self._story_count_rendered_volume_detail_chapters(volume_content)
                range_shortcuts = self._story_find_volume_detail_range_shortcuts(
                    volume_content,
                    start_chapter_num=start_chapter_num,
                    chapters_count_range=chapters_count_range,
                )
                if not range_shortcuts:
                    break

        if 0 < actual_chapter_count < chapters_count_range[0]:
            rendered_chapter_range = self._story_extract_rendered_volume_detail_chapter_range(volume_content)
            last_chapter_num = (
                rendered_chapter_range[1]
                if rendered_chapter_range[1] > 0
                else start_chapter_num + actual_chapter_count - 1
            )
            next_chapter_num = max(start_chapter_num, last_chapter_num + 1)
            required_last_chapter = start_chapter_num + chapters_count_range[0] - 1
            allowed_last_chapter = start_chapter_num + chapters_count_range[1] - 1
            chapter_body = re.split(r"(?m)^##\s*(?:三|3)[、.．].*$", volume_content, maxsplit=1)[0].rstrip()
            continuation_context = chapter_body[-6000:] if len(chapter_body) > 6000 else chapter_body
            supplement_prompt = f"""你上一版第{target_volume_index}卷细纲已经写出了前面的 {actual_chapter_count} 章，但还没有达到最低章节数要求。

请不要重写已有内容，只补写缺失的后续章节：
- 从第{next_chapter_num}章开始连续输出
- 至少补到第{required_last_chapter}章
- 最多补到第{allowed_last_chapter}章
- 只返回新增章节区块，不要重复已有章节
- 不要输出“故事概述 / 伏笔埋设检查 / 卷尾衔接检查 / 解释 / 代码块”
- 每章仍需包含：场景目标、冲突设计、关键事件、涉及人物、人物推进、情节作用、结尾钩子；可选补充爽点类型、伏笔事项

【当前卷框架摘要】
{volume_outline_excerpt}

【上一卷承接信息】
{prev_volume_text}

【已生成内容末段】
{continuation_context}
"""
            supplemented_content = self._story_merge_volume_detail_supplement(
                volume_content,
                supplement_architect.process(supplement_prompt, {}),
                next_chapter_number=next_chapter_num,
            )
            if supplemented_content != volume_content:
                volume_content = supplemented_content
                renumber_result = renumberer.detect_and_fix(
                    content=volume_content,
                    expected_start=start_chapter_num,
                    expected_count_range=chapters_count_range,
                )
                volume_content = renumber_result["fixed_content"]
                actual_chapter_count = self._story_count_rendered_volume_detail_chapters(volume_content)
                range_shortcuts = self._story_find_volume_detail_range_shortcuts(
                    volume_content,
                    start_chapter_num=start_chapter_num,
                    chapters_count_range=chapters_count_range,
                )

        if 0 < actual_chapter_count < chapters_count_range[0]:
            minimum_missing_ranges = self._story_extract_missing_volume_detail_chapter_ranges(
                volume_content,
                start_chapter_num=start_chapter_num,
                chapters_count_range=(chapters_count_range[0], chapters_count_range[0]),
            )
            chunked_minimum_missing_ranges = self._story_chunk_volume_detail_chapter_ranges(
                minimum_missing_ranges,
                chunk_size=15,
            )
            for missing_start, missing_end in chunked_minimum_missing_ranges:
                if actual_chapter_count >= chapters_count_range[0]:
                    break
                rendered_chapters_now = set(self._story_extract_rendered_volume_detail_chapter_numbers(volume_content))
                if all(
                    chapter_number in rendered_chapters_now
                    for chapter_number in range(missing_start, missing_end + 1)
                ):
                    continue
                main_section_excerpt = self._story_truncate_text(
                    self._story_extract_volume_detail_main_section(volume_content),
                    limit=6000,
                ) or "（当前正文规划区提取失败，请严格按框架补齐最低章节数要求所需的缺失章节。）"
                minimum_prompt = f"""你上一版第{target_volume_index}卷细纲还没有达到最低章节数要求，第{missing_start}-{missing_end}章仍缺失。

请不要重写整卷，只补写这段缺失章节：
- 只输出第{missing_start}章到第{missing_end}章的章节区块
- 不要重复已经写出的章节
- 不要输出“故事概述 / 伏笔埋设检查 / 卷尾衔接检查 / 解释 / 代码块”
- 这是为了补齐本卷至少 {chapters_count_range[0]} 章的最低要求，章号必须和前文连续衔接
- 每一章都必须单独写出：场景目标、冲突设计、关键事件、涉及人物、人物推进、情节作用、结尾钩子；可选补充爽点类型、伏笔事项

【当前卷框架摘要】
{volume_outline_excerpt}

【上一卷承接信息】
{prev_volume_text}

【当前已生成正文规划区摘录】
{main_section_excerpt}
"""
                supplemented_content = self._story_merge_volume_detail_supplement(
                    volume_content,
                    supplement_architect.process(minimum_prompt, {}),
                    next_chapter_number=missing_start,
                    max_chapter_number=missing_end,
                )
                if supplemented_content == volume_content:
                    continue
                volume_content = supplemented_content
                renumber_result = renumberer.detect_and_fix(
                    content=volume_content,
                    expected_start=start_chapter_num,
                    expected_count_range=chapters_count_range,
                )
                volume_content = renumber_result["fixed_content"]
                actual_chapter_count = self._story_count_rendered_volume_detail_chapters(volume_content)
                range_shortcuts = self._story_find_volume_detail_range_shortcuts(
                    volume_content,
                    start_chapter_num=start_chapter_num,
                    chapters_count_range=chapters_count_range,
                )

        if range_shortcuts:
            shortcut_text = "、".join(f"第{start}-{end}章" for start, end in range_shortcuts)
            raise ValueError(
                f"单卷细化未逐章展开：第{target_volume_index}卷仍存在范围摘要 {shortcut_text}，"
                "目标章节必须逐章完整输出。"
            )

        if not self._story_is_valid_volume_detail_chapter_count(actual_chapter_count, chapters_count_range):
            raise ValueError(
                f"单卷细化生成章节数不足：第{target_volume_index}卷最终仅识别到 {actual_chapter_count} 章，"
                f"目标范围为 {chapters_count_range[0]}-{chapters_count_range[1]} 章。"
            )

        volume_content = _render_normalized_outline_as_markdown(
            normalize_outline_text(volume_content, characters or "")
        )
        volume_content = self._story_ensure_volume_detail_tail_sections(
            volume_content,
            pending_foreshadowings=pending_foreshadowings,
        )
        actual_chapter_count = self._story_count_rendered_volume_detail_chapters(volume_content)

        validator = _resolve_consistency_validator(strict_mode=True)
        validation_result = validator.validate(
            volume_content=volume_content,
            volume_index=target_volume_index,
            core_storyline=core_storyline or "",
            prev_volume_summary=prev_volume_summary,
            pending_foreshadowings=pending_foreshadowings,
            framework_content=framework_content,
        )
        validation_dict = validation_result.to_dict()
        rendered_chapter_range = self._story_extract_rendered_volume_detail_chapter_range(volume_content)
        chapters_start = rendered_chapter_range[0] if rendered_chapter_range[0] > 0 else start_chapter_num
        chapters_end = (
            rendered_chapter_range[1]
            if rendered_chapter_range[1] > 0
            else start_chapter_num + max(actual_chapter_count, 1) - 1
        )
        actual_count = actual_chapter_count

        return {
            "expanded_outline": volume_content,
            "volume_index": target_volume_index,
            "chapter_count": actual_count,
            "current_chapter_count": actual_count,
            "chapters_start": chapters_start,
            "chapters_end": chapters_end,
            "renumber_result": renumber_result,
            "validation": validation_dict,
            "validation_passed": validation_result.passed,
            "validation_issues": validation_dict.get('issues', []),
            "validation_suggestions": validation_dict.get('suggestions', []),
        }


