import os
import sys
from pathlib import Path
from typing import Any, Dict


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook.tts_style_control import build_model_style_control
from app.services.audiobook.voice_manager import VoiceProfile
from app.services.audiobook.voice_description_policy import reconcile_voice_description_with_selected_voice


def _pin_voice_entry(monkeypatch, entries: Dict[str, Dict[str, Any]]) -> None:
    """把策略读到的目录条目钉死在参数里。

    这些用例原本直读 shared/ 真实目录与画像 sidecar，画像一落地断言就跟着供应商的
    自动打标结果漂移；策略合同应当由固定画像验证，真实投影由打标画像目录测试覆盖。
    """

    def fake_get_voice_entry(voice_id: str, model: str):
        return entries.get(voice_id)

    monkeypatch.setattr(
        "app.services.audiobook.voice_description_policy.get_voice_entry",
        fake_get_voice_entry,
    )


def test_qwen_style_control_keeps_selected_voice_as_hard_constraint(monkeypatch) -> None:
    requested = "低沉中年男性，语速缓慢，适合纪录片解说"
    control = build_model_style_control(
        "qwen-audio-3.1-tts-flash",
        {
            "speaker": "yeqinghe_v3.1",
            "voice_description": requested,
            "segment_speaker": "林晚",
            "segment_type": "dialogue",
            "performance_notes": "压低声音，但吐字保持清晰。",
        },
        "calm",
    )

    instructions = control.provider_fields["instructions"]
    # yeqinghe_v3.1：目录标注 female / style=gentle（亲切、温柔），画像未标注年龄感与语速。
    _pin_voice_entry(
        monkeypatch,
        {
            "yeqinghe_v3.1": {
                "id": "yeqinghe_v3.1",
                "speaker": "yeqinghe_v3.1",
                "gender": "female",
                "style": "gentle",
                "description": "官方系统音色，亲切、温柔。",
                "voice_profile": {},
            }
        },
    )
    result = reconcile_voice_description_with_selected_voice(
        model="qwen-audio-3.1-tts-flash",
        voice_id="yeqinghe_v3.1",
        requested_description=requested,
        fallback_emotion="calm",
        fallback_use_case="有声书角色对白",
    )

    assert "声音描述：" not in instructions
    assert "女性" in result.description
    assert "男性" not in result.description
    assert "中年" not in result.description
    assert "年龄感" not in result.description
    assert "亲切自然" in result.description
    assert any("性别" in warning for warning in result.warnings)
    assert not any("年龄感" in warning for warning in result.warnings)


def _sweetgirl_entry() -> Dict[str, Any]:
    """甜妹音：目录 style=cute 推导出的音调与听感特点，作为策略的固定事实源。"""

    return {
        "id": "anyuqing_v3.1",
        "speaker": "anyuqing_v3.1",
        "gender": "female",
        "style": "cute",
        "description": "官方系统音色，甜妹。",
        "voice_profile": {
            "age_group": "儿童",
            "pitch": "偏高",
            "pace": "中速",
            "timbre_traits": ["稚嫩", "甜美"],
        },
    }


def test_selected_voice_corrects_pitch_and_dialogue_use_case_conflicts(monkeypatch) -> None:
    _pin_voice_entry(monkeypatch, {"anyuqing_v3.1": _sweetgirl_entry()})
    result = reconcile_voice_description_with_selected_voice(
        model="qwen-audio-3.1-tts-flash",
        voice_id="anyuqing_v3.1",
        requested_description="性别：女性，年龄感：儿童，音调：偏低，语速：缓慢，情绪：严肃，特点：浑厚、苍老，用途：纪录片解说",
        fallback_emotion="happy",
        fallback_use_case="有声书角色对白",
    )

    assert "音调：偏高" in result.description
    assert "用途：有声书角色对白" in result.description
    assert "纪录片解说" not in result.description
    assert any("音调" in warning for warning in result.warnings)
    assert any("用途" in warning for warning in result.warnings)


