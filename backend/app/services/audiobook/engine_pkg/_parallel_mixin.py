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
from ..task_tracker import StageType
from ..duration_estimator import estimate_narration_duration_seconds
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

MUSIC_WORTHY_EMOTION_KEYWORDS = (
    "tense",
    "sad",
    "happy",
    "excited",
    "solemn",
    "angry",
    "fear",
    "fearful",
    "nervous",
    "mysterious",
    "suspense",
    "epic",
)


def _has_music_worthy_emotion(emotion: str) -> bool:
    normalized = str(emotion or "").lower()
    return any(key in normalized for key in MUSIC_WORTHY_EMOTION_KEYWORDS)


def _map_music_mood_from_emotion(emotion: str) -> str:
    normalized = str(emotion or "").lower()
    if any(key in normalized for key in ("tense", "angry", "fear", "fearful", "nervous", "suspense")):
        return "tense"
    if "sad" in normalized:
        return "sad"
    if "happy" in normalized or "excited" in normalized:
        return "joyful"
    if "tender" in normalized:
        return "romantic"
    if "solemn" in normalized or "epic" in normalized:
        return "epic"
    if "mysterious" in normalized:
        return "mysterious"
    return "peaceful"

class ParallelMixin:
    async def _parallel_design(
        self,
        task_id: str,
        script_segments: List[Any],
        chapter_content: str = "",
        preserve_user_config: bool = False,  # 🆕 新参数：是否保留用户配置
        chapter_id: Optional[int] = None,
        audiobook_project_id: Optional[int] = None,
        skip_stage_tracking: bool = False,
        include_voice_design: bool = True,
    ) -> tuple:
        """
        并行执行音色、音效、音乐设计
        
        Args:
            task_id: 任务ID
            script_segments: 剧本片段列表
            chapter_content: 章节原文（用于环境音与配乐生成）
            preserve_user_config: 是否保留用户配置（True=只为未配置的角色设计音色）
        
        Returns:
            (voice_profiles, sound_effects_count, music_cues_count)
        """
        audio_fx_for_generation = getattr(self, "_audio_fx_config", None) or {}

        def asset_generation_enabled(enable_key: str, density_key: str) -> bool:
            if not audio_fx_for_generation:
                return False
            enabled = audio_fx_for_generation.get(enable_key, True)
            density = str(audio_fx_for_generation.get(density_key) or "medium").lower()
            return bool(enabled) and density != "off"

        allow_sfx_asset_generation = asset_generation_enabled(
            "enable_sound_effects",
            "sound_effect_density",
        )
        allow_music_asset_generation = asset_generation_enabled(
            "enable_music",
            "music_density",
        )

        # 定义三个并行任务
        async def voice_design_task():
            """ 音色设计任务（已废弃，现统一使用VoiceManager）"""
            if not include_voice_design:
                return {}
            if not skip_stage_tracking:
                self.task_tracker.start_stage(task_id, StageType.VOICE_DESIGN)
            
            # 提取角色列表
            characters_in_script = list(set([
                seg.speaker for seg in script_segments 
                if seg.speaker != "旁白"
            ]))
            
            # 🆕 章节分析：从剧本片段中提取角色特征
            chapter_traits = {}
            known_traits = {}
            for char_name in characters_in_script:
                existing_profile = self.voice_manager.get_voice(char_name)
                if existing_profile:
                    known_traits[char_name] = {
                        "gender": existing_profile.gender,
                        "age_group": existing_profile.age_group,
                        "personality": existing_profile.personality,
                    }

            if characters_in_script and not known_traits:
                chapter_traits = self.voice_manager.analyze_chapter_characters(
                    script_segments, known_characters=known_traits
                )
                if chapter_traits:
                    logger.info("📊 章节角色分析完成: %d 个角色", len(chapter_traits))
                    for char_name, traits in chapter_traits.items():
                        logger.info("   %s: gender=%s, age=%s, personality=%s (source=%s)",
                                   char_name,
                                   traits.get("gender", "unknown"),
                                   traits.get("age_group", "unknown"),
                                   traits.get("personality", "unknown"),
                                   traits.get("source", "unknown"))
                else:
                    logger.info("📖 章节角色分析未提取到新特征")

            if characters_in_script:
                # 🔥 重构：VoiceDesigner 不再设计音色，只检查配置完整性
                if preserve_user_config:
                    # 获取已配置的角色列表
                    configured_characters = set(self.voice_manager.voice_profiles.keys())
                    # 找出未配置的角色
                    characters_to_design = [
                        char for char in characters_in_script 
                        if char not in configured_characters
                    ]
                    
                    if configured_characters:
                        logger.info(f"   🛡️ 保留用户配置: {len(configured_characters)} 个角色 {list(configured_characters)}")
                    
                    # 🔥 关键改动：为未配置的角色使用 VoiceManager.assign_voice 而不是 VoiceDesigner
                    if characters_to_design:
                        logger.info(f"   🎭 使用VoiceManager自动分配: {len(characters_to_design)} 个角色 {characters_to_design}")
                        for char_name in characters_to_design:
                            char_traits = chapter_traits.get(char_name)
                            self.voice_manager.assign_voice(char_name, character_info=char_traits)
                        
                    voice_profiles = {}  # 返回空字典，因为已由 VoiceManager 管理
                else:
                    # 不保留用户配置时，也用 VoiceManager 重新分配
                    logger.info(f"   🎭 使用VoiceManager为 {len(characters_in_script)} 个角色分配音色")
                    for char_name in characters_in_script:
                        char_traits = chapter_traits.get(char_name)
                        self.voice_manager.assign_voice(char_name, character_info=char_traits)
                    voice_profiles = {}
                
                if skip_stage_tracking:
                    return voice_profiles
                self.task_tracker.complete_stage(task_id, StageType.VOICE_DESIGN, metrics={
                    "characters_count": len(characters_in_script),
                    "preserved_count": len(configured_characters) if preserve_user_config else 0,
                    "unified_system": "VoiceManager"  # 🔥 标记：已统一到VoiceManager
                })
                
                return voice_profiles
            else:
                if skip_stage_tracking:
                    return []
                self.task_tracker.complete_stage(task_id, StageType.VOICE_DESIGN, metrics={
                    "characters_count": 0
                })
                return []
        
        async def sound_design_task():
            """音效设计任务（增强 Mureka 环境音）"""
            if not skip_stage_tracking:
                self.task_tracker.start_stage(task_id, StageType.SOUND_DESIGN)
            
            # 如果项目配置关闭了音效，直接跳过音效设计阶段
            audio_fx = getattr(self, "_audio_fx_config", None)
            if audio_fx:
                enable_sfx = audio_fx.get("enable_sound_effects", True)
                sfx_density = str(audio_fx.get("sound_effect_density") or "").lower()
                if (not enable_sfx) or sfx_density == "off":
                    logger.info("🎚 项目级配置已关闭音效设计，跳过 SoundEffectDesigner 阶段")
                    self._last_effect_timeline = None
                    if skip_stage_tracking:
                        return 0
                    self.task_tracker.complete_stage(
                        task_id,
                        StageType.SOUND_DESIGN,
                        metrics={"sound_effects_count": 0, "skipped": True}
                    )
                    return 0
            
            # 构造用于音效设计的简化片段结构
            script_dicts = []
            for seg in script_segments:
                text = getattr(seg, "text", "") or ""
                raw_effects = getattr(seg, "sound_effects", None)
                effect_requests = []
                if raw_effects:
                    for ef in raw_effects:
                        if not ef:
                            continue
                        if isinstance(ef, dict):
                            reference = (
                                ef.get("asset_id")
                                or ef.get("effect_id")
                                or ef.get("id")
                                or ef.get("name")
                            )
                        elif isinstance(ef, str):
                            reference = ef.strip()
                        else:
                            reference = (
                                getattr(ef, "asset_id", None)
                                or getattr(ef, "effect_id", None)
                                or getattr(ef, "id", None)
                                or getattr(ef, "name", None)
                            )
                        if reference:
                            effect_requests.append(ef)
                else:
                    effect_requests = getattr(seg, "sound_effects_simple", []) or []

                script_dicts.append(
                    {
                        "text": text,
                        "sound_effects": effect_requests,
                    }
                )
            
            # 调用音效设计器生成音效时间线
            try:
                effect_cues = self.sound_effect_designer.design_effects(
                    script_dicts,
                    allow_asset_generation=allow_sfx_asset_generation,
                )
                
                # 根据音效密度配置优化音效数量
                sfx_density = str(audio_fx.get("sound_effect_density") or "medium").lower() if audio_fx else "medium"
                if sfx_density == "low":
                    max_per_min = 2  # 低密度：每分钟最多2个音效
                elif sfx_density == "high":
                    max_per_min = 6  # 高密度：每分钟最多6个音效
                else:  # medium
                    max_per_min = 4   # 中密度：每分钟最多4个音效
                
                effect_cues = self.sound_effect_designer.optimize_effect_density(max_effects_per_minute=max_per_min)
                logger.info(f"🎧 根据密度配置 ({sfx_density}) 优化后：{len(effect_cues)} 个音效")

                if allow_sfx_asset_generation and hasattr(self.sound_effect_designer, "ensure_generated_assets"):
                    max_generated_effects = 2 if sfx_density == "low" else 4 if sfx_density == "medium" else 6
                    await self.sound_effect_designer.ensure_generated_assets(
                        max_generated_effects=max_generated_effects,
                    )
                
                self._last_effect_timeline = self.sound_effect_designer.export_effect_timeline()
                sound_effects_count = len(self.sound_effect_designer.effect_cues)
                effect_timeline = self._last_effect_timeline
            except Exception as e:
                logger.warning(f"⚠️ 音效设计阶段异常，将退回到简单计数逻辑: {e}")
                sound_effects_count = sum(len(getattr(seg, "sound_effects", []) or []) for seg in script_segments)
                self._last_effect_timeline = None
                effect_timeline = None
            
            metrics = {"sound_effects_count": sound_effects_count}
            if effect_timeline:
                metrics["timeline"] = effect_timeline
            if skip_stage_tracking:
                return sound_effects_count
            self.task_tracker.complete_stage(task_id, StageType.SOUND_DESIGN, metrics=metrics)
            
            return sound_effects_count
        
        async def music_composition_task():
            """音乐编曲任务（增强 AI 配乐）"""
            if not skip_stage_tracking:
                self.task_tracker.start_stage(task_id, StageType.MUSIC_COMPOSITION)
            
            # 如果项目配置关闭了配乐，直接跳过配乐设计阶段
            audio_fx = getattr(self, "_audio_fx_config", None)
            if audio_fx:
                enable_music = audio_fx.get("enable_music", True)
                music_density = str(audio_fx.get("music_density") or "").lower()
                if (not enable_music) or music_density == "off":
                    logger.info("🎚 项目级配置已关闭配乐设计，跳过 MusicComposer 阶段")
                    self._last_music_timeline = None
                    if skip_stage_tracking:
                        return 0
                    self.task_tracker.complete_stage(
                        task_id,
                        StageType.MUSIC_COMPOSITION,
                        metrics={"music_cues_count": 0, "skipped": True}
                    )
                    return 0
            
            # 提取音乐标注并设计配乐方案
            try:
                # 构造章节结构用于配乐设计（结合剧本片段的emotion和music_cue）
                total_duration = (
                    estimate_narration_duration_seconds(chapter_content, min_duration=0.0)
                    if chapter_content
                    else 600.0
                )

                scenes = []
                current_time = 0.0
                for idx, seg in enumerate(script_segments):
                    text = getattr(seg, "text", "") or ""
                    seg_duration = estimate_narration_duration_seconds(text, min_duration=0.0)

                    # 先累加，用上一段累加的 current_time 作为下一段的起点
                    start_time = current_time
                    current_time += seg_duration

                    # 只有在存在 music_cue 或明显的情绪标签时，才认为是需要配乐的场景
                    raw_music_cue = getattr(seg, "music_cue", None)
                    music_cue_data: Dict[str, Any] = {}
                    music_cue_text = ""
                    if isinstance(raw_music_cue, str):
                        music_cue_text = raw_music_cue
                    elif isinstance(raw_music_cue, dict):
                        music_cue_data = dict(raw_music_cue)
                        music_cue_text = (
                            raw_music_cue.get("style")
                            or raw_music_cue.get("name")
                            or raw_music_cue.get("cue")
                            or ""
                        )
                    elif raw_music_cue is not None:
                        music_cue_data = (
                            asdict(raw_music_cue)
                            if is_dataclass(raw_music_cue)
                            else dict(getattr(raw_music_cue, "__dict__", {}) or {})
                        )
                        music_cue_text = (
                            music_cue_data.get("style")
                            or music_cue_data.get("name")
                            or music_cue_data.get("cue")
                            or ""
                        )
                    else:
                        # 兼容简洁模式：music_cue_simple 只是一个字符串说明
                        music_cue_text = getattr(seg, "music_cue_simple", "") or ""

                    music_asset_id = str(
                        music_cue_data.get("asset_id")
                        or music_cue_data.get("music_id")
                        or music_cue_data.get("id")
                        or ""
                    ).strip()
                    if not music_cue_text and music_asset_id:
                        music_cue_text = music_asset_id

                    emotion = (getattr(seg, "emotion", "") or "").lower()

                    has_explicit_music = bool(music_cue_text)
                    has_strong_emotion = _has_music_worthy_emotion(emotion)

                    if not has_explicit_music and not has_strong_emotion:
                        continue

                    # 将剧本情绪标签映射到音乐情绪
                    mood = _map_music_mood_from_emotion(emotion)

                    # 如果 music_cue 文本里带有明显情绪关键词，也参与微调
                    lc_cue = music_cue_text.lower()
                    if any(k in lc_cue for k in ["suspense", "紧张", "心跳", "低频"]):
                        mood = "tense"
                    elif any(k in lc_cue for k in ["romantic", "浪漫"]):
                        mood = "romantic"
                    elif any(k in lc_cue for k in ["sad", "哀伤", "悲伤"]):
                        mood = "sad"

                    scene = {
                        "scene_id": f"scene_{idx}",
                        "start_time": start_time,
                        "duration": min(max(seg_duration, 20.0), 120.0),  # 单段配乐时长限制在 20-120 秒
                        "mood": mood,
                        "description": text[:80],
                        "is_climax": "tense" in mood or "epic" in mood,
                        "is_turning_point": False,
                    }
                    if music_asset_id:
                        scene["music_asset_id"] = music_asset_id
                    if music_cue_data:
                        scene["music_style"] = music_cue_text
                        cue_field_map = {
                            "volume": "music_volume",
                            "fade_in": "music_fade_in",
                            "fade_out": "music_fade_out",
                            "duration": "music_duration",
                            "start_time": "music_start_time",
                            "sync_with_dialogue": "music_sync_with_dialogue",
                            "dialogue_volume_reduction": "music_dialogue_volume_reduction",
                        }
                        for source_key, scene_key in cue_field_map.items():
                            if music_cue_data.get(source_key) is not None:
                                scene[scene_key] = music_cue_data[source_key]
                    scenes.append(scene)

                # 🆕 智能化增强：高潮点检测 + 情绪曲线分析
                audio_fx = getattr(self, "_audio_fx_config", None) or {}
                enable_smart_enhancement = audio_fx.get("auto_climax_detection", False)
                
                if enable_smart_enhancement:
                    logger.info("🤖 启用智能化增强...")
                    
                    # 1. 高潮点检测
                    climax_points = self.climax_detector.detect_climax_points(script_segments)
                    
                    # 2. 情绪曲线分析
                    emotion_flow = self.emotion_analyzer.analyze_chapter_emotion_flow(script_segments)
                    
                    # 3. 为检测到的高潮点添加配乐
                    for climax in climax_points:
                        idx = climax.segment_idx
                        if idx >= len(script_segments):
                            continue
                        
                        seg = script_segments[idx]
                        # 计算时间点（累积前面所有片段的时长）
                        climax_start_time = sum(
                            getattr(script_segments[i], 'estimated_duration', 5.0)
                            for i in range(idx)
                        )
                        
                        scenes.append({
                            "scene_id": f"climax_{idx}",
                            "start_time": climax_start_time,
                            "duration": 45.0,  # 高潮配乐持续45秒
                            "mood": getattr(seg, 'emotion', 'epic'),
                            "description": f"高潮点 - {climax.description}",
                            "is_climax": True,
                            "is_turning_point": climax.climax_type == 'turning_point',
                            "music_prompt_key": "awakening" if climax.climax_type == 'battle' else "faction_intro"
                        })
                        logger.info(
                            f"  ✅ 添加高潮配乐 #{idx}: {climax.description} "
                            f"(强度={climax.intensity:.2f})"
                        )
                    
                    # 4. 为情绪转折点添加转场音乐
                    for shift in emotion_flow.get('emotional_shifts', []):
                        idx = shift.idx
                        if idx >= len(script_segments):
                            continue
                        
                        shift_start_time = sum(
                            getattr(script_segments[i], 'estimated_duration', 5.0)
                            for i in range(idx)
                        )
                        
                        scenes.append({
                            "scene_id": f"shift_{idx}",
                            "start_time": shift_start_time,
                            "duration": 10.0,  # 转场音乐较短
                            "mood": shift.to_emotion,
                            "description": f"情绪转场 - {shift.from_emotion}→{shift.to_emotion}",
                            "is_climax": False,
                            "is_turning_point": True,
                            "music_prompt_key": "suspense" if shift.to_emotion == 'tense' else "daily"
                        })
                        logger.info(f"  ✅ 添加转场音乐 #{idx}: {shift.shift_type}")
                
                # 如果没有任何候选场景，则退回到原来的简单三场景策略
                if not scenes:
                    scenes = [
                        {
                            "scene_id": f"scene_{i}",
                            "start_time": i * 60.0,
                            "duration": 60.0,
                            "mood": "peaceful",
                            "description": getattr(seg, "text", "")[:50],
                            "is_climax": False,
                            "is_turning_point": False,
                        }
                        for i, seg in enumerate(script_segments[:3])
                    ]

                # 选取第一个场景的情绪作为整体基调，否则使用默认值
                overall_mood = scenes[0]["mood"] if scenes else "mysterious"

                chapter_structure = {
                    "total_duration": total_duration,
                    "overall_mood": overall_mood,
                    "scenes": scenes,
                    "chapter_id": chapter_id,
                    "audiobook_project_id": audiobook_project_id,
                }
                
                # 根据密度决定是否跳过开场/结尾音乐
                music_density = str(audio_fx.get("music_density") or "medium").lower() if audio_fx else "medium"
                skip_intro_outro = (music_density == "low")  # 低密度时只保留关键场景配乐
                
                music_cues = await self.music_composer.design_music(
                    chapter_structure,
                    skip_intro_outro=skip_intro_outro,
                    allow_asset_generation=allow_music_asset_generation,
                )
                
                # 根据音乐密度配置优化配乐数量
                if music_density == "low":
                    max_coverage = 0.15  # 低密度：最多覆盖15%时长
                elif music_density == "high":
                    max_coverage = 0.45  # 高密度：最多覆盖45%时长
                else:  # medium
                    max_coverage = 0.30  # 中密度：最多覆盖30%时长
                
                music_cues = self.music_composer.optimize_music_placement(max_music_coverage=max_coverage)
                logger.info(f"🎼 根据密度配置 ({music_density}) 优化后：{len(music_cues)} 个配乐提示")
                
                self._last_music_timeline = self.music_composer.export_music_timeline()
                music_cues_count = len(music_cues)
                music_timeline = self._last_music_timeline
                logger.info(f"🎼 已设计 {music_cues_count} 个配乐提示")
            except Exception as e:
                logger.warning(f"⚠️ 配乐设计异常（不影响主流程）: {e}")
                music_cues_count = sum(1 for seg in script_segments if seg.music_cue)
                self._last_music_timeline = None
                music_timeline = None
            
            metrics = {"music_cues_count": music_cues_count}
            if music_timeline:
                metrics["timeline"] = music_timeline
            if skip_stage_tracking:
                return music_cues_count
            self.task_tracker.complete_stage(task_id, StageType.MUSIC_COMPOSITION, metrics=metrics)
            
            return music_cues_count
        
        # 并行执行三个任务
        voice_profiles, sound_effects_count, music_cues_count = await asyncio.gather(
            voice_design_task(),
            sound_design_task(),
            music_composition_task()
        )
        
        return voice_profiles, sound_effects_count, music_cues_count
    
