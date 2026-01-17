from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, List, Optional, Tuple

from pipeline.ffmpeg_runner import run_ffmpeg as _run_ffmpeg
from pipeline.media_presets import resolve_frame_size


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


def run(ctx: Any) -> None:
    run_dir = Path("runs") / ctx.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
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
            cmd.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p"])
        elif reencode_video:
            cmd.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p"])
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
