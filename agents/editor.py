from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pipeline.artifacts_io import download_url_to_path as _download_url_to_path
from pipeline.ffmpeg_runner import run_ffmpeg as _run_ffmpeg
from pipeline.media_presets import DREAMWEAVER_WAN_MODEL_ID, resolve_frame_size


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return int(default)
    try:
        value = int(str(raw).strip())
    except Exception:  # noqa: BLE001
        return int(default)
    return int(value)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return float(default)
    try:
        value = float(str(raw).strip())
    except Exception:  # noqa: BLE001
        return float(default)
    return float(value)


def _probe_video_size(path: Path, *, ffprobe: str) -> Optional[Tuple[int, int]]:
    if not isinstance(path, Path) or not path.exists():
        return None
    cmd = [
        str(ffprobe or "ffprobe"),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        path.as_posix(),
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:  # noqa: BLE001
        return None

    try:
        payload = json.loads(proc.stdout or "")
    except Exception:  # noqa: BLE001
        return None

    streams = payload.get("streams")
    if not isinstance(streams, list):
        return None
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        w = stream.get("width")
        h = stream.get("height")
        try:
            width = int(w)
            height = int(h)
        except Exception:  # noqa: BLE001
            continue
        if width > 0 and height > 0:
            return width, height
    return None


def _subtitle_style_params() -> Tuple[int, int, int]:
    alignment = _env_int("DREAMWEAVER_SUBTITLE_ALIGNMENT", 2)
    if alignment not in {1, 2, 3, 4, 5, 6, 7, 8, 9}:
        alignment = 2

    outline = _env_int("DREAMWEAVER_SUBTITLE_OUTLINE", 2)
    outline = max(0, min(int(outline), 10))

    shadow = _env_int("DREAMWEAVER_SUBTITLE_SHADOW", 0)
    shadow = max(0, min(int(shadow), 10))

    return int(alignment), int(outline), int(shadow)


def _default_subtitle_params(*, width: int, height: int) -> Tuple[int, int, int]:
    w = max(1, int(width))
    h = max(1, int(height))

    font_size = _env_int("DREAMWEAVER_SUBTITLE_FONT_SIZE", 0)
    if font_size <= 0:
        # 以画面高度为基准自适应；放宽上限以覆盖 9:16 1080p（1920 高）场景。
        font_size = max(22, min(int(round(h * 0.032)), 72))

    margin_v = _env_int("DREAMWEAVER_SUBTITLE_MARGIN_V", 0)
    if margin_v <= 0:
        margin_v = max(18, min(int(round(h * 0.03)), 96))

    margin_lr = _env_int("DREAMWEAVER_SUBTITLE_MARGIN_LR", 0)
    if margin_lr <= 0:
        margin_lr = max(18, min(int(round(w * 0.03)), 96))

    safe_v_pct = _env_float("DREAMWEAVER_SUBTITLE_SAFE_AREA_V_PCT", 0.0)
    safe_v_pct = max(0.0, min(float(safe_v_pct), 0.2))
    if safe_v_pct > 0:
        margin_v = max(int(margin_v), int(round(h * safe_v_pct)))

    safe_lr_pct = _env_float("DREAMWEAVER_SUBTITLE_SAFE_AREA_LR_PCT", 0.0)
    safe_lr_pct = max(0.0, min(float(safe_lr_pct), 0.2))
    if safe_lr_pct > 0:
        margin_lr = max(int(margin_lr), int(round(w * safe_lr_pct)))

    return int(font_size), int(margin_v), int(margin_lr)


def _srt_timestamp(seconds: float) -> str:
    ms_total = int(round(max(seconds, 0.0) * 1000.0))
    hours, remainder = divmod(ms_total, 3600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _ass_timestamp(seconds: float) -> str:
    cs_total = int(round(max(seconds, 0.0) * 100.0))
    hours, remainder = divmod(cs_total, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, cs = divmod(remainder, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _ass_text(text: str) -> str:
    value = str(text or "")
    value = value.replace("\\", "\\\\")
    value = value.replace("\n", " ").replace("\r", " ")
    value = value.replace("{", "").replace("}", "")
    return value


def _write_ass_from_storyboard(
    storyboard: Any,
    out_path: Path,
    *,
    play_res: Tuple[int, int],
    font_name: str,
    font_size: int,
    margin_v: int,
    margin_l: int,
    margin_r: int,
    alignment: int = 2,
    outline: int = 2,
    shadow: int = 0,
) -> None:
    if not isinstance(storyboard, list) or not storyboard:
        out_path.write_text("", encoding="utf-8")
        return

    play_res_x = max(1, int(play_res[0]))
    play_res_y = max(1, int(play_res[1]))

    lines: List[str] = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {play_res_x}",
        f"PlayResY: {play_res_y}",
        "ScaledBorderAndShadow: yes",
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font_name},{int(font_size)},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,{int(outline)},{int(shadow)},{int(alignment)},{int(margin_l)},{int(margin_r)},{int(margin_v)},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    cursor = 0.0
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        duration_s = float(item.get("duration_s") or 0.0)
        if duration_s <= 0:
            continue

        raw_text = str(item.get("desc") or "").strip()
        raw_text = re.sub(r"\s+", " ", raw_text)
        if not raw_text:
            raw_text = str(item.get("shot_id") or "").strip()
        raw_text = raw_text[:32]
        if not raw_text:
            continue

        start = cursor
        end = cursor + duration_s
        cursor = end

        lines.append(
            f"Dialogue: 0,{_ass_timestamp(start)},{_ass_timestamp(end)},Default,,0,0,0,,{_ass_text(raw_text)}"
        )

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_ass_from_text(
    text: str,
    out_path: Path,
    *,
    play_res: Tuple[int, int],
    font_name: str,
    font_size: int,
    margin_v: int,
    margin_l: int,
    margin_r: int,
    alignment: int = 2,
    outline: int = 2,
    shadow: int = 0,
    start_s: float = 0.0,
    end_s: float = 99.0 * 3600.0,
) -> None:
    value = str(text or "").strip()
    if not value:
        out_path.write_text("", encoding="utf-8")
        return

    play_res_x = max(1, int(play_res[0]))
    play_res_y = max(1, int(play_res[1]))

    lines: List[str] = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {play_res_x}",
        f"PlayResY: {play_res_y}",
        "ScaledBorderAndShadow: yes",
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font_name},{int(font_size)},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,{int(outline)},{int(shadow)},{int(alignment)},{int(margin_l)},{int(margin_r)},{int(margin_v)},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,{_ass_timestamp(float(start_s))},{_ass_timestamp(float(end_s))},Default,,0,0,0,,{_ass_text(value)}",
    ]

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_srt_from_storyboard(storyboard: Any, out_path: Path) -> None:
    if not isinstance(storyboard, list) or not storyboard:
        out_path.write_text("", encoding="utf-8")
        return

    lines: List[str] = []
    cursor = 0.0
    cue_index = 1

    for item in storyboard:
        if not isinstance(item, dict):
            continue
        duration_s = float(item.get("duration_s") or 0.0)
        if duration_s <= 0:
            continue

        raw_text = str(item.get("desc") or "").strip()
        raw_text = re.sub(r"\s+", " ", raw_text)
        if not raw_text:
            raw_text = str(item.get("shot_id") or "").strip()
        # 避免长描述导致字幕多行堆叠占屏（该字幕主要用于快速浏览/调试）
        raw_text = raw_text[:32]

        start = cursor
        end = cursor + duration_s
        cursor = end

        if not raw_text:
            continue

        lines.extend(
            [
                str(cue_index),
                f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}",
                raw_text,
                "",
            ]
        )
        cue_index += 1

    out_path.write_text("\n".join(lines), encoding="utf-8")


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return None


