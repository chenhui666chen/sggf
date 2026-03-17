from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from core.langchain_bridge import create_task_llm


CHAPTER_HEADING_PATTERN = re.compile(
    r"(?m)^(?P<prefix>#{1,6}\s*)?第\s*(?P<number>\d+)\s*章(?:[：:、\-\s]*(?P<title>[^\n]*))?$"
)
CHARACTER_NAME_PATTERN = re.compile(
    r"(?m)^(?:###\s*)?(?:\*\*)?【姓名】(?:：|:)\s*(?P<name>.+?)\s*(?:\*\*)?\s*$"
)


@dataclass
class OutlineBlock:
    original_number: int
    title: str
    body: str
    locked: bool = True
    source: str = "existing"
    anchor_after: Optional[int] = None


def normalize_character_name(name: str) -> str:
    if not name:
        return ""
    value = str(name).strip()
    value = re.sub(r"\*+", "", value)
    value = re.sub(r"[（(].*?[)）]$", "", value).strip()
    value = re.sub(r"\s+", "", value)
    value = value.replace("：", "").replace(":", "")
    return value


def parse_outline_blocks(text: str) -> Tuple[str, List[OutlineBlock]]:
    if not text or not text.strip():
        return "", []

    matches = list(CHAPTER_HEADING_PATTERN.finditer(text))
    if not matches:
        return text.strip(), []

    prefix = text[: matches[0].start()].rstrip()
    blocks: List[OutlineBlock] = []

    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[body_start:body_end].lstrip("\r\n").rstrip()
        title = (match.group("title") or "").strip()
        blocks.append(
            OutlineBlock(
                original_number=int(match.group("number")),
                title=title,
                body=body,
            )
        )

    return prefix, blocks


def render_outline(prefix: str, blocks: List[OutlineBlock]) -> str:
    parts: List[str] = []
    if prefix and prefix.strip():
        parts.append(prefix.strip())

    for index, block in enumerate(blocks, start=1):
        heading = f"第{index}章"
        if block.title:
            heading = f"{heading}：{block.title}"
        parts.append(f"{heading}\n{block.body}".rstrip())

    return "\n\n".join(part for part in parts if part and part.strip())


def extract_character_names(text: str) -> List[str]:
    if not text or not text.strip():
        return []

    names: List[str] = []
    seen = set()
    for match in CHARACTER_NAME_PATTERN.finditer(text):
        normalized = normalize_character_name(match.group("name"))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        names.append(normalized)
    return names


def build_delta_section_title(base_title: str, existing_text: str) -> str:
    existing_rounds = re.findall(rf"(?m)^##\s*{re.escape(base_title)}", existing_text or "")
    return f"{base_title}（第{len(existing_rounds) + 1}轮）"


def merge_character_delta(
    existing_characters: str,
    new_character_cards: str,
    relationship_patch: str,
) -> str:
    parts: List[str] = []
    if existing_characters and existing_characters.strip():
        parts.append(existing_characters.rstrip())

    if new_character_cards and new_character_cards.strip():
        role_title = build_delta_section_title("协同新增角色", existing_characters)
        parts.append(f"## {role_title}\n\n{new_character_cards.strip()}")

    if relationship_patch and relationship_patch.strip():
        relation_title = build_delta_section_title("协同新增关系", existing_characters)
        parts.append(f"## {relation_title}\n\n{relationship_patch.strip()}")

    return "\n\n".join(part for part in parts if part and part.strip())


def build_outline_delta_section(existing_outline: str, generated_chapters: str) -> str:
    if not generated_chapters or not generated_chapters.strip():
        return existing_outline.strip()

    section_title = build_delta_section_title("协同新增章节规划", existing_outline)
    if existing_outline and existing_outline.strip():
        return f"{existing_outline.rstrip()}\n\n## {section_title}\n\n{generated_chapters.strip()}"
    return generated_chapters.strip()


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def evaluate_story_coordination(
    outline_text: str,
    characters_text: str,
) -> Dict[str, Any]:
    _, outline_blocks = parse_outline_blocks(outline_text or "")
    character_names = extract_character_names(characters_text or "")

    outline_reference_text = outline_text or ""
    referenced_characters = [name for name in character_names if name and name in outline_reference_text]
    unreferenced_characters = [name for name in character_names if name not in referenced_characters]

    chapter_count = len(outline_blocks)
    character_count = len(character_names)
    coverage_ratio = (len(referenced_characters) / character_count) if character_count else 0.0
    chapters_per_character = (chapter_count / character_count) if character_count else 0.0

    score = 35
    score += int(min(35, coverage_ratio * 35))
    score += int(min(15, chapter_count))
    score += int(min(15, chapters_per_character * 3))
    score = max(0, min(100, score))

    suggestions: List[str] = []
    if chapter_count == 0:
        suggestions.append("当前大纲缺少可定位章节，建议先生成章节卡，再做中段插入式拓展。")
    if unreferenced_characters:
        suggestions.append("存在未被大纲引用的人物，优先为这些角色补充登场章节或职责。")
    if character_count and coverage_ratio < 0.6:
        suggestions.append("人物与章节覆盖率偏低，新增章节时需要明确写出涉及人物与关系推进。")
    if chapter_count and not character_count:
        suggestions.append("大纲已具备章节结构，但人物档案不足，建议先补足关键功能角色。")
    if not suggestions:
        suggestions.append("当前人物与大纲的基础协同正常，适合继续做增量扩展。")

    return {
        "score": score,
        "chapter_count": chapter_count,
        "character_count": character_count,
        "coverage_ratio": round(coverage_ratio, 3),
        "referenced_characters": referenced_characters,
        "unreferenced_characters": unreferenced_characters,
        "suggestions": suggestions,
    }


