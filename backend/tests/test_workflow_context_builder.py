import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DEBUG", "false")

from app.api.v1 import workflow as workflow_module
from app.core.config import settings as app_settings
from app.services.workflow_context_builder import WorkflowContextBuilder


class DummyResult:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class DummySession:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.executed = []
        self.commits = 0

    def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        row = self.rows.pop(0) if self.rows else None
        return DummyResult(row)

    def commit(self):
        self.commits += 1


def test_load_stage_contents_snapshot_pretty_formats_json_fields() -> None:
    db = DummySession(
        rows=[
            (
                '{"title":"设定中心"}',
                '"世界观正文"',
                '["林岩","扳手"]',
                '{"outline":"第一幕"}',
                "",
                '"章节初稿"',
                '"评审报告"',
                '"终稿"',
            )
        ]
    )

    builder = WorkflowContextBuilder(db)
    snapshot = builder.load_stage_contents_snapshot(1, pretty_json=True)

    assert snapshot["concept"] == '{\n  "title": "设定中心"\n}'
    assert snapshot["world_setting"] == "世界观正文"
    assert snapshot["characters"] == '[\n  "林岩",\n  "扳手"\n]'


def test_load_review_meta_returns_persisted_json() -> None:
    db = DummySession(rows=[('{"multi_model": true, "preset": "deep_7"}',)])

    builder = WorkflowContextBuilder(db)
    meta = builder.load_review_meta(12)

    assert meta == {"multi_model": True, "preset": "deep_7"}


def test_load_stage_status_snapshot_returns_pending_defaults_when_missing() -> None:
    db = DummySession(rows=[None])

    builder = WorkflowContextBuilder(db)
    snapshot = builder.load_stage_status_snapshot(7)

    assert snapshot == {
        "stage_one_status": "pending",
        "stage_two_status": "pending",
        "stage_three_status": "pending",
        "stage_four_status": "pending",
        "stage_five_status": "pending",
    }


def test_load_concept_storage_state_parses_json_values() -> None:
    db = DummySession(rows=[('"故事概念"', '{"阵营":"主角方"}', '["林岩","扳手"]')])

    builder = WorkflowContextBuilder(db)
    state = builder.load_concept_storage_state(3)

    assert state.concept_value == "故事概念"
    assert state.world_setting_value == {"阵营": "主角方"}
    assert state.characters_value == ["林岩", "扳手"]


def test_load_epic_framework_state_decodes_framework_fields() -> None:
    db = DummySession(
        rows=[
            (
                '"长篇框架正文"',
                "2026-04-13T10:00:00",
                '"总纲内容"',
                '{"volumes":{"1":{"type":"framework","title":"初入南麓","summary":"卷摘要","chapters_range":[1,80]}}}',
            )
        ]
    )

    builder = WorkflowContextBuilder(db)
    state = builder.load_epic_framework_state(11)

    assert state.epic_framework == "长篇框架正文"
    assert state.framework_generated_at == "2026-04-13T10:00:00"
    assert "初入南麓" in state.plot_outline
    assert "volumes" in state.epic_volumes_detail
    assert "初入南麓" in state.epic_volumes_detail


def test_load_stage_text_context_normalizes_historical_plot_outline() -> None:
    legacy_outline = (
        "第44章：城寨暗流\n"
        "关键事件：\n"
        "苏璃以自由灵盟技术人员身份接近城寨卫队技术官获取二寨主近期活动情报\n"
        "四天前秘密出城与斗篷人接头\n"
        "发现其自身因果线被巧妙动过\n"
        "涉及人物：顾长庚、苏璃\n"
    )
    db = DummySession(
        rows=[
            (
                "",
                "",
                '["顾长庚","苏璃"]',
                legacy_outline,
                "",
                "",
                "",
                "",
                "",
            )
        ]
    )

    builder = WorkflowContextBuilder(db)
    state = builder.load_stage_text_context(21)

    assert "- 关键事件：苏璃以自由灵盟技术人员身份接近城寨卫队技术官获取二寨主近期活动情报；四天前秘密出城与斗篷人接头；发现其自身因果线被巧妙动过" in state.plot_outline
    assert state.plot_outline.index("- 冲突设计") < state.plot_outline.index("- 关键事件")
    assert state.plot_outline.index("- 关键事件") < state.plot_outline.index("- 涉及人物")


