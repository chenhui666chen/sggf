"""章节结构守卫：规划切片与短稿回退的纯函数工具。

职责边界：
- 分段生成时，首段只保留本段事件、末段保留规划尾部钩子（避免分段互盲导致整弧重启）；
- 迭代改稿后，当修订稿被压缩成摘要时回退原稿。

设计约束：
- 全部为纯文本处理，不依赖任何特定小说的词表；
- 结构重放（同一场景写两次）的检测与拦截由评审 STRUCT_BROKEN 失败码 +
  迭代验收硬停止负责，本模块不再做词表匹配式重放检测。
"""
from __future__ import annotations

from typing import Iterable

_HOOK_LABELS = ("\u7ed3\u5c3e\u94a9\u5b50", "\u94a9\u5b50\u5177\u4f53", "\u94a9\u5b50\u8bbe\u8ba1")


def extract_plan_hook_tail(chapter_plan: str, max_chars: int = 800) -> str:
    """从章节规划中提取结尾钩子相关片段；无钩子标签时回退到规划末尾。"""
    text = str(chapter_plan or "").strip()
    if not text:
        return ""
    for label in _HOOK_LABELS:
        idx = text.find(label)
        if idx >= 0:
            return text[idx : idx + max_chars].strip()
    return text[-max_chars:].strip()


def extract_writable_plan(chapter_plan: str, events: Iterable[str]) -> str:
    """首段只保留本段事件，避免把后续闭环当成可写内容。"""
    event_lines = [str(event).strip() for event in events or [] if str(event).strip()]
    if not event_lines:
        return ""
    return "\n".join(f"- {line}" for line in event_lines)


def should_revert_short_revision(
    original: str,
    revised: str,
    *,
    has_structural_failure: bool = False,
    min_original_chars: int = 500,
    ratio: float = 0.6,
) -> bool:
    """修订稿字数远小于原稿时，判断是否回退为原稿。

    结构重写本身会大幅删减重复内容，字数变短是预期结果，此时不因字数回退；
    无结构重写理由却大幅缩短，多半是被压缩成摘要，回退原稿。
    """
    original_len = len(str(original or ""))
    revised_len = len(str(revised or ""))
    if original_len < min_original_chars or revised_len <= 0:
        return False
    if revised_len >= original_len * ratio:
        return False
    if has_structural_failure:
        return False
    return True
