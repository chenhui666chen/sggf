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
        audiobook_project_id: Optional[int] = None,
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
            for seg_dict in script_segments_data:
                seg = ScriptSegment(
                    type=seg_dict.get("type") or "narration",
                    text=seg_dict.get("text") or "",
                    speaker=seg_dict.get("speaker") or "旁白",
                    emotion=seg_dict.get("emotion") or "neutral",
                    performance_notes=seg_dict.get("performance_notes", ""),
                    pause_before=float(seg_dict.get("pause_before") or 0.0),
                    pause_after=float(seg_dict.get("pause_after") or 0.0),
                    voice_params=seg_dict.get("voice_params"),
                    instruct_emotion=seg_dict.get("instruct_emotion", ""),
                    instruct_scene=seg_dict.get("instruct_scene", ""),
                    instruct_role=seg_dict.get("instruct_role", ""),
                    instruct_identity=seg_dict.get("instruct_identity", ""),
                    sound_effects=seg_dict.get("sound_effects") or [],
                    music_cue=seg_dict.get("music_cue"),
                    sound_effects_simple=seg_dict.get("sound_effects_simple", []),
                    music_cue_simple=seg_dict.get("music_cue_simple", ""),
                    original_text=seg_dict.get("original_text", ""),
                    adaptation_reason=seg_dict.get("adaptation_reason", ""),
                )
                script_segments.append(seg)

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

            voice_profiles, sound_effects_count, music_cues_count = await self._parallel_design(
                task_id,
                script_segments,
                chapter_text_for_design,
                chapter_id=chapter_id,
                audiobook_project_id=audiobook_project_id,
            )

            # ============ 阶段6：音频提示词审阅 ============
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

            # ============ 阶段7：TTS合成 ============
            self.task_tracker.start_stage(task_id, StageType.TTS_SYNTHESIS)
            logger.info("🎙️ [7/9] TTS合成中(基于已审稿剧本)...")
            
            # 🔧 调试：从环境变量读取调试开关
            import os
            debug_save_segments = os.getenv("TTS_DEBUG_SAVE_SEGMENTS", "false").lower() == "true"
            
            audio_list = await self._synthesize_segments(
                script_segments,
                debug_save_segments=debug_save_segments,
                debug_output_dir=f"backend/data/tts_debug/chapter_{chapter_id}"
            )

            tts_stats = self.tts_engine.get_cost_stats()

            self.task_tracker.complete_stage(
                task_id,
                StageType.TTS_SYNTHESIS,
                metrics={"tts_stats": tts_stats},
            )

            # 基于真实音频时长对齐音效/配乐时间线
            self._realign_timelines_with_audio(script_segments, audio_list)

            # ============ 阶段8：音频混合 ============
            self.task_tracker.start_stage(task_id, StageType.AUDIO_MIXING)
            logger.info("🎧 [8/9] 音频混合中...")

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

            self.task_tracker.complete_stage(
                task_id,
                StageType.AUDIO_MIXING,
                metrics={"audio_info": audio_info},
            )

            # ============ 最终音频评审（可选） ============
            if enable_quality_review:
                self.task_tracker.start_stage(task_id, StageType.FINAL_AUDIO_REVIEW)

                final_audio_review = self._final_audio_review(
                    audio_info=audio_info,
                    file_size=len(final_audio),
                    script_quality_report=None,
                )

                self.task_tracker.complete_stage(
                    task_id,
                    StageType.FINAL_AUDIO_REVIEW,
                    metrics=final_audio_review,
                )
            else:
                self.task_tracker.complete_stage(
                    task_id,
                    StageType.FINAL_AUDIO_REVIEW,
                    metrics={"skipped": True},
                )

            # ============ 保存文件（可选） ============
            if output_path:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(final_audio)

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
                    "final_audio_review": final_audio_review,
                },
            }

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

            return {
                "success": False,
                "task_id": task_id if "task_id" in locals() else None,
                "error": str(e),
                "audio_data": None,
                "duration": 0,
                "file_size": 0,
                "stats": {
                    "generation_time": f"{elapsed_time:.1f}秒",
                },
            }

