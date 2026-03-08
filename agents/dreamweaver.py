from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from adapters.model_adapters import GenerationResult, ModelAdapterFactory
from agents.audio_sync_manager import AudioSyncManager
from agents.character_manager import CharacterManager
from agents.sound_effect_manager import SoundEffectManager
from agents.prompt_fragments import (
    library_assets_from_payload as _library_assets_from_payload,
    match_library_assets_for_shot as _match_library_assets_for_shot,
)
from pipeline.media_presets import (
    WAN_I2V_OUTPUT_FPS,
    ensure_media_payload,
    normalize_video_fps,
    normalize_wan_i2v_duration_s,
    resolve_frame_size,
)
from pipeline.artifacts_io import download_url_to_path as _download_url_to_path
from pipeline.ffmpeg_runner import run_ffmpeg as _run_ffmpeg
from pipeline.style_presets import style_negative_prompt_for_preset, style_prompt_for_preset


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


def _build_audio_policy_hint() -> str:
    if not _env_flag("DREAMWEAVER_AUDIO_POLICY_HINT_ENABLED", default=True):
        return ""
    if _env_flag("DREAMWEAVER_DIALOGUE_AUDIO_EMBED", default=False):
        return ""

    sfx_source = str(os.getenv("DREAMWEAVER_SFX_SOURCE") or "library").strip().lower()
    if sfx_source in {"model", "video"}:
        return "音频要求：仅生成环境音/音效，不生成对白音频与背景音乐"
    return "音频要求：不生成对白音频与背景音乐"