def _normalize_text_list(raw: Any, *, limit: int = 200) -> List[str]:
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for item in raw:
        if not isinstance(item, (str, int)):
            continue
        value = str(item).strip()
        if not value or value in out:
            continue
        out.append(value)
        if len(out) >= limit:
            break
    return out


def _shot_id_from_video_clip(item: Any) -> Optional[str]:
    if not isinstance(item, dict):
        return None
    path = item.get("path")
    if not isinstance(path, str) or not path.strip():
        return None
    shot_id = Path(path).stem.strip()
    return shot_id or None


def _index_video_clips_by_shot(items: Any) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(items, list):
        return out
    for item in items:
        shot_id = _shot_id_from_video_clip(item)
        if shot_id and isinstance(item, dict):
            out[shot_id] = item
    return out


def _asset_shot_role_from_path(path: str) -> Tuple[Optional[str], Optional[str]]:
    p = Path(path)
    stem = p.stem
    suffix = p.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        for suffix_name in ("head", "tail", "mid"):
            marker = f"_{suffix_name}"
            if stem.endswith(marker):
                return stem[: -len(marker)], suffix_name
    if suffix in {".mp4", ".mov", ".mkv"}:
        return stem, "clip"
    return None, None


def _resolve_video_edit_settings(payload: Dict[str, Any]) -> Tuple[bool, str]:
    cfg = payload.get("video_edit_config") if isinstance(payload.get("video_edit_config"), dict) else {}
    enabled = bool(cfg.get("enabled")) if isinstance(cfg.get("enabled"), bool) else False
    model_id = str(cfg.get("adapter") or "").strip() or DREAMWEAVER_WAN_MODEL_ID
    return enabled, model_id


