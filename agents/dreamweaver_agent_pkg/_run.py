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

def run_video(ctx: Any) -> None:
    # 视频生成控制与供应商追踪由 backend 侧单一实现，仓库根包不硬依赖 backend，
    # 按既有惯例在入口内延迟导入（core/unified_media_runtime、agents/character_manager 同型）。
    from app.services.dreamweaver.video_generation import (
        build_video_provider_trace,
        resolve_video_generation_controls,
    )

    ensure_media_payload(ctx.payload)

    run_dir = Path("runs") / ctx.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    video_cfg = ctx.payload.get("video_config") if isinstance(ctx.payload.get("video_config"), dict) else {}
    video_cfg = resolve_video_generation_controls(video_cfg)
    ctx.payload["video_config"] = video_cfg
    image_cfg = ctx.payload.get("image_config") if isinstance(ctx.payload.get("image_config"), dict) else {}
    width, height, _ratio = resolve_frame_size(image_cfg)
    fps = normalize_video_fps(video_cfg.get("fps"), default=24)
    engine = normalize_dreamweaver_video_engine(
        video_cfg.get("engine") or os.getenv("DREAMWEAVER_VIDEO_ENGINE") or "ffmpeg_slideshow"
    )
    uses_i2v_engine = is_dreamweaver_i2v_engine(engine)
    uses_t2v_engine = is_dreamweaver_t2v_engine(engine)
    uses_auto_engine = is_dreamweaver_auto_engine(engine)
    explicit_kling_omni = bool(
        str(video_cfg.get("provider_mode") or "").strip().lower() == "kling_omni"
        and bool(video_cfg.get("allow_kling_omni"))
        and bool(video_cfg.get("enable_kling_video_provider"))
    )
    bridge_enabled = bool(explicit_kling_omni or uses_i2v_engine or uses_auto_engine)
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
    lib_assets = _library_assets_from_payload(ctx.payload) if isinstance(storyboard, list) and bool(video_cfg.get("allow_subject_bridge")) else []
    if lib_assets:
        auto_sync_subject_refs = bool(video_cfg.get("allow_subject_bridge_auto_sync"))
        try:
            for item in storyboard:
                if not isinstance(item, dict):
                    continue
                asset_match = _match_library_assets_for_shot(shot=item, library_assets=lib_assets, max_character_refs=3)
                character_assets = asset_match.get("character_assets") if isinstance(asset_match.get("character_assets"), list) else []
                subject_refs = ensure_subject_refs_for_character_assets(
                    character_assets,
                    provider="kling",
                    max_subject_refs=3,
                    auto_sync=auto_sync_subject_refs,
                )
                if subject_refs:
                    item["provider_subject_refs"] = subject_refs
                elif isinstance(item.get("provider_subject_refs"), list):
                    item.pop("provider_subject_refs", None)
        except Exception as exc:  # noqa: BLE001
            print(f"主体桥接预处理失败，已降级忽略: {exc}")
        if auto_sync_subject_refs:
            _apply_library_asset_updates_to_payload(ctx.payload.get("project_assets"), lib_assets)
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

            if uses_i2v_engine or uses_t2v_engine or uses_auto_engine:
                target_duration_s = normalize_dreamweaver_video_duration_s(shot.get("duration_s"), default=5.0)
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
    trace_job_list = _build_video_clip_jobs(
        storyboard=storyboard,
        run_dir=run_dir,
        existing_jobs_by_shot=_index_video_clip_jobs_by_shot(ctx.payload.get("video_clip_jobs")),
        existing_clips_by_shot=_index_video_clips_by_shot(ctx.payload.get("video_clips")),
        requested_shot_ids=requested_shots,
        bridge_enabled=bridge_enabled,
        camera_states=ctx.payload.get("camera_states"),
    )
    video_jobs_by_shot = _index_video_clip_jobs_by_shot(trace_job_list)
    ctx.payload["video_provider_trace"] = build_video_provider_trace(
        storyboard=storyboard,
        jobs_by_shot=video_jobs_by_shot,
        video_config=video_cfg,
        requested_shot_ids=requested_shots or None,
    )
    auto_routed_i2v_shots: set[str] = set()
    auto_routed_t2v_shots: set[str] = set()
    if uses_auto_engine:
        auto_routed_i2v_shots, auto_routed_t2v_shots = _split_auto_video_shots(
            storyboard=storyboard,
            jobs_by_shot=video_jobs_by_shot,
            run_dir=run_dir,
            requested_shot_ids=requested_shots,
            regenerate_shot_ids=regen_set,
        )

    if require_confirmation and not _all_storyboard_shots_have_video(storyboard=storyboard, run_dir=run_dir):
        if requested_shots:
            if explicit_kling_omni:
                _run_kling_omni(
                    ctx,
                    run_dir=run_dir,
                    video_cfg=video_cfg,
                    regenerate_shot_ids=regen_set,
                    allowed_shot_ids=requested_shots,
                )
            elif uses_i2v_engine:
                _run_i2v_video_generation(
                    ctx,
                    run_dir=run_dir,
                    video_cfg=video_cfg,
                    width=width,
                    height=height,
                    regenerate_shot_ids=regen_set,
                    allowed_shot_ids=requested_shots,
                    character_manager=character_manager,
                )
            elif uses_t2v_engine:
                _run_t2v_video_generation(
                    ctx,
                    run_dir=run_dir,
                    video_cfg=video_cfg,
                    width=width,
                    height=height,
                    fps=fps,
                    regenerate_shot_ids=regen_set,
                    allowed_shot_ids=requested_shots,
                )
            elif uses_auto_engine:
                if auto_routed_t2v_shots:
                    _run_t2v_video_generation(
                        ctx,
                        run_dir=run_dir,
                        video_cfg=video_cfg,
                        width=width,
                        height=height,
                        fps=fps,
                        regenerate_shot_ids=regen_set,
                        allowed_shot_ids=auto_routed_t2v_shots,
                    )
                if auto_routed_i2v_shots:
                    _run_i2v_video_generation(
                        ctx,
                        run_dir=run_dir,
                        video_cfg=video_cfg,
                        width=width,
                        height=height,
                        regenerate_shot_ids=regen_set,
                        allowed_shot_ids=auto_routed_i2v_shots,
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

    if explicit_kling_omni:
        _run_kling_omni(
            ctx,
            run_dir=run_dir,
            video_cfg=video_cfg,
            regenerate_shot_ids=regen_set,
            allowed_shot_ids=requested_shots or None,
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

    if uses_i2v_engine:
        _run_i2v_video_generation(
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

    if uses_t2v_engine:
        _run_t2v_video_generation(
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

    if uses_auto_engine:
        if auto_routed_t2v_shots:
            _run_t2v_video_generation(
                ctx,
                run_dir=run_dir,
                video_cfg=video_cfg,
                width=width,
                height=height,
                fps=fps,
                regenerate_shot_ids=regen_set,
                allowed_shot_ids=auto_routed_t2v_shots,
            )
        if auto_routed_i2v_shots:
            _run_i2v_video_generation(
                ctx,
                run_dir=run_dir,
                video_cfg=video_cfg,
                width=width,
                height=height,
                regenerate_shot_ids=regen_set,
                allowed_shot_ids=auto_routed_i2v_shots,
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
