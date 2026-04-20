from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from adapters.adapter_helpers import SimpleGenerationResult as GenerationResult, generate_video
from agents.audio_sync_manager import AudioSyncManager
from agents.character_manager import CharacterManager
from agents.sound_effect_manager import SoundEffectManager
from agents.prompt_fragments import (
    library_assets_from_payload as _library_assets_from_payload,
    match_library_assets_for_shot as _match_library_assets_for_shot,
)
from pipeline.media_presets import (
    DREAMWEAVER_I2V_ENGINE,
    DREAMWEAVER_I2V_OUTPUT_FPS,
    DREAMWEAVER_T2V_ENGINE,
    ensure_media_payload,
    is_dreamweaver_generated_video_engine,
    is_dreamweaver_auto_engine,
    is_dreamweaver_i2v_engine,
    is_dreamweaver_t2v_engine,
    normalize_dreamweaver_video_duration_s,
    normalize_dreamweaver_video_engine,
    normalize_video_fps,
    resolve_frame_size,
)
from pipeline.artifacts_io import download_url_to_path as _download_url_to_path
from pipeline.ffmpeg_runner import run_ffmpeg as _run_ffmpeg
from pipeline.style_presets import style_negative_prompt_for_preset, style_prompt_for_preset

try:
    from agents.painter import _generate_t2i_with_candidates, _generate_edit_with_candidates
    PAINTER_AVAILABLE = True
except ImportError:
    PAINTER_AVAILABLE = False
    _generate_t2i_with_candidates = None
    _generate_edit_with_candidates = None