def _normalize_video_edit_feature(value: Any, *, default: str = "style-transfer") -> str:
    feature = str(value or "").strip().lower()
    if feature in {"style-transfer", "video-extend", "video-remix"}:
        return feature
    return default


def _probe_clip_dimensions(payload: Dict[str, Any], clip: Dict[str, Any], clip_path: Path) -> Tuple[int, int]:
    meta = clip.get("meta") if isinstance(clip.get("meta"), dict) else {}
    width = meta.get("width")
    height = meta.get("height")
    try:
        if int(width) > 0 and int(height) > 0:
            return int(width), int(height)
    except Exception:  # noqa: BLE001
        pass

    ffprobe = str(os.getenv("FFPROBE_PATH", "")).strip() or "ffprobe"
    probed = _probe_video_size(clip_path, ffprobe=ffprobe)
    if probed:
        return int(probed[0]), int(probed[1])

    image_cfg = payload.get("image_config") if isinstance(payload.get("image_config"), dict) else {}
    width, height, _ratio = resolve_frame_size(image_cfg)
    return int(width), int(height)


def _collect_video_edit_reference_images(payload: Dict[str, Any], clip: Dict[str, Any], *, shot_id: str) -> List[str]:
    candidates: List[str] = []
    for key in ("head", "mid", "tail"):
        value = clip.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())

    for item in payload.get("keyframes") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        item_shot_id, role = _asset_shot_role_from_path(path)
        if item_shot_id == shot_id and role in {"head", "tail"}:
            candidates.append(path)

    for item in payload.get("midframes") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        item_shot_id, role = _asset_shot_role_from_path(path)
        if item_shot_id == shot_id and role == "mid":
            candidates.append(path)

    out: List[str] = []
    for path in candidates:
        p = Path(path)
        if not p.exists():
            continue
        normalized = str(p)
        if normalized in out:
            continue
        out.append(normalized)
        if len(out) >= 3:
            break
    return out


