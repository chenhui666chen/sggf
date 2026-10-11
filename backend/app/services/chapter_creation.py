"""章节创建服务。

供两条创建路由共用，避免同一业务在两处各自实现：

- ``POST /api/v1/chapters/``             —— project_id 来自请求体
- ``POST /api/v1/projects/{id}/chapters`` —— project_id 来自路径参数

统一负责：章节号分配、标题解析、字数统计、实体初始追踪与摘要后台任务。
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.project import Chapter

logger = logging.getLogger("uvicorn.error")

# Chapter.title 为 String(255)，超长内容提取出的标题需要截断后再入库
MAX_CHAPTER_TITLE_LENGTH = 255


def count_content_words(content: str) -> int:
    """统计章节字数。

    中文等无空格语言必须按“去空白后的字符数”统计，
    不能用 ``len(content.split())``（按空格分词会把整章算成 1 个字）。
    """
    return len(re.sub(r"\s", "", content or ""))


def resolve_chapter_number(db: Session, project_id: int, requested: Optional[int] = None) -> int:
    """解析章节号：未指定时取当前项目最大章节号 + 1。"""
    if requested:
        return requested
    max_chapter_number = db.query(func.max(Chapter.chapter_number)).filter(
        Chapter.project_id == project_id
    ).scalar()
    return (max_chapter_number or 0) + 1


def resolve_chapter_title(content: str, chapter_number: int, requested: Optional[str] = None) -> str:
    """解析章节标题：手动指定优先，否则从内容智能提取。"""
    manual_title = (requested or "").strip()
    if manual_title:
        return manual_title[:MAX_CHAPTER_TITLE_LENGTH]
    return extract_title_from_content(content or "", chapter_number)[:MAX_CHAPTER_TITLE_LENGTH]


def _remove_chapter_prefix(text: str) -> str:
    """递归移除文本中的所有“第X章：”或“第X章 ”前缀。"""
    text = text.strip().strip('"\'')
    pattern = r'^第[一二三四五六七八九十\d]+章[\uff1a:\s]+(.+)'
    match = re.match(pattern, text)
    if match:
        return _remove_chapter_prefix(match.group(1))
    return text


def _extract_title_only(text: str) -> str:
    """从文本中只提取标题部分，移除后面的正文内容。"""
    text = text.strip().strip('"\'')

    if '\n\n' in text:
        text = text.split('\n\n')[0].strip()

    if '\n' in text:
        text = text.split('\n')[0].strip()

    if len(text) > 50:
        text = text[:50].strip()

    return text


def extract_title_from_content(content: str, chapter_number: int) -> str:
    """从章节内容中智能提取标题。

    优先级：Markdown 加粗标题 → 普通“第X章：标题” → 引号标题 → 首行前 20 字 → 兜底。
    """
    if not content or not content.strip():
        return f"第{chapter_number}章：未命名章节"

    first_line = content.split('\n')[0].strip()

    pattern_bold = r'\*\*第[一二三四五六七八九十\d]+章[\uff1a:\s]+(.+?)\*\*'
    match_bold = re.match(pattern_bold, first_line)
    if match_bold:
        title_only = _extract_title_only(_remove_chapter_prefix(match_bold.group(1).strip()))
        return f"第{chapter_number}章：{title_only}"

    clean_line = first_line.replace('*', '').strip()
    pattern_normal = r'第[一二三四五六七八九十\d]+章[\uff1a:\s]+(.+)'
    match_normal = re.match(pattern_normal, clean_line)
    if match_normal:
        title_only = _extract_title_only(_remove_chapter_prefix(match_normal.group(1).strip()))
        return f"第{chapter_number}章：{title_only}"

    pattern_quoted = r'["\'](.+?)["\']'
    match_quoted = re.match(pattern_quoted, clean_line)
    if match_quoted:
        title_only = _extract_title_only(_remove_chapter_prefix(match_quoted.group(1).strip()))
        return f"第{chapter_number}章：{title_only}"

    clean_preview = clean_line[:20].strip()
    if clean_preview:
        return f"第{chapter_number}章：{_remove_chapter_prefix(clean_preview)}"

    return f"第{chapter_number}章：未命名章节"


def _track_new_chapter_entities(db: Session, chapter: Chapter) -> None:
    """新章节初始追踪：人物出场、设定引用、人物—物品关联。失败不影响创建。"""
    try:
        from app.services.auto_tracking import AutoTrackingService

        content = chapter.content or ""
        AutoTrackingService.update_character_appearances_smart(
            chapter_id=chapter.id,
            old_content="",
            new_content=content,
            project_id=chapter.project_id,
            db=db,
        )
        AutoTrackingService.update_setting_references_smart(
            chapter_id=chapter.id,
            old_content="",
            new_content=content,
            project_id=chapter.project_id,
            db=db,
        )
        relation_result = AutoTrackingService.update_character_item_relations(
            chapter_id=chapter.id,
            chapter_content=content,
            project_id=chapter.project_id,
            db=db,
        )
        logger.info(
            f"   ✅ 章节初始追踪: 功法{relation_result['techniques']}个, "
            f"法宝{relation_result['artifacts']}个, 地点{relation_result['locations']}个"
        )
    except Exception as exc:
        logger.warning(f"⚠️ 初始追踪失败: {exc}")


def _start_chapter_post_save(chapter: Chapter) -> None:
    """启动统一提取 + 摘要生成的后台任务。失败不影响创建。"""
    try:
        from app.services.chapter_post_save import start_chapter_post_save_task

        start_chapter_post_save_task(
            chapter_id=chapter.id,
            chapter_title=chapter.title,
            chapter_content=chapter.content or "",
            chapter_number=chapter.chapter_number,
            project_id=chapter.project_id,
            generate_summary=True,
        )
    except Exception as exc:
        logger.warning(f"⚠️ 启动后台任务失败（不影响章节创建）: {exc}")


def create_project_chapter(
    db: Session,
    project_id: int,
    *,
    content: Optional[str] = None,
    chapter_number: Optional[int] = None,
    title: Optional[str] = None,
) -> Chapter:
    """创建一个归属于 ``project_id`` 的章节并完成配套处理。"""
    resolved_content = content or ""
    resolved_number = resolve_chapter_number(db, project_id, chapter_number)
    resolved_title = resolve_chapter_title(resolved_content, resolved_number, title)

    chapter = Chapter(
        project_id=project_id,
        chapter_number=resolved_number,
        title=resolved_title,
        content=resolved_content,
        word_count=count_content_words(resolved_content),
    )
    db.add(chapter)
    db.commit()
    db.refresh(chapter)

    _track_new_chapter_entities(db, chapter)
    _start_chapter_post_save(chapter)

    return chapter
