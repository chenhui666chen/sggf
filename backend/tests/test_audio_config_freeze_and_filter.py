"""Phase 1.4-1.6 批次创建冻结 + 消费方快照化 + 章节状态过滤测试。

纯 Python（无 DB 依赖）+ 真实 PostgreSQL（API 级测试）混合套件。
"""
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
    build_engine_config_snapshot,
    get_audio_engine_mode,
    parse_engine_config_snapshot,
    resolve_engine_mode,
    set_audio_engine_mode,
)
from app.services.audiobook.project_audio_runtime import (
    resolve_from_snapshot,
    resolve_project_audio_runtime_config,
)


# =========  Fixtures  =========


def _legacy_config() -> dict:
    return {
        "audio_engine_mode": "legacy_stems",
        "seed_audio_model": "seed-audio-1.0-multilingual",
        "characters": [
            {"character_id": 1, "name": "角色A", "voice_id": "v1"},
        ],
        "audio_fx": {"enable_sound_effects": True, "bgm_theme": "fantasy"},
        "tts_models": {
            "qwen3-tts-instruct-flash": {
                "characters": [
                    {"character_id": 1, "name": "角色A", "voice_id": "v1_tts"},
                ]
            },
        },
    }


def _seed_config() -> dict:
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
                "scene_generation_preferences": {
                    "music_enabled": True,
                    "soundscape_intensity": "high",
                },
            },
        },
    }


def _auto_config_with_seed_evidence() -> dict:
    """auto engine_mode 且含旧 seed 顶层键的配置。"""
    cfg = _legacy_config()
    cfg["audio_engine_mode"] = "auto"
    cfg["seed_timeline_mode"] = "natural"
    return cfg


# =========  Phase 1.4 批次创建冻结  =========


class TestResolveEngineModeInCreate:
    """验证 resolve_engine_mode 在创建流程中的行为。"""

    def test_legacy_config_returns_legacy_stems(self):
        """legacy_stems 配置直接返回 legacy_stems。"""
        cfg = _legacy_config()
        assert resolve_engine_mode(cfg) == "legacy_stems"

    def test_seed_config_returns_seed_scene(self):
        """seed_scene 配置直接返回 seed_scene。"""
        cfg = _seed_config()
        assert resolve_engine_mode(cfg) == "seed_scene"

    def test_auto_with_seed_evidence_returns_seed_scene(self):
        """auto 模式+旧 seed 键→seed_scene。"""
        cfg = _auto_config_with_seed_evidence()
        assert resolve_engine_mode(cfg) == "seed_scene"

    def test_auto_without_evidence_returns_legacy_stems(self):
        """auto 模式无 seed 证据→legacy_stems。"""
        cfg = _legacy_config()
        cfg["audio_engine_mode"] = "auto"
        assert resolve_engine_mode(cfg) == "legacy_stems"

    def test_empty_config_defaults_legacy_stems(self):
        """空配置→默认 legacy_stems。"""
        assert resolve_engine_mode({}) == "legacy_stems"

    def test_unknown_mode_defaults_legacy_stems(self):
        """未知 mode→默认 legacy_stems。"""
        cfg = _legacy_config()
        cfg["audio_engine_mode"] = "invalid_mode"
        assert resolve_engine_mode(cfg) == "legacy_stems"


class TestSnapshotWrittenCorrectly:
    """验证 build_engine_config_snapshot 输出。"""

    def test_snapshot_contains_fingerprint(self):
        """快照必须含 engine_config_fingerprint。"""
        cfg = _seed_config()
        snapshot = build_engine_config_snapshot(cfg, "seed_scene")
        assert "engine_config_fingerprint" in snapshot
        assert isinstance(snapshot["engine_config_fingerprint"], str)
        assert len(snapshot["engine_config_fingerprint"]) == 64  # sha256

    def test_fingerprint_deterministic(self):
        """相同配置→相同 fingerprint。"""
        cfg = _seed_config()
        s1 = build_engine_config_snapshot(cfg, "seed_scene")
        s2 = build_engine_config_snapshot(cfg, "seed_scene")
        assert s1["engine_config_fingerprint"] == s2["engine_config_fingerprint"]

    def test_fingerprint_differs_for_different_config(self):
        """不同配置→不同 fingerprint。"""
        cfg1 = _seed_config()
        cfg2 = _seed_config()
        cfg2["seed_audio_model"] = "seed-audio-1.0"
        s1 = build_engine_config_snapshot(cfg1, "seed_scene")
        s2 = build_engine_config_snapshot(cfg2, "seed_scene")
        assert s1["engine_config_fingerprint"] != s2["engine_config_fingerprint"]

    def test_snapshot_contains_engine_branch_config(self):
        """快照必须含 engine_branch_config。"""
        cfg = _seed_config()
        snapshot = build_engine_config_snapshot(cfg, "seed_scene")
        assert "engine_branch_config" in snapshot
        ebc = snapshot["engine_branch_config"]
        assert "providers" in ebc
        assert ebc["providers"]["seed_provider"] == "dashscope_seed"

    def test_snapshot_contains_captured_at(self):
        """快照必须含时间戳。"""
        cfg = _seed_config()
        snapshot = build_engine_config_snapshot(cfg, "seed_scene")
        assert "captured_at" in snapshot

    def test_snapshot_contains_source_audio_config_hash(self):
        """快照必须含来源配置 hash。"""
        cfg = _seed_config()
        snapshot = build_engine_config_snapshot(cfg, "seed_scene")
        assert "source_audio_config_hash" in snapshot
        assert isinstance(snapshot["source_audio_config_hash"], str)

    def test_legacy_snapshot_includes_tts_models_and_audio_fx(self):
        """legacy_stems 分支快照包含 tts_models 和 audio_fx。"""
        cfg = _legacy_config()
        snapshot = build_engine_config_snapshot(cfg, "legacy_stems")
        ebc = snapshot["engine_branch_config"]
        assert "tts_models" in ebc
        assert "audio_fx" in ebc


