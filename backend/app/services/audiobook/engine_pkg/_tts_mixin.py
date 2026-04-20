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

class TTSMixin:
    async def _synthesize_segments(
        self,
        script_segments,
        debug_save_segments: bool = False,
        debug_output_dir: Optional[str] = None
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
            debug_output_dir=debug_output_dir
        )
        
        return audio_list

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

