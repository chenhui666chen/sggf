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

class ReviewMixin:
    def _final_audio_review(
        self,
        audio_info: Dict[str, Any],
        file_size: int,
        script_quality_report: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """对最终混合后的音频做一次轻量评审。

        说明：
        - 主要基于音频时长和基础信息做兜底检查
        - 不做真实波形分析，后续可以接入语音模型进一步增强
        """
        duration = float(audio_info.get("duration_seconds", 0.0) or 0.0)
        bitrate = audio_info.get("bitrate", None)
        sample_rate = audio_info.get("sample_rate", None)

        standards = getattr(self.audio_quality_reviewer, "quality_standards", {})
        max_duration = float(standards.get("max_episode_duration", 0) or 0)
        min_duration = float(standards.get("min_episode_duration", 0) or 0)

        warnings: List[str] = []

        if max_duration and duration > max_duration:
            warnings.append(f"音频时长偏长（约 {duration/60:.1f} 分钟）")
        if min_duration and duration and duration < min_duration * 0.5:
            warnings.append(f"音频时长偏短（约 {duration/60:.1f} 分钟）")

        summary = "通过"
        severity = "info"
        if warnings:
            summary = "存在潜在节奏/时长问题"
            severity = "warning"

        return {
            "duration_seconds": duration,
            "duration_minutes": round(duration / 60.0, 1),
            "file_size_bytes": file_size,
            "bitrate": bitrate,
            "sample_rate": sample_rate,
            "warnings": warnings,
            "summary": summary,
            "severity": severity,
            "script_overall_score": getattr(script_quality_report, "overall_score", None) if script_quality_report else None,
            "script_overall_grade": getattr(script_quality_report, "overall_grade", None) if script_quality_report else None,
        }
    
