"""阶段 4 timeline 模式闸门测试（指导文档 §8.3 验证状态）。

覆盖验收：

- natural 恒开放；
- bounded_timeline 与 strict_timeline 分别依据阶段 0 的版本化验证结论开放；
- 任一模式未通过时只关闭该模式，不连带关闭已通过的模式；
- 缺字段不得静默当作通过。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_engine.timeline_gate import (  # noqa: E402
    TIMELINE_GATE_CONTRACT_VERSION,
    resolve_timeline_gate,
)


def _eligibility(strict=True, bounded=True, **extra):
    payload = {
        "strict_timeline_eligible": strict,
        "strict_reasons": [] if strict else ["start_error_p95_out_of_band"],
        "bounded_timeline_eligible": bounded,
        "bounded_reasons": [] if bounded else ["duration_error_p95_out_of_band"],
    }
    payload.update(extra)
    return payload


class TestTimelineGate:
    def test_natural_always_allowed(self):
        gate = resolve_timeline_gate({})
        assert gate.natural_allowed is True

    def test_both_modes_open_when_eligible(self):
        gate = resolve_timeline_gate(_eligibility())
        assert gate.bounded_allowed is True
        assert gate.strict_allowed is True
        assert gate.allowed_modes == ("natural", "bounded", "strict")

    def test_modes_are_independent_strict_fail_only(self):
        gate = resolve_timeline_gate(_eligibility(strict=False))
        assert gate.bounded_allowed is True
        assert gate.strict_allowed is False
        assert gate.allowed_modes == ("natural", "bounded")
        assert gate.strict_reasons == ("start_error_p95_out_of_band",)

    def test_modes_are_independent_bounded_fail_only(self):
        gate = resolve_timeline_gate(_eligibility(bounded=False))
        assert gate.bounded_allowed is False
        assert gate.strict_allowed is True
        assert gate.allowed_modes == ("natural", "strict")

    def test_missing_fields_do_not_silently_pass(self):
        gate = resolve_timeline_gate({"aggregate": {}})
        assert gate.bounded_allowed is False
        assert gate.strict_allowed is False
        assert gate.allowed_modes == ("natural",)

    def test_non_truthy_flags_do_not_pass(self):
        gate = resolve_timeline_gate(
            {"strict_timeline_eligible": None, "bounded_timeline_eligible": ""}
        )
        assert gate.bounded_allowed is False
        assert gate.strict_allowed is False

    def test_gate_contract_version_is_versioned(self):
        assert TIMELINE_GATE_CONTRACT_VERSION == "1.0.0"
