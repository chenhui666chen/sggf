from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional, Callable, Set

from ..prompt_normalizer import normalize_tts_prompt
from ..pause_tags import strip_pause_tags
from ..tts_delivery_plan import build_delivery_plan, resolve_segment_tts_model
from ..tts_language import apply_detected_language_type
from ..tts_model_ids import DEFAULT_AUDIOBOOK_TTS_MODEL, normalize_audiobook_tts_model
from app.services.audiobook.render_plan import (
    RENDER_PLAN_VERSION,
    RenderChunk,
    build_render_plan,
    extract_render_signatures,
    render_chunks_to_timing_segments_payload,
    render_plan_to_payload,
)
from core.unified_media_runtime import create_tts_engine
from app.services.audiobook.temp_segment_store import (
    extract_cached_segment_paths,
    load_cached_segment_audio,
)

try:
    from ..agent_dispatch_client import client as tts_dispatch_client
    TTS_DISPATCH_AVAILABLE = True
except ImportError:
    TTS_DISPATCH_AVAILABLE = False
    tts_dispatch_client = None

logger = logging.getLogger(__name__)

QWEN_RENDER_CHUNK_MAX_CHARS = 360


def _is_qwen_tts_model(model: Any) -> bool:
    return normalize_audiobook_tts_model(model, default="").startswith("qwen3-tts")


def _item_tts_model(item: Any) -> str:
    voice_params = getattr(item, "voice_params", None)
    if isinstance(voice_params, dict):
        return str(voice_params.get("tts_model") or "").strip()
    if isinstance(item, dict):
        raw_params = item.get("voice_params")
        if isinstance(raw_params, dict):
            return str(raw_params.get("tts_model") or "").strip()
    return ""


