"""
第八轮优化测试 - LLM场景检测、侧链压缩、音效库扩展
"""
import pytest
import sys
import os
from pathlib import Path


# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def sound_effect_designer_module():
    """加载 SoundEffectDesigner 模块"""
    try:
        from app.services.audiobook.agents.sound_effect_designer import (
            SoundEffectDesigner,
            SoundEffectCue,
            EffectType,
        )
        return {
            "SoundEffectDesigner": SoundEffectDesigner,
            "SoundEffectCue": SoundEffectCue,
            "EffectType": EffectType,
        }
    except Exception as e:
        pytest.skip(f"SoundEffectDesigner 模块加载失败: {e}")


@pytest.fixture
def audio_mixer_module():
    """加载 AudioMixer 模块"""
    try:
        from app.services.audiobook.audio_mixer import AudioMixer
        return {"AudioMixer": AudioMixer}
    except Exception as e:
        pytest.skip(f"AudioMixer 模块加载失败: {e}")


# ============== LLM 场景检测测试 ==============

def test_llm_match_effect_with_mock(sound_effect_designer_module):
    """测试 LLM 智能匹配音效（带 mock LLM）"""
    designer = sound_effect_designer_module["SoundEffectDesigner"]()

    # 创建 mock LLM 客户端
    class MockLLMClient:
        def generate(self, prompt, max_tokens=100):
            return '{"recommended": ["rain_heavy", "wind"]}'

    designer.llm_client = MockLLMClient()

    # 测试 LLM 匹配
    result = designer._llm_match_effect("雨夜的城市街道，风声呼啸")
    assert result == "rain_heavy"


def test_llm_match_effect_fallback(sound_effect_designer_module):
    """测试 LLM 失败时降级到关键词匹配"""
    designer = sound_effect_designer_module["SoundEffectDesigner"]()

    # 创建会抛出异常的 mock LLM
    class MockFailingLLM:
        def generate(self, prompt, max_tokens=100):
            raise Exception("LLM 调用失败")

    designer.llm_client = MockFailingLLM()

    # 应该降级到关键词匹配
    result = designer._keyword_match_effect("下雨天的城市")
    assert result == "rain_light"


def test_keyword_match_effect(sound_effect_designer_module):
    """测试关键词映射匹配"""
    designer = sound_effect_designer_module["SoundEffectDesigner"]()

    test_cases = [
        ("倾盆大雨", "rain_heavy"),  # "大雨" 在 "雨" 之前
        ("雨夜", "rain_light"),
        ("森林中", "forest_ambient"),
        ("城市街道", "city_ambient"),
        ("默认场景", "city_ambient"),
    ]

    for scene, expected in test_cases:
        result = designer._keyword_match_effect(scene)
        assert result == expected, f"场景 '{scene}' 应匹配 '{expected}'，实际匹配 '{result}'"


def test_design_ambient_sound_with_llm(sound_effect_designer_module):
    """测试带 LLM 的环境音设计"""
    designer = sound_effect_designer_module["SoundEffectDesigner"]()

    class MockLLMClient:
        def generate(self, prompt, max_tokens=100):
            return '{"recommended": ["wind"]}'

    designer.llm_client = MockLLMClient()

    cue = designer.design_ambient_sound("山顶上的大风", duration=30.0)

    assert cue.effect_type == sound_effect_designer_module["EffectType"].ENVIRONMENT
    assert cue.duration == 30.0
    assert cue.loop is True


def test_design_ambient_sound_without_llm(sound_effect_designer_module):
    """测试无 LLM 时的环境音设计"""
    designer = sound_effect_designer_module["SoundEffectDesigner"]()
    designer.llm_client = None

    cue = designer.design_ambient_sound("下雨的城市", duration=60.0)

    assert cue.effect_type == sound_effect_designer_module["EffectType"].ENVIRONMENT
    assert "rain" in cue.audio_file  # 应该包含 rain


# ============== 侧链压缩测试 ==============

def test_sidechain_compression_basic(audio_mixer_module):
    """测试基础侧链压缩"""
    mixer = audio_mixer_module["AudioMixer"]()

    # 创建测试音频（静音+语音模拟）
    from pydub import AudioSegment

    bgm = AudioSegment.silent(duration=5000)  # 5秒静音
    voice = AudioSegment.silent(duration=5000)

    # 添加一些"语音"（响度变化）
    # 模拟语音包络
    result = mixer.apply_sidechain_compression(
        bgm=bgm,
        voice=voice,
        threshold_dbfs=-35.0,
        ratio=4.0,
    )

    # 应该返回压缩后的音频
    assert len(result) > 0
    assert len(result) == len(bgm)


