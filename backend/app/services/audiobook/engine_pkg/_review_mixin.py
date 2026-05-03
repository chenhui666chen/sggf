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
        audio_data: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """对最终混合后的音频做一次轻量评审。

        说明：
        - 基于音频时长和基础信息做兜底检查
        - 复用 AudioMixer.analyze_quality 做确定性波形质量分析
        - 不新增外部语音模型依赖
        """
        duration = float(audio_info.get("duration_seconds", 0.0) or 0.0)
        bitrate = audio_info.get("bitrate", None)
        sample_rate = audio_info.get("sample_rate", None)

        standards = getattr(self.audio_quality_reviewer, "quality_standards", {})
        max_duration = float(standards.get("max_episode_duration", 0) or 0)
        min_duration = float(standards.get("min_episode_duration", 0) or 0)

        warnings: List[str] = []
        waveform_quality: Dict[str, Any] = {
            "available": False,
            "reason": "missing_audio_data",
        }

        if max_duration and duration > max_duration:
            warnings.append(f"音频时长偏长（约 {duration/60:.1f} 分钟）")
        if min_duration and duration and duration < min_duration * 0.5:
            warnings.append(f"音频时长偏短（约 {duration/60:.1f} 分钟）")
        if audio_data is not None:
            analyze_quality = getattr(self.audio_mixer, "analyze_quality", None)
            if callable(analyze_quality):
                try:
                    waveform_quality = self._serialize_audio_quality_report(
                        analyze_quality(audio_data)
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("最终音频波形质量分析失败: %s", exc)
                    waveform_quality = {
                        "available": False,
                        "reason": "analysis_failed",
                        "error": str(exc),
                    }
            else:
                waveform_quality = {
                    "available": False,
                    "reason": "analyzer_unavailable",
                }

        quality_issues = waveform_quality.get("issues") if isinstance(waveform_quality, dict) else None
        if isinstance(quality_issues, list):
            for issue in quality_issues[:5]:
                if not isinstance(issue, dict):
                    continue
                severity_label = str(issue.get("severity") or "").strip()
                description = str(issue.get("description") or "").strip()
                if description:
                    warnings.append(f"{severity_label}: {description}" if severity_label else description)

        summary = "通过"
        severity = "info"
        quality_passed = waveform_quality.get("passed") if isinstance(waveform_quality, dict) else None
        if warnings:
            summary = "存在潜在音频质量问题"
            severity = "warning"
        if quality_passed is False:
            summary = "存在音频质量问题"
            severity = "error"

        return {
            "duration_seconds": duration,
            "duration_minutes": round(duration / 60.0, 1),
            "file_size_bytes": file_size,
            "bitrate": bitrate,
            "sample_rate": sample_rate,
            "waveform_quality": waveform_quality,
            "warnings": warnings,
            "summary": summary,
            "severity": severity,
            "script_overall_score": getattr(script_quality_report, "overall_score", None) if script_quality_report else None,
            "script_overall_grade": getattr(script_quality_report, "overall_grade", None) if script_quality_report else None,
        }

    def _serialize_audio_quality_report(self, report: Any) -> Dict[str, Any]:
        if report is None:
            return {"available": False, "reason": "empty_report"}

        data = asdict(report) if is_dataclass(report) else dict(report)
        grade = data.get("grade")
        if hasattr(grade, "value"):
            data["grade"] = grade.value

        normalized_issues: List[Dict[str, Any]] = []
        for issue in data.get("issues") or []:
            issue_data = asdict(issue) if is_dataclass(issue) else dict(issue)
            normalized_issues.append(issue_data)

        data["issues"] = normalized_issues
        data["available"] = True
        return data
    
