"""阶段 5 章节接缝评审窗口构造测试（指导文档 §10.5）。

覆盖：

- 不默认提交整章：每个相邻场景只取前一场景末尾 5-10 秒 + 后一场景
  开头 5-10 秒；
- 场景足够长时取最大窗口（10 秒）；场景不足最小窗口（5 秒）时退化为
  整段场景，不补齐、不拒绝；
- 窗口边界参数版本化校验（min ≤ max 且为正）；
- 相对窗口可换算为章节绝对时间区间，供结果定位。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_quality.seam_review import (  # noqa: E402
    SeamWindows,
    build_seam_review_windows,
)


class TestWindowSelection:
    def test_long_scenes_take_max_window(self) -> None:
        windows = build_seam_review_windows(60_000, 45_000)
        # 前一场景末尾 10 秒 + 后一场景开头 10 秒
        assert windows.left_window == (50_000, 60_000)
        assert windows.right_window == (0, 10_000)

    def test_short_scene_degrades_to_full_scene(self) -> None:
        windows = build_seam_review_windows(3_000, 80_000)
        assert windows.left_window == (0, 3_000)
        assert windows.right_window == (0, 10_000)

    def test_mid_length_scene_is_clamped_to_duration(self) -> None:
        windows = build_seam_review_windows(7_000, 60_000)
        assert windows.left_window == (0, 7_000)

    def test_custom_bounds_are_respected(self) -> None:
        windows = build_seam_review_windows(
            60_000, 60_000, min_window_ms=2_000, max_window_ms=4_000
        )
        assert windows.left_window == (56_000, 60_000)
        assert windows.right_window == (0, 4_000)


class TestValidation:
    def test_non_positive_duration_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            build_seam_review_windows(0, 60_000)
        with pytest.raises(ValueError):
            build_seam_review_windows(60_000, -1)

    def test_bounds_must_be_positive_and_ordered(self) -> None:
        with pytest.raises(ValueError):
            build_seam_review_windows(60_000, 60_000, min_window_ms=0)
        with pytest.raises(ValueError):
            build_seam_review_windows(
                60_000, 60_000, min_window_ms=10_000, max_window_ms=5_000
            )


class TestChapterAbsoluteMapping:
    def test_relative_windows_map_to_chapter_coordinates(self) -> None:
        windows = build_seam_review_windows(60_000, 45_000)
        left_abs, right_abs = windows.chapter_windows(
            left_chapter_start_ms=120_000, right_chapter_start_ms=180_000
        )
        assert left_abs == (170_000, 180_000)
        assert right_abs == (180_000, 190_000)

    def test_chapter_start_must_be_non_negative_and_ordered(self) -> None:
        windows = SeamWindows(
            left_window=(0, 5_000),
            right_window=(0, 5_000),
            left_duration_ms=60_000,
            right_duration_ms=60_000,
        )
        with pytest.raises(ValueError):
            windows.chapter_windows(
                left_chapter_start_ms=100_000, right_chapter_start_ms=90_000
            )