def _build_wan_i2v_prompt(*, shot: Dict[str, Any], style_preset: str, frame_ratio: str, prompt_fragment: str = "", engine: str = "wan_i2v") -> str:
    """构建 Wan I2V/T2V 的视频提示词，优先吸收 storyboard 的结构化字段。"""
    style_prompt = style_prompt_for_preset(style_preset)
    soft_negative = _i2v_soft_negative_hint(style_negative_prompt_for_preset(style_preset))
    engine_value = str(engine or "wan_i2v").strip().lower()
    is_t2v = engine_value in {"wan_t2v", "wan26_t2v", "t2v"}
    consistency_line = (
        "连续性约束：首帧参考图是角色与场景基准，保持人物身份、服装、发型、场景布局与光线逻辑一致，禁止突变。"
        if not is_t2v
        else "连续性约束：保持角色身份、场景设定与光线连续，动作过渡自然。"
    )

    schema_v2 = shot.get("shot_schema_v2") if isinstance(shot.get("shot_schema_v2"), dict) else {}
    schema_meta = shot.get("shot_schema_v2_meta") if isinstance(shot.get("shot_schema_v2_meta"), dict) else {}
    head_frame = shot.get("head_frame") if isinstance(shot.get("head_frame"), dict) else {}
    tail_frame = shot.get("tail_frame") if isinstance(shot.get("tail_frame"), dict) else {}

    def _text(value: Any, *, limit: int = 0) -> str:
        s = str(value or "").replace("\n", " ").strip()
        if limit > 0 and len(s) > limit:
            s = s[:limit]
        return s

    def _pick_text(*values: Any, limit: int = 0) -> str:
        for value in values:
            s = _text(value, limit=0)
            if s:
                if limit > 0 and len(s) > limit:
                    return s[:limit]
                return s
        return ""

    def _pick_meta_text(key: str, *, limit: int = 0) -> str:
        return _pick_text(shot.get(key), schema_v2.get(key), schema_meta.get(key), limit=limit)

    def _pick_meta_any(key: str) -> Any:
        for container in (shot, schema_v2, schema_meta):
            if not isinstance(container, dict):
                continue
            value = container.get(key)
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            if isinstance(value, (list, dict)) and not value:
                continue
            return value
        return None

    desc = _pick_text(shot.get("desc"), limit=240)
    visual_desc = _pick_meta_text("visual_desc", limit=240)
    ff_desc = _pick_text(shot.get("ff_desc"), schema_v2.get("ff_desc"), head_frame.get("prompt"), limit=240)
    lf_desc = _pick_text(shot.get("lf_desc"), schema_v2.get("lf_desc"), tail_frame.get("prompt"), limit=240)
    motion_desc = _pick_meta_text("motion_desc", limit=260)
    audio_desc = _pick_meta_text("audio_desc", limit=200)
    state_before = _pick_meta_text("state_before", limit=120)
    state_after = _pick_meta_text("state_after", limit=120)

    shot_type = _pick_meta_text("shot_type", limit=48)
    camera_angle = _pick_meta_text("camera_angle", limit=48)
    movement = _pick_text(
        shot.get("movement"),
        shot.get("camera_movement"),
        schema_v2.get("camera_movement"),
        schema_meta.get("camera_movement"),
        limit=64,
    )
    composition = _pick_text(
        shot.get("composition_notes"),
        shot.get("composition"),
        schema_v2.get("composition_notes"),
        schema_v2.get("composition"),
        schema_meta.get("composition_notes"),
        schema_meta.get("composition"),
        limit=120,
    )
    location = _pick_meta_text("location", limit=120)
    time_text = _pick_meta_text("time", limit=64)
    atmosphere = _pick_meta_text("atmosphere", limit=120)
    emotion = _pick_meta_text("emotion", limit=48)
    variation_type = _pick_meta_text("variation_type", limit=32)
    variation_reason = _pick_meta_text("variation_reason", limit=120)
    scene_id = _text(shot.get("scene_id"), limit=32)
    shot_id = _text(shot.get("shot_id"), limit=32)
    cam_idx = _pick_text(
        shot.get("cam_idx"),
        shot.get("camera_index"),
        schema_v2.get("cam_idx"),
        schema_v2.get("camera_index"),
        limit=16,
    )

    audio_sync = _pick_meta_text("audio_sync", limit=240)
    audio_policy = _build_audio_policy_hint()
    character_ids = _pick_meta_any("character_ids")

    if not motion_desc:
        motion_desc = _join_prompt_parts(
            [
                desc[:120],
                "动作连续且自然过渡",
                "镜头语言稳定清晰",
                "保持节奏与叙事焦点",
            ],
            sep="，",
            max_parts=4,
        )

    motion_level = _pick_meta_text("motion_level", limit=16).lower()
    if motion_level not in {"small", "medium", "large"}:
        motion_level = _infer_motion_level(desc=desc, motion_desc=motion_desc)
    if state_before and state_after:
        if state_before == state_after:
            motion_level = "small"
        elif motion_level == "small":
            motion_level = "medium"

    if motion_level == "small":
        motion_control = "运动强度：small；优先微动作、微表情与局部景别变化，避免大幅位移。"
    elif motion_level == "large":
        motion_control = "运动强度：large；允许明显走位和镜头运动，但保持主体可读性与构图稳定。"
    else:
        motion_control = "运动强度：medium；主体动作和镜头运动适中，突出叙事信息。"

    vis_chars = _as_str_list(_pick_meta_any("ff_vis_char_ids")) + _as_str_list(_pick_meta_any("lf_vis_char_ids"))
    vis_chars = [c for i, c in enumerate(vis_chars) if c and c not in vis_chars[:i]]
    vis_hint = f"可见角色：{', '.join(vis_chars[:6])}" if vis_chars else ""

    fragment_hint = _compact_prompt_fragment(prompt_fragment, limit=220)

    subshots_raw = _pick_meta_any("subshots")
    subshots = subshots_raw if isinstance(subshots_raw, list) else []
    multishot_enabled = str(os.getenv("DREAMWEAVER_WAN_I2V_MULTISHOT_PROMPT", "1") or "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }
    is_multishot = bool(multishot_enabled and subshots)

    override = _pick_text(shot.get("video_prompt_override"), schema_meta.get("video_prompt_override"))
    if override:
        max_chars_default = 1200 if is_multishot else 680
        max_chars = _parse_int(os.getenv("DREAMWEAVER_WAN_I2V_PROMPT_MAX_CHARS"), max_chars_default)
        max_chars = max(240, min(max_chars, 1800))
        if len(override) > max_chars:
            override = override[:max_chars].rstrip("，； ")
        return override

    duration_s = normalize_wan_i2v_duration_s(shot.get("duration_s"), default=15.0)

    prompt = ""
    if is_multishot:
        def _sec(value: Any) -> int:
            try:
                return int(round(float(value)))
            except Exception:  # noqa: BLE001
                return 0

        header: List[str] = [f"镜头任务：生成 {int(duration_s)} 秒连续视频，时间轴 0-{int(duration_s)}s。"]
        if scene_id:
            header.append(f"场景ID：{scene_id}")
        if shot_id:
            header.append(f"镜头ID：{shot_id}")
        if cam_idx:
            header.append(f"机位：{cam_idx}")
        if shot_type:
            header.append(f"镜头类型：{shot_type}")
        if camera_angle:
            header.append(f"镜头角度：{camera_angle}")
        if movement:
            header.append(f"镜头运动：{movement}")
        if composition:
            header.append(f"构图：{composition}")
        if location:
            header.append(f"地点：{location}")
        if time_text:
            header.append(f"时间：{time_text}")
        if atmosphere:
            header.append(f"氛围：{atmosphere}")
        if emotion:
            header.append(f"情绪：{emotion}")
        if variation_type:
            header.append(f"变化幅度：{variation_type}")
        if variation_reason:
            header.append(f"变化原因：{variation_reason}")
        if visual_desc:
            header.append(f"视觉描述：{visual_desc}")
        if desc:
            header.append(f"剧情动作：{desc}")
        if ff_desc:
            header.append(f"首帧语义：{ff_desc}")
        if lf_desc:
            header.append(f"尾帧语义：{lf_desc}")
        if motion_desc:
            header.append(f"运动描述：{motion_desc}")
        if state_before:
            header.append(f"前状态：{state_before}")
        if state_after:
            header.append(f"后状态：{state_after}")
        if audio_desc:
            header.append(f"音频提示：{audio_desc}")
        if audio_sync:
            header.append(f"音画同步：{audio_sync}")
        if audio_policy:
            header.append(audio_policy)
        if vis_hint:
            header.append(vis_hint)
        if character_ids and isinstance(character_ids, list) and character_ids:
            header.append(f"角色ID：{', '.join([str(c) for c in character_ids[:6]])}")
        if fragment_hint:
            header.append(f"素材补充：{fragment_hint}")
        if motion_control:
            header.append(motion_control)
        header.append(consistency_line)
        if frame_ratio:
            header.append(f"画幅：{frame_ratio}")
        if style_prompt:
            header.append(f"风格：{style_prompt}")
        if soft_negative:
            header.append(soft_negative)

        lines: List[str] = []
        lines.append(_join_prompt_parts(header, sep="；", max_parts=36))
        lines.append("时间轴分镜：")

        cursor = 0
        valid_subshots = 0
        for idx, raw in enumerate(subshots[:12]):
            if not isinstance(raw, dict):
                continue
            start = _sec(raw.get("start_s"))
            end = _sec(raw.get("end_s"))
            if idx == 0:
                start = 0
            if end <= start:
                continue

            cursor = max(cursor, end)
            if cursor > int(duration_s):
                cursor = int(duration_s)

            sub_parts: List[str] = []
            trans_s = _text(raw.get("transition"), limit=40)
            shot_type_s = _text(raw.get("shot_type"), limit=40)
            angle_s = _text(raw.get("camera_angle"), limit=40)
            move_s = _text(raw.get("camera_movement"), limit=40)
            emo_s = _text(raw.get("emotion"), limit=40)
            sub_desc = _pick_text(raw.get("desc"), raw.get("visual_desc"), visual_desc, motion_desc, desc, limit=220)

            if idx > 0 and trans_s:
                sub_parts.append(f"转场={trans_s}")
            if shot_type_s:
                sub_parts.append(f"镜头={shot_type_s}")
            if angle_s:
                sub_parts.append(f"角度={angle_s}")
            if move_s:
                sub_parts.append(f"运动={move_s}")
            if emo_s:
                sub_parts.append(f"情绪={emo_s}")
            if sub_desc:
                sub_parts.append(f"内容={sub_desc}")
            if not sub_parts:
                continue

            lines.append(f"[{start}-{end}s] " + _join_prompt_parts(sub_parts, sep="，", max_parts=8))
            valid_subshots += 1
            if cursor >= int(duration_s):
                break

        if valid_subshots <= 0:
            fallback = _pick_text(motion_desc, lf_desc, desc, visual_desc, limit=220) or "保持同一场景内的连续动作与叙事焦点。"
            lines.append(f"[0-{int(duration_s)}s] {fallback}")
            cursor = int(duration_s)

        if cursor < int(duration_s):
            tail_desc = _pick_text(lf_desc, motion_desc, desc, visual_desc, limit=220) or "收束镜头并稳定在尾帧语义。"
            lines.append(f"[{max(0, cursor)}-{int(duration_s)}s] {tail_desc}")

        prompt = "\n".join([line for line in lines if line.strip()])
    else:
        parts: List[str] = []
        if scene_id:
            parts.append(f"场景ID：{scene_id}")
        if shot_id:
            parts.append(f"镜头ID：{shot_id}")
        if cam_idx:
            parts.append(f"机位：{cam_idx}")
        if shot_type:
            parts.append(f"镜头类型：{shot_type}")
        if camera_angle:
            parts.append(f"镜头角度：{camera_angle}")
        if movement:
            parts.append(f"镜头运动：{movement}")
        if composition:
            parts.append(f"构图：{composition}")
        if location:
            parts.append(f"地点：{location}")
        if time_text:
            parts.append(f"时间：{time_text}")
        if atmosphere:
            parts.append(f"氛围：{atmosphere}")
        if emotion:
            parts.append(f"情绪：{emotion}")
        if variation_type:
            parts.append(f"变化幅度：{variation_type}")
        if variation_reason:
            parts.append(f"变化原因：{variation_reason}")
        if visual_desc:
            parts.append(f"视觉描述：{visual_desc}")
        if desc:
            parts.append(f"剧情动作：{desc}")
        if ff_desc:
            parts.append(f"首帧语义：{ff_desc}")
        if lf_desc:
            parts.append(f"尾帧语义：{lf_desc}")
        if motion_desc:
            parts.append(f"运动描述：{motion_desc}")
        if state_before:
            parts.append(f"前状态：{state_before}")
        if state_after:
            parts.append(f"后状态：{state_after}")
        if audio_desc:
            parts.append(f"音频提示：{audio_desc}")
        if audio_sync:
            parts.append(f"音画同步：{audio_sync}")
        if audio_policy:
            parts.append(audio_policy)
        if vis_hint:
            parts.append(vis_hint)
        if character_ids and isinstance(character_ids, list):
            parts.append(f"角色ID：{', '.join([str(c) for c in character_ids[:6]])}")
        if fragment_hint:
            parts.append(f"素材补充：{fragment_hint}")
        if motion_control:
            parts.append(motion_control)
        parts.append(consistency_line)
        if frame_ratio:
            parts.append(f"画幅：{frame_ratio}")
        if style_prompt:
            parts.append(f"风格：{style_prompt}")
        if soft_negative:
            parts.append(soft_negative)

        prompt = _join_prompt_parts(parts, sep="；", max_parts=36)

    max_chars_default = 1200 if is_multishot else 680
    max_chars = _parse_int(os.getenv("DREAMWEAVER_WAN_I2V_PROMPT_MAX_CHARS"), max_chars_default)
    max_chars = max(240, min(max_chars, 1800))
    if len(prompt) > max_chars:
        prompt = prompt[:max_chars].rstrip("，；。 ")
    return prompt


def _store_video_prompt_generated(shot: Dict[str, Any], prompt: str) -> None:
    if not isinstance(shot, dict):
        return
    value = str(prompt or "").strip()
    if not value:
        return
    meta = shot.get("shot_schema_v2_meta")
    if not isinstance(meta, dict):
        meta = {}
        shot["shot_schema_v2_meta"] = meta
    meta["video_prompt_generated"] = value

    # 同步到前端读取路径 shot_schema_v2.meta，避免弹窗缺失。
    shot_schema_v2 = shot.get("shot_schema_v2")
    if isinstance(shot_schema_v2, dict):
        schema_meta = shot_schema_v2.get("meta") if isinstance(shot_schema_v2.get("meta"), dict) else {}
        schema_meta["video_prompt_generated"] = value
        shot_schema_v2["meta"] = schema_meta
        shot["shot_schema_v2"] = shot_schema_v2


def _is_legacy_video_prompt(prompt: str, *, shot: Optional[Dict[str, Any]] = None) -> bool:
    text = str(prompt or "").strip()
    if not text:
        return True
    if any(token in text for token in ("首帧:", "尾帧:", "单格分镜")):
        return True

    has_subshots = False
    if isinstance(shot, dict):
        for container in (
            shot,
            shot.get("shot_schema_v2") if isinstance(shot.get("shot_schema_v2"), dict) else None,
            shot.get("shot_schema_v2_meta") if isinstance(shot.get("shot_schema_v2_meta"), dict) else None,
        ):
            if not isinstance(container, dict):
                continue
            subshots = container.get("subshots")
            if isinstance(subshots, list) and subshots:
                has_subshots = True
                break
    if has_subshots and "时间轴分镜" not in text and re.search(r"\[\d+\-\d+s\]", text) is None:
        return True
    return False


def ensure_storyboard_video_prompts(payload: Dict[str, Any], *, force: bool = False) -> int:
    """
    批量为 storyboard 写入自动视频提示词。
    - 供提示词审核阶段直接展示，不必等待 VIDEO 阶段。
    """
    if not isinstance(payload, dict):
        return 0
    ensure_media_payload(payload)

    storyboard = payload.get("storyboard")
    if not isinstance(storyboard, list) or not storyboard:
        return 0

    video_cfg = payload.get("video_config") if isinstance(payload.get("video_config"), dict) else {}
    image_cfg = payload.get("image_config") if isinstance(payload.get("image_config"), dict) else {}

    style_preset = str(payload.get("style_preset") or "").strip()
    frame_ratio = str(image_cfg.get("ratio") or "").strip() or "16:9"
    engine = str(video_cfg.get("engine") or os.getenv("DREAMWEAVER_VIDEO_ENGINE") or "wan_i2v").strip().lower()
    if engine not in {"wan_i2v", "i2v", "wan_t2v", "wan26_t2v", "t2v", "wan_auto", "auto"}:
        engine = "wan_i2v"

    lib_assets = _library_assets_from_payload(payload)
    updated = 0

    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if not shot_id:
            continue

        existing = ""
        raw_meta = item.get("shot_schema_v2_meta")
        if isinstance(raw_meta, dict):
            existing = str(raw_meta.get("video_prompt_generated") or "").strip()
        if existing and not force:
            if _is_legacy_video_prompt(existing, shot=item):
                existing = ""
            else:
                _store_video_prompt_generated(item, existing)
                continue

        asset_match = _match_library_assets_for_shot(shot=item, library_assets=lib_assets, max_character_refs=3)
        prompt_fragment = str(asset_match.get("prompt_fragment") or "").strip()
        generated = _build_wan_i2v_prompt(
            shot=item,
            style_preset=style_preset,
            frame_ratio=frame_ratio,
            prompt_fragment=prompt_fragment,
            engine=engine,
        )
        if not generated:
            continue
        _store_video_prompt_generated(item, generated)
        updated += 1

    return updated


def _clone_adapter_instance(adapter: Any) -> Optional[Any]:
    cfg = getattr(adapter, "config", None)
    if cfg is None:
        return None
    try:
        return adapter.__class__(cfg)
    except Exception:  # noqa: BLE001
        return None


def _close_adapter_session(adapter: Any) -> None:
    session = getattr(adapter, "session", None)
    try:
        if session is not None:
            session.close()
    except Exception:  # noqa: BLE001
        pass


def _write_video_from_generation_result(result: GenerationResult, out_path: Path) -> None:
    if not result.success:
        raise RuntimeError(result.error or "WAN video generate failed")

    data = result.data
    if isinstance(data, dict):
        url = data.get("video_url") or data.get("url")
        if isinstance(url, str) and url:
            _download_url_to_path(url, out_path, timeout_s=300.0, max_retries=2)
            return

        b64 = data.get("b64_json") or data.get("base64") or data.get("video_base64")
        if isinstance(b64, str) and b64:
            out_path.write_bytes(base64.b64decode(b64))
            return

    raise RuntimeError("WAN video response unsupported: missing video_url/base64 payload")


def _render_slideshow_clip(
    *,
    ffmpeg: str,
    head: Path,
    mid: Optional[Path],
    tail: Path,
    out: Path,
    duration_s: float,
    fps: int = 24,
    width: int = 1280,
    height: int = 720,
    effect: Optional[str] = None,
) -> None:
    effect_value = _resolve_slideshow_effect(effect)
    has_mid = bool(mid and mid.exists())
    if has_mid:
        first_s = max(duration_s / 3.0, 0.1)
        middle_s = max(duration_s / 3.0, 0.1)
        last_s = max(duration_s - first_s - middle_s, 0.1)
    else:
        first_s = max(duration_s / 2.0, 0.1)
        second_s = max(duration_s - first_s, 0.1)

    if effect_value != "static":
        try:
            zoom_step = float(os.getenv("DREAMWEAVER_SLIDESHOW_ZOOM_STEP", "0.0008") or "0.0008")
        except Exception:  # noqa: BLE001
            zoom_step = 0.0008
        zoom_step = max(0.0001, min(0.01, zoom_step))
        try:
            max_zoom = float(os.getenv("DREAMWEAVER_SLIDESHOW_MAX_ZOOM", "1.08") or "1.08")
        except Exception:  # noqa: BLE001
            max_zoom = 1.08
        max_zoom = max(1.0, min(2.0, max_zoom))

        def _kb_stream(input_index: int, frames: int, out_label: str) -> str:
            safe_frames = max(1, int(frames))
            return (
                f"[{input_index}:v]"
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
                f"zoompan=z='min(zoom+{zoom_step:.6f},{max_zoom:.3f})':"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d={safe_frames}:s={width}x{height}:fps={int(fps)},"
                "format=yuv420p,setsar=1,setpts=PTS-STARTPTS"
                f"[{out_label}]"
            )

        if has_mid and mid is not None:
            first_frames = max(1, int(round(first_s * fps)))
            middle_frames = max(1, int(round(middle_s * fps)))
            last_frames = max(1, int(round(last_s * fps)))
            filter_complex = (
                f"{_kb_stream(0, first_frames, 'v0')};"
                f"{_kb_stream(1, middle_frames, 'v1')};"
                f"{_kb_stream(2, last_frames, 'v2')};"
                "[v0][v1][v2]concat=n=3:v=1:a=0,format=yuv420p[v]"
            )
            cmd = [
                ffmpeg,
                "-y",
                "-i",
                str(head),
                "-i",
                str(mid),
                "-i",
                str(tail),
                "-filter_complex",
                filter_complex,
                "-map",
                "[v]",
                "-r",
                str(int(fps)),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(out),
            ]
        else:
            first_frames = max(1, int(round(first_s * fps)))
            second_frames = max(1, int(round(second_s * fps)))
            filter_complex = (
                f"{_kb_stream(0, first_frames, 'v0')};"
                f"{_kb_stream(1, second_frames, 'v1')};"
                "[v0][v1]concat=n=2:v=1:a=0,format=yuv420p[v]"
            )
            cmd = [
                ffmpeg,
                "-y",
                "-i",
                str(head),
                "-i",
                str(tail),
                "-filter_complex",
                filter_complex,
                "-map",
                "[v]",
                "-r",
                str(int(fps)),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(out),
            ]

        _run_ffmpeg(cmd, log_dir=out.parent, log_prefix=f"ffmpeg_slideshow_{out.stem}_kb")
        return

    if has_mid and mid is not None:
        filter_complex = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p[v0];"
            f"[1:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p[v1];"
            f"[2:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p[v2];"
            "[v0][v1][v2]concat=n=3:v=1:a=0,format=yuv420p[v]"
        )
        cmd = [
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-t",
            f"{first_s}",
            "-i",
            str(head),
            "-loop",
            "1",
            "-t",
            f"{middle_s}",
            "-i",
            str(mid),
            "-loop",
            "1",
            "-t",
            f"{last_s}",
            "-i",
            str(tail),
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-r",
            str(int(fps)),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(out),
        ]
    else:
        filter_complex = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p[v0];"
            f"[1:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p[v1];"
            "[v0][v1]concat=n=2:v=1:a=0,format=yuv420p[v]"
        )
        cmd = [
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-t",
            f"{first_s}",
            "-i",
            str(head),
            "-loop",
            "1",
            "-t",
            f"{second_s}",
            "-i",
            str(tail),
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-r",
            str(int(fps)),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(out),
        ]

    _run_ffmpeg(cmd, log_dir=out.parent, log_prefix=f"ffmpeg_slideshow_{out.stem}")


