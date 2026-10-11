from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
for path in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


from app.api.v1.workflow.helpers import (
    _build_recent_full_chapter_excerpt,
    _select_previous_chapter_context_strategy,
)


def test_select_previous_chapter_context_strategy_scales_with_chapter_length() -> None:
    short_chapters = [
        (index, index, f"第{index}章", "短内容" * 120, "")
        for index in range(1, 13)
    ]
    long_chapters = [
        (index, index, f"第{index}章", "长内容" * 2500, "")
        for index in range(1, 13)
    ]

    short_strategy = _select_previous_chapter_context_strategy(
        short_chapters,
        next_chapter_number=13,
        preferred_model="qwen-plus",
    )
    long_strategy = _select_previous_chapter_context_strategy(
        long_chapters,
        next_chapter_number=13,
        preferred_model="qwen-plus",
    )

    assert short_strategy["recent_full_count"] >= long_strategy["recent_full_count"]
    assert short_strategy["recent_asset_count"] >= short_strategy["recent_full_count"]
    assert long_strategy["detailed_summary_count"] >= 0
    assert short_strategy["selected_model"] == "qwen-plus"


def test_build_recent_full_chapter_excerpt_keeps_head_and_tail() -> None:
    content = "开头信息" * 120 + "中段铺陈" * 200 + "结尾钩子" * 120

    excerpt = _build_recent_full_chapter_excerpt(content, max_chars=240)

    assert excerpt.startswith("开头信息")
    assert "..." in excerpt
    assert excerpt.endswith("结尾钩子结尾钩子结尾钩子结尾钩子结尾钩子")
