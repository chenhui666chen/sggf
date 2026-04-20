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