def _normalize_regenerate_shot_ids(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    out: List[str] = []
    for item in value:
        if not isinstance(item, (str, int)):
            continue
        s = str(item).strip()
        if not s or s in out:
            continue
        out.append(s)
        if len(out) >= 200:
            break
    return set(out)


def _index_video_clips_by_shot(items: Any) -> Dict[str, Dict[str, Any]]:
    clips: Dict[str, Dict[str, Any]] = {}
    if not isinstance(items, list):
        return clips
    for item in items:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        shot_id = Path(path).stem
        if shot_id:
            clips[shot_id] = item
    return clips


def _index_camera_states_by_shot_id(camera_states: Any) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(camera_states, list) or not camera_states:
        return out
    for track in camera_states:
        if not isinstance(track, dict):
            continue
        states = track.get("states") if isinstance(track.get("states"), list) else []
        for state in states:
            if not isinstance(state, dict):
                continue
            shot_id = str(state.get("shot_id") or state.get("state_id") or "").strip()
            if not shot_id or shot_id in out:
                continue
            out[shot_id] = state
    return out


def _project_asset_identity_keys(asset: Any) -> List[str]:
    if not isinstance(asset, dict):
        return []
    keys: List[str] = []

    raw_asset_id = asset.get("id")
    if raw_asset_id is None:
        raw_asset_id = asset.get("asset_id")
    try:
        asset_id = int(raw_asset_id) if raw_asset_id is not None else None
    except Exception:  # noqa: BLE001
        asset_id = None
    if asset_id is not None:
        keys.append(f"id:{asset_id}")

    role = str(asset.get("role") or "").strip()
    if role:
        keys.append(f"role:{role}")

    uri = str(asset.get("uri") or "").strip()
    if uri:
        keys.append(f"uri:{uri}")
    return keys


def _apply_library_asset_updates_to_payload(project_assets: Any, library_assets: Any) -> None:
    if not isinstance(project_assets, list) or not isinstance(library_assets, list):
        return

    payload_items_by_key: Dict[str, Dict[str, Any]] = {}
    for item in project_assets:
        if not isinstance(item, dict):
            continue
        for key in _project_asset_identity_keys(item):
            payload_items_by_key.setdefault(key, item)

    for asset in library_assets:
        if not isinstance(asset, dict):
            continue
        target: Optional[Dict[str, Any]] = None
        for key in _project_asset_identity_keys(asset):
            target = payload_items_by_key.get(key)
            if isinstance(target, dict):
                break
        if not isinstance(target, dict):
            continue

        meta = target.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            target["meta"] = meta

        provider_refs = asset.get("provider_refs") if isinstance(asset.get("provider_refs"), dict) else {}
        if provider_refs:
            meta["provider_refs"] = dict(provider_refs)
        else:
            meta.pop("provider_refs", None)

        sync_error = str(asset.get("provider_ref_sync_error") or "").strip()
        if sync_error:
            target["provider_ref_sync_error"] = sync_error
        else:
            target.pop("provider_ref_sync_error", None)


def _collect_dialogues_for_shot(shot: Dict[str, Any], audio_manager: AudioSyncManager) -> List[Dict[str, Any]]:
    dialogues: List[Dict[str, Any]] = []
    markers = shot.get("audio_markers")
    if isinstance(markers, list):
        for marker in markers:
            if not isinstance(marker, dict):
                continue
            text = str(marker.get("dialogue_text") or "").strip()
            speaker = str(marker.get("character_name") or "").strip()
            if text:
                dialogues.append({"text": text, "speaker": speaker})
    if dialogues:
        return dialogues

    desc = str(shot.get("desc") or "").strip()
    if not desc:
        return []
    return audio_manager.extract_dialogue_from_text(desc)


def _normalize_dialogue_key(text: str) -> str:
    raw = str(text or "").strip().lower()
    if not raw:
        return ""
    return re.sub(r"[\s\W]+", "", raw, flags=re.UNICODE)


def _collect_sfx_hint_for_shot(
    *,
    shot: Dict[str, Any],
    audio_markers: Optional[List[Dict[str, Any]]],
    audio_manager: AudioSyncManager,
    max_items: int = 6,
) -> str:
    effects_by_dialogue: Dict[str, List[str]] = {}
    if isinstance(audio_markers, list):
        for marker in audio_markers:
            if not isinstance(marker, dict):
                continue
            effects = marker.get("sound_effects")
            if not isinstance(effects, list) or not effects:
                continue
            key = _normalize_dialogue_key(marker.get("dialogue_line") or "")
            if not key:
                continue
            effects_by_dialogue[key] = [str(e).strip() for e in effects if str(e).strip()]

    effect_names: List[str] = []
    for dialogue in _collect_dialogues_for_shot(shot, audio_manager):
        key = _normalize_dialogue_key(dialogue.get("text") or "")
        if key and key in effects_by_dialogue:
            effect_names.extend(effects_by_dialogue[key])

    if not effect_names and isinstance(shot.get("sound_effects"), list):
        effect_names.extend([str(e).strip() for e in shot.get("sound_effects") if str(e).strip()])

    deduped: List[str] = []
    for name in effect_names:
        if name and name not in deduped:
            deduped.append(name)
        if len(deduped) >= max_items:
            break

    if not deduped:
        return ""

    return "音效：" + "、".join(deduped)


def _apply_sfx_to_clips(*, ctx: Any, run_dir: Path, storyboard: List[Dict[str, Any]]) -> None:
    if not _env_flag("DREAMWEAVER_SFX_ENABLED", default=False):
        return
    source = str(os.getenv("DREAMWEAVER_SFX_SOURCE") or "library").strip().lower()
    if source in {"model", "video", "none"}:
        return
    clips = ctx.payload.get("video_clips")
    if not isinstance(clips, list) or not clips:
        return

    sfx_manager = SoundEffectManager(run_dir=run_dir)
    effect_map = sfx_manager.build_shot_effects_map(
        storyboard=storyboard,
        audio_markers=ctx.payload.get("audio_markers") if isinstance(ctx.payload.get("audio_markers"), list) else None,
    )
    if not effect_map:
        return

    duration_by_shot: Dict[str, float] = {}
    for shot in storyboard:
        if not isinstance(shot, dict):
            continue
        shot_id = str(shot.get("shot_id") or "").strip()
        if not shot_id:
            continue
        try:
            duration_by_shot[shot_id] = float(shot.get("duration_s") or 0.0)
        except Exception:  # noqa: BLE001
            duration_by_shot[shot_id] = 0.0

    audio_manager = AudioSyncManager(run_dir=run_dir)
    updated: List[str] = []
    for clip in clips:
        if not isinstance(clip, dict):
            continue
        path = str(clip.get("path") or "").strip()
        if not path:
            continue
        if clip.get("has_sfx"):
            continue
        shot_id = Path(path).stem
        if not shot_id or shot_id not in effect_map:
            continue
        duration_s = duration_by_shot.get(shot_id, 0.0)
        sfx_path = sfx_manager.render_shot_sfx(
            shot_id=shot_id,
            duration_s=duration_s,
            effect_items=effect_map[shot_id],
        )
        if not sfx_path:
            continue
        output_path = run_dir / f"{shot_id}_sfx.mp4"
        if not output_path.exists():
            ok = audio_manager.sync_audio_to_video(
                video_path=str(Path(path)),
                audio_path=sfx_path,
                output_path=str(output_path),
                start_time=0.0,
                volume=1.0,
                fade_in=0.0,
                fade_out=0.0,
            )
            if not ok:
                continue
        clip["path"] = str(output_path)
        clip["sfx_path"] = sfx_path
        clip["has_sfx"] = True
        updated.append(shot_id)

    if updated:
        ctx.payload["sfx_tracks"] = effect_map


def _stable_seed(*parts: str) -> int:
    payload = "|".join(parts).encode("utf-8", errors="ignore")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False) % 2147483647


