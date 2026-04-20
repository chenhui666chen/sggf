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

def _run_i2v_video_generation(
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
    adapter_name = str(video_cfg.get("adapter") or DREAMWEAVER_I2V_ENGINE).strip() or DREAMWEAVER_I2V_ENGINE

    ffmpeg = os.getenv("FFMPEG_PATH", "ffmpeg")
    fps = DREAMWEAVER_I2V_OUTPUT_FPS
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
        duration_s = normalize_dreamweaver_video_duration_s(item.get("duration_s"), default=5.0)

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
        
        motion_prompt = _build_wan_video_prompt(
            shot=item,
            style_preset=style_preset,
            frame_ratio=frame_ratio,
            prompt_fragment=prompt_fragment,
        )
        _store_video_prompt_generated(item, motion_prompt)

        via = DREAMWEAVER_I2V_ENGINE
        meta: Dict[str, Any] = {"engine": DREAMWEAVER_I2V_ENGINE, "adapter": adapter_name, "fps": fps, "motion_bucket_id": motion_bucket_id}
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
            result = None
            chosen_input_meta: Optional[Dict[str, Any]] = None
            last_error: Optional[str] = None
            for idx, (candidate_path, candidate_meta) in enumerate(candidates):
                meta["i2v_input"] = candidate_meta
                try:
                    result = generate_video(
                        prompt=motion_prompt,
                        duration=float(duration_s),
                        width=int(width),
                        height=int(height),
                        seed=int(seed),
                        image_path=str(candidate_path),
                        model_id=adapter_name,
                        use_fallback=False,
                        fps=int(fps),
                        motion_bucket_id=int(motion_bucket_id),
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
                raise RuntimeError(last_error or f"{DREAMWEAVER_I2V_ENGINE} generate failed")

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


