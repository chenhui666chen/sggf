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
        "validation_stage": "chapter_level",
    }


class StoryExpansionCoordinator:
    SHORT_CHAPTER_DELTA_LIMIT = 30
    SHORT_CHARACTER_DELTA_LIMIT = 10
    ITERATIVE_CHAPTER_STEP = 10
    ITERATIVE_CHARACTER_STEP = 5
    ITERATIVE_MAX_ROUNDS = 40
    LARGE_PROJECT_CHAPTER_THRESHOLD = 100
    SUPER_LARGE_PROJECT_CHAPTER_THRESHOLD = 200
    FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD = 120
    EPIC_CHAPTER_THRESHOLD = 800
    EPIC_DEFAULT_CHAPTERS_PER_VOLUME = 40
    EPIC_MIN_VOLUMES = 10
    EPIC_MAX_VOLUMES = 50

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
            # 超大规模项目（>200章）：使用 qwen-long（超长上下文）
            model_type = "outline_expand"  # qwen-long
            print(f"🔄 检测到超大规模项目（{self.planned_chapters_max}章），使用 qwen-long 模型")
        elif self.planned_chapters_max > self.LARGE_PROJECT_CHAPTER_THRESHOLD:
            # 大规模项目（100-200章）：使用 deepseek-reasoner（推理能力强）
            model_type = "volume_detail_expand"  # deepseek-reasoner
            print(f"✅ 检测到大规模项目（{self.planned_chapters_max}章），使用 deepseek-reasoner 模型")
        else:
            # 常规项目（≤100章）：使用 qwen-long（默认）
            model_type = "outline_expand"  # qwen-long
            print(f"✅ 常规项目（{self.planned_chapters_max}章），使用 qwen-long 模型")

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
    def _intent_to_strategy(intent: str) -> str:
        mapping = {
            "outline_led": "plot_first",
            "character_led": "character_first",
            "balanced": "balanced",
        }
        return mapping.get(str(intent or "").strip(), "balanced")

    @staticmethod
    def _estimate_outline_model(target_chapter_count: int) -> str:
        if target_chapter_count >= 40:
            return "qwen-long"
        return "qwen3-max"

    @staticmethod
    def _estimate_character_model(target_character_count: int) -> str:
        if target_character_count < 20:
            return "deepseek-reasoner"
        if target_character_count < 60:
            return "qwen3-max"
        return "qwen-long"

    @classmethod
    def _build_total_mode_suitability(
        cls,
        *,
        current_chapter_count: int,
        target_chapter_count: int,
        chapters_needed: int,
        execution_mode: str,
    ) -> Dict[str, Any]:
        recommended_upper = cls.LARGE_PROJECT_CHAPTER_THRESHOLD
        caution_upper = cls.FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD - 1
        effective_total = max(current_chapter_count, target_chapter_count)

        if target_chapter_count >= cls.EPIC_CHAPTER_THRESHOLD:
            request_band = "epic"
            request_band_label = "自动切长篇框架"
            request_band_reason = "目标规模已达到史诗级长篇范围，系统会直接使用框架优先协同。"
        elif (
            target_chapter_count >= cls.FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD
            and chapters_needed > cls.SHORT_CHAPTER_DELTA_LIMIT
        ):
            request_band = "framework_preferred"
            request_band_label = "建议切长篇框架"
            request_band_reason = "目标规模已进入长篇区间，且本次增量较大，常规协同更容易受输出长度与上下文压缩影响。"
        elif effective_total > recommended_upper:
            request_band = "caution"
            request_band_label = "可用但需谨慎"
            request_band_reason = "目标规模已接近常规协同上沿，建议拆小请求，或尽早转入长篇框架协同。"
        else:
            request_band = "recommended"
            request_band_label = "推荐区间"
            request_band_reason = "当前目标仍在常规协同的稳定工作带内，适合直接进行单轮或分轮扩展。"

        summary = (
            f"常规协同建议优先用于总规模不超过 {recommended_upper} 章的项目；"
            f"{recommended_upper + 1}-{caution_upper} 章属于谨慎区间；"
            f"达到 {cls.FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD} 章且单次新增超过 {cls.SHORT_CHAPTER_DELTA_LIMIT} 章时，"
            "更适合直接切到长篇框架协同。"
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
            "caution_total_chapters_min": recommended_upper + 1,
            "caution_total_chapters_max": caution_upper,
            "framework_preferred_total_from": cls.FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD,
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
                    "label": "谨慎区间",
                    "range_text": f"总规模 {recommended_upper + 1}-{caution_upper} 章",
                    "detail": "仍可使用常规协同，但会明显更依赖长上下文与上下文压缩，建议尽量拆小请求。",
                },
                {
                    "key": "framework_preferred",
                    "label": "框架优先",
                    "range_text": (
                        f"总规模 >= {cls.FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD} 章，"
                        f"且单次新增 > {cls.SHORT_CHAPTER_DELTA_LIMIT} 章"
                    ),
                    "detail": "系统会优先建议长篇框架协同，先规划卷结构，再逐步细化到单卷。",
                },
                {
                    "key": "epic",
                    "label": "史诗范围",
                    "range_text": f"总规模 >= {cls.EPIC_CHAPTER_THRESHOLD} 章",
                    "detail": "达到该规模后会自动切到长篇框架模式，不再继续走常规协同。",
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
            return max(1, 1 + character_rounds)
        if mode == "epic":
            character_rounds = (characters_needed + cls.ITERATIVE_CHARACTER_STEP - 1) // cls.ITERATIVE_CHARACTER_STEP
            return max(1, 1 + character_rounds)
        if mode == "iterative":
            chapter_rounds = (chapters_needed + cls.ITERATIVE_CHAPTER_STEP - 1) // cls.ITERATIVE_CHAPTER_STEP
            character_rounds = (characters_needed + cls.ITERATIVE_CHARACTER_STEP - 1) // cls.ITERATIVE_CHARACTER_STEP
            return max(1, max(chapter_rounds, character_rounds))
        return 1

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

        for tuple_key in ["chapters_count_range", "expected_chapter_range"]:
            value = volume_detail_config.get(tuple_key)
            if isinstance(value, (list, tuple)) and len(value) == 2:
                try:
                    lower = int(value[0])
                    upper = int(value[1])
                    normalized[tuple_key] = (lower, upper)
                except Exception:
                    normalized[tuple_key] = None

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

    @staticmethod
    def _build_cross_support_plan(
        *,
        current_chapter_count: int,
        current_character_count: int,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        validation: Dict[str, Any],
    ) -> Dict[str, Any]:
        plan = {
            "suggested_target_chapters": target_total_chapters,
            "suggested_target_characters": target_total_characters,
            "chapter_delta": 0,
            "character_delta": 0,
            "reasons": [],
        }

        coverage_ratio = _safe_float(validation.get("coverage_ratio") or 0.0)
        chapter_count = int(validation.get("chapter_count") or current_chapter_count or 0)
        character_count = int(validation.get("character_count") or current_character_count or 0)

        if target_total_chapters is not None and target_total_characters is None:
            chapters_needed = max(0, int(target_total_chapters) - current_chapter_count)
            chapter_per_character = int(target_total_chapters) / max(character_count, 1)
            if chapters_needed > 0 and (
                character_count <= 0 or chapter_per_character > 8 or coverage_ratio < 0.45
            ):
                suggested_characters = max(2, min(6, (chapters_needed + 5) // 6))
                plan["character_delta"] = suggested_characters
                plan["suggested_target_characters"] = current_character_count + suggested_characters
                plan["reasons"].append(
                    "本次以扩章节为主，但人物密度偏低，建议同步补入少量配套角色承接新增情节。"
                )

        if target_total_characters is not None and target_total_chapters is None:
            characters_needed = max(0, int(target_total_characters) - current_character_count)
            chapter_density = chapter_count / max(character_count, 1) if character_count else 0.0
            if characters_needed > 0 and (
                chapter_count <= 0 or chapter_density < 2.0
            ):
                suggested_chapters = max(4, min(10, characters_needed * 2))
                plan["chapter_delta"] = suggested_chapters
                plan["suggested_target_chapters"] = current_chapter_count + suggested_chapters
                plan["reasons"].append(
                    "本次以扩人物为主，但现有章节锚点偏少，建议同步补入少量情节承接新角色。"
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
        epic_config: Optional[Dict[str, Any]] = None,
        volume_detail_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
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
            target_total_chapters=target_total_chapters,
            target_total_characters=target_total_characters,
            validation=validation,
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
        execution_mode = str(effective_mode_info.get("mode") or "delta").strip()
        estimated_rounds = self._estimate_execution_rounds_from_mode_info(effective_mode_info)
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

        model_plan = {
            "coordinator_planner_model": self._get_llm_model_name(getattr(self, "planner_llm", None), "unknown"),
            "coordinator_writer_model": self._get_llm_model_name(getattr(self, "writer_llm", None), "unknown"),
            "outline_expansion_model": self._estimate_outline_model(target_chapter_count),
            "character_expansion_model": self._estimate_character_model(target_character_count),
            "estimated_rounds": estimated_rounds,
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
            warnings.append("当前会走分轮扩展，结果可能分多轮逐步逼近目标，而不是一次性补齐。")
        if execution_mode == "epic":
            warnings.append("当前会先生成长篇框架，再逐步细化，不会一次性产出完整卷级细纲。")
            model_plan["notes"].append("长篇框架阶段优先使用长上下文模型，卷级细化仍建议后续分阶段展开。")
            if (
                normalized_expansion_mode in {"auto", "total"}
                and target_chapter_count >= self.FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD
                and int(effective_mode_info.get("chapters_needed") or 0) > self.SHORT_CHAPTER_DELTA_LIMIT
            ):
                warnings.append("目标章节规模已超出常规协同的稳定工作带，系统已自动升级为框架优先协同以降低超时和截断风险。")
        if normalized_expansion_mode == "epic_framework" and execution_mode == "epic":
            warnings.append("当前为显式长篇框架协同，会优先保证总卷框架与角色体系匹配，再进入卷级细化。")
        if execution_mode == "volume_detail":
            warnings.append("当前会聚焦单卷细化，并同步检查该卷所需角色是否齐备。")
            volume_range = effective_mode_info.get("volume_chapter_range")
            if volume_range:
                model_plan["notes"].append(
                    f"当前聚焦第{effective_mode_info.get('target_volume_index')}卷，预计细化第{int(volume_range[0])}-{int(volume_range[1])}章。"
                )
            volume_upper = int((normalized_volume_detail_config.get("chapters_count_range") or (0, 0))[1] or 0)
            model_plan["outline_expansion_model"] = "qwen-long" if volume_upper > 80 else "deepseek-reasoner"
            if normalized_volume_detail_config.get("existing_volume_detail"):
                warnings.append("目标卷已有细纲，本次协同会覆盖该卷现有细纲。")
        if target_chapter_count >= self.EPIC_CHAPTER_THRESHOLD:
            model_plan["outline_expansion_model"] = "qwen-long"
            model_plan["notes"].append("目标章节规模较大，大纲扩展优先使用长上下文模型，协同会分阶段收敛而非一次性铺满全部细纲。")
        if target_character_count >= 60:
            model_plan["character_expansion_model"] = "qwen-long"
            model_plan["notes"].append("目标人物规模较大，人物扩展会优先使用长上下文模型，并建议分轮补齐关系与剧情职责。")

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
            volume_range = normalized_volume_detail_config.get("expected_chapter_range")
            current_total_count = int(normalized_volume_detail_config.get("current_total_chapter_count") or current_chapter_count)
            expected_total_count = int(normalized_volume_detail_config.get("expected_total_chapter_count") or target_chapter_count or current_total_count)
            target_chapter_count = max(target_chapter_count, expected_total_count)
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

        if (
            normalized_expansion_mode in {"auto", "total"}
            and target_total_chapters is not None
            and chapters_needed > self.SHORT_CHAPTER_DELTA_LIMIT
            and framework_reference >= self.FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD
        ):
            return {
                "mode": "epic",
                "reason": (
                    f"目标规模约 {framework_reference} 章，且本次需跨越 {chapters_needed} 章增量；"
                    "常规协同在该区间更容易受输出长度与上下文压缩影响，切换为框架优先协同。"
                ),
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
        if target_total_chapters is not None and epic_reference >= self.EPIC_CHAPTER_THRESHOLD:
            return {
                "mode": "epic",
                "reason": f"目标规模约 {epic_reference} 章，已进入长篇/超长篇范围，切换为框架优先协同。",
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

    @staticmethod
    def _collect_new_character_names(existing_characters: str, merged_characters: str) -> List[str]:
        before = {normalize_character_name(name) for name in extract_character_names(existing_characters or "")}
        after_names = extract_character_names(merged_characters or "")
        return [name for name in after_names if normalize_character_name(name) not in before]

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
            suggestions.append("史诗框架中提及的人物覆盖率偏低，建议在卷级细纲阶段显式绑定关键人物。")
        suggestions.append("当前结果为史诗框架级协同，后续展开单卷细纲时需要继续做章节级验证。")

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

    @staticmethod
    def _estimate_epic_chapter_range(target_total_chapters: int) -> Tuple[int, int]:
        lower = max(300, int(target_total_chapters * 0.9))
        upper = max(lower + 60, int(target_total_chapters * 1.1))
        return lower, upper

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

    def _run_outline_round(
        self,
        current_outline: str,
        world_setting: str,
        characters: str,
        current_chapter_count: int,
        increment: int,
        target_total_chapters: int,
    ) -> Dict[str, Any]:
        expander = self._get_expander()
        return expander.expand_plot_outline_incremental(
            current_outline=current_outline,
            world_setting=world_setting,
            characters=characters,
            current_chapter_count=current_chapter_count,
            increment=increment,
            target_total_chapters=target_total_chapters,
        )

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
        relationship_patch = ""
        characters_text = current_characters or ""
        current_count = current_character_count

        if target_total_characters <= current_count:
            return {
                "characters_text": characters_text,
                "current_character_count": current_count,
                "relationship_patch": relationship_patch,
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
            next_count = int(round_result.get("current_character_count") or current_count)
            next_characters = round_result.get("all_characters") or characters_text
            if round_result.get("character_relationships"):
                relationship_patch = round_result.get("character_relationships") or relationship_patch

            rounds.append(
                {
                    "round": iteration,
                    "before_character_count": current_count,
                    "after_character_count": next_count,
                    "increment_requested": increment,
                    "post_validation_score": round_result.get("post_validation_score", 0),
                }
            )

            if next_count <= current_count:
                stop_reasons.append("人物扩展未产生新增内容，为避免空转已提前停止。")
                break

            characters_text = next_characters
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

        return {
            "characters_text": characters_text,
            "current_character_count": current_count,
            "relationship_patch": relationship_patch,
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
        resolved_strategy = self._resolve_strategy(
            strategy=strategy,
            validation=validation_before,
            chapters_needed=chapters_needed,
            characters_needed=characters_needed,
        )
        plan["strategy"] = resolved_strategy

        if chapters_needed > self.SHORT_CHAPTER_DELTA_LIMIT:
            raise ValueError("协同拓展一次最多新增 30 章，请切换为分轮模式执行。")
        if characters_needed > self.SHORT_CHARACTER_DELTA_LIMIT:
            raise ValueError("协同拓展一次最多新增 10 个角色，请切换为分轮模式执行。")
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
                new_character_cards=character_delta["new_character_cards"],
                relationship_patch=character_delta["relationship_patch"],
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
        new_character_names = self._collect_new_character_names(characters or "", merged_characters)

        return {
            "execution_mode": "delta",
            "execution_mode_reason": (mode_info or {}).get("reason", ""),
            "strategy": resolved_strategy,
            "summary": plan["summary"],
            "plan": plan,
            "plot_outline": outline_delta["plot_outline"],
            "characters": merged_characters,
            "outline_delta_text": outline_delta["outline_delta_text"],
            "character_delta_text": character_delta["new_character_cards"],
            "relationship_patch": character_delta["relationship_patch"],
            "outline_ops_executed": outline_delta["outline_ops_executed"],
            "execution_rounds": [
                {
                    "round": 1,
                    "mode": "delta",
                    "strategy": resolved_strategy,
                    "chapters_generated": sum(
                        int(item.get("generated_count") or 0)
                        for item in outline_delta["outline_ops_executed"]
                    ),
                    "characters_generated": len(new_character_names),
                }
            ],
            "new_character_names": new_character_names,
            "current_chapter_count": outline_delta["current_chapter_count"],
            "current_character_count": current_character_count,
            "validation_before": validation_before,
            "validation_after": validation_after,
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
        target_chapter_count = int(mode_info.get("target_chapter_count") or current_chapter_count)
        target_character_count = int(mode_info.get("target_character_count") or current_character_count)

        rounds: List[Dict[str, Any]] = []
        stop_reasons: List[str] = []
        relationship_patch = ""
        outline_active = target_chapter_count > current_chapter_count
        character_active = target_character_count > current_character_count

        for iteration in range(1, self.ITERATIVE_MAX_ROUNDS + 1):
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
                    target_total_chapters=target_chapter_count,
                )
                current_outline_text = result.get("expanded_outline") or current_outline_text
                current_chapter_count = int(result.get("current_chapter_count") or current_chapter_count)
                if not result.get("should_continue", True) and current_chapter_count < target_chapter_count:
                    outline_active = False
                    reason = str(result.get("continue_reason") or "").strip()
                    stop_reasons.append(reason or "大纲侧模型建议停止继续扩展。")
                return {
                    "increment_requested": increment,
                    "after_chapter_count": current_chapter_count,
                    "continue_reason": result.get("continue_reason", ""),
                }

            def run_character_side() -> Optional[Dict[str, Any]]:
                nonlocal current_characters, current_character_count, character_active, relationship_patch
                if not character_active:
                    return None
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
                next_count = int(result.get("current_character_count") or current_character_count)
                next_characters = result.get("all_characters") or current_characters
                if result.get("character_relationships"):
                    relationship_patch = result.get("character_relationships") or relationship_patch

                if next_count <= current_character_count:
                    character_active = False
                    stop_reasons.append("人物扩展未产生新增内容，为避免空转已提前停止。")
                else:
                    current_character_count = next_count
                    current_characters = next_characters

                if result.get("should_optimize_first"):
                    character_active = False
                    stop_reasons.append("人物-情节匹配度偏低，已停止继续新增人物。")

                validation_score = int(result.get("post_validation_score") or 0)
                if 0 < validation_score < 60 and current_character_count < target_character_count:
                    character_active = False
                    stop_reasons.append(f"人物-情节匹配度降至 {validation_score}/100，已停止继续新增人物。")

                if not result.get("should_continue", True) and current_character_count < target_character_count:
                    character_active = False
                    reason = str(result.get("continue_reason") or "").strip()
                    stop_reasons.append(reason or "人物侧模型建议停止继续扩展。")

                return {
                    "increment_requested": increment,
                    "after_character_count": current_character_count,
                    "post_validation_score": result.get("post_validation_score", 0),
                    "continue_reason": result.get("continue_reason", ""),
                }

            if round_strategy == "plot_first":
                round_record["plot"] = run_plot_side()
                round_record["character"] = run_character_side()
            else:
                round_record["character"] = run_character_side()
                round_record["plot"] = run_plot_side()

            round_record["after_chapter_count"] = current_chapter_count
            round_record["after_character_count"] = current_character_count
            round_record["validation"] = evaluate_story_coordination(current_outline_text, current_characters)
            rounds.append(round_record)

            if (
                current_chapter_count == before_chapter_count
                and current_character_count == before_character_count
            ):
                stop_reasons.append("本轮协同未产生任何新增内容，已提前停止。")
                break

            if not outline_active and not character_active:
                break

        validation_after = evaluate_story_coordination(current_outline_text, current_characters)
        new_character_names = self._collect_new_character_names(characters or "", current_characters)
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

        return {
            "execution_mode": "iterative",
            "execution_mode_reason": mode_info.get("reason", ""),
            "strategy": resolved_strategy,
            "summary": summary,
            "plan": {
                "strategy": resolved_strategy,
                "mode": "iterative",
                "target_chapter_count": target_chapter_count,
                "target_character_count": target_character_count,
            },
            "plot_outline": current_outline_text,
            "characters": current_characters,
            "outline_delta_text": "",
            "character_delta_text": "",
            "relationship_patch": relationship_patch,
            "outline_ops_executed": rounds,
            "execution_rounds": rounds,
            "new_character_names": new_character_names,
            "current_chapter_count": current_chapter_count,
            "current_character_count": current_character_count,
            "validation_before": validation_before,
            "validation_after": validation_after,
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
        relationship_patch = ""
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
            relationship_patch = character_program["relationship_patch"]
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
            relationship_patch = character_program["relationship_patch"] or relationship_patch
            stop_reasons.extend(character_program["stop_reasons"])
            for item in character_program["rounds"]:
                execution_rounds.append({"stage": "character_expand", **item})

        validation_after = self._build_epic_validation(
            framework_text=plot_outline,
            characters_text=current_characters,
            estimated_chapters=estimated_chapters,
        )
        new_character_names = self._collect_new_character_names(characters or "", current_characters)

        summary = (
            f"已切换为长篇框架优先协同，规划约 {estimated_chapters} 章、{total_volumes} 卷，"
            "后续建议按卷继续展开细纲。"
        )
        if stop_reasons:
            summary += f" 当前已记录阶段性停止原因：{'；'.join(dict.fromkeys(stop_reasons))}"

        return {
            "execution_mode": "epic",
            "execution_mode_reason": mode_info.get("reason", ""),
            "strategy": resolved_strategy,
            "summary": summary,
            "plan": {
                "strategy": resolved_strategy,
                "mode": "epic",
                "total_volumes": total_volumes,
                "target_chapter_range": list(chapter_range),
            },
            "plot_outline": plot_outline,
            "characters": current_characters,
            "outline_delta_text": "",
            "character_delta_text": "",
            "relationship_patch": relationship_patch,
            "outline_ops_executed": execution_rounds,
            "execution_rounds": execution_rounds,
            "new_character_names": new_character_names,
            "current_chapter_count": estimated_chapters,
            "current_character_count": current_character_count,
            "validation_before": validation_before,
            "validation_after": validation_after,
            "epic_framework": plot_outline,
            "epic_volumes_detail": "",
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
            raise ValueError("单卷细化协同缺少史诗框架上下文。")
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
        relationship_patch = ""

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
            relationship_patch = character_program["relationship_patch"]
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
            character_program = self._expand_characters_to_target(
                current_characters=current_characters,
                world_setting=world_setting,
                plot_outline=plot_outline,
                current_character_count=current_character_count,
                target_total_characters=target_character_count,
            )
            current_characters = character_program["characters_text"]
            current_character_count = character_program["current_character_count"]
            relationship_patch = character_program["relationship_patch"] or relationship_patch
            stop_reasons.extend(character_program["stop_reasons"])
            for item in character_program["rounds"]:
                execution_rounds.append({"stage": "character_expand", **item})

        validation_after = evaluate_story_coordination(plot_outline, current_characters)
        new_character_names = self._collect_new_character_names(characters or "", current_characters)
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

        return {
            "execution_mode": "volume_detail",
            "execution_mode_reason": mode_info.get("reason", ""),
            "strategy": resolved_strategy,
            "summary": summary,
            "plan": {
                "strategy": resolved_strategy,
                "mode": "volume_detail",
                "target_volume_index": target_volume_index,
                "chapter_range": [chapters_start, chapters_end],
            },
            "plot_outline": plot_outline,
            "characters": current_characters,
            "outline_delta_text": volume_result["expanded_outline"],
            "character_delta_text": "",
            "relationship_patch": relationship_patch,
            "outline_ops_executed": execution_rounds,
            "execution_rounds": execution_rounds,
            "new_character_names": new_character_names,
            "current_chapter_count": total_chapter_count,
            "current_character_count": current_character_count,
            "validation_before": validation_before,
            "validation_after": validation_after,
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
    ) -> Dict[str, Any]:
        mode_info = self.determine_execution_mode(
            current_outline=current_outline,
            characters=characters,
            target_total_chapters=target_total_chapters,
            target_total_characters=target_total_characters,
            expansion_mode=expansion_mode,
            epic_config=epic_config,
            volume_detail_config=volume_detail_config,
        )

        chapters_needed = int(mode_info.get("chapters_needed") or 0)
        characters_needed = int(mode_info.get("characters_needed") or 0)
        normalized_volume_detail_config = self._normalize_volume_detail_config(volume_detail_config)
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
