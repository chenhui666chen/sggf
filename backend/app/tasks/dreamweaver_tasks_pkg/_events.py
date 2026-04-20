"""
事件发射辅助函数
"""
from typing import Any, Dict

from app.services.dreamweaver.events import DreamweaverEventEmitter


def _emit_asset_ready_events(
    emitter: DreamweaverEventEmitter,
    *,
    payload: Dict[str, Any],
    stage: str,
    emitted_keys: set[str],
) -> None:
    def _emit_single(uri: str, shot_id: Optional[str], role: str, kind: str) -> None:
        asset_id = "merged_video" if role == "merged_video" else f"{shot_id}:{role}" if shot_id else None
        if not asset_id:
            return
        key = uri or asset_id
        if key in emitted_keys:
            return
        emitted_keys.add(key)
        emitter.emit_event(
            stage=stage,
            event_type="asset_ready",
            payload={
                "id": asset_id,
                "shot_id": shot_id,
                "role": role,
                "kind": kind,
                "uri": uri,
                "status": "done",
            },
        )

    keyframes = payload.get("keyframes")
    if isinstance(keyframes, list):
        for item in keyframes:
            if not isinstance(item, dict):
                continue
            uri = item.get("path")
            if not isinstance(uri, str) or not uri.strip():
                continue
            shot_id, role, kind = _infer_asset_from_path(uri)
            if not role or not kind:
                meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
                role_meta = str(meta.get("role") or "").strip().lower()
                if role_meta in {"head", "tail"}:
                    role = "head_frame" if role_meta == "head" else "tail_frame"
                    kind = "image"
            if role and kind and shot_id:
                _emit_single(uri, shot_id, role, kind)

    midframes = payload.get("midframes")
    if isinstance(midframes, list):
        for item in midframes:
            if not isinstance(item, dict):
                continue
            uri = item.get("path")
            if not isinstance(uri, str) or not uri.strip():
                continue
            shot_id, role, kind = _infer_asset_from_path(uri)
            if role and kind and shot_id:
                _emit_single(uri, shot_id, role, kind)

    video_clips = payload.get("video_clips")
    if isinstance(video_clips, list):
        for item in video_clips:
            if not isinstance(item, dict):
                continue
            uri = item.get("path") or item.get("uri")
            if not isinstance(uri, str) or not uri.strip():
                continue
            shot_id, role, kind = _infer_asset_from_path(uri)
            if not role:
                role = "video_clip"
                kind = "video"
                shot_id = shot_id or Path(uri).stem
            if role and kind and shot_id:
                _emit_single(uri, shot_id, role, kind)

    merged_video = payload.get("merged_video")
    if isinstance(merged_video, str) and merged_video.strip():
        _emit_single(merged_video, None, "merged_video", "video")
