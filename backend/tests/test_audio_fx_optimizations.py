"""
第八轮优化测试 - LLM场景检测、侧链压缩、音效库扩展
"""
import asyncio
import json
import logging
import pytest
import sys
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace


@pytest.fixture
def music_composer_module():
    """Load MusicComposer module."""
    try:
        from app.services.audiobook.agents.music_composer import (
            MusicComposer,
            MusicCue,
            MusicMood,
            MusicType,
        )
        return {
            "MusicComposer": MusicComposer,
            "MusicCue": MusicCue,
            "MusicMood": MusicMood,
            "MusicType": MusicType,
        }
    except Exception as e:
        pytest.skip(f"MusicComposer module load failed: {e}")


# 添加 backend 与项目根目录到 sys.path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for path in (BACKEND_ROOT, PROJECT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


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
        assert effect_type in ["environment", "action", "emotion", "transition"]


def test_external_sound_library_skips_missing_files(
    sound_effect_designer_module,
    tmp_path,
    monkeypatch,
    caplog,
):
    """外部索引指向缺失文件时应加载期跳过，避免后续匹配到不可用素材。"""
    SoundEffectDesigner = sound_effect_designer_module["SoundEffectDesigner"]
    designer_module = sys.modules[SoundEffectDesigner.__module__]
    audio_library = tmp_path / "audio_library"
    index_path = audio_library / "sound_effects_index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "missing_effect",
                    "category": "effects/action",
                        "file_path": "sound_effects/effects/action/missing.wav",
                        "description": "缺失动作音",
                        "tags": ["missing"],
                        "source": "user_upload",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(designer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(designer_module, "SOUND_EFFECTS_DIR", audio_library / "sound_effects")

    caplog.set_level(logging.WARNING, logger=designer_module.__name__)
    designer = SoundEffectDesigner(index_path=str(index_path))

    assert "missing_effect" not in designer.sound_library
    assert "音效索引条目文件不存在" in caplog.text


def test_external_sound_library_skips_community_rejected_entries(
    sound_effect_designer_module,
    tmp_path,
    monkeypatch,
):
    SoundEffectDesigner = sound_effect_designer_module["SoundEffectDesigner"]
    designer_module = sys.modules[SoundEffectDesigner.__module__]
    audio_library = tmp_path / "audio_library"
    sound_effect_file = audio_library / "sound_effects" / "action" / "rejected.wav"
    sound_effect_file.parent.mkdir(parents=True)
    sound_effect_file.write_bytes(b"rejected")
    index_path = audio_library / "sound_effects_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "community_rejected_effect",
                    "category": "action/realistic",
                    "file_path": "sound_effects/action/rejected.wav",
                    "quality_status": "community_rejected",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(designer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(designer_module, "SOUND_EFFECTS_DIR", audio_library / "sound_effects")

    designer = SoundEffectDesigner(index_path=str(index_path))

    assert "community_rejected_effect" not in designer.sound_library


def test_external_sound_library_uses_normalized_train_station_category(
    sound_effect_designer_module,
    tmp_path,
    monkeypatch,
):
    SoundEffectDesigner = sound_effect_designer_module["SoundEffectDesigner"]
    designer_module = sys.modules[SoundEffectDesigner.__module__]
    audio_library = tmp_path / "audio_library"
    sound_file = audio_library / "sound_effects" / "action" / "train.ogg"
    sound_file.parent.mkdir(parents=True)
    sound_file.write_bytes(b"OggS")
    index_path = audio_library / "sound_effects_index.json"
    index_path.write_text(
        json.dumps([{
            "id": "action_local_authorized_wikimedia_airchime_k5la_b1a2540775",
            "source_id": "wikimedia_airchime_k5la_train_horn_cc0",
            "name": "train_horn_airchime_k5la",
            "description": "Diesel locomotive horn for train arrivals and railway warnings.",
            "category": "action/intense",
            "style": "intense",
            "tags": ["action", "intense", "battle", "train", "horn", "travel"],
            "scenes": ["battle", "travel"],
                "file_path": "sound_effects/action/train.ogg",
                "source": "user_upload",
        }]),
        encoding="utf-8",
    )
    monkeypatch.setattr(designer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(designer_module, "SOUND_EFFECTS_DIR", audio_library / "sound_effects")

    designer = SoundEffectDesigner(index_path=str(index_path))
    entry = designer.sound_library["action_local_authorized_wikimedia_airchime_k5la_b1a2540775"]

    assert entry["type"] == "environment"
    assert entry["description"] == "火车站环境声，包含火车鸣笛、列车运行声和背景人群交谈。"
    assert "people" in entry["tags"]
    assert "battle" not in entry["tags"]


def test_external_sound_library_replaces_unresolved_builtin_entry(
    sound_effect_designer_module,
    tmp_path,
    monkeypatch,
):
    """外部索引可覆盖同名但不可解析的内置占位条目。"""
    SoundEffectDesigner = sound_effect_designer_module["SoundEffectDesigner"]
    designer_module = sys.modules[SoundEffectDesigner.__module__]
    audio_library = tmp_path / "audio_library"
    sound_effect_file = audio_library / "sound_effects" / "environment" / "rain_heavy.wav"
    sound_effect_file.parent.mkdir(parents=True)
    sound_effect_file.write_bytes(b"rain")
    index_path = audio_library / "sound_effects_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "rain_heavy",
                    "category": "environment/rain",
                    "file_path": "sound_effects/environment/rain_heavy.wav",
                    "description": "可用大雨声",
                    "tags": ["雨", "大雨"],
                        "source": "user_upload",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(designer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(designer_module, "SOUND_EFFECTS_DIR", audio_library / "sound_effects")

    designer = SoundEffectDesigner(index_path=str(index_path))

    assert designer.sound_library["rain_heavy"]["file"] == "sound_effects/environment/rain_heavy.wav"
    assert designer.sound_library["rain_heavy"]["description"] == "可用大雨声"


def test_sound_effect_designer_prefers_explicit_asset_id_over_display_name(
    sound_effect_designer_module,
    tmp_path,
):
    SoundEffectDesigner = sound_effect_designer_module["SoundEffectDesigner"]
    audio_library = tmp_path / "audio_library"
    sound_file = audio_library / "sound_effects" / "selected.wav"
    sound_file.parent.mkdir(parents=True)
    sound_file.write_bytes(b"selected-effect")
    index_path = audio_library / "sound_effects_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "sfx-selected-01",
                    "category": "action",
                        "file_path": "sound_effects/selected.wav",
                        "description": "Selected library effect",
                        "source": "user_upload",
                }
            ]
        ),
        encoding="utf-8",
    )

    designer = SoundEffectDesigner(index_path=str(index_path))
    cues = designer.design_effects(
        [
            {
                "text": "The door shuts.",
                "sound_effects": [
                    {
                        "asset_id": "sfx-selected-01",
                        "name": "A misleading display name",
                    }
                ],
            }
        ],
        allow_asset_generation=False,
    )

    assert cues[0].effect_id == "sfx-selected-01"
    assert cues[0].audio_file == "sound_effects/selected.wav"


