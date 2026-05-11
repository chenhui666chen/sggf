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
from app.services.audiobook.audio_library_paths import (
    get_audio_library_dir,
    resolve_audio_library_file_path,
)

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

class MusicMixin:
    def _resolve_music_path(
        self,
        file_ref: str,
        base_dir: Path,
        *,
        style_hint: str = "",
        mood_hint: str = "",
    ) -> Optional[Path]:
        """解析配乐文件路径（支持索引回退与缓存目录搜索）。"""
        if file_ref:
            music_path = Path(file_ref)
            if not music_path.is_absolute():
                music_path = base_dir / file_ref
            if music_path.exists():
                return music_path

            candidate_name = Path(file_ref).stem
            if candidate_name:
                for candidate in (base_dir / "music_cache").rglob(f"{candidate_name}.*"):
                    return candidate

        style_hint = (style_hint or "").strip()
        mood_hint = (mood_hint or "").strip().lower()
        index_path = base_dir / "music_index.json"
        if index_path.exists():
            try:
                raw = index_path.read_text(encoding="utf-8")
                index_data = json.loads(raw)
            except Exception as exc:
                logger.warning(f"?? 读取配乐索引失败: {exc}")
                index_data = []

            if isinstance(index_data, list):
                if style_hint:
                    for entry in index_data:
                        style = str(entry.get("style") or "").strip()
                        if style and (style_hint in style or style in style_hint):
                            resolved = resolve_audio_library_file_path(
                                entry.get("file_path"),
                                base_dir,
                            )
                            if resolved:
                                return resolved
                if mood_hint:
                    for entry in index_data:
                        if str(entry.get("mood") or "").strip().lower() == mood_hint:
                            resolved = resolve_audio_library_file_path(
                                entry.get("file_path"),
                                base_dir,
                            )
                            if resolved:
                                return resolved
                for entry in index_data:
                    resolved = resolve_audio_library_file_path(
                        entry.get("file_path"),
                        base_dir,
                    )
                    if resolved:
                        return resolved

        for candidate in (base_dir / "music_cache").rglob("*.mp3"):
            return candidate
        return None
    
    def _apply_background_music(
        self,
        audio_data: bytes,
        music_timeline: Dict[str, Any],
    ) -> bytes:
        """根据配乐时间线，将BGM叠加到音频上（🆕 智能音量平衡版）
        
        Args:
            audio_data: 原始音频数据
            music_timeline: 配乐时间线，包含 timeline 列表
        
        Returns:
            叠加BGM后的音频数据
        """
        if not audio_data:
            return audio_data
        
        timeline_items = music_timeline.get("timeline") or []
        if not timeline_items:
            return audio_data
        
        mixed_audio = audio_data
        base_dir = get_audio_library_dir()
        applied_count = 0
        skipped_count = 0
        
        # 🆕 检查是否启用智能音量平衡
        audio_fx = getattr(self, "_audio_fx_config", None) or {}
        intelligent_balance = audio_fx.get("intelligent_balance", False)
        # 将默认配乐基准音量从 -30dB 再降低到 -36dB，避免喧宾夺主
        base_bgm_volume_db = audio_fx.get("base_bgm_volume", -36)
        try:
            bgm_crossfade_ms = int(audio_fx.get("bgm_crossfade_ms") or 0)
        except Exception:
            bgm_crossfade_ms = 0
        if bgm_crossfade_ms < 0:
            bgm_crossfade_ms = 0
        
        for item in timeline_items:
            file_ref = item.get("file")
            timestamp = item.get("timestamp", 0.0)
            volume = item.get("volume", 0.2)
            sync_with_dialogue = item.get("sync_with_dialogue", True)
            dialogue_volume_reduction = item.get("dialogue_volume_reduction", 0.0)
            mood = item.get("mood", "peaceful")
            music_type = item.get("type", "underscore")
            cue_duration = item.get("duration", None)
            fade_in = item.get("fade_in", 0.0)
            fade_out = item.get("fade_out", 0.0)
            
            # 🆕 智能音量平衡计算
            if intelligent_balance:
                bgm_volume_offset = self._calculate_intelligent_bgm_volume(
                    base_volume_db=base_bgm_volume_db,
                    music_type=music_type,
                    mood=mood,
                    target_volume=volume
                )
                logger.debug(f"🎚️ 智能音量: {music_type}/{mood} → {bgm_volume_offset:.1f}dB")
            else:
                # 原有逻辑：固定基准音量
                base_gain = base_bgm_volume_db
                try:
                    volume_val = float(volume)
                except (TypeError, ValueError):
                    volume_val = 0.2
                volume_val = max(0.05, min(1.0, volume_val))
                
                # 以 0.2 为基准做相对音量调整
                relative = volume_val / 0.2
                volume_adjust_db = 20 * math.log10(relative) if relative > 0 else -40
                bgm_volume_offset = base_gain + volume_adjust_db

            # 统一再降低 3dB，进一步减弱BGM存在感
            bgm_volume_offset -= 3
            
            if not file_ref:
                skipped_count += 1
                continue
            
            music_path = Path(file_ref)
            if not music_path.is_absolute():
                # 相对路径：相对于 audio_library 根目录
                music_path = base_dir / file_ref
            
            if not music_path.exists():
                resolved = self._resolve_music_path(
                    str(file_ref or ""),
                    base_dir,
                    style_hint=str(item.get("description") or ""),
                    mood_hint=str(mood or ""),
                )
                if resolved:
                    music_path = resolved
            if not music_path.exists():
                logger.warning(f"⚠️ 配乐文件不存在: {music_path}")
                skipped_count += 1
                continue
            
            try:
                with music_path.open("rb") as f:
                    bgm_bytes = f.read()
                
                logger.info(f"🎼 叠加BGM: {music_path.name} (音量: {bgm_volume_offset:.1f}dB)")
                
                # 使用 AudioMixer.add_background_music 叠加 BGM
                position_ms = max(0, int(float(timestamp or 0.0) * 1000))
                duration_ms = None
                try:
                    if cue_duration is not None:
                        duration_ms = max(0, int(float(cue_duration) * 1000))
                except (TypeError, ValueError):
                    duration_ms = None

                fade_in_ms = max(0, int(float(fade_in or 0.0) * 1000))
                fade_out_ms = max(0, int(float(fade_out or 0.0) * 1000))
                if bgm_crossfade_ms > 0:
                    fade_in_ms = max(fade_in_ms, bgm_crossfade_ms)
                    fade_out_ms = max(fade_out_ms, bgm_crossfade_ms)

                mixed_audio = self.audio_mixer.add_background_music(
                    mixed_audio,
                    bgm_bytes,
                    bgm_volume_offset=int(bgm_volume_offset),
                    position_ms=position_ms,
                    duration_ms=duration_ms,
                    fade_in_ms=fade_in_ms,
                    fade_out_ms=fade_out_ms,
                    loop_fill=True,
                    sync_with_dialogue=bool(sync_with_dialogue),
                    dialogue_volume_reduction=float(dialogue_volume_reduction or 0.0),
                )
                logger.info(f"✅ 已叠加配乐: {music_path.name}, 音量偏移={bgm_volume_offset:.1f}dB")
                applied_count += 1
            except Exception as e:
                logger.warning(f"⚠️ 叠加配乐失败 {music_path}: {e}")
                skipped_count += 1

        logger.info("🎼 配乐时间线处理完成: applied=%s skipped=%s", applied_count, skipped_count)
        return mixed_audio
    
    def _calculate_intelligent_bgm_volume(
        self,
        base_volume_db: float,
        music_type: str,
        mood: str,
        target_volume: float
    ) -> float:
        """
        🤖 智能计算BGM音量（根据场景类型、情绪、音乐类型进行动态调整）
        
        Args:
            base_volume_db: 基础音量（dB），默认-30dB
            music_type: 音乐类型 (opening/ending/underscore/theme)
            mood: 情绪 (tense/epic/peaceful/sad/joyful/mysterious/romantic)
            target_volume: 目标音量 (0.0-1.0)
        
        Returns:
            最终BGM音量偏移（dB）
        
        🎯 智能调整规则：
        1. 开场/片尾音乐：可适当提升音量 (+5dB)
        2. 高潮情绪(tense/epic)：提升音量 (+8dB)
        3. 平静情绪(peaceful/sad)：降低音量 (-5dB)
        4. 背景音乐(underscore)：保持基础音量
        5. 角色主题音乐(theme)：稍微提升 (+3dB)
        """
        # 从基础音量开始
        adjusted_volume = base_volume_db
        
        # 1. 根据音乐类型调整
        if music_type == "opening" or music_type == "ending":
            adjusted_volume += 5  # 开场/结尾可以更响亮
            logger.debug(f"  🎬 开场/结尾音乐: +5dB")
        elif music_type == "theme":
            adjusted_volume += 3  # 主题音乐稍微突出
            logger.debug(f"  🎭 主题音乐: +3dB")
        
        # 2. 根据情绪调整
        if mood in ["tense", "epic"]:
            adjusted_volume += 8  # 紧张/史诗场景，配乐加强
            logger.debug(f"  🔥 高潮情绪({mood}): +8dB")
        elif mood in ["peaceful", "sad"]:
            adjusted_volume -= 5  # 平静/悲伤场景，配乐低调
            logger.debug(f"  🌙 平静情绪({mood}): -5dB")
        elif mood in ["joyful", "romantic"]:
            adjusted_volume += 2  # 欢快/浪漫场景，稍微提升
            logger.debug(f"  ✨ 欢快情绪({mood}): +2dB")
        
        # 3. 根据目标音量做相对调整
        try:
            volume_val = float(target_volume)
        except (TypeError, ValueError):
            volume_val = 0.2
        volume_val = max(0.05, min(1.0, volume_val))
        
        # 以 0.2 为基准，计算相对调整
        relative = volume_val / 0.2
        volume_adjust_db = 20 * math.log10(relative) if relative > 0 else -40
        adjusted_volume += volume_adjust_db
        
        # 4. 限制在合理范围内 (-50dB 到 -10dB)
        adjusted_volume = max(-50, min(-10, adjusted_volume))
        
        logger.debug(
            f"  🎶 最终音量: {base_volume_db:.1f}dB → {adjusted_volume:.1f}dB "
            f"(类型={music_type}, 情绪={mood}, 目标={volume_val:.2f})"
        )
        
        return adjusted_volume
    
