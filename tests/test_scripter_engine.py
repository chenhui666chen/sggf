# -*- coding: utf-8 -*-
"""剧本引擎（scripter_pkg）冒烟测试：FakeClient 打桩 LLM，全流程断言。

覆盖：知识加载 → Story Graph → 结构化生成 → CCV → 3E → 兼容产物 →
幂等短路 → 降级路径（无 LLM）→ 人工门标记。
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agents.scripter_pkg import _knowledge
from agents.scripter_pkg._schema import (
    check_action_lexicon,
    render_markdown,
    validate_document,
)


# ---------------------------------------------------------------- FakeClient
def _fake_graph_json() -> str:
    return json.dumps({
        "characters": [
            {"name": "林晚", "description": "32岁急诊科医生，疲惫而克制", "importance": "main",
             "personality_traits": ["克制", "执拗"], "relationships": [{"with": "陈默", "relation": "前夫"}]},
            {"name": "陈默", "description": "35岁建筑师", "importance": "main",
             "personality_traits": [], "relationships": []},
        ],
        "timeline": [{"order": 1, "event": "林晚在急诊室收到匿名化验单", "characters": ["林晚"]}],
        "scenes": [{"location": "急诊室", "summary": "夜班，匿名化验单出现"}],
        "props": [{"name": "化验单", "descriptor": "攥皱的纸张"}],
    }, ensure_ascii=False)


def _fake_script_json() -> str:
    return json.dumps({
        "schema_version": "2.0",
        "title": "化验单",
        "logline": "一张匿名化验单撕开三年前的谎言",
        "synopsis": "夜班急诊室，林晚收到指向陈默的匿名化验单，旧案重开。",
        "hooks": {
            "opening_hook": "特写：攥皱的化验单与颤抖的手",
            "ending_hook": "林晚拨通三年前删掉的号码",
            "share_emotion": "『我等的不是道歉，是真相』",
        },
        "scenes": [{
            "scene_id": "S1", "number": 1, "title": "夜班",
            "interior": "内景", "location": "急诊室", "time_of_day": "夜",
            "characters": ["林晚"], "summary": "匿名化验单出现",
            "beats": [
                {"beat_id": "S1-B1", "family": "信息揭示族", "type": "reveal",
                 "description": "林晚拆开信封，化验单滑出",
                 "action": "抓起→接", "shot_purpose": "揭示变化",
                 "dialogue": [], "visual_anchor": "化验单滑落在地",
                 "hook": True, "duration_hint_s": 4.0},
                {"beat_id": "S1-B2", "family": "情绪爆发族", "type": "dialogue",
                 "description": "林晚认出签名，崩溃质问",
                 "action": "看→皱眉→流泪", "shot_purpose": "强调情绪",
                 "dialogue": [{"speaker": "林晚", "line": "你到底瞒了我什么", "emotion": "sad"}],
                 "visual_anchor": "颤抖的手与攥皱的化验单",
                 "hook": False, "duration_hint_s": 4.0},
            ],
        }],
    }, ensure_ascii=False)


def _fake_ccv_json() -> str:
    # 修正版：词典外动作『抓起』→『拿起』，补结尾钩子已存在——按需微调
    doc = json.loads(_fake_script_json())
    doc["scenes"][0]["beats"][0]["action"] = "伸手→接→拿起"
    return json.dumps({
        "issues_fixed": ["词典外动作已归一"],
        "issues_remaining": [],
        "revised_document": doc,
    }, ensure_ascii=False)


class _FakeClient:
    """按调用顺序返回：图 JSON → 剧本 JSON → CCV JSON。"""

    def __init__(self):
        self.responses = [_fake_graph_json(), _fake_script_json(), _fake_ccv_json()]
        self.calls: list[dict] = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[idx]


def _make_ctx(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(payload=payload)


# ---------------------------------------------------------------- 知识层
def test_knowledge_loads_from_split_dir():
    k = _knowledge.load_script_knowledge()
    assert len(k["beat_families"]) == 7
    assert any("信息揭示" in f["family"] for f in k["beat_families"])
    assert k["compat_rules"], "script_generator_compatibility 应有内容"
    assert k["action_lexicon_lines"], "闭合动作词典应有内容"
    assert k["reuse_rules"], "adaptation_resource_protocol 应有内容"


# ---------------------------------------------------------------- 全流程（LLM 模式）
def test_run_full_flow_with_fake_llm(monkeypatch):
    monkeypatch.setenv("DREAMWEAVER_REQUIRE_SCRIPT_APPROVAL", "true")
    monkeypatch.setenv("DREAMWEAVER_SCRIPT_ENABLE_LLM", "true")
    fake = _FakeClient()

    payload = {
        "run_id": "run-test-1",
        "project_id": 1,
        "chapter_ids": [12],
        "source_text": "林晚在急诊室值夜班。凌晨三点，一封没有署名的信被塞进分诊台……（测试章节文本，超过最小长度以便图抽取与剧本生成有内容可用。）",
        "quality_mode": "fast",
    }
    ctx = _make_ctx(payload)

    fake_runtime = SimpleNamespace(
        api_key="test-key", base_url="https://example.test/v1",
        api_key_env="TEST_KEY_ENV", base_url_env="TEST_BASE_ENV",
    )
    with patch("agents.llm_client.get_llm_client", return_value=fake), patch(
        "agents.scripter_pkg._run.resolve_llm_runtime_config", return_value=fake_runtime
    ):
        from agents.scripter_pkg import run
        run(ctx)

    # 新键
    doc = ctx.payload["script_document"]
    assert doc["schema_version"] == "2.0"
    assert doc["scenes"] and doc["scenes"][0]["beats"]
    assert doc["source"]["chapter_ids"] == ["12"]  # provenance 资源 ID 统一字符串化
    assert doc["source"]["provenance"][0]["reuse_mode"] == "read_only_text_source"
    assert ctx.payload["story_graph"]["characters"][0]["name"] == "林晚"

    # beat 七族与词典
    fam = doc["scenes"][0]["beats"][0]["family"]
    assert fam in _knowledge.load_script_knowledge()["beat_family_names"]
    assert not check_action_lexicon(doc), "CCV 修正后不应有词典外动作"

    # 兼容键：旧标记
    text = ctx.payload["script_text"]
    for marker in ("## 概要", "## 分场", "### 场1", "节拍", "对白", "视觉锚点"):
        assert marker in text, f"旧校验标记缺失：{marker}"
    assert "林晚：你到底瞒了我什么" in text

    # 实体 / 档案 / 音频标记
    entities = ctx.payload["script_entities"]
    assert any(c["name"] == "林晚" for c in entities["characters"])
    assert entities["scenes"][0]["name"] == "急诊室"
    profiles = ctx.payload["character_profiles"]
    assert profiles and profiles[0]["name"] == "林晚"
    assert profiles[0]["importance"] == "main"
    markers = ctx.payload["audio_markers"]
    assert markers and markers[0]["character_name"] == "林晚"
    assert markers[0]["end_time"] > markers[0]["start_time"]

    # 报告与人工门
    gen = ctx.payload["script_generation"]
    assert gen["engine"] == "director_os_script_v2"
    assert gen["ccv"]["status"] == "pass"
    assert ctx.payload["script_requires_review"] is True
    assert ctx.payload["script_review"] == {"approved": False}


# ---------------------------------------------------------------- 幂等短路
def test_run_idempotent_short_circuit(monkeypatch):
    monkeypatch.setenv("DREAMWEAVER_REQUIRE_SCRIPT_APPROVAL", "true")
    payload = {
        "script_text": "## 概要\n- 已审核",
        "script_review": {"approved": True},
    }
    ctx = _make_ctx(payload)
    from agents.scripter_pkg import run
    run(ctx)
    assert ctx.payload["script_requires_review"] is False
    assert "script_document" not in ctx.payload  # 短路不重跑


# ---------------------------------------------------------------- 降级路径（无 LLM）
def test_run_fallback_without_llm(monkeypatch):
    monkeypatch.setenv("DREAMWEAVER_SCRIPT_ENABLE_LLM", "false")
    monkeypatch.setenv("DREAMWEAVER_REQUIRE_SCRIPT_APPROVAL", "true")
    payload = {
        "run_id": "run-fb-1",
        "chapter_ids": [3],
        "source_text": "第一段：夜班。第二段：化验单。第三段：电话响了，她没有接。",
    }
    ctx = _make_ctx(payload)
    from agents.scripter_pkg import run
    run(ctx)  # 不应抛异常

    doc = ctx.payload["script_document"]
    assert doc["scenes"], "降级文档也应有场与 beat"
    gen = ctx.payload["script_generation"]
    assert gen["mode"] == "fallback_structured"
    assert ctx.payload["script_text"]
    assert ctx.payload["script_requires_review"] is True


# ---------------------------------------------------------------- 单元级：schema 工具
def test_render_and_validate():
    doc = json.loads(_fake_script_json())
    assert validate_document(doc) == [] or all("钩子" not in i for i in validate_document(doc))
    md = render_markdown(doc)
    assert "### 场1 | 内景 | 急诊室 | 夜" in md
    assert "- [信息揭示族]（钩子）" in md


def test_lexicon_catches_unknown_action():
    doc = json.loads(_fake_script_json())
    doc["scenes"][0]["beats"][0]["action"] = "抓起→凝视虚空"
    violations = check_action_lexicon(doc)
    assert violations and "抓起" in violations[0]["unknown_actions"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