def _build_video_edit_prompt(
    *,
    shot: Dict[str, Any],
    plan_item: Dict[str, Any],
    clip: Dict[str, Any],
    edit_feature: str,
) -> str:
    shot_desc = str(plan_item.get("shot_desc") or shot.get("desc") or "").strip()
    motion_prompt = str(plan_item.get("motion_prompt") or "").strip()
    summary = str(plan_item.get("summary") or "").strip()
    issues = _normalize_text_list(plan_item.get("issues"), limit=6)
    score = _safe_float(plan_item.get("review_score"))
    threshold = _safe_float(plan_item.get("threshold"))

    prompt_parts: List[str] = []
    if edit_feature == "video-extend":
        prompt_parts.extend(
            [
                "请基于参考视频做延展式修补，重点补足开头、结尾或过渡不完整的问题。",
                "保持主体身份、场景设定、镜头意图、时长节奏和基本构图尽量一致。",
                "优先修复片段衔接生硬、动作中断、首尾断裂和过渡缺失，不要重做成完全不同的镜头。",
            ]
        )
    elif edit_feature == "video-remix":
        prompt_parts.extend(
            [
                "请基于参考视频做时序稳定性修补，而不是重新设计镜头。",
                "保持主体身份、场景设定、镜头意图、时长节奏和基本构图不变。",
                "优先修复抖动、跳帧、闪烁、主体一致性不足、动作连贯性差和镜头不稳的问题。",
            ]
        )
    else:
        prompt_parts.extend(
            [
                "请基于参考视频做轻量修复，而不是重新设计镜头。",
                "保持主体身份、场景设定、镜头意图、时长节奏和基本构图不变。",
                "优先提升画面清晰度、主体一致性、运动流畅度、光影稳定性和色彩自然度。",
            ]
        )
    prompt_parts.append("不要新增无关主体，不要明显改变机位，不要改成另一条镜头内容。")
    if shot_desc:
        prompt_parts.append(f"分镜描述：{shot_desc}")
    if motion_prompt:
        prompt_parts.append(f"原视频提示词参考：{motion_prompt}")
    if summary:
        prompt_parts.append(f"质检总结：{summary}")
    if issues:
        prompt_parts.append(f"待修复问题：{'；'.join(issues)}")
    if score is not None and threshold is not None:
        prompt_parts.append(f"当前视觉评分约为 {score:.1f}/10，需要至少提升到 {threshold:.1f}/10。")

    meta = clip.get("meta") if isinstance(clip.get("meta"), dict) else {}
    engine = str(meta.get("engine") or "").strip()
    if engine:
        prompt_parts.append(f"尽量保持原片段的运动风格和镜头语言（原引擎：{engine}）。")
    return "\n".join(prompt_parts)


def _write_video_result(result: Any, out_path: Path) -> None:
    if not bool(getattr(result, "success", False)):
        raise RuntimeError(str(getattr(result, "error", "") or "video edit failed"))

    data = result.data if isinstance(getattr(result, "data", None), dict) else {}
    url = data.get("video_url") or data.get("url")
    if not url:
        outputs = getattr(result, "outputs", None)
        if isinstance(outputs, list) and outputs:
            url = outputs[0]

    if isinstance(url, str) and url:
        local_candidate = Path(url)
        if local_candidate.exists():
            out_path.write_bytes(local_candidate.read_bytes())
            return
        _download_url_to_path(url, out_path, timeout_s=300.0, max_retries=2)
        return

    b64_payload = data.get("b64_json") or data.get("base64") or data.get("video_base64")
    if isinstance(b64_payload, str) and b64_payload:
        import base64

        out_path.write_bytes(base64.b64decode(b64_payload))
        return

    raise RuntimeError("video edit response unsupported: missing video payload")


def _run_video_edit_request(
    *,
    prompt: str,
    duration: float,
    width: int,
    height: int,
    video_path: str,
    reference_images: Optional[List[str]],
    edit_feature: str,
    model_id: str,
) -> Any:
    from core.unified_media_runtime import media_runtime

    return media_runtime.edit_video(
        prompt=prompt,
        duration=float(duration),
        width=int(width),
        height=int(height),
        video_path=video_path,
        reference_images=reference_images or None,
        edit_feature=edit_feature,
        model_id=model_id,
        use_fallback=False,
    )


