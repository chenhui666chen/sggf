"""章节接缝评审窗口构造（指导文档 §10.5）。

不默认提交整章：每个相邻场景只取前一场景末尾 5-10 秒与后一场景开头
5-10 秒。场景不足最小窗口时退化为整段场景，不补齐、不拒绝。纯技术
响度差仍由本地分析器判定，本窗口只服务于 Omni 语义连续性评审。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

DEFAULT_SEAM_MIN_WINDOW_MS = 5_000
DEFAULT_SEAM_MAX_WINDOW_MS = 10_000


@dataclass(frozen=True)
class SeamWindows:
    """相邻场景接缝窗口（相对各自音频的毫秒区间）。"""

    left_window: Tuple[int, int]
    right_window: Tuple[int, int]
    left_duration_ms: int
    right_duration_ms: int

    def chapter_windows(
        self, *, left_chapter_start_ms: int, right_chapter_start_ms: int
    ) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        """换算为章节绝对时间区间，供评审结果定位。"""
        if left_chapter_start_ms < 0 or right_chapter_start_ms < 0:
            raise ValueError("chapter starts must be non-negative")
        if right_chapter_start_ms < left_chapter_start_ms:
            raise ValueError("right chapter start must not precede left")
        left_abs = (
            left_chapter_start_ms + self.left_window[0],
            left_chapter_start_ms + self.left_window[1],
        )
        right_abs = (
            right_chapter_start_ms + self.right_window[0],
            right_chapter_start_ms + self.right_window[1],
        )
        return left_abs, right_abs


def build_seam_review_windows(
    left_duration_ms: int,
    right_duration_ms: int,
    *,
    min_window_ms: int = DEFAULT_SEAM_MIN_WINDOW_MS,
    max_window_ms: int = DEFAULT_SEAM_MAX_WINDOW_MS,
) -> SeamWindows:
    """构造接缝评审窗口：前末 min~max 秒 + 后首 min~max 秒。"""
    if int(left_duration_ms) <= 0 or int(right_duration_ms) <= 0:
        raise ValueError("scene durations must be positive")
    if int(min_window_ms) <= 0:
        raise ValueError("min_window_ms must be positive")
    if int(min_window_ms) > int(max_window_ms):
        raise ValueError("min_window_ms must not exceed max_window_ms")

    left_length = min(int(left_duration_ms), int(max_window_ms))
    right_length = min(int(right_duration_ms), int(max_window_ms))
    return SeamWindows(
        left_window=(int(left_duration_ms) - left_length, int(left_duration_ms)),
        right_window=(0, right_length),
        left_duration_ms=int(left_duration_ms),
        right_duration_ms=int(right_duration_ms),
    )


__all__ = [
    "DEFAULT_SEAM_MAX_WINDOW_MS",
    "DEFAULT_SEAM_MIN_WINDOW_MS",
    "SeamWindows",
    "build_seam_review_windows",
]