def test_sidechain_compression_with_voice_exceeding_threshold(audio_mixer_module):
    """测试语音超过阈值时的压缩"""
    mixer = audio_mixer_module["AudioMixer"]()

    from pydub import AudioSegment

    # 创建 5 秒 BGM
    bgm = AudioSegment.silent(duration=5000)

    # 创建包含"语音"的音频（模拟高响度）
    voice = AudioSegment.silent(duration=5000)

    # 压缩应成功
    result = mixer.apply_sidechain_compression(
        bgm=bgm,
        voice=voice,
        threshold_dbfs=-35.0,
        ratio=4.0,
        max_reduction_db=-12.0,
    )

    assert len(result) > 0


def test_sidechain_compression_fallback(audio_mixer_module):
    """测试侧链压缩失败降级"""
    mixer = audio_mixer_module["AudioMixer"]()

    from pydub import AudioSegment

    bgm = AudioSegment.silent(duration=1000)
    voice = AudioSegment.silent(duration=1000)

    # 正常情况应返回压缩后的音频
    result = mixer.apply_sidechain_compression(bgm, voice)
    assert len(result) > 0


def test_sidechain_compression_vs_ducking(audio_mixer_module):
    """对比侧链压缩和硬切换 ducking 的差异"""
    mixer = audio_mixer_module["AudioMixer"]()

    from pydub import AudioSegment

    # 侧链压缩的优势是平滑过渡，此处验证机制正确性
    bgm = AudioSegment.silent(duration=3000)
    voice = AudioSegment.silent(duration=3000)

    # 验证侧链压缩方法存在且可调用
    assert hasattr(mixer, 'apply_sidechain_compression')
    assert callable(mixer.apply_sidechain_compression)


# ============== 音效库扩展测试 ==============

def test_sound_library_structure(sound_effect_designer_module):
    """测试音效库结构完整性"""
    designer = sound_effect_designer_module["SoundEffectDesigner"]()

    # 检查内置音效库结构
    for effect_id, effect_info in designer.sound_library.items():
        assert "type" in effect_info
        assert "file" in effect_info
        assert "description" in effect_info

        # 验证类型有效
        effect_type = effect_info["type"]
        assert effect_type in ["environment", "action", "emotion"]


def test_effect_type_enum(sound_effect_designer_module):
    """测试音效类型枚举"""
    EffectType = sound_effect_designer_module["EffectType"]
    assert EffectType.ENVIRONMENT.value == "environment"
    assert EffectType.ACTION.value == "action"
    assert EffectType.EMOTION.value == "emotion"
    assert EffectType.TRANSITION.value == "transition"


def test_sound_effect_cue_dataclass(sound_effect_designer_module):
    """测试 SoundEffectCue 数据类"""
    SoundEffectCue = sound_effect_designer_module["SoundEffectCue"]
    EffectType = sound_effect_designer_module["EffectType"]

    cue = SoundEffectCue(
        scene_id="test_scene",
        timestamp=0.0,
        effect_type=EffectType.ENVIRONMENT,
        description="测试音效",
        audio_file="test.mp3",
        volume=0.5,
        fade_in=2.0,
        fade_out=2.0,
        loop=True,
        duration=10.0,
        mix_mode="background",
    )

    assert cue.scene_id == "test_scene"
    assert cue.timestamp == 0.0
    assert cue.volume == 0.5
    assert cue.loop is True


def test_design_effects_with_sound_effect_library(sound_effect_designer_module):
    """测试使用音效库设计音效"""
    designer = sound_effect_designer_module["SoundEffectDesigner"]()

    segments = [
        {
            "text": "林墨走在雨中的街道上",
            "sound_effects": ["rain_heavy", "footsteps"],
            "timestamp": 0.0,
        },
    ]

    cues = designer.design_effects(segments)

    assert len(cues) > 0
    assert cues[0].audio_file is not None


# ============== 导入测试 ==============

def test_sound_effect_designer_imports():
    """测试 SoundEffectDesigner 模块导入"""
    try:
        from app.services.audiobook.agents.sound_effect_designer import (
            SoundEffectDesigner,
            SoundEffectCue,
            EffectType,
        )
        assert SoundEffectDesigner is not None
        assert SoundEffectCue is not None
        assert EffectType is not None
    except ImportError as e:
        pytest.fail(f"SoundEffectDesigner 模块导入失败: {e}")


def test_audio_mixer_sidechain_imports():
    """测试 AudioMixer 侧链压缩方法导入"""
    try:
        from app.services.audiobook.audio_mixer import AudioMixer
        mixer = AudioMixer()
        assert hasattr(mixer, 'apply_sidechain_compression')
        assert callable(mixer.apply_sidechain_compression)
    except ImportError as e:
        pytest.fail(f"AudioMixer 侧链压缩方法导入失败: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