def test_load_epic_framework_state_normalizes_plot_outline() -> None:
    legacy_outline = (
        "第17章：灯下问局\n"
        "关键事件：\n"
        "顾长歌潜入偏殿确认假印来源\n"
        "试探苏晚晴\n"
        "发现第二枚假印\n"
    )
    db = DummySession(
        rows=[
            (
                '"长篇框架正文"',
                "2026-04-13T10:00:00",
                json.dumps(legacy_outline, ensure_ascii=False),
                "",
            )
        ]
    )

    builder = WorkflowContextBuilder(db)
    state = builder.load_epic_framework_state(18)

    assert "- 关键事件：顾长歌潜入偏殿确认假印来源；试探苏晚晴；发现第二枚假印" in state.plot_outline


def test_read_stage_content_flattens_character_cards_for_prompt_usage() -> None:
    db = DummySession(rows=[('["林岩","扳手"]',)])

    builder = WorkflowContextBuilder(db)
    content = builder.read_stage_content(2, "character_designer")

    assert content == "林岩\n扳手"


def test_update_project_settings_fields_records_allowed_fields_and_commits() -> None:
    db = DummySession(rows=[(1,)])

    builder = WorkflowContextBuilder(db)
    builder.update_project_settings_fields(
        9,
        plot_outline="大纲正文",
        stage_two_status="completed",
    )

    assert db.commits == 1
    sql, params = db.executed[-1]
    assert "UPDATE project_settings" in sql
    assert "plot_outline = :plot_outline" in sql
    assert "stage_two_status = :stage_two_status" in sql
    assert params["project_id"] == 9
    assert params["plot_outline"] == "大纲正文"
    assert params["stage_two_status"] == "completed"
    assert "updated_at" in params


def test_update_project_settings_fields_accepts_review_meta() -> None:
    db = DummySession(rows=[(1,)])

    builder = WorkflowContextBuilder(db)
    builder.update_project_settings_fields(
        9,
        review_meta={"multi_model": True, "preset": "key_chapter_5"},
    )

    sql, params = db.executed[-1]
    assert "UPDATE project_settings" in sql
    assert "review_meta = :review_meta" in sql
    assert json.loads(params["review_meta"]) == {"multi_model": True, "preset": "key_chapter_5"}


def test_update_project_settings_fields_merges_review_meta_without_dropping_narrative_state() -> None:
    existing_meta = {
        "narrative_state_v1": {
            "latest_chapter": 4,
            "open_debts": [{"content": "打捞许可未办", "since_chapter": 4}],
            "chapters": {"4": {"chapter": 4, "narrative_debts": [{"content": "打捞许可未办"}]}},
        },
        "quality_memory": {"items": [{"issue": "旧问题", "hits": 1}]},
        "foreshadow_ledger": {"entries": [{"id": "fs_1"}]},
        "multi_model": False,
    }
    incoming_meta = {
        "multi_model": True,
        "preset": "key_chapter_5",
        "quality_memory": {"items": [{"issue": "新问题", "hits": 1}]},
    }
    db = DummySession(rows=[(1,), (json.dumps(existing_meta, ensure_ascii=False),)])

    builder = WorkflowContextBuilder(db)
    builder.update_project_settings_fields(9, review_meta=incoming_meta)

    sql, params = db.executed[-1]
    persisted = json.loads(params["review_meta"])
    assert persisted["multi_model"] is True
    assert persisted["preset"] == "key_chapter_5"
    assert persisted["narrative_state_v1"]["latest_chapter"] == 4
    assert persisted["narrative_state_v1"]["open_debts"][0]["content"] == "打捞许可未办"
    assert persisted["foreshadow_ledger"]["entries"][0]["id"] == "fs_1"
    assert persisted["quality_memory"]["items"][0]["issue"] == "新问题"


def test_update_project_settings_fields_normalizes_plot_outline_before_persisting() -> None:
    db = DummySession(rows=[(1,)])
    legacy_outline = (
        "第44章：城寨暗流\n"
        "关键事件：\n"
        "苏璃以自由灵盟技术人员身份接近城寨卫队技术官获取二寨主近期活动情报\n"
        "四天前秘密出城与斗篷人接头\n"
        "发现其自身因果线被巧妙动过\n"
    )

    builder = WorkflowContextBuilder(db)
    builder.update_project_settings_fields(
        9,
        plot_outline=legacy_outline,
        characters='["顾长庚","苏璃"]',
    )

    sql, params = db.executed[-1]
    assert "UPDATE project_settings" in sql
    assert "- 关键事件：苏璃以自由灵盟技术人员身份接近城寨卫队技术官获取二寨主近期活动情报；四天前秘密出城与斗篷人接头；发现其自身因果线被巧妙动过" in params["plot_outline"]


