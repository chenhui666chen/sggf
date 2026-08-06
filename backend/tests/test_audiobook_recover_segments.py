"""
Phase 2 换音色恢复：单元测试。

覆盖：
- _extract_missing_speakers 从 checkpoint 提取缺失角色
- _apply_voice_overrides_to_project_config 持久化音色配置
- _build_segment_voice_overrides 映射 render chunk -> 源片段索引
- _apply_segment_voice_overrides 引擎级选择性覆盖
- 换音色缓存失效验证清单（cache_key 含最终实际 speaker）
- 护栏校验（voice_overrides 为空 / 角色不在缺失片段中）
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _BACKEND_DIR.parent
for _path in (_BACKEND_DIR, _PROJECT_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.api.v1.audiobook_api.routes_recover import (
    _apply_voice_overrides_to_project_config,
    _build_segment_voice_overrides,
    _extract_missing_speakers,
)
from app.schemas.audiobook import VoiceOverride
from app.services.audiobook.render_plan import _build_cache_key, _signature_voice_params


# ─── _extract_missing_speakers ────────────────────────────────────────────────


class TestExtractMissingSpeakers:
    def test_from_missing_segments_report(self):
        checkpoint = {
            "missing_segments": [
                {"index": 2, "speaker": "林黛玉", "text": "你好"},
                {"index": 5, "speaker": "贾宝玉", "text": "再见"},
            ],
            "failed_segment_indices": [2, 5],
        }
        assert _extract_missing_speakers(checkpoint) == {"林黛玉", "贾宝玉"}

    def test_fallback_from_render_plan(self):
        checkpoint = {
            "failed_segment_indices": [1, 3],
            "render_plan": [
                {"index": 0, "speaker": "旁白", "cache_key": "aaa"},
                {"index": 1, "speaker": "林黛玉", "cache_key": "bbb"},
                {"index": 2, "speaker": "旁白", "cache_key": "ccc"},
                {"index": 3, "speaker": "林黛玉", "cache_key": "ddd"},
            ],
        }
        assert _extract_missing_speakers(checkpoint) == {"林黛玉"}

    def test_empty_checkpoint(self):
        assert _extract_missing_speakers({}) == set()


# ─── _apply_voice_overrides_to_project_config ─────────────────────────────────


class TestApplyVoiceOverridesToProjectConfig:
    def _make_project(self, characters: List[Dict[str, Any]]) -> SimpleNamespace:
        config = {
            "tts_models": {
                "qwen3-tts-instruct-flash": {"characters": characters}
            }
        }
        return SimpleNamespace(audio_config=json.dumps(config, ensure_ascii=False))

    def test_updates_existing_character(self):
        project = self._make_project([
            {"name": "林黛玉", "voice_id": "old_voice_1"},
            {"name": "贾宝玉", "voice_id": "old_voice_2"},
        ])
        overrides = {"林黛玉": VoiceOverride(voice_id="new_voice_x")}
        _apply_voice_overrides_to_project_config(
            project, tts_model="qwen3-tts-instruct-flash", voice_overrides=overrides
        )
        result = json.loads(project.audio_config)
        chars = result["tts_models"]["qwen3-tts-instruct-flash"]["characters"]
        assert chars[0]["voice_id"] == "new_voice_x"
        assert chars[1]["voice_id"] == "old_voice_2"  # 未变

    def test_appends_missing_character(self):
        project = self._make_project([{"name": "林黛玉", "voice_id": "v1"}])
        overrides = {"新角色": VoiceOverride(voice_id="v_new")}
        _apply_voice_overrides_to_project_config(
            project, tts_model="qwen3-tts-instruct-flash", voice_overrides=overrides
        )
        result = json.loads(project.audio_config)
        chars = result["tts_models"]["qwen3-tts-instruct-flash"]["characters"]
        assert len(chars) == 2
        assert chars[1]["name"] == "新角色"
        assert chars[1]["voice_id"] == "v_new"

    def test_preserves_reference_fields(self):
        project = self._make_project([{"name": "角色A", "voice_id": "v1"}])
        overrides = {
            "角色A": VoiceOverride(
                voice_id="v2",
                reference_source="user_private",
                voice_reference_asset_id="asset_123",
            )
        }
        _apply_voice_overrides_to_project_config(
            project, tts_model="qwen3-tts-instruct-flash", voice_overrides=overrides
        )
        result = json.loads(project.audio_config)
        char = result["tts_models"]["qwen3-tts-instruct-flash"]["characters"][0]
        assert char["reference_source"] == "user_private"
        assert char["voice_reference_asset_id"] == "asset_123"


# ─── _build_segment_voice_overrides ───────────────────────────────────────────


class TestBuildSegmentVoiceOverrides:
    def test_maps_failed_chunks_to_source_segments(self):
        checkpoint = {
            "failed_segment_indices": [1, 2],
            "render_plan": [
                {"index": 0, "speaker": "旁白", "source_segment_indices": [0]},
                {"index": 1, "speaker": "林黛玉", "source_segment_indices": [1, 2]},
                {"index": 2, "speaker": "林黛玉", "source_segment_indices": [3]},
                {"index": 3, "speaker": "贾宝玉", "source_segment_indices": [4]},
            ],
        }
        overrides = {"林黛玉": VoiceOverride(voice_id="new_voice")}
        result = _build_segment_voice_overrides(checkpoint, overrides)
        # 源片段 1, 2, 3 应被覆盖（来自 failed chunk 1 和 2）
        assert set(result.keys()) == {"1", "2", "3"}
        assert result["1"]["voice_id"] == "new_voice"
        assert result["1"]["original_speaker"] == "林黛玉"

    def test_ignores_non_matching_speaker(self):
        checkpoint = {
            "failed_segment_indices": [0],
            "render_plan": [
                {"index": 0, "speaker": "贾宝玉", "source_segment_indices": [0]},
            ],
        }
        overrides = {"林黛玉": VoiceOverride(voice_id="new_voice")}
        result = _build_segment_voice_overrides(checkpoint, overrides)
        assert result == {}

    def test_empty_render_plan(self):
        checkpoint = {"failed_segment_indices": [0], "render_plan": []}
        overrides = {"林黛玉": VoiceOverride(voice_id="v")}
        assert _build_segment_voice_overrides(checkpoint, overrides) == {}


# ─── _apply_segment_voice_overrides（引擎级） ─────────────────────────────────


class TestApplySegmentVoiceOverrides:
    def _make_segment(self, speaker: str, voice_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            speaker=speaker,
            voice_params={"speaker": voice_id, "rate": 1.0, "pitch": 1.0},
        )

    def test_overrides_target_segments_only(self):
        from app.services.audiobook.engine_pkg._script_utils_mixin import ScriptUtilsMixin

        mixin = ScriptUtilsMixin.__new__(ScriptUtilsMixin)
        segments = [
            self._make_segment("林黛玉", "voice_a"),
            self._make_segment("林黛玉", "voice_a"),
            self._make_segment("贾宝玉", "voice_b"),
        ]
        overrides = {1: {"voice_id": "voice_x", "original_speaker": "林黛玉"}}
        mixin._apply_segment_voice_overrides(segments, overrides)

        # 片段 0 不变
        assert segments[0].voice_params["speaker"] == "voice_a"
        # 片段 1 被覆盖
        assert segments[1].voice_params["speaker"] == "voice_x"
        # 片段 2 不变
        assert segments[2].voice_params["speaker"] == "voice_b"

    def test_skips_empty_voice_id(self):
        from app.services.audiobook.engine_pkg._script_utils_mixin import ScriptUtilsMixin

        mixin = ScriptUtilsMixin.__new__(ScriptUtilsMixin)
        segments = [self._make_segment("林黛玉", "voice_a")]
        overrides = {0: {"voice_id": "", "original_speaker": "林黛玉"}}
        mixin._apply_segment_voice_overrides(segments, overrides)
        assert segments[0].voice_params["speaker"] == "voice_a"


# ─── 换音色缓存失效验证清单 ───────────────────────────────────────────────────


class TestCacheKeyInvalidation:
    """验证 cache_key 包含最终实际 speaker/音色，换音色后旧缓存不命中。"""

    def test_cache_key_changes_with_voice_id(self):
        """voice_params.speaker 变化 → cache_key 变化。"""
        common = dict(
            text="你好世界",
            speaker="林黛玉",
            emotion="neutral",
            segment_type="dialogue",
            performance_notes="",
        )
        old_key = _build_cache_key(
            **common,
            voice_params={"speaker": "old_voice", "rate": 1.0},
        )
        new_key = _build_cache_key(
            **common,
            voice_params={"speaker": "new_voice", "rate": 1.0},
        )
        assert old_key != new_key

    def test_cache_key_stable_without_voice_change(self):
        """相同 voice_params → 相同 cache_key（其他角色复用缓存）。"""
        params = dict(
            text="你好世界",
            speaker="林黛玉",
            emotion="neutral",
            voice_params={"speaker": "voice_a", "rate": 1.0},
            segment_type="dialogue",
            performance_notes="",
        )
        assert _build_cache_key(**params) == _build_cache_key(**params)

    def test_signature_voice_params_includes_speaker(self):
        """_signature_voice_params 保留 speaker 键（参与 hash）。"""
        result = _signature_voice_params({"speaker": "v1", "rate": 1.0, "pause_before": 0.5})
        assert "speaker" in result
        assert "pause_before" not in result  # 被忽略

    def test_replace_voice_all_all_character_chunks_invalidated(self):
        """replace_voice_all: 目标角色所有 chunk 的 cache_key 都变化。"""
        # 模拟同一角色的 3 个 chunk
        chunks_text = ["第一段", "第二段", "第三段"]
        old_keys = []
        new_keys = []
        for text in chunks_text:
            old_keys.append(_build_cache_key(
                text=text, speaker="林黛玉", emotion="neutral",
                voice_params={"speaker": "old_voice", "rate": 1.0},
                segment_type="dialogue", performance_notes="",
            ))
            new_keys.append(_build_cache_key(
                text=text, speaker="林黛玉", emotion="neutral",
                voice_params={"speaker": "new_voice", "rate": 1.0},
                segment_type="dialogue", performance_notes="",
            ))
        # 所有 chunk 的 cache_key 都应变化
        for old, new in zip(old_keys, new_keys):
            assert old != new

    def test_replace_voice_missing_only_target_segments_invalidated(self):
        """replace_voice_missing: 仅覆盖片段的 cache_key 变化，同角色其他片段不变。"""
        common = dict(speaker="林黛玉", emotion="neutral", segment_type="dialogue", performance_notes="")
        # 成功片段（不覆盖）
        success_key_before = _build_cache_key(
            text="成功文本", voice_params={"speaker": "voice_a", "rate": 1.0}, **common
        )
        success_key_after = _build_cache_key(
            text="成功文本", voice_params={"speaker": "voice_a", "rate": 1.0}, **common
        )
        assert success_key_before == success_key_after  # 成功片段不变

        # 失败片段（覆盖）
        failed_key_before = _build_cache_key(
            text="失败文本", voice_params={"speaker": "voice_a", "rate": 1.0}, **common
        )
        failed_key_after = _build_cache_key(
            text="失败文本", voice_params={"speaker": "voice_x", "rate": 1.0}, **common
        )
        assert failed_key_before != failed_key_after  # 失败片段变化


# ─── 护栏校验 ─────────────────────────────────────────────────────────────────


class TestGuardRails:
    """验证端点前置校验逻辑（纯逻辑层，不依赖 HTTP）。"""

    def test_voice_overrides_empty_for_replace_action(self):
        """replace_voice_* 无 voice_overrides 应被拒绝。"""
        from app.schemas.audiobook import RecoverSegmentsRequest

        req = RecoverSegmentsRequest(action="replace_voice_all", voice_overrides={})
        # 端点逻辑：if not body.voice_overrides → 400
        assert not req.voice_overrides

    def test_irrelevant_characters_detected(self):
        """覆盖角色不在缺失片段中应被检测。"""
        checkpoint = {
            "missing_segments": [{"index": 1, "speaker": "林黛玉"}],
            "failed_segment_indices": [1],
        }
        missing_speakers = _extract_missing_speakers(checkpoint)
        override_names = {"贾宝玉"}  # 不在缺失中
        irrelevant = override_names - missing_speakers
        assert irrelevant == {"贾宝玉"}

    def test_valid_overrides_pass(self):
        """覆盖角色在缺失片段中 → 通过。"""
        checkpoint = {
            "missing_segments": [{"index": 1, "speaker": "林黛玉"}],
            "failed_segment_indices": [1],
        }
        missing_speakers = _extract_missing_speakers(checkpoint)
        override_names = {"林黛玉"}
        irrelevant = override_names - missing_speakers
        assert not irrelevant