def _run_wan_i2v(
    ctx: Any,
    *,
    run_dir: Path,
    video_cfg: Dict[str, Any],
    width: int,
    height: int,
    regenerate_shot_ids: Optional[set[str]] = None,
    allowed_shot_ids: Optional[set[str]] = None,
    character_manager: Optional[CharacterManager] = None,
) -> None:
    factory = ModelAdapterFactory()
    adapter_name = str(video_cfg.get("adapter") or "wan_i2v").strip() or "wan_i2v"
    i2v = factory.get_adapter(adapter_name)

    ffmpeg = os.getenv("FFMPEG_PATH", "ffmpeg")
    fps = WAN_I2V_OUTPUT_FPS
    motion_bucket_id = int(video_cfg.get("motion_bucket_id") or 127)
    slideshow_effect = _resolve_slideshow_effect(video_cfg.get("slideshow_effect"))

    regen_set = regenerate_shot_ids or set()
    existing_clips_by_shot = _index_video_clips_by_shot(ctx.payload.get("video_clips"))

    style_preset = str(ctx.payload.get("style_preset") or "").strip()
    image_cfg = ctx.payload.get("image_config") if isinstance(ctx.payload.get("image_config"), dict) else {}
    frame_ratio = str(image_cfg.get("ratio") or "").strip() or "16:9"
    lib_assets = _library_assets_from_payload(ctx.payload)

    storyboard = ctx.payload.get("storyboard", [])
    camera_states = ctx.payload.get("camera_states")
    if not isinstance(camera_states, list) or not camera_states:
        try:
            from agents.camera_states import build_camera_states as _build_camera_states
            from agents.camera_tree import build_camera_tree as _build_camera_tree

            camera_tree = ctx.payload.get("camera_tree")
            if not (
                isinstance(camera_tree, list)
                and any(isinstance(n, dict) and isinstance(n.get("cam_idx"), int) for n in camera_tree)
            ):
                camera_tree = _build_camera_tree(storyboard if isinstance(storyboard, list) else [])
                if camera_tree:
                    ctx.payload["camera_tree"] = camera_tree

            camera_states = _build_camera_states(
                storyboard if isinstance(storyboard, list) else [],
                camera_tree if isinstance(camera_tree, list) and camera_tree else None,
            )
            if camera_states:
                ctx.payload["camera_states"] = camera_states
        except Exception:  # noqa: BLE001
            camera_states = None
    camera_state_by_shot_id = _index_camera_states_by_shot_id(camera_states)

    jobs: List[dict] = []
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "")
        if not shot_id:
            continue
        if allowed_shot_ids is not None and shot_id not in allowed_shot_ids:
            continue
        out = run_dir / f"{shot_id}.mp4"
        if out.exists() and shot_id not in regen_set:
            continue
        jobs.append(item)

    video_parallelism = _parse_int(video_cfg.get("parallelism") or os.getenv("DREAMWEAVER_VIDEO_PARALLELISM"), 1)
    video_parallelism = max(1, min(int(video_parallelism), len(jobs) if jobs else 1))
    if video_parallelism > 1:
        probe = _clone_adapter_instance(i2v)
        if probe is None:
            video_parallelism = 1
        else:
            _close_adapter_session(probe)

    def _render_one(
        item: dict,
        *,
        head_override: Optional[Path] = None,
        i2v_input_meta: Optional[Dict[str, Any]] = None,
        disallow_slideshow_fallback: bool = False,
    ) -> dict:
        shot_id = str(item.get("shot_id") or "")
        head = run_dir / f"{shot_id}_head.png"
        tail = run_dir / f"{shot_id}_tail.png"
        mid = run_dir / f"{shot_id}_mid.png"
        out = run_dir / f"{shot_id}.mp4"
        duration_s = normalize_wan_i2v_duration_s(item.get("duration_s"), default=5.0)

        if not head.exists():
            raise RuntimeError(f"missing head frame for i2v: {head}")

        input_head = head_override if isinstance(head_override, Path) else head

        asset_match = _match_library_assets_for_shot(shot=item, library_assets=lib_assets, max_character_refs=3)
        prompt_fragment = str(asset_match.get("prompt_fragment") or "").strip()
        
        character_assets = asset_match.get("character_assets") if isinstance(asset_match.get("character_assets"), list) else []
        character_references: List[Dict[str, Any]] = []
        for char_asset in character_assets:
            char_ref: Dict[str, Any] = {
                "character_id": str(char_asset.get("entity_name") or ""),
                "name": str(char_asset.get("entity_name") or ""),
            }
            descriptor = str(char_asset.get("descriptor") or "")
            if descriptor:
                char_ref["appearance"] = descriptor
            character_references.append(char_ref)
        
        if character_manager:
            try:
                manager_chars = character_manager.get_characters_for_api(shot_id, max_characters=3)
                if manager_chars:
                    character_references = manager_chars
            except Exception as e:
                print(f"获取角色引用失败 ({shot_id}): {e}")
        
        motion_prompt = _build_wan_i2v_prompt(
            shot=item,
            style_preset=style_preset,
            frame_ratio=frame_ratio,
            prompt_fragment=prompt_fragment,
        )
        _store_video_prompt_generated(item, motion_prompt)

        via = "wan_i2v"
        meta: Dict[str, Any] = {"engine": "wan_i2v", "adapter": adapter_name, "fps": fps, "motion_bucket_id": motion_bucket_id}
        seed = _stable_seed(str(getattr(ctx, "run_id", "")), shot_id, "clip")

        default_input_meta = {"mode": "head_keyframe", "reason": "default", "head_path": str(head)}
        primary_input_meta = i2v_input_meta or default_input_meta

        attempts: List[Dict[str, Any]] = []
        candidates: List[Tuple[Path, Dict[str, Any]]] = [(input_head, dict(primary_input_meta))]

        # “尾帧->下镜头首帧桥接”属于连续性增强策略：不允许退化到图片拼接。
        # 但允许在桥接输入失败时，回退到本镜头 head keyframe 继续 I2V（仍保证是真视频片段）。
        if disallow_slideshow_fallback and isinstance(head_override, Path) and head_override.exists() and head_override != head:
            candidates.append(
                (
                    head,
                    {
                        "mode": "head_keyframe",
                        "reason": "bridge_i2v_failed_fallback_to_head_keyframe",
                        "head_path": str(head),
                        "bridge_source": dict(primary_input_meta),
                    },
                )
            )

        try:
            local_i2v = i2v
            if video_parallelism > 1:
                cloned = _clone_adapter_instance(i2v)
                if cloned is None:
                    raise RuntimeError("adapter clone failed for parallel i2v generation")
                local_i2v = cloned

            result = None
            chosen_input_meta: Optional[Dict[str, Any]] = None
            try:
                last_error: Optional[str] = None
                for idx, (candidate_path, candidate_meta) in enumerate(candidates):
                    meta["i2v_input"] = candidate_meta
                    try:
                        result = local_i2v.generate(
                            image_path=str(candidate_path),
                            prompt=motion_prompt,
                            duration=duration_s,
                            fps=fps,
                            motion_bucket_id=motion_bucket_id,
                            seed=seed,
                            character_references=character_references if character_references else None,
                        )
                        _write_video_from_generation_result(result, out)
                        chosen_input_meta = candidate_meta
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_error = str(exc)
                        attempts.append(
                            {
                                "attempt": idx + 1,
                                "image_path": str(candidate_path),
                                "input_meta": candidate_meta,
                                "error": last_error,
                            }
                        )
                        result = None
                        chosen_input_meta = None
                        continue

                if result is None or chosen_input_meta is None:
                    raise RuntimeError(last_error or "wan_i2v generate failed")
            finally:
                if local_i2v is not i2v:
                    _close_adapter_session(local_i2v)

            if isinstance(result.data, dict) and isinstance(result.data.get("video_url"), str):
                meta["remote_url"] = result.data["video_url"]
            if isinstance(getattr(result, "metadata", None), dict):
                image_input_mode = result.metadata.get("image_input_mode")
                if isinstance(image_input_mode, str) and image_input_mode.strip():
                    meta["image_input_mode"] = image_input_mode.strip()
            meta["seed"] = seed
            if attempts:
                meta["i2v_attempts"] = attempts
            meta["i2v_input"] = chosen_input_meta
        except Exception as exc:  # noqa: BLE001
            if disallow_slideshow_fallback:
                meta["error"] = str(exc)
                meta["strict_i2v"] = True
                if attempts and "i2v_attempts" not in meta:
                    meta["i2v_attempts"] = attempts
                raise

            via = "ffmpeg_slideshow_fallback"
            meta["error"] = str(exc)
            meta["slideshow_effect"] = slideshow_effect
            _render_slideshow_clip(
                ffmpeg=ffmpeg,
                head=input_head,
                mid=mid if mid.exists() else None,
                tail=tail,
                out=out,
                duration_s=duration_s,
                fps=fps,
                width=width,
                height=height,
                effect=slideshow_effect,
            )

        return {
            "path": str(out),
            "duration": duration_s,
            "head": str(head),
            "mid": str(mid) if mid.exists() else None,
            "tail": str(tail),
            "meta": {**meta, "via": via, "motion_prompt": motion_prompt[:240]},
        }

    # 若存在“上一镜头视频尾帧 -> 下一镜头首帧”的依赖，则强制串行生成，避免并发打乱依赖关系。
    needs_bridge = False
    prev_item: Optional[dict] = None
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if not shot_id:
            continue
        inferred = _infer_i2v_head_source(
            prev_shot=prev_item,
            shot=item,
            camera_state=camera_state_by_shot_id.get(shot_id),
        )
        if (allowed_shot_ids is None or shot_id in allowed_shot_ids) and str(inferred.get("mode") or "") == "prev_clip_tail":
            needs_bridge = True
            break
        prev_item = item
    if needs_bridge:
        video_parallelism = 1

    generated: List[dict] = []
    if video_parallelism <= 1 or len(jobs) <= 1:
        # 串行：在 storyboard 顺序下填充 prev_clip_path，用于尾帧抽取。
        prev_clip_path: Optional[Path] = None
        prev_shot_id: Optional[str] = None
        prev_item = None

        def _resolve_clip_path(shot_key: str) -> Optional[Path]:
            key = str(shot_key or "").strip()
            if not key:
                return None
            existing = existing_clips_by_shot.get(key)
            if isinstance(existing, dict) and isinstance(existing.get("path"), str):
                p = Path(str(existing.get("path") or "")).expanduser()
                if p.exists():
                    return p
            p = run_dir / f"{key}.mp4"
            return p if p.exists() else None

        for item in storyboard:
            if not isinstance(item, dict):
                continue
            shot_id = str(item.get("shot_id") or "").strip()
            if not shot_id:
                continue

            out = run_dir / f"{shot_id}.mp4"
            existing = existing_clips_by_shot.get(shot_id)
            existing_path = Path(str(existing.get("path") or out)) if isinstance(existing, dict) else out
            if not existing_path.exists() and out.exists():
                existing_path = out

            if allowed_shot_ids is not None and shot_id not in allowed_shot_ids:
                prev_clip_path = existing_path if existing_path.exists() else None
                prev_shot_id = shot_id
                prev_item = item
                continue

            if existing_path.exists() and shot_id not in regen_set:
                prev_clip_path = existing_path
                prev_shot_id = shot_id
                prev_item = item
                continue

            head_override: Optional[Path] = None
            input_meta: Optional[Dict[str, Any]] = None
            inferred = _infer_i2v_head_source(
                prev_shot=prev_item,
                shot=item,
                camera_state=camera_state_by_shot_id.get(shot_id),
            )
            bridge_required = str(inferred.get("mode") or "") == "prev_clip_tail"
            dep_shot_id = str(inferred.get("depends_on_shot_id") or "").strip() if bridge_required else ""
            dep_clip_path = _resolve_clip_path(dep_shot_id) if dep_shot_id else None

            if bridge_required and allowed_shot_ids is not None and (dep_clip_path is None or not dep_clip_path.exists()):
                prev_clip_path = None
                prev_shot_id = shot_id
                prev_item = item
                continue
            if bridge_required and dep_clip_path is not None and dep_clip_path.exists():
                tail_frame = run_dir / f"{Path(dep_clip_path).stem}_clip_tail.png"
                try:
                    _extract_video_tail_frame(
                        ffmpeg=ffmpeg,
                        video_path=dep_clip_path,
                        out_path=tail_frame,
                        width=width,
                        height=height,
                    )
                    if tail_frame.exists():
                        head_override = tail_frame
                        input_meta = {
                            "mode": "prev_clip_tail",
                            "reason": inferred.get("reason"),
                            "depends_on_shot_id": dep_shot_id or None,
                            "depends_on_clip_path": str(dep_clip_path),
                            "tail_frame_path": str(tail_frame),
                            "prev_state_after": inferred.get("prev_state_after"),
                            "state_before": inferred.get("state_before"),
                            "anchor_source": inferred.get("anchor_source"),
                            "anchor_shot_id": inferred.get("anchor_shot_id"),
                            "cam_idx": _shot_cam_idx(item),
                        }
                except Exception as exc:  # noqa: BLE001
                    input_meta = {
                        "mode": "head_keyframe_fallback",
                        "reason": "extract_prev_clip_tail_failed",
                        "depends_on_shot_id": dep_shot_id or None,
                        "depends_on_clip_path": str(dep_clip_path) if dep_clip_path is not None else None,
                        "error": str(exc),
                        "cam_idx": _shot_cam_idx(item),
                    }

            clip = _render_one(
                item,
                head_override=head_override,
                i2v_input_meta=input_meta,
                disallow_slideshow_fallback=bridge_required,
            )
            generated.append(clip)
            prev_clip_path = Path(str(clip.get("path") or out))
            prev_shot_id = shot_id
            prev_item = item
    else:
        # 并行：无跨镜头首帧依赖时，保持原并发行为。
        ordered: List[Optional[dict]] = [None] * len(jobs)
        with ThreadPoolExecutor(max_workers=video_parallelism) as pool:
            futures = {pool.submit(_render_one, item): idx for idx, item in enumerate(jobs)}
            for fut in as_completed(futures):
                idx = futures[fut]
                ordered[idx] = fut.result()
        generated = [c for c in ordered if isinstance(c, dict)]

    for clip in generated:
        path = clip.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        shot_key = Path(path).stem
        if shot_key:
            existing_clips_by_shot[shot_key] = clip

    merged: List[dict] = []
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "")
        if not shot_id:
            continue
        clip = existing_clips_by_shot.get(shot_id)
        if isinstance(clip, dict):
            merged.append(clip)

    audio_sync_enabled = _env_flag("DREAMWEAVER_AUDIO_SYNC_ENABLED", default=True)
    dialogue_embed = _env_flag("DREAMWEAVER_DIALOGUE_AUDIO_EMBED", default=False)
    if audio_sync_enabled and dialogue_embed and merged:
        try:
            audio_manager = AudioSyncManager(run_dir=run_dir, batch_id=batch_id, cache_dir=audio_cache_dir)
            audio_clips: List[Dict[str, Any]] = []
            
            for clip in merged:
                shot_id = Path(clip.get("path") or "").stem
                if not shot_id:
                    continue
                
                shot_item = None
                for item in storyboard:
                    if isinstance(item, dict) and str(item.get("shot_id") or "") == shot_id:
                        shot_item = item
                        break
                
                if not shot_item:
                    continue
                
                audio_sync_marker = shot_item.get("audio_sync")
                if not audio_sync_marker:
                    continue
                
                video_path = Path(clip.get("path") or "")
                
                if not video_path.exists():
                    continue
                
                try:
                    audio_map = audio_manager.generate_audio_for_storyboard(
                        storyboard=[shot_item],
                        character_manager=character_manager,
                    )
                    
                    generated_audio_path = audio_map.get(shot_id)
                    if generated_audio_path and Path(generated_audio_path).exists():
                        output_with_audio = run_dir / f"{shot_id}_with_audio.mp4"
                        if audio_manager.sync_audio_to_video(
                            video_path=str(video_path),
                            audio_path=generated_audio_path,
                            output_path=str(output_with_audio),
                            start_time=0.0,
                            volume=1.0,
                            fade_in=0.1,
                            fade_out=0.1
                        ):
                            clip["audio_path"] = generated_audio_path
                            clip["path_with_audio"] = str(output_with_audio)
                            clip["has_audio"] = True
                            audio_clips.append(clip)
                except Exception as e:
                    print(f"音频同步失败 ({shot_id}): {e}")
                    clip["has_audio"] = False
                    clip["audio_error"] = str(e)
            
            if audio_clips:
                for clip in merged:
                    shot_id = Path(clip.get("path") or "").stem
                    for audio_clip in audio_clips:
                        if Path(audio_clip.get("path") or "").stem == shot_id:
                            clip.update(audio_clip)
                            break
        except Exception as e:
            print(f"音频同步初始化失败: {e}")

    ctx.payload["video_clips"] = merged


