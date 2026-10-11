"""
P4：可暂停自动推进与熔断

对应《小说流水线整合改进指南》第 9 节：本项目定位不是纯无人值守系统，
出现连续质量问题时应暂停项目、保留现场并等待人工确认，而不是继续生成。

状态持久化于 project_settings.review_meta.circuit_breaker：

{
    "paused": false,
    "reason": "",
    "paused_at_chapter": null,
    "streaks": {"gate_blocking": 0, "digest_failure": 0},
    "history": [{"chapter": 12, "event": "gate_blocking", "detail": "..."}]
}

熔断条件（指南 9.2）：
- 连续章节写前闸门 blocking 未解决（gate_blocking 连续 >= 2）
- 结构化状态提取连续失败（digest_failure 连续 >= 3）
- 伏笔账本无法解析（ledger_corrupt，立即熔断）
- 模型输出为空/重复（empty_output，立即熔断，接口预留）

设计约束：
- 所有函数均为纯函数（只修改传入的 review_meta dict），绝不抛异常；
  review_meta 的落库由调用方负责。
- 熔断只阻断后续的 generate-next-chapter 请求；人工确认恢复后连续计数清零。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, NamedTuple, Optional

logger = logging.getLogger(__name__)

CIRCUIT_BREAKER_KEY = "circuit_breaker"

# 熔断阈值（指南 9.2）
GATE_BLOCKING_THRESHOLD = 2   # 连续章节写前闸门 blocking
DIGEST_FAILURE_THRESHOLD = 3  # 连续写后消化失败

# 信号事件
EVENT_GENERATION_SUCCESS = "generation_success"  # 章节正常生成完成，重置闸门连续计数
EVENT_GATE_BLOCKING = "gate_blocking"            # 写前闸门重规划后仍 blocking
EVENT_DIGEST_SUCCESS = "digest_success"          # 写后消化成功
EVENT_DIGEST_FAILURE = "digest_failure"          # 写后消化失败/无产出
EVENT_LEDGER_CORRUPT = "ledger_corrupt"          # 伏笔账本无法解析
EVENT_EMPTY_OUTPUT = "empty_output"              # 模型输出为空/重复
EVENT_MANUAL_RESUME = "manual_resume"            # 人工确认恢复

_MAX_HISTORY = 20

_PAUSE_EVENTS = {EVENT_LEDGER_CORRUPT, EVENT_EMPTY_OUTPUT}

_PAUSE_REASONS = {
    EVENT_LEDGER_CORRUPT: "伏笔账本无法解析或状态冲突",
    EVENT_EMPTY_OUTPUT: "模型输出为空或重复",
}

# 与上一章比对：过短文本不判重复，避免短章误伤
_REPEAT_MIN_CHARS = 400
_REPEAT_RATIO_THRESHOLD = 0.92
_PLACEHOLDER_MARKERS = ("（此处为生成的章节内容）",)

# 章节正文合法收尾字符（句末标点/引号/括号收口）；结尾不在此集合视为疑似截断（F.6 TruncatedOutput）
_CHAPTER_ENDING_CHARS = set('。！？…！?~"\'\'』」》）).')
# 正文最小字符数：非空但短于此值视为过短产出（F.6 EmptyOrShortOutput）；与截断启发式下限一致
_MIN_CHAPTER_CHARS = 200

# F.6 稳定输出拒绝码（output_reject_reason）；前端 OUTPUT_REJECT_REASON_LABELS 已预置对应中文标签
REASON_EMPTY = "EmptyOutput"
REASON_PLACEHOLDER = "PlaceholderOutput"
REASON_SHORT = "EmptyOrShortOutput"
REASON_REPEAT = "RepeatedOutput"
REASON_TRUNCATED = "TruncatedOutput"


def _default_state() -> Dict[str, Any]:
    return {
        "paused": False,
        "reason": "",
        "paused_at_chapter": None,
        "streaks": {"gate_blocking": 0, "digest_failure": 0},
        "history": [],
    }


def get_breaker_state(review_meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """读取 review_meta 中的熔断状态；缺失或损坏时初始化默认结构。"""
    if not isinstance(review_meta, dict):
        return _default_state()
    state = review_meta.get(CIRCUIT_BREAKER_KEY)
    if not isinstance(state, dict):
        state = _default_state()
        review_meta[CIRCUIT_BREAKER_KEY] = state
    defaults = _default_state()
    for key, value in defaults.items():
        state.setdefault(key, value)
    if not isinstance(state.get("streaks"), dict):
        state["streaks"] = dict(defaults["streaks"])
    if not isinstance(state.get("history"), list):
        state["history"] = []
    return state


def _append_history(state: Dict[str, Any], chapter_number: Optional[int], event: str, detail: str = "") -> None:
    history = state.setdefault("history", [])
    history.append({
        "chapter": chapter_number,
        "event": event,
        "detail": (detail or "")[:200],
    })
    if len(history) > _MAX_HISTORY:
        del history[: len(history) - _MAX_HISTORY]


def _pause(state: Dict[str, Any], *, reason: str, chapter_number: Optional[int]) -> None:
    if state.get("paused"):
        return
    state["paused"] = True
    state["reason"] = reason
    state["paused_at_chapter"] = chapter_number
    logger.warning(f"   🔌 项目自动推进熔断：{reason}（第{chapter_number}章）")


def record_generation_signal(
    review_meta: Optional[Dict[str, Any]],
    *,
    chapter_number: Optional[int],
    event: str,
    detail: str = "",
) -> Dict[str, Any]:
    """记录一次生成链路信号，达到阈值时触发熔断。绝不抛异常。

    调用方在信号记录完成后负责把 review_meta 落库。
    """
    try:
        state = get_breaker_state(review_meta if isinstance(review_meta, dict) else None)
        streaks = state["streaks"]
        if event == EVENT_GATE_BLOCKING:
            streaks["gate_blocking"] = int(streaks.get("gate_blocking") or 0) + 1
            if streaks["gate_blocking"] >= GATE_BLOCKING_THRESHOLD:
                _pause(
                    state,
                    reason=f"连续 {streaks['gate_blocking']} 章写前闸门存在未解决 blocking 冲突",
                    chapter_number=chapter_number,
                )
        elif event == EVENT_GENERATION_SUCCESS:
            streaks["gate_blocking"] = 0
        elif event == EVENT_DIGEST_FAILURE:
            streaks["digest_failure"] = int(streaks.get("digest_failure") or 0) + 1
            if streaks["digest_failure"] >= DIGEST_FAILURE_THRESHOLD:
                _pause(
                    state,
                    reason=f"连续 {streaks['digest_failure']} 章结构化状态提取失败",
                    chapter_number=chapter_number,
                )
        elif event == EVENT_DIGEST_SUCCESS:
            streaks["digest_failure"] = 0
        elif event in _PAUSE_EVENTS:
            _pause(
                state,
                reason=_PAUSE_REASONS.get(event, event),
                chapter_number=chapter_number,
            )
        _append_history(state, chapter_number, event, detail)
        return state
    except Exception as signal_error:
        logger.warning(f"   ⚠️ 熔断信号记录失败（不影响主流程）: {signal_error}")
        return _default_state()


def is_paused(review_meta: Optional[Dict[str, Any]]) -> bool:
    """项目是否处于熔断暂停状态。"""
    try:
        if not isinstance(review_meta, dict):
            return False
        state = review_meta.get(CIRCUIT_BREAKER_KEY)
        return bool(isinstance(state, dict) and state.get("paused"))
    except Exception:
        return False


def get_pause_info(review_meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """返回暂停摘要（供接口 409 响应携带）。"""
    fallback = {"paused": False, "reason": "", "paused_at_chapter": None}
    try:
        if not isinstance(review_meta, dict):
            return fallback
        state = review_meta.get(CIRCUIT_BREAKER_KEY)
        if not isinstance(state, dict):
            return fallback
        return {
            "paused": bool(state.get("paused")),
            "reason": str(state.get("reason") or ""),
            "paused_at_chapter": state.get("paused_at_chapter"),
        }
    except Exception:
        return fallback


PAUSE_MESSAGE = "项目自动推进已暂停，请确认暂停原因后再继续生成"


def build_pause_detail(review_meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """构造熔断 409 响应体。

    message 只写用户可读下一步，不得出现 resume_after_confirmation 等接口参数名；
    具体暂停原因与章节由 circuit_breaker 结构交给前端确认弹窗渲染。
    """
    return {
        "message": PAUSE_MESSAGE,
        "circuit_breaker": get_pause_info(review_meta),
    }


def confirm_and_resume(
    review_meta: Optional[Dict[str, Any]],
    *,
    chapter_number: Optional[int] = None,
) -> Dict[str, Any]:
    """人工确认后清除暂停状态：连续计数清零，history 保留以便追溯。"""
    try:
        state = get_breaker_state(review_meta if isinstance(review_meta, dict) else None)
        state["paused"] = False
        state["reason"] = ""
        state["streaks"] = {"gate_blocking": 0, "digest_failure": 0}
        _append_history(state, chapter_number, EVENT_MANUAL_RESUME, "人工确认恢复")
        return state
    except Exception as resume_error:
        logger.warning(f"   ⚠️ 熔断恢复处理失败: {resume_error}")
        return _default_state()

def _normalize_repeat_text(text: Any) -> str:
    return "".join(str(text or "").split())


def _char_ngram_overlap(left: str, right: str, n: int = 8) -> float:
    if len(left) < n or len(right) < n:
        return 1.0 if left == right and left else 0.0
    left_grams = {left[i:i + n] for i in range(0, len(left) - n + 1, n)}
    right_grams = {right[i:i + n] for i in range(0, len(right) - n + 1, n)}
    if not left_grams or not right_grams:
        return 0.0
    inter = len(left_grams & right_grams)
    union = len(left_grams | right_grams)
    return inter / union if union else 0.0


class ChapterOutputVerdict(NamedTuple):
    """统一输出验收结果（F.6）：accepted=是否可采用；code=稳定拒绝码（accepted 时为空）；
    detail=中文详情（供熔断信号/日志复用，accepted 时为空）。"""

    accepted: bool
    code: str
    detail: str


def is_likely_truncated(text: Any) -> bool:
    """启发式检测正文是否疑似截断：以非句末标点收尾（如'离她二十'）视为截断（F.6 TruncatedOutput）。

    仅对 >=_MIN_CHAPTER_CHARS 的文本判定；空稿/过短稿走 EmptyOutput/EmptyOrShortOutput，不在此管辖。
    routes_chapter._is_likely_truncated_chapter 委托本函数，保证截断口径单一真源。
    """
    s = str(text or "")
    if len(s) < _MIN_CHAPTER_CHARS:
        return False
    stripped = s.rstrip()
    if not stripped:
        return False
    return stripped[-1] not in _CHAPTER_ENDING_CHARS


def evaluate_chapter_output(draft: Any, previous_content: Any = "") -> ChapterOutputVerdict:
    """统一输出验收纯函数（F.6 唯一真源）：按 空→占位→过短→重复→截断 顺序判定。

    主正文/同步 fallback/content_retry/结构重生成/改稿全部改调本函数，消除此前四处分裂口径
    （主正文只查空/占位/重复、结构重生成只查 len>200、改稿硬编码 accepted、截断检测只驱动重试
    不进验收）。返回稳定拒绝码 code 供 output_reject_reason、中文 detail 供熔断信号；accepted 时二者为空。
    """
    text = str(draft or "").strip()
    if not text:
        return ChapterOutputVerdict(False, REASON_EMPTY, "正文输出为空")
    if any(marker in text for marker in _PLACEHOLDER_MARKERS):
        return ChapterOutputVerdict(False, REASON_PLACEHOLDER, "正文输出为占位模板")
    if len(text) < _MIN_CHAPTER_CHARS:
        return ChapterOutputVerdict(
            False, REASON_SHORT, f"正文过短（{len(text)}<{_MIN_CHAPTER_CHARS} 字符）"
        )
    previous = str(previous_content or "").strip()
    if len(text) >= _REPEAT_MIN_CHARS and len(previous) >= _REPEAT_MIN_CHARS:
        left = _normalize_repeat_text(text)
        right = _normalize_repeat_text(previous)
        if left and right:
            if left == right:
                return ChapterOutputVerdict(False, REASON_REPEAT, "正文与上一章完全重复")
            overlap = _char_ngram_overlap(left, right)
            if overlap >= _REPEAT_RATIO_THRESHOLD:
                return ChapterOutputVerdict(
                    False, REASON_REPEAT, f"正文与上一章高度重复（overlap={overlap:.2f}）"
                )
    if is_likely_truncated(text):
        return ChapterOutputVerdict(
            False, REASON_TRUNCATED, f"正文疑似截断（结尾…{text[-20:]}）"
        )
    return ChapterOutputVerdict(True, "", "")


def detect_invalid_chapter_output(draft: Any, previous_content: Any = "") -> Optional[str]:
    """兼容包装：返回中文拒绝详情或 None（None=可接受）。语义已升级为含过短/截断。

    新代码应直接用 evaluate_chapter_output 取 (accepted, code, detail)；本函数保留供既有熔断信号
    detail 与历史调用方复用，委托 evaluate_chapter_output 保证验收口径单一真源、不再各路径分裂。
    """
    return evaluate_chapter_output(draft, previous_content).detail or None


class FinalVersionResolution(NamedTuple):
    """最终保存前验收 + 回退结果（F.6 第五条路径）：version=采用版本；verdict=该版本验收；
    source=来源（final/best/draft，或 none=三者全无效须终止保存）。"""

    version: str
    verdict: ChapterOutputVerdict
    source: str


def resolve_final_version(
    final_version: Any,
    best_version: Any,
    chapter_draft: Any,
    previous_content: Any = "",
) -> FinalVersionResolution:
    """最终保存前统一验收 + 回退优先级（F.6 第五条路径闭环，第十三轮 P1-2）。

    clean_final_output 可能把终稿清空、同步 optimize_chapter fallback 返回未验收稿，二者都绕过
    改稿循环验收直奔 project_settings.final_version 与 chapters.content 落库。本函数在保存前按
    final→best→draft 优先级返回首个通过 evaluate_chapter_output 的版本；三者全无效时返回
    source="none" + 末位候选的 rejected verdict，由调用方终止保存并触发 empty_output 熔断，
    杜绝空/过短/占位/重复/截断稿落库。best/draft 为改稿循环/主正文已验收版本，作可靠回退兜底。
    """
    last_verdict = ChapterOutputVerdict(False, REASON_EMPTY, "正文输出为空")
    for candidate, source in (
        (final_version, "final"),
        (best_version, "best"),
        (chapter_draft, "draft"),
    ):
        verdict = evaluate_chapter_output(candidate, previous_content)
        last_verdict = verdict
        if verdict.accepted:
            return FinalVersionResolution(str(candidate or ""), verdict, source)
    return FinalVersionResolution(str(chapter_draft or ""), last_verdict, "none")
