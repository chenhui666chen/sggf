from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.services.audiobook.constants import (
    QWEN3_TTS_INSTRUCT_SUPPORTED_VOICES,
    normalize_speaker_id,
)
from app.services.audiobook.tts_engine_pkg._aliyun_mixin import AliyunMixin
from app.services.audiobook.voice_catalog import load_voice_catalog_for_model


class _DummyQwenAliyunMixin(AliyunMixin):
    model = "qwen3-tts-instruct-flash"

    def _is_qwen_model(self) -> bool:
        return True

    def _is_minimax_model(self) -> bool:
        return False


def test_qwen_voice_catalog_filters_flash_only_voices() -> None:
    catalog = load_voice_catalog_for_model("qwen3-tts-instruct-flash")
    voice_ids = {voice["id"] for voice in catalog["voices"]}

    assert voice_ids == QWEN3_TTS_INSTRUCT_SUPPORTED_VOICES
    assert "Dylan" not in voice_ids
    assert catalog["meta"]["voice_count"] == len(QWEN3_TTS_INSTRUCT_SUPPORTED_VOICES)


def test_normalize_speaker_id_maps_legacy_qwen_and_cosyvoice_ids() -> None:
    assert normalize_speaker_id("Dylan") == "Ethan"
    assert normalize_speaker_id("Ryan") == "Neil"
    assert normalize_speaker_id("longxiaochun") == "Bellona"


def test_aliyun_qwen_normalization_uses_supported_instruct_voice() -> None:
    engine = _DummyQwenAliyunMixin()

    assert engine._normalize_speaker_id("Dylan", "qwen3-tts-instruct-flash") == "Ethan"
    assert engine._normalize_speaker_id("male_narrator", "qwen3-tts-instruct-flash") == "Neil"
    assert engine._normalize_speaker_id("female_villain_cold", "qwen3-tts-instruct-flash") == "Bellona"