def _run_wan_t2v(
    ctx: Any,
    *,
    run_dir: Path,
    video_cfg: Dict[str, Any],
    width: int,
    height: int,
    fps: int,
    regenerate_shot_ids: Optional[set[str]] = None,
    allowed_shot_ids: Optional[set[str]] = None,
) -> None:
    factory = ModelAdapterFactory()
    adapter_name = str(video_cfg.get("adapter") or "wan_t2v").strip() or "wan_t2v"
    t2v = factory.get_adapter(adapter_name)

    regen_set = regenerate_shot_ids or set()
    existing_clips_by_shot = _index_video_clips_by_shot(ctx.payload.get("video_clips"))

    style_preset = str(ctx.payload.get("style_preset") or "").strip()
    image_cfg = ctx.payload.get("image_config") if isinstance(ctx.payload.get("image_config"), dict) else {}
    frame_ratio = str(image_cfg.get("ratio") or "").strip() or "16:9"
    lib_assets = _library_assets_from_payload(ctx.payload)

    storyboard = ctx.payload.get("storyboard", [])
    jobs: List[dict] = []
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if not shot_id:
            continue
        if allowed_shot_ids is not None and shot_id not in allowed_shot_ids:
            continue
        out = run_dir / f"{shot_id}.mp4"
        if out.exists() and shot_id not in regen_set:
            continue
        jobs.append(item)

    video_parallelism = _parse_int(video_cfg.get("parallelism") or os.getenv("DREAMWEAVER_VIDEO_PARALLELISM"), 1)
    video_parallelism = max(1, min(int(video_parallelism), len(jobs) if jobs else 1))
    if video_parallelism > 1:
        probe = _clone_adapter_instance(t2v)
        if probe is None:
            video_parallelism = 1
        else:
            _close_adapter_session(probe)

    def _render_one(item: dict) -> dict:
        shot_id = str(item.get("shot_id") or "").strip()
        out = run_dir / f"{shot_id}.mp4"
        duration_s = normalize_wan_i2v_duration_s(item.get("duration_s"), default=5.0)

        asset_match = _match_library_assets_for_shot(shot=item, library_assets=lib_assets, max_character_refs=3)
        prompt_fragment = str(asset_match.get("prompt_fragment") or "").strip()

        prompt = _build_wan_i2v_prompt(
            shot=item,
            style_preset=style_preset,
            frame_ratio=frame_ratio,
            prompt_fragment=prompt_fragment,
            engine="wan_t2v",
        )
        _store_video_prompt_generated(item, prompt)

        seed = _stable_seed(str(getattr(ctx, "run_id", "")), shot_id, "t2v_clip")
        meta: Dict[str, Any] = {"engine": "wan_t2v", "adapter": adapter_name, "fps": fps, "width": width, "height": height, "seed": seed}

        local_t2v = t2v
        if video_parallelism > 1:
            cloned = _clone_adapter_instance(t2v)
            if cloned is None:
                raise RuntimeError("adapter clone failed for parallel t2v generation")
            local_t2v = cloned

        try:
            kwargs: Dict[str, Any] = {
                "prompt": prompt,
                "width": int(width),
                "height": int(height),
                "duration": float(duration_s),
                "fps": int(fps),
                "seed": int(seed),
            }
            steps = video_cfg.get("num_inference_steps")
            if steps is not None:
                kwargs["num_inference_steps"] = int(steps)
            guidance = video_cfg.get("guidance_scale")
            if guidance is not None:
                kwargs["guidance_scale"] = float(guidance)

            result = local_t2v.generate(**kwargs)
        finally:
            if local_t2v is not t2v:
                _close_adapter_session(local_t2v)

        _write_video_from_generation_result(result, out)
        if isinstance(result.data, dict) and isinstance(result.data.get("video_url"), str):
            meta["remote_url"] = result.data["video_url"]

        return {"path": str(out), "duration": float(duration_s), "meta": {**meta, "via": "wan_t2v", "prompt": prompt[:240]}}

    generated_by_shot: Dict[str, Dict[str, Any]] = {}
    if video_parallelism <= 1 or len(jobs) <= 1:
        for item in jobs:
            clip = _render_one(item)
            sid = Path(str(clip.get("path") or "")).stem
            if sid:
                generated_by_shot[sid] = clip
    else:
        with ThreadPoolExecutor(max_workers=int(video_parallelism)) as pool:
            futures = [pool.submit(_render_one, item) for item in jobs]
            for fut in as_completed(futures):
                clip = fut.result()
                sid = Path(str(clip.get("path") or "")).stem
                if sid:
                    generated_by_shot[sid] = clip

    clips_by_shot: Dict[str, Dict[str, Any]] = dict(existing_clips_by_shot)
    clips_by_shot.update(generated_by_shot)

    merged: List[dict] = []
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if not shot_id:
            continue
        existing = clips_by_shot.get(shot_id)
        if allowed_shot_ids is not None and shot_id not in allowed_shot_ids:
            if isinstance(existing, dict):
                merged.append(existing)
            continue

        if isinstance(existing, dict):
            merged.append(existing)
            continue

        out = run_dir / f"{shot_id}.mp4"
        if out.exists():
            duration_s = normalize_wan_i2v_duration_s(item.get("duration_s"), default=5.0)
            merged.append(
                {
                    "path": str(out),
                    "duration": float(duration_s),
                    "meta": {"engine": "wan_t2v", "via": "wan_t2v", "fps": fps, "width": width, "height": height},
                }
            )

    ctx.payload["video_clips"] = merged


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_audio_batch_id(payload: Dict[str, Any]) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    raw = str(payload.get("batch_id") or "").strip()
    if raw:
        return raw
    project_id = payload.get("project_id") or payload.get("source_project_id")
    if project_id is not None:
        try:
            project_id_str = str(int(project_id))
        except Exception:  # noqa: BLE001
            project_id_str = str(project_id).strip()
        if project_id_str:
            return f"dw_project_{project_id_str}"
    run_id = str(payload.get("run_id") or "").strip()
    return run_id or None


