from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import HTTPException, status

from app.services.audiobook.agents import SoundEffectDesigner
from app.services.audiobook.audio_library_paths import (
    get_audio_library_dir,
    resolve_audio_library_file_path,
)
from app.services.audiobook.audio_mixer import AudioMixer
from app.services.audiobook.duration_estimator import estimate_narration_duration_seconds
from app.services.audiobook.tts_engine import RetryConfig as TTSRetryConfig
from app.services.audiobook.voice_manager_factory import create_voice_manager
from core.unified_media_runtime import synthesize_speech as runtime_synthesize_speech

logger = logging.getLogger(__name__)

SynthesizeSpeech = Callable[..., Awaitable[bytes]]


@dataclass(frozen=True)
class SegmentPreviewResult:
    audio: bytes
    media_type: str


class SegmentPreviewService:
    """单段剧本试听编排服务。"""

    def __init__(
        self,
        *,
        tts_model: str,
        voice_mapping: Dict[str, Dict[str, Any]],
        audio_fx: Dict[str, Any],
        synthesize_speech: SynthesizeSpeech = runtime_synthesize_speech,
        audio_mixer: Optional[AudioMixer] = None,
        audio_library_dir: Optional[Path] = None,
    ) -> None:
        self.tts_model = tts_model
        self.audio_fx = dict(audio_fx or {})
        self.synthesize_speech = synthesize_speech
        self.audio_mixer = audio_mixer or AudioMixer()
        self.audio_library_dir = audio_library_dir or get_audio_library_dir()
        self.voice_manager = create_voice_manager(tts_model=tts_model, llm_client=None)

        if voice_mapping:
            try:
                self.voice_manager.apply_project_voice_mapping(voice_mapping)
            except Exception as exc:
                logger.warning("单段音色映射失败: %s", exc)

    def resolve_voice_params(self, segment: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        speaker = str(segment.get("speaker") or "旁白").strip() or "旁白"
        if speaker in {"旁白", "narrator", "Narrator"}:
            voice_profile = self.voice_manager.get_narrator_voice()
        else:
            voice_profile = self.voice_manager.get_voice(speaker)
            if not voice_profile:
                voice_profile = self.voice_manager.assign_voice(speaker)

        emotion = str(segment.get("emotion") or "neutral").strip() or "neutral"
        instruct_emotion = str(segment.get("instruct_emotion") or "").strip()
        emotion_for_params = instruct_emotion or emotion

        voice_params = voice_profile.get_tts_params(emotion_for_params)
        segment_voice_params = segment.get("voice_params") or {}
        if not isinstance(segment_voice_params, dict):
            segment_voice_params = {}
        for key, value in segment_voice_params.items():
            if value is None or key == "speaker":
                continue
            voice_params[key] = value

        if instruct_emotion and instruct_emotion != "neutral":
            voice_params["emotion"] = instruct_emotion

        if "rate" in voice_params:
            voice_params["speed"] = voice_params["rate"]
        elif "speed" in voice_params:
            voice_params["rate"] = voice_params["speed"]

        voice_params["pause_before"] = segment_voice_params.get(
            "pause_before",
            segment.get("pause_before", 0.0),
        )
        voice_params["pause_after"] = segment_voice_params.get(
            "pause_after",
            segment.get("pause_after", 0.0),
        )

        voice_params["segment_speaker"] = speaker
        voice_params["segment_type"] = segment.get("type", "")
        voice_params["instruct_emotion"] = instruct_emotion
        voice_params["instruct_scene"] = str(segment.get("instruct_scene") or "").strip()
        voice_params["instruct_role"] = str(segment.get("instruct_role") or "").strip()
        voice_params["instruct_identity"] = str(segment.get("instruct_identity") or "").strip()
        performance_notes = str(segment.get("performance_notes") or "").strip()
        if performance_notes:
            voice_params["performance_notes"] = performance_notes

        if (
            instruct_emotion
            or voice_params["instruct_scene"]
            or voice_params["instruct_role"]
            or voice_params["instruct_identity"]
            or performance_notes
        ):
            voice_params["use_instruct_mode"] = True

        return emotion_for_params, voice_params

    @staticmethod
    def estimate_duration_seconds(text_value: str) -> float:
        return estimate_narration_duration_seconds(text_value, min_duration=3.0)

    @staticmethod
    def normalize_sound_effects(segment_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        specs: List[Dict[str, Any]] = []
        raw_effects = segment_data.get("sound_effects")
        if isinstance(raw_effects, list) and raw_effects:
            for effect in raw_effects:
                if not effect:
                    continue
                if isinstance(effect, dict):
                    asset_id = (
                        effect.get("asset_id")
                        or effect.get("effect_id")
                        or effect.get("id")
                    )
                    name = effect.get("name") or effect.get("effect") or asset_id
                    if not name:
                        continue
                    spec = {
                        "name": str(name).strip(),
                        "volume": effect.get("volume"),
                        "delay": effect.get("delay", effect.get("start_time", 0.0)),
                        "duration": effect.get("duration"),
                        "fade_in": effect.get("fade_in"),
                        "fade_out": effect.get("fade_out"),
                        "layer": effect.get("layer"),
                        "timing": effect.get("timing"),
                        "file": effect.get("file") or effect.get("audio_file"),
                    }
                    if asset_id:
                        spec["asset_id"] = str(asset_id).strip()
                    specs.append(spec)
                else:
                    name = str(effect).strip()
                    if name:
                        specs.append({"name": name})
        else:
            simple = segment_data.get("sound_effects_simple") or []
            if isinstance(simple, list):
                for name in simple:
                    if not name:
                        continue
                    specs.append({"name": str(name).strip()})
            elif isinstance(simple, str) and simple.strip():
                for name in simple.split(","):
                    if not name.strip():
                        continue
                    specs.append({"name": name.strip()})
        return specs

    @staticmethod
    def build_effect_timeline(effect_specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not effect_specs:
            return []
        designer = SoundEffectDesigner(llm_client=None)
        timeline: List[Dict[str, Any]] = []
        for spec in effect_specs:
            name = spec.get("name")
            if not name:
                continue
            match_reference = spec.get("asset_id") or name
            cue = designer._match_effect(str(match_reference), 0.0, "preview")
            layer = str(spec.get("layer") or "").strip().lower()
            effect_type = cue.effect_type.value if cue else "action"
            if layer in {"bottom", "atmosphere", "environment", "ambient"}:
                effect_type = "environment"
            file_ref = spec.get("file") or (cue.audio_file if cue else "")
            if not file_ref:
                continue
            timeline.append(
                {
                    "timestamp": float(spec.get("delay") or 0.0),
                    "type": effect_type,
                    "description": str(name),
                    "file": file_ref,
                    "volume": spec.get("volume", cue.volume if cue else 0.5),
                    "duration": spec.get("duration", cue.duration if cue else None),
                    "fade_in": spec.get("fade_in", cue.fade_in if cue else 0.0),
                    "fade_out": spec.get("fade_out", cue.fade_out if cue else 0.0),
                    "loop": bool(
                        spec.get("timing") == "continuous"
                        or spec.get("loop")
                        or (cue.loop if cue else False)
                        or effect_type == "environment"
                    ),
                }
            )
        return timeline

    @staticmethod
    def resolve_effect_path(file_ref: str, name_hint: str, base_dir: Path) -> Optional[Path]:
        if not file_ref:
            return None
        effect_path = Path(file_ref)
        if not effect_path.is_absolute():
            effect_path = base_dir / file_ref
        if effect_path.exists():
            return effect_path
        candidate_name = Path(file_ref).stem or name_hint
        if candidate_name:
            for candidate in (base_dir / "sound_effects").rglob(f"{candidate_name}.*"):
                return candidate
        return None

    def apply_sound_effects(
        self,
        base_audio: bytes,
        timeline: List[Dict[str, Any]],
    ) -> bytes:
        if not base_audio or not timeline:
            return base_audio
        mixed_audio = base_audio
        ducking_enabled = self.audio_fx.get("sound_effect_ducking", True)
        ducking_priority = self.audio_fx.get("sound_effect_priority", "dialogue")
        ducking_threshold_dbfs = self.audio_fx.get("sound_effect_ducking_threshold_dbfs", -35.0)
        ducking_reduction_db = self.audio_fx.get("sound_effect_ducking_reduction_db", -6.0)
        ducking_chunk_ms = self.audio_fx.get("sound_effect_ducking_chunk_ms", 250)
        base_gain_map = {
            "environment": -14.0,
            "action": -14.0,
            "emotion": -16.0,
            "transition": -18.0,
        }
        for item in timeline:
            file_ref = item.get("file")
            effect_path = self.resolve_effect_path(
                str(file_ref or ""), str(item.get("description") or ""), self.audio_library_dir
            )
            if not effect_path or not effect_path.exists():
                logger.warning("试听音效文件不存在: %s", effect_path or file_ref)
                continue

            effect_type_str = item.get("type", "action")
            base_gain = base_gain_map.get(effect_type_str, -16.0)
            timeline_volume = item.get("volume", 0.5)
            try:
                timeline_volume = float(timeline_volume)
            except (TypeError, ValueError):
                timeline_volume = 0.5
            timeline_volume = max(0.05, min(1.0, timeline_volume))
            relative = timeline_volume / 0.5
            volume_adjust_db = 20 * math.log10(relative)
            effect_volume_offset = base_gain + volume_adjust_db

            duration = item.get("duration")
            fade_in = item.get("fade_in", 0.0)
            fade_out = item.get("fade_out", 0.0)
            loop = bool(item.get("loop")) or effect_type_str == "environment"

            try:
                with effect_path.open("rb") as f:
                    effect_bytes = f.read()
                position_ms = int(float(item.get("timestamp") or 0.0) * 1000)
                effect_duration_ms = None
                try:
                    if duration is not None:
                        duration_val = float(duration)
                        if duration_val <= 0:
                            effect_duration_ms = None
                        else:
                            effect_duration_ms = int(duration_val * 1000)
                except (TypeError, ValueError):
                    effect_duration_ms = None
                fade_in_ms = int(float(fade_in) * 1000) if fade_in else 0
                fade_out_ms = int(float(fade_out) * 1000) if fade_out else 0
                mixed_audio = self.audio_mixer.add_sound_effect(
                    mixed_audio,
                    effect_bytes,
                    position_ms=position_ms,
                    effect_volume_offset=effect_volume_offset,
                    effect_duration_ms=effect_duration_ms,
                    fade_in_ms=fade_in_ms,
                    fade_out_ms=fade_out_ms,
                    loop_fill=bool(loop),
                    ducking_enabled=bool(ducking_enabled),
                    ducking_priority=str(ducking_priority or "dialogue"),
                    ducking_threshold_dbfs=float(ducking_threshold_dbfs),
                    ducking_reduction_db=float(ducking_reduction_db),
                    ducking_chunk_ms=int(ducking_chunk_ms),
                )
            except Exception as exc:
                logger.warning("叠加试听音效失败 %s: %s", effect_path, exc)
        return mixed_audio

    @staticmethod
    def normalize_music_cue(segment_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        raw_cue = segment_data.get("music_cue")
        if isinstance(raw_cue, dict):
            style = raw_cue.get("style") or raw_cue.get("name") or raw_cue.get("cue")
            file_ref = raw_cue.get("file") or raw_cue.get("audio_file")
            return {
                "asset_id": str(
                    raw_cue.get("asset_id")
                    or raw_cue.get("music_id")
                    or raw_cue.get("id")
                    or ""
                ).strip() or None,
                "style": str(style or "").strip(),
                "file": file_ref,
                "volume": raw_cue.get("volume", 0.2),
                "fade_in": raw_cue.get("fade_in", 0.0),
                "fade_out": raw_cue.get("fade_out", 0.0),
                "duration": raw_cue.get("duration"),
                "start_time": raw_cue.get("start_time", 0.0),
                "sync_with_dialogue": raw_cue.get("sync_with_dialogue", True),
                "dialogue_volume_reduction": raw_cue.get("dialogue_volume_reduction", 0.0),
                "mood": raw_cue.get("mood"),
            }
        if isinstance(raw_cue, str) and raw_cue.strip():
            return {
                "style": raw_cue.strip(),
                "file": None,
                "volume": 0.2,
                "fade_in": 0.0,
                "fade_out": 0.0,
                "duration": None,
                "start_time": 0.0,
                "sync_with_dialogue": True,
                "dialogue_volume_reduction": 0.0,
                "mood": None,
            }
        simple_cue = segment_data.get("music_cue_simple")
        if isinstance(simple_cue, str) and simple_cue.strip():
            return {
                "style": simple_cue.strip(),
                "file": None,
                "volume": 0.2,
                "fade_in": 0.0,
                "fade_out": 0.0,
                "duration": None,
                "start_time": 0.0,
                "sync_with_dialogue": True,
                "dialogue_volume_reduction": 0.0,
                "mood": None,
            }
        return None

    @staticmethod
    def infer_music_mood(emotion_value: str) -> str:
        raw = (emotion_value or "").lower()
        if any(key in raw for key in ["sad", "悲", "伤"]):
            return "sad"
        if any(key in raw for key in ["happy", "joy", "欢", "乐"]):
            return "joyful"
        if any(key in raw for key in ["tense", "angry", "fear", "紧张", "恐惧", "愤怒"]):
            return "tense"
        if any(key in raw for key in ["romantic", "love", "浪漫"]):
            return "romantic"
        if any(key in raw for key in ["mysterious", "神秘"]):
            return "mysterious"
        if any(key in raw for key in ["epic", "史诗", "宏大"]):
            return "epic"
        return "peaceful"

    @staticmethod
    def load_music_index(base_dir: Path) -> List[Dict[str, Any]]:
        index_path = base_dir / "music_index.json"
        if not index_path.exists():
            return []
        try:
            raw = index_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning("读取音乐索引失败: %s", exc)
            return []

    @staticmethod
    def resolve_music_path(
        file_ref: Optional[str],
        style_hint: str,
        mood_hint: str,
        base_dir: Path,
        music_index: List[Dict[str, Any]],
        asset_id: str = "",
    ) -> Optional[Path]:
        normalized_asset_id = str(asset_id or "").strip()
        if normalized_asset_id and music_index:
            for entry in music_index:
                entry_id = str(entry.get("id") or entry.get("asset_id") or "").strip()
                if entry_id != normalized_asset_id:
                    continue
                resolved = resolve_audio_library_file_path(
                    entry.get("file_path") or entry.get("file"),
                    base_dir,
                )
                if resolved:
                    return resolved
                break
            logger.warning("试听配乐素材 ID 不存在或文件不可用，将回退到提示匹配: %s", normalized_asset_id)

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

        if music_index:
            if style_hint:
                for entry in music_index:
                    style = str(entry.get("style") or "").strip()
                    if style and (style_hint in style or style in style_hint):
                        resolved = resolve_audio_library_file_path(
                            entry.get("file_path"),
                            base_dir,
                        )
                        if resolved:
                            return resolved
            if mood_hint:
                for entry in music_index:
                    if str(entry.get("mood") or "").strip().lower() == mood_hint:
                        resolved = resolve_audio_library_file_path(
                            entry.get("file_path"),
                            base_dir,
                        )
                        if resolved:
                            return resolved
            for entry in music_index:
                resolved = resolve_audio_library_file_path(
                    entry.get("file_path"),
                    base_dir,
                )
                if resolved:
                    return resolved

        for candidate in (base_dir / "music_cache").rglob("*.mp3"):
            return candidate
        return None

    def apply_background_music(
        self,
        base_audio: bytes,
        cue: Dict[str, Any],
        *,
        duration_seconds: float,
        emotion: str,
    ) -> bytes:
        if not base_audio or not cue:
            return base_audio
        music_index = self.load_music_index(self.audio_library_dir)
        mood_hint = str(cue.get("mood") or self.infer_music_mood(emotion)).strip()
        style_hint = str(cue.get("style") or "").strip()
        music_path = self.resolve_music_path(
            cue.get("file"),
            style_hint,
            mood_hint,
            self.audio_library_dir,
            music_index,
            asset_id=str(cue.get("asset_id") or ""),
        )
        if not music_path or not music_path.exists():
            logger.warning("试听配乐文件不存在: %s", music_path)
            return base_audio

        base_bgm_volume_db = self.audio_fx.get("base_bgm_volume", -36)
        try:
            volume_val = float(cue.get("volume", 0.2))
        except (TypeError, ValueError):
            volume_val = 0.2
        volume_val = max(0.05, min(1.0, volume_val))
        relative = volume_val / 0.2
        volume_adjust_db = 20 * math.log10(relative) if relative > 0 else -40
        bgm_volume_offset = base_bgm_volume_db + volume_adjust_db - 3

        try:
            bgm_crossfade_ms = int(self.audio_fx.get("bgm_crossfade_ms") or 0)
        except Exception:
            bgm_crossfade_ms = 0
        if bgm_crossfade_ms < 0:
            bgm_crossfade_ms = 0

        try:
            with music_path.open("rb") as f:
                bgm_bytes = f.read()
            start_ms = max(0, int(float(cue.get("start_time") or 0.0) * 1000))
            duration_ms = None
            try:
                if cue.get("duration") is not None:
                    duration_ms = max(0, int(float(cue.get("duration") or 0.0) * 1000))
                else:
                    duration_ms = max(0, int(duration_seconds * 1000))
            except (TypeError, ValueError):
                duration_ms = None
            fade_in_ms = max(0, int(float(cue.get("fade_in") or 0.0) * 1000))
            fade_out_ms = max(0, int(float(cue.get("fade_out") or 0.0) * 1000))
            if bgm_crossfade_ms > 0:
                fade_in_ms = max(fade_in_ms, bgm_crossfade_ms)
                fade_out_ms = max(fade_out_ms, bgm_crossfade_ms)

            return self.audio_mixer.add_background_music(
                base_audio,
                bgm_bytes,
                bgm_volume_offset=int(bgm_volume_offset),
                position_ms=start_ms,
                duration_ms=duration_ms,
                fade_in_ms=fade_in_ms,
                fade_out_ms=fade_out_ms,
                loop_fill=True,
                sync_with_dialogue=bool(cue.get("sync_with_dialogue", True)),
                dialogue_volume_reduction=float(cue.get("dialogue_volume_reduction") or 0.0),
            )
        except Exception as exc:
            logger.warning("叠加试听配乐失败 %s: %s", music_path, exc)
            return base_audio

    def resolve_base_duration(
        self,
        *,
        estimated_duration: float,
        effect_timeline: List[Dict[str, Any]],
        music_cue: Optional[Dict[str, Any]],
    ) -> float:
        base_duration = estimated_duration
        if effect_timeline:
            for item in effect_timeline:
                item_duration = item.get("duration")
                try:
                    if item_duration is None:
                        item_duration = estimated_duration if item.get("loop") else 2.0
                    item_duration = float(item_duration or 0.0)
                except (TypeError, ValueError):
                    item_duration = 0.0
                try:
                    timestamp = float(item.get("timestamp") or 0.0)
                except (TypeError, ValueError):
                    timestamp = 0.0
                base_duration = max(base_duration, timestamp + max(0.0, item_duration))
        if music_cue:
            try:
                start_time = float(music_cue.get("start_time") or 0.0)
            except (TypeError, ValueError):
                start_time = 0.0
            cue_duration = music_cue.get("duration")
            try:
                cue_duration = (
                    float(cue_duration) if cue_duration is not None else estimated_duration
                )
            except (TypeError, ValueError):
                cue_duration = estimated_duration
            base_duration = max(base_duration, start_time + max(0.0, cue_duration))
        return base_duration

    async def synthesize_voice(
        self,
        *,
        text: str,
        voice_params: Dict[str, Any],
        emotion: str,
    ) -> bytes:
        preview_retry = TTSRetryConfig(
            max_retries=4,
            base_delay=1.0,
            max_delay=8.0,
            exponential_base=2.0,
            jitter=True,
        )
        try:
            voice_audio = await self.synthesize_speech(
                text=text,
                voice_params=voice_params,
                emotion=emotion,
                model_id=self.tts_model,
                enable_cache=False,
                max_concurrent=1,
                request_delay=0.0,
                retry_config=preview_retry,
            )
        except Exception as exc:
            logger.warning("单段TTS试听失败: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"message": "TTS服务暂时不可用，请稍后重试", "retryable": True},
            ) from exc

        if not voice_audio:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"message": "TTS服务暂时不可用，请稍后重试", "retryable": True},
            )
        return voice_audio

    async def generate_preview(
        self,
        segment: Dict[str, Any],
        *,
        preview_type: str,
    ) -> SegmentPreviewResult:
        text = str(segment.get("text") or "").strip()
        if not text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="台词不能为空",
            )

        emotion, voice_params = self.resolve_voice_params(segment)

        voice_audio: Optional[bytes] = None
        if preview_type in {"voice", "mix"}:
            voice_audio = await self.synthesize_voice(
                text=text,
                voice_params=voice_params,
                emotion=emotion,
            )

            if preview_type == "voice":
                media_type = "audio/wav" if voice_audio.startswith(b"RIFF") else "audio/mpeg"
                return SegmentPreviewResult(audio=voice_audio, media_type=media_type)

        estimated_duration = self.estimate_duration_seconds(text)

        effect_timeline: List[Dict[str, Any]] = []
        if preview_type in {"sfx", "mix"}:
            effect_specs = self.normalize_sound_effects(segment)
            effect_timeline = self.build_effect_timeline(effect_specs)
            if preview_type == "sfx" and not effect_timeline:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="该片段未配置音效，无法试听音效",
                )

        music_cue = None
        if preview_type in {"bgm", "mix"}:
            music_cue = self.normalize_music_cue(segment)
            if preview_type == "bgm" and not music_cue:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="该片段未配置配乐，无法试听配乐",
                )

        base_duration = self.resolve_base_duration(
            estimated_duration=estimated_duration,
            effect_timeline=effect_timeline,
            music_cue=music_cue,
        )

        if preview_type in {"sfx", "bgm"}:
            base_audio = self.audio_mixer.create_silence(
                int(max(1.0, base_duration) * 1000),
                output_format="mp3",
                bitrate="128k",
            )
            if not base_audio:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="音频混音组件不可用，无法生成试听音频",
                )
        else:
            base_audio = voice_audio or b""

        mixed_audio = base_audio
        if effect_timeline:
            mixed_audio = self.apply_sound_effects(mixed_audio, effect_timeline)
        if music_cue:
            mixed_audio = self.apply_background_music(
                mixed_audio,
                music_cue,
                duration_seconds=base_duration,
                emotion=emotion,
            )

        if not mixed_audio:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="试听音频生成失败，请稍后重试",
            )

        return SegmentPreviewResult(audio=mixed_audio, media_type="audio/mpeg")