def _apply_video_edit_plan(ctx: Any, *, run_dir: Path) -> None:
    plan = ctx.payload.pop("video_edit_plan", None)
    if not isinstance(plan, dict):
        return

    enabled, model_id = _resolve_video_edit_settings(ctx.payload)
    plan_edit_feature = _normalize_video_edit_feature(plan.get("edit_feature"), default="style-transfer")
    plan_edit_feature_mode = str(plan.get("edit_feature") or "").strip().lower() or plan_edit_feature
    target_shot_ids = _normalize_text_list(plan.get("target_shot_ids"))
    plan_items_raw = plan.get("items") if isinstance(plan.get("items"), list) else []
    plan_items = [item for item in plan_items_raw if isinstance(item, dict)]
    if not target_shot_ids:
        for item in plan_items:
            shot_id = str(item.get("shot_id") or "").strip()
            if shot_id and shot_id not in target_shot_ids:
                target_shot_ids.append(shot_id)

    result_summary: Dict[str, Any] = {
        "source": str(plan.get("source") or "").strip() or "runtime",
        "reason": str(plan.get("reason") or "").strip(),
        "enabled": bool(enabled),
        "model_id": model_id,
        "edit_feature": plan_edit_feature_mode,
        "edit_feature_mode": plan_edit_feature_mode,
        "default_edit_feature": plan_edit_feature,
        "target_shot_ids": target_shot_ids,
        "requested_count": len(target_shot_ids),
        "edited_count": 0,
        "failed_count": 0,
        "feature_counts": {},
        "items": [],
    }

    attempted_shots = _normalize_text_list(ctx.payload.get("video_edit_attempted_shot_ids"))
    for shot_id in target_shot_ids:
        if shot_id and shot_id not in attempted_shots:
            attempted_shots.append(shot_id)
    ctx.payload["video_edit_attempted_shot_ids"] = attempted_shots

    failed_shots = _normalize_text_list(ctx.payload.get("video_edit_failed_shot_ids"))

    if not enabled or not plan_items:
        result_summary["status"] = "skipped"
        result_summary["failed_count"] = len(target_shot_ids)
        if target_shot_ids:
            ctx.payload["video_edit_failed_shot_ids"] = [*failed_shots, *[sid for sid in target_shot_ids if sid not in failed_shots]]
        ctx.payload["video_edit_result"] = result_summary
        return

    clips_by_shot = _index_video_clips_by_shot(ctx.payload.get("video_clips"))
    storyboard_by_shot: Dict[str, Dict[str, Any]] = {}
    for item in ctx.payload.get("storyboard") or []:
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "").strip()
        if shot_id and shot_id not in storyboard_by_shot:
            storyboard_by_shot[shot_id] = item

    edited_dir = run_dir / "edited_clips"
    edited_dir.mkdir(parents=True, exist_ok=True)
    updated_by_shot: Dict[str, Dict[str, Any]] = {}

    for plan_item in plan_items:
        shot_id = str(plan_item.get("shot_id") or "").strip()
        if not shot_id:
            continue
        clip = clips_by_shot.get(shot_id)
        if not isinstance(clip, dict):
            result_summary["items"].append({"shot_id": shot_id, "status": "missing_clip"})
            if shot_id not in failed_shots:
                failed_shots.append(shot_id)
            continue

        source_path = str(clip.get("path") or "").strip()
        source_file = Path(source_path)
        if not source_path or not source_file.exists():
            result_summary["items"].append({"shot_id": shot_id, "status": "missing_source", "path": source_path})
            if shot_id not in failed_shots:
                failed_shots.append(shot_id)
            continue

        shot = storyboard_by_shot.get(shot_id, {})
        duration = _safe_float(plan_item.get("duration"))
        if duration is None or duration <= 0:
            duration = _safe_float(clip.get("duration"))
        if duration is None or duration <= 0:
            duration = _safe_float(shot.get("duration_s"))
        if duration is None or duration <= 0:
            duration = 5.0

        width, height = _probe_clip_dimensions(ctx.payload, clip, source_file)
        reference_images = _collect_video_edit_reference_images(ctx.payload, clip, shot_id=shot_id)
        item_edit_feature = _normalize_video_edit_feature(plan_item.get("edit_feature"), default=plan_edit_feature)
        item_edit_feature_reason = str(plan_item.get("edit_feature_reason") or "").strip()
        prompt = _build_video_edit_prompt(shot=shot, plan_item=plan_item, clip=clip, edit_feature=item_edit_feature)
        out_path = edited_dir / f"{shot_id}.mp4"

        try:
            result = _run_video_edit_request(
                prompt=prompt,
                duration=float(duration),
                width=int(width),
                height=int(height),
                video_path=str(source_file),
                reference_images=reference_images,
                edit_feature=item_edit_feature,
                model_id=model_id,
            )
            _write_video_result(result, out_path)

            updated_clip = dict(clip)
            updated_clip["path"] = str(out_path)
            updated_clip["duration"] = float(duration)

            meta = clip.get("meta") if isinstance(clip.get("meta"), dict) else {}
            updated_meta = dict(meta)
            edit_history = updated_meta.get("edit_history") if isinstance(updated_meta.get("edit_history"), list) else []
            edit_history.append(
                {
                    "source": "dreamweaver_autoqc",
                    "model_id": str(model_id),
                    "edit_feature": item_edit_feature,
                    "from_path": str(source_file),
                    "to_path": str(out_path),
                    "review_score": _safe_float(plan_item.get("review_score")),
                    "threshold": _safe_float(plan_item.get("threshold")),
                    "issues": _normalize_text_list(plan_item.get("issues"), limit=6),
                    "edit_feature_reason": item_edit_feature_reason,
                }
            )
            updated_meta["edit_history"] = edit_history[-5:]
            updated_meta["edited"] = True
            updated_meta["edited_from_path"] = str(source_file)
            updated_meta["edit_model"] = str(model_id)
            updated_meta["edit_feature"] = item_edit_feature
            updated_meta["edit_feature_reason"] = item_edit_feature_reason
            updated_meta["edit_prompt"] = prompt[:240]
            updated_meta["via"] = "video_edit"
            if isinstance(getattr(result, "data", None), dict) and isinstance(result.data.get("video_url"), str):
                updated_meta["remote_url"] = result.data["video_url"]
            updated_clip["meta"] = updated_meta

            updated_by_shot[shot_id] = updated_clip
            result_summary["edited_count"] = int(result_summary["edited_count"]) + 1
            feature_counts = result_summary.get("feature_counts")
            if isinstance(feature_counts, dict):
                feature_counts[item_edit_feature] = int(feature_counts.get(item_edit_feature) or 0) + 1
            result_summary["items"].append(
                {
                    "shot_id": shot_id,
                    "status": "edited",
                    "path": str(out_path),
                    "edit_feature": item_edit_feature,
                    "edit_feature_reason": item_edit_feature_reason,
                }
            )
            if shot_id in failed_shots:
                failed_shots.remove(shot_id)
        except Exception as exc:  # noqa: BLE001
            result_summary["items"].append(
                {
                    "shot_id": shot_id,
                    "status": "failed",
                    "error": str(exc),
                    "edit_feature": item_edit_feature,
                    "edit_feature_reason": item_edit_feature_reason,
                }
            )
            if shot_id not in failed_shots:
                failed_shots.append(shot_id)

    if updated_by_shot:
        merged_clips: List[Dict[str, Any]] = []
        for item in ctx.payload.get("video_clips") or []:
            shot_id = _shot_id_from_video_clip(item)
            if shot_id and shot_id in updated_by_shot:
                merged_clips.append(updated_by_shot.pop(shot_id))
            elif isinstance(item, dict):
                merged_clips.append(item)
        for shot_id in target_shot_ids:
            clip = updated_by_shot.get(shot_id)
            if isinstance(clip, dict):
                merged_clips.append(clip)
        ctx.payload["video_clips"] = merged_clips

    result_summary["failed_count"] = len(failed_shots)
    result_summary["status"] = "edited" if int(result_summary["edited_count"]) > 0 else "failed"
    ctx.payload["video_edit_failed_shot_ids"] = failed_shots
    ctx.payload["video_edit_result"] = result_summary


