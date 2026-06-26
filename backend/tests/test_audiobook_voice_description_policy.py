import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook.agents.voice_designer import VoiceDesigner
from app.services.audiobook.tts_style_control import build_model_style_control
from app.services.audiobook.voice_manager import VoiceProfile
from app.services.audiobook.voice_description_policy import reconcile_voice_description_with_selected_voice


def test_voice_designer_generates_multidimensional_actionable_description() -> None:
    profile = VoiceDesigner().design_voice(
        {
            "name": "林晚",
            "gender": "female",
            "age": 29,
            "personality": "冷静、温柔、观察力强",
            "background": "刑侦顾问",
            "role": "主角",
        }
    )

    description = profile.voice_description

    assert "性别：女性" in description
    assert "年龄感：青年" in description
    assert "音调：" in description
    assert "语速：" in description
    assert "情绪：" in description
    assert "特点：" in description
    assert "用途：" in description
    assert "好听" not in description
    assert "普通" not in description
    assert "模仿" not in description


def test_qwen_style_control_keeps_selected_voice_as_hard_constraint() -> None:
    control = build_model_style_control(
        "qwen3-tts-instruct-flash",
        {
            "speaker": "Cherry",
            "voice_description": "低沉中年男性，语速缓慢，适合纪录片解说",
            "segment_speaker": "林晚",
            "segment_type": "dialogue",
            "performance_notes": "压低声音，但吐字保持清晰。",
        },
        "calm",
    )

    instructions = control.provider_fields["instructions"]
    voice_description = instructions.split("声音描述：", 1)[1].split("；", 1)[0]

    assert "女性" in voice_description
    assert "男性" not in voice_description
    assert "青年" in voice_description
    assert "中年" not in voice_description
    assert "亲切自然" in voice_description
    assert any("性别" in warning for warning in control.warnings)
    assert any("年龄感" in warning for warning in control.warnings)


def test_selected_voice_corrects_pitch_and_dialogue_use_case_conflicts() -> None:
    control = build_model_style_control(
        "qwen3-tts-instruct-flash",
        {
            "speaker": "Bella",
            "voice_description": "性别：女性，年龄感：儿童，音调：偏低，语速：缓慢，情绪：严肃，特点：浑厚、苍老，用途：纪录片解说",
            "segment_speaker": "萌萌",
            "segment_type": "dialogue",
        },
        "happy",
    )

    instructions = control.provider_fields["instructions"]
    voice_description = instructions.split("声音描述：", 1)[1].split("；", 1)[0]

    assert "音调：偏高" in voice_description
    assert "用途：有声书角色对白" in voice_description
    assert "纪录片解说" not in voice_description
    assert any("音调" in warning for warning in control.warnings)
    assert any("用途" in warning for warning in control.warnings)


def test_childlike_voice_reports_rough_timbre_conflicts() -> None:
    control = build_model_style_control(
        "qwen3-tts-instruct-flash",
        {
            "speaker": "Bella",
            "voice_description": "性别：女性，年龄感：儿童，音调：偏高，语速：中速，情绪：紧张，特点：沙哑烟嗓、苍老、浑厚，用途：有声书角色对白",
            "segment_speaker": "萌萌",
            "segment_type": "dialogue",
        },
        "tense",
    )

    instructions = control.provider_fields["instructions"]
    voice_description = instructions.split("声音描述：", 1)[1].split("；", 1)[0]

    assert "特点：稚嫩、甜美" in voice_description
    assert "沙哑烟嗓" not in voice_description
    assert "苍老" not in voice_description
    assert "浑厚" not in voice_description
    assert any("音质" in warning for warning in control.warnings)


def test_magnetic_voice_reports_childlike_timbre_conflicts() -> None:
    control = build_model_style_control(
        "qwen3-tts-instruct-flash",
        {
            "speaker": "Vincent",
            "voice_description": "性别：男性，年龄感：中年，音调：偏低，语速：中速，情绪：沉稳，特点：清脆童声、稚嫩、甜美，用途：有声书角色对白",
            "segment_speaker": "田叔",
            "segment_type": "dialogue",
        },
        "calm",
    )

    instructions = control.provider_fields["instructions"]
    voice_description = instructions.split("声音描述：", 1)[1].split("；", 1)[0]

    assert "特点：沙哑、有磁性" in voice_description
    assert "清脆童声" not in voice_description
    assert "稚嫩" not in voice_description
    assert "甜美" not in voice_description
    assert any("音质" in warning for warning in control.warnings)


def test_voice_profile_prefers_catalog_metadata_over_style_defaults(monkeypatch) -> None:
    def fake_get_voice_entry(voice_id: str, model: str):
        assert voice_id == "Custom"
        assert model == "qwen3-tts-instruct-flash"
        return {
            "id": "Custom",
            "speaker": "Custom",
            "gender": "female",
            "style": "gentle",
            "description": "测试音色",
            "voice_profile": {
                "age_group": "老年",
                "pitch": "偏低",
                "pace": "缓慢",
                "emotion_baseline": "沉稳",
                "timbre_traits": ["苍老", "沙哑"],
                "recommended_use_cases": ["有声书旁白"],
                "avoid_use_cases": ["儿童角色"],
                "conflict_rules": [],
            },
        }

    monkeypatch.setattr(
        "app.services.audiobook.voice_description_policy.get_voice_entry",
        fake_get_voice_entry,
    )

    result = reconcile_voice_description_with_selected_voice(
        model="qwen3-tts-instruct-flash",
        voice_id="Custom",
        requested_description="性别：女性，年龄感：青年，音调：中音，情绪：平静，特点：温柔、亲切自然，用途：有声书角色对白",
        fallback_emotion="calm",
        fallback_use_case="有声书角色对白",
    )

    assert "年龄感：老年" in result.description
    assert "音调：偏低" in result.description
    assert "语速：缓慢" in result.description
    assert "特点：苍老、沙哑" in result.description
    assert any("年龄感" in warning for warning in result.warnings)


def test_narration_use_case_survives_selected_voice_reconciliation() -> None:
    control = build_model_style_control(
        "qwen3-tts-instruct-flash",
        {
            "speaker": "Neil",
            "voice_description": "性别：中性，年龄感：中年，音调：中低音，语速：缓慢，情绪：calm，特点：温和、舒缓，用途：有声书旁白",
            "segment_speaker": "旁白",
            "segment_type": "narration",
        },
        "calm",
    )

    instructions = control.provider_fields["instructions"]
    voice_description = instructions.split("声音描述：", 1)[1].split("；", 1)[0]

    assert "性别：男性" in voice_description
    assert "用途：有声书旁白" in voice_description
    assert "角色对白" not in voice_description
    assert any("性别" in warning for warning in control.warnings)
    assert not any("用途" in warning for warning in control.warnings)


def test_voice_manager_tts_params_include_voice_description_for_render_chain() -> None:
    profile = VoiceProfile(
        voice_id="hero",
        character_name="林晚",
        gender="female",
        age_group="young",
        personality="gentle",
        tts_speaker_id="Cherry",
        pitch_base=50,
        speed_base=1.0,
        volume_base=50,
    )

    params = profile.get_tts_params("calm")

    assert params["voice_description"].startswith("性别：女性，年龄感：青年")
    assert "音调：" in params["voice_description"]
    assert "语速：" in params["voice_description"]
    assert "情绪：calm" in params["voice_description"]
    assert "用途：有声书角色对白" in params["voice_description"]
