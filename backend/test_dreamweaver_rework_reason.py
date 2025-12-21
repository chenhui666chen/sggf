from __future__ import annotations

from pipeline.state_machine import RunContext, State, step


def test_rework_reason_set_when_audit_fails(monkeypatch):
    import adapters.mock.review as review_mod

    def fail_check(self, bundle):  # noqa: ANN001
        return {"pass": False, "issues": [{"category": "continuity"}]}

    monkeypatch.setattr(review_mod.MockReviewAdapter, "check", fail_check)

    ctx = RunContext(run_id="run_rework", payload={"source_text": "x"})
    for _ in range(20):
        ctx = step(ctx)
        if ctx.state == State.REWORK:
            break

    assert ctx.state == State.REWORK
    assert ctx.payload.get("rework_reason", {}).get("type") == "audit_failed"
    assert ctx.payload.get("rework_reason", {}).get("issues") == [{"category": "continuity"}]
