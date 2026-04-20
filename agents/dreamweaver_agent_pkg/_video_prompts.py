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

def _build_audio_policy_hint() -> str:
    if not _env_flag("DREAMWEAVER_AUDIO_POLICY_HINT_ENABLED", default=True):
        return ""
    if _env_flag("DREAMWEAVER_DIALOGUE_AUDIO_EMBED", default=False):
        return ""

    sfx_source = str(os.getenv("DREAMWEAVER_SFX_SOURCE") or "library").strip().lower()
    if sfx_source in {"model", "video"}:
        return "音频要求：仅生成环境音/音效，不生成对白音频与背景音乐"
    return "音频要求：不生成对白音频与背景音乐"


def _build_wan_video_prompt(*, shot: Dict[str, Any], style_preset: str, frame_ratio: str, prompt_fragment: str = "", engine: str = DREAMWEAVER_I2V_ENGINE) -> str:
    """构建 Wan I2V/T2V 的视频提示词，优先吸收 storyboard 的结构化字段。"""
    style_prompt = style_prompt_for_preset(style_preset)
    soft_negative = _i2v_soft_negative_hint(style_negative_prompt_for_preset(style_preset))
    engine_value = normalize_dreamweaver_video_engine(engine, default=DREAMWEAVER_I2V_ENGINE)
    is_t2v = is_dreamweaver_t2v_engine(engine_value)
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

    duration_s = normalize_dreamweaver_video_duration_s(shot.get("duration_s"), default=15.0)

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


