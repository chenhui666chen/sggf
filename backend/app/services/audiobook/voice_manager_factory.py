from __future__ import annotations

from typing import Any

from .voice_manager import VoiceManager
from .voice_manager_cosyvoice_v3_plus import CosyVoiceV3PlusVoiceManager


def create_voice_manager(tts_model: str, llm_client: Any = None):
    tts_model = (tts_model or "").strip() or "qwen3-tts-flash"
    if tts_model == "cosyvoice-v3-plus":
        return CosyVoiceV3PlusVoiceManager()
    return VoiceManager(llm_client=llm_client)