def _build_segment_statuses(
    *,
    total_segments: int,
    completed_indices: List[int],
    reused_indices: List[int],
    synthesized_indices: List[int],
    failed_indices: Optional[List[int]] = None,
    failed_segment_errors: Optional[Dict[int, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    completed_set = _normalize_segment_indices(completed_indices)
    reused_set = _normalize_segment_indices(reused_indices)
    synthesized_set = _normalize_segment_indices(synthesized_indices)
    failed_set = _normalize_segment_indices(failed_indices)
    failed_errors = dict(failed_segment_errors or {})
    statuses: Dict[str, Dict[str, Any]] = {}

    for index in range(max(int(total_segments or 0), 0)):
        if index in failed_set and index not in completed_set:
            status_payload = {
                "index": index,
                "status": "failed",
                "source": "tts_synthesis",
                "recovery_stage": "failed",
            }
            error_payload = failed_errors.get(index) or failed_errors.get(str(index))
            if isinstance(error_payload, dict) and error_payload:
                status_payload["error"] = error_payload
            statuses[str(index)] = status_payload
        elif index in completed_set:
            if index in reused_set:
                source = "resume_cache"
                recovery_stage = "cache_loaded"
            elif index in synthesized_set:
                source = "tts_synthesis"
                recovery_stage = "synthesized"
            else:
                source = "checkpoint_cache"
                recovery_stage = "cache_loaded"
            statuses[str(index)] = {
                "index": index,
                "status": "cached",
                "source": source,
                "recovery_stage": recovery_stage,
            }
        else:
            statuses[str(index)] = {
                "index": index,
                "status": "pending",
                "source": None,
                "recovery_stage": "pending",
            }

    return statuses


def _normalize_segment_indices(values: Any) -> Set[int]:
    normalized: Set[int] = set()
    for value in values or []:
        try:
            index = int(value)
        except Exception:
            continue
        if index >= 0:
            normalized.add(index)
    return normalized


def _mark_temp_asset_saved_segment_statuses(
    *,
    segment_statuses: Any,
    cached_audio_paths: Any,
) -> Any:
    if not isinstance(segment_statuses, dict) or not isinstance(cached_audio_paths, dict):
        return segment_statuses

    saved_indices = _normalize_segment_indices(cached_audio_paths.keys())
    if not saved_indices:
        return segment_statuses

    updated: Dict[str, Any] = {}
    for raw_key, raw_status in segment_statuses.items():
        key = str(raw_key)
        if not isinstance(raw_status, dict):
            updated[key] = raw_status
            continue

        status = dict(raw_status)
        try:
            index = int(status.get("index", raw_key))
        except Exception:
            updated[key] = status
            continue

        if index in saved_indices and status.get("status") == "cached":
            status["recovery_stage"] = "temp_asset_saved"
        updated[key] = status

    return updated


class TTSMixin:
    def _get_tts_engine_for_segment_model(self, model: Optional[str]):
        normalized_model = normalize_audiobook_tts_model(
            model or getattr(self, "tts_model", None) or DEFAULT_AUDIOBOOK_TTS_MODEL
        )
        current_model = normalize_audiobook_tts_model(getattr(self.tts_engine, "model", None))
        if normalized_model == current_model:
            return self.tts_engine

        engines_by_model = getattr(self, "_tts_engines_by_model", None)
        if not isinstance(engines_by_model, dict):
            engines_by_model = {}
            setattr(self, "_tts_engines_by_model", engines_by_model)

        engine = engines_by_model.get(normalized_model)
        if engine is None:
            engine = create_tts_engine(
                enable_cache=bool(getattr(self.tts_engine, "enable_cache", True)),
                max_concurrent=int(getattr(self.tts_engine, "max_concurrent", 1) or 1),
                model=normalized_model,
                request_delay=float(getattr(self.tts_engine, "request_delay", 0.5) or 0.5),
                retry_config=getattr(self.tts_engine, "retry_config", None),
            )
            engines_by_model[normalized_model] = engine
            logger.info("🎙️ 已为角色级 TTS 模型创建合成引擎: %s", normalized_model)
        return engine

    async def _synthesize_mixed_model_batch(
        self,
        batch_data: List[Dict[str, Any]],
        *,
        debug_save_segments: bool = False,
        debug_output_dir: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> List[bytes]:
        audio_list: List[bytes] = []

        debug_dir = None
        if debug_save_segments:
            from pathlib import Path

            debug_dir = Path(debug_output_dir or "backend/data/tts_debug/mixed_models")
            debug_dir.mkdir(parents=True, exist_ok=True)

        for index, item in enumerate(batch_data):
            text = str(item.get("text") or "")
            voice_params = dict(item.get("voice_params") or {})
            emotion = str(item.get("emotion") or "neutral")
            segment_model = normalize_audiobook_tts_model(
                voice_params.get("tts_model") or getattr(self, "tts_model", None)
            )
            engine = self._get_tts_engine_for_segment_model(segment_model)

            try:
                audio_bytes = await engine.synthesize(text, voice_params, emotion)
            except Exception as exc:
                logger.error(
                    "角色级模型合成失败: index=%s model=%s speaker=%s error=%s",
                    index,
                    segment_model,
                    voice_params.get("speaker"),
                    exc,
                )
                audio_bytes = b""

            audio_list.append(bytes(audio_bytes or b""))

            if debug_dir and audio_bytes:
                try:
                    (debug_dir / f"segment_{index + 1:03d}_{segment_model}.mp3").write_bytes(audio_bytes)
                except Exception as exc:
                    logger.warning("保存混合模型调试音频失败: %s", exc)

            if progress_callback:
                progress_callback(
                    {
                        "event": "segment",
                        "segment_index": index,
                        "audio_bytes": bytes(audio_bytes or b""),
                        "error_message": "" if audio_bytes else "tts_segment_failed",
                        "error_type": "" if audio_bytes else "TTSSegmentError",
                        "batch_index": index,
                        "num_batches": len(batch_data),
                        "start_idx": index,
                        "end_idx": index + 1,
                    }
                )

        return audio_list

    def _build_render_chunks(self, script_segments) -> List[RenderChunk]:
        items = list(script_segments or [])
        if all(isinstance(item, RenderChunk) for item in items):
            return items
        default_model = getattr(self, "tts_model", None)
        segment_models = [_item_tts_model(item) for item in items]
        has_qwen_model = _is_qwen_tts_model(default_model) or any(
            _is_qwen_tts_model(model)
            for model in segment_models
            if model
        )
        max_chunk_chars = QWEN_RENDER_CHUNK_MAX_CHARS if has_qwen_model else None
        return build_render_plan(items, max_chunk_chars=max_chunk_chars)

    def _build_tts_batch_item(self, seg) -> Dict[str, Any]:
        original_text = str(getattr(seg, "text", "") or "")
        pause_result = strip_pause_tags(original_text)
        raw_voice_params = getattr(seg, "voice_params", None)
        voice_params = dict(raw_voice_params) if isinstance(raw_voice_params, dict) else {}
        normalized_text = normalize_tts_prompt(
            pause_result.text,
            substitutions=_extract_tts_substitutions(voice_params),
            protected_words=_extract_tts_protected_words(voice_params),
        )
        voice_params = apply_detected_language_type(voice_params, normalized_text)
        performance_notes = str(getattr(seg, "performance_notes", "") or "").strip()
        if performance_notes:
            voice_params.setdefault("performance_notes", performance_notes)
        resolved_model = resolve_segment_tts_model(
            voice_params,
            getattr(self, "tts_model", None) or DEFAULT_AUDIOBOOK_TTS_MODEL,
        )
        voice_params["resolved_tts_model"] = resolved_model
        voice_params["delivery_plan"] = build_delivery_plan(
            segment=seg,
            voice_params={**voice_params, "text": normalized_text},
            model=resolved_model,
            emotion=(
                getattr(seg, "instruct_emotion", "")
                or voice_params.get("instruct_emotion")
                or voice_params.get("emotion")
                or getattr(seg, "emotion", "neutral")
            ),
        )

        if pause_result.applied:
            voice_params.setdefault("original_tts_text", original_text)
            voice_params["pause_tag_applied"] = True
        if pause_result.pause_after_ms is not None:
            voice_params.setdefault("pause_after_ms", pause_result.pause_after_ms)

        if voice_params.get("timeline_boundary_managed"):
            # Chapter-level cadence is inserted once by the final mixer. Do not let
            # provider-specific SSML/WebSocket controls add the same boundary again.
            voice_params.pop("pause_before", None)
            voice_params.pop("pause_after", None)

        if normalized_text != original_text:
            voice_params.setdefault("original_tts_text", original_text)
            voice_params["normalized_text_applied"] = True

        return {
            "text": normalized_text,
            "voice_params": voice_params,
            "emotion": (
                getattr(seg, "instruct_emotion", "")
                or voice_params.get("instruct_emotion")
                or voice_params.get("emotion")
                or getattr(seg, "emotion", "neutral")
            ),
        }

    def _attach_render_plan_metadata(
        self,
        temp_segment_cache: Optional[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(temp_segment_cache, dict) or not isinstance(metadata, dict):
            return temp_segment_cache
        for key in (
            "render_plan_version",
            "render_chunk_count",
            "render_plan",
            "segment_statuses",
            "failed_segment_indices",
            "failed_segment_errors",
        ):
            if key in metadata:
                temp_segment_cache[key] = metadata[key]
        segment_statuses = temp_segment_cache.get("segment_statuses")
        if isinstance(segment_statuses, dict):
            temp_segment_cache["segment_statuses"] = _mark_temp_asset_saved_segment_statuses(
                segment_statuses=segment_statuses,
                cached_audio_paths=temp_segment_cache.get("cached_audio_paths"),
            )
        return temp_segment_cache

    async def _synthesize_segments(
        self,
        script_segments,
        debug_save_segments: bool = False,
        debug_output_dir: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> List[bytes]:
        """批量合成剧本片段"""
        # 准备批量数据
        render_chunks = self._build_render_chunks(script_segments)
        batch_data = [self._build_tts_batch_item(chunk) for chunk in render_chunks]
        batch_models = {
            normalize_audiobook_tts_model(
                (item.get("voice_params") or {}).get("tts_model")
                or getattr(self, "tts_model", None)
            )
            for item in batch_data
        }

        if len(batch_models) > 1:
            logger.info("🎙️ 检测到角色级混合 TTS 模型，按片段模型合成: %s", sorted(batch_models))
            return await self._synthesize_mixed_model_batch(
                batch_data,
                debug_save_segments=debug_save_segments,
                debug_output_dir=debug_output_dir,
                progress_callback=progress_callback,
            )

        if batch_models:
            only_model = next(iter(batch_models))
            engine = self._get_tts_engine_for_segment_model(only_model)
        else:
            engine = self.tts_engine
        
        # 批量合成（使用分批策略）
        audio_list = await engine.synthesize_batch(
            batch_data,
            batch_size=10,  # 每批10个片段
            batch_interval=0,  # 批次间0秒（取消节流）
            debug_save_segments=debug_save_segments,
            debug_output_dir=debug_output_dir,
            progress_callback=progress_callback,
        )
        
        return audio_list

    def _build_resume_audio_plan(
        self,
        script_segments,
        *,
        resume_checkpoint: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        render_chunks = self._build_render_chunks(script_segments)
        total_segments = len(render_chunks)
        current_signatures = {
            chunk.index: chunk.cache_key
            for chunk in render_chunks
            if chunk.cache_key
        }
        empty_plan = {
            "audio_by_index": {},
            "reused_indices": [],
            "missing_indices": list(range(total_segments)),
            "resume_source": None,
        }
        if total_segments <= 0 or not isinstance(resume_checkpoint, dict) or not resume_checkpoint:
            return empty_plan

        checkpoint_candidates = [("current_checkpoint", resume_checkpoint)]
        source_checkpoint = resume_checkpoint.get("source_checkpoint")
        if isinstance(source_checkpoint, dict) and source_checkpoint:
            checkpoint_candidates.append(("source_checkpoint", source_checkpoint))

        merged_audio_by_index: Dict[int, bytes] = {}
        used_sources: List[str] = []
        for source_name, checkpoint_candidate in checkpoint_candidates:
            raw_total_segments = checkpoint_candidate.get("total_segments")
            try:
                checkpoint_total_segments = int(raw_total_segments) if raw_total_segments is not None else None
            except Exception:
                checkpoint_total_segments = None

            checkpoint_signatures = extract_render_signatures(checkpoint_candidate)

            if checkpoint_total_segments not in {None, 0, total_segments} and not checkpoint_signatures:
                logger.info(
                    "Skip resume cache from %s due to total_segments mismatch: checkpoint=%s current=%s",
                    source_name,
                    checkpoint_total_segments,
                    total_segments,
                )
                continue

            if checkpoint_signatures:
                cached_paths = extract_cached_segment_paths(checkpoint_candidate)
                signature_to_path: Dict[str, str] = {}
                for old_index, signature in checkpoint_signatures.items():
                    path_value = cached_paths.get(old_index)
                    if signature and path_value:
                        signature_to_path.setdefault(signature, path_value)
                remapped_paths = {
                    current_index: signature_to_path[signature]
                    for current_index, signature in current_signatures.items()
                    if signature in signature_to_path
                }
                audio_by_index = load_cached_segment_audio(
                    {"cached_audio_paths": remapped_paths},
                    max_segment_count=total_segments,
                )
            else:
                audio_by_index = load_cached_segment_audio(
                    checkpoint_candidate,
                    max_segment_count=total_segments,
                )
            if not audio_by_index:
                continue

            for index, audio_bytes in audio_by_index.items():
                merged_audio_by_index.setdefault(index, audio_bytes)
            used_sources.append(source_name)

        if merged_audio_by_index:
            reused_indices = sorted(merged_audio_by_index.keys())
            missing_indices = [index for index in range(total_segments) if index not in merged_audio_by_index]
            return {
                "audio_by_index": merged_audio_by_index,
                "reused_indices": reused_indices,
                "missing_indices": missing_indices,
                "resume_source": "+".join(used_sources),
            }

        return empty_plan

    async def _synthesize_segments_with_resume(
        self,
        script_segments,
        *,
        resume_checkpoint: Optional[Dict[str, Any]] = None,
        debug_save_segments: bool = False,
        debug_output_dir: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        render_chunks = self._build_render_chunks(script_segments)
        render_plan_payload = render_plan_to_payload(render_chunks)
        resume_plan = self._build_resume_audio_plan(
            render_chunks,
            resume_checkpoint=resume_checkpoint,
        )
        audio_by_index = dict(resume_plan.get("audio_by_index") or {})
        missing_indices = list(resume_plan.get("missing_indices") or [])
        synthesized_indices: List[int] = []
        failed_segment_indices: List[int] = []
        failed_segment_errors: Dict[int, Dict[str, Any]] = {}

        def emit_progress_payload(
            *,
            batch_index: Optional[int] = None,
            num_batches: Optional[int] = None,
            start_idx: Optional[int] = None,
            end_idx: Optional[int] = None,
        ) -> None:
            if not progress_callback:
                return
            try:
                completed_indices = sorted(audio_by_index.keys())
                reused_indices = list(resume_plan.get("reused_indices") or [])
                failed_indices = sorted(set(failed_segment_indices) - set(completed_indices))
                progress_callback(
                    {
                        "total_segments": len(render_chunks),
                        "completed_segment_indices": completed_indices,
                        "failed_segment_indices": failed_indices,
                        "failed_segment_errors": {
                            str(index): failed_segment_errors[index]
                            for index in failed_indices
                            if index in failed_segment_errors
                        },
                        "audio_by_index": dict(audio_by_index),
                        "resume_source": resume_plan.get("resume_source"),
                        "reused_indices": reused_indices,
                        "reused_count": len(resume_plan.get("reused_indices") or []),
                        "synthesized_indices": list(synthesized_indices),
                        "synthesized_count": len(synthesized_indices),
                        "segment_statuses": _build_segment_statuses(
                            total_segments=len(render_chunks),
                            completed_indices=completed_indices,
                            reused_indices=reused_indices,
                            synthesized_indices=list(synthesized_indices),
                            failed_indices=failed_indices,
                            failed_segment_errors=failed_segment_errors,
                        ),
                        "progress": (
                            len(audio_by_index) / len(render_chunks)
                            if render_chunks
                            else 1.0
                        ),
                        "render_plan_version": RENDER_PLAN_VERSION,
                        "render_chunk_count": len(render_chunks),
                        "render_plan": render_plan_payload,
                        "batch_index": batch_index,
                        "num_batches": num_batches,
                        "start_idx": start_idx,
                        "end_idx": end_idx,
                    }
                )
            except Exception as callback_exc:
                logger.warning("TTS resume progress callback failed: %s", callback_exc)

        if audio_by_index:
            emit_progress_payload()

        if missing_indices:
            missing_segments = [render_chunks[index] for index in missing_indices]
            missing_audio_by_index: Dict[int, bytes] = {}

            def handle_missing_progress(payload: Dict[str, Any]) -> None:
                event_type = str(payload.get("event") or "").strip().lower()
                start_idx = int(payload.get("start_idx") or 0)

                if event_type == "segment":
                    segment_index = int(payload.get("segment_index") or 0)
                    if segment_index < 0 or segment_index >= len(missing_indices):
                        return
                    global_index = missing_indices[segment_index]
                    payload_bytes = bytes(payload.get("audio_bytes") or b"")
                    if payload_bytes:
                        missing_audio_by_index[global_index] = payload_bytes
                        audio_by_index[global_index] = payload_bytes
                        failed_segment_errors.pop(global_index, None)
                        if global_index in failed_segment_indices:
                            failed_segment_indices.remove(global_index)
                    else:
                        if global_index not in failed_segment_indices:
                            failed_segment_indices.append(global_index)
                        failed_segment_errors[global_index] = {
                            "error_message": str(payload.get("error_message") or "tts_segment_failed"),
                            "error_type": str(payload.get("error_type") or "TTSSegmentError"),
                        }
                    synthesized_indices.clear()
                    synthesized_indices.extend(sorted(missing_audio_by_index.keys()))
                    emit_progress_payload(
                        batch_index=payload.get("batch_index"),
                        num_batches=payload.get("num_batches"),
                        start_idx=segment_index,
                        end_idx=segment_index + 1,
                    )
                    return

                if event_type == "batch_completed":
                    return

                batch_audio_list = payload.get("batch_audio_list") or []
                end_idx = int(payload.get("end_idx") or start_idx)
                relative_indices = missing_indices[start_idx:end_idx]
                for global_index, audio_bytes in zip(relative_indices, batch_audio_list):
                    payload_bytes = bytes(audio_bytes or b"")
                    if not payload_bytes:
                        continue
                    missing_audio_by_index[global_index] = payload_bytes
                    audio_by_index[global_index] = payload_bytes
                synthesized_indices.clear()
                synthesized_indices.extend(sorted(missing_audio_by_index.keys()))
                emit_progress_payload(
                    batch_index=payload.get("batch_index"),
                    num_batches=payload.get("num_batches"),
                    start_idx=start_idx,
                    end_idx=end_idx,
                )

            synthesized_audio_list = await self._synthesize_segments(
                missing_segments,
                debug_save_segments=debug_save_segments,
                debug_output_dir=debug_output_dir,
                progress_callback=handle_missing_progress,
            )
            for index, audio_bytes in zip(missing_indices, synthesized_audio_list):
                payload_bytes = bytes(audio_bytes or b"")
                if not payload_bytes:
                    if index not in failed_segment_indices:
                        failed_segment_indices.append(index)
                    failed_segment_errors.setdefault(
                        index,
                        {
                            "error_message": "tts_segment_failed",
                            "error_type": "TTSSegmentError",
                        },
                    )
                    continue
                audio_by_index[index] = payload_bytes
                if index not in synthesized_indices:
                    synthesized_indices.append(index)
                failed_segment_errors.pop(index, None)
                if index in failed_segment_indices:
                    failed_segment_indices.remove(index)

        synthesized_indices = sorted(set(synthesized_indices))
        if progress_callback and (audio_by_index or not missing_indices):
            emit_progress_payload()

        audio_list = [bytes(audio_by_index.get(index, b"")) for index in range(len(render_chunks))]
        completed_indices = sorted(audio_by_index.keys())
        reused_indices = list(resume_plan.get("reused_indices") or [])
        failed_indices = sorted(set(failed_segment_indices) - set(completed_indices))
        return {
            "audio_list": audio_list,
            "resume_source": resume_plan.get("resume_source"),
            "reused_indices": reused_indices,
            "reused_count": len(resume_plan.get("reused_indices") or []),
            "synthesized_indices": synthesized_indices,
            "synthesized_count": len(synthesized_indices),
            "failed_segment_indices": failed_indices,
            "failed_segment_errors": {
                str(index): failed_segment_errors[index]
                for index in failed_indices
                if index in failed_segment_errors
            },
            "segment_statuses": _build_segment_statuses(
                total_segments=len(render_chunks),
                completed_indices=completed_indices,
                reused_indices=reused_indices,
                synthesized_indices=synthesized_indices,
                failed_indices=failed_indices,
                failed_segment_errors=failed_segment_errors,
            ),
            "render_plan_version": RENDER_PLAN_VERSION,
            "render_chunk_count": len(render_chunks),
            "render_plan": render_plan_payload,
            "timing_segments_payload": render_chunks_to_timing_segments_payload(render_chunks),
        }

    def get_tts_dispatch_models(self) -> List[Dict[str, Any]]:
        """获取已注册的 TTS 智能调度模型列表"""
        if TTS_DISPATCH_AVAILABLE and tts_dispatch_client:
            return tts_dispatch_client.get_available_models()
        return []

    def synthesize_with_dispatch(
        self,
        text: str,
        strategy: str = "balanced",
        voice_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[Any]:
        """使用智能调度系统合成语音

        Args:
            text: 要合成的文本
            strategy: 调度策略 (quality/fast/balanced/cost_saving)
            voice_id: 指定音色 ID
            **kwargs: 其他 TTS 参数

        Returns:
            TTSDispatchResult 或 None
        """
        if not self._use_tts_dispatch or not tts_dispatch_client:
            logger.warning("TTS 智能调度系统未启用")
            return None

        return tts_dispatch_client.synthesize(
            text=text,
            strategy=strategy,
            voice_id=voice_id,
            **kwargs,
        )

    async def _synthesize_segments_with_dispatch(
        self,
        script_segments,
        strategy: str = "balanced",
        debug_save_segments: bool = False,
        debug_output_dir: Optional[str] = None,
    ) -> List[bytes]:
        """使用智能调度系统批量合成剧本片段"""
        if not self._use_tts_dispatch or not tts_dispatch_client:
            logger.warning("TTS 智能调度系统未启用，回退到传统引擎")
            return await self._synthesize_segments(
                script_segments,
                debug_save_segments=debug_save_segments,
                debug_output_dir=debug_output_dir,
            )

        batch_data = [self._build_tts_batch_item(seg) for seg in script_segments]
        texts = [seg["text"] for seg in batch_data]
        voice_ids = [seg["voice_params"].get("speaker") for seg in batch_data]

        dispatch_results = tts_dispatch_client.synthesize_batch(
            texts=texts,
            strategy=strategy,
            voice_ids=voice_ids,
            max_concurrent=5,
        )

        audio_list: List[bytes] = []
        for i, result in enumerate(dispatch_results):
            if result and result.success and result.audio_data:
                audio_list.append(result.audio_data)
            else:
                logger.error("TTS 智能调度片段 %s 失败: %s", i + 1, result.error if result else "未知错误")
                audio_list.append(b"")

        if debug_save_segments and audio_list:
            from pathlib import Path
            
            if debug_output_dir:
                debug_dir = Path(debug_output_dir)
            else:
                debug_dir = Path("backend/data/tts_dispatch_debug")
            
            debug_dir.mkdir(parents=True, exist_ok=True)
            logger.info("[调试模式] 保存 TTS 智能调度片段到: %s", debug_dir)
            
            for i, (seg, audio_bytes) in enumerate(zip(script_segments, audio_list), start=1):
                try:
                    audio_file = debug_dir / f"dispatch_segment_{i:03d}.mp3"
                    if audio_bytes and len(audio_bytes) > 0:
                        audio_file.write_bytes(audio_bytes)
                        
                        text_file = debug_dir / f"dispatch_segment_{i:03d}.txt"
                        seg_text = seg.text if hasattr(seg, "text") else ""
                        speaker = seg.voice_params.get("speaker", "unknown") if hasattr(seg, "voice_params") else "unknown"
                        emotion = getattr(seg, "instruct_emotion", "") or getattr(seg, "emotion", "neutral")
                        text_file.write_text(
                            f"片段 {i}\n"
                            f"长度: {len(seg_text)} 字符\n"
                            f"音频大小: {len(audio_bytes)} 字节\n"
                            f"音色: {speaker}\n"
                            f"情感: {emotion}\n"
                            f"\n文本内容:\n{seg_text}\n",
                            encoding="utf-8"
                        )
                except Exception as e:
                    logger.error("保存片段 %03d 失败: %s", i, e)

        return audio_list


def _extract_tts_substitutions(voice_params: Dict[str, Any]) -> Optional[Dict[str, str]]:
    for key in (
        "tts_substitutions",
        "word_substitutions",
        "pronunciation_substitutions",
        "pronunciation_dictionary",
    ):
        parsed = _coerce_substitution_mapping(voice_params.get(key))
        if parsed:
            return parsed
    return None


def _coerce_substitution_mapping(value: Any) -> Dict[str, str]:
    if isinstance(value, dict):
        return {
            str(key).strip(): str(raw_value).strip()
            for key, raw_value in value.items()
            if str(key).strip() and str(raw_value).strip()
        }
    if isinstance(value, list):
        output: Dict[str, str] = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            source = (
                item.get("source")
                or item.get("from")
                or item.get("word")
                or item.get("pattern")
                or item.get("term")
            )
            target = (
                item.get("target")
                or item.get("to")
                or item.get("replacement")
                or item.get("pronunciation")
                or item.get("reading")
            )
            source_text = str(source or "").strip()
            target_text = str(target or "").strip()
            if source_text and target_text:
                output[source_text] = target_text
        return output
    return {}


def _extract_tts_protected_words(voice_params: Dict[str, Any]) -> Optional[Set[str]]:
    protected_words: Set[str] = set()
    for key in (
        "tts_protected_words",
        "protected_words",
        "pronunciation_protected_words",
    ):
        protected_words.update(_coerce_word_set(voice_params.get(key)))
    return protected_words or None


def _coerce_word_set(value: Any) -> Set[str]:
    if isinstance(value, str):
        return {item.strip() for item in value.split(",") if item.strip()}
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item).strip()}
    return set()