def _parse_int(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return default
        return int(value)
    except Exception:  # noqa: BLE001
        return default


def _resolve_slideshow_effect(value: Any) -> str:
    raw = str(value or os.getenv("DREAMWEAVER_SLIDESHOW_EFFECT") or "kenburns").strip().lower()
    if not raw:
        return "kenburns"
    if raw in {"none", "off", "disabled"}:
        return "static"
    if raw in {"zoompan", "motion"}:
        return "kenburns"
    return raw


def _join_prompt_parts(parts: List[str], *, sep: str = "，", max_parts: int = 12) -> str:
    deduped: List[str] = []
    for part in parts:
        s = str(part or "").strip()
        if not s or s in deduped:
            continue
        deduped.append(s)
        if len(deduped) >= max_parts:
            break
    return sep.join(deduped)


def _i2v_soft_negative_hint(style_negative_prompt: str) -> str:
    raw = str(style_negative_prompt or "").strip()
    if not raw:
        return ""
    items = [s.strip() for s in raw.replace("，", ",").split(",") if s.strip()]
    items = [it for i, it in enumerate(items) if it not in items[:i]]
    if not items:
        return ""
    items = items[:8]
    return "避免出现：" + "、".join(items)


def _compact_prompt_fragment(fragment: str, *, limit: int = 180) -> str:
    text = str(fragment or "").strip()
    if not text:
        return ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    merged = "；".join(lines)
    if limit > 0 and len(merged) > int(limit):
        merged = merged[: int(limit)].rstrip("，； ")
    return merged


def _infer_motion_level(*, desc: str, motion_desc: str) -> str:
    text = f"{desc} {motion_desc}".strip()
    if any(k in text for k in ("过渡", "衔接", "转场", "接续", "镜头切换", "承接")):
        return "small"
    if any(k in text for k in ("打斗", "追逐", "爆炸", "奔跑", "冲刺", "激烈", "快速", "翻滚")):
        return "large"
    return "medium"


def _as_str_list(value: Any, *, limit: int = 8) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if not isinstance(item, (str, int)):
            continue
        s = str(item).strip()
        if not s or s in out:
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _normalize_state_text(value: Any, *, limit: int = 120) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if limit > 0 and len(text) > int(limit):
        text = text[: int(limit)]
    return text


def _shot_cam_idx(shot: Dict[str, Any]) -> int:
    raw = None
    if isinstance(shot, dict):
        if "cam_idx" in shot:
            raw = shot.get("cam_idx")
        elif "camera_index" in shot:
            raw = shot.get("camera_index")
    if raw is None or isinstance(raw, bool):
        return -1
    try:
        return int(raw)
    except Exception:  # noqa: BLE001
        return -1


def _infer_i2v_head_source(
    *,
    prev_shot: Optional[Dict[str, Any]],
    shot: Dict[str, Any],
    camera_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    自动推断本镜头 I2V 的首帧来源：
    - 默认：使用本镜头 keyframe head（稳定、可控）
    - 若满足“同相机 + 状态连续”（或明确的过渡/衔接镜头）：使用上一镜头视频尾帧作为本镜头首帧（更强衔接）
    - 若存在相机 State（camera_states）且首镜头依赖 parent camera/shot：允许使用依赖镜头视频尾帧作为首帧（更强跨相机衔接）
    推断优先依赖 state_before/state_after + cam_idx，并在状态缺失时用 motion_desc 做轻量兜底（KISS）。
    """
    base: Dict[str, Any]
    if not isinstance(prev_shot, dict):
        base = {"mode": "head_keyframe", "reason": "no_prev_shot"}
    else:
        curr_cam = _shot_cam_idx(shot)
        prev_cam = _shot_cam_idx(prev_shot)
        if curr_cam < 0 or prev_cam < 0:
            base = {"mode": "head_keyframe", "reason": "missing_cam_idx"}
        elif curr_cam != prev_cam:
            base = {"mode": "head_keyframe", "reason": "cam_changed"}
        else:
            prev_after = _normalize_state_text(prev_shot.get("state_after"))
            curr_before = _normalize_state_text(shot.get("state_before"))
            motion_level = _infer_motion_level(
                desc=str(shot.get("desc") or "").strip(),
                motion_desc=str(shot.get("motion_desc") or "").strip(),
            )

            if prev_after and curr_before:
                if prev_after == curr_before:
                    base = {
                        "mode": "prev_clip_tail",
                        "reason": "same_cam_and_state_match",
                        "prev_state_after": prev_after,
                        "state_before": curr_before,
                        "motion_level": motion_level,
                    }
                else:
                    base = {
                        "mode": "head_keyframe",
                        "reason": "state_mismatch",
                        "prev_state_after": prev_after,
                        "state_before": curr_before,
                        "motion_level": motion_level,
                    }
            elif not prev_after and not curr_before:
                if motion_level == "small":
                    base = {"mode": "prev_clip_tail", "reason": "same_cam_transition", "motion_level": motion_level}
                else:
                    base = {"mode": "head_keyframe", "reason": "state_missing_but_not_transition", "motion_level": motion_level}
            else:
                base = {
                    "mode": "head_keyframe",
                    "reason": "partial_state_provided",
                    "prev_state_after": prev_after,
                    "state_before": curr_before,
                    "motion_level": motion_level,
                }

    if str(base.get("mode") or "") == "prev_clip_tail" and isinstance(prev_shot, dict):
        prev_shot_id = str(prev_shot.get("shot_id") or "").strip()
        if prev_shot_id:
            base.setdefault("depends_on_shot_id", prev_shot_id)

    if str(base.get("mode") or "") != "prev_clip_tail" and isinstance(camera_state, dict) and _env_flag("DREAMWEAVER_I2V_CAMERA_STATE_BRIDGE", default=True):
        anchor_source = str(camera_state.get("anchor_source") or "").strip()
        anchor_shot_id = str(camera_state.get("anchor_shot_id") or "").strip()
        if anchor_source in {"camera_tree_parent_shot", "parent_camera_tail"} and anchor_shot_id:
            motion_level = _infer_motion_level(
                desc=str(shot.get("desc") or "").strip(),
                motion_desc=str(shot.get("motion_desc") or "").strip(),
            )
            base = {
                "mode": "prev_clip_tail",
                "reason": anchor_source,
                "depends_on_shot_id": anchor_shot_id,
                "anchor_source": anchor_source,
                "anchor_shot_id": anchor_shot_id,
                "motion_level": motion_level,
                "cam_idx": _shot_cam_idx(shot),
            }

    return base


def _extract_video_tail_frame(
    *,
    ffmpeg: str,
    video_path: Path,
    out_path: Path,
    width: int,
    height: int,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-sseof",
        "-0.1",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        str(out_path),
    ]
    _run_ffmpeg(cmd, log_dir=out_path.parent, log_prefix=f"ffmpeg_extract_tail_{video_path.stem}")