def run(ctx: Any) -> None:
    run_dir = Path("runs") / ctx.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _apply_video_edit_plan(ctx, run_dir=run_dir)
    clips: List[str] = []
    for item in ctx.payload.get("video_clips", []) or []:
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            clips.append(item["path"])

    if not clips:
        raise RuntimeError("no video_clips to merge")

    ffmpeg = os.getenv("FFMPEG_PATH", "ffmpeg")
    enable_subtitles = _env_flag("DREAMWEAVER_ENABLE_SUBTITLES", default=True)
    if isinstance(ctx.payload.get("enable_subtitles"), bool):
        enable_subtitles = bool(ctx.payload["enable_subtitles"])

    audio_path_value = ctx.payload.get("audio_path")
    audio_path: Optional[str]
    if isinstance(audio_path_value, str) and audio_path_value and Path(audio_path_value).exists():
        audio_path = audio_path_value
    else:
        audio_path = None

    concat_list = run_dir / "concat.txt"
    lines = []
    for path in clips:
        p = Path(path).resolve().as_posix()
        lines.append(f"file '{p}'")
    concat_list.write_text("\n".join(lines), encoding="utf-8")

    merged = run_dir / "merged.mp4"
    subtitle_path = run_dir / "subtitles.ass"
    if enable_subtitles:
        image_cfg = ctx.payload.get("image_config") if isinstance(ctx.payload.get("image_config"), dict) else {}
        w, h, _r = resolve_frame_size(image_cfg)
        ffprobe = str(os.getenv("FFPROBE_PATH", "")).strip() or "ffprobe"
        for clip_path in clips:
            candidate = Path(clip_path)
            if candidate.exists():
                probed = _probe_video_size(candidate, ffprobe=ffprobe)
                if probed:
                    w, h = probed
                break

        font_name = str(os.getenv("DREAMWEAVER_SUBTITLE_FONT_NAME", "")).strip() or "Arial"
        font_size, margin_v, margin_lr = _default_subtitle_params(width=w, height=h)
        alignment, outline, shadow = _subtitle_style_params()

        _write_ass_from_storyboard(
            ctx.payload.get("storyboard"),
            subtitle_path,
            play_res=(int(w), int(h)),
            font_name=font_name,
            font_size=int(font_size),
            margin_v=int(margin_v),
            margin_l=int(margin_lr),
            margin_r=int(margin_lr),
            alignment=int(alignment),
            outline=int(outline),
            shadow=int(shadow),
        )

    subtitle_filters: List[str] = []
    if enable_subtitles and subtitle_path.exists() and subtitle_path.stat().st_size > 0:
        subtitle_filters.append(f"subtitles={subtitle_path.as_posix()}")

    def _run_concat(*, with_audio: bool, subtitle_filter: Optional[str], reencode_video: bool) -> None:
        cmd: List[str] = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
        ]

        if with_audio and audio_path:
            cmd.extend(["-i", audio_path, "-map", "0:v:0", "-map", "1:a:0", "-shortest"])
        else:
            cmd.extend(["-map", "0:v:0", "-map", "0:a?"])

        if subtitle_filter:
            cmd.extend(["-vf", subtitle_filter])
            cmd.extend(["-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p"])
        elif reencode_video:
            cmd.extend(["-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p"])
        else:
            cmd.extend(["-c:v", "copy"])

        if with_audio and audio_path:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.extend(["-c:a", "copy"])

        cmd.extend(["-movflags", "+faststart", str(merged)])
        log_prefix = f"ffmpeg_edit_concat_{'a1' if (with_audio and audio_path) else 'a0'}_{'s1' if subtitle_filter else 's0'}_{'v1' if reencode_video else 'v0'}"
        _run_ffmpeg(cmd, log_dir=run_dir, log_prefix=log_prefix)

    attempts: List[Tuple[bool, Optional[str], bool]] = []
    if audio_path and subtitle_filters:
        for sf in subtitle_filters:
            attempts.append((True, sf, False))
    if audio_path:
        attempts.append((True, None, False))
    if subtitle_filters:
        for sf in subtitle_filters:
            attempts.append((False, sf, False))
    attempts.append((False, None, False))
    attempts.append((False, None, True))

    last_exc: Optional[Exception] = None
    for with_audio, subtitle_filter, reencode_video in attempts:
        try:
            _run_concat(with_audio=with_audio, subtitle_filter=subtitle_filter, reencode_video=reencode_video)
            last_exc = None
            break
        except RuntimeError as exc:
            last_exc = exc
            continue

    if last_exc:
        raise last_exc

    ctx.payload["merged_video"] = str(merged)
