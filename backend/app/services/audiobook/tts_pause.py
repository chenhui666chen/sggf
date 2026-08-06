"""有声书任务暂停信号。

API 将任务标记为 pause_requested 后，Worker 原本只能在章节循环边界响应暂停；
为让暂停在章节处理过程中即时生效，TTS 片段循环与剧本生成（分析/转化/审稿）
的每个批次开始前会调用 pause_check，检测到暂停请求时抛出 AudiobookPauseRequested，
由后台任务捕获后将任务落库为 paused（保留当前章节以便恢复）。
"""

from __future__ import annotations


class AudiobookPauseRequested(Exception):
    """检测到任务暂停请求，当前生成流程应立即停止。"""


# 兼容旧名称（最初仅在 TTS 片段循环中使用）
TTSPauseRequested = AudiobookPauseRequested


__all__ = ["AudiobookPauseRequested", "TTSPauseRequested"]
