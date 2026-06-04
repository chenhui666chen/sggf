from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from app.services.audiobook.llm_client import call_audiobook_llm_async
from app.services.audiobook.llm_json import LLMJsonParseError, parse_llm_json_array

from ._dataclasses import ScriptSegment
from ._segment_validation import NARRATOR, build_script_segments

logger = logging.getLogger(__name__)

DEFAULT_REVIEW_BATCH_SIZE = 8
DEFAULT_MIN_TEXT_COVERAGE = 0.92
REVIEW_SOURCE_CONTEXT_MAX_CHARS = 1200
REVIEW_OUTPUT_TOKEN_MIN = 1800
REVIEW_OUTPUT_TOKEN_MAX = 7000
REVIEW_TIMEOUT_MIN_SECONDS = 35
REVIEW_TIMEOUT_MAX_SECONDS = 75
REVIEW_FALLBACK_ATTEMPTS = 1
REVIEW_TIMEOUT_OVERHEAD_SECONDS = 15


@dataclass
class ScriptLLMReviewResult:
    segments: List[ScriptSegment]
    report: Dict[str, Any]


def summarize_script_review_report(report: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not report:
        return None

    return {
        "attempted": bool(report.get("attempted")),
        "applied": bool(report.get("applied")),
        "reason": str(report.get("reason") or ""),
        "original_count": int(report.get("original_count") or 0),
        "reviewed_count": int(report.get("reviewed_count") or 0),
        "coverage_ratio": _round_ratio(report.get("coverage_ratio")),
        "changed_batches": int(report.get("changed_batches") or 0),
        "failed_batches": int(report.get("failed_batches") or 0),
    }


async def review_script_segments_with_llm(
    llm_client: Any,
    script_segments: Sequence[ScriptSegment],
    *,
    source_text: str = "",
    batch_size: int = DEFAULT_REVIEW_BATCH_SIZE,
    min_text_coverage: float = DEFAULT_MIN_TEXT_COVERAGE,
) -> ScriptLLMReviewResult:
    original_segments = list(script_segments or [])
    report: Dict[str, Any] = {
        "attempted": bool(original_segments),
        "applied": False,
        "reason": "",
        "original_count": len(original_segments),
        "reviewed_count": len(original_segments),
        "coverage_ratio": 1.0,
        "changed_batches": 0,
        "failed_batches": 0,
        "batches": [],
    }
    if not original_segments:
        report["reason"] = "empty_script"
        return ScriptLLMReviewResult(segments=original_segments, report=report)

    reviewed_segments: List[ScriptSegment] = []
    changed_batches = 0
    failed_batches = 0

    batches = list(_iter_batches(original_segments, max(1, int(batch_size or DEFAULT_REVIEW_BATCH_SIZE))))
    for batch_index, batch in enumerate(batches, start=1):
        batch_report: Dict[str, Any] = {
            "batch_index": batch_index,
            "batch_total": len(batches),
            "original_count": len(batch),
            "applied": False,
            "coverage_ratio": 0.0,
            "error": "",
        }
        try:
            reviewed_batch = await _review_batch(
                llm_client,
                batch,
                batch_index=batch_index,
                batch_total=len(batches),
                source_text=source_text,
            )
            coverage_ratio = calculate_text_coverage(batch, reviewed_batch)
            batch_report["coverage_ratio"] = coverage_ratio

            if coverage_ratio < min_text_coverage:
                batch_report["error"] = (
                    f"text_coverage_below_threshold:{coverage_ratio:.3f}<{min_text_coverage:.3f}"
                )
                reviewed_segments.extend(batch)
                failed_batches += 1
            else:
                reviewed_segments.extend(reviewed_batch)
                batch_report["applied"] = _segments_changed(batch, reviewed_batch)
                if batch_report["applied"]:
                    changed_batches += 1
        except Exception as exc:  # noqa: BLE001 - 审稿不能阻断主生成链路
            error_summary = _format_exception_summary(exc)
            logger.warning("LLM脚本审稿批次失败，保留原片段: batch=%s error=%s", batch_index, error_summary)
            batch_report["error"] = error_summary
            reviewed_segments.extend(batch)
            failed_batches += 1

        report["batches"].append(batch_report)

    coverage_ratio = calculate_text_coverage(original_segments, reviewed_segments)
    report.update(
        {
            "reviewed_count": len(reviewed_segments),
            "coverage_ratio": coverage_ratio,
            "changed_batches": changed_batches,
            "failed_batches": failed_batches,
        }
    )

    if coverage_ratio < min_text_coverage:
        report["applied"] = False
        report["reason"] = (
            f"global_text_coverage_below_threshold:{coverage_ratio:.3f}<{min_text_coverage:.3f}"
        )
        return ScriptLLMReviewResult(segments=original_segments, report=report)

    report["applied"] = changed_batches > 0
    report["reason"] = "review_applied" if report["applied"] else "no_changes"
    return ScriptLLMReviewResult(segments=reviewed_segments, report=report)


async def _review_batch(
    llm_client: Any,
    batch: Sequence[ScriptSegment],
    *,
    batch_index: int,
    batch_total: int,
    source_text: str = "",
) -> List[ScriptSegment]:
    payload = [_segment_to_payload(segment, index=index) for index, segment in enumerate(batch)]
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    prompt = _build_review_prompt(
        payload_json,
        batch_index=batch_index,
        batch_total=batch_total,
        source_text=source_text,
    )
    max_tokens = _estimate_review_max_tokens(payload_json)
    timeout = _estimate_review_timeout(max_tokens)
    timeout_seconds = _estimate_review_total_timeout(timeout)
    response = await call_audiobook_llm_async(
        llm_client,
        messages=[
            {
                "role": "system",
                "content": "你是有声小说剧本审稿器，只做结构纠错，严格输出 JSON。",
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.2,
        timeout=timeout,
        timeout_seconds=timeout_seconds,
        max_retries=1,
        disable_timeout_auto_tuning=True,
        use_cache=False,
        response_format={"type": "json_object"},
    )

    try:
        reviewed_data = parse_llm_json_array(response)
    except LLMJsonParseError as exc:
        raise RuntimeError(f"script_review_json_parse_failed:{exc}") from exc

    normalized_data = [_normalize_review_item(item) for item in reviewed_data]
    reviewed_segments = build_script_segments(normalized_data)
    if not reviewed_segments:
        raise RuntimeError("script_review_returned_no_valid_segments")
    return reviewed_segments


def _build_review_prompt(
    payload_json: str,
    *,
    batch_index: int,
    batch_total: int,
    source_text: str = "",
) -> str:
    source_block = ""
    if source_text:
        source_block = (
            "\n原始章节参考（只用于判断上下文，不要照抄未出现在输入片段中的文本）：\n"
            f"{source_text[:REVIEW_SOURCE_CONTEXT_MAX_CHARS]}\n"
        )

    return f"""请审阅下面的有声小说剧本片段，修正会影响 TTS 朗读质量的结构问题。

批次：{batch_index}/{batch_total}
{source_block}
输出要求：
- 只返回 JSON 对象，格式为 {{"segments": [ ... ]}}。
- 每个 segment 尽量保留输入字段：type、text、speaker、emotion、performance_notes、pause_before、pause_after、voice_params、instruct_emotion、instruct_scene、instruct_role、instruct_identity、sound_effects、music_cue、sound_effects_simple、music_cue_simple、original_text、adaptation_reason。
- 不要输出 markdown，不要解释。

只允许做以下修正：
1. text 里如果是朗读方式说明而不是真正台词/旁白，优先用 original_text 修正。
2. dialogue 片段如果 speaker 是旁白或空，且 text 实际是旁白，则改为 narration；不要强行编造说话人。
3. 对话中残留“他说/她问/某某道”等归因标签时，可以删掉归因标签；如果归因里包含动作/场景信息，拆成 narration 片段。
4. 角色台词中混入明显旁白时，拆出 narration；旁白中混入明显引号台词时，拆出 dialogue。
5. narration 超过 140 字，或 dialogue/monologue 超过 120 字时，按播讲拍点拆分；强动作、强情绪、转场、回忆切入必须单独成段。
6. 连续动作按“发动 -> 受击 -> 后果 -> 反应”拆；逃亡/追逐/战斗场景每段只承载一个主要动作。
7. 拆分时 sound_effects / music_cue 只保留在最相关的动作段或首段，不要在拆出的每段重复同一音效/配乐。
8. performance_notes 和 instruct_* 只能描述声音、语气、情绪、节奏，不要描述身体动作。

硬性约束：
- 不得丢失 text 内容。拆分或合并后，输入 text 中的语义内容必须仍然出现在输出中。
- 不要改写作者措辞、叙事人称和时态，除非是在删除归因标签或把动作归为旁白。
- 不要删除 sound_effects / music_cue / voice_params 等已有配置；如果无法判断，原样保留。
- 不要添加未在输入中出现的新剧情。

待审稿片段 JSON：
{payload_json}
"""


def _estimate_review_max_tokens(payload_json: str) -> int:
    """审稿只做结构纠错，输出预算应随输入增长但不能拖慢主链路。"""
    estimated = int(len(payload_json or "") * 1.15) + 900
    return max(REVIEW_OUTPUT_TOKEN_MIN, min(REVIEW_OUTPUT_TOKEN_MAX, estimated))


def _estimate_review_timeout(max_tokens: int) -> int:
    """LLM 审稿是非阻断增强，失败应快速降级保留原片段。"""
    estimated = int(max_tokens / 140) + 25
    return max(REVIEW_TIMEOUT_MIN_SECONDS, min(REVIEW_TIMEOUT_MAX_SECONDS, estimated))


def _estimate_review_total_timeout(request_timeout: int) -> int:
    request_timeout = max(1, int(request_timeout or REVIEW_TIMEOUT_MIN_SECONDS))
    return request_timeout * (1 + REVIEW_FALLBACK_ATTEMPTS) + REVIEW_TIMEOUT_OVERHEAD_SECONDS


def _format_exception_summary(exc: BaseException) -> str:
    message = str(exc).strip()
    if message:
        return message
    return type(exc).__name__


def _segment_to_payload(segment: ScriptSegment, *, index: int) -> Dict[str, Any]:
    if is_dataclass(segment):
        payload = asdict(segment)
    elif isinstance(segment, dict):
        payload = dict(segment)
    else:
        payload = dict(getattr(segment, "__dict__", {}) or {})
    payload["index"] = index
    return payload


def _normalize_review_item(item: Any) -> Any:
    if not isinstance(item, dict):
        return item

    normalized = dict(item)
    normalized.pop("index", None)

    speaker = str(normalized.get("speaker") or "").strip()
    if speaker.upper() == "NARRATOR":
        normalized["speaker"] = NARRATOR

    if not normalized.get("performance_notes") and normalized.get("instruct"):
        normalized["performance_notes"] = normalized.get("instruct")

    if not normalized.get("type"):
        normalized["type"] = "narration" if normalized.get("speaker") in ("", NARRATOR) else "dialogue"

    return normalized


def calculate_text_coverage(
    original_segments: Iterable[ScriptSegment],
    reviewed_segments: Iterable[ScriptSegment],
) -> float:
    original_units = _text_units(_join_segment_text(original_segments))
    if not original_units:
        return 1.0

    reviewed_units = _text_units(_join_segment_text(reviewed_segments))
    if not reviewed_units:
        return 0.0

    original_counter = Counter(original_units)
    reviewed_counter = Counter(reviewed_units)
    matched = sum(min(count, reviewed_counter.get(unit, 0)) for unit, count in original_counter.items())
    return matched / sum(original_counter.values())


def _join_segment_text(segments: Iterable[ScriptSegment]) -> str:
    return "".join(str(getattr(segment, "text", "") or "") for segment in segments or [])


def _text_units(text: str) -> List[str]:
    return [
        match.group(0).lower()
        for match in re.finditer(r"[\u3400-\u4dbf\u4e00-\u9fff]|[A-Za-z0-9]+", str(text or ""))
        if match.group(0) != "_"
    ]


def _round_ratio(value: Any) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return 0.0


def _segments_changed(original: Sequence[ScriptSegment], reviewed: Sequence[ScriptSegment]) -> bool:
    if len(original) != len(reviewed):
        return True
    for left, right in zip(original, reviewed):
        if (
            getattr(left, "type", "") != getattr(right, "type", "")
            or getattr(left, "speaker", "") != getattr(right, "speaker", "")
            or getattr(left, "text", "") != getattr(right, "text", "")
            or getattr(left, "performance_notes", "") != getattr(right, "performance_notes", "")
            or getattr(left, "instruct_emotion", "") != getattr(right, "instruct_emotion", "")
        ):
            return True
    return False


def _iter_batches(items: Sequence[ScriptSegment], batch_size: int) -> Iterable[List[ScriptSegment]]:
    for start in range(0, len(items), batch_size):
        yield list(items[start:start + batch_size])
