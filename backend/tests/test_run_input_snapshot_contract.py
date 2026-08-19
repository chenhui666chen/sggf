"""GUIDE 验收 8/19：run_input_snapshot 方案 A 自包含正文合同与恢复消费链路。

覆盖（§7 测试计划"快照与运行输入"）：
- `_parse_run_input_snapshot`：None/损坏 JSON/缺 signed_payload 均返回 None；
- `build_run_input_snapshot_for_chapter` 按 run_type 合同冻结：
  - audio_from_scripts/场景重渲染：script_facts 内嵌已审批 script_json 正文、
    source_chapter_content 为 null、revision_heads 投影内嵌；
  - full/script_only：script_facts 为 null、source_chapter_content 内嵌章节正文；
  - input_signature = sha256(canonical_json(signed_payload))，相同输入相同签名；
  - 无批次快照退化为 legacy_stems 空配置；
- `_build_resume_input_context` 恢复只消费快照正文（不读实时 audio_config/
  script_json）：audio_from_scripts 用快照 script_facts、full 用快照
  source_chapter_content、run_options 驱动 narration_style/output_format、
  resolve_from_run_input 消费快照；无快照历史 run 回退实时解析。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _BACKEND_DIR.parent
for _path in (_BACKEND_DIR, _PROJECT_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.project import Chapter, Project
from app.services.audiobook import task_support
from app.services.audiobook.project_audio_config import _canonical_json
from app.services.audiobook.task_support import (
    _build_resume_input_context,
    _parse_run_input_snapshot,
    _sha256_payload,
    build_run_input_snapshot_for_chapter,
)

SCRIPT_FACTS = [
    {"segment_key": "seg_1", "type": "dialogue", "text": "第一段台词", "speaker": "角色甲", "seq": 1},
    {"segment_key": "seg_2", "type": "narration", "text": "旁白内容", "speaker": "旁白", "seq": 2},
]

REVISION_HEADS = {
    "revision_set_hash": "set-hash-abc",
    "dialogue": {"revision_id": 1, "revision_hash": "h-dialogue"},
    "director_override": None,
    "voice_binding": {"revision_id": 2, "revision_hash": "h-voice"},
    "projection": {
        "dialogue": {"revision_hash": "h-dialogue"},
        "director_override": None,
        "voice_binding": {"revision_hash": "h-voice"},
    },
}

ENGINE_SNAPSHOT = {
    "snapshot_version": 1,
    "engine_mode": "seed_scene",
    "engine_config_fingerprint": "fp-seed-1",
    "engine_branch_config": {
        "seed_audio_model": "seed-audio-1.0",
        "providers": {"seed": "dashscope", "fallback_tts": "qwen"},
    },
    "captured_at": "2026-08-01T00:00:00+00:00",
    "source_audio_config_hash": "src-hash",
}


class _FakeQuery:
    def __init__(self, row):
        self._row = row

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._row


class _FakeDb:
    """按模型类返回预设行的最小 DB 替身（仅覆盖测试路径的 query 形状）。"""

    def __init__(self, rows: Dict[Any, Any]):
        self._rows = rows

    def query(self, model):
        return _FakeQuery(self._rows.get(model))


def _fake_project_state(*, engine_snapshot: Any = None, chapter_content: str = "实时章节正文"):
    return {
        AudiobookProject: SimpleNamespace(
            id=1,
            project_id=100,
            engine_config_snapshot=(
                json.dumps(engine_snapshot, ensure_ascii=False)
                if engine_snapshot is not None
                else None
            ),
        ),
        Project: SimpleNamespace(id=100),
        Chapter: SimpleNamespace(
            id=1,
            title="第一章",
            content=chapter_content,
            summary="摘要",
            summary_data=None,
        ),
    }


def _audio_from_scripts_run_options() -> Dict[str, Any]:
    return {
        "tts_model": "qwen-tts-v1",
        "output_format": "mp3",
        "narration_style": "温柔叙述",
        "narration_style_prompt": "放慢语速",
        "generate_subtitle": True,
        "timeline_edits": {"seg_1": {"startUnit": 0, "durationUnits": 10, "volume": 0.9}},
    }


def _build_snapshot(
    *,
    run_type: str = "audio_from_scripts",
    revision_heads: Any = REVISION_HEADS,
    script_json: Any = SCRIPT_FACTS,
    chapter_content: str = "实时章节正文",
    engine_snapshot: Any = ENGINE_SNAPSHOT,
) -> Dict[str, Any]:
    chapter_audio = SimpleNamespace(
        id=10,
        script_json=json.dumps(script_json, ensure_ascii=False),
        script_status="approved",
    )
    db = _FakeDb(
        {
            **_fake_project_state(
                engine_snapshot=engine_snapshot, chapter_content=chapter_content
            ),
            ChapterAudio: chapter_audio,
        }
    )
    return build_run_input_snapshot_for_chapter(
        db,
        audiobook_project_id=1,
        chapter_id=1,
        run_type=run_type,
        revision_heads=revision_heads,
        **_audio_from_scripts_run_options(),
    )


# ——— _parse_run_input_snapshot ———


def test_parse_snapshot_none_and_corrupt_returns_none():
    assert _parse_run_input_snapshot(None) is None
    assert _parse_run_input_snapshot("not-json{{{") is None
    assert _parse_run_input_snapshot("{}") is None
    assert _parse_run_input_snapshot({"engine_mode": "seed_scene"}) is None  # 缺 signed_payload


def test_parse_snapshot_accepts_dict_and_json_string():
    snapshot = {"signed_payload": {"run_options": {}}, "input_signature": "sig"}
    assert _parse_run_input_snapshot(snapshot) is snapshot
    parsed = _parse_run_input_snapshot(json.dumps(snapshot))
    assert parsed["input_signature"] == "sig"


# ——— build_run_input_snapshot_for_chapter：run_type 合同 ———


def test_snapshot_audio_from_scripts_embeds_script_facts_and_revision_heads():
    snapshot = _build_snapshot()
    signed = snapshot["signed_payload"]
    assert signed["script_facts"] == SCRIPT_FACTS
    assert signed["source_chapter_content"] is None
    assert signed["revision_set_hash"] == "set-hash-abc"
    assert signed["revision_heads"]["dialogue"]["revision_hash"] == "h-dialogue"
    assert signed["revision_heads"]["voice_binding"]["revision_hash"] == "h-voice"
    assert signed["revision_projection"] == REVISION_HEADS["projection"]
    assert signed["engine_config_payload"] == ENGINE_SNAPSHOT["engine_branch_config"]
    assert snapshot["base_fingerprint"] == "fp-seed-1"
    assert snapshot["batch_snapshot_version"] == 1
    run_options = signed["run_options"]
    assert run_options["tts_model"] == "qwen-tts-v1"
    assert run_options["narration_style"] == "温柔叙述"
    assert run_options["output_format"] == "mp3"


def test_snapshot_full_and_script_only_freeze_chapter_content():
    for run_type in ("full", "script_only"):
        snapshot = _build_snapshot(run_type=run_type)
        signed = snapshot["signed_payload"]
        assert signed["script_facts"] is None
        assert signed["source_chapter_content"] == "实时章节正文"
        assert signed["revision_heads"] is None
        assert signed["revision_set_hash"] is None


def test_snapshot_audio_from_scripts_reads_revision_heads_when_not_passed(monkeypatch):
    captured = {}

    def fake_read_heads(db, *, audiobook_project_id, chapter_id):
        captured["called"] = (audiobook_project_id, chapter_id)
        return dict(REVISION_HEADS)

    monkeypatch.setattr(task_support, "_read_revision_heads_projection", fake_read_heads)
    snapshot = _build_snapshot(revision_heads=None)
    assert captured["called"] == (1, 1)
    assert snapshot["signed_payload"]["revision_set_hash"] == "set-hash-abc"


def test_snapshot_without_batch_snapshot_degrades_to_legacy():
    snapshot = _build_snapshot(engine_snapshot=None)
    signed = snapshot["signed_payload"]
    assert signed["engine_config_payload"] == {}
    assert snapshot["base_fingerprint"] is None
    # 退化分支仍携带剧本正文（正文不依赖批次快照）
    assert signed["script_facts"] == SCRIPT_FACTS


def test_snapshot_input_signature_is_canonical_sha256():
    snapshot = _build_snapshot()
    expected = hashlib.sha256(
        _canonical_json(snapshot["signed_payload"]).encode("utf-8")
    ).hexdigest()
    assert snapshot["input_signature"] == expected
    # 相同输入产生相同签名（审计字段 captured_at 不参与签名）
    snapshot_again = _build_snapshot()
    assert snapshot_again["input_signature"] == snapshot["input_signature"]


# ——— _build_resume_input_context：恢复只消费快照 ———


def _patch_runtime_resolve(monkeypatch, *, characters=None, audio_fx=None):
    calls = {}

    def fake_resolve_from_run_input(snapshot, tts_model=None):
        calls["snapshot"] = snapshot
        calls["tts_model"] = tts_model
        return SimpleNamespace(character_items=characters or [], audio_fx=audio_fx)

    def fake_resolve_real_time(project, tts_model=None):
        calls["real_time_called"] = True
        return SimpleNamespace(character_items=characters or [], audio_fx=audio_fx)

    import app.services.audiobook.project_audio_runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "resolve_from_run_input", fake_resolve_from_run_input)
    monkeypatch.setattr(
        runtime_mod, "resolve_project_audio_runtime_config", fake_resolve_real_time
    )
    return calls


def _resume_context(
    *,
    snapshot: Any,
    run_type: str = "audio_from_scripts",
    live_script_json: Any = None,
    live_content: str = "实时章节正文",
    run_tts_model: str = "qwen-tts-v1",
):
    db = _FakeDb(_fake_project_state(chapter_content=live_content))
    chapter_run = SimpleNamespace(
        run_type=run_type,
        run_input_snapshot=snapshot,
        tts_model=run_tts_model,
        narration_style=None,
        narration_style_prompt=None,
        output_format=None,
    )
    chapter_audio = SimpleNamespace(
        id=10,
        script_json=json.dumps(live_script_json, ensure_ascii=False)
        if live_script_json is not None
        else None,
        narration_style=None,
        narration_style_prompt=None,
    )
    return _build_resume_input_context(
        db,
        audiobook_project_id=1,
        chapter_id=1,
        chapter_run=chapter_run,
        chapter_audio=chapter_audio,
    )


def test_resume_audio_from_scripts_consumes_snapshot_script_facts(monkeypatch):
    snapshot = _build_snapshot()
    calls = _patch_runtime_resolve(monkeypatch, characters=[{"character_id": 1}])
    # 实时 script_json 已变更：恢复必须仍用快照正文
    result = _resume_context(
        snapshot=json.dumps(snapshot, ensure_ascii=False),
        live_script_json=[{"segment_key": "seg_live", "text": "实时剧本已改"}],
    )
    assert calls["tts_model"] == "qwen-tts-v1"
    assert calls["snapshot"]["input_signature"] == snapshot["input_signature"]
    assert result["script_hash"] == _sha256_payload(SCRIPT_FACTS)
    assert result["narration_style"] == "温柔叙述"
    assert result["output_format"] == "mp3"
    assert "real_time_called" not in calls


def test_resume_full_consumes_snapshot_chapter_content(monkeypatch):
    snapshot = _build_snapshot(run_type="full")
    calls = _patch_runtime_resolve(monkeypatch)
    result = _resume_context(
        snapshot=snapshot,  # dict 直接传入（_parse 兼容）
        run_type="full",
        live_content="实时章节正文已被改动",
    )
    assert result["script_hash"] == _sha256_payload(
        {
            "chapter_title": "第一章",
            "chapter_content": "实时章节正文",
            "chapter_summary": "摘要",
            "summary_data": None,
        }
    )
    assert "real_time_called" not in calls


def test_resume_without_snapshot_falls_back_to_real_time(monkeypatch):
    calls = _patch_runtime_resolve(monkeypatch, characters=[{"character_id": 9}])
    result = _resume_context(
        snapshot=None,
        live_script_json=SCRIPT_FACTS,
    )
    assert calls["real_time_called"] is True
    assert result["script_hash"] == _sha256_payload(SCRIPT_FACTS)


def test_resume_corrupt_snapshot_falls_back_to_real_time(monkeypatch):
    calls = _patch_runtime_resolve(monkeypatch)
    result = _resume_context(
        snapshot="corrupt-json{{{",
        live_script_json=SCRIPT_FACTS,
    )
    assert calls["real_time_called"] is True
    assert result["script_hash"] == _sha256_payload(SCRIPT_FACTS)
