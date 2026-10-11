"""Shared constants for audiobook services."""

from .tts_model_ids import QWEN_AUDIO_31_TTS_FLASH_MODEL
from .voice_catalog import get_voice_entry

# qwen-audio-3.1-tts-flash 的官方音色 ID 一律带 `_v3.1` 后缀，且与部分
# CosyVoice 声线同名（longanya、longanlang、longanwen…）。历史项目配置里残留的
# 旧写法只需补后缀就能命中当前音色目录；命不中的原样返回，由调用方按默认音色兜底。
_QWEN_AUDIO_31_VOICE_SUFFIX = "_v3.1"
_LEGACY_SPEAKER_SUFFIXES = ("_v3.5", "_v3_plus", "_v3")


def normalize_speaker_id(speaker_id: str) -> str:
    """把历史 speaker 折叠到 qwen-audio-3.1-tts-flash 的音色 ID 空间。"""
    raw = str(speaker_id or "").strip()
    if not raw:
        return ""
    if raw.endswith(_QWEN_AUDIO_31_VOICE_SUFFIX):
        return raw

    stem = raw
    for suffix in _LEGACY_SPEAKER_SUFFIXES:
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break

    candidate = f"{stem}{_QWEN_AUDIO_31_VOICE_SUFFIX}"
    if get_voice_entry(candidate, model=QWEN_AUDIO_31_TTS_FLASH_MODEL) is not None:
        return candidate
    return raw