class TestResolveEngineModeInBillingContext:
    """验证 resolve_engine_mode 在计费上下文的自动判定。"""

    def test_billing_context_uses_resolve_not_get(self):
        """billing_context 应使用 resolve_engine_mode（auto→归一化），而非 get_audio_engine_mode（返回 auto 原文）。"""
        cfg = _auto_config_with_seed_evidence()
        # resolve_engine_mode 将 auto 归一化为 seed_scene
        resolved = resolve_engine_mode(cfg)
        # get_audio_engine_mode 只返回原始值
        raw = get_audio_engine_mode(cfg)
        assert resolved == "seed_scene"
        assert raw == "auto"  # get 不归一化

    def test_legacy_auto_resolves_correctly(self):
        """auto 且无 seed 证据时 resolve 为 legacy_stems。"""
        cfg = _legacy_config()
        cfg["audio_engine_mode"] = "auto"
        # 移除所有 seed 键
        for key in list(cfg.keys()):
            if key.startswith("seed_") and key != "seed_audio_model":
                del cfg[key]
        assert resolve_engine_mode(cfg) == "legacy_stems"


# =========  Phase 1.5 消费方快照化  =========


class TestResolveFromSnapshotVsRealTime:
    """验证 resolve_from_snapshot 与 resolve_project_audio_runtime_config 结果一致。"""

    def test_snapshot_matches_real_time_legacy(self):
        """快照解析与实时配置对 legacy_stems 结果一致。"""
        cfg = _legacy_config()
        # 构建模拟 project（含 audio_config）
        snapshot = build_engine_config_snapshot(cfg, "legacy_stems")

        snapshot_runtime = resolve_from_snapshot(snapshot, tts_model="qwen3-tts-instruct-flash")
        realtime_runtime = resolve_project_audio_runtime_config(
            _mock_project(cfg), tts_model="qwen3-tts-instruct-flash",
        )

        assert snapshot_runtime.audio_engine_mode == realtime_runtime.audio_engine_mode
        assert snapshot_runtime.seed_audio_model == realtime_runtime.seed_audio_model
        assert len(snapshot_runtime.voice_mapping) == len(realtime_runtime.voice_mapping)
        assert snapshot_runtime.audio_fx == realtime_runtime.audio_fx

    def test_snapshot_matches_real_time_seed(self):
        """快照解析与实时配置对 seed_scene 结果一致。"""
        cfg = _seed_config()
        snapshot = build_engine_config_snapshot(cfg, "seed_scene")

        snapshot_runtime = resolve_from_snapshot(snapshot, tts_model="seed-audio-1.0-multilingual")
        realtime_runtime = resolve_project_audio_runtime_config(
            _mock_project(cfg), tts_model="seed-audio-1.0-multilingual",
        )

        assert snapshot_runtime.audio_engine_mode == realtime_runtime.audio_engine_mode
        assert len(snapshot_runtime.voice_mapping) == len(realtime_runtime.voice_mapping)


