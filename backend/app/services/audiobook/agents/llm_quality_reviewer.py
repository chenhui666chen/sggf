"""
LLMQualityReviewer - LLM 多维度质感评审器

核心职责：
1. 对有声剧本进行 8 个主观质感维度的 LLM 评审（只评不改）
2. 产出结构化维度评分与按维度归因的 issues
3. 批处理 + 非阻断降级，失败不影响主生成链路

评审维度（三类八维）：
- 内容与叙事：semantic_coherence / narrative_pacing / atmosphere_imagery
- 角色与对白：characterization / dialogue_naturalness / emotion_expression
- 听觉制作：audio_cue_relevance / speakability
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Dict, List, Optional, Sequence

from app.services.audiobook.llm_client import call_audiobook_llm_async
from app.services.audiobook.voice_identity_policy import (
    FIXED_VOICE_PERFORMANCE_BOUNDARY_PROMPT,
)
from app.services.audiobook.llm_json import LLMJsonParseError, parse_llm_json_object

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_REVIEW_BATCH_SIZE = 8
REVIEW_OUTPUT_TOKEN_MIN = 2000
REVIEW_OUTPUT_TOKEN_MAX = 6000
REVIEW_TIMEOUT_MIN_SECONDS = 40
REVIEW_TIMEOUT_MAX_SECONDS = 80
REVIEW_TIMEOUT_OVERHEAD_SECONDS = 15
REVIEW_FALLBACK_ATTEMPTS = 1
SOURCE_CONTEXT_MAX_CHARS = 1500

# 8 个评审维度及其说明（注入 prompt）
QUALITY_DIMENSIONS: Dict[str, Dict[str, str]] = {
    "semantic_coherence": {
        "label": "语义完整性与连贯性",
        "category": "content_narrative",
        "criteria": "指代清晰、因果连贯、场景转换可理解、无断裂/遗漏/重复",
    },
    "narrative_pacing": {
        "label": "叙事节奏",
        "category": "content_narrative",
        "criteria": "张弛有度、悬念铺垫、高潮推进、信息密度适当",
    },
    "atmosphere_imagery": {
        "label": "氛围与画面感",
        "category": "content_narrative",
        "criteria": "场景氛围营造、环境听觉想象、沉浸感",
    },
    "characterization": {
        "label": "角色贴合度",
        "category": "character_dialogue",
        "criteria": "对白符合人设/身份/性格、语气一致、角色区分度",
    },
    "dialogue_naturalness": {
        "label": "对白自然度",
        "category": "character_dialogue",
        "criteria": "口语化、符合听觉接受、无生硬书面语",
    },
    "emotion_expression": {
        "label": "情感表达",
        "category": "character_dialogue",
        "criteria": "情绪标注准确、贴合情境、起伏自然、performance_notes可执行",
    },
    "audio_cue_relevance": {
        "label": "音效配乐契合度",
        "category": "audio_production",
        "criteria": "音效/配乐与场景情绪匹配（超越密度，关注契合）",
    },
    "speakability": {
        "label": "朗读可播讲性",
        "category": "audio_production",
        "criteria": "适合朗读、无拗口/歧义、断句合理",
    },
}

VALID_FIX_TYPES = ("deterministic", "llm_rewrite", "none")
VALID_SEVERITIES = ("critical", "major", "minor")


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class LLMQualityIssue:
    """LLM 维度评审发现的单个问题"""
    segment_index: int  # 对应输入片段下标（全局）
    dimension: str  # 所属维度 key
    severity: str  # critical / major / minor
    description: str  # 问题描述
    suggestion: str  # 修改建议
    fix_type: str  # deterministic / llm_rewrite / none
    target_fields: List[str] = field(default_factory=list)  # 建议修改的字段


@dataclass
class LLMQualityReport:
    """LLM 多维度质感评审报告"""
    dimensions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # dimensions 结构: {"emotion_expression": {"score": 8.0, "comment": "..."}}
    issues: List[LLMQualityIssue] = field(default_factory=list)
    avg_score: float = 0.0  # 所有维度平均分 (0-10)
    failed_batches: int = 0
    total_batches: int = 0
    attempted: bool = False


# ---------------------------------------------------------------------------
# 主类
# ---------------------------------------------------------------------------

class LLMQualityReviewer:
    """
    LLM 多维度质感评审器

    只评不改：对剧本片段进行 8 维度打分并归因 issues，
    由下游（融合报告 / 自动优化）决定如何修订。
    """

    def __init__(self, llm_client: Any = None, *, batch_size: int = DEFAULT_REVIEW_BATCH_SIZE):
        self.llm_client = llm_client
        self.batch_size = max(1, int(batch_size or DEFAULT_REVIEW_BATCH_SIZE))

    async def review(
        self,
        segments: Sequence[Dict[str, Any]],
        *,
        source_text: str = "",
        novel_genre: str = "",
        audio_engine_mode: str = "legacy_stems",
    ) -> LLMQualityReport:
        """
        对剧本片段进行 LLM 多维度质感评审。

        Args:
            segments: 剧本片段列表（dict 格式，含 type/text/speaker/emotion 等）
            source_text: 原始章节文本（用于上下文参考）
            novel_genre: 小说类型
            audio_engine_mode: 音频引擎模式

        Returns:
            LLMQualityReport（失败时返回空报告，不抛异常）
        """
        segment_list = list(segments or [])
        report = LLMQualityReport(attempted=bool(segment_list))

        if not segment_list:
            return report

        batches = list(self._iter_batches(segment_list))
        report.total_batches = len(batches)

        # 各批次的维度分收集（用于最终加权平均）
        all_dimension_scores: Dict[str, List[float]] = {key: [] for key in QUALITY_DIMENSIONS}
        all_dimension_comments: Dict[str, List[str]] = {key: [] for key in QUALITY_DIMENSIONS}
        all_issues: List[LLMQualityIssue] = []

        for batch_index, batch in enumerate(batches, start=1):
            batch_start = sum(len(b) for b in batches[: batch_index - 1])
            batch_end = batch_start + len(batch)

            try:
                batch_result = await self._review_batch(
                    batch,
                    batch_index=batch_index,
                    batch_total=len(batches),
                    batch_start_index=batch_start,
                    source_text=source_text,
                    novel_genre=novel_genre,
                    audio_engine_mode=audio_engine_mode,
                    previous_context=self._build_neighbor_context(
                        segment_list[max(0, batch_start - 2):batch_start]
                    ),
                    next_context=self._build_neighbor_context(
                        segment_list[batch_end:batch_end + 2]
                    ),
                )
                # 收集维度分
                for dim_key, dim_data in batch_result.get("dimensions", {}).items():
                    if dim_key in all_dimension_scores:
                        score = self._safe_score(dim_data.get("score"))
                        if score is not None:
                            all_dimension_scores[dim_key].append(score)
                        comment = str(dim_data.get("comment") or "").strip()
                        if comment:
                            all_dimension_comments[dim_key].append(comment)

                # 收集 issues
                for issue_data in batch_result.get("issues", []):
                    issue = self._parse_issue(issue_data, batch_start_index=batch_start)
                    if issue:
                        all_issues.append(issue)

            except Exception as exc:  # noqa: BLE001 - 评审不能阻断主链路
                error_msg = str(exc).strip() or type(exc).__name__
                logger.warning(
                    "LLM维度评审批次失败，跳过: batch=%s/%s error=%s",
                    batch_index, len(batches), error_msg,
                )
                report.failed_batches += 1

        # 汇总维度分
        report.dimensions = self._aggregate_dimensions(all_dimension_scores, all_dimension_comments)
        report.issues = all_issues
        report.avg_score = self._calculate_avg_score(report.dimensions)

        logger.info(
            "LLM维度评审完成: avg_score=%.1f, issues=%d, failed_batches=%d/%d",
            report.avg_score, len(all_issues), report.failed_batches, report.total_batches,
        )
        return report

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _review_batch(
        self,
        batch: List[Dict[str, Any]],
        *,
        batch_index: int,
        batch_total: int,
        batch_start_index: int,
        source_text: str = "",
        novel_genre: str = "",
        audio_engine_mode: str = "legacy_stems",
        previous_context: str = "",
        next_context: str = "",
    ) -> Dict[str, Any]:
        """评审单批次，返回解析后的 JSON dict。"""
        payload = self._build_batch_payload(batch, start_index=batch_start_index)
        payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        prompt = self._build_review_prompt(
            payload_json,
            batch_index=batch_index,
            batch_total=batch_total,
            source_text=source_text,
            novel_genre=novel_genre,
            audio_engine_mode=audio_engine_mode,
            previous_context=previous_context,
            next_context=next_context,
        )

        max_tokens = self._estimate_max_tokens(payload_json)
        timeout = self._estimate_timeout(max_tokens)
        timeout_seconds = timeout * (1 + REVIEW_FALLBACK_ATTEMPTS) + REVIEW_TIMEOUT_OVERHEAD_SECONDS

        response = await call_audiobook_llm_async(
            self.llm_client,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是有声小说剧本质感评审专家，从多个维度评价剧本的听觉体验质量。"
                        "只评价、不修改。严格输出 JSON。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
            timeout=timeout,
            timeout_seconds=timeout_seconds,
            max_retries=1,
            disable_timeout_auto_tuning=True,
            use_cache=False,
            response_format={"type": "json_object"},
        )

        try:
            data = parse_llm_json_object(response)
        except LLMJsonParseError as exc:
            raise RuntimeError(f"llm_quality_review_json_parse_failed:{exc}") from exc

        return self._normalize_batch_result(data)

    def _build_review_prompt(
        self,
        payload_json: str,
        *,
        batch_index: int,
        batch_total: int,
        source_text: str = "",
        novel_genre: str = "",
        audio_engine_mode: str = "legacy_stems",
        previous_context: str = "",
        next_context: str = "",
    ) -> str:
        """构建维度评审 prompt。"""
        # 维度说明
        dim_lines = []
        for key, meta in QUALITY_DIMENSIONS.items():
            dim_lines.append(f"  - {key}（{meta['label']}）：{meta['criteria']}")
        dimensions_block = "\n".join(dim_lines)

        # 可选上下文块
        source_block = ""
        if source_text:
            excerpt = self._build_source_excerpt(source_text)
            source_block = f"\n原始章节参考（仅用于理解上下文，不作为评审对象）：\n{excerpt}\n"

        genre_block = f"\n小说类型：{novel_genre}\n" if novel_genre else ""

        prev_block = (
            f"\n批次前置衔接锚点（判断连贯性用）：\n{previous_context}\n"
            if previous_context else ""
        )
        next_block = (
            f"\n批次后续预览锚点（判断节奏收束用）：\n{next_context}\n"
            if next_context else ""
        )

        return f"""请对下面的有声小说剧本片段进行多维度质感评审。

