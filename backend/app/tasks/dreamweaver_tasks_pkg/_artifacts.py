"""
状态和产物相关函数
"""
from typing import Any, Dict, List

from pipeline.state_machine import State


def _is_sqlite_locked_error(exc: Exception) -> bool:
    if not isinstance(exc, OperationalError):
        return False
    orig = getattr(exc, "orig", None)
    if isinstance(orig, sqlite3.OperationalError) and "database is locked" in str(orig).lower():
        return True
    msg = str(exc).lower()
    return "database is locked" in msg or "database schema is locked" in msg


def _stage_artifacts(state: State, payload: Dict[str, Any]) -> Dict[str, Any]:
    storyboard = payload.get("storyboard") or []
    keyframes = payload.get("keyframes") or []
    midframes = payload.get("midframes") or []
    video_clips = payload.get("video_clips") or []
    camera_tree_generation = payload.get("camera_tree_generation") if isinstance(payload.get("camera_tree_generation"), dict) else None
    camera_tree = payload.get("camera_tree") if isinstance(payload.get("camera_tree"), list) else None
    camera_states = payload.get("camera_states") if isinstance(payload.get("camera_states"), list) else None
    camera_scenes = payload.get("camera_scenes") if isinstance(payload.get("camera_scenes"), list) else None

    last_storyboard_shot_id = None
    if isinstance(storyboard, list) and storyboard:
        last_item = storyboard[-1]
        if isinstance(last_item, dict):
            last_storyboard_shot_id = last_item.get("shot_id")

    audit = payload.get("audit")
    audit_pass = None
    issues_count = None
    if isinstance(audit, dict):
        audit_pass = audit.get("pass")
        issues = audit.get("issues")
        issues_count = len(issues) if isinstance(issues, list) else None

    autoqc = payload.get("autoqc")
    autoqc_pass = None
    autoqc_score = None
    if isinstance(autoqc, dict):
        autoqc_pass = autoqc.get("pass")
        if isinstance(autoqc.get("overall_score"), (int, float)):
            autoqc_score = float(autoqc["overall_score"])

    stage_specific: Dict[str, Any] = {
        "state": state.name,
        "stage": stage_label(state),
    }

    if state == State.SCRIPT:
        script_text = payload.get("script_text")
        stage_specific["script_generation"] = payload.get("script_generation") if isinstance(payload.get("script_generation"), dict) else None
        stage_specific["script_requires_review"] = bool(payload.get("script_requires_review"))
        stage_specific["script_review"] = payload.get("script_review") if isinstance(payload.get("script_review"), dict) else None
        stage_specific["script_text_preview"] = str(script_text)[:300] if isinstance(script_text, str) else None
    elif state == State.STORYBOARD:
        stage_specific["storyboard_count"] = len(storyboard) if isinstance(storyboard, list) else 0
        stage_specific["last_storyboard_shot_id"] = last_storyboard_shot_id
        stage_specific["camera_tree_mode"] = (
            str(camera_tree_generation.get("mode") or "").strip() if isinstance(camera_tree_generation, dict) else None
        )
        stage_specific["camera_count"] = len(camera_tree) if isinstance(camera_tree, list) else 0
        stage_specific["camera_states_count"] = len(camera_states) if isinstance(camera_states, list) else 0
    elif state == State.ASSET_LIBRARY:
        stage_specific["asset_library"] = payload.get("asset_library")
        stage_specific["asset_library_requires_review"] = bool(payload.get("asset_library_requires_review"))
        stage_specific["asset_library_review"] = payload.get("asset_library_review")
    elif state == State.KEYFRAMES:
        stage_specific["keyframes_paths"] = [i.get("path") for i in keyframes[-3:] if isinstance(i, dict) and isinstance(i.get("path"), str)]
        stage_specific["camera_scenes_count"] = len(camera_scenes) if isinstance(camera_scenes, list) else 0
    elif state == State.MIDFRAMES:
        stage_specific["midframes_paths"] = [i.get("path") for i in midframes[-3:] if isinstance(i, dict) and isinstance(i.get("path"), str)]
    elif state == State.VIDEO:
        stage_specific["video_clips_paths"] = [i.get("path") for i in video_clips[-3:] if isinstance(i, dict) and isinstance(i.get("path"), str)]
    elif state == State.WAITING_VIDEO_CONFIRMATION:
        stage_specific["video_clips_paths"] = [i.get("path") for i in video_clips[-3:] if isinstance(i, dict) and isinstance(i.get("path"), str)]
    elif state == State.EDIT:
        stage_specific["merged_video"] = payload.get("merged_video")
    elif state == State.REVIEW:
        stage_specific["audit_pass"] = audit_pass
        stage_specific["issues_count"] = issues_count
        stage_specific["autoqc_pass"] = autoqc_pass
        stage_specific["autoqc_overall_score"] = autoqc_score
    elif state == State.WAITING_APPROVAL:
        stage_specific["asset_library"] = payload.get("asset_library")
        stage_specific["asset_library_requires_review"] = bool(payload.get("asset_library_requires_review"))
        stage_specific["asset_library_review"] = payload.get("asset_library_review")
    elif state == State.WAITING_SCRIPT_APPROVAL:
        script_text = payload.get("script_text")
        stage_specific["script_generation"] = payload.get("script_generation") if isinstance(payload.get("script_generation"), dict) else None
        stage_specific["script_requires_review"] = bool(payload.get("script_requires_review"))
        stage_specific["script_review"] = payload.get("script_review") if isinstance(payload.get("script_review"), dict) else None
        stage_specific["script_text_preview"] = str(script_text)[:300] if isinstance(script_text, str) else None
    elif state == State.REWORK:
        stage_specific["rework_reason"] = payload.get("rework_reason")

    return stage_specific