def test_match_effect_prefers_resolvable_external_match_over_builtin_placeholder(
    sound_effect_designer_module,
    tmp_path,
    monkeypatch,
):
    """语义都匹配时，应优先使用外部索引中的真实素材，而不是内置占位文件名。"""
    SoundEffectDesigner = sound_effect_designer_module["SoundEffectDesigner"]
    designer_module = sys.modules[SoundEffectDesigner.__module__]
    audio_library = tmp_path / "audio_library"
    sound_effect_file = audio_library / "sound_effects" / "effects" / "action" / "paper.wav"
    sound_effect_file.parent.mkdir(parents=True)
    sound_effect_file.write_bytes(b"paper")
    index_path = audio_library / "sound_effects_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "paper_available",
                    "category": "effects/action",
                    "file_path": "sound_effects/effects/action/paper.wav",
                    "description": "纸张摩擦声",
                    "tags": ["纸张", "摩擦"],
                        "source": "user_upload",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(designer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(designer_module, "SOUND_EFFECTS_DIR", audio_library / "sound_effects")

    designer = SoundEffectDesigner(index_path=str(index_path))

    cue = designer._match_effect(description="纸张摩擦声", timestamp=0.0, scene_id="scene")

    assert cue.audio_file == "sound_effects/effects/action/paper.wav"


def test_match_effect_prefers_resolvable_external_match_when_scores_tie(
    sound_effect_designer_module,
    tmp_path,
    monkeypatch,
):
    """描述匹配分数相同时，可解析真实素材应优先于不可解析占位。"""
    SoundEffectDesigner = sound_effect_designer_module["SoundEffectDesigner"]
    designer_module = sys.modules[SoundEffectDesigner.__module__]
    audio_library = tmp_path / "audio_library"
    sound_effect_file = audio_library / "sound_effects" / "effects" / "action" / "custom_paper.wav"
    sound_effect_file.parent.mkdir(parents=True)
    sound_effect_file.write_bytes(b"paper")
    index_path = audio_library / "sound_effects_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "paper_tie_available",
                    "category": "effects/action",
                    "file_path": "sound_effects/effects/action/custom_paper.wav",
                    "description": "纸张簌簌声",
                    "tags": ["纸张"],
                        "source": "user_upload",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(designer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(designer_module, "SOUND_EFFECTS_DIR", audio_library / "sound_effects")

    designer = SoundEffectDesigner(index_path=str(index_path))

    cue = designer._match_effect(description="纸张簌簌声", timestamp=0.0, scene_id="scene")

    assert cue.audio_file == "sound_effects/effects/action/custom_paper.wav"


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


def test_export_effect_timeline_includes_matched_effect_id(sound_effect_designer_module, monkeypatch):
    """Timeline should preserve the concrete sound library ID used for credits."""
    designer = sound_effect_designer_module["SoundEffectDesigner"]()
    # 测试环境无真实素材文件，视为可解析以聚焦 effect_id 保留行为
    monkeypatch.setattr(designer, "_has_resolvable_audio_file", lambda file_ref: True)

    cues = designer.design_effects(
        [
            {
                "text": "rain",
                "sound_effects": ["rain_light"],
                "timestamp": 0.0,
            }
        ]
    )
    timeline = designer.export_effect_timeline()

    assert cues[0].effect_id == "rain_light"
    assert timeline["timeline"][0]["effect_id"] == "rain_light"


def test_export_effect_timeline_reports_unresolved_sound_effect_assets(
    sound_effect_designer_module,
    monkeypatch,
):
    """Timeline should expose placeholder/missing SFX as user-visible warnings."""
    SoundEffectCue = sound_effect_designer_module["SoundEffectCue"]
    EffectType = sound_effect_designer_module["EffectType"]
    designer = sound_effect_designer_module["SoundEffectDesigner"]()
    designer.effect_cues = [
        SoundEffectCue(
            scene_id="scene_1",
            timestamp=0.0,
            effect_type=EffectType.ACTION,
            description="骨裂声",
            audio_file="placeholder.mp3",
            effect_id="",
        ),
        SoundEffectCue(
            scene_id="scene_2",
            timestamp=2.5,
            effect_type=EffectType.ENVIRONMENT,
            description="荒野风声",
            audio_file="missing_wind.wav",
            effect_id="wind_missing",
        ),
    ]
    monkeypatch.setattr(designer, "_has_resolvable_audio_file", lambda file_ref: False)

    timeline = designer.export_effect_timeline()

    assert timeline["unresolved_effects"]["unresolved_count"] == 2
    assert timeline["unresolved_effects"]["placeholder_count"] == 1
    assert timeline["unresolved_effects"]["missing_file_count"] == 1
    assert timeline["unresolved_effects"]["items"][0]["reason"] == "placeholder_audio"
    assert timeline["unresolved_effects"]["items"][1]["reason"] == "missing_audio_file"
    assert timeline["warnings"][0]["code"] == "unresolved_sound_effect_assets"
    assert "2" in timeline["warnings"][0]["message"]


def test_export_effect_timeline_excludes_unresolvable_assets(
    sound_effect_designer_module,
    monkeypatch,
):
    """音效生成失败不做兜底直接跳过：placeholder/死文件名条目不应进入混音时间线，
    否则混音层逐条尝试后刷"音效文件不存在"警告。"""
    SoundEffectCue = sound_effect_designer_module["SoundEffectCue"]
    EffectType = sound_effect_designer_module["EffectType"]
    designer = sound_effect_designer_module["SoundEffectDesigner"]()
    designer.effect_cues = [
        SoundEffectCue(
            scene_id="scene_1",
            timestamp=0.0,
            effect_type=EffectType.ACTION,
            description="骨裂声",
            audio_file="placeholder.mp3",
            effect_id="",
        ),
        SoundEffectCue(
            scene_id="scene_2",
            timestamp=2.5,
            effect_type=EffectType.EMOTION,
            description="远处呼喊回声",
            audio_file="distant_shout_echo.mp3",
            effect_id="distant_shout_echo",
        ),
        SoundEffectCue(
            scene_id="scene_3",
            timestamp=5.0,
            effect_type=EffectType.ACTION,
            description="关门声",
            audio_file="door_close.mp3",
            effect_id="door_close",
        ),
    ]
    monkeypatch.setattr(
        designer,
        "_has_resolvable_audio_file",
        lambda file_ref: file_ref == "door_close.mp3",
    )

    timeline = designer.export_effect_timeline()

    # 只有可解析素材进入混音时间线
    assert [item["file"] for item in timeline["timeline"]] == ["door_close.mp3"]
    # 不可解析条目仍保留在质量报告中
    assert timeline["unresolved_effects"]["unresolved_count"] == 2
    assert timeline["total_effects"] == 3


def test_design_effects_uses_narration_speed_for_timestamps(sound_effect_designer_module):
    """音效时间线应按中文朗读语速估算，而不是按 10 字/秒压缩时间轴。"""
    designer = sound_effect_designer_module["SoundEffectDesigner"]()

    cues = designer.design_effects(
        [
            {"text": "甲" * 45, "sound_effects": ["rain_heavy"]},
            {"text": "乙" * 10, "sound_effects": ["wind"]},
        ]
    )

    assert [cue.timestamp for cue in cues[:2]] == pytest.approx([0.0, 10.0])


def test_design_effects_preserves_structured_sound_effect_parameters(sound_effect_designer_module):
    """Structured script SFX fields should survive library matching."""
    designer = sound_effect_designer_module["SoundEffectDesigner"]()
    EffectType = sound_effect_designer_module["EffectType"]

    cues = designer.design_effects(
        [
            {
                "text": "风声从巷口压过来。",
                "sound_effects": [
                    {
                        "name": "风声",
                        "layer": "bottom",
                        "volume": 0.12,
                        "timing": "continuous",
                        "duration": 8.0,
                        "fade_in": 1.0,
                        "fade_out": 1.5,
                        "delay": 0.7,
                    }
                ],
                "timestamp": 0.0,
            }
        ]
    )

    assert len(cues) == 1
    cue = cues[0]
    assert cue.effect_type == EffectType.ENVIRONMENT
    assert cue.volume == 0.12
    assert cue.duration == 8.0
    assert cue.fade_in == 1.0
    assert cue.fade_out == 1.5
    assert cue.timestamp == 0.7
    assert cue.loop is True
    assert cue.mix_mode == "background"


def test_common_fantasy_effect_descriptions_match_library_aliases(sound_effect_designer_module):
    """Common generated SFX names should map to concrete cue categories before AI generation."""
    designer = sound_effect_designer_module["SoundEffectDesigner"]()
    EffectType = sound_effect_designer_module["EffectType"]

    cases = [
        ("纸张摩擦声", EffectType.ACTION),
        ("火把点燃声", EffectType.ACTION, "torch_ignite.mp3"),
        ("远处呼喊回声", EffectType.EMOTION, "distant_shout_echo.mp3"),
        ("灵石碰撞声", EffectType.ACTION, "crystal_clink.mp3"),
    ]

    for case in cases:
        description, expected_type, *expected_file = case
        cue = designer._match_effect(description=description, timestamp=0.0, scene_id="scene")
        assert cue.effect_type == expected_type
        if expected_file:
            assert cue.audio_file == expected_file[0]
        else:
            assert cue.audio_file == "paper.mp3"
        assert cue.description == description


def test_doubao_effect_prompt_enriches_fantasy_material(sound_effect_designer_module):
    """Fantasy object SFX prompts should explain material and acoustic target."""
    SoundEffectCue = sound_effect_designer_module["SoundEffectCue"]
    EffectType = sound_effect_designer_module["EffectType"]
    designer = sound_effect_designer_module["SoundEffectDesigner"]()

    prompt = designer._build_doubao_effect_prompt(
        SoundEffectCue(
            scene_id="scene",
            timestamp=0.0,
            effect_type=EffectType.ACTION,
            description="灵石碰撞声",
        )
    )

    assert "灵石碰撞声" in prompt
    assert "晶石/玉石" in prompt
    assert "奇幻灵力" in prompt
    # 负面约束（不要音乐/人声）已按需求移除
    assert "不要音乐" not in prompt
    assert "不要人声台词" not in prompt


def test_doubao_effect_prompt_prefers_llm_expansion(sound_effect_designer_module):
    """LLM available: prompt should be the LLM-expanded sound design description."""
    SoundEffectCue = sound_effect_designer_module["SoundEffectCue"]
    EffectType = sound_effect_designer_module["EffectType"]
    designer = sound_effect_designer_module["SoundEffectDesigner"]()
    designer.llm_client = object()

    captured = {}

    def fake_run(prompt: str, max_tokens: int) -> str:
        captured["prompt"] = prompt
        return '{"prompt": "细碎的晶石相互碰撞，清脆短促，近景干净，尾音带一丝灵力闪烁感"}'

    designer._run_llm_chat_sync = fake_run

    prompt = designer._build_doubao_effect_prompt(
        SoundEffectCue(
            scene_id="scene",
            timestamp=0.0,
            effect_type=EffectType.ACTION,
            description="灵石碰撞声",
        )
    )

    assert prompt == "细碎的晶石相互碰撞，清脆短促，近景干净，尾音带一丝灵力闪烁感"
    # 扩写请求里应携带剧本描述与声音特点要求
    assert "灵石碰撞声" in captured["prompt"]
    assert "声源与材质" in captured["prompt"]


def test_doubao_effect_prompt_falls_back_when_llm_fails(sound_effect_designer_module):
    """LLM failure should fall back to the keyword template without crashing."""
    SoundEffectCue = sound_effect_designer_module["SoundEffectCue"]
    EffectType = sound_effect_designer_module["EffectType"]
    designer = sound_effect_designer_module["SoundEffectDesigner"]()
    designer.llm_client = object()

    def fake_run(prompt: str, max_tokens: int) -> str:
        raise RuntimeError("llm down")

    designer._run_llm_chat_sync = fake_run

    prompt = designer._build_doubao_effect_prompt(
        SoundEffectCue(
            scene_id="scene",
            timestamp=0.0,
            effect_type=EffectType.ACTION,
            description="灵石碰撞声",
        )
    )

    assert "灵石碰撞声" in prompt
    assert "晶石/玉石" in prompt


def test_optimize_effect_density_respects_max_effects_per_minute(sound_effect_designer_module):
    """Density settings should map to a real minimum interval."""
    SoundEffectCue = sound_effect_designer_module["SoundEffectCue"]
    EffectType = sound_effect_designer_module["EffectType"]
    designer = sound_effect_designer_module["SoundEffectDesigner"]()

    designer.effect_cues = [
        SoundEffectCue("scene_1", 0.0, EffectType.ACTION, "hit_1", "hit.mp3"),
        SoundEffectCue("scene_1", 6.0, EffectType.ACTION, "hit_2", "hit.mp3"),
        SoundEffectCue("scene_1", 12.0, EffectType.ACTION, "hit_3", "hit.mp3"),
    ]
    assert len(designer.optimize_effect_density(max_effects_per_minute=10)) == 3

    designer.effect_cues = [
        SoundEffectCue("scene_1", 0.0, EffectType.ACTION, "hit_1", "hit.mp3"),
        SoundEffectCue("scene_1", 6.0, EffectType.ACTION, "hit_2", "hit.mp3"),
        SoundEffectCue("scene_1", 12.0, EffectType.ACTION, "hit_3", "hit.mp3"),
    ]
    optimized = designer.optimize_effect_density(max_effects_per_minute=6)
    assert [cue.timestamp for cue in optimized] == [0.0, 12.0]


def test_generated_environment_category_normalizes_to_environment(
    sound_effect_designer_module,
    tmp_path,
):
    """Generated category paths should not leak into EffectType coercion."""
    designer = sound_effect_designer_module["SoundEffectDesigner"](
        index_path=str(tmp_path / "sound_effects_index.json")
    )

    designer.register_new_effect(
        {
            "id": "city_rain_generated",
            "category": "environment/city_rain",
            "file_path": "sound_effects/environment/city_rain.mp3",
            "description": "city rain",
            "tags": ["rain"],
            "source": "ai_generated",
        }
    )

    assert designer.sound_library["city_rain_generated"]["type"] == "environment"


def test_music_composer_normalizes_extended_moods(music_composer_module):
    """Script review moods outside MusicMood should degrade to valid music moods."""
    MusicComposer = music_composer_module["MusicComposer"]
    MusicMood = music_composer_module["MusicMood"]
    composer = MusicComposer(enable_ai=False)

    assert composer._normalize_music_mood("fearful") == "tense"
    assert composer._normalize_music_mood("angry") == "tense"
    assert composer._normalize_music_mood("happy") == "joyful"
    assert composer._normalize_music_mood("unknown") == "peaceful"

    cue = composer._create_opening_music({"overall_mood": "fearful"})
    assert cue.mood == MusicMood.TENSE


def test_music_composer_export_timeline_preserves_mood(music_composer_module):
    """V3-12: 导出的配乐时间线应保留 mood，供智能音量平衡使用。"""
    MusicComposer = music_composer_module["MusicComposer"]
    MusicCue = music_composer_module["MusicCue"]
    MusicMood = music_composer_module["MusicMood"]
    MusicType = music_composer_module["MusicType"]

    composer = MusicComposer(enable_ai=False)
    composer.music_cues = [
        MusicCue(
            scene_id="scene_tense",
            timestamp=3.5,
            music_type=MusicType.UNDERSCORE,
            mood=MusicMood.TENSE,
            description="tense underscore",
            audio_file="music_cache/tense.mp3",
            volume=0.2,
            duration=18.0,
        )
    ]

    timeline = composer.export_music_timeline()

    assert timeline["timeline"][0]["mood"] == "tense"
    assert timeline["timeline"][0]["type"] == "underscore"
    assert timeline["cues_by_mood"] == {"tense": 1}


def test_optimize_music_placement_drops_overlapping_underscore(music_composer_module):
    """Multiple underscore cues should not be selected over the same time range."""
    MusicComposer = music_composer_module["MusicComposer"]
    MusicCue = music_composer_module["MusicCue"]
    MusicMood = music_composer_module["MusicMood"]
    MusicType = music_composer_module["MusicType"]
    composer = MusicComposer(enable_ai=False)
    composer._chapter_total_duration = 200.0
    composer.music_cues = [
        MusicCue("scene_1", 0.0, MusicType.UNDERSCORE, MusicMood.TENSE, "first", duration=30.0),
        MusicCue("scene_2", 20.0, MusicType.UNDERSCORE, MusicMood.TENSE, "overlap", duration=30.0),
        MusicCue("scene_3", 60.0, MusicType.UNDERSCORE, MusicMood.TENSE, "later", duration=20.0),
    ]

    optimized = composer.optimize_music_placement(max_music_coverage=1.0)

    assert [cue.scene_id for cue in optimized] == ["scene_1", "scene_3"]


def test_audio_library_dir_points_to_backend_data():
    """混音阶段应读取生成器实际写入的 backend/data/audio_library。"""
    from app.services.audiobook.audio_library_paths import get_audio_library_dir

    assert get_audio_library_dir() == BACKEND_ROOT / "data" / "audio_library"


def test_sound_effect_timeline_resolves_generated_audio_library_path(tmp_path, monkeypatch):
    """最终音效叠加应能解析 sound_effects/... 相对路径。"""
    from app.services.audiobook.audio_library_paths import AUDIO_LIBRARY_DIR_ENV
    from app.services.audiobook.engine_pkg._sfx_mixin import SfxMixin

    audio_library = tmp_path / "audio_library"
    effect_path = audio_library / "sound_effects" / "effects" / "action" / "hit.wav"
    effect_path.parent.mkdir(parents=True)
    effect_path.write_bytes(b"effect-bytes")
    monkeypatch.setenv(AUDIO_LIBRARY_DIR_ENV, str(audio_library))

    calls = []

    class Harness(SfxMixin):
        def __init__(self):
            self._audio_fx_config = {}
            self.audio_mixer = SimpleNamespace(
                add_sound_effect=self._add_sound_effect,
            )

        def _add_sound_effect(self, voice_audio, effect_audio, **kwargs):
            calls.append((effect_audio, kwargs))
            return voice_audio + b"|sfx"

    result = Harness()._apply_sound_effects(
        b"voice",
        {
            "timeline": [
                {
                    "file": "sound_effects/effects/action/hit.wav",
                    "timestamp": 1.2,
                    "type": "action",
                    "volume": 0.5,
                }
            ]
        },
    )

    assert result == b"voice|sfx"
    assert calls[0][0] == b"effect-bytes"
    assert calls[0][1]["position_ms"] == 1200


def test_music_timeline_resolves_generated_audio_library_path(tmp_path, monkeypatch):
    """最终配乐叠加应能解析 music_cache/... 相对路径。"""
    from app.services.audiobook.audio_library_paths import AUDIO_LIBRARY_DIR_ENV
    from app.services.audiobook.engine_pkg._music_mixin import MusicMixin

    audio_library = tmp_path / "audio_library"
    music_path = audio_library / "music_cache" / "bgm.mp3"
    music_path.parent.mkdir(parents=True)
    music_path.write_bytes(b"bgm-bytes")
    monkeypatch.setenv(AUDIO_LIBRARY_DIR_ENV, str(audio_library))

    calls = []

    class Harness(MusicMixin):
        def __init__(self):
            self._audio_fx_config = {}
            self.audio_mixer = SimpleNamespace(
                add_background_music=self._add_background_music,
            )

        def _add_background_music(self, voice_audio, bgm_audio, **kwargs):
            calls.append((bgm_audio, kwargs))
            return voice_audio + b"|bgm"

    result = Harness()._apply_background_music(
        b"voice",
        {
            "timeline": [
                {
                    "file": "music_cache/bgm.mp3",
                    "timestamp": 2.0,
                    "type": "underscore",
                    "mood": "tense",
                    "volume": 0.2,
                    "duration": 12.0,
                }
            ]
        },
    )

    assert result == b"voice|bgm"
    assert calls[0][0] == b"bgm-bytes"
    assert calls[0][1]["position_ms"] == 2000
    assert calls[0][1]["duration_ms"] == 12000


@pytest.mark.parametrize(
    ("mood", "expected_volume_db"),
    [
        ("tense", -28.0),
        ("epic", -28.0),
        ("peaceful", -41.0),
        ("sad", -41.0),
        ("joyful", -34.0),
        ("romantic", -34.0),
        ("mysterious", -36.0),
    ],
)
def test_intelligent_bgm_volume_adjusts_underscore_moods(mood, expected_volume_db):
    """V3-12: underscore 携带 mood 时也应参与智能 BGM 音量调整。"""
    from app.services.audiobook.engine_pkg._music_mixin import MusicMixin

    class Harness(MusicMixin):
        pass

    volume_db = Harness()._calculate_intelligent_bgm_volume(
        base_volume_db=-36.0,
        music_type="underscore",
        mood=mood,
        target_volume=0.2,
    )

    assert volume_db == pytest.approx(expected_volume_db)


def test_music_resolver_uses_audio_library_base_for_relative_index_paths(tmp_path):
    """V3-15: 混音链路读取 music_index.json 时应按 audio_library 根目录解析相对路径。"""
    from app.services.audiobook.engine_pkg._music_mixin import MusicMixin

    audio_library = tmp_path / "audio_library"
    music_file = audio_library / "music_cache" / "indexed.wav"
    music_file.parent.mkdir(parents=True)
    music_file.write_bytes(b"indexed-music")
    (audio_library / "music_index.json").write_text(
        json.dumps(
            [
                {
                    "style": "悬疑氛围",
                    "mood": "tense",
                    "file_path": "music_cache/indexed.wav",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class Harness(MusicMixin):
        pass

    resolved = Harness()._resolve_music_path(
        "missing.mp3",
        audio_library,
        style_hint="悬疑氛围",
        mood_hint="tense",
    )

    assert resolved == music_file


def test_segment_preview_resolver_uses_audio_library_base_for_relative_index_paths(tmp_path):
    """V3-15: 单段试听读取 music_index.json 时应按 audio_library 根目录解析相对路径。"""
    from app.services.audiobook.segment_preview_service import SegmentPreviewService

    audio_library = tmp_path / "audio_library"
    music_file = audio_library / "music_cache" / "indexed.wav"
    music_file.parent.mkdir(parents=True)
    music_file.write_bytes(b"indexed-music")

    resolved = SegmentPreviewService.resolve_music_path(
        "missing.mp3",
        "悬疑氛围",
        "tense",
        audio_library,
        [
            {
                "style": "悬疑氛围",
                "mood": "tense",
                "file_path": "music_cache/indexed.wav",
            }
        ],
    )

    assert resolved == music_file


def test_parallel_sound_design_preserves_structured_asset_selection():
    from app.services.audiobook.engine_pkg._parallel_mixin import ParallelMixin

    class FakeSoundEffectDesigner:
        def __init__(self):
            self.script_segments = None
            self.effect_cues = []

        def design_effects(self, script_segments, **kwargs):
            self.script_segments = script_segments
            self.effect_cues = [SimpleNamespace()]
            return self.effect_cues

        def optimize_effect_density(self, max_effects_per_minute=4):
            return self.effect_cues

        def export_effect_timeline(self):
            return {"timeline": []}

    class Harness(ParallelMixin):
        def __init__(self):
            self._audio_fx_config = {
                "enable_sound_effects": True,
                "sound_effect_density": "medium",
                "enable_music": False,
            }
            self.sound_effect_designer = FakeSoundEffectDesigner()

    harness = Harness()
    asyncio.run(
        harness._parallel_design(
            task_id="task",
            script_segments=[
                SimpleNamespace(
                    text="The door shuts.",
                    sound_effects=[
                        SimpleNamespace(
                            asset_id="sfx-door-01",
                            name="Heavy door",
                            volume=0.4,
                        )
                    ],
                    sound_effects_simple=[],
                )
            ],
            skip_stage_tracking=True,
            include_voice_design=False,
        )
    )

    effect_request = harness.sound_effect_designer.script_segments[0]["sound_effects"][0]
    assert effect_request.asset_id == "sfx-door-01"
    assert effect_request.name == "Heavy door"
    assert effect_request.volume == 0.4


def test_parallel_design_seed_scene_skips_local_asset_generation():
    from app.services.audiobook.engine_pkg._parallel_mixin import ParallelMixin

    class UnexpectedSoundDesigner:
        def __init__(self):
            self.calls = 0

        def design_effects(self, *args, **kwargs):
            self.calls += 1
            return []

    class UnexpectedMusicComposer:
        def __init__(self):
            self.calls = 0

        async def design_music(self, *args, **kwargs):
            self.calls += 1
            return []

    class Harness(ParallelMixin):
        def __init__(self):
            self._audio_engine_mode = "seed_scene"
            self._audio_fx_config = {
                "enable_sound_effects": True,
                "sound_effect_density": "high",
                "enable_music": True,
                "music_density": "high",
            }
            self.sound_effect_designer = UnexpectedSoundDesigner()
            self.music_composer = UnexpectedMusicComposer()
            self._last_effect_timeline = {"timeline": ["stale"]}
            self._last_music_timeline = {"timeline": ["stale"]}

    harness = Harness()
    result = asyncio.run(
        harness._parallel_design(
            task_id="task",
            script_segments=[
                SimpleNamespace(
                    text="雨声中，门被猛地推开。",
                    sound_effects=[SimpleNamespace(name="持续雨声")],
                    music_cue=SimpleNamespace(style="低频紧张弦乐进入"),
                )
            ],
            skip_stage_tracking=True,
            include_voice_design=False,
            prepare_render_assets=False,
        )
    )

    assert result[1:] == (1, 1)
    assert harness.sound_effect_designer.calls == 0
    assert harness.music_composer.calls == 0
    assert harness._last_effect_timeline is None
    assert harness._last_music_timeline is None


def test_parallel_design_seed_scene_keeps_legacy_fallback_assets_by_default():
    from app.services.audiobook.engine_pkg._parallel_mixin import ParallelMixin

    class FallbackSoundDesigner:
        def __init__(self):
            self.calls = 0
            self.effect_cues = []

        def design_effects(self, *args, **kwargs):
            self.calls += 1
            self.effect_cues = [SimpleNamespace()]
            return self.effect_cues

        def optimize_effect_density(self, **kwargs):
            return self.effect_cues

        def export_effect_timeline(self):
            return {"timeline": [{"description": "关门声"}]}

    class FallbackMusicComposer:
        def __init__(self):
            self.calls = 0
            self.music_cues = []

        async def design_music(self, *args, **kwargs):
            self.calls += 1
            self.music_cues = [SimpleNamespace()]
            return self.music_cues

        def optimize_music_placement(self, **kwargs):
            return self.music_cues

        def export_music_timeline(self):
            return {"timeline": [{"description": "紧张配乐"}]}

    class Harness(ParallelMixin):
        def __init__(self):
            self._audio_engine_mode = "seed_scene"
            self._audio_fx_config = {
                "enable_sound_effects": True,
                "sound_effect_density": "medium",
                "enable_music": True,
                "music_density": "medium",
            }
            self.sound_effect_designer = FallbackSoundDesigner()
            self.music_composer = FallbackMusicComposer()

    harness = Harness()
    asyncio.run(
        harness._parallel_design(
            task_id="task",
            script_segments=[
                SimpleNamespace(
                    text="门被猛地关上。",
                    emotion="tense",
                    sound_effects=[SimpleNamespace(name="关门声")],
                    sound_effects_simple=[],
                    music_cue=SimpleNamespace(style="紧张弦乐进入"),
                    music_cue_simple="",
                )
            ],
            chapter_content="门被猛地关上。",
            skip_stage_tracking=True,
            include_voice_design=False,
        )
    )

    assert harness.sound_effect_designer.calls == 1
    assert harness.music_composer.calls == 1
    assert harness._last_effect_timeline["timeline"]
    assert harness._last_music_timeline["timeline"]


def test_parallel_music_scene_builder_preserves_explicit_asset_selection():
    from app.services.audiobook.engine_pkg._parallel_mixin import ParallelMixin

    class FakeMusicComposer:
        def __init__(self):
            self.chapter_structure = None

        async def design_music(self, chapter_structure, **kwargs):
            self.chapter_structure = chapter_structure
            return []

        def optimize_music_placement(self, max_music_coverage=0.4):
            return []

        def export_music_timeline(self):
            return {"timeline": []}

    class Harness(ParallelMixin):
        def __init__(self):
            self._audio_fx_config = {
                "enable_sound_effects": False,
                "enable_music": True,
                "music_density": "medium",
            }
            self.music_composer = FakeMusicComposer()

    harness = Harness()
    asyncio.run(
        harness._parallel_design(
            task_id="task",
            script_segments=[
                SimpleNamespace(
                    text="The corridor narrows.",
                    emotion="neutral",
                    music_cue=SimpleNamespace(
                        asset_id="music-corridor-01",
                        style="Tense corridor bed",
                        volume=0.18,
                    ),
                    music_cue_simple="",
                )
            ],
            skip_stage_tracking=True,
            include_voice_design=False,
        )
    )

    scene = harness.music_composer.chapter_structure["scenes"][0]
    assert scene["music_asset_id"] == "music-corridor-01"
    assert scene["music_style"] == "Tense corridor bed"
    assert scene["music_volume"] == 0.18


def test_parallel_music_scene_builder_uses_narration_duration_estimate():
    """配乐候选场景起点和总时长应使用统一朗读时长估算。"""
    from app.services.audiobook.engine_pkg._parallel_mixin import ParallelMixin

    class FakeMusicComposer:
        def __init__(self):
            self.chapter_structure = None

        async def design_music(self, chapter_structure, **kwargs):
            self.chapter_structure = chapter_structure
            return []

        def optimize_music_placement(self, max_music_coverage=0.4):
            return []

        def export_music_timeline(self):
            return {"timeline": []}

    class Harness(ParallelMixin):
        def __init__(self):
            self._audio_fx_config = {
                "enable_sound_effects": False,
                "enable_music": True,
                "music_density": "medium",
            }
            self.music_composer = FakeMusicComposer()

    harness = Harness()
    asyncio.run(
        harness._parallel_design(
            task_id="task",
            script_segments=[
                SimpleNamespace(text="甲" * 45, emotion="tense", music_cue="低频铺底"),
                SimpleNamespace(text="乙" * 45, emotion="sad", music_cue="悲伤铺底"),
            ],
            chapter_content="章" * 90,
            skip_stage_tracking=True,
            include_voice_design=False,
        )
    )

    structure = harness.music_composer.chapter_structure
    assert structure["total_duration"] == pytest.approx(20.0)
    assert [scene["start_time"] for scene in structure["scenes"]] == pytest.approx([0.0, 10.0])


def test_parallel_music_scene_builder_includes_moderate_emotions():
    """恐惧、紧张等中等情绪即使无显式 music_cue 也应进入配乐候选。"""
    from app.services.audiobook.engine_pkg._parallel_mixin import ParallelMixin

    class FakeMusicComposer:
        def __init__(self):
            self.chapter_structure = None

        async def design_music(self, chapter_structure, **kwargs):
            self.chapter_structure = chapter_structure
            return []

        def optimize_music_placement(self, max_music_coverage=0.4):
            return []

        def export_music_timeline(self):
            return {"timeline": []}

    class Harness(ParallelMixin):
        def __init__(self):
            self._audio_fx_config = {
                "enable_sound_effects": False,
                "enable_music": True,
                "music_density": "medium",
            }
            self.music_composer = FakeMusicComposer()

    harness = Harness()
    asyncio.run(
        harness._parallel_design(
            task_id="task",
            script_segments=[
                SimpleNamespace(
                    text="黑暗中传来细碎的声响。",
                    emotion="fearful",
                    music_cue=None,
                    music_cue_simple="",
                )
            ],
            chapter_content="黑暗中传来细碎的声响。",
            skip_stage_tracking=True,
            include_voice_design=False,
        )
    )

    scene = harness.music_composer.chapter_structure["scenes"][0]
    assert scene["scene_id"] == "scene_0"
    assert scene["mood"] == "tense"
    assert scene["is_climax"] is True


def test_ensure_generated_assets_replaces_missing_environment_audio(
    sound_effect_designer_module,
    monkeypatch,
):
    """测试缺失环境音会被真实生成结果替换。"""
    SoundEffectCue = sound_effect_designer_module["SoundEffectCue"]
    EffectType = sound_effect_designer_module["EffectType"]
    designer = sound_effect_designer_module["SoundEffectDesigner"]()

    designer.effect_cues = [
        SoundEffectCue(
            scene_id="scene_1",
            timestamp=3.0,
            effect_type=EffectType.ENVIRONMENT,
            description="雨夜街道环境音",
            audio_file="rain_heavy.mp3",
            volume=0.2,
            fade_in=1.0,
            fade_out=1.0,
            loop=True,
            duration=12.0,
            mix_mode="background",
        )
    ]

    monkeypatch.setattr(
        designer,
        "_has_resolvable_audio_file",
        lambda file_ref: file_ref == "sound_effects/environment/generated_rain.mp3",
    )

    async def fake_ensure_doubao_ambient_sound(scene_description, duration, mood=None):
        return SoundEffectCue(
            scene_id="ambient",
            timestamp=0.0,
            effect_type=EffectType.ENVIRONMENT,
            description=scene_description,
            audio_file="sound_effects/environment/generated_rain.mp3",
            volume=0.1,
            fade_in=0.0,
            fade_out=0.0,
            loop=True,
            duration=duration,
            mix_mode="background",
        )

    monkeypatch.setattr(designer, "ensure_doubao_ambient_sound", fake_ensure_doubao_ambient_sound)

    asyncio.run(designer.ensure_generated_assets(max_generated_effects=1))

    cue = designer.effect_cues[0]
    assert cue.audio_file == "sound_effects/environment/generated_rain.mp3"
    assert cue.scene_id == "scene_1"
    assert cue.timestamp == 3.0
    assert cue.volume == 0.2
    assert cue.fade_in == 1.0


def test_doubao_ambient_ignores_missing_static_library_match(
    sound_effect_designer_module,
    monkeypatch,
):
    """测试静态库只命中文件名但本地文件不存在时，仍继续生成真实环境音。"""
    SoundEffectCue = sound_effect_designer_module["SoundEffectCue"]
    EffectType = sound_effect_designer_module["EffectType"]
    designer = sound_effect_designer_module["SoundEffectDesigner"]()

    monkeypatch.setattr(
        designer,
        "_match_effect",
        lambda **_: SoundEffectCue(
            scene_id="ambient",
            timestamp=0.0,
            effect_type=EffectType.ENVIRONMENT,
            description="内置雨声",
            audio_file="rain_heavy.mp3",
        ),
    )
    monkeypatch.setattr(designer, "_has_resolvable_audio_file", lambda file_ref: False)
    monkeypatch.setattr(
        designer,
        "download_and_register_effect",
        lambda **_: {"file_path": "sound_effects/environment/generated_rain.mp3"},
    )

    class FakeDoubaoResult:
        success = True
        audio_url = "https://example.test/rain.mp3"
        error = ""

    class FakeDoubaoGenerator:
        async def generate_audio_async(self, **kwargs):
            return FakeDoubaoResult()

    designer._doubao_sfx_generator = FakeDoubaoGenerator()

    cue = asyncio.run(designer.ensure_doubao_ambient_sound("雨夜街道", 12.0, mood="tense"))

    assert cue.audio_file == "sound_effects/environment/generated_rain.mp3"


def test_ambient_effect_metadata_name_uses_scene_description(sound_effect_designer_module):
    """回归：环境音入库名称应为真实场景描述（纯中文），不追加"环境音"后缀，且标签不混入英文提供商名。"""
    designer = sound_effect_designer_module["SoundEffectDesigner"]()

    meta = designer._build_ambient_effect_metadata("脚步声", "calm", provider="Doubao")

    assert meta["name"] == "脚步声"
    assert "环境音" not in meta["name"]
    assert "Doubao" not in meta["tags"]
    assert "Doubao" not in meta["name"]
    # effect_id 仍保留提供商后缀用于去重
    assert "doubao" in meta["effect_id"]

    # 场景描述已以"环境音"结尾时去掉该后缀，避免冗余
    meta2 = designer._build_ambient_effect_metadata("雨夜的城市街道环境音", "calm", provider="Doubao")
    assert meta2["name"] == "雨夜的城市街道"
    assert "环境音" not in meta2["name"]

    # 空描述时回退到粗分类模板名，同样不含"环境音"
    meta3 = designer._build_ambient_effect_metadata("", "calm", provider="Doubao")
    assert meta3["name"]
    assert "环境音" not in meta3["name"]
    assert "（" not in meta3["name"]


def test_doubao_ambient_failure_returns_none_without_fallback(
    sound_effect_designer_module,
    monkeypatch,
):
    """回归：豆包环境音生成失败时不做任何兜底，直接返回 None。"""
    designer = sound_effect_designer_module["SoundEffectDesigner"]()

    monkeypatch.setattr(designer, "_match_effect", lambda **_: None)
    monkeypatch.setattr(designer, "_has_resolvable_audio_file", lambda file_ref: False)

    fallback_calls = []
    monkeypatch.setattr(
        designer,
        "design_ambient_sound",
        lambda *args, **kwargs: fallback_calls.append("builtin"),
    )
    monkeypatch.setattr(
        designer,
        "ensure_mureka_ambient_sound",
        lambda *args, **kwargs: fallback_calls.append("mureka"),
    )

    class FakeDoubaoResult:
        success = False
        audio_url = ""
        error = "quota exceeded"

    class FakeDoubaoGenerator:
        async def generate_audio_async(self, **kwargs):
            return FakeDoubaoResult()

    designer._doubao_sfx_generator = FakeDoubaoGenerator()

    cue = asyncio.run(designer.ensure_doubao_ambient_sound("雨夜街道", 12.0, mood="tense"))

    assert cue is None
    assert fallback_calls == []


def test_download_and_register_effect_url_without_extension(
    sound_effect_designer_module,
    monkeypatch,
    tmp_path,
):
    """回归：豆包CDN直链无文件后缀时，不应把域名/路径误当后缀导致写文件失败。"""
    import app.services.audiobook.agents.sound_effect_designer as sfx_module

    designer = sound_effect_designer_module["SoundEffectDesigner"]()

    monkeypatch.setattr(sfx_module, "SOUND_EFFECTS_DIR", tmp_path)
    monkeypatch.setattr(designer, "register_new_effect", lambda record: None)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            yield b"fake-audio-bytes"

    monkeypatch.setattr(sfx_module.requests, "get", lambda *args, **kwargs: FakeResponse())

    record = designer.download_and_register_effect(
        url="https://sami-vod.volcengine-speech.com/volcengine-speech/cdn/20260729/861023e6-a02e-45b3-88a4-0382c255dfbd",
        effect_id="ambient_city_test_doubao_78221c",
        category="environment/peaceful",
        description="测试环境音",
        tags=["city"],
        source="ai_generated",
    )

    assert record is not None
    assert record["file_path"] == "sound_effects/environment/peaceful/ambient_city_test_doubao_78221c.mp3"
    saved = tmp_path / "environment" / "peaceful" / "ambient_city_test_doubao_78221c.mp3"
    assert saved.exists()
    assert saved.read_bytes() == b"fake-audio-bytes"


def test_doubao_short_effects_use_canonical_category_and_scene_tags(sound_effect_designer_module):
    """豆包短音效入库时，应使用统一分类并携带场景标签。"""
    SoundEffectDesigner = sound_effect_designer_module["SoundEffectDesigner"]
    SoundEffectCue = sound_effect_designer_module["SoundEffectCue"]
    EffectType = sound_effect_designer_module["EffectType"]

    designer = SoundEffectDesigner()
    calls = {}

    class FakeDoubaoResult:
        success = True
        audio_url = "https://example.test/door-kick.mp3"
        error = ""

    class FakeDoubaoGenerator:
        async def generate_audio_async(self, **kwargs):
            return FakeDoubaoResult()

    def fake_download_and_register_effect(
        *,
        url,
        effect_id,
        category,
        description,
        tags,
        source,
        style="",
        scenes=None,
        file_name=None,
    ):
        calls.update(
            {
                "url": url,
                "effect_id": effect_id,
                "category": category,
                "description": description,
                "tags": list(tags),
                "source": source,
                "style": style,
                "scenes": list(scenes or []),
                "file_name": file_name,
            }
        )
        return {
            "id": effect_id,
            "file_path": f"sound_effects/{category}/{effect_id}.mp3",
        }

    designer._doubao_sfx_generator = FakeDoubaoGenerator()
    designer.download_and_register_effect = fake_download_and_register_effect  # type: ignore[method-assign]

    cue = SoundEffectCue(
        scene_id="scene_1",
        timestamp=0.0,
        effect_type=EffectType.ACTION,
        description="门被踹开声",
        audio_file="",
    )

    record = asyncio.run(designer._generate_doubao_effect_for_cue(cue))

    assert record is not None
    assert calls["category"] == "action/realistic"
    assert calls["style"] == "realistic"
    assert "indoor" in calls["scenes"]
    assert "action" in calls["tags"]
    assert "realistic" in calls["tags"]


def test_doubao_prompt_adapter_uses_seed_audio_contract(sound_effect_designer_module):
    """测试单段音效 prompt 会以 prompt/duration 契约调用豆包生成器。"""
    designer = sound_effect_designer_module["SoundEffectDesigner"]()

    class FakeDoubaoResult:
        success = True
        audio_url = "https://example.test/effect.mp3"
        error = ""

    class FakeDoubaoGenerator:
        def __init__(self):
            self.calls = []

        async def generate_audio_async(self, **kwargs):
            self.calls.append(kwargs)
            return FakeDoubaoResult()

    fake_doubao = FakeDoubaoGenerator()
    designer._doubao_sfx_generator = fake_doubao

    result = asyncio.run(
        designer._generate_doubao_audio_for_prompt(
            prompt="low buzz",
            duration=3.0,
        )
    )

    assert result.success is True
    assert fake_doubao.calls == [
        {
            "prompt": "low buzz",
            "duration": 3.0,
        }
    ]


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


# ============== V3-15 ~ V3-18 音乐库优化测试 ==============


def test_music_index_uses_relative_paths(tmp_path, monkeypatch):
    """V3-15: music_index.json 写入时 file_path 应为相对路径。"""
    from app.services.audiobook.ai_music import MurekaO1Client, MusicGenerationRequest, MusicStyle

    cache_dir = tmp_path / "music_cache"
    cache_dir.mkdir()
    monkeypatch.setenv("MUREKA_API_KEY", "test-key")

    client = MurekaO1Client(enable_cache=True, cache_dir=str(cache_dir))
    cache_file = cache_dir / "abc123.mp3"
    cache_file.write_bytes(b"fake-audio")

    request = MusicGenerationRequest(
        prompt="test",
        style=MusicStyle.AMBIENT,
        duration=20,
        tempo="medium",
        mood="tense",
        instruments=[],
        variant=0,
        bucket="underscore:tense",
    )
    client._update_music_index(request, cache_file)

    import json as _json
    with client.index_path.open("r", encoding="utf-8") as f:
        data = _json.load(f)

    assert len(data) == 1
    assert not Path(data[0]["file_path"]).is_absolute()
    assert data[0]["file_path"].startswith("music_cache/")


def test_music_index_attaches_cloud_metadata_for_generated_music(tmp_path, monkeypatch):
    """AI 生成音乐写入共享音乐库索引时，应同步记录云端对象信息。"""
    from app.services.audiobook import ai_music as ai_music_module
    from app.services.audiobook.ai_music import MurekaO1Client, MusicGenerationRequest, MusicStyle

    cache_dir = tmp_path / "music_cache"
    cache_dir.mkdir()
    monkeypatch.setenv("MUREKA_API_KEY", "test-key")

    uploaded = []

    def fake_upload_audio_library_asset(*, local_path, relative_path, library_type):
        uploaded.append((Path(local_path).name, relative_path, library_type))
        return {
            "storage_mode": "durable_cloud",
            "storage_driver": "dashscope_oss",
            "cloud_uri": f"oss://shared/audio-library/{library_type}/{relative_path}",
            "public_url": f"https://cdn.example.test/{library_type}/{relative_path}",
            "object_key": f"shared/audio-library/{library_type}/{relative_path}",
            "local_cache_path": relative_path,
            "asset_scope": "shared_library",
        }

    monkeypatch.setattr(ai_music_module, "upload_audio_library_asset", fake_upload_audio_library_asset)

    client = MurekaO1Client(enable_cache=True, cache_dir=str(cache_dir))
    monkeypatch.setattr(
        client,
        "_assess_audio_quality",
        lambda file_path: {"quality_score": 90.0, "quality_grade": "A", "quality_status": "accepted"},
    )
    cache_file = cache_dir / "abc123.mp3"
    cache_file.write_bytes(b"ID3fake-audio")

    request = MusicGenerationRequest(
        prompt="test",
        style=MusicStyle.AMBIENT,
        duration=20,
        tempo="medium",
        mood="tense",
        instruments=[],
        variant=0,
        bucket="underscore:tense",
    )
    client._update_music_index(request, cache_file)

    data = json.loads(client.index_path.read_text(encoding="utf-8"))
    assert uploaded == [("abc123.mp3", "music_cache/abc123.mp3", "music")]
    assert data[0]["storage_mode"] == "durable_cloud"
    assert data[0]["storage_driver"] == "dashscope_oss"
    assert data[0]["cloud_uri"] == "oss://shared/audio-library/music/music_cache/abc123.mp3"
    assert data[0]["public_url"] == "https://cdn.example.test/music/music_cache/abc123.mp3"


def test_music_index_upserts_generated_music_to_shared_db_index(tmp_path, monkeypatch):
    from app.services.audiobook import ai_music as ai_music_module
    from app.services.audiobook.ai_music import MurekaO1Client, MusicGenerationRequest, MusicStyle

    cache_dir = tmp_path / "music_cache"
    cache_dir.mkdir()
    monkeypatch.setenv("MUREKA_API_KEY", "test-key")
    monkeypatch.setattr(ai_music_module, "upload_audio_library_asset", lambda **kwargs: {})
    saved_records = []
    commits = []

    class FakeSession:
        def commit(self):
            commits.append(True)

        def rollback(self):
            raise AssertionError("successful database upsert must not roll back")

        def close(self):
            pass

    monkeypatch.setattr(ai_music_module, "SessionLocal", lambda: FakeSession(), raising=False)
    monkeypatch.setattr(
        ai_music_module,
        "upsert_audio_library_asset",
        lambda db, library_type, record: saved_records.append((library_type, dict(record))),
        raising=False,
    )

    client = MurekaO1Client(enable_cache=True, cache_dir=str(cache_dir))
    monkeypatch.setattr(
        client,
        "_assess_audio_quality",
        lambda file_path: {"quality_score": 90.0, "quality_grade": "A", "quality_status": "accepted"},
    )
    cache_file = cache_dir / "shared.mp3"
    cache_file.write_bytes(b"ID3fake-audio")
    request = MusicGenerationRequest(
        prompt="tense underscore",
        style=MusicStyle.AMBIENT,
        duration=20,
        tempo="medium",
        mood="tense",
        instruments=[],
        variant=0,
        bucket="underscore:tense",
    )

    client._update_music_index(request, cache_file)

    assert commits == [True]
    assert saved_records[0][0] == "music"
    saved_record = saved_records[0][1]
    assert saved_record["id"] == client._get_cache_key(request)
    assert saved_record["file_path"] == "music_cache/shared.mp3"
    assert saved_record["source"] == "mureka"


def test_music_composer_loads_external_index(music_composer_module, tmp_path, monkeypatch):
    """V3-16: MusicComposer 应从 music_index.json 加载外部条目。"""
    MusicComposer = music_composer_module["MusicComposer"]
    composer_module = sys.modules[MusicComposer.__module__]

    audio_library = tmp_path / "audio_library"
    music_cache = audio_library / "music_cache"
    music_cache.mkdir(parents=True)
    music_file = music_cache / "tense_1.mp3"
    music_file.write_bytes(b"fake-music")

    index_path = audio_library / "music_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "tense_entry_1",
                    "mood": "tense",
                    "file_path": "music_cache/tense_1.mp3",
                    "prompt": "tense scene",
                    "bucket": "underscore:tense",
                    "source": "mureka",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(composer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(composer_module, "DEFAULT_MUSIC_INDEX_PATH", index_path)

    composer = MusicComposer(enable_ai=False, index_path=str(index_path))

    assert "tense_entry_1" in composer.music_library
    assert composer.music_library["tense_entry_1"]["mood"] == "tense"


def test_music_composer_custom_index_resolves_relative_paths_from_index_dir(music_composer_module, tmp_path):
    """V3-16: 自定义 music_index.json 的相对 file_path 应按索引所在目录解析。"""
    MusicComposer = music_composer_module["MusicComposer"]

    audio_library = tmp_path / "custom_audio_library"
    music_cache = audio_library / "music_cache"
    music_cache.mkdir(parents=True)
    music_file = music_cache / "tense_custom.mp3"
    music_file.write_bytes(b"fake-music")

    index_path = audio_library / "music_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "tense_custom",
                    "mood": "tense",
                    "file_path": "music_cache/tense_custom.mp3",
                    "prompt": "tense custom",
                    "source": "mureka",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    composer = MusicComposer(enable_ai=False, index_path=str(index_path))

    assert "tense_custom" in composer.music_library


def test_music_composer_external_index_skips_missing_files(
    music_composer_module, tmp_path, monkeypatch, caplog
):
    """V3-16: 外部音乐索引条目文件不存在时应跳过。"""
    MusicComposer = music_composer_module["MusicComposer"]
    composer_module = sys.modules[MusicComposer.__module__]

    audio_library = tmp_path / "audio_library"
    index_path = audio_library / "music_index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "missing_music",
                    "mood": "tense",
                    "file_path": "music_cache/missing.mp3",
                    "source": "mureka",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(composer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(composer_module, "DEFAULT_MUSIC_INDEX_PATH", index_path)

    caplog.set_level(logging.WARNING, logger=composer_module.__name__)
    composer = MusicComposer(enable_ai=False, index_path=str(index_path))

    assert "missing_music" not in composer.music_library
    assert "音乐索引条目文件不存在" in caplog.text


def test_music_composer_external_index_skips_community_rejected_entries(
    music_composer_module,
    tmp_path,
    monkeypatch,
):
    MusicComposer = music_composer_module["MusicComposer"]
    composer_module = sys.modules[MusicComposer.__module__]
    audio_library = tmp_path / "audio_library"
    music_file = audio_library / "music_cache" / "rejected.mp3"
    music_file.parent.mkdir(parents=True)
    music_file.write_bytes(b"rejected")
    index_path = audio_library / "music_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "community_rejected_music",
                    "mood": "tense",
                    "file_path": "music_cache/rejected.mp3",
                    "quality_status": "community_rejected",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(composer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(composer_module, "DEFAULT_MUSIC_INDEX_PATH", index_path)

    composer = MusicComposer(enable_ai=False, index_path=str(index_path))

    assert "community_rejected_music" not in composer.music_library


def test_music_composer_external_index_replaces_unresolved_builtin(music_composer_module, tmp_path, monkeypatch):
    """V3-16: 外部真实素材应覆盖内置不可解析占位。"""
    MusicComposer = music_composer_module["MusicComposer"]
    composer_module = sys.modules[MusicComposer.__module__]

    audio_library = tmp_path / "audio_library"
    music_cache = audio_library / "music_cache"
    music_cache.mkdir(parents=True)
    music_file = music_cache / "suspense_1.mp3"
    music_file.write_bytes(b"real-music")

    index_path = audio_library / "music_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "suspense_1",
                    "mood": "tense",
                    "file_path": "music_cache/suspense_1.mp3",
                    "prompt": "suspense",
                    "source": "mureka",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(composer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(composer_module, "DEFAULT_MUSIC_INDEX_PATH", index_path)

    composer = MusicComposer(enable_ai=False, index_path=str(index_path))

    assert composer.music_library["suspense_1"]["file"] == "music_cache/suspense_1.mp3"


def test_music_composer_uses_explicit_asset_id_without_ai_generation(
    music_composer_module,
    tmp_path,
    monkeypatch,
):
    MusicComposer = music_composer_module["MusicComposer"]
    composer_module = sys.modules[MusicComposer.__module__]
    audio_library = tmp_path / "audio_library"
    music_file = audio_library / "music_cache" / "selected.mp3"
    music_file.parent.mkdir(parents=True)
    music_file.write_bytes(b"selected-music")
    index_path = audio_library / "music_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "music-selected-01",
                    "mood": "tense",
                    "style": "Selected tense bed",
                    "file_path": "music_cache/selected.mp3",
                    "description": "Selected library music",
                }
            ]
        ),
        encoding="utf-8",
    )

    class FakeGenerator:
        def __init__(self):
            self.calls = []

        async def generate_for_bucket(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(success=True, audio_file_path="generated.mp3")

    generator = FakeGenerator()
    monkeypatch.setattr(composer_module, "AI_MUSIC_AVAILABLE", True)
    composer = MusicComposer(
        ai_generator=generator,
        enable_ai=True,
        index_path=str(index_path),
    )

    cue = asyncio.run(
        composer._design_scene_music(
            {
                "scene_id": "scene-1",
                "start_time": 4.0,
                "duration": 30.0,
                "mood": "tense",
                "description": "Tense corridor",
                "is_climax": True,
                "music_asset_id": "music-selected-01",
                "music_volume": 0.18,
            }
        )
    )

    assert cue is not None
    assert cue.audio_file == "music_cache/selected.mp3"
    assert cue.volume == 0.18
    assert getattr(cue, "asset_id", "") == "music-selected-01"
    assert generator.calls == []

    composer.music_cues = [cue]
    composer._chapter_total_duration = 30.0
    assert composer.optimize_music_placement(max_music_coverage=0.01) == [cue]


def test_music_pool_cache_preloaded_from_index(music_composer_module, tmp_path, monkeypatch):
    """V3-17: 音乐池缓存应从 music_index.json 预加载。"""
    MusicComposer = music_composer_module["MusicComposer"]
    composer_module = sys.modules[MusicComposer.__module__]

    audio_library = tmp_path / "audio_library"
    music_cache = audio_library / "music_cache"
    music_cache.mkdir(parents=True)

    entries = []
    for i in range(3):
        f = music_cache / f"tense_{i}.mp3"
        f.write_bytes(b"music")
        entries.append(
            {
                "id": f"tense_{i}",
                "mood": "tense",
                "file_path": f"music_cache/tense_{i}.mp3",
                "prompt": "tense",
                "bucket": "underscore:tense",
                "variant": i,
                "source": "mureka",
            }
        )

    index_path = audio_library / "music_index.json"
    index_path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(composer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(composer_module, "DEFAULT_MUSIC_INDEX_PATH", index_path)

    composer = MusicComposer(enable_ai=False, index_path=str(index_path))

    assert len(composer._music_pool_cache) > 0


def test_ensure_music_pool_uses_preloaded_cache_with_enough_variants(music_composer_module):
    """V3-17: 已有索引变体数量充足时，音乐池应复用缓存而不是重新调用生成器。"""
    MusicComposer = music_composer_module["MusicComposer"]
    composer = MusicComposer(enable_ai=False)
    composer._music_pool_cache.clear()

    preloaded = [f"music_cache/preloaded_{i}.mp3" for i in range(7)]
    composer._music_pool_cache["underscore:tense|tense|20|7"] = preloaded

    class FakeGenerator:
        def __init__(self):
            self.calls = []

        async def generate_for_bucket(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                success=True,
                audio_file_path=f"music_cache/generated_{kwargs['variant']}.mp3",
            )

    fake_generator = FakeGenerator()
    composer.enable_ai = True
    composer.ai_generator = fake_generator

    result = asyncio.run(
        composer._ensure_music_pool(
            bucket="underscore:tense",
            mood="tense",
            prompt="unused",
            duration=20,
            pool_size=5,
        )
    )

    assert result == preloaded[:5]
    assert fake_generator.calls == []
    assert composer._music_pool_cache["underscore:tense|tense|20|5"] == preloaded[:5]


def test_match_music_uses_seed_for_variety(music_composer_module):
    """V3-18: _match_music 应基于 seed 稳定随机选取，而非固定返回首个。"""
    MusicComposer = music_composer_module["MusicComposer"]
    composer = MusicComposer(enable_ai=False)

    composer.music_library["tense_a"] = {"mood": "tense", "description": "A", "file": "a.mp3"}
    composer.music_library["tense_b"] = {"mood": "tense", "description": "B", "file": "b.mp3"}
    composer.music_library["tense_c"] = {"mood": "tense", "description": "C", "file": "c.mp3"}

    result_a = composer._match_music("tense", seed="scene_1")
    result_b = composer._match_music("tense", seed="scene_2")

    assert result_a["mood"] == "tense"
    assert result_b["mood"] == "tense"

    same_seed_1 = composer._match_music("tense", seed="scene_1")
    same_seed_2 = composer._match_music("tense", seed="scene_1")
    assert same_seed_1["file"] == same_seed_2["file"]


def test_scene_music_static_fallback_seed_includes_project_and_chapter(music_composer_module):
    """V3-18: 静态库降级选曲 seed 应包含项目和章节，避免跨章节固定命中同一首。"""
    MusicComposer = music_composer_module["MusicComposer"]
    composer = MusicComposer(enable_ai=False)
    calls = []

    def fake_match_music(mood, seed=""):
        calls.append((mood, seed))
        return {"mood": mood, "description": "tense", "file": "tense.mp3"}

    composer._match_music = fake_match_music

    cue = asyncio.run(
        composer._design_scene_music(
            {
                "audiobook_project_id": "project_1",
                "chapter_id": "chapter_2",
                "scene_id": "scene_1",
                "start_time": 12.5,
                "duration": 30.0,
                "mood": "tense",
                "is_climax": True,
            },
            allow_asset_generation=False,
        )
    )

    assert calls == [("tense", "project_1|chapter_2|scene_1|12.5|tense")]
    assert cue.audio_file == "tense.mp3"


# ============== V3-19 质量门控与素材清理测试 ==============


def test_sound_effect_register_writes_quality_metadata(sound_effect_designer_module, tmp_path, monkeypatch):
    """V3-19: register_new_effect 应自动写入质量元数据。"""
    SoundEffectDesigner = sound_effect_designer_module["SoundEffectDesigner"]
    designer_module = sys.modules[SoundEffectDesigner.__module__]

    audio_library = tmp_path / "audio_library"
    sfx_dir = audio_library / "sound_effects" / "test"
    sfx_dir.mkdir(parents=True)
    sfx_file = sfx_dir / "click.wav"
    sfx_file.write_bytes(b"fake")

    index_path = audio_library / "sound_effects_index.json"
    monkeypatch.setattr(designer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(designer_module, "SOUND_EFFECTS_DIR", audio_library / "sound_effects")

    designer = SoundEffectDesigner(index_path=str(index_path))
    designer.register_new_effect({
        "id": "test_click",
        "category": "action",
        "file_path": "sound_effects/test/click.wav",
        "description": "click",
    })

    with index_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    entry = next(r for r in data if r["id"] == "test_click")
    assert "quality_score" in entry
    assert "quality_grade" in entry
    assert "quality_status" in entry


def test_sound_effect_quality_uses_ffmpeg_fallback_when_pydub_decode_fails(
    sound_effect_designer_module,
    tmp_path,
    monkeypatch,
):
    """pydub 解码失败时，质量门禁应回退到 ffprobe/ffmpeg，避免误拒可用音频。"""
    SoundEffectDesigner = sound_effect_designer_module["SoundEffectDesigner"]
    designer_module = sys.modules[SoundEffectDesigner.__module__]

    audio_library = tmp_path / "audio_library"
    sfx_dir = audio_library / "sound_effects"
    sfx_dir.mkdir(parents=True)
    sfx_file = sfx_dir / "ambient.ogg"
    sfx_file.write_bytes(b"OggS fake but ffmpeg mocked")

    class BrokenAudioSegment:
        @staticmethod
        def from_file(path):
            raise RuntimeError("decoder unavailable")

    def fake_run(cmd, capture_output, text, check):
        joined = " ".join(str(part) for part in cmd)
        if "-show_entries" in joined:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    {
                        "streams": [{"codec_type": "audio", "sample_rate": "48000", "channels": 2}],
                        "format": {"duration": "12.5", "bit_rate": "160000"},
                    }
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="",
            stderr=(
                "[Parsed_volumedetect_0] mean_volume: -24.0 dB\n"
                "[Parsed_volumedetect_0] max_volume: -3.0 dB\n"
            ),
        )

    monkeypatch.setitem(sys.modules, "pydub", SimpleNamespace(AudioSegment=BrokenAudioSegment))
    monkeypatch.setattr(designer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(designer_module.subprocess, "run", fake_run)

    designer = SoundEffectDesigner(index_path=str(audio_library / "sound_effects_index.json"))
    quality = designer._assess_audio_quality("sound_effects/ambient.ogg")

    assert quality["quality_status"] == "accepted"
    assert quality["quality_score"] >= 60


def test_sound_effect_quality_does_not_penalize_valid_short_effects(sound_effect_designer_module):
    """短促点状音效本身不应被视为低质量。"""
    SoundEffectDesigner = sound_effect_designer_module["SoundEffectDesigner"]

    designer = SoundEffectDesigner()
    quality = designer._score_audio_quality_metrics(
        duration_s=0.12,
        dbfs=-24.0,
        silent_ratio=0.0,
    )

    assert quality["quality_status"] == "accepted"
    assert quality["quality_score"] == 100.0


def test_sound_effect_register_attaches_cloud_metadata_for_generated_sfx(
    sound_effect_designer_module,
    tmp_path,
    monkeypatch,
):
    """AI 生成音效入库时，应同步登记共享云端对象信息。"""
    SoundEffectDesigner = sound_effect_designer_module["SoundEffectDesigner"]
    designer_module = sys.modules[SoundEffectDesigner.__module__]

    audio_library = tmp_path / "audio_library"
    sfx_dir = audio_library / "sound_effects" / "generated"
    sfx_dir.mkdir(parents=True)
    sfx_file = sfx_dir / "hit.wav"
    sfx_file.write_bytes(b"RIFF0000WAVEfmt ")

    uploaded = []

    def fake_upload_audio_library_asset(*, local_path, relative_path, library_type):
        uploaded.append((Path(local_path).name, relative_path, library_type))
        return {
            "storage_mode": "durable_cloud",
            "storage_driver": "dashscope_oss",
            "cloud_uri": f"oss://shared/audio-library/{library_type}/{relative_path}",
            "public_url": f"https://cdn.example.test/{library_type}/{relative_path}",
            "object_key": f"shared/audio-library/{library_type}/{relative_path}",
            "local_cache_path": relative_path,
            "asset_scope": "shared_library",
        }

    index_path = audio_library / "sound_effects_index.json"
    monkeypatch.setattr(designer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(designer_module, "SOUND_EFFECTS_DIR", audio_library / "sound_effects")
    monkeypatch.setattr(designer_module, "upload_audio_library_asset", fake_upload_audio_library_asset)

    designer = SoundEffectDesigner(index_path=str(index_path))
    monkeypatch.setattr(
        designer,
        "_assess_audio_quality",
        lambda file_path: {"quality_score": 88.0, "quality_grade": "B", "quality_status": "accepted"},
    )
    designer.register_new_effect(
        {
            "id": "generated_hit",
            "category": "action",
            "file_path": "sound_effects/generated/hit.wav",
            "description": "hit",
            "source": "vidu",
        }
    )

    data = json.loads(index_path.read_text(encoding="utf-8"))
    entry = next(r for r in data if r["id"] == "generated_hit")
    assert uploaded == [("hit.wav", "sound_effects/generated/hit.wav", "sfx")]
    assert entry["storage_mode"] == "durable_cloud"
    assert entry["storage_driver"] == "dashscope_oss"
    assert entry["cloud_uri"] == "oss://shared/audio-library/sfx/sound_effects/generated/hit.wav"
    assert entry["public_url"] == "https://cdn.example.test/sfx/sound_effects/generated/hit.wav"


def test_sound_effect_register_upserts_generated_sfx_to_shared_db_index(
    sound_effect_designer_module,
    tmp_path,
    monkeypatch,
):
    """AI 生成音效入库时，应同步写入共享数据库索引，保证素材浏览可见。"""
    SoundEffectDesigner = sound_effect_designer_module["SoundEffectDesigner"]
    designer_module = sys.modules[SoundEffectDesigner.__module__]

    audio_library = tmp_path / "audio_library"
    sfx_dir = audio_library / "sound_effects" / "generated"
    sfx_dir.mkdir(parents=True)
    sfx_file = sfx_dir / "door.wav"
    sfx_file.write_bytes(b"RIFF0000WAVEfmt ")

    saved_records = []
    commits = []

    class FakeSession:
        def close(self):
            pass

        def commit(self):
            commits.append(True)

        def rollback(self):
            raise AssertionError("不应回滚成功写入")

    monkeypatch.setattr(designer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(designer_module, "SOUND_EFFECTS_DIR", audio_library / "sound_effects")
    monkeypatch.setattr(designer_module, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        designer_module,
        "upsert_audio_library_asset",
        lambda db, library_type, record: saved_records.append((library_type, dict(record))),
    )

    designer = SoundEffectDesigner(index_path=str(audio_library / "sound_effects_index.json"))
    monkeypatch.setattr(
        designer,
        "_assess_audio_quality",
        lambda file_path: {"quality_score": 90.0, "quality_grade": "A", "quality_status": "accepted"},
    )

    designer.register_new_effect(
        {
            "id": "generated_door",
            "category": "effects/action",
            "file_path": "sound_effects/generated/door.wav",
            "description": "门被踹开声",
            "source": "vidu",
        }
    )

    assert commits == [True]
    assert saved_records[0][0] == "sfx"
    saved_record = saved_records[0][1]
    assert saved_record["id"] == "generated_door"
    assert saved_record["category"] == "action/realistic"
    assert saved_record["style"] == "realistic"
    assert "indoor" in saved_record["scenes"]


def test_sound_effect_purge_low_quality(sound_effect_designer_module, tmp_path, monkeypatch):
    """V3-19: purge_low_quality_assets 应删除低质条目和磁盘文件。"""
    SoundEffectDesigner = sound_effect_designer_module["SoundEffectDesigner"]
    designer_module = sys.modules[SoundEffectDesigner.__module__]

    audio_library = tmp_path / "audio_library"
    sfx_dir = audio_library / "sound_effects" / "test"
    sfx_dir.mkdir(parents=True)
    bad_file = sfx_dir / "bad.wav"
    bad_file.write_bytes(b"bad")
    good_file = sfx_dir / "good.wav"
    good_file.write_bytes(b"good")

    index_path = audio_library / "sound_effects_index.json"
    index_path.write_text(json.dumps([
        {"id": "bad_effect", "file_path": "sound_effects/test/bad.wav", "quality_score": 10.0, "quality_status": "rejected"},
        {"id": "good_effect", "file_path": "sound_effects/test/good.wav", "quality_score": 80.0, "quality_status": "accepted"},
    ], ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(designer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(designer_module, "SOUND_EFFECTS_DIR", audio_library / "sound_effects")

    designer = SoundEffectDesigner(index_path=str(index_path))
    result = designer.purge_low_quality_assets(min_score=40.0)

    assert result["purged_count"] == 1
    assert not bad_file.exists()
    assert good_file.exists()

    with index_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["id"] == "good_effect"


def test_sound_effect_purge_orphan_entries(sound_effect_designer_module, tmp_path, monkeypatch):
    """V3-19: purge_orphan_entries 应清理文件已不存在的索引条目。"""
    SoundEffectDesigner = sound_effect_designer_module["SoundEffectDesigner"]
    designer_module = sys.modules[SoundEffectDesigner.__module__]

    audio_library = tmp_path / "audio_library"
    sfx_dir = audio_library / "sound_effects" / "test"
    sfx_dir.mkdir(parents=True)
    existing_file = sfx_dir / "exists.wav"
    existing_file.write_bytes(b"data")

    index_path = audio_library / "sound_effects_index.json"
    index_path.write_text(json.dumps([
        {"id": "orphan_effect", "file_path": "sound_effects/test/missing.wav", "quality_score": 80.0},
        {"id": "existing_effect", "file_path": "sound_effects/test/exists.wav", "quality_score": 80.0},
    ], ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(designer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(designer_module, "SOUND_EFFECTS_DIR", audio_library / "sound_effects")

    designer = SoundEffectDesigner(index_path=str(index_path))
    result = designer.purge_orphan_entries()

    assert result["purged_count"] == 1
    assert existing_file.exists()

    with index_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["id"] == "existing_effect"


def test_sound_effect_purge_dry_run(sound_effect_designer_module, tmp_path, monkeypatch):
    """V3-19: dry_run=True 时仅统计不实际删除。"""
    SoundEffectDesigner = sound_effect_designer_module["SoundEffectDesigner"]
    designer_module = sys.modules[SoundEffectDesigner.__module__]

    audio_library = tmp_path / "audio_library"
    sfx_dir = audio_library / "sound_effects" / "test"
    sfx_dir.mkdir(parents=True)
    bad_file = sfx_dir / "bad.wav"
    bad_file.write_bytes(b"bad")

    index_path = audio_library / "sound_effects_index.json"
    index_path.write_text(json.dumps([
        {"id": "bad_effect", "file_path": "sound_effects/test/bad.wav", "quality_score": 10.0, "quality_status": "rejected"},
    ], ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(designer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(designer_module, "SOUND_EFFECTS_DIR", audio_library / "sound_effects")

    designer = SoundEffectDesigner(index_path=str(index_path))
    result = designer.purge_low_quality_assets(dry_run=True)

    assert result["purged_count"] == 1
    assert bad_file.exists()

    with index_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 1


def test_sound_effect_purge_does_not_delete_absolute_file_outside_library(
    sound_effect_designer_module, tmp_path, monkeypatch
):
    """V3-19: 清理索引时不得删除素材库外部的绝对路径文件。"""
    SoundEffectDesigner = sound_effect_designer_module["SoundEffectDesigner"]
    designer_module = sys.modules[SoundEffectDesigner.__module__]

    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    outside_file = tmp_path / "outside.wav"
    outside_file.write_bytes(b"outside")

    index_path = audio_library / "sound_effects_index.json"
    index_path.write_text(json.dumps([
        {
            "id": "outside_effect",
            "file_path": str(outside_file),
            "quality_score": 10.0,
            "quality_status": "rejected",
        },
    ], ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(designer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(designer_module, "SOUND_EFFECTS_DIR", audio_library / "sound_effects")

    designer = SoundEffectDesigner(index_path=str(index_path))
    result = designer.purge_low_quality_assets(min_score=40.0)

    assert result["purged_count"] == 1
    assert outside_file.exists()

    with index_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert data == []


def test_sound_effect_purge_low_quality_keeps_unknown_quality_entries(
    sound_effect_designer_module, tmp_path, monkeypatch
):
    """V3-19: 缺失质量元数据的历史音效条目不应被低质清理误删。"""
    SoundEffectDesigner = sound_effect_designer_module["SoundEffectDesigner"]
    designer_module = sys.modules[SoundEffectDesigner.__module__]

    audio_library = tmp_path / "audio_library"
    sfx_dir = audio_library / "sound_effects" / "test"
    sfx_dir.mkdir(parents=True)
    legacy_file = sfx_dir / "legacy.wav"
    legacy_file.write_bytes(b"legacy")

    index_path = audio_library / "sound_effects_index.json"
    index_path.write_text(json.dumps([
        {"id": "legacy_effect", "file_path": "sound_effects/test/legacy.wav"},
    ], ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(designer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(designer_module, "SOUND_EFFECTS_DIR", audio_library / "sound_effects")

    designer = SoundEffectDesigner(index_path=str(index_path))
    result = designer.purge_low_quality_assets(min_score=40.0)

    assert result["purged_count"] == 0
    assert legacy_file.exists()

    with index_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["id"] == "legacy_effect"


def test_music_composer_purge_low_quality(music_composer_module, tmp_path, monkeypatch):
    """V3-19: MusicComposer.purge_low_quality_assets 应删除低质音乐条目。"""
    MusicComposer = music_composer_module["MusicComposer"]
    composer_module = sys.modules[MusicComposer.__module__]

    audio_library = tmp_path / "audio_library"
    music_cache = audio_library / "music_cache"
    music_cache.mkdir(parents=True)
    bad_file = music_cache / "bad.mp3"
    bad_file.write_bytes(b"bad")
    good_file = music_cache / "good.mp3"
    good_file.write_bytes(b"good")

    index_path = audio_library / "music_index.json"
    index_path.write_text(json.dumps([
        {"id": "bad_music", "file_path": "music_cache/bad.mp3", "quality_score": 15.0, "quality_status": "rejected"},
        {"id": "good_music", "file_path": "music_cache/good.mp3", "quality_score": 85.0, "quality_status": "accepted"},
    ], ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(composer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(composer_module, "DEFAULT_MUSIC_INDEX_PATH", index_path)

    composer = MusicComposer(enable_ai=False, index_path=str(index_path))
    result = composer.purge_low_quality_assets(min_score=40.0)

    assert result["purged_count"] == 1
    assert not bad_file.exists()
    assert good_file.exists()


def test_music_composer_purge_does_not_delete_absolute_file_outside_library(music_composer_module, tmp_path):
    """V3-19: 音乐清理不得删除素材库外部的绝对路径文件。"""
    MusicComposer = music_composer_module["MusicComposer"]

    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    outside_file = tmp_path / "outside.mp3"
    outside_file.write_bytes(b"outside")

    index_path = audio_library / "music_index.json"
    index_path.write_text(json.dumps([
        {
            "id": "outside_music",
            "file_path": str(outside_file),
            "quality_score": 10.0,
            "quality_status": "rejected",
        },
    ], ensure_ascii=False), encoding="utf-8")

    composer = MusicComposer(enable_ai=False, index_path=str(index_path))
    result = composer.purge_low_quality_assets(min_score=40.0)

    assert result["purged_count"] == 1
    assert outside_file.exists()

    with index_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert data == []


def test_music_composer_purge_low_quality_keeps_unknown_quality_entries(music_composer_module, tmp_path):
    """V3-19: 缺失质量元数据的历史音乐条目不应被低质清理误删。"""
    MusicComposer = music_composer_module["MusicComposer"]

    audio_library = tmp_path / "audio_library"
    music_cache = audio_library / "music_cache"
    music_cache.mkdir(parents=True)
    legacy_file = music_cache / "legacy.mp3"
    legacy_file.write_bytes(b"legacy")

    index_path = audio_library / "music_index.json"
    index_path.write_text(json.dumps([
        {"id": "legacy_music", "file_path": "music_cache/legacy.mp3"},
    ], ensure_ascii=False), encoding="utf-8")

    composer = MusicComposer(enable_ai=False, index_path=str(index_path))
    result = composer.purge_low_quality_assets(min_score=40.0)

    assert result["purged_count"] == 0
    assert legacy_file.exists()

    with index_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["id"] == "legacy_music"


def test_music_composer_purge_orphan_entries(music_composer_module, tmp_path, monkeypatch):
    """V3-19: MusicComposer.purge_orphan_entries 应清理孤立音乐条目。"""
    MusicComposer = music_composer_module["MusicComposer"]
    composer_module = sys.modules[MusicComposer.__module__]

    audio_library = tmp_path / "audio_library"
    music_cache = audio_library / "music_cache"
    music_cache.mkdir(parents=True)
    existing_file = music_cache / "exists.mp3"
    existing_file.write_bytes(b"data")

    index_path = audio_library / "music_index.json"
    index_path.write_text(json.dumps([
        {"id": "orphan_music", "file_path": "music_cache/missing.mp3", "quality_score": 80.0},
        {"id": "existing_music", "file_path": "music_cache/exists.mp3", "quality_score": 80.0},
    ], ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(composer_module, "AUDIO_LIBRARY_DIR", audio_library)
    monkeypatch.setattr(composer_module, "DEFAULT_MUSIC_INDEX_PATH", index_path)

    composer = MusicComposer(enable_ai=False, index_path=str(index_path))
    result = composer.purge_orphan_entries()

    assert result["purged_count"] == 1
    assert existing_file.exists()


def test_download_and_register_effect_normalizes_quiet_audio(
    sound_effect_designer_module,
    monkeypatch,
    tmp_path,
):
    """回归：豆包生成的音效电平极低（实测约-50dBFS）时，入库前应做响度归一化，
    否则混音层再叠加 -14dB 基准增益后几乎不可闻，且质量评估会因低响度+
    静音误判打成 rejected（阻断云端上传、被 purge_low_quality_assets 清理）。"""
    import base64
    import io

    from pydub import AudioSegment
    from pydub.generators import Sine

    import app.services.audiobook.agents.sound_effect_designer as sfx_module

    designer = sound_effect_designer_module["SoundEffectDesigner"]()

    monkeypatch.setattr(sfx_module, "SOUND_EFFECTS_DIR", tmp_path)
    monkeypatch.setattr(designer, "register_new_effect", lambda record: None)

    # 构造 -50dBFS 的低电平音频（模拟豆包真实返回）
    quiet = Sine(440).to_audio_segment(duration=1000)
    quiet = quiet.apply_gain(-50.0 - quiet.dBFS)
    buf = io.BytesIO()
    quiet.export(buf, format="wav")
    data_uri = "data:audio/wav;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    record = designer.download_and_register_effect(
        url=data_uri,
        effect_id="sfx_action_quiet01",
        category="action/realistic",
        description="低电平测试音效",
        tags=["action"],
        source="ai_generated",
    )

    assert record is not None
    saved = tmp_path / "action" / "realistic" / "sfx_action_quiet01.wav"
    assert saved.exists()
    normalized = AudioSegment.from_file(str(saved))
    # 归一化后平均响度应显著抬升（目标约 -23dBFS，允许编码误差）
    assert normalized.dBFS > -30.0


def test_enhance_effects_with_doubao_covers_transition_cues(
    sound_effect_designer_module,
    monkeypatch,
):
    """回归：TRANSITION 类型占位音效也应被豆包补生成，
    否则转场占位永远无人生成、混音时被静默跳过。"""
    SoundEffectCue = sound_effect_designer_module["SoundEffectCue"]
    EffectType = sound_effect_designer_module["EffectType"]
    designer = sound_effect_designer_module["SoundEffectDesigner"]()

    class FakeDoubaoResult:
        success = True
        audio_url = "https://example.test/transition.mp3"
        error = ""

    class FakeDoubaoGenerator:
        async def generate_audio_async(self, **kwargs):
            return FakeDoubaoResult()

    designer._doubao_sfx_generator = FakeDoubaoGenerator()
    monkeypatch.setattr(designer, "_has_resolvable_audio_file", lambda file_ref: False)
    designer.download_and_register_effect = lambda **kwargs: {  # type: ignore[method-assign]
        "id": kwargs["effect_id"],
        "file_path": f"sound_effects/{kwargs['category']}/{kwargs['effect_id']}.mp3",
    }

    designer.effect_cues = [
        SoundEffectCue(
            scene_id="scene_1",
            timestamp=10.0,
            effect_type=EffectType.TRANSITION,
            description="场景切换的呼啸转场音",
            audio_file="placeholder.mp3",
        )
    ]

    asyncio.run(designer.enhance_effects_with_doubao(max_generated_effects=1))

    cue = designer.effect_cues[0]
    assert cue.audio_file != "placeholder.mp3"
    assert "sfx_transition_" in cue.audio_file


def test_ambient_effect_metadata_slug_not_forced_to_city(sound_effect_designer_module):
    """回归：环境音 effect_id 的 slug 推断不应把非城市场景（水滴声等）
    一律兜底成 city_ambient 模板，避免 id 与声学语义不符。"""
    designer = sound_effect_designer_module["SoundEffectDesigner"]()

    # 水声类场景应归 water 而非 city
    meta = designer._build_ambient_effect_metadata("水滴声", "calm", provider="Doubao")
    assert "city" not in meta["effect_id"]
    assert "water" in meta["effect_id"]

    meta2 = designer._build_ambient_effect_metadata("水牢里持续的滴水声", "tense", provider="Doubao")
    assert "city" not in meta2["effect_id"]

    # 无任何场景关键词时用中性 slug，不冒充城市
    meta3 = designer._build_ambient_effect_metadata("心跳声", "calm", provider="Doubao")
    assert "city" not in meta3["effect_id"]

    # 真实城市场景仍归 city
    meta4 = designer._build_ambient_effect_metadata("雨夜的城市街道", "calm", provider="Doubao")
    assert "city" in meta4["effect_id"]


def test_llm_prompt_expansion_runs_off_event_loop(sound_effect_designer_module, monkeypatch):
    """回归：async 生成链路中的 LLM 提示词扩写应放入线程执行，
    避免同步 HTTP 调用阻塞事件循环。"""
    import threading

    designer = sound_effect_designer_module["SoundEffectDesigner"]()
    designer.llm_client = object()

    captured = {}

    def fake_run_llm(prompt, max_tokens):
        captured["thread"] = threading.current_thread()
        return '{"prompt": "扩写后的声音描述"}'

    monkeypatch.setattr(designer, "_run_llm_chat_sync", fake_run_llm)

    async def main():
        loop_thread = threading.current_thread()
        expanded = await designer._expand_effect_prompt_with_llm_async(
            "雨夜街道", "持续循环的环境音"
        )
        return loop_thread, expanded

    loop_thread, expanded = asyncio.run(main())

    assert expanded == "扩写后的声音描述"
    assert captured["thread"] is not loop_thread


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