批次：{batch_index}/{batch_total}
{genre_block}{source_block}{prev_block}{next_block}
评审维度（每个维度打 0-10 分，并给出一句话评语）：
{dimensions_block}

{FIXED_VOICE_PERFORMANCE_BOUNDARY_PROMPT}

输出要求：
- 只返回一个 JSON 对象，不要输出 markdown 或解释。
- 格式：
{{
  "dimensions": {{
    "semantic_coherence": {{"score": 8.0, "comment": "..."}},
    "narrative_pacing": {{"score": 7.5, "comment": "..."}},
    "atmosphere_imagery": {{"score": 7.0, "comment": "..."}},
    "characterization": {{"score": 8.0, "comment": "..."}},
    "dialogue_naturalness": {{"score": 7.5, "comment": "..."}},
    "emotion_expression": {{"score": 8.0, "comment": "..."}},
    "audio_cue_relevance": {{"score": 7.0, "comment": "..."}},
    "speakability": {{"score": 8.5, "comment": "..."}}
  }},
  "issues": [
    {{
      "segment_index": 3,
      "dimension": "dialogue_naturalness",
      "severity": "major",
      "description": "该段对白过于书面化...",
      "suggestion": "改为更口语的表达...",
      "fix_type": "llm_rewrite",
      "target_fields": ["text"]
    }}
  ]
}}

