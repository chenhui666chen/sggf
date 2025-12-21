from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if PROJECT_ROOT in sys.path:
    sys.path.remove(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from agents import auditor, dreamweaver, editor, painter, planner, storyboarder
from pipeline import autoqc


class State(Enum):
    INIT = auto()
    SCRIPT = auto()
    STORYBOARD = auto()
    KEYFRAMES = auto()
    MIDFRAMES = auto()
    VIDEO = auto()
    EDIT = auto()
    REVIEW = auto()
    DONE = auto()
    REWORK = auto()
    FAILED = auto()


@dataclass
class RunContext:
    run_id: str
    state: State = State.INIT
    retry: Dict[State, int] = field(default_factory=dict)
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 让所有节点都能稳定取到 run_id（历史代码部分读取 ctx.payload["run_id"]）
        self.payload.setdefault("run_id", self.run_id)

    def bump_retry(self, state: State, limit: int = 2) -> bool:
        self.retry[state] = self.retry.get(state, 0) + 1
        return self.retry[state] <= limit


def step(ctx: RunContext) -> RunContext:
    """最小可运行状态机：逐步调用 mock agent，跑通主链路。"""
    try:
        if ctx.state == State.INIT:
            planner.run(ctx)
            ctx.state = State.SCRIPT
        elif ctx.state == State.SCRIPT:
            storyboarder.run(ctx)
            ctx.state = State.STORYBOARD
        elif ctx.state == State.STORYBOARD:
            painter.run_keyframes(ctx)
            ctx.state = State.KEYFRAMES
        elif ctx.state == State.KEYFRAMES:
            painter.run_midframes(ctx)
            ctx.state = State.MIDFRAMES
        elif ctx.state == State.MIDFRAMES:
            dreamweaver.run_video(ctx)  # 织梦映心
            ctx.state = State.VIDEO
        elif ctx.state == State.VIDEO:
            editor.run(ctx)
            ctx.state = State.EDIT
        elif ctx.state == State.EDIT:
            ctx.state = State.REVIEW
        elif ctx.state == State.REVIEW:
            audit_result = auditor.run(ctx)
            qc_result = autoqc.run(ctx.payload)
            ctx.payload["autoqc"] = qc_result

            if audit_result.get("pass") and qc_result.get("pass"):
                ctx.state = State.DONE
            else:
                if not qc_result.get("pass"):
                    ctx.payload["rework_reason"] = {
                        "type": "autoqc_failed",
                        "failures": qc_result.get("failures", []),
                        "route": qc_result.get("route"),
                    }
                    if isinstance(qc_result.get("route"), dict):
                        ctx.payload["rework_route"] = qc_result["route"]
                else:
                    ctx.payload["rework_reason"] = {
                        "type": "audit_failed",
                        "issues": audit_result.get("issues", []),
                    }
                    ctx.payload["rework_route"] = {
                        "target_state": "SCRIPT",
                        "action": "review_fix",
                        "reason": "audit_failed",
                    }
                ctx.state = State.REWORK
        elif ctx.state == State.REWORK:
            if ctx.bump_retry(State.REWORK):
                route = ctx.payload.get("rework_route")
                target = None
                if isinstance(route, dict) and isinstance(route.get("target_state"), str):
                    target = route["target_state"]
                try:
                    ctx.state = State[target] if target else State.STORYBOARD
                except Exception:  # noqa: BLE001
                    ctx.state = State.STORYBOARD
            else:
                ctx.state = State.FAILED
        else:
            ctx.state = ctx.state
    except Exception as exc:  # noqa: BLE001
        if ctx.bump_retry(ctx.state):
            return ctx
        ctx.state = State.FAILED
        ctx.payload["error"] = str(exc)
    return ctx


def run_until_done(ctx: RunContext, max_steps: int = 50) -> RunContext:
    for _ in range(max_steps):
        if ctx.state in (State.DONE, State.FAILED):
            break
        ctx = step(ctx)
    return ctx


def progress_percent(state: State) -> int:
    """
    将状态机阶段映射为粗粒度进度百分比（0-100）。
    注意：REWORK 代表返工，进度可能回退；用于 UI 展示而非严格度量。
    """
    mapping = {
        State.INIT: 0,
        State.SCRIPT: 10,
        State.STORYBOARD: 25,
        State.KEYFRAMES: 45,
        State.MIDFRAMES: 60,
        State.VIDEO: 75,
        State.EDIT: 90,
        State.REVIEW: 95,
        State.REWORK: 30,
        State.DONE: 100,
        State.FAILED: 0,
    }
    return mapping.get(state, 0)


def stage_label(state: State) -> str:
    """用于 UI 的阶段短标签。"""
    mapping = {
        State.INIT: "init",
        State.SCRIPT: "script",
        State.STORYBOARD: "storyboard",
        State.KEYFRAMES: "keyframes",
        State.MIDFRAMES: "midframes",
        State.VIDEO: "video",
        State.EDIT: "edit",
        State.REVIEW: "review",
        State.REWORK: "rework",
        State.DONE: "done",
        State.FAILED: "failed",
    }
    return mapping.get(state, state.name.lower())