class StoryExpansionCoordinator:
    def __init__(self) -> None:
        self.planner_llm = create_task_llm(task_type="outline_expand", temperature=0.2)
        self.writer_llm = create_task_llm(task_type="outline_expand", temperature=0.45)

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
      "role_type": "导师/对手/盟友/信息角色/世界观角色",
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
                "new_character_cards": "",
                "relationship_patch": "",
                "new_character_names": [],
            }

        existing_names = extract_character_names(existing_characters)
        op_summary_lines = []
        for index, op in enumerate(plan.get("character_ops") or [], start=1):
            role_type = op.get("role_type") or "功能角色"
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

        prompt = f"""
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
【角色定位】：...
【外貌特征】：...
【性格特点】：...
【背景故事】：...
【世界观/价值观立场】：...
【核心动机】：...
【能力/特长】：...
【弱点/缺陷】：...
【在情节中的作用】：...
【人物成长线】：...
【关键关系】：...
【关联线索】：...
---

最后另起一节，输出：
## 关系补丁
- 角色A ↔ 角色B：关系类型（简述）
"""

        raw_text = self._invoke_text(prompt)
        split_pattern = re.split(r"(?m)^##\s*关系补丁\s*$", raw_text, maxsplit=1)
        if len(split_pattern) == 2:
            cards_text, relationships_text = split_pattern[0].strip(), split_pattern[1].strip()
        else:
            cards_text, relationships_text = raw_text.strip(), ""

        new_character_names = extract_character_names(cards_text)
        return {
            "new_character_cards": cards_text,
            "relationship_patch": relationships_text,
            "new_character_names": new_character_names,
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

        prompt = f"""
你是小说章节拓展策划师。请只生成 {count} 个新增章节，不允许改写旧章节。

【插入位置】
{placement}

【当前锚点章节】
{f"第{after_chapter}章：{anchor_block.title}\\n{anchor_block.body[:800]}" if anchor_block else "无明确锚点"}

【后继锁定章节】
{f"第{next_block.original_number}章：{next_block.title}\\n{next_block.body[:800]}" if next_block else "无，表示可在结尾延展"}

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
- 主要内容：...
- 关键事件：...
- 涉及人物：角色A、角色B
- 人物推进：...
- 情节作用：...

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
                "outline_delta_text": "",
                "outline_ops_executed": [],
                "current_chapter_count": len(blocks),
            }

        if not blocks:
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
- 主要内容：...
- 关键事件：...
- 涉及人物：...
- 人物推进：...
- 情节作用：...
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
                "outline_delta_text": raw_text.strip(),
                "outline_ops_executed": outline_ops_executed,
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
            "outline_delta_text": "\n\n".join(part for part in outline_delta_parts if part.strip()),
            "outline_ops_executed": outline_ops_executed,
            "current_chapter_count": len(mutable_blocks),
        }

    def execute(
        self,
        current_outline: str,
        characters: str,
        world_setting: str,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        strategy: str = "auto",
    ) -> Dict[str, Any]:
        validation_before = evaluate_story_coordination(current_outline or "", characters or "")
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

        if chapters_needed > 30:
            raise ValueError("协同拓展一次最多新增 30 章，请分轮执行。")
        if characters_needed > 10:
            raise ValueError("协同拓展一次最多新增 10 个角色，请分轮执行。")
        if chapters_needed <= 0 and characters_needed <= 0:
            raise ValueError("目标章节数和目标人物数均不高于当前内容，无需协同拓展。")

        character_delta = self.generate_character_delta(
            existing_characters=characters,
            current_outline=current_outline,
            world_setting=world_setting,
            plan=plan,
        )

        merged_characters = merge_character_delta(
            existing_characters=characters or "",
            new_character_cards=character_delta["new_character_cards"],
            relationship_patch=character_delta["relationship_patch"],
        )

        outline_delta = self.generate_outline_delta(
            current_outline=current_outline,
            characters_text=merged_characters,
            world_setting=world_setting,
            plan=plan,
            new_character_cards=character_delta["new_character_cards"],
        )

        validation_after = evaluate_story_coordination(
            outline_delta["plot_outline"],
            merged_characters,
        )

        current_character_count = len(extract_character_names(merged_characters))

        return {
            "strategy": plan["strategy"],
            "summary": plan["summary"],
            "plan": plan,
            "plot_outline": outline_delta["plot_outline"],
            "characters": merged_characters,
            "outline_delta_text": outline_delta["outline_delta_text"],
            "character_delta_text": character_delta["new_character_cards"],
            "relationship_patch": character_delta["relationship_patch"],
            "outline_ops_executed": outline_delta["outline_ops_executed"],
            "new_character_names": character_delta["new_character_names"],
            "current_chapter_count": outline_delta["current_chapter_count"],
            "current_character_count": current_character_count,
            "validation_before": validation_before,
            "validation_after": validation_after,
        }
