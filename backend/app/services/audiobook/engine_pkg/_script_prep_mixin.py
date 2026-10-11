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
from ..script_adapter_pkg._llm_review import summarize_script_review_report
from ..voice_manager_factory import create_voice_manager
from ..audio_mixer import AudioMixer
from ..task_tracker import StageType
from app.services.chapter_adaptation_assets import build_audio_adaptation_hint
from app.services.audiobook.chapter_cadence import apply_chapter_cadence
from app.services.audiobook.tts_pause import AudiobookPauseRequested
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
    SoundEffectDesigner,
    MusicComposer,
)

logger = logging.getLogger(__name__)

class ScriptPrepMixin:
    async def prepare_chapter_script(
        self,
        chapter_content: str,
        chapter_id: int,
        character_list: Optional[List[str]] = None,
        novel_genre: str = "科幻",
        novel_theme: str = "未知主题",
        enable_quality_review: bool = True,
        quality_threshold: float = 70.0,
        audiobook_project_id: Optional[int] = None,
        chapter_title: str = "",
        chapter_summary: str = "",
        summary_data: Any = None,
        character_profiles: Optional[List[Dict[str, Any]]] = None,
        pause_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """仅生成章节剧本与剧本质量评审，不执行TTS和混音。

        用于两阶段流程的第1阶段：先改编+评审，再人工审稿，最后进入TTS。
        
        Args:
            character_profiles: 🆕 完整角色档案列表（包含性别、年龄、角色定位、关系网络等）
        """
        start_time = time.time()

        task_id = self.task_tracker.create_task(
            chapter_id=chapter_id,
            novel_genre=novel_genre,
            novel_theme=novel_theme,
            metadata={
                "character_list": character_list,
                "character_profiles_count": len(character_profiles) if character_profiles else 0,
            },
        )

        logger.info(f"{'='*70}")
        logger.info(f"📝 开始生成章节剧本: Chapter {chapter_id} [TaskID: {task_id[:8]}]")
        logger.info(f"{'='*70}")

        try:
            quality_report = None

            # 阶段1：制定改编策略
            self.task_tracker.start_stage(task_id, StageType.STRATEGY)
            logger.info("🎭 [1/7] 制定改编策略...")
            
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
                target_audience="通用听众",
            )
            # 应用项目级音效/BGM 配置对策略进行微调
            self._apply_audio_fx_to_strategy(strategy)
            self.script_adapter.strategy = strategy
            self.task_tracker.complete_stage(
                task_id,
                StageType.STRATEGY,
                metrics={
                    "style": strategy.style.value,
                    "sound_density": strategy.sound_effect_density,
                },
            )
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

            # 阶段2：剧本改编
            self.task_tracker.start_stage(task_id, StageType.SCRIPT_ADAPTATION)
            logger.info("📝 [2/7] 剧本改编...")
            
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
                pause_check=pause_check,
            )

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
            transform_degradation = getattr(self.script_adapter, "last_transform_degradation", None)
            has_degraded_batches = bool(
                isinstance(transform_degradation, dict)
                and transform_degradation.get("degraded_batches")
            )
            if has_degraded_batches:
                logger.warning(
                    "⚠️ 剧本转化存在降级批次: %s/%s（已回退原文旁白，审核时请重点检查）",
                    transform_degradation.get("degraded_batches"),
                    transform_degradation.get("total_batches"),
                )
            self._last_source_text_for_script_revision = chapter_content
            self._last_llm_script_review = llm_script_review
            script_stage_metrics = {
                "segments_count": segments_count,
                "text_length": len(chapter_content),
            }
            if llm_script_review_summary:
                script_stage_metrics["llm_script_review"] = llm_script_review_summary
            if has_degraded_batches:
                script_stage_metrics["transform_degradation"] = transform_degradation

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
                    message=f'剧本改编完成：{segments_count}个片段',
                    stage_metrics={'segments_count': segments_count}
                )

            # ============ 阶段3-5：并行设计（音色+音效+音乐）============
            logger.info("🎵 [3-5/7] 并行设计：音色、音效、音乐...")

            if WEBSOCKET_AVAILABLE and audiobook_project_id:
                await ws_manager.send_audiobook_progress(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    stage='design',
                    progress=0,
                    message='正在并行设计音色、音效、音乐...'
                )

            voice_profiles, sound_effects_count, music_cues_count = await self._parallel_design(
                task_id,
                script_segments,
                chapter_content,
                preserve_user_config=True,
                chapter_id=chapter_id,
                audiobook_project_id=audiobook_project_id,
                prepare_render_assets=False,
            )

            logger.info("   ✅并行设计完成")
            logger.info(f"      - 音色: {len(voice_profiles) if voice_profiles else 0} 个角色")
            logger.info(f"      - 音效: {sound_effects_count} 个标注")
            logger.info(f"      - 音乐: {music_cues_count} 个提示")

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

            # 阶段3：剧本质量评审（可选）
            auto_revision: Dict[str, Any] = {"applied": False}
            if enable_quality_review:
                self.task_tracker.start_stage(task_id, StageType.QUALITY_REVIEW)
                logger.info("🔍 [6/7] 剧本质量评审...")
                
                # 📡 WebSocket推送：评审阶段开始
                if WEBSOCKET_AVAILABLE and audiobook_project_id:
                    await ws_manager.send_audiobook_progress(
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        stage='quality_review',
                        progress=0,
                        message='正在评审剧本质量...'
                    )

                quality_report_obj, auto_revision = self._run_quality_review_with_auto_revision(
                    script_segments,
                    novel_genre=novel_genre,
                    quality_threshold=quality_threshold,
                )

                # 序列化为dict，方便存库
                quality_report = {
                    "script_quality": quality_report_obj.script_quality,
                    "audio_balance": quality_report_obj.audio_balance,
                    "pacing": quality_report_obj.pacing,
                    "overall_grade": quality_report_obj.overall_grade,
                    "overall_score": quality_report_obj.overall_score,
                    "revision_suggestions": quality_report_obj.revision_suggestions,
                    "issues": [
                        {
                            "location": i.location,
                            "severity": i.severity,
                            "category": i.category,
                            "description": i.description,
                            "suggestion": i.suggestion,
                            "dimension": getattr(i, "dimension", "") or "",
                            "fix_type": getattr(i, "fix_type", "") or "",
                            "target_fields": list(getattr(i, "target_fields", None) or []),
                            "segment_index": getattr(i, "segment_index", -1),
                        }
                        for i in quality_report_obj.issues
                    ],
                    "auto_revision": auto_revision if auto_revision.get("applied") else None,
                    "quality_gate": auto_revision.get("quality_gate"),
                    "llm_script_review": llm_script_review,
                    "transform_degradation": transform_degradation if has_degraded_batches else None,
                    "llm_dimensions": getattr(quality_report_obj, "llm_dimensions", None) or {},
                }

                issues_preview = quality_report["issues"][:20]
                stage_metrics = {
                    "overall_score": quality_report_obj.overall_score,
                    "overall_grade": quality_report_obj.overall_grade,
                    "issues_count": len(quality_report_obj.issues),
                    "script_quality": quality_report_obj.script_quality,
                    "audio_balance": quality_report_obj.audio_balance,
                    "pacing": quality_report_obj.pacing,
                    "revision_suggestions": quality_report_obj.revision_suggestions,
                    "issues": issues_preview,
                    "quality_gate": auto_revision.get("quality_gate"),
                    "llm_dimensions": getattr(quality_report_obj, "llm_dimensions", None) or {},
                }
                if auto_revision.get("applied"):
                    stage_metrics["auto_revision"] = auto_revision
                if llm_script_review_summary:
                    stage_metrics["llm_script_review"] = llm_script_review_summary
                self.task_tracker.complete_stage(
                    task_id,
                    StageType.QUALITY_REVIEW,
                    metrics=stage_metrics,
                )
                logger.info(f"   ✅ 评审完成: {quality_report_obj.overall_grade} ({quality_report_obj.overall_score:.1f}分)")
                logger.info(f"   发现 {len(quality_report_obj.issues)} 个问题")
                
                # 📡 WebSocket推送：评审阶段完成
                if WEBSOCKET_AVAILABLE and audiobook_project_id:
                    ws_metrics = {
                        'overall_score': quality_report_obj.overall_score,
                        'overall_grade': quality_report_obj.overall_grade,
                        'issues_count': len(quality_report_obj.issues),
                        'quality_gate': auto_revision.get("quality_gate"),
                    }
                    llm_dims = getattr(quality_report_obj, "llm_dimensions", None) or {}
                    if llm_dims:
                        ws_metrics['llm_dimensions'] = llm_dims
                    await ws_manager.send_audiobook_progress(
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        stage='quality_review',
                        progress=100,
                        message=f'剧本质量评审完成：{quality_report_obj.overall_grade} ({quality_report_obj.overall_score:.1f}分)',
                        stage_metrics=ws_metrics,
                    )

                if quality_report_obj.overall_score < quality_threshold:
                    logger.warning(
                        f"⚠️ 剧本质量评分低于阈值 ({quality_report_obj.overall_score:.1f} < {quality_threshold})"
                    )
                    logger.warning(
                        f"   修订建议: {', '.join(quality_report_obj.revision_suggestions)}"
                    )
            else:
                # 跳过质量评审
                logger.info("⚠️ [6/7] 已跳过剧本质量评审（配置关闭）")
                quality_report = None
                self.task_tracker.complete_stage(
                    task_id,
                    StageType.QUALITY_REVIEW,
                    metrics={"skipped": True},
                )

            # 为脚本片段补全音色参数，便于提示词审阅
            apply_chapter_cadence(script_segments)
            self._assign_voices(script_segments)

            # 音频提示词审阅阶段（输出可编辑的提示词快照）
            self.task_tracker.start_stage(task_id, StageType.AUDIO_PROMPT_REVIEW)
            output_segments = self._build_review_segments(script_segments)
            prompt_metrics = self._build_audio_prompt_review_metrics(
                output_segments,
                llm_script_review_summary=llm_script_review_summary,
            )
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

            # 统计对话和旁白数量
            dialogue_count = 0
            narration_count = 0
            for seg in script_segments:
                seg_type = getattr(seg, "type", "")
                if seg_type == "dialogue":
                    dialogue_count += 1
                elif seg_type == "narration":
                    narration_count += 1

            elapsed_time = time.time() - start_time

            result: Dict[str, Any] = {
                "success": True,
                "task_id": task_id,
                "stats": {
                    "generation_time": f"{elapsed_time:.1f}秒",
                    "parse_stats": {
                        "total_segments": len(script_segments),
                        "dialogue_count": dialogue_count,
                        "narration_count": narration_count,
                    },
                    "characters": len(character_list or []),
                    "llm_script_review": llm_script_review_summary,
                    "transform_degradation": transform_degradation if has_degraded_batches else None,
                },
                "script_segments": output_segments,
                "quality_report": quality_report,
            }

            self.task_tracker.complete_task(task_id)
            return result

        except AudiobookPauseRequested:
            # 暂停信号需向上透传给后台任务，由其落库为 paused，不当作失败处理
            raise
        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(f"❌ 剧本生成失败: {e}")
            import traceback
            traceback.print_exc()

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

            return {
                "success": False,
                "task_id": task_id,
                "error": str(e),
                "stats": {
                    "generation_time": f"{elapsed_time:.1f}秒",
                },
            }

