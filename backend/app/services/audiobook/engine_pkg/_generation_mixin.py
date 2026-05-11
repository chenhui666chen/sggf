from __future__ import annotations

import asyncio
import logging
import time
import math
import json
from typing import List, Dict, Any, Optional, Callable
from dataclasses import asdict, is_dataclass

from ..script_adapter import AudiobookScriptAgent, ScriptSegment, ChapterStructure
from ..script_adapter_pkg._llm_review import summarize_script_review_report
from ..voice_manager_factory import create_voice_manager
from ..audio_mixer import AudioMixer
from ..task_tracker import StageType
from app.services.chapter_adaptation_assets import build_audio_adaptation_hint
from app.services.audiobook.render_plan import render_chunks_to_timing_segments_payload
from app.services.audiobook.temp_segment_store import save_segment_audio_batch, save_segment_audio_map
from app.services.audiobook.atomic_files import write_bytes_atomic
from core.unified_media_runtime import create_tts_engine

try:
    from app.websocket.manager import ws_manager
    WEBSOCKET_AVAILABLE = True
except Exception:  # pragma: no cover - WebSocket is optional for generation workers.
    ws_manager = None
    WEBSOCKET_AVAILABLE = False

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

class GenerationMixin:
    async def generate_chapter_audio(
        self,
        chapter_content: str,
        chapter_id: int,
        character_list: Optional[List[str]] = None,
        output_path: Optional[str] = None,
        novel_genre: str = "科幻",
        novel_theme: str = "未知主题",
        enable_quality_review: bool = True,
        quality_threshold: float = 70.0,
        audiobook_project_id: Optional[int] = None,  # 新增：用于WebSocket推送
        output_format: str = "mp3",
        chapter_title: str = "",
        chapter_summary: str = "",
        summary_data: Any = None,
        character_profiles: Optional[List[Dict[str, Any]]] = None,
        resume_checkpoint: Optional[Dict[str, Any]] = None,
        tts_progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """
        生成单章节有声书
        
        Args:
            chapter_content: 章节文本
            chapter_id: 章节ID
            character_list: 角色列表（可选）
            output_path: 输出路径（可选）
            novel_genre: 小说类型
            novel_theme: 小说主题
        
        Returns:
            {
                "success": True/False,
                "audio_data": bytes,
                "duration": 秒,
                "file_size": 字节,
                "stats": {...}
            }
        """
        start_time = time.time()
        
        # 创建任务追踪
        task_id = self.task_tracker.create_task(
            chapter_id=chapter_id,
            novel_genre=novel_genre,
            novel_theme=novel_theme,
            metadata={"character_list": character_list}
        )
        
        logger.info(f"{'='*70}")
        logger.info(f"🎬 开始生成章节有声书: Chapter {chapter_id} [TaskID: {task_id[:8]}]")
        logger.info(f"{'='*70}")
        
        try:
            quality_report = None  # 剧本级质量评审结果
            final_audio_review = None  # 最终音频评审结果
            auto_revision: Dict[str, Any] = {"applied": False}
            # ============ 阶段1：制定改编策略 ============
            self.task_tracker.start_stage(task_id, StageType.STRATEGY)
            logger.info("🎭 [1/6] AudioDirector制定改编策略...")
            
            # 📡 WebSocket推送：策略阶段开始
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='strategy',
                    progress=0,
                    message='正在制定改编策略...'
                )
            
            strategy = self.audio_director.formulate_strategy(
                novel_genre=novel_genre,
                novel_theme=novel_theme,
                target_audience="通用听众"
            )

            # 应用项目级音效/BGM 配置对策略进行微调（如控制音效/配乐密度）
            self._apply_audio_fx_to_strategy(strategy)

            # 将导演策略传递给剧本改编Agent，启用语义完整性控制
            self.script_adapter.strategy = strategy
            
            self.task_tracker.complete_stage(task_id, StageType.STRATEGY, metrics={
                "style": strategy.style.value,
                "sound_density": strategy.sound_effect_density
            })
            logger.info(f"   ✅ 策略: {strategy.style.value}, 音效密度: {strategy.sound_effect_density}")
            
            # 📡 WebSocket推送：策略阶段完成
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='strategy',
                    progress=100,
                    message=f'策略完成: {strategy.style.value}',
                    stage_metrics={'style': strategy.style.value, 'sound_density': strategy.sound_effect_density}
                )
            
            # ============ 阶段2：剧本改编 ============
            self.task_tracker.start_stage(task_id, StageType.SCRIPT_ADAPTATION)
            logger.info("📝 [2/6] AudiobookScriptAdapter剧本改编...")
            
            # 📡 WebSocket推送：剧本阶段开始
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='script_adaptation',
                    progress=0,
                    message='正在改编剧本...'
                )
            
            def on_script_progress(progress: float, metrics: Optional[Dict[str, Any]] = None) -> None:
                self.task_tracker.update_stage_progress(
                    task_id,
                    StageType.SCRIPT_ADAPTATION,
                    progress,
                    metrics,
                )

            audio_adaptation_context = build_audio_adaptation_hint(
                summary_data,
                chapter_title=chapter_title,
                chapter_summary=chapter_summary,
            )
            adapted_result = await self.script_adapter.adapt_chapter(
                chapter_content=chapter_content,
                character_list=character_list,
                character_profiles=character_profiles,
                chapter_title=chapter_title or f"Chapter {chapter_id}",
                genre=novel_genre,
                adaptation_context=audio_adaptation_context,
                progress_callback=on_script_progress,
                enable_llm_script_review=enable_quality_review,
            )
            
            # 兼容 ChapterStructure 与纯片段列表两种返回形式
            if isinstance(adapted_result, ChapterStructure):
                chapter_structure = adapted_result
                script_segments = self._flatten_chapter_structure(chapter_structure)
                segments_count = chapter_structure.get_total_segments()
            else:
                chapter_structure = None
                script_segments = adapted_result
                segments_count = len(script_segments)

            llm_script_review = getattr(self.script_adapter, "last_script_review", None)
            llm_script_review_summary = summarize_script_review_report(llm_script_review)

            script_stage_metrics = {
                "segments_count": segments_count,
                "text_length": len(chapter_content),
            }
            if llm_script_review_summary:
                script_stage_metrics["llm_script_review"] = llm_script_review_summary

            self.task_tracker.complete_stage(
                task_id,
                StageType.SCRIPT_ADAPTATION,
                metrics=script_stage_metrics,
            )
            logger.info(f"   ✅ 生成 {segments_count} 个剧本片段")
            
            # 📡 WebSocket推送：剧本阶段完成
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='script_adaptation',
                    progress=100,
                    message=f'剧本改编完成：{len(script_segments)}个片段',
                    stage_metrics={'segments_count': len(script_segments)}
                )
            
            # ============ 阶段3-5：并行设计（音色+音效+音乐） ============
            logger.info("🎵 [3-5/8] 并行设计：音色+音效+音乐...")
            
            # 📡 WebSocket推送：设计阶段开始
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='design',
                    progress=0,
                    message='正在并行设计音色、音效、音乐...'
                )
            
            # 并行执行三个设计阶段
            # 👉 关键修复：只为未配置的角色设计音色，避免覆盖用户配置
            voice_profiles, sound_effects_count, music_cues_count = await self._parallel_design(
                task_id,
                script_segments,
                chapter_content,
                preserve_user_config=True,  # 🔥 保留用户配置
                chapter_id=chapter_id,
                audiobook_project_id=audiobook_project_id,
            )
            
            logger.info(f"   ✅ 并行设计完成")
            logger.info(f"      - 音色: {len(voice_profiles) if voice_profiles else 0} 个角色")
            logger.info(f"      - 音效: {sound_effects_count} 个标注")
            logger.info(f"      - 音乐: {music_cues_count} 个提示")
            
            # 📡 WebSocket推送：设计阶段完成
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='design',
                    progress=100,
                    message=f'设计完成：{len(voice_profiles) if voice_profiles else 0}个角色、{sound_effects_count}个音效、{music_cues_count}个配乐',
                    stage_metrics={
                        'voice_count': len(voice_profiles) if voice_profiles else 0,
                        'sound_effects_count': sound_effects_count,
                        'music_cues_count': music_cues_count
                    }
                )

            # ============ 阶段6：剧本质量评审（TTS 前） ============
            if enable_quality_review:
                self.task_tracker.start_stage(task_id, StageType.QUALITY_REVIEW)
                logger.info("🔍 [6/8] AudioQualityReviewer剧本质量评审（TTS前）...")
                
                quality_report, auto_revision = self._run_quality_review_with_auto_revision(
                    script_segments,
                    novel_genre=novel_genre,
                    quality_threshold=quality_threshold,
                )

                review_segments = self._build_review_segments(script_segments)
                sample_segments = [
                    {
                        "index": idx,
                        "type": seg_dict["type"],
                        "speaker": seg_dict["speaker"],
                        "text": seg_dict["text"],
                        "emotion": seg_dict["emotion"],
                    }
                    for idx, seg_dict in enumerate(review_segments[:50])
                ]
                
                issues_preview = [
                    {
                        "location": issue.location,
                        "severity": issue.severity,
                        "category": issue.category,
                        "description": issue.description,
                        "suggestion": issue.suggestion,
                    }
                    for issue in quality_report.issues[:20]
                ]
                quality_stage_metrics = {
                    "overall_score": quality_report.overall_score,
                    "overall_grade": quality_report.overall_grade,
                    "issues_count": len(quality_report.issues),
                    "script_quality": quality_report.script_quality,
                    "audio_balance": quality_report.audio_balance,
                    "pacing": quality_report.pacing,
                    "revision_suggestions": quality_report.revision_suggestions,
                    "sample_segments": sample_segments,
                    "issues": issues_preview,
                    "auto_revision": auto_revision if auto_revision.get("applied") else None,
                    "quality_gate": auto_revision.get("quality_gate"),
                }
                if llm_script_review_summary:
                    quality_stage_metrics["llm_script_review"] = llm_script_review_summary
                self.task_tracker.complete_stage(
                    task_id,
                    StageType.QUALITY_REVIEW,
                    metrics=quality_stage_metrics,
                )
                
                logger.info(f"   ✅ 剧本评审完成: {quality_report.overall_grade} ({quality_report.overall_score:.1f}分)")
                logger.info(f"   发现 {len(quality_report.issues)} 个问题")
                
                quality_gate = auto_revision.get("quality_gate") or {}
                if not quality_gate.get("passed", True):
                    logger.warning(
                        "⚠️ 剧本质量闸门未通过，停止进入 TTS: %.1f < %.1f",
                        quality_report.overall_score,
                        quality_gate.get("threshold", quality_threshold),
                    )
                    logger.warning(f"   修订建议: {', '.join(quality_report.revision_suggestions)}")
                    for issue in quality_report.issues[:5]:
                        logger.warning(f"   - [{issue.severity}] {issue.description}")
                
                # 📡 WebSocket推送：剧本质量评审完成
                if WEBSOCKET_AVAILABLE and audiobook_project_id:
                    await ws_manager.send_audiobook_progress(
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        stage='quality_review',
                        progress=100,
                        message=f'剧本质量评审完成：{quality_report.overall_grade} ({quality_report.overall_score:.1f}分)',
                        stage_metrics={
                            'overall_score': quality_report.overall_score,
                            'overall_grade': quality_report.overall_grade,
                            'issues_count': len(quality_report.issues),
                            'quality_gate': quality_gate,
                        }
                    )

                if auto_revision.get("applied"):
                    try:
                        _, sound_effects_count, music_cues_count = await self._parallel_design(
                            task_id,
                            script_segments,
                            chapter_content,
                            preserve_user_config=True,
                            chapter_id=chapter_id,
                            audiobook_project_id=audiobook_project_id,
                            skip_stage_tracking=True,
                            include_voice_design=False,
                        )

                        audio_fx = getattr(self, "_audio_fx_config", None)
                        sound_metrics = {"sound_effects_count": sound_effects_count}
                        if self._last_effect_timeline:
                            sound_metrics["timeline"] = self._last_effect_timeline
                        if audio_fx:
                            enable_sfx = audio_fx.get("enable_sound_effects", True)
                            sfx_density = str(audio_fx.get("sound_effect_density") or "").lower()
                            if (not enable_sfx) or sfx_density == "off":
                                sound_metrics["skipped"] = True
                        self.task_tracker.complete_stage(
                            task_id,
                            StageType.SOUND_DESIGN,
                            metrics=sound_metrics,
                        )

                        music_metrics = {"music_cues_count": music_cues_count}
                        if self._last_music_timeline:
                            music_metrics["timeline"] = self._last_music_timeline
                        if audio_fx:
                            enable_music = audio_fx.get("enable_music", True)
                            music_density = str(audio_fx.get("music_density") or "").lower()
                            if (not enable_music) or music_density == "off":
                                music_metrics["skipped"] = True
                        self.task_tracker.complete_stage(
                            task_id,
                            StageType.MUSIC_COMPOSITION,
                            metrics=music_metrics,
                        )

                        logger.info("Auto revision applied; refreshed sound/music timelines.")
                    except Exception as exc:
                        logger.warning("Auto revision refresh failed: %s", exc)

                if not quality_gate.get("passed", True):
                    gate_reason = (
                        f"script_quality_gate_failed:"
                        f"{quality_report.overall_score:.1f}<"
                        f"{float(quality_gate.get('threshold') or quality_threshold):.1f}"
                    )
                    if WEBSOCKET_AVAILABLE and audiobook_project_id:
                        await ws_manager.send_audiobook_progress(
                            audiobook_project_id=audiobook_project_id,
                            chapter_id=chapter_id,
                            stage='quality_review',
                            progress=100,
                            message='剧本质量未通过，已停止进入语音合成',
                            stage_metrics=quality_stage_metrics,
                        )
                    self.task_tracker.fail_stage(task_id, StageType.QUALITY_REVIEW, gate_reason)
                    elapsed_time = time.time() - start_time
                    return {
                        "success": False,
                        "task_id": task_id,
                        "error": "script_quality_gate_failed",
                        "message": "剧本质量评审未通过，已在 TTS 合成前停止",
                        "script_segments_payload": self._build_review_segments(script_segments),
                        "quality_report_detail": self._quality_report_to_payload(
                            quality_report,
                            auto_revision=auto_revision,
                            llm_script_review=llm_script_review,
                        ),
                        "stats": {
                            "generation_time": f"{elapsed_time:.1f}秒",
                            "mode": "专业Agent模式",
                            "script_segments": len(script_segments),
                            "quality_report": {
                                "overall_grade": quality_report.overall_grade,
                                "overall_score": quality_report.overall_score,
                                "issues_count": len(quality_report.issues),
                                "revision_suggestions": quality_report.revision_suggestions,
                                "auto_revision": auto_revision if auto_revision.get("applied") else None,
                                "quality_gate": quality_gate,
                                "llm_script_review": llm_script_review_summary,
                            },
                            "llm_script_review": llm_script_review_summary,
                        },
                    }
            else:
                # 跳过质量评审，标记为已完成
                self.task_tracker.complete_stage(task_id, StageType.QUALITY_REVIEW, metrics={
                    "skipped": True
                })
                if WEBSOCKET_AVAILABLE and audiobook_project_id:
                    await ws_manager.send_audiobook_progress(
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        stage='quality_review',
                        progress=100,
                        message='已跳过剧本质量评审（配置关闭）',
                        stage_metrics={'skipped': True}
                    )
            
            # ============ 阶段7：音频提示词审阅 ============
            self._assign_voices(script_segments)
            self.task_tracker.start_stage(task_id, StageType.AUDIO_PROMPT_REVIEW)
            prompt_metrics = {
                "segments_count": len(script_segments),
                "sound_effects_count": sum(len(getattr(seg, "sound_effects", []) or []) for seg in script_segments),
                "music_cues_count": sum(
                    1
                    for seg in script_segments
                    if getattr(seg, "music_cue", None) or getattr(seg, "music_cue_simple", "")
                ),
                "instruct_count": sum(
                    1
                    for seg in script_segments
                    if (getattr(seg, "instruct_emotion", "") or getattr(seg, "instruct_scene", "") or getattr(seg, "instruct_role", "") or getattr(seg, "instruct_identity", ""))
                ),
            }
            if llm_script_review_summary:
                prompt_metrics["llm_script_review"] = llm_script_review_summary
            self.task_tracker.complete_stage(task_id, StageType.AUDIO_PROMPT_REVIEW, metrics=prompt_metrics)
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='audio_prompt_review',
                    progress=100,
                    message='音频提示词准备完成，可进入审阅',
                    stage_metrics=prompt_metrics,
                )

            # ============ 阶段8：TTS合成 ============
            self.task_tracker.start_stage(task_id, StageType.TTS_SYNTHESIS)
            logger.info("🎙️ [8/10] TTS合成中...")
            
            # 📡 WebSocket推送：TTS阶段开始
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='tts_synthesis',
                    progress=0,
                    message=f'正在合成{len(script_segments)}个音频片段...'
                )
            
            temp_segment_cache: Optional[Dict[str, Any]] = None

            def handle_tts_progress(progress_payload: Dict[str, Any]) -> None:
                nonlocal temp_segment_cache
                audio_by_index = progress_payload.get("audio_by_index") or {}
                if not isinstance(audio_by_index, dict):
                    return

                temp_segment_cache = save_segment_audio_map(
                    run_id=task_id,
                    chapter_id=chapter_id,
                    audio_map=audio_by_index,
                    format="mp3",
                )
                temp_segment_cache = self._attach_render_plan_metadata(temp_segment_cache, progress_payload)
                if isinstance(temp_segment_cache, dict) and isinstance(
                    temp_segment_cache.get("segment_statuses"),
                    dict,
                ):
                    progress_payload = {
                        **progress_payload,
                        "segment_statuses": temp_segment_cache["segment_statuses"],
                    }
                completed_segment_indices = sorted(
                    int(index)
                    for index in (progress_payload.get("completed_segment_indices") or [])
                    if isinstance(index, int) or (isinstance(index, str) and str(index).isdigit())
                )
                total_segments = int(progress_payload.get("total_segments") or len(script_segments) or 0)
                progress_value = float(progress_payload.get("progress") or 0.0)
                tts_metrics_snapshot = {
                    "tts_stats": self.tts_engine.get_cost_stats(),
                    "total_segments": total_segments,
                    "completed_segment_count": len(completed_segment_indices),
                    "completed_segment_indices": completed_segment_indices,
                    "reused_segment_count": int(progress_payload.get("reused_count") or 0),
                    "synthesized_segment_count": int(progress_payload.get("synthesized_count") or 0),
                    "resume_source": progress_payload.get("resume_source"),
                    "temp_segment_cache": temp_segment_cache,
                }
                self.task_tracker.update_stage_progress(
                    task_id,
                    StageType.TTS_SYNTHESIS,
                    progress_value,
                    tts_metrics_snapshot,
                )
                if tts_progress_callback:
                    tts_progress_callback(
                        {
                            **progress_payload,
                            "task_id": task_id,
                            "chapter_id": chapter_id,
                            "temp_segment_cache": temp_segment_cache,
                            "tts_stats": tts_metrics_snapshot["tts_stats"],
                        }
                    )

            synthesis_result = await self._synthesize_segments_with_resume(
                script_segments,
                resume_checkpoint=resume_checkpoint,
                progress_callback=handle_tts_progress,
            )
            audio_list = synthesis_result["audio_list"]
            reused_segment_indices = synthesis_result.get("reused_indices") or []
            if reused_segment_indices:
                logger.info(
                    "♻️ TTS 断点复用命中: chapter_id=%s reused=%s synthesized=%s source=%s",
                    chapter_id,
                    len(reused_segment_indices),
                    synthesis_result.get("synthesized_count", 0),
                    synthesis_result.get("resume_source"),
                )
            if not temp_segment_cache or len(temp_segment_cache.get("cached_audio_paths") or {}) < len(
                [audio_bytes for audio_bytes in audio_list if audio_bytes]
            ):
                try:
                    temp_segment_cache = save_segment_audio_batch(
                        run_id=task_id,
                        chapter_id=chapter_id,
                        audio_list=audio_list,
                        format="mp3",
                    )
                    temp_segment_cache = self._attach_render_plan_metadata(temp_segment_cache, synthesis_result)
                except Exception as cache_err:
                    logger.warning("⚠️ 保存临时分段音频失败: %s", cache_err)
            
            tts_stats = self.tts_engine.get_cost_stats()

            tts_stage_metrics = {
                "tts_stats": tts_stats,
                "reused_segment_count": len(reused_segment_indices),
                "synthesized_segment_count": synthesis_result.get("synthesized_count", len(script_segments)),
            }
            if reused_segment_indices:
                tts_stage_metrics["reused_segment_indices"] = list(reused_segment_indices)
                if synthesis_result.get("resume_source"):
                    tts_stage_metrics["resume_source"] = synthesis_result.get("resume_source")
            if temp_segment_cache:
                tts_stage_metrics["temp_segment_count"] = temp_segment_cache.get("segment_count", 0)
            if synthesis_result.get("render_chunk_count") is not None:
                tts_stage_metrics["render_chunk_count"] = synthesis_result.get("render_chunk_count")

            self.task_tracker.complete_stage(task_id, StageType.TTS_SYNTHESIS, metrics=tts_stage_metrics)
            logger.info(f"   ✅ TTS完成: {tts_stats}")
            
            # 📡 WebSocket推送：TTS阶段完成
            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='tts_synthesis',
                    progress=100,
                    message='音频合成完成',
                    stage_metrics=tts_stats
                )
            
            build_render_chunks = getattr(self, "_build_render_chunks", None)
            render_chunks = (
                build_render_chunks(script_segments)
                if callable(build_render_chunks)
                else list(script_segments or [])
            )
            mixer_segments = render_chunks if len(render_chunks) == len(audio_list) else script_segments
            timing_segments_payload = synthesis_result.get("timing_segments_payload")
            if (
                not isinstance(timing_segments_payload, list)
                and len(render_chunks) == len(audio_list)
                and all(hasattr(chunk, "source_segment_indices") for chunk in render_chunks)
            ):
                timing_segments_payload = render_chunks_to_timing_segments_payload(render_chunks)

            # 基于真实音频时长对齐音效/配乐时间线
            realign_with_render_chunks = getattr(self, "_realign_timelines_with_render_chunks", None)
            if (
                callable(realign_with_render_chunks)
                and len(render_chunks) == len(audio_list)
                and all(hasattr(chunk, "source_segment_indices") for chunk in render_chunks)
            ):
                realign_with_render_chunks(script_segments, render_chunks, audio_list)
            else:
                self._realign_timelines_with_audio(script_segments, audio_list)

            # ============ 阶段9：音频混合 ============
            self.task_tracker.start_stage(task_id, StageType.AUDIO_MIXING)
            logger.info("🎧 [9/10] 音频混合中...")
            
            segment_types = self._build_mixer_segment_types(mixer_segments)
            build_pause_after_ms = getattr(self, "_build_mixer_pause_after_ms", None)
            pause_after_ms = (
                build_pause_after_ms(mixer_segments)
                if callable(build_pause_after_ms)
                else [None] * len(audio_list)
            )
            build_segment_timeline = getattr(self.audio_mixer, "build_segment_timeline", None)
            segment_timings = []
            if callable(build_segment_timeline):
                try:
                    segment_timings = build_segment_timeline(
                        audio_list,
                        segment_types=segment_types,
                        pause_after_ms=pause_after_ms,
                    )
                except TypeError:
                    segment_timings = build_segment_timeline(audio_list, segment_types=segment_types)
            try:
                final_audio = self.audio_mixer.mix_chapter(
                    audio_list,
                    output_format=output_format,
                    segment_types=segment_types,
                    pause_after_ms=pause_after_ms,
                )
            except TypeError:
                final_audio = self.audio_mixer.mix_chapter(audio_list, segment_types=segment_types)
            
            # 应用音效时间线（如有）
            if self._last_effect_timeline and self._last_effect_timeline.get("timeline"):
                logger.info("🎛 应用音效时间线叠加音效...")
                final_audio = self._apply_sound_effects(final_audio, self._last_effect_timeline)
            
            # 应用配乐时间线（如有）
            if self._last_music_timeline and self._last_music_timeline.get("timeline"):
                logger.info("🎼 应用配乐时间线叠加BGM...")
                final_audio = self._apply_background_music(final_audio, self._last_music_timeline)
            
            # 允许空音频（用于MVP测试）
            transcode_audio = getattr(self.audio_mixer, "transcode_audio", None)
            if callable(transcode_audio):
                final_audio = transcode_audio(
                    final_audio,
                    output_format=output_format,
                )

            if not final_audio:
                logger.warning("⚠️ 音频为空，生成占位数据")
                final_audio = b""  # 空字节
                
            audio_info = self.audio_mixer.get_audio_info(final_audio)
            
            self.task_tracker.complete_stage(task_id, StageType.AUDIO_MIXING, metrics={
                "audio_info": audio_info,
                "segment_timing_count": len(segment_timings),
            })
            logger.info(f"   ✅ 混合完成: {audio_info}")
            
            # ============ 阶段10：最终音频评审（可选） ============
            if enable_quality_review:
                self.task_tracker.start_stage(task_id, StageType.FINAL_AUDIO_REVIEW)
                logger.info("🔎 [10/10] 最终音频评审（基于音频信息）...")
                
                final_audio_review = self._final_audio_review(
                    audio_info=audio_info,
                    file_size=len(final_audio),
                    script_quality_report=quality_report,
                    audio_data=final_audio,
                )

                self.task_tracker.complete_stage(task_id, StageType.FINAL_AUDIO_REVIEW, metrics=final_audio_review)
                
                logger.info(f"   ✅ 最终音频评审完成: {final_audio_review.get('summary', '')}")
            else:
                # 跳过音频评审，标记为已完成
                self.task_tracker.complete_stage(task_id, StageType.FINAL_AUDIO_REVIEW, metrics={
                    "skipped": True
                })
            
            # ============ 阶段11：保存文件（可选） ============
            if output_path:
                write_bytes_atomic(output_path, final_audio)
                logger.info(f"💾 音频已保存: {output_path}")
            
            # ============ 阶段12：统计结果 ============
            elapsed_time = time.time() - start_time
            
            # 标记任务完成
            self.task_tracker.complete_task(task_id)
            
            # 统计对话和旁白数量（兼容parse_stats）
            dialogue_count = 0
            narration_count = 0
            for seg in script_segments:
                if hasattr(seg, 'type'):
                    if seg.type == "dialogue":
                        dialogue_count += 1
                    elif seg.type == "narration":
                        narration_count += 1
            
            script_segments_payload: List[Dict[str, Any]] = []
            for seg in script_segments:
                if is_dataclass(seg):
                    script_segments_payload.append(asdict(seg))
                elif isinstance(seg, dict):
                    script_segments_payload.append(seg)
                else:
                    script_segments_payload.append(getattr(seg, "__dict__", seg))

            quality_report_payload = self._quality_report_to_payload(
                quality_report,
                auto_revision=auto_revision,
                llm_script_review=llm_script_review,
            )

            result = {
                "success": True,
                "task_id": task_id,  # 返回任务ID
                "audio_data": final_audio,
                "duration": audio_info.get("duration_seconds", 0),
                "file_size": len(final_audio),
                "segment_timings": segment_timings,
                "script_segments_payload": script_segments_payload,
                "timing_segments_payload": timing_segments_payload,
                "quality_report_detail": quality_report_payload,
                "temp_segment_cache": temp_segment_cache,
                "stats": {
                    "generation_time": f"{elapsed_time:.1f}秒",
                    "mode": "专业Agent模式",
                    # 兼容旧版API的parse_stats结构
                    "parse_stats": {
                        "total_segments": len(script_segments),
                        "dialogue_count": dialogue_count,
                        "narration_count": narration_count,
                    },
                    "script_segments": len(script_segments),
                    "characters": len(characters_in_script) if 'characters_in_script' in locals() else 0,
                    "sound_effects": sound_effects_count if 'sound_effects_count' in locals() else 0,
                    "music_cues": music_cues_count if 'music_cues_count' in locals() else 0,
                    "tts_stats": tts_stats,
                    "audio_info": audio_info,
                    "quality_report": {
                        "overall_grade": quality_report.overall_grade,
                        "overall_score": quality_report.overall_score,
                        "issues_count": len(quality_report.issues),
                        "revision_suggestions": quality_report.revision_suggestions,
                        "auto_revision": auto_revision if auto_revision.get("applied") else None,
                        "quality_gate": auto_revision.get("quality_gate"),
                        "llm_script_review": llm_script_review_summary,
                    } if quality_report else None,
                    "llm_script_review": llm_script_review_summary,
                    "final_audio_review": final_audio_review,
                }
            }
            if self._last_effect_timeline and self._last_effect_timeline.get("timeline"):
                result["effect_timeline"] = self._last_effect_timeline
            
            logger.info(f"{'='*70}")
            if len(final_audio) > 0:
                logger.info(f"✅ 章节生成成功!")
            else:
                logger.info(f"⚠️ 章节生成完成（模拟模式，无真实音频）")
                logger.info(f"   提示: 请配置 DASHSCOPE_API_KEY 环境变量以生成真实音频")
            logger.info(f"   - 时长: {audio_info.get('duration_seconds', 0):.1f}秒")
            logger.info(f"   - 大小: {len(final_audio)/1024:.1f}KB")
            logger.info(f"   - 耗时: {elapsed_time:.1f}秒")
            logger.info(f"   - 成本: {tts_stats.get('estimated_cost', '¥0.00')}")
            logger.info(f"{'='*70}\n")
            
            return result
                
        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(f"❌ 章节生成失败: {e}")
            import traceback
            traceback.print_exc()
            
            # 标记任务失败（如果task_id已创建）
            if 'task_id' in locals():
                # 尝试获取当前阶段
                task_status = self.task_tracker.get_task_status(task_id)
                if task_status:
                    for stage_name, stage_info in task_status['stages'].items():
                        if stage_info['status'] == 'running':
                            self.task_tracker.fail_stage(
                                task_id,
                                StageType(stage_name),
                                str(e)
                            )
                            break
            
            failure_stats: Dict[str, Any] = {
                "generation_time": f"{elapsed_time:.1f}秒",
            }
            if "script_segments" in locals():
                failure_dialogue_count = 0
                failure_narration_count = 0
                failure_script_segments_payload: List[Dict[str, Any]] = []
                for seg in script_segments:
                    if hasattr(seg, "type"):
                        if seg.type == "dialogue":
                            failure_dialogue_count += 1
                        elif seg.type == "narration":
                            failure_narration_count += 1
                    if is_dataclass(seg):
                        failure_script_segments_payload.append(asdict(seg))
                    elif isinstance(seg, dict):
                        failure_script_segments_payload.append(seg)
                    else:
                        failure_script_segments_payload.append(getattr(seg, "__dict__", seg))
                failure_stats["parse_stats"] = {
                    "total_segments": len(script_segments),
                    "dialogue_count": failure_dialogue_count,
                    "narration_count": failure_narration_count,
                }
                failure_stats["script_segments"] = len(script_segments)

            failure_result = {
                "success": False,
                "task_id": task_id if 'task_id' in locals() else None,
                "error": str(e),
                "audio_data": None,
                "duration": 0,
                "file_size": 0,
                "stats": failure_stats,
            }
            if "failure_script_segments_payload" in locals():
                failure_result["script_segments_payload"] = failure_script_segments_payload
            if "temp_segment_cache" in locals() and temp_segment_cache:
                failure_result["temp_segment_cache"] = temp_segment_cache
            return failure_result
    
