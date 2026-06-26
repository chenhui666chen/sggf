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
from app.services.audiobook.tts_model_ids import MIMO_V25_TTS_MODEL
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
    assert "qwen-tts-voice-list" in catalog["meta"]["source"]


def test_qwen_voice_catalog_uses_official_instruct_voice_metadata() -> None:
    catalog = load_voice_catalog_for_model("qwen3-tts-instruct-flash")
    voices = catalog["voices_by_id"]

    assert voices["Mochi"]["gender"] == "male"
    assert voices["Elias"]["gender"] == "female"
    assert voices["Cherry"]["label"] == "芊悦 (Cherry)"
    assert voices["Neil"]["description"].startswith("平直的基线语调")


def test_qwen_instruct_voices_expose_machine_readable_voice_profiles() -> None:
    catalog = load_voice_catalog_for_model("qwen3-tts-instruct-flash")
    voices = catalog["voices_by_id"]
    required_profile_fields = {
        "age_group",
        "pitch",
        "pace",
        "emotion_baseline",
        "timbre_traits",
        "recommended_use_cases",
        "avoid_use_cases",
        "conflict_rules",
    }

    for voice_id in QWEN3_TTS_INSTRUCT_SUPPORTED_VOICES:
        profile = voices[voice_id].get("voice_profile")
        assert profile, f"{voice_id} 缺少 voice_profile"
        assert required_profile_fields.issubset(profile), f"{voice_id} voice_profile 字段不完整"
        assert isinstance(profile["timbre_traits"], list) and profile["timbre_traits"]
        assert isinstance(profile["recommended_use_cases"], list) and profile["recommended_use_cases"]
        assert isinstance(profile["avoid_use_cases"], list)
        assert isinstance(profile["conflict_rules"], list)


def test_normalize_speaker_id_maps_legacy_qwen_and_cosyvoice_ids() -> None:
    assert normalize_speaker_id("Dylan") == "Ethan"
    assert normalize_speaker_id("Ryan") == "Neil"
    assert normalize_speaker_id("longxiaochun") == "Bellona"


def test_aliyun_qwen_normalization_uses_supported_instruct_voice() -> None:
    engine = _DummyQwenAliyunMixin()

    assert engine._normalize_speaker_id("Dylan", "qwen3-tts-instruct-flash") == "Ethan"
    assert engine._normalize_speaker_id("male_narrator", "qwen3-tts-instruct-flash") == "Neil"
    assert engine._normalize_speaker_id("female_villain_cold", "qwen3-tts-instruct-flash") == "Bellona"


def test_mimo_preset_voice_catalog_uses_official_voice_ids() -> None:
    catalog = load_voice_catalog_for_model(MIMO_V25_TTS_MODEL)
    voice_ids = {voice["id"] for voice in catalog["voices"]}

    assert catalog["meta"]["model"] == MIMO_V25_TTS_MODEL
    assert catalog["meta"]["voice_count"] == 9
    assert voice_ids == {
        "mimo_default",
        "冰糖",
        "茉莉",
        "苏打",
        "白桦",
        "Mia",
        "Chloe",
        "Milo",
        "Dean",
    }
    assert "male-qn-qingse" not in voice_ids
    assert catalog["voices_by_id"]["mimo_default"]["description"].startswith("因部署集群而异")
