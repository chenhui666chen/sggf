# -*- coding: utf-8 -*-
"""storyboarder 拆分遗留死码的物理退役守卫。

commit b330b27 把 `agents/storyboarder.py` 拆成 `storyboarder_pkg/` 时，连同零调用、
且跨模块符号已丢失（一调用就 NameError）的链路一起搬了过来，例如 `_detect_dynamic`
的定义留在旧文件里没搬走，而 `_estimate_video_subshot_weight` / `_infer_subshot_movement`
仍在调用它。退役原则与模型退役一致：物理删除，不留 alias、不留 re-export。

本用例同时锁住「必须保留」的活码：`_allocate_integer_durations` 被
`_fallback_bins_for_duration`（非经典档位的均分逻辑）调用，`_clean_text_chars` 被
`_scene_key_and_beat_text` 等活路径调用——按名字批量删死链时最容易误删这两个。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("agents", "backend", "pipeline", "core", "tests", "scripts")

RETIRED_SYMBOLS = (
    "_pack_video_containers_from_segments",
    "_plan_video_subshots_from_beats",
    "_normalize_beats_count",
    "_split_beat_once",
    "_estimate_video_subshot_weight",
    "_infer_subshot_type",
    "_infer_subshot_movement",
    "_normalize_frame_spec",
    "_smooth_storyboard_subject_pos",
    "_entities_summary",
    "_detect_dynamic",
)


def _python_sources():
    here = Path(__file__).resolve()
    for directory in SCAN_DIRS:
        base = ROOT / directory
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            # 本文件自己枚举了退役符号，必须排除，否则永远命中
            if path.resolve() == here:
                continue
            yield path


@pytest.mark.parametrize("symbol", RETIRED_SYMBOLS)
def test_retired_symbol_has_no_reference_left(symbol):
    pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(symbol) + r"(?![A-Za-z0-9_])")
    hits = []
    for path in _python_sources():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not pattern.search(text):
            continue
        line_no = next(i for i, line in enumerate(text.splitlines(), 1) if pattern.search(line))
        hits.append(f"{path.relative_to(ROOT).as_posix()}:{line_no}")
    assert not hits, f"{symbol} 仍被引用: {hits}"


@pytest.mark.parametrize(
    "symbol",
    (
        "_allocate_integer_durations",
        "_clean_text_chars",
        "_scene_key_and_beat_text",
        "_fallback_video_subshots",
        "_fallback_bins_for_duration",
        "_normalize_video_subshots",
    ),
)
def test_live_subshot_helpers_survive_the_cleanup(symbol):
    from agents.storyboarder_pkg import _video_subshots

    assert hasattr(_video_subshots, symbol), symbol
