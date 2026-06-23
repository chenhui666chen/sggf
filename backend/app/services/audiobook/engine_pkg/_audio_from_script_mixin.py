from __future__ import annotations

import logging
import time
from typing import List, Dict, Any, Optional, Callable

from ..script_adapter import ScriptSegment
from ..task_tracker import StageType
from ..script_adapter_pkg._segment_validation import build_script_segment
from app.services.audiobook.render_plan import render_chunks_to_timing_segments_payload
from app.services.audiobook.temp_segment_store import save_segment_audio_batch, save_segment_audio_map
from app.services.audiobook.atomic_files import write_bytes_atomic

logger = logging.getLogger(__name__)


def _estimate_editor_segment_unit(segment: ScriptSegment) -> float:
    text_length = len((getattr(segment, "text", "") or "").strip())
    if text_length <= 0:
        return 72.0
    return float(round(max(64.0, min(220.0, text_length * 1.8 + 56.0))))


class AudioFromScriptMixin:
    async def generate_chapter_audio_from_script(
        self,
        script_segments_data: List[Dict[str, Any]],
        chapter_id: int,
        character_list: Optional[List[str]] = None,
        output_path: Optional[str] = None,
        novel_genre: str = "科幻",
        novel_theme: str = "未知主题",
        enable_quality_review: bool = True,
        quality_threshold: float = 70.0,
        audiobook_project_id: Optional[int] = None,
        output_format: str = "mp3",
        resume_checkpoint: Optional[Dict[str, Any]] = None,
        timeline_edits: Optional[Dict[str, Dict[str, float]]] = None,
        tts_progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """使用已经生成/人工编辑后的剧本片段生成章节音频。

        用于两阶段流程的第2阶段：从 ChapterAudio.script_json 直接进入 TTS + 混音。
        """
        start_time = time.time()

        # 创建任务追踪（标记来源为 existing_script）
        task_id = self.task_tracker.create_task(
            chapter_id=chapter_id,
            novel_genre=novel_genre,
            novel_theme=novel_theme,
            metadata={"character_list": character_list, "source": "script_json"},
        )

        logger.info(f"{'='*70}")
        logger.info(f"🎬 从剧本片段生成章节有声书: Chapter {chapter_id} [TaskID: {task_id[:8]}]")
        logger.info(f"{'='*70}")

        try:
            final_audio_review = None
            quality_report = None
            auto_revision: Dict[str, Any] = {"applied": False}

            # ============ 阶段1：制定改编策略（用于后续设计阶段的风格参考） ============
            self.task_tracker.start_stage(task_id, StageType.STRATEGY)
            strategy = self.audio_director.formulate_strategy(
                novel_genre=novel_genre,
                novel_theme=novel_theme,
                target_audience="通用听众",
            )
            # 应用项目级音效/BGM 配置对策略进行微调
            self._apply_audio_fx_to_strategy(strategy)
            # 虽然不再改编剧本，但仍将策略传入，便于音效/配乐设计阶段参考
            self.script_adapter.strategy = strategy
            self.task_tracker.complete_stage(
                task_id,
                StageType.STRATEGY,
                metrics={
                    "style": strategy.style.value,
                    "sound_density": strategy.sound_effect_density,
                },
            )

            # ============ 阶段2：剧本改编（已完成，这里直接使用传入剧本） ============
            self.task_tracker.start_stage(task_id, StageType.SCRIPT_ADAPTATION)

            # 将dict列表转换为 ScriptSegment 对象列表
            script_segments: List[ScriptSegment] = []
            for index, seg_dict in enumerate(script_segments_data):
                validated_segment = build_script_segment(seg_dict, index=index)
                if validated_segment is not None:
                    script_segments.append(validated_segment)

            if not script_segments:
                raise ValueError("script_json does not contain valid script segments")

            segments_count = len(script_segments)
            self.task_tracker.complete_stage(
                task_id,
                StageType.SCRIPT_ADAPTATION,
                metrics={
                    "segments_count": segments_count,
                    "source": "existing_script",
                },
            )

            # ============ 阶段3-5：并行设计（音色+音效+音乐） ============
            logger.info("🎵 [3-5/8] 并行设计：音色+音效+音乐...")

            # 使用剧本文本粗略拼接作为环境描述
            chapter_text_for_design = "".join([seg.text for seg in script_segments])
            self._last_source_text_for_script_revision = chapter_text_for_design
            self._last_llm_script_review = None

            voice_profiles, sound_effects_count, music_cues_count = await self._parallel_design(
                task_id,
                script_segments,
                chapter_text_for_design,
                chapter_id=chapter_id,
                audiobook_project_id=audiobook_project_id,
            )

            # ============ 阶段6：剧本质量评审闸门（TTS 前） ============
            if enable_quality_review:
                self.task_tracker.start_stage(task_id, StageType.QUALITY_REVIEW)
                quality_report, auto_revision = self._run_quality_review_with_auto_revision(
                    script_segments,
                    novel_genre=novel_genre,
                    quality_threshold=quality_threshold,
                )
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
                    "issues": issues_preview,
                    "auto_revision": auto_revision if auto_revision.get("applied") else None,
                    "quality_gate": auto_revision.get("quality_gate"),
                }
                self.task_tracker.complete_stage(
                    task_id,
                    StageType.QUALITY_REVIEW,
                    metrics=quality_stage_metrics,
                )

                if auto_revision.get("applied"):
                    try:
                        _, sound_effects_count, music_cues_count = await self._parallel_design(
                            task_id,
                            script_segments,
                            "".join([seg.text for seg in script_segments]),
                            chapter_id=chapter_id,
                            audiobook_project_id=audiobook_project_id,
                            skip_stage_tracking=True,
                            include_voice_design=False,
                        )
                    except Exception as exc:
                        logger.warning("Auto revision refresh failed: %s", exc)

                quality_gate = auto_revision.get("quality_gate") or {}
                if not quality_gate.get("passed", True):
                    gate_reason = (
                        f"script_quality_gate_failed:"
                        f"{quality_report.overall_score:.1f}<"
                        f"{float(quality_gate.get('threshold') or quality_threshold):.1f}"
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
                        ),
                        "stats": {
                            "generation_time": f"{elapsed_time:.1f}秒",
                            "mode": "script_only_pipeline",
                            "script_segments": len(script_segments),
                            "quality_report": {
                                "overall_grade": quality_report.overall_grade,
                                "overall_score": quality_report.overall_score,
                                "issues_count": len(quality_report.issues),
                                "revision_suggestions": quality_report.revision_suggestions,
                                "auto_revision": auto_revision if auto_revision.get("applied") else None,
                                "quality_gate": quality_gate,
                            },
                        },
                    }
            else:
                self.task_tracker.complete_stage(
                    task_id,
                    StageType.QUALITY_REVIEW,
                    metrics={"skipped": True},
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
            self.task_tracker.complete_stage(task_id, StageType.AUDIO_PROMPT_REVIEW, metrics=prompt_metrics)

            # ============ 阶段8：TTS合成 ============
            self.task_tracker.start_stage(task_id, StageType.TTS_SYNTHESIS)
            logger.info("🎙️ [8/10] TTS合成中(基于已审稿剧本)...")
            
            # 🔧 调试：从环境变量读取调试开关
            import os
            debug_save_segments = os.getenv("TTS_DEBUG_SAVE_SEGMENTS", "false").lower() == "true"
            
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
                debug_save_segments=debug_save_segments,
                debug_output_dir=f"backend/data/tts_debug/chapter_{chapter_id}",
                progress_callback=handle_tts_progress,
            )
            audio_list = synthesis_result["audio_list"]
            reused_segment_indices = synthesis_result.get("reused_indices") or []
            if reused_segment_indices:
                logger.info(
                    "♻️ 剧本音频阶段断点复用命中: chapter_id=%s reused=%s synthesized=%s source=%s",
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

            self.task_tracker.complete_stage(
                task_id,
                StageType.TTS_SYNTHESIS,
                metrics={
                    "tts_stats": tts_stats,
                    "temp_segment_count": temp_segment_cache.get("segment_count", 0)
                    if temp_segment_cache
                    else 0,
                    "reused_segment_count": len(reused_segment_indices),
                    "synthesized_segment_count": synthesis_result.get("synthesized_count", len(script_segments)),
                    "resume_source": synthesis_result.get("resume_source"),
                    "render_chunk_count": synthesis_result.get("render_chunk_count"),
                },
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
                actual_durations = self._audio_durations_for_segments(render_chunks, audio_list)
                source_actual_durations = [0.0 for _ in script_segments]
                for chunk_index, chunk in enumerate(render_chunks):
                    source_indices = getattr(chunk, "source_segment_indices", None) or []
                    if not source_indices:
                        continue
                    try:
                        source_index = int(source_indices[0])
                    except Exception:
                        continue
                    if source_index < 0 or source_index >= len(source_actual_durations):
                        continue
                    if chunk_index < len(actual_durations):
                        source_actual_durations[source_index] += max(0.0, float(actual_durations[chunk_index] or 0.0))
                actual_durations_for_editor = source_actual_durations
            else:
                self._realign_timelines_with_audio(script_segments, audio_list)
                actual_durations_for_editor = self._audio_durations_for_segments(script_segments, audio_list)

            apply_editor_timeline_edits = getattr(self, "_apply_editor_timeline_edits", None)
            if callable(apply_editor_timeline_edits) and timeline_edits:
                apply_editor_timeline_edits(
                    timeline_edits,
                    segment_units=[_estimate_editor_segment_unit(segment) for segment in script_segments],
                    actual_durations=actual_durations_for_editor,
                )

            # ============ 阶段8：音频混合 ============
            self.task_tracker.start_stage(task_id, StageType.AUDIO_MIXING)
            logger.info("🎧 [8/9] 音频混合中...")

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

            self.task_tracker.complete_stage(
                task_id,
                StageType.AUDIO_MIXING,
                metrics={
                    "audio_info": audio_info,
                    "segment_timing_count": len(segment_timings),
                },
            )

            # ============ 最终音频评审（可选） ============
            if enable_quality_review:
                self.task_tracker.start_stage(task_id, StageType.FINAL_AUDIO_REVIEW)

                final_audio_review = self._final_audio_review(
                    audio_info=audio_info,
                    file_size=len(final_audio),
                    script_quality_report=quality_report,
                    audio_data=final_audio,
                )

                self.task_tracker.complete_stage(
                    task_id,
                    StageType.FINAL_AUDIO_REVIEW,
                    metrics=final_audio_review,
                )
            else:
                final_audio_review = {"skipped": True}
                self.task_tracker.complete_stage(
                    task_id,
                    StageType.FINAL_AUDIO_REVIEW,
                    metrics=final_audio_review,
                )

            # ============ 保存文件（可选） ============
            if output_path:
                write_bytes_atomic(output_path, final_audio)

            # ============ 统计结果 ============
            elapsed_time = time.time() - start_time

            # 标记任务完成
            self.task_tracker.complete_task(task_id)

            # 统计对话和旁白数量（兼容parse_stats）
            dialogue_count = 0
            narration_count = 0
            for seg in script_segments:
                seg_type = getattr(seg, "type", "")
                if seg_type == "dialogue":
                    dialogue_count += 1
                elif seg_type == "narration":
                    narration_count += 1

            result: Dict[str, Any] = {
                "success": True,
                "task_id": task_id,
                "audio_data": final_audio,
                "duration": audio_info.get("duration_seconds", 0),
                "file_size": len(final_audio),
                "segment_timings": segment_timings,
                "timing_segments_payload": timing_segments_payload,
                "temp_segment_cache": temp_segment_cache,
                "stats": {
                    "generation_time": f"{elapsed_time:.1f}秒",
                    "mode": "script_only_pipeline",
                    "parse_stats": {
                        "total_segments": len(script_segments),
                        "dialogue_count": dialogue_count,
                        "narration_count": narration_count,
                    },
                    "script_segments": len(script_segments),
                    "sound_effects": sound_effects_count if "sound_effects_count" in locals() else 0,
                    "music_cues": music_cues_count if "music_cues_count" in locals() else 0,
                    "tts_stats": tts_stats,
                    "audio_info": audio_info,
                    "quality_report": {
                        "overall_grade": quality_report.overall_grade,
                        "overall_score": quality_report.overall_score,
                        "issues_count": len(quality_report.issues),
                        "revision_suggestions": quality_report.revision_suggestions,
                        "auto_revision": auto_revision if auto_revision.get("applied") else None,
                        "quality_gate": auto_revision.get("quality_gate"),
                    } if quality_report else None,
                    "quality_report_detail": (
                        self._quality_report_to_payload(
                            quality_report,
                            auto_revision=auto_revision,
                        )
                        if hasattr(self, "_quality_report_to_payload")
                        else None
                    ),
                    "final_audio_review": final_audio_review,
                },
            }
            if self._last_effect_timeline and self._last_effect_timeline.get("timeline"):
                result["effect_timeline"] = self._last_effect_timeline

            logger.info(f"{'='*70}")
            if len(final_audio) > 0:
                logger.info("✅ 从剧本生成章节音频成功!")
            else:
                logger.info("⚠️ 章节生成完成（模拟模式，无真实音频）")
                logger.info("   提示: 请配置 DASHSCOPE_API_KEY 环境变量以生成真实音频")
            logger.info(f"   - 时长: {audio_info.get('duration_seconds', 0):.1f}秒")
            logger.info(f"   - 大小: {len(final_audio)/1024:.1f}KB")
            logger.info(f"   - 耗时: {elapsed_time:.1f}秒")
            logger.info(f"   - 成本: {tts_stats.get('estimated_cost', '¥0.00')}")
            logger.info(f"{'='*70}\n")

            return result

        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(f"❌ 从剧本生成章节音频失败: {e}")
            import traceback
            traceback.print_exc()

            # 标记任务失败（如果task_id已创建）
            if "task_id" in locals():
                task_status = self.task_tracker.get_task_status(task_id)
                if task_status:
                    for stage_name, stage_info in task_status["stages"].items():
                        if stage_info["status"] == "running":
                            self.task_tracker.fail_stage(
                                task_id,
                                StageType(stage_name),
                                str(e),
                            )
                            break

            failure_stats: Dict[str, Any] = {
                "generation_time": f"{elapsed_time:.1f}秒",
            }
            if "script_segments" in locals():
                failure_dialogue_count = 0
                failure_narration_count = 0
                for seg in script_segments:
                    seg_type = getattr(seg, "type", "")
                    if seg_type == "dialogue":
                        failure_dialogue_count += 1
                    elif seg_type == "narration":
                        failure_narration_count += 1
                failure_stats["parse_stats"] = {
                    "total_segments": len(script_segments),
                    "dialogue_count": failure_dialogue_count,
                    "narration_count": failure_narration_count,
                }
                failure_stats["script_segments"] = len(script_segments)

            failure_result = {
                "success": False,
                "task_id": task_id if "task_id" in locals() else None,
                "error": str(e),
                "audio_data": None,
                "duration": 0,
                "file_size": 0,
                "stats": failure_stats,
            }
            if "temp_segment_cache" in locals() and temp_segment_cache:
                failure_result["temp_segment_cache"] = temp_segment_cache
            return failure_result