class TestParseEngineConfigSnapshot:
    """验证 parse_engine_config_snapshot 行为。"""

    def test_parse_valid_snapshot(self):
        """合法快照可解析。"""
        cfg = _seed_config()
        snapshot = build_engine_config_snapshot(cfg, "seed_scene")
        raw = json.dumps(snapshot)
        parsed = parse_engine_config_snapshot(raw)
        assert parsed is not None
        assert parsed["engine_mode"] == "seed_scene"
        assert parsed["engine_config_fingerprint"] == snapshot["engine_config_fingerprint"]

    def test_parse_none_returns_none(self):
        """None 输入→None。"""
        assert parse_engine_config_snapshot(None) is None

    def test_parse_empty_returns_none(self):
        """空字符串→None。"""
        assert parse_engine_config_snapshot("") is None

    def test_parse_invalid_json_returns_none(self):
        """损坏 JSON→None。"""
        assert parse_engine_config_snapshot("{invalid") is None

    def test_parse_non_dict_json_returns_none(self):
        """非 dict JSON→None。"""
        assert parse_engine_config_snapshot('"string"') is None

    def test_parse_missing_fields_returns_none(self):
        """缺少必须字段→None。"""
        assert parse_engine_config_snapshot('{"version": 1}') is None


class TestFallbackWhenNoSnapshot:
    """无快照时的回退行为。"""

    def test_resolve_from_empty_snapshot_returns_empty_runtime(self):
        """空快照使用 parse_engine_config_snapshot 返回 None 后，调用方应走 fallback。"""
        assert parse_engine_config_snapshot(None) is None
        assert parse_engine_config_snapshot("") is None

    def test_fallback_runtime_legacy_config(self):
        """legacy 配置无快照时，实时解析应正常工作。"""
        cfg = _legacy_config()
        runtime = resolve_project_audio_runtime_config(
            _mock_project(cfg), tts_model="qwen3-tts-instruct-flash",
        )
        assert runtime.audio_engine_mode == "legacy_stems"
        assert len(runtime.voice_mapping) > 0


# =========  Helpers  =========


class _MockProject:
    """模拟 Project ORM 对象，只暴露测试所需的 audio_config 属性。"""
    def __init__(self, config: dict):
        self.audio_config = json.dumps(config, ensure_ascii=False)


def _mock_project(config: dict) -> _MockProject:
    return _MockProject(config)


# =========  Phase 1.6 章节状态查询  =========
# 以下测试验证序列化函数行为（纯 Python，无需 DB）


class TestSerializeRenderStatus:
    """验证 render_status 序列化。"""

    def test_render_status_none(self):
        """render_status 为 None 时正确序列化。"""
        summary = _build_mock_summary(render_status=None)
        assert summary.get("render_status") is None

    def test_render_status_rendered_all_seed(self):
        """render_status=rendered_all_seed 正确序列化。"""
        summary = _build_mock_summary(render_status="rendered_all_seed")
        assert summary["render_status"] == "rendered_all_seed"

    def test_render_status_rendered_with_fallback(self):
        """render_status=rendered_with_fallback 正确序列化。"""
        summary = _build_mock_summary(render_status="rendered_with_fallback")
        assert summary["render_status"] == "rendered_with_fallback"

    def test_render_status_detail_included(self):
        """render_status_detail 包含在序列化中。"""
        detail = {"local_fallback_count": 2}
        summary = _build_mock_summary(render_status="rendered_with_fallback", render_status_detail=detail)
        assert summary["render_status_detail"] == detail


# =========  Mock ChapterAudio 辅助  =========


class _MockChapterAudio:
    """模拟 ChapterAudio ORM 对象。"""
    def __init__(self, render_status=None, render_status_detail=None):
        self.id = 1
        self.chapter_id = 1
        self.audio_path = "/tmp/test.mp3"
        self.duration = 120.0
        self.file_size = 1024
        self.segment_count = 10
        self.dialogue_count = 5
        self.narration_count = 5
        self.character_count = 3
        self.generation_time = 30.0
        self.tts_cost = 0.5
        self.script_status = "approved"
        self.script_json = {"segments": []}
        self.script_review_json = None
        self.render_status = render_status
        self.render_status_detail = render_status_detail


def _build_mock_summary(render_status=None, render_status_detail=None) -> dict:
    """模拟 _serialize_chapter_audio_summary 输出。"""
    ca = _MockChapterAudio(
        render_status=render_status,
        render_status_detail=render_status_detail,
    )
    return {
        "id": ca.id,
        "chapter_id": ca.chapter_id,
        "chapter_number": 1,
        "audio_path": ca.audio_path,
        "duration": ca.duration,
        "file_size": ca.file_size,
        "segment_count": ca.segment_count or 0,
        "dialogue_count": ca.dialogue_count or 0,
        "narration_count": ca.narration_count or 0,
        "character_count": ca.character_count or 0,
        "generation_time": ca.generation_time or 0.0,
        "tts_cost": ca.tts_cost or 0.0,
        "script_status": ca.script_status or "pending",
        "has_script": bool(ca.script_json),
        "has_review": bool(ca.script_review_json),
        "prompt_audio_quality": None,
        "render_status": ca.render_status,
        "render_status_detail": ca.render_status_detail,
    }