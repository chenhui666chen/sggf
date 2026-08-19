"""timeline 模式闸门（指导文档 §8.3 验证状态）。

natural 恒开放；bounded_timeline 与 strict_timeline 分别依据阶段 0 的
版本化验证结论（eligibility summary）独立开放：任一模式未通过时只关闭
该模式，不连带关闭已通过的模式。缺字段不得静默当作通过。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Tuple

TIMELINE_GATE_CONTRACT_VERSION = "1.0.0"


@dataclass(frozen=True)
class TimelineGateDecision:
    natural_allowed: bool
    bounded_allowed: bool
    strict_allowed: bool
    bounded_reasons: Tuple[str, ...]
    strict_reasons: Tuple[str, ...]

    @property
    def allowed_modes(self) -> Tuple[str, ...]:
        modes = ["natural"] if self.natural_allowed else []
        if self.bounded_allowed:
            modes.append("bounded")
        if self.strict_allowed:
            modes.append("strict")
        return tuple(modes)


def resolve_timeline_gate(eligibility: Mapping[str, Any]) -> TimelineGateDecision:
    """从阶段 0 eligibility 结论解析模式闸门；布尔必须为 True 才开放。"""
    strict_reasons = tuple(str(reason) for reason in eligibility.get("strict_reasons") or ())
    bounded_reasons = tuple(
        str(reason) for reason in eligibility.get("bounded_reasons") or ()
    )
    return TimelineGateDecision(
        natural_allowed=True,
        bounded_allowed=eligibility.get("bounded_timeline_eligible") is True,
        strict_allowed=eligibility.get("strict_timeline_eligible") is True,
        bounded_reasons=bounded_reasons,
        strict_reasons=strict_reasons,
    )


__all__ = [
    "TIMELINE_GATE_CONTRACT_VERSION",
    "TimelineGateDecision",
    "resolve_timeline_gate",
]