def _artifact_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    storyboard = payload.get("storyboard") or []
    keyframes = payload.get("keyframes") or []
    midframes = payload.get("midframes") or []
    video_clips = payload.get("video_clips") or []

    audit = payload.get("audit")
    audit_pass = None
    if isinstance(audit, dict):
        audit_pass = audit.get("pass")

    autoqc = payload.get("autoqc")
    autoqc_pass = None
    autoqc_score = None
    autoqc_route = None
    if isinstance(autoqc, dict):
        autoqc_pass = autoqc.get("pass")
        autoqc_route = autoqc.get("route")
        if isinstance(autoqc.get("overall_score"), (int, float)):
            autoqc_score = float(autoqc["overall_score"])

    def safe_len(value: Any) -> int:
        return len(value) if isinstance(value, list) else 0

    def last_path(items: Any) -> Any:
        if not isinstance(items, list) or not items:
            return None
        last = items[-1]
        if isinstance(last, dict):
            return last.get("path")
        return None

    def tail_paths(items: Any, limit: int = 3) -> List[str]:
        if not isinstance(items, list) or not items:
            return []
        paths: List[str] = []
        for item in items[-limit:]:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                paths.append(item["path"])
        return paths

    def library_assets(items: Any) -> List[Dict[str, Any]]:
        if not isinstance(items, list):
            return []
        out: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            if not isinstance(role, str) or not role.startswith("lib_"):
                continue
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            out.append({"role": role, "approved": bool(meta.get("approved")), "uri": item.get("uri")})
        return out

    lib_assets = library_assets(payload.get("project_assets"))

    return {
        "has_plan": bool(payload.get("plan")),
        "storyboard_count": safe_len(storyboard),
        "keyframes_count": safe_len(keyframes),
        "last_keyframe_path": last_path(keyframes),
        "keyframes_tail_paths": tail_paths(keyframes),
        "midframes_count": safe_len(midframes),
        "last_midframe_path": last_path(midframes),
        "midframes_tail_paths": tail_paths(midframes),
        "video_clips_count": safe_len(video_clips),
        "last_video_clip_path": last_path(video_clips),
        "video_clips_tail_paths": tail_paths(video_clips),
        "merged_video": payload.get("merged_video"),
        "library_assets_count": len(lib_assets),
        "library_unapproved_count": len([a for a in lib_assets if not a.get("approved")]),
        "audit_pass": audit_pass,
        "autoqc_pass": autoqc_pass,
        "autoqc_overall_score": autoqc_score,
        "autoqc_route": autoqc_route,
        "rework_reason": payload.get("rework_reason"),
    }
