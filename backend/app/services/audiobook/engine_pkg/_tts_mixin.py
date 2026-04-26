from __future__ import annotations

import asyncio
import logging
import time
import math
import json
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path
from dataclasses import asdict, is_dataclass

from ..script_adapter import AudiobookScriptAgent, ScriptSegment, ChapterStructure
from ..voice_manager_factory import create_voice_manager
from ..audio_mixer import AudioMixer
from app.services.chapter_adaptation_assets import build_audio_adaptation_hint
from app.services.audiobook.temp_segment_store import load_cached_segment_audio
from core.unified_media_runtime import create_tts_engine

try:
    from ..agent_dispatch_client import client as tts_dispatch_client
    from ..agent_dispatch_client import TTSDispatchResult
    TTS_DISPATCH_AVAILABLE = True
except ImportError:
    TTS_DISPATCH_AVAILABLE = False
    tts_dispatch_client = None
    TTSDispatchResult = None

# 导入专业Agent
from ..agents import (
    AudioDirector,
    VoiceDesigner,
    SoundEffectDesigner,
    MusicComposer,
)

logger = logging.getLogger(__name__)

class TTSMixin:
    async def _synthesize_segments(
        self,
        script_segments,
        debug_save_segments: bool = False,
        debug_output_dir: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> List[bytes]:
        """批量合成剧本片段"""
        # 准备批量数据
        batch_data = [
            {
                "text": seg.text,
                "voice_params": seg.voice_params if hasattr(seg, 'voice_params') else {},
                "emotion": (getattr(seg, "instruct_emotion", "") or getattr(seg, "emotion", "neutral"))
            }
            for seg in script_segments
        ]
        
        # 批量合成（使用分批策略）
        audio_list = await self.tts_engine.synthesize_batch(
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
        total_segments = len(script_segments or [])
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

            if checkpoint_total_segments not in {None, 0, total_segments}:
                logger.info(
                    "Skip resume cache from %s due to total_segments mismatch: checkpoint=%s current=%s",
                    source_name,
                    checkpoint_total_segments,
                    total_segments,
                )
                continue

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
        resume_plan = self._build_resume_audio_plan(
            script_segments,
            resume_checkpoint=resume_checkpoint,
        )
        audio_by_index = dict(resume_plan.get("audio_by_index") or {})
        missing_indices = list(resume_plan.get("missing_indices") or [])
        synthesized_indices: List[int] = []

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
                progress_callback(
                    {
                        "total_segments": len(script_segments or []),
                        "completed_segment_indices": sorted(audio_by_index.keys()),
                        "audio_by_index": dict(audio_by_index),
                        "resume_source": resume_plan.get("resume_source"),
                        "reused_indices": list(resume_plan.get("reused_indices") or []),
                        "reused_count": len(resume_plan.get("reused_indices") or []),
                        "synthesized_indices": list(synthesized_indices),
                        "synthesized_count": len(synthesized_indices),
                        "progress": (
                            len(audio_by_index) / len(script_segments)
                            if script_segments
                            else 1.0
                        ),
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
            missing_segments = [script_segments[index] for index in missing_indices]
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
                    continue
                audio_by_index[index] = payload_bytes
                if index not in synthesized_indices:
                    synthesized_indices.append(index)

        synthesized_indices = sorted(set(synthesized_indices))
        if progress_callback and (audio_by_index or not missing_indices):
            emit_progress_payload()

        audio_list = [bytes(audio_by_index.get(index, b"")) for index in range(len(script_segments or []))]
        return {
            "audio_list": audio_list,
            "resume_source": resume_plan.get("resume_source"),
            "reused_indices": list(resume_plan.get("reused_indices") or []),
            "reused_count": len(resume_plan.get("reused_indices") or []),
            "synthesized_indices": synthesized_indices,
            "synthesized_count": len(synthesized_indices),
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

        texts = [seg.text for seg in script_segments]
        voice_ids = [
            seg.voice_params.get("speaker") if hasattr(seg, "voice_params") else None
            for seg in script_segments
        ]

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