def _resolve_audio_cache_dir(payload: Dict[str, Any]) -> Optional[Path]:
    if not isinstance(payload, dict):
        return None
    project_id = payload.get("project_id") or payload.get("source_project_id")
    if project_id is None:
        return None
    try:
        project_id_str = str(int(project_id))
    except Exception:  # noqa: BLE001
        project_id_str = str(project_id).strip()
    if not project_id_str:
        return None
    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "_", project_id_str)
    return Path("runs") / "_audio_cache" / f"project_{safe_id}"


def _index_video_clip_jobs_by_shot(items: Any) -> Dict[str, Dict[str, Any]]:
    jobs: Dict[str, Dict[str, Any]] = {}
    if not isinstance(items, list):
        return jobs
    for item in items:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if not shot_id:
            continue
        jobs[shot_id] = item
    return jobs


def _all_storyboard_shots_have_video(*, storyboard: Any, run_dir: Path) -> bool:
    if not isinstance(storyboard, list) or not storyboard:
        return False
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if not shot_id:
            continue
        if not (run_dir / f"{shot_id}.mp4").exists():
            return False
    return True


def _build_video_clip_jobs(
    *,
    storyboard: Any,
    run_dir: Path,
    existing_jobs_by_shot: Dict[str, Dict[str, Any]],
    existing_clips_by_shot: Dict[str, Dict[str, Any]],
    requested_shot_ids: set[str],
    bridge_enabled: bool,
    camera_states: Any = None,
) -> List[Dict[str, Any]]:
    jobs: List[Dict[str, Any]] = []
    if not isinstance(storyboard, list):
        return jobs

    camera_state_by_shot_id = _index_camera_states_by_shot_id(camera_states)
    if bridge_enabled and not camera_state_by_shot_id and _env_flag("DREAMWEAVER_I2V_CAMERA_STATE_BRIDGE", default=True):
        try:
            from agents.camera_states import build_camera_states as _build_camera_states
            from agents.camera_tree import build_camera_tree as _build_camera_tree

            camera_tree = _build_camera_tree(storyboard)
            built = _build_camera_states(storyboard, camera_tree if isinstance(camera_tree, list) and camera_tree else None)
            camera_state_by_shot_id = _index_camera_states_by_shot_id(built)
        except Exception:  # noqa: BLE001
            camera_state_by_shot_id = {}

    prev_item: Optional[Dict[str, Any]] = None
    prev_shot_id: Optional[str] = None
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if not shot_id:
            continue

        prior = existing_jobs_by_shot.get(shot_id) if isinstance(existing_jobs_by_shot, dict) else None
        confirmed = bool(prior.get("confirmed")) if isinstance(prior, dict) else False
        if shot_id in requested_shot_ids:
            confirmed = True

        out = run_dir / f"{shot_id}.mp4"
        clip = existing_clips_by_shot.get(shot_id)
        clip_exists = out.exists() or (
            isinstance(clip, dict) and isinstance(clip.get("path"), str) and Path(str(clip.get("path") or "")).exists()
        )

        if bridge_enabled:
            inferred = _infer_i2v_head_source(
                prev_shot=prev_item,
                shot=item,
                camera_state=camera_state_by_shot_id.get(shot_id),
            )
            requires_bridge = str(inferred.get("mode") or "") == "prev_clip_tail"
        else:
            inferred = {"mode": "head_keyframe", "reason": "bridge_disabled"}
            requires_bridge = False
        dep_shot_id = str(inferred.get("depends_on_shot_id") or "").strip() if requires_bridge else ""

        status = "draft"
        if clip_exists:
            status = "done"
        elif confirmed:
            if requires_bridge and dep_shot_id:
                dep_clip_path = run_dir / f"{dep_shot_id}.mp4"
                dep_exists = dep_clip_path.exists()
                if not dep_exists:
                    dep_existing = existing_clips_by_shot.get(dep_shot_id) if isinstance(existing_clips_by_shot, dict) else None
                    dep_path = (
                        Path(str(dep_existing.get("path") or "")) if isinstance(dep_existing, dict) and isinstance(dep_existing.get("path"), str) else None
                    )
                    if dep_path is not None and dep_path.exists():
                        dep_exists = True

                dep_confirmed = dep_shot_id in requested_shot_ids
                if not dep_exists and not dep_confirmed:
                    status = "blocked"
                else:
                    status = "confirmed"
            else:
                status = "confirmed"

        jobs.append(
            {
                "shot_id": shot_id,
                "confirmed": confirmed,
                "status": status,
                "desc": str(item.get("desc") or "").strip(),
                "duration_s": item.get("duration_s"),
                "cam_idx": item.get("cam_idx"),
                "motion_desc": str(item.get("motion_desc") or "").strip(),
                "requires_bridge": requires_bridge,
                "depends_on_shot_id": dep_shot_id if dep_shot_id else None,
                "i2v_head_source": inferred,
                "inputs": {
                    "head": str(run_dir / f"{shot_id}_head.png"),
                    "mid": str(run_dir / f"{shot_id}_mid.png"),
                    "tail": str(run_dir / f"{shot_id}_tail.png"),
                },
                "outputs": {"clip": str(out)},
            }
        )

        prev_item = item
        prev_shot_id = shot_id

    return jobs