def test_childlike_voice_reports_rough_timbre_conflicts(monkeypatch) -> None:
    _pin_voice_entry(monkeypatch, {"anyuqing_v3.1": _sweetgirl_entry()})
    result = reconcile_voice_description_with_selected_voice(
        model="qwen-audio-3.1-tts-flash",
        voice_id="anyuqing_v3.1",
        requested_description="性别：女性，年龄感：儿童，音调：偏高，语速：中速，情绪：紧张，特点：沙哑烟嗓、苍老、浑厚，用途：有声书角色对白",
        fallback_emotion="tense",
        fallback_use_case="有声书角色对白",
    )

    assert "特点：稚嫩、甜美" in result.description
    assert "沙哑烟嗓" not in result.description
    assert "苍老" not in result.description
    assert "浑厚" not in result.description
    assert any("音质" in warning for warning in result.warnings)


def test_magnetic_voice_reports_childlike_timbre_conflicts(monkeypatch) -> None:
    _pin_voice_entry(
        monkeypatch,
        {
            "baianran_v3.1": {
                "id": "baianran_v3.1",
                "speaker": "baianran_v3.1",
                "gender": "female",
                "style": "magnetic",
                "description": "官方系统音色，低沉、浑厚、气声。",
                "voice_profile": {
                    "age_group": "中年",
                    "pitch": "偏低",
                    "pace": "中速",
                    "timbre_traits": ["沙哑", "有磁性"],
                },
            }
        },
    )
    result = reconcile_voice_description_with_selected_voice(
        model="qwen-audio-3.1-tts-flash",
        voice_id="baianran_v3.1",
        requested_description="性别：男性，年龄感：中年，音调：偏低，语速：中速，情绪：沉稳，特点：清脆童声、稚嫩、甜美，用途：有声书角色对白",
        fallback_emotion="calm",
        fallback_use_case="有声书角色对白",
    )

    assert "特点：沙哑、有磁性" in result.description
    assert "清脆童声" not in result.description
    assert "稚嫩" not in result.description
    assert "甜美" not in result.description
    assert any("音质" in warning for warning in result.warnings)


def test_voice_profile_prefers_catalog_metadata_over_style_defaults(monkeypatch) -> None:
    def fake_get_voice_entry(voice_id: str, model: str):
        assert voice_id == "Custom"
        assert model == "qwen-audio-3.1-tts-flash"
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
        model="qwen-audio-3.1-tts-flash",
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


def test_age_conflict_check_covers_every_taxonomy_label(monkeypatch) -> None:
    """年龄冲突判据必须跟着词表走，不能各自维护一张中文年龄表。"""

    def fake_get_voice_entry(voice_id: str, model: str):
        return {
            "id": voice_id,
            "speaker": voice_id,
            "gender": "male",
            "style": "calm",
            "description": "测试音色",
            "voice_profile": {"age_group": "青年", "timbre_traits": ["沉稳"]},
        }

    monkeypatch.setattr(
        "app.services.audiobook.voice_description_policy.get_voice_entry",
        fake_get_voice_entry,
    )

    result = reconcile_voice_description_with_selected_voice(
        model="qwen-audio-3.1-tts-flash",
        voice_id="MatureVoice",
        requested_description="性别：男性，年龄感：熟年，情绪：平静，特点：沉稳，用途：有声书角色对白",
        fallback_emotion="calm",
        fallback_use_case="有声书角色对白",
    )

    assert any("年龄感" in warning for warning in result.warnings)
    assert "年龄感：青年" in result.description


