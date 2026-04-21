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

class AudiobookEngineBase:
    """有声书生成引擎 - 专业多Agent协作模式"""

    def __init__(
        self,
        enable_cache: bool = True,
        max_concurrent: int = 1,  # 降低并发，避免阿里云限流（从5改为1）
        llm_client=None,  # LLM客户端（用于专业Agent + 智能音色推断）
        tts_model: str = "qwen3-tts-instruct-flash",  # TTS 模型（qwen3-tts-instruct-flash / cosyvoice-v3-plus）
        progress_handler: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        # 检查LLM客户端
        if llm_client is None:
            raise ValueError("有声书引擎必须提供llm_client参数，用于剧本改编和质量评审")
        
        # 初始化任务追踪和消息总线
        self.task_tracker = TaskTracker()
        self._progress_handler: Optional[Callable[[Dict[str, Any]], None]] = progress_handler
        self.task_tracker.add_observer(self._handle_task_progress)
        self.message_bus = MessageBus()
        
        # 初始化专业Agent
        logger.info("🎬 启用专业LLM驱动的多Agent协作模式")
        self.audio_director = AudioDirector(llm_client=llm_client)
        self.script_adapter = AudiobookScriptAgent(llm_client=llm_client, tts_model=tts_model)
        self.voice_designer = VoiceDesigner()
        self.sound_effect_designer = SoundEffectDesigner(llm_client=llm_client)
        self.music_composer = MusicComposer()
        self.audio_quality_reviewer = AudioQualityReviewer(llm_client=llm_client)
        
        # 初始化基础组件
        self.tts_model = tts_model
        # 🆕 VoiceManager自动启用智能推断：
        # - 用户已配置的角色 → 使用用户配置
        # - 用户未配置的角色 → LLM智能推断 (如果有llm_client)
        # - LLM推断失败 → 增强版规则推断
        self.voice_manager = create_voice_manager(tts_model=tts_model, llm_client=llm_client)
        self.tts_engine = create_tts_engine(
            enable_cache=enable_cache,
            max_concurrent=max_concurrent,
            model=tts_model  # 支持 qwen3-tts-instruct-flash / cosyvoice-v3-plus
        )
        self.audio_mixer = AudioMixer()
        # 存储最近一次音效时间线（用于混音）
        self._last_effect_timeline: Optional[Dict[str, Any]] = None
        # 存储最近一次配乐时间线（用于混音）
        self._last_music_timeline: Optional[Dict[str, Any]] = None
        # 项目级音效/BGM 配置（来自 Project.audio_config.audio_fx）
        self._audio_fx_config: Optional[Dict[str, Any]] = None
        
        # 🆕 智能化模块
        from .intelligence import ClimaxDetector, EmotionCurveAnalyzer
        self.climax_detector = ClimaxDetector()
        self.emotion_analyzer = EmotionCurveAnalyzer()
        
        self._use_tts_dispatch = TTS_DISPATCH_AVAILABLE
        if self._use_tts_dispatch:
            logger.info("🚀 已启用 TTS 智能调度系统（4 个已注册模型）")
        else:
            logger.info("📝 TTS 智能调度系统不可用，使用传统 TTS 引擎")
        
        logger.info("🎶 有声书生成引擎初始化完成")
    
    def set_progress_handler(self, handler: Optional[Callable[[Dict[str, Any]], None]]) -> None:
        """设置外部进度回调（用于持久化阶段状态）"""
        self._progress_handler = handler

    def _handle_task_progress(self, snapshot: Dict[str, Any]) -> None:
        if not self._progress_handler:
            return
        try:
            self._progress_handler(snapshot)
        except Exception as exc:  # pragma: no cover - 避免进度回调影响主流程
            logger.warning("⚠️ 分发任务进度失败: %s", exc)
    
    def apply_audio_fx_config(self, audio_fx: Dict[str, Any]) -> None:
        """应用项目级音效/BGM 配置（来自 Project.audio_config['audio_fx']）。"""
        try:
            self._audio_fx_config = audio_fx or {}
            theme = str(self._audio_fx_config.get("bgm_theme") or "").strip() or None
            style = str(self._audio_fx_config.get("bgm_style") or "").strip() or None
            if hasattr(self.music_composer, "apply_project_style"):
                self.music_composer.apply_project_style(theme=theme, style=style)
            logger.info(f"🎚 已应用项目级音效/BGM 配置: {self._audio_fx_config}")
        except Exception as e:
            logger.warning(f"⚠️ 设置音效/BGM 配置失败: {e}")
    
    def _apply_audio_fx_to_strategy(self, strategy) -> None:
        """根据项目级音效/BGM 配置调整导演策略中的 sound_effect_density / music_density。"""
        cfg = getattr(self, "_audio_fx_config", None)
        if not cfg:
            return
        try:
            enable_sfx = cfg.get("enable_sound_effects", True)
            enable_music = cfg.get("enable_music", True)
            sfx_density = str(cfg.get("sound_effect_density") or "").lower()
            music_density = str(cfg.get("music_density") or "").lower()
            allowed = {"low", "medium", "high", "off"}
            if not enable_sfx:
                strategy.sound_effect_density = "off"
            elif sfx_density in allowed:
                strategy.sound_effect_density = sfx_density
            if not enable_music:
                strategy.music_density = "off"
            elif music_density in allowed:
                strategy.music_density = music_density
        except Exception as e:
            logger.warning(f"⚠️ 应用项目级音效/BGM 策略失败: {e}")

    def _build_review_segments(self, script_segments: List[ScriptSegment]) -> List[Dict[str, Any]]:
        """构造评审所需的片段结构。"""
        return [
            {
                "type": seg.type,
                "text": seg.text,
                "speaker": seg.speaker,
                "emotion": seg.emotion,
                "performance_notes": seg.performance_notes if hasattr(seg, "performance_notes") else "",
                "pause_before": getattr(seg, "pause_before", 0.0),
                "pause_after": getattr(seg, "pause_after", 0.0),
                "voice_params": seg.voice_params if hasattr(seg, "voice_params") else {},
                "instruct_emotion": getattr(seg, "instruct_emotion", ""),
                "instruct_scene": getattr(seg, "instruct_scene", ""),
                "instruct_role": getattr(seg, "instruct_role", ""),
                "instruct_identity": getattr(seg, "instruct_identity", ""),
                "sound_effects": seg.sound_effects if seg.sound_effects is not None else [],
                "music_cue": seg.music_cue if hasattr(seg, "music_cue") and seg.music_cue is not None else "",
                "sound_effects_simple": getattr(seg, "sound_effects_simple", []) or [],
                "music_cue_simple": getattr(seg, "music_cue_simple", "") or "",
                "original_text": getattr(seg, "original_text", ""),
                "adaptation_reason": getattr(seg, "adaptation_reason", ""),
            }
            for seg in script_segments
        ]

    @staticmethod
    def _select_evenly_indices(total: int, keep: int) -> List[int]:
        if keep <= 0:
            return []
        if keep >= total:
            return list(range(total))
        if keep == 1:
            return [0]

        step = (total - 1) / (keep - 1)
        selected = [int(round(i * step)) for i in range(keep)]
        unique = []
        used = set()
        for idx in selected:
            if idx in used:
                continue
            used.add(idx)
            unique.append(idx)
        if len(unique) < keep:
            for idx in range(total):
                if idx in used:
                    continue
                unique.append(idx)
                used.add(idx)
                if len(unique) == keep:
                    break
        unique.sort()
        return unique

    def _auto_balance_script_audio_cues(
        self,
        script_segments: List[ScriptSegment],
        standards: Dict[str, Any],
    ) -> Dict[str, Any]:
        """根据评审标准自动收敛音效/配乐密度。"""
        if not script_segments:
            return {"applied": False}

        total_text_length = sum(len(getattr(seg, "text", "") or "") for seg in script_segments)
        if total_text_length <= 0:
            return {"applied": False}

        estimated_minutes = total_text_length / 10 / 60
        audio_fx = getattr(self, "_audio_fx_config", None) or {}
        sfx_density = str(audio_fx.get("sound_effect_density") or "").lower()
        music_density = str(audio_fx.get("music_density") or "").lower()

        min_sfx_per_min = standards.get("min_sound_effects_per_minute", 2)
        max_sfx_per_min = standards.get("max_sound_effects_per_minute", 6)
        hard_max_sfx_per_min = standards.get("hard_max_sound_effects_per_minute", max_sfx_per_min)

        target_sfx_per_min = max_sfx_per_min
        if sfx_density == "off":
            target_sfx_per_min = 0
        elif sfx_density == "low":
            target_sfx_per_min = min_sfx_per_min
        elif sfx_density == "high":
            target_sfx_per_min = hard_max_sfx_per_min

        target_music_min = standards.get("music_coverage_target_min", 0.15)
        target_music_max = standards.get("music_coverage_target_max", 0.40)
        max_music_coverage = standards.get("max_music_coverage", 0.60)

        target_music_coverage = target_music_max
        if music_density == "off":
            target_music_coverage = 0.0
        elif music_density == "low":
            target_music_coverage = target_music_min
        elif music_density == "high":
            target_music_coverage = max_music_coverage

        max_effects = int(math.floor(target_sfx_per_min * estimated_minutes))
        if target_sfx_per_min > 0 and max_effects == 0:
            max_effects = 1

        max_music_segments = int(math.floor(target_music_coverage * len(script_segments)))
        if target_music_coverage > 0 and max_music_segments == 0:
            max_music_segments = 1

        effect_entries: List[tuple[int, int]] = []
        for seg_idx, seg in enumerate(script_segments):
            effects = seg.sound_effects or []
            for effect_idx, _ in enumerate(effects):
                effect_entries.append((seg_idx, effect_idx))

        total_effects = len(effect_entries)
        total_music_segments = sum(1 for seg in script_segments if seg.music_cue)
        summary = {
            "applied": False,
            "estimated_minutes": round(estimated_minutes, 2),
            "sound_effects_before": total_effects,
            "sound_effects_after": total_effects,
            "music_cues_before": total_music_segments,
            "music_cues_after": total_music_segments,
            "targets": {
                "sound_effects_per_minute": target_sfx_per_min,
                "music_coverage": target_music_coverage,
            },
        }

        if total_effects > max_effects:
            keep_indices = set(self._select_evenly_indices(total_effects, max_effects))
            new_effects_by_segment: List[List[Any]] = [[] for _ in script_segments]
            for flat_idx, (seg_idx, effect_idx) in enumerate(effect_entries):
                if flat_idx in keep_indices:
                    new_effects_by_segment[seg_idx].append(script_segments[seg_idx].sound_effects[effect_idx])
            for seg_idx, seg in enumerate(script_segments):
                seg.sound_effects = new_effects_by_segment[seg_idx]
            summary["sound_effects_after"] = max_effects
            summary["applied"] = True

        if total_music_segments > max_music_segments:
            music_indices = [idx for idx, seg in enumerate(script_segments) if seg.music_cue]
            keep_music = set(self._select_evenly_indices(len(music_indices), max_music_segments))
            for keep_idx, seg_idx in enumerate(music_indices):
                if keep_idx in keep_music:
                    continue
                script_segments[seg_idx].music_cue = None
            summary["music_cues_after"] = max_music_segments
            summary["applied"] = True

        if summary["applied"]:
            for seg in script_segments:
                effects = seg.sound_effects or []
                names = []
                for effect in effects:
                    if isinstance(effect, dict):
                        name = effect.get("name") or effect.get("id") or effect.get("effect_id") or ""
                    else:
                        name = getattr(effect, "name", "") or str(effect)
                    if name:
                        names.append(name)
                seg.sound_effects_simple = names

                if seg.music_cue:
                    if isinstance(seg.music_cue, dict):
                        seg.music_cue_simple = seg.music_cue.get("style") or seg.music_cue.get("name") or ""
                    else:
                        seg.music_cue_simple = getattr(seg.music_cue, "style", "") or str(seg.music_cue)
                else:
                    seg.music_cue_simple = ""

        return summary
    
