"""
声音类型系统测试
"""
import pytest
import sys
import os
import importlib.util
from pathlib import Path


@pytest.fixture
def voice_types_module():
    """加载 voice_types 模块"""
    backend_services_dir = Path(__file__).parent.parent / "app" / "services" / "audiobook"
    spec = importlib.util.spec_from_file_location(
        "voice_types", backend_services_dir / "voice_types.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_voice_type_enum_values(voice_types_module):
    """测试声音类型枚举值"""
    assert hasattr(voice_types_module, "VoiceType")
    
    # 检查所有预设都存在
    for voice_type_key in voice_types_module.VOICE_TYPE_PRESETS:
        assert hasattr(voice_types_module.VoiceType, voice_type_key.upper())


def test_personality_type_enum_values(voice_types_module):
    """测试性格类型枚举值"""
    assert hasattr(voice_types_module, "PersonalityType")
    assert voice_types_module.PersonalityType.INTROVERT.value == "introvert"
    assert voice_types_module.PersonalityType.EXTROVERT.value == "extrovert"


def test_emotion_tendency_enum_values(voice_types_module):
    """测试情感倾向枚举值"""
    assert hasattr(voice_types_module, "EmotionTendency")
    assert voice_types_module.EmotionTendency.POSITIVE.value == "positive"
    assert voice_types_module.EmotionTendency.NEGATIVE.value == "negative"


def test_get_voice_type_preset(voice_types_module):
    """测试获取声音类型预设"""
    preset = voice_types_module.get_voice_type_preset("majestic")
    assert preset is not None
    assert preset.voice_type == "majestic"
    assert preset.name == "威严"
    assert preset.speed_modifier == 0.85


def test_get_voice_type_preset_not_found(voice_types_module):
    """测试获取不存在的声音类型"""
    preset = voice_types_module.get_voice_type_preset("nonexistent")
    assert preset is None


def test_get_all_voice_types(voice_types_module):
    """测试获取所有声音类型列表"""
    all_types = voice_types_module.get_all_voice_types()
    assert len(all_types) == 10
    
    # 检查返回格式
    for vt in all_types:
        assert "voice_type" in vt
        assert "name" in vt
        assert "description" in vt


def test_recommend_voice_type_by_personality(voice_types_module):
    """测试根据性格推荐声音类型"""
    recommended = voice_types_module.recommend_voice_type(personality="calm")
    assert len(recommended) > 0
    
    # 冷静性格应该推荐某些类型
    assert any(vt in recommended for vt in ["majestic", "mysterious", "scholarly", "cold"])


def test_recommend_voice_type_by_gender(voice_types_module):
    """测试根据性别推荐声音类型"""
    recommended = voice_types_module.recommend_voice_type(gender="female")
    assert len(recommended) > 0
    
    # 女性应该推荐适合女性的类型
    assert "gentle" in recommended[:3]


def test_recommend_voice_type_combined(voice_types_module):
    """测试组合推荐"""
    recommended = voice_types_module.recommend_voice_type(
        personality="extrovert",
        gender="female",
        age_range="teen",
    )
    assert len(recommended) > 0
    
    # 应该推荐活泼类型
    assert "lively" in recommended[:2]


def test_apply_voice_type_to_tts_params_basic(voice_types_module):
    """测试应用声音类型到 TTS 参数（基础）"""
    base_params = {}
    enhanced = voice_types_module.apply_voice_type_to_tts_params("majestic", base_params)
    
    assert enhanced["speed"] == 0.85
    assert enhanced["pitch"] == -2
    assert enhanced["emotion"] == "calm"


def test_apply_voice_type_to_tts_params_with_existing(voice_types_module):
    """测试应用声音类型到已有 TTS 参数"""
    base_params = {
        "speed": 1.0,
        "pitch": 0,
        "volume": 50,
        "emotion": "happy",
    }
    enhanced = voice_types_module.apply_voice_type_to_tts_params("lively", base_params)
    
    # 应该叠加调整
    assert enhanced["speed"] == pytest.approx(1.0 * 1.15)  # 1.0 * 1.15
    assert enhanced["pitch"] == 0 + 2  # 0 + 2


def test_apply_voice_type_nonexistent(voice_types_module):
    """测试应用不存在的声音类型"""
    base_params = {"speed": 1.0}
    enhanced = voice_types_module.apply_voice_type_to_tts_params("nonexistent", base_params)
    
    # 应该返回原始参数
    assert enhanced == base_params


def test_create_character_voice_profile_with_type(voice_types_module):
    """测试创建角色声音配置（带类型）"""
    profile = voice_types_module.create_character_voice_profile(
        character_name="主角",
        voice_id="longxiaochun",
        voice_type="lively",
        personality="extrovert",
    )
    
    assert profile["character_name"] == "主角"
    assert profile["voice_id"] == "longxiaochun"
    assert profile["voice_type"] == "lively"
    assert profile["personality"] == "extrovert"
    assert "speed" in profile
    assert "pitch" in profile


def test_create_character_voice_profile_with_custom(voice_types_module):
    """测试创建角色声音配置（带自定义设置）"""
    profile = voice_types_module.create_character_voice_profile(
        character_name="配角",
        voice_id="longxiaochun",
        voice_type="gentle",
        custom_settings={"custom_field": "custom_value"},
    )
    
    assert profile["custom_field"] == "custom_value"


def test_voice_type_preset_structure(voice_types_module):
    """测试声音类型预设结构完整性"""
    for voice_type, preset in voice_types_module.VOICE_TYPE_PRESETS.items():
        assert preset.voice_type == voice_type
        assert preset.name is not None
        assert preset.description is not None
        assert 0.5 <= preset.speed_modifier <= 1.5  # 语速应在合理范围
        assert -5 <= preset.pitch_modifier <= 5  # 音调应在合理范围
        assert 0 <= preset.emotion_intensity <= 1  # 情感强度应在 0-1 范围
        assert preset.emotion_tendency in ["positive", "negative", "neutral", "variable"]


def test_voice_type_compatible_personalities(voice_types_module):
    """测试声音类型与性格的兼容性"""
    for voice_type, preset in voice_types_module.VOICE_TYPE_PRESETS.items():
        # 每个类型应有至少 1 个兼容性格
        assert len(preset.compatible_personalities) >= 1
        
        # 检查性格值是否在枚举中
        for personality in preset.compatible_personalities:
            assert hasattr(voice_types_module.PersonalityType, personality.upper())


def test_voice_type_suitable_scenarios(voice_types_module):
    """测试声音类型的适用场景"""
    for voice_type, preset in voice_types_module.VOICE_TYPE_PRESETS.items():
        # 每个类型应有至少 1 个适用场景
        assert len(preset.suitable_scenarios) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
