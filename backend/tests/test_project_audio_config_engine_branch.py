"""引擎分支服务单元测试（纯 Python，无 DB 依赖）。"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")

from app.services.audiobook.project_audio_config import (
    ENGINE_BRANCH_KEYS,
    _SEED_KEY_MIGRATION_MAP,
    build_engine_config_snapshot,
    get_audio_fx,
    get_characters_for_model,
    get_engine_branch,
    get_scene_generation_preferences,
    resolve_engine_mode,
    set_audio_fx,
    set_characters_for_model,
    set_engine_branch,
)


# ——— Fixtures ———


def _legacy_top_level() -> dict:
    """构造含旧顶层数据的配置（engines 字段不存在）。"""
    return {
        "audio_engine_mode": "legacy_stems",
        "seed_audio_model": "seed-audio-1.0-multilingual",
        "characters": [
            {"character_id": 1, "name": "角色A", "voice_id": "v1"},
            {"character_id": 2, "name": "角色B", "voice_id": "v2"},
        ],
        "audio_fx": {"enable_sound_effects": True, "bgm_theme": "fantasy"},
        "tts_models": {
            "qwen-audio-3.1-tts-flash": {
                "characters": [
                    {"character_id": 1, "name": "角色A", "voice_id": "v1_tts"},
                ]
            },
        },
    }


def _seed_config_with_engines() -> dict:
    """构造已含 seed_scene 引擎分支的配置。"""
    return {
        "audio_engine_mode": "seed_scene",
        "seed_audio_model": "seed-audio-1.0-multilingual",
        "engines": {
            "seed_scene": {
                "tts_models": {
                    "seed-audio-1.0-multilingual": {
                        "characters": [
                            {"character_id": 1, "name": "角色A", "voice_id": "seed_v1"},
                        ]
                    },
                },
                "audio_fx": {"enable_sound_effects": True, "bgm_theme": "scifi"},
                "scene_generation_preferences": {
                    "music_enabled": True,
                    "soundscape_intensity": "high",
                },
            },
            "legacy_stems": {
                "tts_models": {
                    "qwen-audio-3.1-tts-flash": {
                        "characters": [
                            {"character_id": 1, "name": "角色A", "voice_id": "legacy_v1"},
                        ]
                    },
                },
                "audio_fx": {"enable_sound_effects": True, "bgm_theme": "fantasy"},
            },
        },
    }


# ——— get_engine_branch ———


class TestGetEngineBranch:
    def test_legacy_fallback_readonly(self):
        """旧顶层归一化为 legacy_stems 分支（只读回退，不就地改写）。"""
        config = _legacy_top_level()
        branch = get_engine_branch(config, "legacy_stems")

        assert "characters" in branch
        assert len(branch["characters"]) == 2
        assert "tts_models" in branch
        assert "audio_fx" in branch
        # 不就地改写
        assert "engines" not in config

    def test_seed_scene_returns_empty_when_no_branch(self):
        """seed_scene 无分支数据时返回空字典。"""
        config = _legacy_top_level()
        branch = get_engine_branch(config, "seed_scene")
        assert branch == {}

    def test_returns_exact_branch(self):
        """engines.{mode} 存在时精确返回分支内容。"""
        config = _seed_config_with_engines()
        branch = get_engine_branch(config, "seed_scene")
        assert branch["tts_models"]["seed-audio-1.0-multilingual"]["characters"][0]["voice_id"] == "seed_v1"
        assert branch["audio_fx"]["bgm_theme"] == "scifi"
        assert branch["scene_generation_preferences"]["soundscape_intensity"] == "high"

    def test_legacy_branch_from_engines(self):
        """legacy_stems 分支已存在于 engines 时优先返回引擎分支。"""
        config = _seed_config_with_engines()
        branch = get_engine_branch(config, "legacy_stems")
        assert branch["tts_models"]["qwen-audio-3.1-tts-flash"]["characters"][0]["voice_id"] == "legacy_v1"


# ——— set_engine_branch ———


class TestSetEngineBranch:
    def test_write_and_read_back(self):
        """写入引擎分支后 get_engine_branch 返回一致。"""
        config: dict = {}
        branch_data = {
            "tts_models": {
                "qwen-audio-3.1-tts-flash": {
                    "characters": [{"character_id": 1, "name": "X", "voice_id": "vx"}],
                }
            },
        }
        set_engine_branch(config, "legacy_stems", branch_data)
        assert "engines" in config
        assert "legacy_stems" in config["engines"]
        read_back = get_engine_branch(config, "legacy_stems")
        assert read_back["tts_models"]["qwen-audio-3.1-tts-flash"]["characters"][0]["voice_id"] == "vx"

    def test_raises_on_invalid_mode(self):
        """不支持的 engine_mode 抛出 ValueError。"""
        with pytest.raises(ValueError):
            set_engine_branch({}, "invalid_mode", {})

    def test_empty_branch_clears(self):
        """传入空字典创建空分支。"""
        config = _seed_config_with_engines()
        set_engine_branch(config, "legacy_stems", {})
        branch = get_engine_branch(config, "legacy_stems")
        assert branch == {}


# ——— resolve_engine_mode ———


class TestResolveEngineMode:
    def test_auto_detects_seed_scene_via_old_top_level_keys(self):
        """auto 模式：旧顶层 seed 键存在时判定为 seed_scene。"""
        config = {
            "audio_engine_mode": "auto",
            "seed_timeline_mode": "fast",
        }
        assert resolve_engine_mode(config) == "seed_scene"

    def test_auto_detects_seed_scene_via_engines_branch(self):
        """auto 模式：engines.seed_scene 非空时判定为 seed_scene。"""
        config = {
            "audio_engine_mode": "auto",
            "engines": {"seed_scene": {"audio_fx": {}}},
        }
        assert resolve_engine_mode(config) == "seed_scene"

    def test_auto_falls_to_legacy_stems(self):
        """auto 模式：无 seed 证据时判定为 legacy_stems。"""
        config = {
            "audio_engine_mode": "auto",
            "audio_fx": {"enable_sound_effects": True},
        }
        assert resolve_engine_mode(config) == "legacy_stems"

    def test_explicit_mode_returned_directly(self):
        """非 auto 模式直接返回。"""
        config = {"audio_engine_mode": "seed_scene"}
        assert resolve_engine_mode(config) == "seed_scene"

        config = {"audio_engine_mode": "legacy_stems"}
        assert resolve_engine_mode(config) == "legacy_stems"

    def test_empty_config_defaults_to_legacy_stems(self):
        """空配置返回 legacy_stems。"""
        assert resolve_engine_mode({}) == "legacy_stems"

    def test_auto_with_empty_engines_no_keys(self):
        """auto + 空 engines 字段 + 无旧键 → legacy_stems。"""
        config = {
            "audio_engine_mode": "auto",
            "engines": {},
        }
        assert resolve_engine_mode(config) == "legacy_stems"


# ——— get_characters_for_model ———


class TestGetCharactersForModel:
    def test_branch_first_priority(self):
        """引擎分支 tts_models.{model}.characters 优先于旧顶层。"""
        config = _legacy_top_level()
        config["engines"] = {
            "legacy_stems": {
                "tts_models": {
                    "qwen-audio-3.1-tts-flash": {
                        "characters": [{"character_id": 99, "name": "分支角色", "voice_id": "branch_only"}],
                    }
                },
            },
        }
        result = get_characters_for_model(config, "qwen-audio-3.1-tts-flash", engine_mode="legacy_stems")
        assert len(result) == 1
        assert result[0]["character_id"] == 99

    def test_branch_fallback_to_top_level_legacy(self):
        """legacy_stems 分支无数据时回退旧顶层。"""
        config = _legacy_top_level()
        config["engines"] = {"legacy_stems": {}}
        result = get_characters_for_model(config, "qwen-audio-3.1-tts-flash", engine_mode="legacy_stems")
        # 应有顶层 tts_models.qwen-audio-3.1-tts-flash.characters 的数据
        assert len(result) >= 1

    def test_branch_fallback_to_top_level_characters(self):
        """legacy_stems 分支和 tts_models 整体不存在时回退顶层 characters。"""
        config = _legacy_top_level()
        config["engines"] = {"legacy_stems": {}}
        # 完全删除 tts_models 确保回退到顶层 characters
        del config["tts_models"]
        result = get_characters_for_model(config, "qwen-audio-3.1-tts-flash", engine_mode="legacy_stems")
        # 回退到顶层 characters
        assert len(result) == 2

    def test_seed_scene_returns_empty_when_no_data(self):
        """seed_scene 无数据且无旧顶层回退时返回空列表。"""
        config = _legacy_top_level()
        result = get_characters_for_model(config, "seed-audio-1.0-multilingual", engine_mode="seed_scene")
        assert result == []

    def test_none_engine_mode_old_behavior(self):
        """engine_mode=None 保持旧行为（从顶层读取）。"""
        config = _legacy_top_level()
        result = get_characters_for_model(config, "qwen-audio-3.1-tts-flash", engine_mode=None)
        assert len(result) >= 1

    def test_legacy_model_key_fallback(self):
        """分支内按旧键名回退读取。"""
        config = {
            "engines": {
                "legacy_stems": {
                    "tts_models": {
                        "minimax-speech-2.8": {
                            "characters": [{"character_id": 1, "name": "旧键角色", "voice_id": "old_key"}],
                        }
                    },
                },
            },
        }
        result = get_characters_for_model(config, "minimax-speech-2.8-hd", engine_mode="legacy_stems")
        assert len(result) == 1
        assert result[0]["voice_id"] == "old_key"


# ——— set_characters_for_model ———


class TestSetCharactersForModel:
    def test_writes_to_engine_branch(self):
        """写入引擎分支成功，get 读取一致。"""
        config: dict = {}
        chars = [{"character_id": 1, "name": "新角色", "voice_id": "new_v1"}]
        set_characters_for_model(config, "qwen-audio-3.1-tts-flash", chars, engine_mode="legacy_stems")
        result = get_characters_for_model(config, "qwen-audio-3.1-tts-flash", engine_mode="legacy_stems")
        assert len(result) == 1
        assert result[0]["voice_id"] == "new_v1"

    def test_mirrors_to_top_level_for_legacy_default_model(self):
        """legacy_stems + 默认模型时镜像顶层 characters。"""
        config: dict = {}
        chars = [{"character_id": 1, "name": "兼容角色", "voice_id": "compat_v1"}]
        set_characters_for_model(config, "qwen-audio-3.1-tts-flash", chars, engine_mode="legacy_stems")
        assert "characters" in config
        assert config["characters"][0]["voice_id"] == "compat_v1"

    def test_no_mirror_for_non_default_model(self):
        """非默认模型（不归一到默认模型）不镜像顶层。"""
        config: dict = {}
        chars = [{"character_id": 1, "name": "非默认", "voice_id": "non_default"}]
        # 使用 minimax-speech-2.8-hd，它归一化为 MINIMAX_SPEECH_28_HD_MODEL，不等于默认模型
        set_characters_for_model(config, "minimax-speech-2.8-hd", chars, engine_mode="legacy_stems")
        assert "characters" not in config

    def test_no_mirror_for_seed_scene(self):
        """seed_scene 分支不镜像顶层。"""
        config: dict = {}
        chars = [{"character_id": 1, "name": "种子角色", "voice_id": "seed_v1"}]
        set_characters_for_model(config, "qwen-audio-3.1-tts-flash", chars, engine_mode="seed_scene")
        assert "characters" not in config

    def test_none_engine_mode_writes_to_top_level(self):
        """engine_mode=None 写旧顶层。"""
        config: dict = {}
        chars = [{"character_id": 1, "name": "旧顶层", "voice_id": "old_top"}]
        set_characters_for_model(config, "qwen-audio-3.1-tts-flash", chars, engine_mode=None)
        assert "characters" in config
        assert "tts_models" in config


# ——— get_audio_fx ———


class TestGetAudioFx:
    def test_reads_from_engine_branch(self):
        """引擎分支 audio_fx 优先于旧顶层。"""
        config = _legacy_top_level()
        config["engines"] = {
            "legacy_stems": {"audio_fx": {"enable_sound_effects": False, "bgm_theme": "branch"}},
        }
        fx = get_audio_fx(config, engine_mode="legacy_stems")
        assert fx is not None
        assert fx["bgm_theme"] == "branch"
        assert fx["enable_sound_effects"] is False

    def test_fallback_to_top_level_legacy(self):
        """legacy_stems 分支无 audio_fx 时回退旧顶层。"""
        config = _legacy_top_level()
        config["engines"] = {"legacy_stems": {}}
        fx = get_audio_fx(config, engine_mode="legacy_stems")
        assert fx is not None
        assert fx["bgm_theme"] == "fantasy"

    def test_seed_scene_no_fallback(self):
        """seed_scene 分支无 audio_fx 时返回 None（不回退旧顶层）。"""
        config = _legacy_top_level()
        config["engines"] = {"seed_scene": {}}
        fx = get_audio_fx(config, engine_mode="seed_scene")
        assert fx is None

    def test_none_mode_old_behavior(self):
        """engine_mode=None 从顶层读取。"""
        config = _legacy_top_level()
        fx = get_audio_fx(config, engine_mode=None)
        assert fx is not None
        assert fx["bgm_theme"] == "fantasy"


# ——— set_audio_fx ———


class TestSetAudioFx:
    def test_writes_to_engine_branch(self):
        """写入引擎分支后 get_audio_fx 读取一致。"""
        config: dict = {}
        set_audio_fx(config, {"enable_sound_effects": True, "bgm_theme": "mystery"}, engine_mode="legacy_stems")
        fx = get_audio_fx(config, engine_mode="legacy_stems")
        assert fx["bgm_theme"] == "mystery"

    def test_does_not_write_top_level(self):
        """引擎模式下停止写旧顶层。"""
        config: dict = {}
        set_audio_fx(config, {"enable_sound_effects": True}, engine_mode="legacy_stems")
        assert "audio_fx" not in config


# ——— get_scene_generation_preferences ———


class TestGetSceneGenerationPreferences:
    def test_reads_from_branch(self):
        """从引擎分支正确读取 scene_generation_preferences。"""
        config = _seed_config_with_engines()
        prefs = get_scene_generation_preferences(config, "seed_scene")
        assert prefs.get("music_enabled") is True
        assert prefs.get("soundscape_intensity") == "high"

    def test_legacy_stems_returns_empty(self):
        """legacy_stems 分支返回空字典。"""
        config = _legacy_top_level()
        prefs = get_scene_generation_preferences(config, "legacy_stems")
        assert prefs == {}

    def test_old_key_migration(self):
        """旧顶层 seed 键通过迁移映射回退到 scene_generation_preferences。"""
        config = {
            "seed_timeline_mode": "fast",
            "seed_terminal_policy": "auto_approve",
            "semantic_review_enabled": True,
            "semantic_review_mode": "strict",
        }
        prefs = get_scene_generation_preferences(config, "seed_scene")
        assert prefs.get("scene_generation_preferences", {}).get("timeline_mode") == "fast"
        assert prefs.get("scene_generation_preferences", {}).get("terminal_policy") == "auto_approve"
        assert prefs.get("scene_generation_preferences", {}).get("semantic_review_enabled") is True
        assert prefs.get("scene_generation_preferences", {}).get("semantic_review_mode") == "strict"

    def test_branch_prefs_override_old_keys(self):
        """分支内已有值不受旧键覆盖（旧键迁移仅在分支无该字段时生效）。"""
        config = {
            "seed_timeline_mode": "fast",
            "engines": {
                "seed_scene": {
                    "scene_generation_preferences": {
                        "timeline_mode": "natural",
                    },
                },
            },
        }
        prefs = get_scene_generation_preferences(config, "seed_scene")
        # 分支顶层保留 timeline_mode: "natural"
        assert prefs.get("timeline_mode") == "natural"


# ——— SceneGenerationPreferences ———


class TestSetSceneGenerationPreferences:
    def test_writes_to_seed_scene(self):
        """写入 seed_scene 分支成功。"""
        from app.services.audiobook.project_audio_config import set_scene_generation_preferences

        config: dict = {}
        prefs = {"music_enabled": False, "soundscape_intensity": "low"}
        set_scene_generation_preferences(config, "seed_scene", prefs)
        read_back = get_scene_generation_preferences(config, "seed_scene")
        assert read_back.get("music_enabled") is False
        assert read_back.get("soundscape_intensity") == "low"

    def test_raises_on_legacy_stems(self):
        """非 seed_scene 模式抛出 ValueError。"""
        from app.services.audiobook.project_audio_config import set_scene_generation_preferences

        with pytest.raises(ValueError):
            set_scene_generation_preferences({}, "legacy_stems", {})


# ——— build_engine_config_snapshot ———


class TestBuildEngineConfigSnapshot:
    def test_contains_fingerprint(self):
        """快照包含 engine_config_fingerprint（sha256）。"""
        config = _seed_config_with_engines()
        snapshot = build_engine_config_snapshot(config, "seed_scene")
        assert "engine_config_fingerprint" in snapshot
        fp = snapshot["engine_config_fingerprint"]
        assert isinstance(fp, str)
        assert len(fp) == 64  # sha256 hex

    def test_fingerprint_deterministic(self):
        """相同输入产生相同 fingerprint。"""
        config = _legacy_top_level()
        s1 = build_engine_config_snapshot(config, "legacy_stems")
        s2 = build_engine_config_snapshot(config, "legacy_stems")
        assert s1["engine_config_fingerprint"] == s2["engine_config_fingerprint"]

    def test_fingerprint_differs_by_mode(self):
        """不同 engine_mode 产生不同 fingerprint。"""
        config = _legacy_top_level()
        s_legacy = build_engine_config_snapshot(config, "legacy_stems")
        s_seed = build_engine_config_snapshot(config, "seed_scene")
        assert s_legacy["engine_config_fingerprint"] != s_seed["engine_config_fingerprint"]

    def test_contains_required_fields(self):
        """快照包含所有必要字段。"""
        config = _legacy_top_level()
        snapshot = build_engine_config_snapshot(config, "legacy_stems")
        assert snapshot["snapshot_version"] == 1
        assert snapshot["engine_mode"] == "legacy_stems"
        assert "engine_branch_config" in snapshot
        assert "captured_at" in snapshot
        assert "source_audio_config_hash" in snapshot
        assert snapshot["migrated_at"] is None

    def test_engine_branch_config_contains_providers_and_seed_audio_model(self):
        """engine_branch_config 包含 providers 和 seed_audio_model。"""
        config = _legacy_top_level()
        snapshot = build_engine_config_snapshot(config, "legacy_stems")
        ebc = snapshot["engine_branch_config"]
        assert "providers" in ebc
        assert ebc["providers"]["seed_provider"] == "dashscope_seed"
        assert "seed_audio_model" in ebc


# ——— ENGINE_BRANCH_KEYS ———


class TestEngineBranchKeys:
    def test_branch_keys_defined(self):
        """ENGINE_BRANCH_KEYS 定义正确。"""
        assert "tts_models" in ENGINE_BRANCH_KEYS
        assert "audio_fx" in ENGINE_BRANCH_KEYS
        assert "scene_generation_preferences" in ENGINE_BRANCH_KEYS


# ——— _SEED_KEY_MIGRATION_MAP ———


class TestSeedKeyMigrationMap:
    def test_migration_map_defined(self):
        """映射字典定义正确。"""
        assert "seed_timeline_mode" in _SEED_KEY_MIGRATION_MAP
        assert _SEED_KEY_MIGRATION_MAP["seed_timeline_mode"] == ("scene_generation_preferences", "timeline_mode")
        assert _SEED_KEY_MIGRATION_MAP["semantic_review_enabled"] == ("scene_generation_preferences", "semantic_review_enabled")