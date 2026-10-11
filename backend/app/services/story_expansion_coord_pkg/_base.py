from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from core.langchain_bridge import create_task_llm
from core.model_runtime import estimate_model_timeout_seconds
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

class StoryExpansionCoordinatorBase:
    # 协同扩展运行策略
    # 说明：
    # 1. 常规协同推荐控制在 450 章以内；
    # 2. 451-600 章仍允许执行，但更建议切换长篇框架；
    # 3. 超过 600 章后必须切到长篇框架协同。
    ITERATIVE_MAX_ROUNDS = 10
    ITERATIVE_CHAPTER_STEP = 60
    ITERATIVE_CHARACTER_STEP = 8
    ITERATIVE_TAIL_CHAPTER_GAP = 12
    SHORT_CHAPTER_DELTA_LIMIT = 60
    SHORT_CHARACTER_DELTA_LIMIT = 8
    CHARACTER_TARGET_MIN_CHAPTERS_PER_ROLE = 8
    CHARACTER_TARGET_MAX_CHAPTERS_PER_ROLE = 5
    AUTO_CHARACTER_INCREMENT_SOFT_CAP = 8
    EPIC_FRAMEWORK_AUTO_CHARACTER_INCREMENT_FLOOR = 12
    EPIC_FRAMEWORK_AUTO_CHARACTER_INCREMENT_SOFT_CAP = 24
    CONVENTIONAL_COLLABORATION_RECOMMENDED_MAX_CHAPTERS = 450
    FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD = 451
    CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS = 600
    EPIC_CHAPTER_THRESHOLD = 700
    EPIC_FRAMEWORK_MIN_TOTAL_CHAPTERS = 300
    EPIC_FRAMEWORK_MAX_TOTAL_CHAPTERS = 5000
    VOLUME_DETAIL_MIN_CHAPTERS = 20
    VOLUME_DETAIL_MAX_CHAPTERS = 120
    EPIC_MIN_VOLUMES = 3
    EPIC_MAX_VOLUMES = 50
    EPIC_DEFAULT_CHAPTERS_PER_VOLUME = 30
    STORY_EXPANSION_MODEL_CANDIDATES = (
        "qwen-plus",
        "deepseek-pro",
    )
    STORY_EXPANSION_MIN_CONTEXT_TOKENS = 1_000_000
    STORY_EXPANSION_MIN_OUTPUT_TOKENS = 65_536
    STORY_EXPANSION_LOW_RISK_QUALITY_FLOOR = 8.8
    STORY_EXPANSION_MEDIUM_RISK_QUALITY_FLOOR = 9.0
    STORY_EXPANSION_HIGH_RISK_QUALITY_FLOOR = 9.5
    STORY_EXPANSION_OUTPUT_HEADROOM_RATIO = 0.85
    # 扩展链路上下文预算（字符级）。
    # 协调器选型已要求 1M 上下文档位模型（STORY_EXPANSION_MIN_CONTEXT_TOKENS），
    # 旧的 2500/5000 字符粗截断会把长篇大纲后半段与完整世界观挡在决策视野外，
    # 导致新增角色与后期剧情错位。以下预算按 1M 窗口的保守占用设计。
    CONTEXT_BUDGET_WORLD = 8000
    CONTEXT_BUDGET_OUTLINE = 20000
    CONTEXT_BUDGET_CHARACTERS = 12000
    CONTEXT_BUDGET_NEW_CHARACTER_CARDS = 6000
    # delta 单批生成章数上限：超过该值时拆批调用，避免单次 JSON 负载过大稀释单章字段质量
    # （与 volume_detail 的分段生成保护对齐）
    DELTA_CHAPTER_BATCH_MAX_PER_CALL = 4
    # 人物-情节对齐闸门：评分低于该值或问题数达到该值时触发一次性自动修复
    ALIGNMENT_GATE_SCORE_THRESHOLD = 50
    ALIGNMENT_GATE_ISSUE_COUNT_THRESHOLD = 3

    def _run_character_plot_alignment_validation(
        self,
        characters: str,
        plot_outline: str,
        world_setting: str,
    ) -> Optional[Dict[str, Any]]:
        """对新协调结果执行 LLM 级人物-情节对齐验证（非阻塞）。

        规则级 evaluate_story_coordination 只能确认"人物名是否出现在大纲中"，
        无法发现人物在场但对情节无推动、角色冗余、关系设定未落地等深层错位；
        此处把 legacy 路径的 LLM 验证器接入新协调路径。
        """
        try:
            from app.services.agents.character_plot_validator import CharacterPlotValidator

            # 优先复用扩展运行时已验证可用的 planner 模型，
            # 避免 default 任务模型未配置 Key 时验证器静默失效
            runtime_model = (self._story_expansion_runtime_model_plan or {}).get("planner_model")
            validation = CharacterPlotValidator(
                model=runtime_model,
            ).validate_character_plot_alignment(
                characters=characters or "",
                plot_outline=plot_outline or "",
                world_setting=world_setting or "",
            )
            if validation.get("success"):
                return validation
            logger.warning(
                "人物-情节对齐验证未成功: %s",
                validation.get("error"),
            )
            return None
        except Exception as exc:
            logger.warning("人物-情节对齐验证失败（不影响扩展结果）: %s", exc)
            return None

    @staticmethod
    def _merge_character_plot_alignment_into_result(
        result: Dict[str, Any],
        alignment: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """把 LLM 对齐验证结论合并进扩展结果（追加告警，不阻断流程）。"""
        if not isinstance(result, dict) or not alignment or not alignment.get("success"):
            return result

        compact = {
            "score": alignment.get("score") or 0,
            "redundant_characters": list(alignment.get("redundant_characters") or []),
            "missing_characters": list(alignment.get("missing_characters") or []),
            "relationship_issues": list(alignment.get("relationship_issues") or []),
            "suggestions": list(alignment.get("suggestions") or [])[:5],
        }
        result["character_plot_alignment"] = compact

        notes: List[str] = []
        score = int(compact["score"] or 0)
        if score and score < 60:
            notes.append(f"人物-情节对齐评分 {score}/100 偏低")
        redundant = [str(item).strip() for item in compact["redundant_characters"][:3] if str(item).strip()]
        missing = [str(item).strip() for item in compact["missing_characters"][:3] if str(item).strip()]
        issues = [str(item).strip() for item in compact["relationship_issues"][:2] if str(item).strip()]
        if redundant:
            notes.append("疑似冗余人物：" + "；".join(redundant))
        if missing:
            notes.append("疑似缺失人物：" + "；".join(missing))
        if issues:
            notes.append("关系问题：" + "；".join(issues))

        if notes:
            warning_text = "【人物-情节对齐】" + "；".join(notes)
            warnings = list(result.get("alignment_warnings") or [])
            warnings.append(warning_text)
            result["alignment_warnings"] = warnings
            summary = str(result.get("coordination_summary") or "").strip()
            result["coordination_summary"] = f"{summary} {warning_text}".strip() if summary else warning_text
        return result

    @classmethod
    def _alignment_gate_should_retry(cls, alignment: Optional[Dict[str, Any]]) -> bool:
        """判断对齐验证结果是否触发一次性闸门修复（评分过低或问题项过多）。"""
        if not isinstance(alignment, dict) or not alignment.get("success"):
            return False
        try:
            score = int(alignment.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        issue_count = (
            len(alignment.get("redundant_characters") or [])
            + len(alignment.get("missing_characters") or [])
            + len(alignment.get("relationship_issues") or [])
        )
        return (
            score < cls.ALIGNMENT_GATE_SCORE_THRESHOLD
            or issue_count >= cls.ALIGNMENT_GATE_ISSUE_COUNT_THRESHOLD
        )

    @staticmethod
    def _format_alignment_issue_brief(alignment: Dict[str, Any]) -> str:
        """把首轮对齐问题压缩为修复指令可用的简报。"""
        def _clean(items: Any) -> List[str]:
            return [str(x).strip() for x in (items or []) if str(x).strip()]

        try:
            score = int(alignment.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        parts = [f"对齐评分：{score}/100"]
        redundant = _clean(alignment.get("redundant_characters"))
        missing = _clean(alignment.get("missing_characters"))
        issues = _clean(alignment.get("relationship_issues"))
        if redundant:
            parts.append("冗余人物（在场但无情节推动）：" + "；".join(redundant[:5]))
        if missing:
            parts.append("缺失人物（剧情需要但无人承担）：" + "；".join(missing[:5]))
        if issues:
            parts.append("关系合理性问题：" + "；".join(issues[:5]))
        return "\n".join(parts)

    def _apply_alignment_gate(
        self,
        result: Dict[str, Any],
        alignment: Optional[Dict[str, Any]],
        *,
        characters: str,
        world_setting: str,
    ) -> Dict[str, Any]:
        """对齐闸门：低分/多问题时触发一次性增量修复，修复后复验。

        语义：
        - 首验通过 → alignment_gate_status = "passed"，零额外调用
        - 触发修复 → 修复器先分类问题层级：
          - 注记级问题 → 生成增量补丁（只增不改，保持 delta 锁定语义）→ 应用 → 复验
            - 复验通过 → "repaired"
            - 复验仍不通过 → "failed_after_retry"（放行但显著标记）
          - 情节级问题（跨多章行动线/渐进铺垫，注记补丁无法落地）→ 不浪费修复+复验调用，
            记为 "deferred"，问题清单写入 alignment_structural_debt，
            由下一轮扩展的章节生成 prompt 承接（跨轮修复）
        - 验证器本身不可用（无 Key/异常）→ 不设状态，维持非阻塞兜底
        """
        if not isinstance(alignment, dict) or not alignment.get("success"):
            return self._merge_character_plot_alignment_into_result(result, alignment)

        result = self._merge_character_plot_alignment_into_result(result, alignment)
        # 本轮验证可用即重置结构债（后续情节级问题会重新写入；
        # 显式空值让调用方以最新状态覆盖存储，避免旧债无法清除）
        result["alignment_structural_debt"] = ""

        if not self._alignment_gate_should_retry(alignment):
            result["alignment_gate_status"] = "passed"
            return result

        issue_brief = self._format_alignment_issue_brief(alignment)
        patch_applied: Dict[str, int] = {"cards": 0, "duty_patches": 0, "relationship_patches": 0}
        try:
            patch = self._generate_alignment_repair_patch(
                plot_outline=str(result.get("plot_outline") or ""),
                characters=str(result.get("characters") or characters or ""),
                world_setting=str(world_setting or ""),
                issue_brief=issue_brief,
            )
            result, patch_applied = self._apply_alignment_repair_patch(result, patch)
        except Exception as exc:
            logger.warning("对齐闸门修复调用失败（放行并标记）: %s", exc)
            result["alignment_gate_status"] = "failed_after_retry"
            result["alignment_gate_retry"] = {"issues": issue_brief, "error": str(exc)[:200]}
            return result

        plot_level_issues = [
            str(item).strip()
            for item in (patch.get("plot_level_issues") or [])
            if str(item).strip()
        ]
        if plot_level_issues:
            result["alignment_structural_debt"] = "\n".join(
                f"- {issue}" for issue in plot_level_issues[:10]
            )

        total_applied = sum(patch_applied.values())
        if total_applied == 0:
            if plot_level_issues:
                # 全部为情节级问题：注记补丁无意义，跳过注定失败的复验，
                # 转为 deferred 结构债，由下轮扩展新增章节承接
                logger.info(
                    "对齐闸门：%s 项情节级问题转为结构债（deferred），下轮扩展承接",
                    len(plot_level_issues),
                )
                result["alignment_gate_status"] = "deferred"
                result["alignment_gate_retry"] = {
                    "issues": issue_brief,
                    "patch_applied": patch_applied,
                    "plot_level_issues": plot_level_issues[:10],
                }
                return result
            # 修复器认为无可补：保守起见按情节级问题处理（首验问题清单整体转为结构债，
            # 由下轮扩展承接；若确属误报，注入 prompt 的提示无害）
            logger.info(
                "对齐闸门：修复器无可补输出，首验 %s 项问题整体转为结构债（deferred）",
                issue_brief.count("\n") or len(issue_brief),
            )
            result["alignment_gate_status"] = "deferred"
            result["alignment_structural_debt"] = issue_brief[:2000]
            result["alignment_gate_retry"] = {"issues": issue_brief, "patch_applied": patch_applied}
            return result

        # 复验一次（重跑上限 1 次）
        recheck = self._run_character_plot_alignment_validation(
            characters=str(result.get("characters") or characters or ""),
            plot_outline=str(result.get("plot_outline") or ""),
            world_setting=str(world_setting or ""),
        )
        if isinstance(recheck, dict) and recheck.get("success"):
            result = self._merge_character_plot_alignment_into_result(result, recheck)
            result["alignment_gate_status"] = (
                "repaired" if not self._alignment_gate_should_retry(recheck) else "failed_after_retry"
            )
        else:
            result["alignment_gate_status"] = "failed_after_retry"
        result["alignment_gate_retry"] = {
            "issues": issue_brief,
            "patch_applied": patch_applied,
            **({"plot_level_issues": plot_level_issues[:10]} if plot_level_issues else {}),
        }
        return result

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

        deepseek_v4_budget = 384000
        deepseek_v4_timeout = estimate_model_timeout_seconds(
            "deepseek-pro",
            deepseek_v4_budget,
        )

        # 🚀 协同扩展统一使用 deepseek-pro（384K 超长输出），不再按规模动态切换
        logger.debug(
            f"✅ 协同扩展统一使用 deepseek-pro（规划章节数={self.planned_chapters_max}）"
        )
        self.planner_llm = create_task_llm(
            model="deepseek-pro",
            temperature=0.2,
            max_tokens=deepseek_v4_budget,
            timeout=deepseek_v4_timeout,
        )
        self.writer_llm = create_task_llm(
            model="deepseek-pro",
            temperature=0.45,
            max_tokens=deepseek_v4_budget,
            timeout=deepseek_v4_timeout,
        )
        self._outline_expander: Optional[Any] = None
        self._story_expansion_runtime_model_plan: Dict[str, Any] = {}

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

    def _invoke_chapter_json(
        self,
        prompt: str,
        fallback: Dict[str, Any],
        *,
        chapter_count: int = 1,
    ) -> Dict[str, Any]:
        """章节卡 JSON 专用调用：独立大输出预算，避免与 planner 小预算共用导致截断。

        动态选模给 planner 的 max_tokens 按小规划 JSON 估算（约 4K），
        而章节卡 JSON 每章 10 个中文字段，输出量大（每章约 1.2K-1.5K token），
        复用 planner 预算会截断 JSON 导致整批解析失败（只能走文本回退）。
        """
        try:
            per_chapter_tokens = 1500
            budget = max(8192, per_chapter_tokens * max(1, int(chapter_count)) + 3072)
            llm = self._build_story_expansion_runtime_llm(
                (self._story_expansion_runtime_model_plan or {}).get("planner_model")
                or "deepseek-pro",
                role="planner",
                requested_max_tokens=budget,
                response_format={"type": "json_object"},
            )
            response = llm.invoke(prompt)
            raw_text = response.content if hasattr(response, "content") else str(response)
        except Exception as exc:
            logger.warning("章节卡 JSON 调用异常（回退 planner 预算重试）: %s", exc)
            raw_text = self._invoke_text(prompt, use_planner=True)
        parsed = self._extract_json(raw_text)
        if isinstance(parsed, dict):
            return parsed
        salvaged = self._salvage_truncated_chapter_json(raw_text)
        if salvaged and salvaged.get("chapters"):
            logger.warning(
                "章节卡 JSON 尾部截断，抢救回收 %s/%s 章完整章节卡：raw_len=%s",
                len(salvaged["chapters"]),
                chapter_count,
                len(raw_text or ""),
            )
            return salvaged
        logger.warning(
            "章节卡 JSON 解析失败：raw_len=%s head=%r tail=%r",
            len(raw_text or ""),
            (raw_text or "")[:120],
            (raw_text or "")[-120:],
        )
        return fallback

    @staticmethod
    def _salvage_truncated_chapter_json(text: str) -> Optional[Dict[str, Any]]:
        """从尾部截断的章节卡 JSON 中抢救完整章节对象。

        思考型模型思考 token 挤占输出预算时，JSON 会在字符串中间被截断，
        整批解析失败即整批丢失；此处按括号配对回收已完整的章节卡，降级不减质。
        """
        match = re.search(r'"chapters"\s*:\s*\[', text or "")
        if not match:
            return None
        chapters: List[Any] = []
        depth = 0
        in_string = False
        escaped = False
        obj_start = -1
        for index in range(match.end(), len(text)):
            ch = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                if depth == 0:
                    obj_start = index
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and obj_start >= 0:
                    fragment = text[obj_start : index + 1]
                    try:
                        chapters.append(json.loads(fragment))
                    except Exception:
                        pass
                    obj_start = -1
            elif ch == "]" and depth == 0:
                break
        valid_chapters = [item for item in chapters if isinstance(item, dict)]
        if not valid_chapters:
            return None
        return {"chapters": valid_chapters}

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
            from app.services.agents.outline_expander import create_outline_expander

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
    def _coerce_non_negative_int(value: Any, fallback: int = 0) -> int:
        try:
            return max(0, int(value))
        except Exception:
            return max(0, int(fallback or 0))

    @classmethod
    def build_conventional_collaboration_limit_message(cls) -> str:
        return (
            f"常规协同仅支持总规模不超过 {cls.CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS} 个细化章节；"
            f"{cls.FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD} 章起建议优先改用长篇框架协同，"
            f"超过 {cls.CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS} 章后必须切换。"
        )

    @classmethod
    def build_conventional_collaboration_recommendation_message(cls) -> str:
        return (
            f"常规协同推荐总规模不超过 {cls.CONVENTIONAL_COLLABORATION_RECOMMENDED_MAX_CHAPTERS} 个细化章节；"
            f"{cls.FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD}-{cls.CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS} 章仍可执行，"
            "但更建议先切换到长篇框架协同。"
        )

    @classmethod
    def build_epic_framework_total_range_text(cls) -> str:
        return f"{cls.EPIC_FRAMEWORK_MIN_TOTAL_CHAPTERS}-{cls.EPIC_FRAMEWORK_MAX_TOTAL_CHAPTERS}"

    @classmethod
    def build_volume_detail_chapter_range_text(cls) -> str:
        return f"{cls.VOLUME_DETAIL_MIN_CHAPTERS}-{cls.VOLUME_DETAIL_MAX_CHAPTERS}"

    @classmethod
    def _resolve_outline_count(
        cls,
        outline_text: str,
        reported_count: Any,
        fallback_count: int,
    ) -> int:
        _, blocks = parse_outline_blocks(outline_text or "")
        parsed_max_number = max((int(block.original_number or 0) for block in blocks), default=0)
        fallback_value = cls._coerce_non_negative_int(fallback_count)
        reported_value = cls._coerce_non_negative_int(reported_count)
        if parsed_max_number > 0:
            return max(fallback_value, parsed_max_number)
        return max(fallback_value, reported_value)

    @classmethod
    def _resolve_character_count(
        cls,
        characters_text: str,
        reported_count: Any,
        fallback_count: int,
    ) -> int:
        parsed_count = len(extract_character_names(characters_text or ""))
        fallback_value = cls._coerce_non_negative_int(fallback_count)
        reported_value = cls._coerce_non_negative_int(reported_count)
        if parsed_count > 0:
            return max(fallback_value, parsed_count)
        return max(fallback_value, reported_value)

    def _get_story_expansion_candidate_specs(self) -> List[Dict[str, Any]]:
        try:
            from core.model_hub import model_hub
            from core.model_runtime import ensure_model_hub_initialized

            ensure_model_hub_initialized()
        except Exception:
            return []

        candidates: List[Dict[str, Any]] = []
        for model_id in self.STORY_EXPANSION_MODEL_CANDIDATES:
            spec = model_hub.registry.get_spec(model_id)
            if spec is None or not spec.is_available():
                continue

            performance = getattr(spec, "performance", None)
            constraints = getattr(spec, "constraints", None)
            quality_score = float(getattr(performance, "quality_score", 0.0) or 0.0)
            input_cost = float(getattr(performance, "cost_per_1k_input_tokens", 0.0) or 0.0)
            output_cost = float(getattr(performance, "cost_per_1k_output_tokens", 0.0) or 0.0)
            context_limit = self._coerce_non_negative_int(
                getattr(constraints, "max_context_tokens", 0),
            )
            output_limit = self._coerce_non_negative_int(
                getattr(constraints, "max_output_tokens", 0),
            )

            candidates.append(
                {
                    "model_id": model_id,
                    "spec": spec,
                    "quality_score": quality_score,
                    "input_cost": input_cost,
                    "output_cost": output_cost,
                    "blended_cost": input_cost + output_cost * 1.2,
                    "context_limit": context_limit,
                    "output_limit": output_limit,
                }
            )

        return candidates

    @classmethod
    def _estimate_story_expansion_output_tokens(
        cls,
        *,
        role: str,
        execution_mode: str,
        current_chapter_count: int,
        target_chapter_count: int,
        current_character_count: int,
        target_character_count: int,
        estimated_rounds: int,
        volume_detail_config: Optional[Dict[str, Any]] = None,
    ) -> int:
        chapter_delta = max(0, target_chapter_count - current_chapter_count)
        character_delta = max(0, target_character_count - current_character_count)

        if execution_mode == "iterative":
            chapter_payload = min(chapter_delta, cls.ITERATIVE_CHAPTER_STEP)
            character_payload = min(character_delta, cls.ITERATIVE_CHARACTER_STEP)
        elif execution_mode == "volume_detail":
            chapter_payload = max(0, cls._resolve_volume_detail_target_span(volume_detail_config))
            character_payload = character_delta
        elif execution_mode == "epic":
            chapter_payload = min(
                max(chapter_delta, cls.EPIC_DEFAULT_CHAPTERS_PER_VOLUME),
                cls.EPIC_DEFAULT_CHAPTERS_PER_VOLUME * 2,
            )
            character_payload = min(
                character_delta,
                cls.EPIC_FRAMEWORK_AUTO_CHARACTER_INCREMENT_SOFT_CAP,
            )
        else:
            chapter_payload = chapter_delta
            character_payload = character_delta

        rounds = max(1, int(estimated_rounds or 1))
        if role == "planner":
            base_tokens = 3500 if execution_mode != "volume_detail" else 5000
            per_chapter_tokens = 220 if execution_mode == "volume_detail" else 140
            per_character_tokens = 420
            if execution_mode == "epic":
                per_chapter_tokens = 180
                per_character_tokens = 520
            return max(
                4096,
                int(
                    base_tokens
                    + chapter_payload * per_chapter_tokens
                    + character_payload * per_character_tokens
                    + max(0, rounds - 1) * 600
                ),
            )

        base_tokens = 3000
        per_chapter_tokens = 520
        per_character_tokens = 2200
        if execution_mode == "volume_detail":
            base_tokens = 6000
            per_chapter_tokens = 850
            per_character_tokens = 2400
        elif execution_mode == "epic":
            base_tokens = 8000
            per_chapter_tokens = 180
            per_character_tokens = 2400

        return max(
            4096,
            int(
                base_tokens
                + chapter_payload * per_chapter_tokens
                + character_payload * per_character_tokens
            ),
        )

    @classmethod
    def _resolve_story_expansion_quality_floor(cls, risk_score: int) -> float:
        if risk_score >= 60:
            return cls.STORY_EXPANSION_HIGH_RISK_QUALITY_FLOOR
        if risk_score >= 30:
            return cls.STORY_EXPANSION_MEDIUM_RISK_QUALITY_FLOOR
        return cls.STORY_EXPANSION_LOW_RISK_QUALITY_FLOOR

    def _build_story_expansion_model_context(
        self,
        *,
        current_outline: str,
        characters: str,
        world_setting: str,
        validation: Optional[Dict[str, Any]],
        mode_info: Dict[str, Any],
        estimated_rounds: int,
        expansion_mode: str,
        volume_detail_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        validation = validation or {}
        execution_mode = str(mode_info.get("mode") or "delta").strip()
        current_chapter_count = self._coerce_non_negative_int(mode_info.get("current_chapter_count"))
        target_chapter_count = max(
            current_chapter_count,
            self._coerce_non_negative_int(mode_info.get("target_chapter_count"), current_chapter_count),
        )
        current_character_count = self._coerce_non_negative_int(mode_info.get("current_character_count"))
        target_character_count = max(
            current_character_count,
            self._coerce_non_negative_int(mode_info.get("target_character_count"), current_character_count),
        )
        chapter_delta = max(0, target_chapter_count - current_chapter_count)
        character_delta = max(0, target_character_count - current_character_count)
        coordination_score = int(round(_safe_float(validation.get("score") or 0.0)))
        coverage_ratio = _safe_float(validation.get("coverage_ratio") or 0.0)
        unreferenced_characters = list(validation.get("unreferenced_characters") or [])

        planner_risk = 0
        writer_risk = 0

        if execution_mode == "volume_detail":
            planner_risk += 42
            writer_risk += 46
        elif execution_mode == "epic":
            planner_risk += 18
            writer_risk += 22
        elif execution_mode == "iterative":
            planner_risk += 10
            writer_risk += 12

        if coordination_score < 55:
            planner_risk += 28
            writer_risk += 32
        elif coordination_score < 65:
            planner_risk += 16
            writer_risk += 18
        elif coordination_score < 75:
            planner_risk += 8
            writer_risk += 10

        if coverage_ratio < 0.55:
            planner_risk += 20
            writer_risk += 24
        elif coverage_ratio < 0.7:
            planner_risk += 8
            writer_risk += 10

        if len(unreferenced_characters) >= 4:
            planner_risk += 18
            writer_risk += 22
        elif unreferenced_characters:
            planner_risk += 8
            writer_risk += 10

        if not (current_outline or "").strip():
            planner_risk += 8
            writer_risk += 10
        if not (characters or "").strip():
            planner_risk += 8
            writer_risk += 12
        if not (world_setting or "").strip():
            planner_risk += 2
            writer_risk += 2

        if chapter_delta >= self.ITERATIVE_CHAPTER_STEP:
            planner_risk += 8
            writer_risk += 12
        elif chapter_delta >= max(1, self.ITERATIVE_CHAPTER_STEP // 2):
            planner_risk += 4
            writer_risk += 6

        if character_delta >= self.ITERATIVE_CHARACTER_STEP * 2:
            planner_risk += 16
            writer_risk += 22
        elif character_delta >= self.ITERATIVE_CHARACTER_STEP:
            planner_risk += 8
            writer_risk += 12
        elif character_delta >= max(1, self.ITERATIVE_CHARACTER_STEP // 2):
            planner_risk += 4
            writer_risk += 6

        if max(1, int(estimated_rounds or 1)) >= 5:
            planner_risk += 8
            writer_risk += 8

        planner_estimated_output = self._estimate_story_expansion_output_tokens(
            role="planner",
            execution_mode=execution_mode,
            current_chapter_count=current_chapter_count,
            target_chapter_count=target_chapter_count,
            current_character_count=current_character_count,
            target_character_count=target_character_count,
            estimated_rounds=estimated_rounds,
            volume_detail_config=volume_detail_config,
        )
        writer_estimated_output = self._estimate_story_expansion_output_tokens(
            role="writer",
            execution_mode=execution_mode,
            current_chapter_count=current_chapter_count,
            target_chapter_count=target_chapter_count,
            current_character_count=current_character_count,
            target_character_count=target_character_count,
            estimated_rounds=estimated_rounds,
            volume_detail_config=volume_detail_config,
        )

        if planner_estimated_output >= 40000:
            planner_risk += 14
        elif planner_estimated_output >= 20000:
            planner_risk += 6

        if writer_estimated_output >= 52000:
            writer_risk += 26
        elif writer_estimated_output >= 42000:
            writer_risk += 12

        planner_required_output = max(
            16384,
            min(self.STORY_EXPANSION_MIN_OUTPUT_TOKENS, planner_estimated_output),
        )
        writer_required_output = max(
            self.STORY_EXPANSION_MIN_OUTPUT_TOKENS,
            writer_estimated_output,
        )

        qwen_output_threshold = int(
            self.STORY_EXPANSION_MIN_OUTPUT_TOKENS * self.STORY_EXPANSION_OUTPUT_HEADROOM_RATIO
        )
        if planner_estimated_output >= qwen_output_threshold:
            planner_required_output = self.STORY_EXPANSION_MIN_OUTPUT_TOKENS + 1
        if writer_estimated_output >= qwen_output_threshold:
            writer_required_output = self.STORY_EXPANSION_MIN_OUTPUT_TOKENS + 1

        return {
            "expansion_mode": str(expansion_mode or "auto").strip() or "auto",
            "execution_mode": execution_mode,
            "current_chapter_count": current_chapter_count,
            "target_chapter_count": target_chapter_count,
            "current_character_count": current_character_count,
            "target_character_count": target_character_count,
            "chapter_delta": chapter_delta,
            "character_delta": character_delta,
            "estimated_rounds": max(1, int(estimated_rounds or 1)),
            "coordination_score": coordination_score,
            "coverage_ratio": coverage_ratio,
            "unreferenced_characters": unreferenced_characters,
            "planner_risk_score": planner_risk,
            "writer_risk_score": writer_risk,
            "planner_quality_floor": self._resolve_story_expansion_quality_floor(planner_risk),
            "writer_quality_floor": self._resolve_story_expansion_quality_floor(writer_risk),
            "planner_estimated_output_tokens": planner_estimated_output,
            "writer_estimated_output_tokens": writer_estimated_output,
            "planner_required_output_tokens": planner_required_output,
            "writer_required_output_tokens": writer_required_output,
        }

    def _select_story_expansion_model_for_role(
        self,
        *,
        role: str,
        context: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if role not in {"planner", "writer"}:
            raise ValueError(f"unsupported story expansion role: {role}")

        quality_floor = float(context.get(f"{role}_quality_floor") or self.STORY_EXPANSION_HIGH_RISK_QUALITY_FLOOR)
        required_output = self._coerce_non_negative_int(
            context.get(f"{role}_required_output_tokens"),
            self.STORY_EXPANSION_MIN_OUTPUT_TOKENS,
        )
        estimated_output = self._coerce_non_negative_int(
            context.get(f"{role}_estimated_output_tokens"),
            required_output,
        )
        risk_score = self._coerce_non_negative_int(context.get(f"{role}_risk_score"))

        eligible = [
            candidate
            for candidate in candidates
            if candidate["context_limit"] >= self.STORY_EXPANSION_MIN_CONTEXT_TOKENS
            and candidate["output_limit"] >= required_output
            and candidate["quality_score"] >= quality_floor
        ]

        if eligible:
            selected = min(
                eligible,
                key=lambda item: (
                    item["blended_cost"],
                    -item["quality_score"],
                    -item["output_limit"],
                ),
            )
            fallback_used = False
        else:
            compatible = [
                candidate
                for candidate in candidates
                if candidate["context_limit"] >= self.STORY_EXPANSION_MIN_CONTEXT_TOKENS
            ]
            if compatible:
                selected = max(
                    compatible,
                    key=lambda item: (
                        item["quality_score"],
                        item["output_limit"],
                        -item["blended_cost"],
                    ),
                )
            elif candidates:
                selected = max(
                    candidates,
                    key=lambda item: (
                        item["quality_score"],
                        item["output_limit"],
                        -item["blended_cost"],
                    ),
                )
            else:
                selected = {
                    "model_id": "deepseek-pro",
                    "quality_score": self.STORY_EXPANSION_HIGH_RISK_QUALITY_FLOOR,
                    "input_cost": 0.0,
                    "output_cost": 0.0,
                    "context_limit": self.STORY_EXPANSION_MIN_CONTEXT_TOKENS,
                    "output_limit": 384000,
                }
            fallback_used = True

        if fallback_used:
            basis = (
                f"{role} 阶段未找到同时满足质量≥{quality_floor:.1f}、输出≥{required_output} 的低成本候选，"
                f"回退到能力更强的 {selected['model_id']} 保底。"
            )
        else:
            basis = (
                f"{role} 阶段先按质量≥{quality_floor:.1f}、输出≥{required_output}、上下文≥"
                f"{self.STORY_EXPANSION_MIN_CONTEXT_TOKENS} 过滤，再选择综合成本最低的 {selected['model_id']}。"
            )

        requested_max_tokens = max(
            4096,
            int(math.ceil(estimated_output * (1.12 if role == "planner" else 1.18))),
        )
        output_limit = self._coerce_non_negative_int(
            selected.get("output_limit"),
            requested_max_tokens,
        )
        if output_limit > 0:
            requested_max_tokens = min(requested_max_tokens, output_limit)
        timeout_seconds = estimate_model_timeout_seconds(
            selected["model_id"],
            requested_max_tokens,
        )

        return {
            "role": role,
            "selected_model": selected["model_id"],
            "quality_floor": quality_floor,
            "required_output_tokens": required_output,
            "estimated_output_tokens": estimated_output,
            "requested_max_tokens": requested_max_tokens,
            "timeout_seconds": timeout_seconds,
            "risk_score": risk_score,
            "fallback_used": fallback_used,
            "input_cost": float(selected.get("input_cost", 0.0) or 0.0),
            "output_cost": float(selected.get("output_cost", 0.0) or 0.0),
            "quality_score": float(selected.get("quality_score", 0.0) or 0.0),
            "selection_basis": basis,
        }

    def _select_story_expansion_runtime_models(
        self,
        *,
        current_outline: str,
        characters: str,
        world_setting: str,
        validation: Optional[Dict[str, Any]],
        mode_info: Dict[str, Any],
        estimated_rounds: int,
        expansion_mode: str,
        volume_detail_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = self._build_story_expansion_model_context(
            current_outline=current_outline,
            characters=characters,
            world_setting=world_setting,
            validation=validation,
            mode_info=mode_info,
            estimated_rounds=estimated_rounds,
            expansion_mode=expansion_mode,
            volume_detail_config=volume_detail_config,
        )
        candidates = self._get_story_expansion_candidate_specs()
        planner = self._select_story_expansion_model_for_role(
            role="planner",
            context=context,
            candidates=candidates,
        )
        writer = self._select_story_expansion_model_for_role(
            role="writer",
            context=context,
            candidates=candidates,
        )

        selection_reason = (
            "协同扩展先做质量与输出门槛过滤，再在达标模型里按综合成本最低选型。"
        )
        quality_guard = (
            f"基础门槛为 1M 上下文、至少 {self.STORY_EXPANSION_MIN_OUTPUT_TOKENS} 输出、质量分至少 "
            f"{self.STORY_EXPANSION_LOW_RISK_QUALITY_FLOOR:.1f}；当协同分偏低、角色承接薄弱、卷级细化或输出接近 "
            f"{self.STORY_EXPANSION_MIN_OUTPUT_TOKENS} 上限时，自动升级到更高质量模型。"
        )
        cost_hint = (
            f"planner={planner['selected_model']}({planner['input_cost']}/{planner['output_cost']}), "
            f"writer={writer['selected_model']}({writer['input_cost']}/{writer['output_cost']}) "
            "按输入/输出千 token 成本计。"
        )

        return {
            "planner_model": planner["selected_model"],
            "writer_model": writer["selected_model"],
            "planner": planner,
            "writer": writer,
            "context": context,
            "selection_reason": selection_reason,
            "selection_quality_guard": quality_guard,
            "selection_cost_hint": cost_hint,
        }

    def _build_story_expansion_runtime_llm(
        self,
        model_id: str,
        *,
        role: str,
        requested_max_tokens: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> Any:
        candidate_specs = self._get_story_expansion_candidate_specs()
        selected_spec = next(
            (item for item in candidate_specs if item["model_id"] == model_id),
            None,
        )
        model_output_limit = self._coerce_non_negative_int(
            (selected_spec or {}).get("output_limit"),
            384000 if model_id == "deepseek-pro" else self.STORY_EXPANSION_MIN_OUTPUT_TOKENS,
        )
        max_tokens = self._coerce_non_negative_int(
            requested_max_tokens,
            model_output_limit,
        )
        if model_output_limit > 0:
            max_tokens = min(max_tokens, model_output_limit)
        effective_timeout_seconds = self._coerce_non_negative_int(
            timeout_seconds,
            estimate_model_timeout_seconds(model_id, max_tokens) or 0,
        )
        temperature = 0.2 if role == "planner" else 0.45
        return create_task_llm(
            model=model_id,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=effective_timeout_seconds or None,
            response_format=response_format,
        )

    def _configure_story_expansion_runtime_models(
        self,
        *,
        current_outline: str,
        characters: str,
        world_setting: str,
        validation: Optional[Dict[str, Any]],
        mode_info: Dict[str, Any],
        estimated_rounds: int,
        expansion_mode: str,
        volume_detail_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        selection = self._select_story_expansion_runtime_models(
            current_outline=current_outline,
            characters=characters,
            world_setting=world_setting,
            validation=validation,
            mode_info=mode_info,
            estimated_rounds=estimated_rounds,
            expansion_mode=expansion_mode,
            volume_detail_config=volume_detail_config,
        )
        self.planner_llm = self._build_story_expansion_runtime_llm(
            selection["planner_model"],
            role="planner",
            requested_max_tokens=selection.get("planner", {}).get("requested_max_tokens"),
            timeout_seconds=selection.get("planner", {}).get("timeout_seconds"),
        )
        self.writer_llm = self._build_story_expansion_runtime_llm(
            selection["writer_model"],
            role="writer",
            requested_max_tokens=selection.get("writer", {}).get("requested_max_tokens"),
            timeout_seconds=selection.get("writer", {}).get("timeout_seconds"),
        )
        self._story_expansion_runtime_model_plan = selection

        logger.info(
            "协同扩展动态选模完成: planner=%s writer=%s score=%s coverage=%.2f mode=%s",
            selection["planner_model"],
            selection["writer_model"],
            selection["context"].get("coordination_score"),
            float(selection["context"].get("coverage_ratio") or 0.0),
            selection["context"].get("execution_mode"),
        )
        logger.info(
            "协同扩展选模细节: planner=%s(max_tokens=%s, est_output=%s, risk=%s) "
            "writer=%s(max_tokens=%s, est_output=%s, risk=%s)",
            selection["planner_model"],
            selection.get("planner", {}).get("requested_max_tokens"),
            selection.get("planner", {}).get("estimated_output_tokens"),
            selection.get("planner", {}).get("risk_score"),
            selection["writer_model"],
            selection.get("writer", {}).get("requested_max_tokens"),
            selection.get("writer", {}).get("estimated_output_tokens"),
            selection.get("writer", {}).get("risk_score"),
        )
        logger.info(
            "协同扩展选模依据: planner=%s | writer=%s",
            selection.get("planner", {}).get("selection_basis"),
            selection.get("writer", {}).get("selection_basis"),
        )
        logger.info(
            "协同扩展动态超时: planner=%s(max_tokens=%s, timeout=%s) writer=%s(max_tokens=%s, timeout=%s)",
            selection["planner_model"],
            selection.get("planner", {}).get("requested_max_tokens"),
            selection.get("planner", {}).get("timeout_seconds"),
            selection["writer_model"],
            selection.get("writer", {}).get("requested_max_tokens"),
            selection.get("writer", {}).get("timeout_seconds"),
        )
        return selection

