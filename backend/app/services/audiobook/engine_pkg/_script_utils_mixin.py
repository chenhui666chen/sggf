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

class ScriptUtilsMixin:
    def _flatten_chapter_structure(
        self,
        chapter_structure: ChapterStructure,
    ) -> List[ScriptSegment]:
        """将 ChapterStructure 展平为 ScriptSegment 列表，包含片头和片尾"""
        segments: List[ScriptSegment] = []

        # 片头
        opening = chapter_structure.opening
        if opening and opening.intro_text:
            opening_segment = ScriptSegment(
                type="narration",
                text=opening.intro_text,
                speaker=getattr(opening, "intro_narrator", "旁白") or "旁白",
                emotion="calm",
                performance_notes="章节片头",
                pause_before=0.0,
                pause_after=0.5,
                music_cue=getattr(opening, "intro_music", None),
                original_text=opening.intro_text,
                adaptation_reason="自动生成章节片头",
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
            for key, value in segment_voice_params.items():
                if value is None or key == "speaker":
                    continue
                voice_params_dict[key] = value

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
            
            # 🔍 调试：输出最终参数
            logger.info(
                f"🎵 [{segment.speaker}] 最终voice_params: "
                f"speaker={voice_params_dict.get('speaker')}, "
                f"pitch={voice_params_dict.get('pitch')}, "
                f"speed={voice_params_dict.get('speed'):.2f}, "
                f"volume={voice_params_dict.get('volume')}"
            )
            
            # 写回到segment
            segment.voice_params = voice_params_dict
            
            # 将片段元信息透传给TTS，用于Instruct模板（场景/角色/身份）
            segment.voice_params["segment_speaker"] = getattr(segment, "speaker", "")
            segment.voice_params["segment_type"] = getattr(segment, "type", "") 
            segment.voice_params["instruct_emotion"] = instruct_emotion
            segment.voice_params["instruct_scene"] = getattr(segment, "instruct_scene", "") or ""
            segment.voice_params["instruct_role"] = getattr(segment, "instruct_role", "") or ""
            segment.voice_params["instruct_identity"] = getattr(segment, "instruct_identity", "") or ""

            if instruct_emotion or segment.voice_params["instruct_scene"] or segment.voice_params["instruct_role"] or segment.voice_params["instruct_identity"]:
                segment.voice_params["use_instruct_mode"] = True