def _split_wan_auto_shots(
    *,
    storyboard: Any,
    jobs_by_shot: Dict[str, Dict[str, Any]],
    run_dir: Path,
    requested_shot_ids: set[str],
    regenerate_shot_ids: set[str],
) -> Tuple[set[str], set[str]]:
    """
    wan_auto 路由策略：
    - 默认走 t2v（文本生成视频）
    - 需要参考图桥接（requires_bridge=True）走 i2v
    """
    i2v_shot_ids: set[str] = set()
    t2v_shot_ids: set[str] = set()
    if not isinstance(storyboard, list):
        return i2v_shot_ids, t2v_shot_ids

    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if not shot_id:
            continue
        if requested_shot_ids and shot_id not in requested_shot_ids:
            continue
        out = run_dir / f"{shot_id}.mp4"
        if out.exists() and shot_id not in regenerate_shot_ids:
            continue

        job = jobs_by_shot.get(shot_id) if isinstance(jobs_by_shot, dict) else None
        requires_bridge = bool(job.get("requires_bridge")) if isinstance(job, dict) else False
        if requires_bridge:
            i2v_shot_ids.add(shot_id)
        else:
            t2v_shot_ids.add(shot_id)
    return i2v_shot_ids, t2v_shot_ids


def run_video(ctx: Any) -> None:
    ensure_media_payload(ctx.payload)

    run_dir = Path("runs") / ctx.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    video_cfg = ctx.payload.get("video_config") if isinstance(ctx.payload.get("video_config"), dict) else {}
    image_cfg = ctx.payload.get("image_config") if isinstance(ctx.payload.get("image_config"), dict) else {}
    width, height, _ratio = resolve_frame_size(image_cfg)
    fps = normalize_video_fps(video_cfg.get("fps"), default=24)
    engine = str(video_cfg.get("engine") or os.getenv("DREAMWEAVER_VIDEO_ENGINE") or "ffmpeg_slideshow").strip().lower()
    is_wan_i2v_engine = engine in {"wan_i2v", "i2v"}
    is_wan_t2v_engine = engine in {"wan_t2v", "wan26_t2v", "t2v"}
    is_wan_auto_engine = engine in {"wan_auto", "auto"}
    bridge_enabled = bool(is_wan_i2v_engine or is_wan_auto_engine)
    regen_set = _normalize_regenerate_shot_ids(ctx.payload.get("regenerate_shot_ids"))
    batch_id = _resolve_audio_batch_id(ctx.payload)
    if batch_id and not str(ctx.payload.get("batch_id") or "").strip():
        ctx.payload["batch_id"] = batch_id
    audio_cache_dir = _resolve_audio_cache_dir(ctx.payload)

    audio_sync_enabled = _env_flag("DREAMWEAVER_AUDIO_SYNC_ENABLED", default=True)
    lipsync_mode = str(os.getenv("DREAMWEAVER_DIALOGUE_LIPSYNC_MODE") or "estimate").strip().lower()
    enable_tts_lipsync = audio_sync_enabled and lipsync_mode in {"tts", "tts_lipsync"}
    viseme_tracks_enabled = _env_flag("DREAMWEAVER_LIPSYNC_TRACKS_ENABLED", default=True)

    require_confirmation_cfg = video_cfg.get("require_confirmation")
    require_confirmation = (
        bool(require_confirmation_cfg)
        if isinstance(require_confirmation_cfg, bool)
        else _env_flag("DREAMWEAVER_VIDEO_REQUIRE_CONFIRMATION", default=False)
    )

    storyboard = ctx.payload.get("storyboard", [])
    existing_clips_by_shot = _index_video_clips_by_shot(ctx.payload.get("video_clips"))
    existing_jobs_by_shot = _index_video_clip_jobs_by_shot(ctx.payload.get("video_clip_jobs"))
    requested_shots = set(regen_set)
    for s in existing_jobs_by_shot.values():
        if not isinstance(s, dict):
            continue
        if bool(s.get("confirmed")) and isinstance(s.get("shot_id"), str):
            requested_shots.add(str(s["shot_id"]).strip())

    character_manager = None
    character_profiles = ctx.payload.get("character_profiles", [])
    need_character_manager = bool(isinstance(character_profiles, list) and character_profiles and bridge_enabled) or enable_tts_lipsync
    if need_character_manager:
        try:
            character_manager = CharacterManager(run_dir=run_dir)
            entities = ctx.payload.get("entities")
            if not isinstance(entities, dict) or not entities:
                entities = ctx.payload.get("script_entities", {})
            if isinstance(entities, dict):
                character_manager.auto_assign_characters_from_storyboard(storyboard=storyboard, entities=entities)
        except Exception as e:
            print(f"角色管理器初始化失败: {e}")
            character_manager = None
    if enable_tts_lipsync and isinstance(storyboard, list):
        audio_manager = AudioSyncManager(run_dir=run_dir, batch_id=batch_id, cache_dir=audio_cache_dir)
        existing_tracks = ctx.payload.get("dialogue_tracks") if isinstance(ctx.payload.get("dialogue_tracks"), dict) else {}
        existing_audio_map = ctx.payload.get("dialogue_audio_map") if isinstance(ctx.payload.get("dialogue_audio_map"), dict) else {}
        existing_viseme_tracks = ctx.payload.get("viseme_tracks") if isinstance(ctx.payload.get("viseme_tracks"), dict) else {}
        target_shots = requested_shots if requested_shots else {str(s.get("shot_id") or "") for s in storyboard if isinstance(s, dict)}

        for shot in storyboard:
            if not isinstance(shot, dict):
                continue
            shot_id = str(shot.get("shot_id") or "").strip()
            if not shot_id or shot_id not in target_shots:
                continue

            dialogues = _collect_dialogues_for_shot(shot, audio_manager)
            if not dialogues:
                continue

            if is_wan_i2v_engine or is_wan_t2v_engine or is_wan_auto_engine:
                target_duration_s = normalize_wan_i2v_duration_s(shot.get("duration_s"), default=5.0)
            else:
                try:
                    target_duration_s = float(shot.get("duration_s") or 0.0)
                except Exception:  # noqa: BLE001
                    target_duration_s = 0.0

            tracks = audio_manager.build_dialogue_tracks(
                shot_id=shot_id,
                dialogues=dialogues,
                character_manager=character_manager,
                target_duration_s=target_duration_s,
            )
            if not tracks:
                continue

            shot["dialogue_tracks"] = tracks
            viseme_tracks = []
            if viseme_tracks_enabled:
                viseme_tracks = audio_manager.build_viseme_tracks(tracks, mode=lipsync_mode)
                if viseme_tracks:
                    shot["viseme_tracks"] = viseme_tracks
            shot["audio_markers"] = audio_manager.build_audio_markers_from_tracks(tracks)
            shot["audio_sync"] = audio_manager.format_audio_sync_text(tracks)
            sfx_source = str(os.getenv("DREAMWEAVER_SFX_SOURCE") or "library").strip().lower()
            if sfx_source in {"model", "video"}:
                sfx_hint = _collect_sfx_hint_for_shot(
                    shot=shot,
                    audio_markers=ctx.payload.get("audio_markers") if isinstance(ctx.payload.get("audio_markers"), list) else None,
                    audio_manager=audio_manager,
                )
                if sfx_hint:
                    if shot["audio_sync"]:
                        shot["audio_sync"] = f"{shot['audio_sync']}；{sfx_hint}"
                    else:
                        shot["audio_sync"] = sfx_hint

            existing_tracks[shot_id] = tracks
            existing_audio_map[shot_id] = [t.get("audio_path") for t in tracks if t.get("audio_path")]
            if viseme_tracks:
                existing_viseme_tracks[shot_id] = viseme_tracks

        if existing_tracks:
            ctx.payload["dialogue_tracks"] = existing_tracks
        if existing_audio_map:
            ctx.payload["dialogue_audio_map"] = existing_audio_map
        if existing_viseme_tracks:
            ctx.payload["viseme_tracks"] = existing_viseme_tracks

    ctx.payload["video_clip_jobs"] = _build_video_clip_jobs(
        storyboard=storyboard,
        run_dir=run_dir,
        existing_jobs_by_shot=existing_jobs_by_shot,
        existing_clips_by_shot=existing_clips_by_shot,
        requested_shot_ids=requested_shots,
        bridge_enabled=bridge_enabled,
        camera_states=ctx.payload.get("camera_states"),
    )
    video_jobs_by_shot = _index_video_clip_jobs_by_shot(ctx.payload.get("video_clip_jobs"))
    auto_i2v_shots: set[str] = set()
    auto_t2v_shots: set[str] = set()
    if is_wan_auto_engine:
        auto_i2v_shots, auto_t2v_shots = _split_wan_auto_shots(
            storyboard=storyboard,
            jobs_by_shot=video_jobs_by_shot,
            run_dir=run_dir,
            requested_shot_ids=requested_shots,
            regenerate_shot_ids=regen_set,
        )

    if require_confirmation and not _all_storyboard_shots_have_video(storyboard=storyboard, run_dir=run_dir):
        if requested_shots:
            if is_wan_i2v_engine:
                _run_wan_i2v(
                    ctx,
                    run_dir=run_dir,
                    video_cfg=video_cfg,
                    width=width,
                    height=height,
                    regenerate_shot_ids=regen_set,
                    allowed_shot_ids=requested_shots,
                    character_manager=character_manager,
                )
            elif is_wan_t2v_engine:
                _run_wan_t2v(
                    ctx,
                    run_dir=run_dir,
                    video_cfg=video_cfg,
                    width=width,
                    height=height,
                    fps=fps,
                    regenerate_shot_ids=regen_set,
                    allowed_shot_ids=requested_shots,
                )
            elif is_wan_auto_engine:
                if auto_t2v_shots:
                    _run_wan_t2v(
                        ctx,
                        run_dir=run_dir,
                        video_cfg=video_cfg,
                        width=width,
                        height=height,
                        fps=fps,
                        regenerate_shot_ids=regen_set,
                        allowed_shot_ids=auto_t2v_shots,
                    )
                if auto_i2v_shots:
                    _run_wan_i2v(
                        ctx,
                        run_dir=run_dir,
                        video_cfg=video_cfg,
                        width=width,
                        height=height,
                        regenerate_shot_ids=regen_set,
                        allowed_shot_ids=auto_i2v_shots,
                        character_manager=character_manager,
                    )
            else:
                ffmpeg = os.getenv("FFMPEG_PATH", "ffmpeg")
                slideshow_effect = _resolve_slideshow_effect(video_cfg.get("slideshow_effect"))
                existing_clips_by_shot = _index_video_clips_by_shot(ctx.payload.get("video_clips"))
                clips: List[dict] = []
                for item in storyboard:
                    if not isinstance(item, dict):
                        continue
                    shot_id = str(item.get("shot_id") or "")
                    if not shot_id:
                        continue
                    if shot_id not in requested_shots:
                        existing = existing_clips_by_shot.get(shot_id)
                        if isinstance(existing, dict):
                            clips.append(existing)
                        continue

                    head = run_dir / f"{shot_id}_head.png"
                    tail = run_dir / f"{shot_id}_tail.png"
                    mid = run_dir / f"{shot_id}_mid.png"
                    out = run_dir / f"{shot_id}.mp4"
                    duration_s = float(item.get("duration_s", 3.0))

                    existing = existing_clips_by_shot.get(shot_id)
                    if out.exists() and shot_id not in regen_set:
                        if isinstance(existing, dict):
                            clips.append(existing)
                        else:
                            clips.append(
                                {
                                    "path": str(out),
                                    "duration": duration_s,
                                    "head": str(head),
                                    "mid": str(mid) if mid.exists() else None,
                                    "tail": str(tail),
                                    "meta": {
                                        "engine": "ffmpeg_slideshow",
                                        "via": "ffmpeg_slideshow",
                                        "slideshow_effect": slideshow_effect,
                                        "fps": fps,
                                        "width": width,
                                        "height": height,
                                    },
                                }
                            )
                        continue

                    _render_slideshow_clip(
                        ffmpeg=ffmpeg,
                        head=head,
                        mid=mid if mid.exists() else None,
                        tail=tail,
                        out=out,
                        duration_s=duration_s,
                        fps=fps,
                        width=width,
                        height=height,
                        effect=slideshow_effect,
                    )
                    clips.append(
                        {
                            "path": str(out),
                            "duration": duration_s,
                            "head": str(head),
                            "mid": str(mid) if mid.exists() else None,
                            "tail": str(tail),
                            "meta": {
                                "engine": "ffmpeg_slideshow",
                                "via": "ffmpeg_slideshow",
                                "slideshow_effect": slideshow_effect,
                                "fps": fps,
                                "width": width,
                                "height": height,
                            },
                        }
                    )
                ctx.payload["video_clips"] = clips

        _apply_sfx_to_clips(ctx=ctx, run_dir=run_dir, storyboard=storyboard)
        ctx.payload["video_clip_jobs"] = _build_video_clip_jobs(
            storyboard=storyboard,
            run_dir=run_dir,
            existing_jobs_by_shot=_index_video_clip_jobs_by_shot(ctx.payload.get("video_clip_jobs")),
            existing_clips_by_shot=_index_video_clips_by_shot(ctx.payload.get("video_clips")),
            requested_shot_ids=requested_shots,
            bridge_enabled=bridge_enabled,
            camera_states=ctx.payload.get("camera_states"),
        )
        ctx.payload["video_done"] = _all_storyboard_shots_have_video(storyboard=storyboard, run_dir=run_dir)
        return

    if is_wan_i2v_engine:
        _run_wan_i2v(
            ctx,
            run_dir=run_dir,
            video_cfg=video_cfg,
            width=width,
            height=height,
            regenerate_shot_ids=regen_set,
            character_manager=character_manager,
        )
        _apply_sfx_to_clips(ctx=ctx, run_dir=run_dir, storyboard=storyboard)
        ctx.payload["video_clip_jobs"] = _build_video_clip_jobs(
            storyboard=storyboard,
            run_dir=run_dir,
            existing_jobs_by_shot=_index_video_clip_jobs_by_shot(ctx.payload.get("video_clip_jobs")),
            existing_clips_by_shot=_index_video_clips_by_shot(ctx.payload.get("video_clips")),
            requested_shot_ids=requested_shots,
            bridge_enabled=bridge_enabled,
            camera_states=ctx.payload.get("camera_states"),
        )
        ctx.payload["video_done"] = True
        return

    if is_wan_t2v_engine:
        _run_wan_t2v(
            ctx,
            run_dir=run_dir,
            video_cfg=video_cfg,
            width=width,
            height=height,
            fps=fps,
            regenerate_shot_ids=regen_set,
        )
        _apply_sfx_to_clips(ctx=ctx, run_dir=run_dir, storyboard=storyboard)
        ctx.payload["video_clip_jobs"] = _build_video_clip_jobs(
            storyboard=storyboard,
            run_dir=run_dir,
            existing_jobs_by_shot=_index_video_clip_jobs_by_shot(ctx.payload.get("video_clip_jobs")),
            existing_clips_by_shot=_index_video_clips_by_shot(ctx.payload.get("video_clips")),
            requested_shot_ids=requested_shots,
            bridge_enabled=bridge_enabled,
            camera_states=ctx.payload.get("camera_states"),
        )
        ctx.payload["video_done"] = True
        return

    if is_wan_auto_engine:
        if auto_t2v_shots:
            _run_wan_t2v(
                ctx,
                run_dir=run_dir,
                video_cfg=video_cfg,
                width=width,
                height=height,
                fps=fps,
                regenerate_shot_ids=regen_set,
                allowed_shot_ids=auto_t2v_shots,
            )
        if auto_i2v_shots:
            _run_wan_i2v(
                ctx,
                run_dir=run_dir,
                video_cfg=video_cfg,
                width=width,
                height=height,
                regenerate_shot_ids=regen_set,
                allowed_shot_ids=auto_i2v_shots,
                character_manager=character_manager,
            )
        _apply_sfx_to_clips(ctx=ctx, run_dir=run_dir, storyboard=storyboard)
        ctx.payload["video_clip_jobs"] = _build_video_clip_jobs(
            storyboard=storyboard,
            run_dir=run_dir,
            existing_jobs_by_shot=_index_video_clip_jobs_by_shot(ctx.payload.get("video_clip_jobs")),
            existing_clips_by_shot=_index_video_clips_by_shot(ctx.payload.get("video_clips")),
            requested_shot_ids=requested_shots,
            bridge_enabled=True,
            camera_states=ctx.payload.get("camera_states"),
        )
        ctx.payload["video_done"] = True
        return

    ffmpeg = os.getenv("FFMPEG_PATH", "ffmpeg")
    slideshow_effect = _resolve_slideshow_effect(video_cfg.get("slideshow_effect"))
    existing_clips_by_shot = _index_video_clips_by_shot(ctx.payload.get("video_clips"))
    clips: List[dict] = []
    storyboard = ctx.payload.get("storyboard", [])
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "")
        if not shot_id:
            continue
        head = run_dir / f"{shot_id}_head.png"
        tail = run_dir / f"{shot_id}_tail.png"
        mid = run_dir / f"{shot_id}_mid.png"
        out = run_dir / f"{shot_id}.mp4"
        duration_s = float(item.get("duration_s", 3.0))

        if regen_set and shot_id not in regen_set and out.exists():
            existing = existing_clips_by_shot.get(shot_id)
            if isinstance(existing, dict):
                clips.append(existing)
                continue

        _render_slideshow_clip(
            ffmpeg=ffmpeg,
            head=head,
            mid=mid if mid.exists() else None,
            tail=tail,
            out=out,
            duration_s=duration_s,
            fps=fps,
            width=width,
            height=height,
            effect=slideshow_effect,
        )

        clips.append(
            {
                "path": str(out),
                "duration": duration_s,
                "head": str(head),
                "mid": str(mid) if mid.exists() else None,
                "tail": str(tail),
                "meta": {
                    "engine": "ffmpeg_slideshow",
                    "via": "ffmpeg_slideshow",
                    "slideshow_effect": slideshow_effect,
                    "fps": fps,
                    "width": width,
                    "height": height,
                },
            }
        )

    ctx.payload["video_clips"] = clips
    _apply_sfx_to_clips(ctx=ctx, run_dir=run_dir, storyboard=storyboard)
    ctx.payload["video_clip_jobs"] = _build_video_clip_jobs(
        storyboard=storyboard,
        run_dir=run_dir,
        existing_jobs_by_shot=_index_video_clip_jobs_by_shot(ctx.payload.get("video_clip_jobs")),
        existing_clips_by_shot=_index_video_clips_by_shot(ctx.payload.get("video_clips")),
        requested_shot_ids=requested_shots,
        bridge_enabled=bridge_enabled,
        camera_states=ctx.payload.get("camera_states"),
    )
    ctx.payload["video_done"] = True
