"""角色音配置解析失败必须显式拒单，不再静默降级为自动分配。

背景（2026-10-11 退役复核）：``VoiceManager.apply_project_voice_mapping`` 在
``_resolve_voice_config_for_model`` 解析不到音色时只 ``logger.warning`` 后
``continue``，角色因此不进入 ``character_voices``，下游
``_script_utils_mixin`` / ``segment_preview_service`` 会 ``assign_voice()`` 自动
另配一条声线。用户明确指定的音色被换掉，整本书少一条声线而任务显示成功 ——
这是退役教义下最后一个还活着的静默降质面。

覆盖：
- 未知音色（含退役声线名）拒单，错误消息列出**全部**越界角色；
- 拒单是整批原子的：同批合法角色也不落库，避免半套配置继续生成；
- 用户显式指定 ``tts_model`` 且该模型目录查无此音色 → 拒单；
- 模型来自智能推荐（用户只给音色）时先回退默认模型解析，回退成功不落错误；
- 自定义音色前缀委派失败（``mimo_design:`` 等）同样拒单且理由可辨；
- ``load_from_db`` 与 ``apply_project_voice_mapping`` 口径一致；
- 调用点不再吞掉该异常（共享层 helper + 剧本阶段）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook import voice_manager_factory
from app.services.audiobook.project_audio_runtime import apply_runtime_voice_mapping
from app.services.audiobook.tts_model_ids import (
    DEFAULT_AUDIOBOOK_TTS_MODEL,
    MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    MINIMAX_SPEECH_28_HD_MODEL,
)
from app.services.audiobook.voice_manager import (
    VoiceManager,
    VoiceMappingResolutionError,
)

VALID_DEFAULT_VOICE = "longanhuan_v3.1"
RETIRED_VOICE = "Neil"


def test_unknown_voice_id_raises_instead_of_silent_skip() -> None:
    manager = VoiceManager()

    with pytest.raises(VoiceMappingResolutionError, match=RETIRED_VOICE):
        manager.apply_project_voice_mapping({"配角甲": {"voice_id": RETIRED_VOICE}})

    assert manager.get_voice("配角甲") is None


def test_error_lists_every_offending_character() -> None:
    manager = VoiceManager()

    with pytest.raises(VoiceMappingResolutionError) as excinfo:
        manager.apply_project_voice_mapping(
            {
                "配角甲": {"voice_id": RETIRED_VOICE},
                "配角乙": {"voice_id": "Ryan", "tts_model": DEFAULT_AUDIOBOOK_TTS_MODEL},
            }
        )

    message = str(excinfo.value)
    for needle in ("配角甲", "配角乙", RETIRED_VOICE, "Ryan", DEFAULT_AUDIOBOOK_TTS_MODEL):
        assert needle in message


def test_rejection_is_atomic_for_the_whole_batch() -> None:
    manager = VoiceManager()

    with pytest.raises(VoiceMappingResolutionError):
        manager.apply_project_voice_mapping(
            {
                "主角": {"voice_id": VALID_DEFAULT_VOICE},
                "配角甲": {"voice_id": RETIRED_VOICE},
            }
        )

    assert manager.get_voice("主角") is None
    assert manager.used_voice_ids == set()


def test_user_pinned_model_without_that_voice_raises() -> None:
    manager = VoiceManager()

    with pytest.raises(VoiceMappingResolutionError, match=MINIMAX_SPEECH_28_HD_MODEL):
        manager.apply_project_voice_mapping(
            {
                "主角": {
                    "voice_id": VALID_DEFAULT_VOICE,
                    "tts_model": MINIMAX_SPEECH_28_HD_MODEL,
                }
            }
        )


def test_recommended_model_mismatch_falls_back_to_default_resolution(monkeypatch) -> None:
    """用户只给音色、模型来自推荐：推荐模型目录没有该音色时回退默认模型解析。"""
    manager = VoiceManager()
    monkeypatch.setattr(
        voice_manager_factory,
        "suggest_model_for_character",
        lambda **kwargs: MINIMAX_SPEECH_28_HD_MODEL,
    )

    manager.apply_project_voice_mapping(
        {"主角": {"voice_id": VALID_DEFAULT_VOICE}},
        character_profiles=[{"name": "主角", "importance_level": "主角"}],
    )

    profile = manager.get_voice("主角")
    assert profile is not None
    assert profile.voice_id == VALID_DEFAULT_VOICE


def test_custom_asset_prefix_delegation_failure_raises() -> None:
    manager = VoiceManager()

    with pytest.raises(
        VoiceMappingResolutionError, match="mimo_design:missing-asset"
    ) as excinfo:
        manager.apply_project_voice_mapping(
            {
                "主角": {
                    "voice_id": "mimo_design:missing-asset",
                    "tts_model": MIMO_V25_TTS_VOICE_DESIGN_MODEL,
                }
            }
        )

    assert "自定义音色" in str(excinfo.value)


def test_valid_mapping_still_applies_with_params() -> None:
    manager = VoiceManager()

    manager.apply_project_voice_mapping(
        {"主角": {"voice_id": "male-qn-qingse", "tts_model": MINIMAX_SPEECH_28_HD_MODEL, "volume": 58}}
    )

    profile = manager.get_voice("主角")
    assert profile is not None
    assert profile.tts_model == MINIMAX_SPEECH_28_HD_MODEL
    assert profile.volume_base == 58


def test_empty_voice_id_stays_auto_assignment_not_rejected() -> None:
    """未显式配置音色 = 保留自动分配，不属于解析失败。"""
    manager = VoiceManager()

    manager.apply_project_voice_mapping({"主角": {"voice_id": "", "volume": 50}})

    assert manager.get_voice("主角") is None


def test_load_from_db_raises_on_unknown_voice() -> None:
    manager = VoiceManager()

    with pytest.raises(VoiceMappingResolutionError, match=RETIRED_VOICE):
        manager.load_from_db({"配角甲": {"voice_id": RETIRED_VOICE}})


def test_apply_runtime_voice_mapping_propagates_resolution_failure() -> None:
    class Exploding:
        def apply_project_voice_mapping(self, mapping):
            raise VoiceMappingResolutionError("角色 配角甲 的音色 Neil 无法解析")

    with pytest.raises(VoiceMappingResolutionError, match="配角甲"):
        apply_runtime_voice_mapping(
            voice_manager=Exploding(),
            voice_mapping={"配角甲": {"voice_id": RETIRED_VOICE}},
        )


def test_apply_runtime_voice_mapping_passes_profiles_through() -> None:
    seen = {}

    class Recorder:
        def apply_project_voice_mapping(self, mapping, character_profiles=None):
            seen["mapping"] = mapping
            seen["character_profiles"] = character_profiles

    apply_runtime_voice_mapping(
        voice_manager=Recorder(),
        voice_mapping={"主角": {"voice_id": VALID_DEFAULT_VOICE}},
        character_profiles=[{"name": "主角"}],
    )

    assert seen["character_profiles"] == [{"name": "主角"}]


def test_script_stage_project_audio_config_does_not_swallow_failure(monkeypatch) -> None:
    from app.services.audiobook import background_jobs_scripts

    engine = SimpleNamespace(
        voice_manager=SimpleNamespace(
            apply_project_voice_mapping=lambda *args, **kwargs: (_ for _ in ()).throw(
                VoiceMappingResolutionError("角色 配角甲 的音色 Neil 无法解析")
            )
        ),
        apply_scene_audio_runtime_config=lambda **kwargs: None,
    )
    runtime_config = SimpleNamespace(
        voice_mapping={"配角甲": {"voice_id": RETIRED_VOICE}},
        audio_fx={},
        audio_engine_mode="classic",
        seed_audio_model=None,
        character_items=[],
    )
    monkeypatch.setattr(
        background_jobs_scripts,
        "resolve_project_audio_runtime_config",
        lambda *args, **kwargs: runtime_config,
    )

    with pytest.raises(VoiceMappingResolutionError, match="配角甲"):
        background_jobs_scripts._apply_script_stage_project_audio_config(
            engine=engine,
            project=SimpleNamespace(),
            tts_model=DEFAULT_AUDIOBOOK_TTS_MODEL,
            character_profiles=[],
        )