def test_update_project_settings_fields_auto_creates_settings_record_when_missing() -> None:
    db = DummySession(rows=[None, None])

    builder = WorkflowContextBuilder(db)
    builder.update_project_settings_fields(
        5,
        review_report="评审内容",
    )

    assert db.commits == 2
    assert "INSERT INTO project_settings" in db.executed[1][0]
    assert "UPDATE project_settings" in db.executed[2][0]


def test_write_stage_content_rejects_unknown_stage() -> None:
    db = DummySession()
    builder = WorkflowContextBuilder(db)

    with pytest.raises(ValueError, match="Unsupported workflow stage"):
        builder.write_stage_content(1, "unknown_stage", "test")


def test_validate_story_framework_mode_switch_blocks_total_mode_when_framework_exists() -> None:
    db = DummySession(rows=[('"现有长篇框架"', "2026-04-13T10:00:00", "", "")])
    request = workflow_module.ExpandStoryRequest(
        project_id=18,
        current_outline="",
        world_setting="",
        characters="",
        target_total_chapters=320,
        expansion_mode="total",
    )

    with pytest.raises(HTTPException) as exc_info:
        workflow_module._validate_story_framework_mode_switch(request, db)

    assert "已存在长篇框架" in exc_info.value.detail


def test_validate_story_framework_mode_switch_allows_total_mode_without_framework() -> None:
    db = DummySession(rows=[None])
    request = workflow_module.ExpandStoryRequest(
        project_id=19,
        current_outline="",
        world_setting="",
        characters="",
        target_total_chapters=120,
        expansion_mode="total",
    )

    workflow_module._validate_story_framework_mode_switch(request, db)


def test_load_project_chapter_context_prefers_stage_outline_and_builder_data() -> None:
    db = DummySession(
        rows=[
            ("项目标题", "科幻", "太空歌剧", "long", 120, 300, "用户自定义大纲", ""),
            ("", '"世界观设定"', '["林岩","回声"]', '"阶段大纲"', "", "", "", "", ""),
        ]
    )

    context = workflow_module._load_project_chapter_context(db, project_id=22)

    assert context["genre"] == "科幻"
    assert context["outline"] == "阶段大纲"
    assert context["world_setting"] == "世界观设定"
    assert context["characters"] == "林岩\n回声"


def test_build_typed_rag_context_prefers_character_runtime_metadata_and_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyKB:
        def search(self, query, k, filter_type=None, project_id=None):
            if filter_type == "character":
                return [
                    SimpleNamespace(
                        page_content="### 【姓名】：林澈\n【角色定位】：主角\n【关键关系】：顾晚：盟友/互相信任",
                        metadata={
                            "character_id": "1",
                            "name": "林澈",
                            "runtime_summary": "林澈（主角 / 主角方） | 当前关系：顾晚：盟友/互补 | 当前主线：剧情职责：追查旧案",
                        },
                    ),
                    SimpleNamespace(
                        page_content="重复分片",
                        metadata={
                            "character_id": "1",
                            "name": "林澈",
                            "runtime_summary": "不应重复出现",
                        },
                    ),
                    SimpleNamespace(
                        page_content=(
                            "### 【姓名】：顾晚\n"
                            "【故事立场】：主角方\n"
                            "【角色定位】：盟友\n"
                            "【关键关系】：林澈：盟友/互相信任\n"
                            "【主线绑定】：剧情职责：协助追查旧案 / 关联线索：掌握藏书楼线索"
                        ),
                        metadata={
                            "character_id": "2",
                            "name": "顾晚",
                        },
                    ),
                ]
            return []

    monkeypatch.setattr("app.services.vector_sync.get_vector_kb", lambda: DummyKB())
    monkeypatch.setattr(app_settings, "ENABLE_TYPED_RAG", True, raising=False)

    builder = WorkflowContextBuilder(DummySession())
    result = builder.build_typed_rag_context(project_id=3, query_text="旧案调查")

    assert result.used_vector_search is True
    assert result.character_hits == 2
    assert result.rag_character_context.count("- 林澈:") == 1
    assert "林澈（主角 / 主角方）" in result.rag_character_context
    assert "顾晚" in result.rag_character_context
    assert "协助追查旧案" in result.rag_character_context
