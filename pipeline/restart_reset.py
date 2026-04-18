from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def apply_restart_reset(payload: Dict[str, Any], *, start_state: str, reset_policy: str) -> None:
    """
    对“重启式重跑”做下游清理（downstream reset）。

    说明：
    - policy=none：不清理任何产物/状态（resume/继续执行时常用）
    - policy=downstream：按 start_state 清理该阶段及后续产物；支持 shot_ids 局部重跑
    """
    policy = (reset_policy or "").strip().lower()
    if policy == "none":
        return

    state = (start_state or "").strip().upper()

    regen_shots_raw = payload.get("regenerate_shot_ids")
    regen_shots: list[str] = []
    if isinstance(regen_shots_raw, list):
        for item in regen_shots_raw:
            if not isinstance(item, (str, int)):
                continue
            s = str(item).strip()
            if not s or s in regen_shots:
                continue
            regen_shots.append(s)
            if len(regen_shots) >= 200:
                break
    regen_shot_set = set(regen_shots)

    def _as_str_list(raw: Any, *, limit: int = 200) -> list[str]:
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        for item in raw:
            if not isinstance(item, (str, int)):
                continue
            s = str(item).strip()
            if not s or s in out:
                continue
            out.append(s)
            if len(out) >= limit:
                break
        return out

    def _as_int_list(raw: Any, *, limit: int = 200) -> list[int]:
        if not isinstance(raw, list):
            return []
        out: list[int] = []
        for item in raw:
            if isinstance(item, bool):
                continue
            try:
                n = int(item)
            except Exception:  # noqa: BLE001
                continue
            if n in out:
                continue
            out.append(n)
            if len(out) >= limit:
                break
        return out

    def _materialize_regenerate_shot_ids_from_cam_idxs() -> None:
        nonlocal regen_shots, regen_shot_set

        if state not in {"KEYFRAMES", "MIDFRAMES", "VIDEO"}:
            return
        cam_idxs = _as_int_list(payload.get("regenerate_cam_idxs"))
        if not cam_idxs:
            return
        cam_set = set(cam_idxs)

        storyboard = payload.get("storyboard")
        derived: list[str] = []
        if isinstance(storyboard, list) and storyboard:
            for shot in storyboard:
                if not isinstance(shot, dict):
                    continue
                shot_id = str(shot.get("shot_id") or "").strip()
                if not shot_id or shot_id in derived:
                    continue
                raw_cam_idx = shot.get("cam_idx") or shot.get("camera_index") or 0
                try:
                    cam_idx = int(raw_cam_idx)
                except Exception:  # noqa: BLE001
                    cam_idx = 0
                if cam_idx not in cam_set:
                    continue
                derived.append(shot_id)
                if len(derived) >= 200:
                    break

        if not derived:
            return

        merged: list[str] = []
        for sid in regen_shots:
            if not sid or sid in merged:
                continue
            merged.append(sid)
            if len(merged) >= 200:
                break
        for sid in derived:
            if sid in merged:
                continue
            merged.append(sid)
            if len(merged) >= 200:
                break

        regen_shots = merged
        regen_shot_set = set(merged)
        payload["regenerate_shot_ids"] = merged

    def _deps_by_shot_from_camera_states(raw: Any) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        if not isinstance(raw, list) or not raw:
            return out
        for track in raw:
            if not isinstance(track, dict):
                continue
            states = track.get("states") if isinstance(track.get("states"), list) else []
            for state_node in states:
                if not isinstance(state_node, dict):
                    continue
                shot_id = str(state_node.get("shot_id") or state_node.get("state_id") or "").strip()
                if not shot_id or shot_id in out:
                    continue
                deps = _as_str_list(state_node.get("depends_on_state_ids"), limit=20)
                if not deps:
                    anchor = state_node.get("anchor_shot_id")
                    if isinstance(anchor, str) and anchor.strip():
                        deps = [anchor.strip()]
                if deps:
                    out[shot_id] = deps
        return out

    _materialize_regenerate_shot_ids_from_cam_idxs()

    def _expand_regenerate_shot_ids_for_keyframes() -> None:
        nonlocal regen_shots, regen_shot_set
        if not regen_shot_set or state != "KEYFRAMES":
            return

        storyboard = payload.get("storyboard")
        shot_pos_by_id: dict[str, int] = {}
        storyboard_order: list[str] = []
        if isinstance(storyboard, list) and storyboard:
            for pos, shot in enumerate(storyboard):
                if not isinstance(shot, dict):
                    continue
                shot_id = str(shot.get("shot_id") or "").strip()
                if not shot_id or shot_id in shot_pos_by_id:
                    continue
                shot_pos_by_id[shot_id] = int(pos)
                storyboard_order.append(shot_id)

        camera_states = payload.get("camera_states")
        deps_by_shot = _deps_by_shot_from_camera_states(camera_states)

        if not deps_by_shot and isinstance(storyboard, list) and storyboard:
            try:
                from agents.camera_states import build_camera_states  # local import: avoid pipeline<->agents hard dep at import time

                camera_tree = payload.get("camera_tree")
                built = build_camera_states(
                    storyboard,
                    camera_tree if isinstance(camera_tree, list) and camera_tree else None,
                )
                deps_by_shot = _deps_by_shot_from_camera_states(built)
                if deps_by_shot:
                    payload["camera_states"] = built
            except Exception:  # noqa: BLE001
                deps_by_shot = {}

        if not deps_by_shot:
            return

        # 只接受“指向更早 shot”的依赖，避免错误数据导致循环/死锁。
        if shot_pos_by_id:
            filtered: dict[str, list[str]] = {}
            for shot_id, deps in deps_by_shot.items():
                pos = shot_pos_by_id.get(shot_id)
                if not isinstance(pos, int):
                    continue
                kept: list[str] = []
                for dep in deps:
                    dep_pos = shot_pos_by_id.get(dep)
                    if isinstance(dep_pos, int) and int(dep_pos) < int(pos):
                        kept.append(dep)
                if kept:
                    filtered[shot_id] = kept
            deps_by_shot = filtered

        # reverse graph: dep -> dependents
        reverse: dict[str, set[str]] = {}
        for shot_id, deps in deps_by_shot.items():
            for dep in deps:
                reverse.setdefault(dep, set()).add(shot_id)

        expanded: set[str] = set(regen_shot_set)
        queue: list[str] = list(regen_shot_set)
        while queue:
            cur = queue.pop()
            for child in reverse.get(cur, set()):
                if child in expanded:
                    continue
                expanded.add(child)
                queue.append(child)
                if len(expanded) >= 400:  # safety: still hard-capped when materializing list
                    break

        if expanded == regen_shot_set:
            return

        # materialize order: keep user input first, then storyboard order, then stable fallback.
        ordered: list[str] = []
        for sid in regen_shots:
            if sid in expanded and sid not in ordered:
                ordered.append(sid)
        for sid in storyboard_order:
            if sid in expanded and sid not in ordered:
                ordered.append(sid)
                if len(ordered) >= 200:
                    break
        if len(ordered) < 200:
            for sid in sorted(expanded):
                if sid in ordered:
                    continue
                ordered.append(sid)
                if len(ordered) >= 200:
                    break

        regen_shots = ordered
        regen_shot_set = set(ordered)
        payload["regenerate_shot_ids"] = ordered

    _expand_regenerate_shot_ids_for_keyframes()

    def _shot_key_from_asset_path(path: str) -> str | None:
        p = Path(path)
        stem = p.stem
        suffix = p.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            if stem.endswith("_head"):
                return stem[: -len("_head")]
            if stem.endswith("_tail"):
                return stem[: -len("_tail")]
            if stem.endswith("_mid"):
                return stem[: -len("_mid")]
            return None
        if suffix in {".mp4", ".mov", ".mkv"}:
            return stem
        return None

    def _drop_assets_for_shots(items: Any) -> Any:
        if not regen_shot_set:
            return items
        if not isinstance(items, list) or not items:
            return items
        kept: list[Any] = []
        for it in items:
            if not isinstance(it, dict):
                kept.append(it)
                continue
            path = it.get("path")
            if not isinstance(path, str) or not path.strip():
                kept.append(it)
                continue
            shot_key = _shot_key_from_asset_path(path)
            if shot_key and shot_key in regen_shot_set:
                continue
            kept.append(it)
        return kept

    def _drop_shot_ids_from_payload_list(key: str) -> None:
        current = _as_str_list(payload.get(key))
        if not current:
            payload.pop(key, None)
            return
        if not regen_shot_set:
            payload.pop(key, None)
            return
        kept = [sid for sid in current if sid not in regen_shot_set]
        if kept:
            payload[key] = kept
        else:
            payload.pop(key, None)

    # 始终清理：失败/审计/质检/返工信息，避免“带病重跑”
    for k in (
        "error",
        "audit",
        "autoqc",
        "rework_reason",
        "rework_route",
        "qc_warning",
        "video_edit_result",
        "script_generation",
        "script_entities_synced",
        "script_entities_sync",
        "asset_library_force_regenerate",
    ):
        payload.pop(k, None)

    if policy != "downstream":
        return

    def _drop(keys: List[str]) -> None:
        for key in keys:
            payload.pop(key, None)

    if state == "SCRIPT":
        _drop(
            [
                "script_text",
                "script_entities",
                "script_review",
                "script_requires_review",
                "storyboard",
                "keyframes",
                "midframes",
                "video_clips",
                "merged_video",
                "video_edit_attempted_shot_ids",
                "video_edit_failed_shot_ids",
            ]
        )
        return
    if state == "STORYBOARD":
        _drop(["storyboard", "keyframes", "midframes", "video_clips", "merged_video", "video_edit_attempted_shot_ids", "video_edit_failed_shot_ids"])
        return
    if state == "ASSET_LIBRARY":
        regen_roles = payload.get("asset_library_regenerate_roles")
        if isinstance(regen_roles, list) and any(isinstance(r, (str, int)) and str(r).strip() for r in regen_roles):
            payload.pop("asset_library_force_regenerate", None)
            payload.pop("asset_library_progress", None)
            payload.pop("asset_library_regenerate_progress", None)
        else:
            payload["asset_library_force_regenerate"] = True
        _drop(
            [
                "asset_library",
                "asset_library_requires_review",
                "keyframes",
                "midframes",
                "video_clips",
                "merged_video",
                "video_edit_attempted_shot_ids",
                "video_edit_failed_shot_ids",
            ]
        )
        return
    if state == "KEYFRAMES":
        if regen_shot_set:
            payload["keyframes"] = _drop_assets_for_shots(payload.get("keyframes"))
            payload["midframes"] = _drop_assets_for_shots(payload.get("midframes"))
            payload["video_clips"] = _drop_assets_for_shots(payload.get("video_clips"))
            payload.pop("merged_video", None)
            _drop_shot_ids_from_payload_list("video_edit_attempted_shot_ids")
            _drop_shot_ids_from_payload_list("video_edit_failed_shot_ids")
        else:
            _drop(["keyframes", "midframes", "video_clips", "merged_video", "video_edit_attempted_shot_ids", "video_edit_failed_shot_ids"])
        return
    if state == "MIDFRAMES":
        if regen_shot_set:
            payload["midframes"] = _drop_assets_for_shots(payload.get("midframes"))
            payload["video_clips"] = _drop_assets_for_shots(payload.get("video_clips"))
            payload.pop("merged_video", None)
            _drop_shot_ids_from_payload_list("video_edit_attempted_shot_ids")
            _drop_shot_ids_from_payload_list("video_edit_failed_shot_ids")
        else:
            _drop(["midframes", "video_clips", "merged_video", "video_edit_attempted_shot_ids", "video_edit_failed_shot_ids"])
        return
    if state == "VIDEO":
        if regen_shot_set:
            payload["video_clips"] = _drop_assets_for_shots(payload.get("video_clips"))
            payload.pop("merged_video", None)
            _drop_shot_ids_from_payload_list("video_edit_attempted_shot_ids")
            _drop_shot_ids_from_payload_list("video_edit_failed_shot_ids")
        else:
            _drop(["video_clips", "merged_video", "video_edit_attempted_shot_ids", "video_edit_failed_shot_ids"])
        return
    if state == "EDIT":
        _drop(["merged_video"])
        return
    if state == "REVIEW":
        return
