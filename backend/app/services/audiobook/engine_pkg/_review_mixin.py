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
        script_segments: Optional[List[Any]] = None,
        audio_list: Optional[List[Any]] = None,
        audio_presence: Optional[List[bool]] = None,
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
            "prompt_audio_quality": self._build_prompt_audio_quality_feedback(
                script_segments,
                audio_list,
                audio_presence,
            ),
            "warnings": warnings,
            "summary": summary,
            "severity": severity,
            "script_overall_score": getattr(script_quality_report, "overall_score", None) if script_quality_report else None,
            "script_overall_grade": getattr(script_quality_report, "overall_grade", None) if script_quality_report else None,
        }

    def _build_prompt_audio_quality_feedback(
        self,
        script_segments: Optional[List[Any]],
        audio_list: Optional[List[Any]],
        audio_presence: Optional[List[bool]] = None,
    ) -> Dict[str, Any]:
        if not script_segments:
            return {"available": False, "reason": "missing_script_segments"}

        by_model: Dict[str, Dict[str, Any]] = {}
        provider_prompt_snapshot_count = 0
        inline_tag_strategy_count = 0
        audio_segments_count = 0
        manual_review_pending_count = 0

        for index, segment in enumerate(script_segments):
            voice_params = self._segment_voice_params(segment)
            snapshot = voice_params.get("provider_prompt_snapshot") if isinstance(voice_params, dict) else None
            provider_prompt = snapshot.get("provider_prompt") if isinstance(snapshot, dict) else None
            strategy = provider_prompt.get("inline_tag_strategy") if isinstance(provider_prompt, dict) else None

            model = self._segment_review_model(segment, voice_params, snapshot)
            model_feedback = by_model.setdefault(
                model,
                {
                    "model_family": "unknown",
                    "segments_count": 0,
                    "audio_segments_count": 0,
                    "missing_audio_count": 0,
                    "provider_prompt_snapshot_count": 0,
                    "inline_tag_strategy_count": 0,
                    "use_tag_parser_count": 0,
                    "tag_count": 0,
                    "manual_review_segment_indices": [],
                    "manual_review_fields": {
                        "tag_parse_success": None,
                        "text_contamination": None,
                        "score": None,
                    },
                },
            )
            model_feedback["segments_count"] += 1

            if audio_presence is not None:
                has_audio = bool(
                    index < len(audio_presence) and audio_presence[index]
                )
            else:
                has_audio = bool(
                    index < len(audio_list or []) and (audio_list or [])[index]
                )
            if has_audio:
                audio_segments_count += 1
                model_feedback["audio_segments_count"] += 1
            else:
                model_feedback["missing_audio_count"] += 1

            if isinstance(snapshot, dict):
                provider_prompt_snapshot_count += 1
                model_feedback["provider_prompt_snapshot_count"] += 1

            if not isinstance(strategy, dict):
                continue

            inline_tag_strategy_count += 1
            manual_review_pending_count += 1
            model_feedback["inline_tag_strategy_count"] += 1
            model_feedback["manual_review_segment_indices"].append(index)
            model_feedback["model_family"] = (
                str(strategy.get("model_family") or model_feedback["model_family"]).strip()
                or model_feedback["model_family"]
            )
            use_tag_parser = strategy.get("use_tag_parser")
            if use_tag_parser is True or (
                isinstance(use_tag_parser, str)
                and use_tag_parser.strip().lower() in {"1", "true", "yes"}
            ):
                model_feedback["use_tag_parser_count"] += 1

            segment_tags = set()
            for tag_key in ("style_tags", "inline_tags"):
                tags = strategy.get(tag_key)
                if not isinstance(tags, list):
                    continue
                for tag in tags:
                    tag_text = str(tag).strip() if tag is not None else ""
                    if tag_text:
                        segment_tags.add(tag_text)
            model_feedback["tag_count"] += len(segment_tags)

        segments_count = len(script_segments)
        return {
            "available": True,
            "coverage": {
                "segments_count": segments_count,
                "audio_segments_count": audio_segments_count,
                "missing_audio_count": max(segments_count - audio_segments_count, 0),
                "provider_prompt_snapshot_count": provider_prompt_snapshot_count,
                "inline_tag_strategy_count": inline_tag_strategy_count,
                "manual_review_pending_count": manual_review_pending_count,
            },
            "by_model": by_model,
        }

    def _segment_voice_params(self, segment: Any) -> Dict[str, Any]:
        if isinstance(segment, dict):
            voice_params = segment.get("voice_params")
        else:
            voice_params = getattr(segment, "voice_params", None)
        return voice_params if isinstance(voice_params, dict) else {}

    def _segment_review_model(
        self,
        segment: Any,
        voice_params: Dict[str, Any],
        snapshot: Any,
    ) -> str:
        if isinstance(snapshot, dict):
            model = str(snapshot.get("model") or "").strip()
            if model:
                return model
        for key in ("resolved_tts_model", "tts_model"):
            model = str(voice_params.get(key) or "").strip()
            if model:
                return model
        if isinstance(segment, dict):
            model = str(segment.get("tts_model") or "").strip()
        else:
            model = str(getattr(segment, "tts_model", "") or "").strip()
        return model or "unknown"

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
    