def test_pending_voice_profile_omits_unmeasured_clauses(monkeypatch) -> None:
    """目录条目没有 voice_profile 时，年龄感/语速子句必须整条省略。

    这段描述会进入 TTS 提示词，伪造的"青年/中速"会被模型当成音色事实。
    """

    def fake_get_voice_entry(voice_id: str, model: str):
        return {
            "id": voice_id,
            "speaker": voice_id,
            "gender": "female",
            "style": "gentle",
            "description": "亲切自然、温柔",
        }

    monkeypatch.setattr(
        "app.services.audiobook.voice_description_policy.get_voice_entry",
        fake_get_voice_entry,
    )

    result = reconcile_voice_description_with_selected_voice(
        model="qwen-audio-3.1-tts-flash",
        voice_id="PendingVoice",
        requested_description="",
        fallback_emotion="calm",
        fallback_use_case="有声书角色对白",
    )

    assert "性别：女性" in result.description
    assert "年龄感" not in result.description
    assert "语速" not in result.description
    assert "青年" not in result.description
    assert "中速" not in result.description
    assert result.warnings == []


def test_pending_voice_profile_keeps_requested_age_and_pace(monkeypatch) -> None:
    """画像未标注时保留用户自己写的年龄感/语速，而不是改写成伪造默认值。"""

    def fake_get_voice_entry(voice_id: str, model: str):
        return {
            "id": voice_id,
            "speaker": voice_id,
            "gender": "female",
            "style": "gentle",
            "description": "亲切自然、温柔",
        }

    monkeypatch.setattr(
        "app.services.audiobook.voice_description_policy.get_voice_entry",
        fake_get_voice_entry,
    )

    result = reconcile_voice_description_with_selected_voice(
        model="qwen-audio-3.1-tts-flash",
        voice_id="PendingVoice",
        requested_description="性别：女性，年龄感：老年，语速：缓慢，情绪：平静，特点：温柔，用途：有声书角色对白",
        fallback_emotion="calm",
        fallback_use_case="有声书角色对白",
    )

    assert "年龄感：老年" in result.description
    assert "语速：缓慢" in result.description
    assert not any("年龄感" in warning for warning in result.warnings)


def test_narration_use_case_survives_selected_voice_reconciliation() -> None:
    result = reconcile_voice_description_with_selected_voice(
        model="qwen-audio-3.1-tts-flash",
        voice_id="longsanshu_v3.1",
        requested_description="性别：中性，年龄感：中年，音调：中低音，语速：缓慢，情绪：calm，特点：温和、舒缓，用途：有声书旁白",
        fallback_emotion="calm",
        fallback_use_case="有声书旁白",
    )

    assert "性别：男性" in result.description
    assert "用途：有声书旁白" in result.description
    assert "角色对白" not in result.description
    assert any("性别" in warning for warning in result.warnings)
    assert not any("用途" in warning for warning in result.warnings)


def test_fixed_voice_prompt_drops_dynamic_description_fields_but_voice_design_keeps_them() -> None:
    description = (
        "性别：女性，年龄感：青年，音调：中低音，语速：缓慢，"
        "情绪：极度痛苦，特点：吐字清晰、气息稳定，用途：有声书角色对白"
    )

    fixed_control = build_model_style_control(
        "qwen-audio-3.1-tts-flash",
        {
            "speaker": "Cherry",
            "segment_type": "dialogue",
            "voice_description": description,
        },
        "sad",
    )
    design_control = build_model_style_control(
        "mimo-v2.5-tts-voicedesign",
        {"voice_description": description},
        "sad",
    )

    fixed_instructions = fixed_control.provider_fields["instructions"]
    design_prompt = design_control.messages[0]["content"]

    assert "声音描述：" not in fixed_instructions
    assert "性别：女性" not in fixed_instructions
    assert "年龄感：青年" not in fixed_instructions
    assert "语速：缓慢" in design_prompt
    assert "情绪：极度痛苦" in design_prompt


def test_voice_manager_tts_params_exclude_identity_description_from_render_chain() -> None:
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

    assert "voice_description" not in params
    assert "pitch" not in params
    assert "character_base_pitch" not in params
