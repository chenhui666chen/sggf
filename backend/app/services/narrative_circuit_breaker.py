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
from typing import Any, Dict, Optional

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


def detect_invalid_chapter_output(draft: Any, previous_content: Any = "") -> Optional[str]:
    text = str(draft or "").strip()
    if not text:
        return "正文输出为空"
    if any(marker in text for marker in _PLACEHOLDER_MARKERS):
        return "正文输出为占位模板"
    previous = str(previous_content or "").strip()
    if len(text) < _REPEAT_MIN_CHARS or len(previous) < _REPEAT_MIN_CHARS:
        return None
    left = _normalize_repeat_text(text)
    right = _normalize_repeat_text(previous)
    if not left or not right:
        return None
    if left == right:
        return "正文与上一章完全重复"
    overlap = _char_ngram_overlap(left, right)
    if overlap >= _REPEAT_RATIO_THRESHOLD:
        return f"正文与上一章高度重复（overlap={overlap:.2f}）"
    return None
