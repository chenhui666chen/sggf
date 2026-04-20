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
        chapter_title: str = "",
        chapter_summary: str = "",
        summary_data: Any = None,
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
            
            self.task_tracker.complete_stage(task_id, StageType.SCRIPT_ADAPTATION, metrics={
                "segments_count": segments_count,
                "text_length": len(chapter_content)
            })
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
                
                # 转换script_segments为评审格式
                review_segments = self._build_review_segments(script_segments)

                # 为前端评审弹窗准备一份精简的片段列表（只保留前50段）
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
                
                quality_report = self.audio_quality_reviewer.review_script(
                    review_segments,
                    novel_genre=novel_genre
                )

                auto_revision = self._auto_balance_script_audio_cues(
                    script_segments,
                    self.audio_quality_reviewer.quality_standards,
                )
                if auto_revision.get("applied"):
                    review_segments = self._build_review_segments(script_segments)
                    quality_report = self.audio_quality_reviewer.review_script(
                        review_segments,
                        novel_genre=novel_genre
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
                self.task_tracker.complete_stage(task_id, StageType.QUALITY_REVIEW, metrics={
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
                })
                
                logger.info(f"   ✅ 剧本评审完成: {quality_report.overall_grade} ({quality_report.overall_score:.1f}分)")
                logger.info(f"   发现 {len(quality_report.issues)} 个问题")
                
                # 质量预警（不阻断流程，仅日志提示）
                if quality_report.overall_score < quality_threshold:
                    logger.warning(f"⚠️ 剧本质量评分低于阈值 ({quality_report.overall_score:.1f} < {quality_threshold})")
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
            
            audio_list = await self._synthesize_segments(script_segments)
            
            tts_stats = self.tts_engine.get_cost_stats()
            
            self.task_tracker.complete_stage(task_id, StageType.TTS_SYNTHESIS, metrics={
                "tts_stats": tts_stats
            })
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
            
            # 基于真实音频时长对齐音效/配乐时间线
            self._realign_timelines_with_audio(script_segments, audio_list)

            # ============ 阶段9：音频混合 ============
            self.task_tracker.start_stage(task_id, StageType.AUDIO_MIXING)
            logger.info("🎧 [9/10] 音频混合中...")
            
            final_audio = self.audio_mixer.mix_chapter(audio_list)
            
            # 应用音效时间线（如有）
            if self._last_effect_timeline and self._last_effect_timeline.get("timeline"):
                logger.info("🎛 应用音效时间线叠加音效...")
                final_audio = self._apply_sound_effects(final_audio, self._last_effect_timeline)
            
            # 应用配乐时间线（如有）
            if self._last_music_timeline and self._last_music_timeline.get("timeline"):
                logger.info("🎼 应用配乐时间线叠加BGM...")
                final_audio = self._apply_background_music(final_audio, self._last_music_timeline)
            
            # 允许空音频（用于MVP测试）
            if not final_audio:
                logger.warning("⚠️ 音频为空，生成占位数据")
                final_audio = b""  # 空字节
                
            audio_info = self.audio_mixer.get_audio_info(final_audio)
            
            self.task_tracker.complete_stage(task_id, StageType.AUDIO_MIXING, metrics={
                "audio_info": audio_info
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
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'wb') as f:
                    f.write(final_audio)
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

            quality_report_payload = asdict(quality_report) if quality_report else None
            if quality_report_payload and auto_revision.get("applied"):
                quality_report_payload["auto_revision"] = auto_revision

            result = {
                "success": True,
                "task_id": task_id,  # 返回任务ID
                "audio_data": final_audio,
                "duration": audio_info.get("duration_seconds", 0),
                "file_size": len(final_audio),
                "script_segments_payload": script_segments_payload,
                "quality_report_detail": quality_report_payload,
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
                    } if quality_report else None,
                    "final_audio_review": final_audio_review,
                }
            }
            
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
            
            return {
                "success": False,
                "task_id": task_id if 'task_id' in locals() else None,
                "error": str(e),
                "audio_data": None,
                "duration": 0,
                "file_size": 0,
                "stats": {
                    "generation_time": f"{elapsed_time:.1f}秒"
                }
            }
    
