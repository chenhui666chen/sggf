from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, Iterator

DEFAULT_MAX_STEPS = 50
MAX_STEPS_WARNING_THRESHOLD = 100

PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if PROJECT_ROOT in sys.path:
    sys.path.remove(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from agents import asset_library, auditor, dreamweaver, editor, painter, planner, scripter, storyboarder
from pipeline import autoqc
from pipeline.dreamweaver_smart_dispatch_trace import (
    initialize_dreamweaver_smart_dispatch_trace,
    refresh_dreamweaver_smart_dispatch_trace,
)
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
    event_emitter: Any | None = None

    def __post_init__(self) -> None:
        # 让所有节点都能稳定取到 run_id（历史代码部分读取 ctx.payload["run_id"]）
        self.payload.setdefault("run_id", self.run_id)
        _ensure_telemetry(self.payload)
        initialize_dreamweaver_smart_dispatch_trace(self.payload)

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


def _normalize_text_list(raw: Any, *, limit: int = 200) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (str, int)) and not isinstance(raw, bool):
        text = str(raw).strip()
        return [text] if text else []
    if not isinstance(raw, list):
        return []

    out: list[str] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, (str, int)):
            continue
        text = str(item).strip()
        if not text or text in out:
            continue
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _collect_output_issue_messages(audit_result: Dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("output_issues", "issues"):
        issues = audit_result.get(key)
        if not isinstance(issues, list):
            continue
        for item in issues:
            if not isinstance(item, dict):
                continue
            if key == "issues":
                category = str(item.get("category") or "").strip().lower()
                if category and category != "output":
                    continue
            message = str(item.get("message") or "").strip().lower()
            if not message or message in out:
                continue
            out.append(message)
    return out


def _has_mergeable_video_clips(payload: Dict[str, Any]) -> bool:
    video_clips = payload.get("video_clips")
    if not isinstance(video_clips, list):
        return False

    valid_clip_count = 0
    for item in video_clips:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if path:
            valid_clip_count += 1

    if valid_clip_count <= 0:
        return False

    storyboard = payload.get("storyboard")
    if isinstance(storyboard, list):
        storyboard_count = sum(1 for item in storyboard if isinstance(item, dict))
        if storyboard_count > 0 and valid_clip_count < storyboard_count:
            return False

    return True


def _should_rebuild_merged_video_in_edit(payload: Dict[str, Any], audit_result: Dict[str, Any]) -> bool:
    output_issue_messages = _collect_output_issue_messages(audit_result)
    if not output_issue_messages:
        return False
    if not _has_mergeable_video_clips(payload):
        return False
    remergeable_messages = {
        "merged_video missing",
        "merged_video file missing",
        "merged_video too small",
    }
    return all(message in remergeable_messages for message in output_issue_messages)


def _build_review_audit_rework_route(payload: Dict[str, Any], audit_result: Dict[str, Any]) -> Dict[str, Any] | None:
    audit_failure_type = str(audit_result.get("failure_type") or "").strip().lower()
    if audit_failure_type != "output_audit_failed":
        return None

    if _should_rebuild_merged_video_in_edit(payload, audit_result):
        return {
            "target_state": "EDIT",
            "action": "rebuild_merged_video",
            "reason": "output_audit_failed",
            "reset_policy": "downstream",
        }

    regenerate_shot_ids = _normalize_text_list(payload.get("video_edit_failed_shot_ids"))
    if not regenerate_shot_ids:
        regenerate_shot_ids = _normalize_text_list(payload.get("video_edit_attempted_shot_ids"))

    route: Dict[str, Any] = {
        "target_state": "VIDEO",
        "action": "rerun_video",
        "reason": "output_audit_failed",
        "reset_policy": "downstream",
    }
    if regenerate_shot_ids:
        route["patch"] = {"regenerate_shot_ids": regenerate_shot_ids}
    return route


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
            try:
                # 在提示词审核前预生成视频提示词，避免前端“自动提示词”为空。
                dreamweaver.ensure_storyboard_video_prompts(ctx.payload, force=True)
            except Exception:  # noqa: BLE001
                pass
            ctx.state = State.ASSET_LIBRARY
        elif ctx.state == State.ASSET_LIBRARY:
            with _stage_timer(ctx.payload, stage=stage_label(ctx.state)):
                asset_library.run(ctx)
            try:
                # 素材库补充后再刷新一次，确保新信息进入视频提示词。
                dreamweaver.ensure_storyboard_video_prompts(ctx.payload, force=True)
            except Exception:  # noqa: BLE001
                pass
            # 允许素材库阶段“增量推进”：单次 step() 只生成一部分素材，
            # 其间保持停留在 ASSET_LIBRARY，便于 Celery/UI 持续刷新进度。
            # 向后兼容：若未设置 asset_library_done，视为已完成本阶段。
            prompt_review_required = bool(ctx.payload.get("prompt_review_required"))
            prompt_review = ctx.payload.get("prompt_review") if isinstance(ctx.payload.get("prompt_review"), dict) else {}
            prompt_review_approved = bool(prompt_review.get("approved"))
            if ctx.payload.get("asset_library_done") is False:
                ctx.state = State.ASSET_LIBRARY
            elif bool(ctx.payload.get("asset_library_requires_review")):
                ctx.state = State.WAITING_APPROVAL
            elif prompt_review_required and not prompt_review_approved:
                ctx.state = State.WAITING_APPROVAL
            else:
                ctx.state = State.KEYFRAMES
        elif ctx.state == State.WAITING_APPROVAL:
            ctx.state = State.WAITING_APPROVAL
        elif ctx.state == State.KEYFRAMES:
            with _stage_timer(ctx.payload, stage=stage_label(ctx.state)):
                painter.run_keyframes(ctx)
            refresh_dreamweaver_smart_dispatch_trace(ctx.payload, stage=stage_label(ctx.state))
            ctx.state = State.MIDFRAMES
        elif ctx.state == State.MIDFRAMES:
            with _stage_timer(ctx.payload, stage=stage_label(ctx.state)):
                painter.run_midframes(ctx)
            refresh_dreamweaver_smart_dispatch_trace(ctx.payload, stage=stage_label(ctx.state))
            ctx.state = State.VIDEO
        elif ctx.state == State.VIDEO:
            with _stage_timer(ctx.payload, stage=stage_label(ctx.state)):
                dreamweaver.run_video(ctx)  # 织梦映心
            refresh_dreamweaver_smart_dispatch_trace(ctx.payload, stage=stage_label(ctx.state))
            if ctx.payload.get("video_done") is False:
                ctx.state = State.WAITING_VIDEO_CONFIRMATION
            else:
                ctx.state = State.EDIT
        elif ctx.state == State.WAITING_VIDEO_CONFIRMATION:
            ctx.state = State.WAITING_VIDEO_CONFIRMATION
        elif ctx.state == State.EDIT:
            with _stage_timer(ctx.payload, stage=stage_label(ctx.state)):
                editor.run(ctx)
            refresh_dreamweaver_smart_dispatch_trace(ctx.payload, stage=stage_label(ctx.state))
            ctx.state = State.REVIEW
        elif ctx.state == State.REVIEW:
            with _stage_timer(ctx.payload, stage=stage_label(ctx.state)):
                audit_result = auditor.run(ctx)
                audit_failure_type = str(audit_result.get("failure_type") or "").strip().lower()
                safety_audit_blocked = audit_failure_type == "safety_audit_failed"

                if safety_audit_blocked:
                    qc_result = {
                        "pass": True,
                        "skipped": True,
                        "reason": "safety_audit_failed",
                        "failures": [],
                        "route": None,
                        "config": {},
                        "shots": {},
                    }
                else:
                    qc_result = autoqc.run(ctx.payload)
                ctx.payload["autoqc"] = qc_result
                # Phase 2.6 · AM-15 评价接线（双格式报告 + repair_dispatch；失败静默降级不阻断出片）
                try:
                    from pipeline.orchestration_kit import run_am15_stage

                    run_am15_stage(ctx.payload)
                except Exception:  # noqa: BLE001
                    pass
                # Phase 2.7 · 合成双通道：通道 A 编码基线校验（merged.mp4）+ 通道 B 剪映草稿导出
                try:
                    from pathlib import Path as _P

                    from agents.synthesis_kit import run_synthesis_dual_channel

                    _run_root = _P("backend/runs") if _P("backend/runs").exists() else _P("runs")
                    run_synthesis_dual_channel(
                        payload=ctx.payload,
                        run_dir=_run_root / str(ctx.payload.get("run_id") or "unknown"),
                    )
                except Exception:  # noqa: BLE001
                    pass
                refresh_dreamweaver_smart_dispatch_trace(ctx.payload, stage=stage_label(ctx.state))

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
                        if safety_audit_blocked:
                            safety_audit = (
                                audit_result.get("safety_audit")
                                if isinstance(audit_result.get("safety_audit"), dict)
                                else {}
                            )
                            ctx.payload["rework_reason"] = {
                                "type": "safety_audit_failed",
                                "issues": audit_result.get("issues", []),
                                "safety_audit": safety_audit,
                            }
                            ctx.payload["failed_from_state"] = State.REVIEW.name
                            ctx.payload["error"] = (
                                str(safety_audit.get("summary") or "").strip()
                                or "safety audit failed"
                            )
                            ctx.payload["error_type"] = "SafetyAuditFailed"
                            ctx.state = State.FAILED
                        elif not qc_pass:
                            ctx.payload["rework_reason"] = {
                                "type": "autoqc_failed",
                                "failures": qc_result.get("failures", []),
                                "route": qc_result.get("route"),
                            }
                            if isinstance(qc_result.get("route"), dict):
                                ctx.payload["rework_route"] = qc_result["route"]
                            ctx.state = State.REWORK
                            _record_rework(ctx.payload)
                        else:
                            audit_rework_route = _build_review_audit_rework_route(ctx.payload, audit_result)
                            if isinstance(audit_rework_route, dict):
                                ctx.payload["rework_reason"] = {
                                    "type": "output_audit_failed",
                                    "issues": audit_result.get("issues", []),
                                    "route": audit_rework_route,
                                }
                                ctx.payload["rework_route"] = audit_rework_route
                            else:
                                fallback_route = {
                                    "target_state": "SCRIPT",
                                    "action": "review_fix",
                                    "reason": "audit_failed",
                                }
                                ctx.payload["rework_reason"] = {
                                    "type": "audit_failed",
                                    "issues": audit_result.get("issues", []),
                                    "route": fallback_route,
                                }
                                ctx.payload["rework_route"] = fallback_route
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
        import traceback
        failed_from = ctx.state
        if ctx.bump_retry(ctx.state):
            return ctx
        ctx.payload["failed_from_state"] = failed_from.name
        ctx.state = State.FAILED
        ctx.payload["error"] = str(exc)
        ctx.payload["error_type"] = type(exc).__name__
        ctx.payload["error_traceback"] = traceback.format_exc()
    finally:
        if ctx.state in (State.DONE, State.FAILED):
            telemetry = _ensure_telemetry(ctx.payload)
            telemetry.setdefault("run_finished_at", time.time())
            telemetry["terminal_state"] = ctx.state.name
    return ctx


def run_until_done(ctx: RunContext, max_steps: int = DEFAULT_MAX_STEPS) -> RunContext:
    for _ in range(max_steps):
        if ctx.state in (
            State.DONE,
            State.FAILED,
            State.WAITING_SCRIPT_APPROVAL,
            State.WAITING_APPROVAL,
            State.WAITING_VIDEO_CONFIRMATION,
        ):
            break
        prev_state = ctx.state
        ctx = step(ctx)
        # Phase 2.6 · handoff 3E 门位记录（默认 warn 不阻断；DREAMWEAVER_HANDOFF_MODE=block 可阻断）
        try:
            from pipeline.orchestration_kit import record_stage_handoff

            record_stage_handoff(ctx.payload, prev_state.name)
        except RuntimeError:
            raise
        except Exception:  # noqa: BLE001 — 门位记录失败不影响主流程
            pass
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
