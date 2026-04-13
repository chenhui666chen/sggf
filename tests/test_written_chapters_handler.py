import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
for path in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

import backend.app.api.v1.workflow as workflow
from app.services.agents import outline_extractor
from app.services.agents.written_chapters_handler import process_written_chapters


class _FetchAllResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = list(rows)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)


class _FakeDB:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = list(rows)
        self.execute_calls: list[tuple[Any, Any]] = []

    def execute(self, query: Any, params: Any = None) -> _FetchAllResult:
        self.execute_calls.append((query, params))
        return _FetchAllResult(self._rows)


class _NoExtractionExtractor:
    def extract_from_chapter(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("命中摘要资产时不应再回退全文细纲提取")

    def format_outline_text(self, outline_data: dict[str, Any]) -> str:
        lines = [
            f"### 第{outline_data.get('chapter_number')}章：{outline_data.get('title')}",
            f"场景目标：{outline_data.get('scene_goal', '')}",
            f"冲突设计：{outline_data.get('conflict_design', '')}",
            f"关键事件：{' | '.join(outline_data.get('key_events', []))}",
            f"涉及人物：{outline_data.get('involved_characters', '')}",
            f"人物推进：{outline_data.get('character_progress', '')}",
            f"情节作用：{outline_data.get('plot_function', '')}",
            f"结尾钩子：{outline_data.get('ending_hook', '')}",
            f"爽点类型：{outline_data.get('highlight_type', '')}",
            f"伏笔事项：{outline_data.get('foreshadowing_item', '')}",
        ]
        return "\n".join(lines)


@pytest.mark.asyncio
async def test_process_written_chapters_reuses_workflow_summary_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        (
            1,
            "旧宅异响",
            "这是正文内容" * 200,
            "主角潜入旧宅调查，发现墙上血字。",
            json.dumps(
                {
                    "key_events": ["潜入旧宅", "发现墙上血字"],
                    "plot_advancement": "旧案调查进入新阶段",
                    "hooks": ["暗门后传来脚步声"],
                },
                ensure_ascii=False,
            ),
        )
    ]
    fake_db = _FakeDB(rows)

    monkeypatch.setattr(
        outline_extractor,
        "create_outline_extractor",
        lambda llm=None: _NoExtractionExtractor(),
    )

    written_count, outline_text = await process_written_chapters(
        project_id=1,
        preserve_written_mode="extract_extend",
        project_genre="悬疑",
        combined_world_setting="迷雾旧城",
        db=fake_db,
        extractor_llm=object(),
    )

    assert written_count == 1
    assert "潜入旧宅" in outline_text
    assert "旧案调查进入新阶段" in outline_text
    assert "暗门后传来脚步声" in outline_text


@pytest.mark.asyncio
async def test_process_written_chapters_reuses_book_parser_summary_data_without_plain_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        (
            12,
            "迷雾重重",
            "这是拆书导入后的正文内容，不应直接回退成正文截断。" * 80,
            "",
            json.dumps(
                {
                    "scene_goal": "潜入书库查卷",
                    "conflict_arc": {
                        "trigger": "守卫巡逻逼近",
                        "escalation": "顾晚临时分散守卫注意",
                        "resolution": "林舟带卷险逃",
                    },
                    "ending_hook": {"type": "reveal", "content": "密道尽头传来异响"},
                    "key_events": ["发现密道", "取得旧卷"],
                    "foreshadowing": ["旧卷背后仍有隐藏势力"],
                },
                ensure_ascii=False,
            ),
        )
    ]
    fake_db = _FakeDB(rows)

    monkeypatch.setattr(
        outline_extractor,
        "create_outline_extractor",
        lambda llm=None: _NoExtractionExtractor(),
    )

    written_count, outline_text = await process_written_chapters(
        project_id=1,
        preserve_written_mode="extract_extend",
        project_genre="悬疑",
        combined_world_setting="迷雾旧城",
        db=fake_db,
        extractor_llm=object(),
    )

    assert written_count == 1
    assert "潜入书库查卷" in outline_text
    assert "守卫巡逻逼近" in outline_text
    assert "密道尽头传来异响" in outline_text
    assert "发现密道" in outline_text


def test_build_story_written_chapter_preview_prefers_summary_assets_over_content_snippet() -> None:
    fake_db = _FakeDB(
        [
            (
                12,
                "迷雾重重",
                "正文前200字不该直接出现在预检结果里。" * 40,
                "",
                json.dumps(
                    {
                        "scene_goal": "潜入书库查卷",
                        "key_events": ["发现密道", "取得旧卷"],
                        "ending_hook": {"type": "reveal", "content": "密道尽头传来异响"},
                    },
                    ensure_ascii=False,
                ),
            )
        ]
    )

    preview = workflow._build_story_written_chapter_preview(
        workflow.ExpandStoryRequest(
            project_id=1,
            current_outline="旧大纲",
            world_setting="迷雾旧城",
            characters="### 【姓名】：林舟\n【角色定位】：主角",
            target_total_chapters=20,
            preserve_written_mode="extract_extend",
        ),
        fake_db,
    )

    assert preview["applied"] is True
    assert "潜入书库查卷" in preview["effective_outline"]
    assert "密道尽头传来异响" in preview["effective_outline"]
    assert "正文前200字不该直接出现在预检结果里" not in preview["effective_outline"]
