from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, Iterator

PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if PROJECT_ROOT in sys.path:
    sys.path.remove(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from agents import asset_library, auditor, dreamweaver, editor, painter, planner, scripter, storyboarder
from pipeline import autoqc
from pipeline.smart_tuning import apply_smart_tuning
from pipeline.restart_reset import apply_restart_reset as _apply_restart_reset_impl


class State(Enum):
    INIT = auto()
    SCRIPT = auto()
    WAITING_SCRIPT_APPROVAL = auto()
    STORYBOARD = auto()
    ASSET_LIBRARY = auto()
    WAITING_APPROVAL = auto()
    KEYFRAMES = auto()
    MIDFRAMES = auto()
    VIDEO = auto()
    WAITING_VIDEO_CONFIRMATION = auto()
    EDIT = auto()
    REVIEW = auto()
    DONE = auto()
    REWORK = auto()
    FAILED = auto()


def _ensure_telemetry(payload: Dict[str, Any]) -> Dict[str, Any]:
    telemetry = payload.get("telemetry")
    if not isinstance(telemetry, dict):
        telemetry = {}
        payload["telemetry"] = telemetry
    if not isinstance(telemetry.get("stages"), dict):
        telemetry["stages"] = {}
    telemetry.setdefault("run_started_at", time.time())
    telemetry["updated_at"] = time.time()
    return telemetry


def _record_stage_timing(payload: Dict[str, Any], *, stage: str, duration_s: float, success: bool) -> None:
    telemetry = _ensure_telemetry(payload)
    stages = telemetry["stages"]
    entry = stages.get(stage)
    if not isinstance(entry, dict):
        entry = {"calls": 0, "success": 0, "failure": 0, "total_s": 0.0}
        stages[stage] = entry
    entry["calls"] = int(entry.get("calls") or 0) + 1
    entry["total_s"] = float(entry.get("total_s") or 0.0) + float(duration_s)
    if success:
        entry["success"] = int(entry.get("success") or 0) + 1
    else:
        entry["failure"] = int(entry.get("failure") or 0) + 1
    entry["last_duration_s"] = float(duration_s)
    entry["last_success"] = bool(success)
    entry["last_ts"] = time.time()


def _record_rework(payload: Dict[str, Any]) -> None:
    telemetry = _ensure_telemetry(payload)
    telemetry["rework_count"] = int(telemetry.get("rework_count") or 0) + 1
    reason = payload.get("rework_reason")
    if not isinstance(reason, dict):
        return
    reason_type = str(reason.get("type") or "").strip()
    if not reason_type:
        return
    by_type = telemetry.get("rework_by_type")
    if not isinstance(by_type, dict):
        by_type = {}
        telemetry["rework_by_type"] = by_type
    by_type[reason_type] = int(by_type.get(reason_type) or 0) + 1


@contextmanager
def _stage_timer(payload: Dict[str, Any], *, stage: str) -> Iterator[None]:
    start = time.perf_counter()
    ok = True
    try:
        yield
    except Exception:  # noqa: BLE001
        ok = False
        raise
    finally:
        _record_stage_timing(payload, stage=stage, duration_s=time.perf_counter() - start, success=ok)


@dataclass
class RunContext:
    run_id: str
    state: State = State.INIT
    retry: Dict[State, int] = field(default_factory=dict)
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 让所有节点都能稳定取到 run_id（历史代码部分读取 ctx.payload["run_id"]）
        self.payload.setdefault("run_id", self.run_id)
        _ensure_telemetry(self.payload)

    def bump_retry(self, state: State, limit: int = 2) -> bool:
        self.retry[state] = self.retry.get(state, 0) + 1
        return self.retry[state] <= limit


def _deep_merge(dst: Dict[str, Any], patch: Dict[str, Any]) -> None:
    for key, value in patch.items():
        existing = dst.get(key)
        if isinstance(value, dict) and isinstance(existing, dict):
            _deep_merge(existing, value)
        else:
            dst[key] = value


def _apply_restart_reset(payload: Dict[str, Any], *, start_state: str, reset_policy: str) -> None:
    _apply_restart_reset_impl(payload, start_state=start_state, reset_policy=reset_policy)


def step(ctx: RunContext) -> RunContext:
    """DreamWeaver 状态机：按阶段生成分镜、帧、片段与合成成片。"""
    try:
        try:
            apply_smart_tuning(ctx.payload, stage=ctx.state.name.lower())
        except Exception:  # noqa: BLE001
            # 智能调参为可选增强，不应影响主流程的可用性
            pass
        if ctx.state == State.INIT:
            with _stage_timer(ctx.payload, stage=stage_label(ctx.state)):
                planner.run(ctx)
            ctx.state = State.SCRIPT
        elif ctx.state == State.SCRIPT:
            with _stage_timer(ctx.payload, stage=stage_label(ctx.state)):
                scripter.run(ctx)
            if bool(ctx.payload.get("script_requires_review")):
                ctx.state = State.WAITING_SCRIPT_APPROVAL
            else:
                ctx.state = State.STORYBOARD
        elif ctx.state == State.WAITING_SCRIPT_APPROVAL:
            ctx.state = State.WAITING_SCRIPT_APPROVAL
        elif ctx.state == State.STORYBOARD:
            with _stage_timer(ctx.payload, stage=stage_label(ctx.state)):
                storyboarder.run(ctx)
            ctx.state = State.ASSET_LIBRARY
        elif ctx.state == State.ASSET_LIBRARY:
            with _stage_timer(ctx.payload, stage=stage_label(ctx.state)):
                asset_library.run(ctx)
            # 允许素材库阶段“增量推进”：单次 step() 只生成一部分素材，
            # 其间保持停留在 ASSET_LIBRARY，便于 Celery/UI 持续刷新进度。
            # 向后兼容：若未设置 asset_library_done，视为已完成本阶段。
            if ctx.payload.get("asset_library_done") is False:
                ctx.state = State.ASSET_LIBRARY
            elif bool(ctx.payload.get("asset_library_requires_review")):
                ctx.state = State.WAITING_APPROVAL
            else:
                ctx.state = State.KEYFRAMES
        elif ctx.state == State.WAITING_APPROVAL:
            ctx.state = State.WAITING_APPROVAL
        elif ctx.state == State.KEYFRAMES:
            with _stage_timer(ctx.payload, stage=stage_label(ctx.state)):
                painter.run_keyframes(ctx)
            ctx.state = State.MIDFRAMES
        elif ctx.state == State.MIDFRAMES:
            with _stage_timer(ctx.payload, stage=stage_label(ctx.state)):
                painter.run_midframes(ctx)
            ctx.state = State.VIDEO
        elif ctx.state == State.VIDEO:
            with _stage_timer(ctx.payload, stage=stage_label(ctx.state)):
                dreamweaver.run_video(ctx)  # 织梦映心
            if ctx.payload.get("video_done") is False:
                ctx.state = State.WAITING_VIDEO_CONFIRMATION
            else:
                ctx.state = State.EDIT
        elif ctx.state == State.WAITING_VIDEO_CONFIRMATION:
            ctx.state = State.WAITING_VIDEO_CONFIRMATION
        elif ctx.state == State.EDIT:
            with _stage_timer(ctx.payload, stage=stage_label(ctx.state)):
                editor.run(ctx)
            ctx.state = State.REVIEW
        elif ctx.state == State.REVIEW:
            with _stage_timer(ctx.payload, stage=stage_label(ctx.state)):
                audit_result = auditor.run(ctx)
                qc_result = autoqc.run(ctx.payload)
                ctx.payload["autoqc"] = qc_result

                qc_cfg = ctx.payload.get("qc_config") if isinstance(ctx.payload.get("qc_config"), dict) else {}
                qc_fail_policy = str(qc_cfg.get("fail_policy") or "").strip().lower()
                qc_allow_fail = bool(qc_cfg.get("allow_fail")) if isinstance(qc_cfg.get("allow_fail"), bool) else False
                qc_warn_only = qc_allow_fail or qc_fail_policy in {"warn", "warning", "soft", "allow", "ignore"}

                audit_pass = bool(audit_result.get("pass"))
                qc_pass = bool(qc_result.get("pass"))

                if audit_pass and qc_pass:
                    ctx.state = State.DONE
                else:
                    # 允许“质检失败仅警告，不拦截出片”（用于业务强制出片 / 降低返工成本）。
                    if audit_pass and (not qc_pass) and qc_warn_only:
                        ctx.payload["qc_warning"] = {
                            "autoqc_pass": qc_pass,
                            "audit_pass": audit_pass,
                            "policy": "warn_only",
                            "route": qc_result.get("route") if isinstance(qc_result, dict) else None,
                        }
                        ctx.state = State.DONE
                    else:
                        if not qc_pass:
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
                        _record_rework(ctx.payload)
        elif ctx.state == State.REWORK:
            if ctx.bump_retry(State.REWORK):
                route = ctx.payload.get("rework_route")
                target = None
                patch = None
                reset_policy = "downstream"
                if isinstance(route, dict):
                    if isinstance(route.get("target_state"), str):
                        target = str(route.get("target_state") or "").strip().upper() or None
                    if isinstance(route.get("patch"), dict) and route.get("patch"):
                        patch = route.get("patch")
                    if isinstance(route.get("reset_policy"), str) and str(route.get("reset_policy") or "").strip():
                        reset_policy = str(route.get("reset_policy") or "").strip()

                if isinstance(patch, dict):
                    _deep_merge(ctx.payload, patch)

                start_state = target or "STORYBOARD"
                _apply_restart_reset(ctx.payload, start_state=start_state, reset_policy=reset_policy)
                try:
                    ctx.state = State[start_state]
                except Exception:  # noqa: BLE001
                    ctx.state = State.STORYBOARD
            else:
                # 返工次数耗尽：补齐错误信息，避免上层仅显示 “pipeline failed”。
                reason = ctx.payload.get("rework_reason")
                reason_type = None
                reason_detail = None
                if isinstance(reason, dict):
                    if isinstance(reason.get("type"), str) and str(reason.get("type") or "").strip():
                        reason_type = str(reason.get("type") or "").strip()
                    route = reason.get("route") if isinstance(reason.get("route"), dict) else None
                    if isinstance(route, dict) and isinstance(route.get("reason"), str) and str(route.get("reason") or "").strip():
                        reason_detail = str(route.get("reason") or "").strip()
                msg = "rework exceeded retry limit"
                if reason_type and reason_detail:
                    msg = f"{msg}: {reason_type} ({reason_detail})"
                elif reason_type:
                    msg = f"{msg}: {reason_type}"
                elif reason_detail:
                    msg = f"{msg}: {reason_detail}"
                ctx.payload.setdefault("failed_from_state", State.REWORK.name)
                ctx.payload.setdefault("error", msg)
                ctx.state = State.FAILED
        else:
            ctx.state = ctx.state
    except Exception as exc:  # noqa: BLE001
        failed_from = ctx.state
        if ctx.bump_retry(ctx.state):
            return ctx
        ctx.payload["failed_from_state"] = failed_from.name
        ctx.state = State.FAILED
        ctx.payload["error"] = str(exc)
    finally:
        if ctx.state in (State.DONE, State.FAILED):
            telemetry = _ensure_telemetry(ctx.payload)
            telemetry.setdefault("run_finished_at", time.time())
            telemetry["terminal_state"] = ctx.state.name
    return ctx


def run_until_done(ctx: RunContext, max_steps: int = 50) -> RunContext:
    for _ in range(max_steps):
        if ctx.state in (
            State.DONE,
            State.FAILED,
            State.WAITING_SCRIPT_APPROVAL,
            State.WAITING_APPROVAL,
            State.WAITING_VIDEO_CONFIRMATION,
        ):
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
        State.WAITING_SCRIPT_APPROVAL: 12,
        State.STORYBOARD: 25,
        State.ASSET_LIBRARY: 35,
        State.WAITING_APPROVAL: 35,
        State.KEYFRAMES: 45,
        State.MIDFRAMES: 60,
        State.VIDEO: 75,
        State.WAITING_VIDEO_CONFIRMATION: 75,
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
        State.WAITING_SCRIPT_APPROVAL: "waiting_script_approval",
        State.STORYBOARD: "storyboard",
        State.ASSET_LIBRARY: "asset_library",
        State.WAITING_APPROVAL: "waiting_approval",
        State.KEYFRAMES: "keyframes",
        State.MIDFRAMES: "midframes",
        State.VIDEO: "video",
        State.WAITING_VIDEO_CONFIRMATION: "waiting_video_confirmation",
        State.EDIT: "edit",
        State.REVIEW: "review",
        State.REWORK: "rework",
        State.DONE: "done",
        State.FAILED: "failed",
    }
    return mapping.get(state, state.name.lower())
