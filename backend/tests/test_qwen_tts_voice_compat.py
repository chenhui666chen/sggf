"""Qwen-Audio 3.1 音色目录与历史 speaker 折叠的兼容性契约。

Qwen3-TTS 已物理退役，音色空间整体换成带 `_v3.1` 后缀的官方系统音色；
本文件锁住三件事：目录事实、旧 speaker 写法如何折叠到新音色、以及目录里
不该出现的旧写法不会被静默当成可用音色。MiMo 预设音色表同属"目录事实"，一并留在此处。
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from app.services.audiobook.constants import normalize_speaker_id
from app.services.audiobook.tts_model_ids import (
    MIMO_V25_TTS_MODEL,
    QWEN_AUDIO_31_TTS_FLASH_MODEL,
    SEED_TTS_20_EXPRESSIVE_MODEL,
    STEPAUDIO_3_TTS_MODEL,
)
from app.services.audiobook.voice_catalog import get_voice_entry, load_voice_catalog_for_model

QWEN_AUDIO_31_VOICE_COUNT = 68


def test_qwen_audio_31_catalog_contains_only_official_v31_voices() -> None:
    catalog = load_voice_catalog_for_model(QWEN_AUDIO_31_TTS_FLASH_MODEL)
    voice_ids = {voice["id"] for voice in catalog["voices"]}

    assert catalog["meta"]["model"] == QWEN_AUDIO_31_TTS_FLASH_MODEL
    assert catalog["meta"]["voice_count"] == len(voice_ids) == QWEN_AUDIO_31_VOICE_COUNT
    assert all(voice_id.endswith("_v3.1") for voice_id in voice_ids)
    assert "qwen-audio-tts-voice-list" in catalog["meta"]["source"]


def test_qwen_audio_31_catalog_keeps_official_voice_metadata() -> None:
    voices = load_voice_catalog_for_model(QWEN_AUDIO_31_TTS_FLASH_MODEL)["voices_by_id"]

    assert voices["longsanshu_v3.1"]["gender"] == "male"
    assert voices["longsanshu_v3.1"]["category"] == "narrator"
    assert voices["longanhuan_v3.1"]["id"] == "longanhuan_v3.1"
    assert voices["longanya_v3.1"]["label"].startswith("龙安雅")


def test_retired_qwen3_voice_ids_are_absent_from_the_active_catalog() -> None:
    catalog = load_voice_catalog_for_model(QWEN_AUDIO_31_TTS_FLASH_MODEL)

    assert "Cherry" not in catalog["voices_by_id"]
    assert "Neil" not in catalog["voices_by_id"]
    # 目录查不到才由调用方显式重置，而不是静默发一个错误音色
    assert get_voice_entry("Neil", model=QWEN_AUDIO_31_TTS_FLASH_MODEL) is None


def test_normalize_speaker_id_folds_legacy_suffixes_to_v31() -> None:
    assert normalize_speaker_id("longanya") == "longanya_v3.1"
    assert normalize_speaker_id("longanya_v3") == "longanya_v3.1"
    assert normalize_speaker_id("longanya_v3.5") == "longanya_v3.1"
    assert normalize_speaker_id("longanya_v3_plus") == "longanya_v3.1"
    assert normalize_speaker_id("  longanyang  ") == "longanyang_v3.1"
    # 已是现行写法：原样返回，不重复加后缀
    assert normalize_speaker_id("longsanshu_v3.1") == "longsanshu_v3.1"


def test_normalize_speaker_id_leaves_unmatched_names_untouched() -> None:
    # 旧 Qwen3 音色名、CosyVoice 专属声线、预设别名都不在 3.1 目录里：必须原样返回，
    # 由上层按目录校验重置，而不是折叠到一个不相干的音色上。
    assert normalize_speaker_id("Cherry") == "Cherry"
    assert normalize_speaker_id("longxiaochun") == "longxiaochun"
    assert normalize_speaker_id("male_narrator") == "male_narrator"
    assert normalize_speaker_id("") == ""


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


def test_match_voice_by_traits_only_returns_presets_resolvable_in_catalog() -> None:
    """音色匹配的任何返回值都必须能在预设表里取到配置，且声线在现行目录内。

    退役旧模型只换音色空间、不改匹配逻辑时最容易出现"返回一个历史声线名"的哑雷：
    匹配函数返回的字符串会被 assign_voice 直接当作 PRESET_VOICES 的键取用，
    键不存在就是 KeyError，测试若不覆盖反派分支就完全不会变红。
    """
    from app.services.audiobook.voice_manager import VoiceManager

    cases = [
        {"gender": "male", "age_group": "adult", "personality": "cold", "role_type": "反派"},
        {"gender": "female", "age_group": "young", "personality": "cruel", "role_type": "villain"},
        {"gender": "male", "age_group": "young", "personality": "calm", "role_type": ""},
        {"gender": "female", "age_group": "elder", "personality": "gentle", "role_type": ""},
        {"gender": "other", "age_group": "adult", "personality": "lively", "role_type": ""},
    ]

    for traits in cases:
        manager = VoiceManager()
        voice_id = manager._match_voice_by_traits(dict(traits))
        voice_config = manager.PRESET_VOICES[voice_id]
        speaker = normalize_speaker_id(voice_config["tts_speaker_id"])

        assert get_voice_entry(speaker, model=QWEN_AUDIO_31_TTS_FLASH_MODEL) is not None, traits
        assert voice_config.get("legacy_alias_of") or voice_id.endswith("_v3.1"), traits


def test_villain_characters_are_locked_to_active_tension_voices() -> None:
    from app.services.audiobook.voice_manager import VoiceManager

    male = VoiceManager()._match_voice_by_traits(
        {"gender": "male", "age_group": "adult", "personality": "sinister", "role_type": "反派"}
    )
    female = VoiceManager()._match_voice_by_traits(
        {"gender": "female", "age_group": "adult", "personality": "domineering", "role_type": "villain"}
    )

    # 高张力反派声线来自 3.1 目录（与 LEGACY_PRESET_ALIASES 的反派定位一致），
    # 不再是已退役模型里自带 angry/disgusted 张力的 Ethan/Bunny。
    assert male == "huozhuoshi_v3.1"
    assert female == "longanyuanfei_v3.1"


def test_voice_manager_last_resort_preset_is_still_available() -> None:
    from app.services.audiobook.voice_manager import VoiceManager

    voice_config = VoiceManager.PRESET_VOICES["male_narrator"]

    assert voice_config["tts_speaker_id"] == "longsanshu_v3.1"
    assert normalize_speaker_id(voice_config["tts_speaker_id"]) == "longsanshu_v3.1"


def test_every_engine_default_voice_is_in_its_own_active_catalog() -> None:
    """引擎各模型调用点的兜底默认音色，必须能在该模型自己的目录里查到。

    片段重生成等接口在未选音色时不再编音色名，而是下发空 speaker，
    由 `_aliyun_mixin` 各模型载荷组装点兜自己的默认；门禁只扫模型 ID 不扫音色 ID，
    所以"默认音色是否在目录里"只能靠目录校验固定。历史写法用退役模型的 "Neil"
    兜底时，现役上游判它无效 voice 且本地无报错，只表现为"这句试听没有声音"。
    """
    from app.services.audiobook.tts_engine_pkg._aliyun_mixin import (
        QWEN_AUDIO_31_DEFAULT_VOICE,
        SEED_TTS_DEFAULT_VOICE,
        STEPAUDIO_TTS_DEFAULT_VOICE,
    )

    engine_defaults = {
        QWEN_AUDIO_31_TTS_FLASH_MODEL: QWEN_AUDIO_31_DEFAULT_VOICE,
        STEPAUDIO_3_TTS_MODEL: STEPAUDIO_TTS_DEFAULT_VOICE,
        SEED_TTS_20_EXPRESSIVE_MODEL: SEED_TTS_DEFAULT_VOICE,
        MIMO_V25_TTS_MODEL: "mimo_default",
    }

    for model, default_voice_id in engine_defaults.items():
        assert (
            get_voice_entry(default_voice_id, model=model) is not None
        ), f"模型 {model} 的兜底音色 {default_voice_id} 不在自己的目录里"
