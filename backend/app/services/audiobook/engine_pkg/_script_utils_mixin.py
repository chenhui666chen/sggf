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
from ..narration_styles import apply_narration_style_to_tts_params
from ..pause_tags import coerce_pause_ms, strip_pause_tags
from ..segment_synthesis_contract import PROVIDER_PROMPT_DERIVED_FIELDS
from ..tts_delivery_plan import build_delivery_plan, resolve_segment_tts_model
from ..tts_style_control import build_model_style_control, build_provider_prompt_snapshot
from ..voice_parameter_policy import (
    merge_segment_performance_params,
    stabilize_instruct_model_speed,
)
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
    SoundEffectDesigner,
    MusicComposer,
)

logger = logging.getLogger(__name__)

class ScriptUtilsMixin:
    def _infer_opening_delivery(self, text: str) -> Dict[str, str]:
        """根据片头文本推断有声书开场的播讲方式。"""
        normalized_text = str(text or "")
        tense_keywords = (
            "逃亡",
            "危机",
            "威胁",
            "致命",
            "恐怖",
            "追杀",
            "杀",
            "血",
            "危险",
            "风暴",
        )
        mysterious_keywords = ("未知", "秘密", "真相", "谜", "阴影", "禁地")

        if any(keyword in normalized_text for keyword in tense_keywords):
            return {
                "emotion": "tense",
                "instruct_emotion": "fearful",
                "performance_notes": "克制而紧迫地讲述，带悬念感；关键词略加重，句尾短暂停顿。",
            }

        if any(keyword in normalized_text for keyword in mysterious_keywords):
            return {
                "emotion": "mysterious",
                "instruct_emotion": "neutral",
                "performance_notes": "收紧语势，保留悬念感；信息点清晰，结尾留白。",
            }

        return {
            "emotion": "solemn",
            "instruct_emotion": "neutral",
            "performance_notes": "沉稳开场，语速适中；章节名和集数清晰读出。",
        }

    def _is_narration_segment(self, segment: ScriptSegment) -> bool:
        speaker = str(getattr(segment, "speaker", "") or "").strip()
        segment_type = str(getattr(segment, "type", "") or "").strip().lower()
        return speaker == "旁白" or segment_type == "narration"

    def _apply_narration_style_to_voice_params(
        self,
        segment: ScriptSegment,
        voice_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        style_id = str(getattr(self, "_narration_style_id", "") or "").strip()
        if not style_id or not self._is_narration_segment(segment):
            return voice_params

        base_params = dict(voice_params)
        performance_notes = str(getattr(segment, "performance_notes", "") or "").strip()
        if performance_notes and not base_params.get("performance_notes"):
            base_params["performance_notes"] = performance_notes

        original_segment_params = getattr(segment, "voice_params", None) or {}
        if "speed" not in original_segment_params and "rate" not in original_segment_params:
            base_params.pop("speed", None)
            base_params.pop("rate", None)

        styled_params = apply_narration_style_to_tts_params(
            style_id,
            base_params,
            custom_prompt=getattr(self, "_narration_style_prompt", None),
        )
        styled_params["narration_style"] = style_id

        style_emotion = str(styled_params.get("emotion") or "").strip()
        if style_emotion == "variable":
            styled_params.pop("emotion", None)
        elif style_emotion:
            try:
                setattr(segment, "emotion", style_emotion)
                if not str(getattr(segment, "instruct_emotion", "") or "").strip():
                    setattr(segment, "instruct_emotion", style_emotion)
            except Exception:
                pass

        try:
            pause_multiplier = float(styled_params.get("pause_multiplier") or 1.0)
        except (TypeError, ValueError):
            pause_multiplier = 1.0

        if pause_multiplier != 1.0 and not styled_params.get("narration_style_pause_applied"):
            for key in ("pause_before", "pause_after"):
                try:
                    styled_params[key] = max(0.0, float(styled_params.get(key) or 0.0) * pause_multiplier)
                except (TypeError, ValueError):
                    pass
            pause_after_ms = coerce_pause_ms(styled_params.get("pause_after_ms"))
            if pause_after_ms is not None:
                styled_params["pause_after_ms"] = int(max(0, pause_after_ms) * pause_multiplier)
            styled_params["narration_style_pause_applied"] = True

        return styled_params

    def _normalize_final_voice_params(
        self,
        segment: ScriptSegment,
        voice_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized_params = dict(voice_params)
        instruct_emotion = str(getattr(segment, "instruct_emotion", "") or "").strip()
        if instruct_emotion and instruct_emotion != "neutral":
            normalized_params["emotion"] = instruct_emotion
            try:
                setattr(segment, "emotion", instruct_emotion)
            except Exception:
                pass

        if "rate" in normalized_params:
            normalized_params["speed"] = normalized_params["rate"]
        elif "speed" in normalized_params:
            normalized_params["rate"] = normalized_params["speed"]

        for key in ("pause_before", "pause_after"):
            try:
                pause_value = max(0.0, float(normalized_params.get(key) or 0.0))
            except (TypeError, ValueError):
                pause_value = 0.0
            normalized_params[key] = pause_value
            try:
                setattr(segment, key, pause_value)
            except Exception:
                pass

        return normalized_params

    def _build_mixer_segment_types(self, script_segments) -> List[str]:
        def normalize_type(value: Any) -> str:
            raw = str(value or "").strip().lower()
            if raw in {"section", "paragraph", "sentence", "phrase"}:
                return raw
            if raw in {"p", "para"}:
                return "paragraph"
            if raw in {"s", "sent", "narration", "dialogue", "monologue"}:
                return "sentence"
            if raw in {"is", "word"}:
                return "phrase"
            return ""

        result: List[str] = []
        for segment in script_segments or []:
            voice_params = getattr(segment, "voice_params", None) or {}
            explicit_type = (
                normalize_type(getattr(segment, "segment_type", None))
                or normalize_type(getattr(segment, "reason", None))
                or normalize_type(voice_params.get("mixer_segment_type"))
                or normalize_type(voice_params.get("text_segment_type"))
                or normalize_type(voice_params.get("segment_reason"))
            )
            if explicit_type:
                result.append(explicit_type)
                continue

            try:
                pause_after = float(
                    voice_params.get("pause_after", getattr(segment, "pause_after", 0.0)) or 0.0
                )
            except (TypeError, ValueError):
                pause_after = 0.0

            text = str(getattr(segment, "text", "") or "").rstrip()
            if pause_after >= 1.0:
                result.append("paragraph")
            elif pause_after > 0 and pause_after < 0.35:
                result.append("phrase")
            elif text.endswith(("，", "、", ",", ":", "：", ";", "；")):
                result.append("phrase")
            else:
                result.append("sentence")

        return result

    def _build_mixer_pause_after_ms(self, script_segments) -> List[Optional[int]]:
        result: List[Optional[int]] = []
        for segment in script_segments or []:
            voice_params = getattr(segment, "voice_params", None) or {}
            pause_ms = coerce_pause_ms(voice_params.get("timeline_pause_after_ms"))
            if pause_ms is None:
                pause_ms = coerce_pause_ms(voice_params.get("pause_after_ms"))
            if pause_ms is None:
                pause_ms = strip_pause_tags(getattr(segment, "text", "") or "").pause_after_ms
            result.append(pause_ms)
        return result

    def _flatten_chapter_structure(
        self,
        chapter_structure: ChapterStructure,
    ) -> List[ScriptSegment]:
        """将 ChapterStructure 展平为 ScriptSegment 列表，包含片头和片尾"""
        segments: List[ScriptSegment] = []

        # 片头
        opening = chapter_structure.opening
        if opening and opening.intro_text:
            opening_delivery = self._infer_opening_delivery(opening.intro_text)
            opening_segment = ScriptSegment(
                type="narration",
                text=opening.intro_text,
                speaker=getattr(opening, "intro_narrator", "旁白") or "旁白",
                emotion=opening_delivery["emotion"],
                performance_notes=opening_delivery["performance_notes"],
                pause_before=0.0,
                pause_after=0.5,
                music_cue=getattr(opening, "intro_music", None),
                original_text=opening.intro_text,
                adaptation_reason="自动生成章节片头",
                instruct_emotion=opening_delivery["instruct_emotion"],
                instruct_scene="章节片头",
                instruct_role="有声书旁白",
            )
            segments.append(opening_segment)

        # 正文
        segments.extend(chapter_structure.body_segments or [])

        # 片尾
        closing = chapter_structure.closing
        if closing:
            # 🆕 收集片尾各部分文本
            closing_parts = [
                closing.recap_text.strip() if closing.recap_text else "",
                closing.hook_text.strip() if closing.hook_text else "",
                closing.call_to_action.strip() if closing.call_to_action else "",
            ]
            
            # 🔥 关键修复：过滤异常内容（移除包含"旁白"等角色说话引导语的片段）
            import re
            cleaned_parts = []
            for part in closing_parts:
                if not part:
                    continue
                
                # 检测并移除异常的角色说话引导语（如"旁白说："、"旁白怎么怎么样"等）
                # 模式1："旁白说：xxx" → 保留"xxx"
                cleaned = re.sub(r'^旁白[说道讲][:：]\s*', '', part)
                # 模式2："旁白怎么怎么样" → 完全移除这种描述性文本
                if not re.match(r'^旁白[^：:，,。.！!？?\s]+', cleaned):
                    # 只有不是纯粹描述旁白状态的文本才保留
                    cleaned_parts.append(cleaned)
                else:
                    logger.warning(f"⚠️ 片尾检测到异常内容并移除: {part[:50]}")
            
            closing_text = " ".join(cleaned_parts)
            if closing_text:
                closing_segment = ScriptSegment(
                    type="narration",
                    text=closing_text,
                    speaker=getattr(closing, "outro_narrator", "旁白") or "旁白",
                    emotion="calm",
                    performance_notes="章节片尾",
                    pause_before=0.5,
                    pause_after=0.0,
                    music_cue=getattr(closing, "outro_music", None),
                    original_text=closing_text,
                    adaptation_reason="自动生成章节片尾",
                )
                segments.append(closing_segment)

        return segments
    
    def _assign_voices(self, script_segments):
        """为剧本片段分配音色（统一使用VoiceManager）"""
        for segment in script_segments:
            if segment.speaker == "旁白":
                voice_profile = self.voice_manager.get_narrator_voice()
            else:
                voice_profile = self.voice_manager.get_voice(segment.speaker)
                if not voice_profile:
                    # 未知角色，临时分配
                    voice_profile = self.voice_manager.assign_voice(segment.speaker)
            
            # 🔥 重构后：使用 VoiceManager 的默认参数，并合并段落级 voice_params
            segment_emotion = getattr(segment, "emotion", "neutral")
            instruct_emotion = (getattr(segment, "instruct_emotion", "") or "").strip()
            emotion_for_params = instruct_emotion or segment_emotion or "neutral"
            voice_params_dict = voice_profile.get_tts_params(emotion_for_params)

            segment_voice_params = getattr(segment, "voice_params", None) or {}
            voice_params_dict = merge_segment_performance_params(
                voice_params_dict,
                segment_voice_params,
                ignored_fields={"speaker", *PROVIDER_PROMPT_DERIVED_FIELDS},
            )

            if "rate" not in voice_params_dict and "speed" in voice_params_dict:
                voice_params_dict["rate"] = voice_params_dict["speed"]

            voice_params_dict["pause_before"] = segment_voice_params.get(
                "pause_before",
                getattr(segment, "pause_before", 0.0),
            )
            voice_params_dict["pause_after"] = segment_voice_params.get(
                "pause_after",
                getattr(segment, "pause_after", 0.0),
            )
            voice_params_dict = self._apply_narration_style_to_voice_params(segment, voice_params_dict)
            if "rate" not in voice_params_dict and "speed" in voice_params_dict:
                voice_params_dict["rate"] = voice_params_dict["speed"]
            voice_params_dict["tts_model"] = (
                segment_voice_params.get("tts_model")
                or getattr(voice_profile, "tts_model", None)
                or getattr(self, "tts_model", "")
            )
            voice_params_dict = self._normalize_final_voice_params(segment, voice_params_dict)
            resolved_model = resolve_segment_tts_model(
                voice_params_dict,
                getattr(self, "tts_model", None),
            )
            voice_params_dict = stabilize_instruct_model_speed(
                voice_params_dict,
                resolved_model,
            )
            voice_params_dict["resolved_tts_model"] = resolved_model
            
            # 🔍 调试：输出最终参数
            speed_for_log = voice_params_dict.get("speed")
            try:
                speed_text = f"{float(speed_for_log):.2f}"
            except (TypeError, ValueError):
                speed_text = ""
            logger.info(
                f"🎵 [{segment.speaker}] 最终voice_params: "
                f"speaker={voice_params_dict.get('speaker')}, "
                f"speed={speed_text}, "
                f"volume={voice_params_dict.get('volume')}"
            )
            
            # 写回到segment
            segment.voice_params = voice_params_dict
            instruct_emotion = (getattr(segment, "instruct_emotion", "") or "").strip()
            
            # 将片段元信息透传给TTS，用于Instruct模板（场景/角色/身份）
            segment.voice_params["segment_speaker"] = getattr(segment, "speaker", "")
            segment.voice_params["segment_type"] = getattr(segment, "type", "") 
            segment.voice_params["instruct_emotion"] = instruct_emotion
            segment.voice_params["instruct_scene"] = getattr(segment, "instruct_scene", "") or ""
            segment.voice_params["instruct_role"] = getattr(segment, "instruct_role", "") or ""
            segment.voice_params["instruct_identity"] = getattr(segment, "instruct_identity", "") or ""

            if instruct_emotion or segment.voice_params["instruct_scene"] or segment.voice_params["instruct_role"] or segment.voice_params["instruct_identity"]:
                segment.voice_params["use_instruct_mode"] = True

            segment.voice_params["delivery_plan"] = build_delivery_plan(
                segment=segment,
                voice_params=segment.voice_params,
                model=resolved_model,
                emotion=instruct_emotion or segment_emotion or "neutral",
            )
            style_control = build_model_style_control(
                resolved_model,
                segment.voice_params,
                instruct_emotion or segment_emotion or "neutral",
            )
            segment.voice_params["provider_prompt_snapshot"] = build_provider_prompt_snapshot(
                model=resolved_model,
                voice_id=segment.voice_params.get("speaker") or segment.voice_params.get("voice_id") or "",
                style_control=style_control,
                delivery_plan=segment.voice_params["delivery_plan"],
            )

    def _apply_segment_voice_overrides(
        self,
        script_segments: List,
        segment_voice_overrides: Dict[int, Dict[str, Any]],
    ) -> None:
        """Phase 2 replace_voice_missing：对指定源片段索引选择性覆盖音色。

        仅替换 voice_params["speaker"]（即 voice_id），使目标片段的 cache_key
        变化从而触发重生成，其余片段（含同角色成功片段）保持原音色复用缓存。
        """
        for index, segment in enumerate(script_segments):
            override = segment_voice_overrides.get(index)
            if not override:
                continue
            new_voice_id = str(override.get("voice_id") or override.get("speaker") or "")
            if not new_voice_id:
                continue
            voice_params = getattr(segment, "voice_params", None) or {}
            old_voice = voice_params.get("speaker") or ""
            voice_params["speaker"] = new_voice_id
            segment.voice_params = voice_params
            logger.info(
                "🔄 [replace_voice_missing] 片段 #%d (%s) 音色覆盖: %s -> %s",
                index,
                getattr(segment, "speaker", ""),
                old_voice,
                new_voice_id,
            )