issues 字段说明：
- segment_index：问题片段在本批次中的下标（从 0 开始）。
- dimension：问题所属维度 key。
- severity：critical / major / minor。
- description：问题描述（简洁明确）。
- suggestion：修改建议。
- fix_type：修复方式——
  - "deterministic"：可通过确定性规则修复（结构调整/停顿/音效cue）
  - "llm_rewrite"：需要 LLM 改写文字或字段
  - "none"：仅提示，无需自动修复
- target_fields：建议修改的字段列表（如 ["text","performance_notes"]），fix_type=none 时可为空。

评审原则：
- 只评价，不修改片段。
- 评分应基于听众的听觉体验，而非文学阅读体验。
- 没有问题时 issues 为空数组。
- 评分标准：0-3 严重不足，4-5 明显缺陷，6-7 基本合格，8-9 优秀，10 完美。
- 不要过于苛刻，也不要全部给高分；根据实际质量区分。

待评审片段 JSON：
{payload_json}
"""

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _iter_batches(self, segments: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """按 batch_size 分批。"""
        batches = []
        for start in range(0, len(segments), self.batch_size):
            batches.append(segments[start:start + self.batch_size])
        return batches

    def _build_batch_payload(
        self, batch: List[Dict[str, Any]], *, start_index: int
    ) -> List[Dict[str, Any]]:
        """构造发送给 LLM 的精简片段 payload。"""
        payload = []
        for i, seg in enumerate(batch):
            item: Dict[str, Any] = {
                "index": i,
                "type": str(seg.get("type") or ""),
                "text": str(seg.get("text") or ""),
                "speaker": str(seg.get("speaker") or ""),
                "emotion": str(seg.get("emotion") or ""),
            }
            # 可选字段（有则附带，确保 JSON 可序列化）
            for opt_key in ("performance_notes", "sound_effects", "music_cue",
                            "pause_before", "pause_after"):
                val = seg.get(opt_key)
                if val:
                    item[opt_key] = self._to_serializable(val)
            payload.append(item)
        return payload

    @staticmethod
    def _to_serializable(val: Any) -> Any:
        """将 dataclass / 嵌套对象转为 JSON 可序列化形式。"""
        if is_dataclass(val) and not isinstance(val, type):
            return asdict(val)
        if isinstance(val, list):
            return [
                asdict(v) if is_dataclass(v) and not isinstance(v, type) else v
                for v in val
            ]
        if isinstance(val, dict):
            return val
        return str(val) if not isinstance(val, (int, float, bool, str)) else val

    def _build_neighbor_context(self, segments: Sequence[Dict[str, Any]]) -> str:
        """构建邻批上下文锚点（精简 JSON）。"""
        if not segments:
            return ""
        payload = []
        for seg in segments:
            payload.append({
                "type": str(seg.get("type") or ""),
                "speaker": str(seg.get("speaker") or ""),
                "text": str(seg.get("text") or "")[:180],
                "emotion": str(seg.get("emotion") or ""),
            })
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def _build_source_excerpt(self, source_text: str) -> str:
        """截取原文摘要。"""
        text = str(source_text or "").strip()
        if len(text) <= SOURCE_CONTEXT_MAX_CHARS:
            return text
        head = SOURCE_CONTEXT_MAX_CHARS // 2
        tail = SOURCE_CONTEXT_MAX_CHARS - head
        return f"{text[:head]}\n……（中段省略）……\n{text[-tail:]}"

    def _estimate_max_tokens(self, payload_json: str) -> int:
        """估算输出 token 上限。"""
        estimated = int(len(payload_json or "") * 0.8) + 1200
        return max(REVIEW_OUTPUT_TOKEN_MIN, min(REVIEW_OUTPUT_TOKEN_MAX, estimated))

    def _estimate_timeout(self, max_tokens: int) -> int:
        """估算请求超时（秒）。"""
        estimated = int(max_tokens / 120) + 30
        return max(REVIEW_TIMEOUT_MIN_SECONDS, min(REVIEW_TIMEOUT_MAX_SECONDS, estimated))

    @staticmethod
    def _safe_score(value: Any) -> Optional[float]:
        """安全转换分数到 0-10。"""
        try:
            score = float(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(10.0, score))

    def _parse_issue(
        self, data: Any, *, batch_start_index: int
    ) -> Optional[LLMQualityIssue]:
        """解析单条 issue，无效则返回 None。"""
        if not isinstance(data, dict):
            return None

        dimension = str(data.get("dimension") or "").strip()
        if dimension not in QUALITY_DIMENSIONS:
            return None

        severity = str(data.get("severity") or "minor").strip().lower()
        if severity not in VALID_SEVERITIES:
            severity = "minor"

        fix_type = str(data.get("fix_type") or "none").strip().lower()
        if fix_type not in VALID_FIX_TYPES:
            fix_type = "none"

        try:
            local_index = int(data.get("segment_index", 0))
        except (TypeError, ValueError):
            local_index = 0
        global_index = batch_start_index + max(0, local_index)

        target_fields = data.get("target_fields")
        if not isinstance(target_fields, list):
            target_fields = []
        target_fields = [str(f).strip() for f in target_fields if str(f).strip()]

        description = str(data.get("description") or "").strip()
        if not description:
            return None

        return LLMQualityIssue(
            segment_index=global_index,
            dimension=dimension,
            severity=severity,
            description=description,
            suggestion=str(data.get("suggestion") or "").strip(),
            fix_type=fix_type,
            target_fields=target_fields,
        )

    def _normalize_batch_result(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """规范化 LLM 返回的批次结果。"""
        dimensions = data.get("dimensions")
        if not isinstance(dimensions, dict):
            dimensions = {}

        issues = data.get("issues")
        if not isinstance(issues, list):
            issues = []

        return {"dimensions": dimensions, "issues": issues}

    def _aggregate_dimensions(
        self,
        scores: Dict[str, List[float]],
        comments: Dict[str, List[str]],
    ) -> Dict[str, Dict[str, Any]]:
        """汇总各批次维度分为最终维度报告。"""
        result: Dict[str, Dict[str, Any]] = {}
        for dim_key in QUALITY_DIMENSIONS:
            dim_scores = scores.get(dim_key, [])
            dim_comments = comments.get(dim_key, [])
            if dim_scores:
                avg = round(sum(dim_scores) / len(dim_scores), 1)
            else:
                avg = 0.0
            result[dim_key] = {
                "score": avg,
                "label": QUALITY_DIMENSIONS[dim_key]["label"],
                "category": QUALITY_DIMENSIONS[dim_key]["category"],
                "comment": " | ".join(dim_comments) if dim_comments else "",
            }
        return result

    @staticmethod
    def _calculate_avg_score(dimensions: Dict[str, Dict[str, Any]]) -> float:
        """计算所有维度的平均分。"""
        valid_scores = [
            d["score"] for d in dimensions.values()
            if isinstance(d.get("score"), (int, float)) and d["score"] > 0
        ]
        if not valid_scores:
            return 0.0
        return round(sum(valid_scores) / len(valid_scores), 1)
