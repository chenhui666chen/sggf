"""
已写章节处理器 - 用于大纲扩展时处理已有章节内容

功能：
1. 检测数据库中已有内容的章节
2. 根据模式提取细纲或摘要
3. 为AI扩展提供准确的上下文
"""

from typing import Dict, Any, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text
import logging
import asyncio

from app.services.chapter_adaptation_assets import (
    build_drama_adaptation_hint,
    load_summary_data,
)

logger = logging.getLogger(__name__)


def _clean_prompt_text(value: Any, *, max_length: int = 120) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    if len(text) > max_length:
        return text[: max_length - 3].rstrip() + "..."
    return text


def _normalize_prompt_item(value: Any, *, max_length: int = 120) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        ordered_keys = (
            "content",
            "description",
            "summary",
            "hook",
            "text",
            "name",
            "event",
            "trigger",
            "escalation",
            "resolution",
            "result",
            "type",
        )
        parts: List[str] = []
        seen = set()
        for key in ordered_keys:
            text = _clean_prompt_text(value.get(key), max_length=max_length)
            if text and text not in seen:
                parts.append(text)
                seen.add(text)
        if parts:
            return " / ".join(parts[:3])
        for raw in value.values():
            text = _clean_prompt_text(raw, max_length=max_length)
            if text:
                return text
        return ""
    if isinstance(value, list):
        items = _normalize_prompt_list(value, max_items=3, max_length=max_length)
        return " / ".join(items)
    return _clean_prompt_text(value, max_length=max_length)


def _normalize_prompt_list(
    value: Any,
    *,
    max_items: int = 5,
    max_length: int = 60,
) -> List[str]:
    if value is None:
        return []

    raw_items = value if isinstance(value, list) else [value]
    items: List[str] = []
    seen = set()
    for raw in raw_items:
        text = _normalize_prompt_item(raw, max_length=max_length)
        if not text or text in seen:
            continue
        items.append(text)
        seen.add(text)
        if len(items) >= max_items:
            break
    return items


def _pick_first_text(*values: Any, max_length: int = 120) -> str:
    for value in values:
        text = _normalize_prompt_item(value, max_length=max_length)
        if text:
            return text
    return ""


def build_written_chapter_summary_preview(
    *,
    chapter_number: int,
    title: str,
    content: str,
    summary: str,
    summary_data: Any,
) -> str:
    summary_payload = load_summary_data(summary_data)
    chapter_title = title or f"第{chapter_number}章"
    summary_text = _pick_first_text(
        summary_payload.get("core_summary"),
        summary,
        max_length=220,
    )
    if summary_text:
        return summary_text

    drama_hint = build_drama_adaptation_hint(
        summary_payload,
        chapter_title=chapter_title,
        chapter_summary=summary,
    )
    scene_objective = _pick_first_text(
        drama_hint.get("scene_objective"),
        summary_payload.get("scene_goal"),
        max_length=80,
    )
    key_beats = _normalize_prompt_list(
        drama_hint.get("key_beats") or summary_payload.get("key_events"),
        max_items=3,
        max_length=50,
    )
    ending_hook = _pick_first_text(
        drama_hint.get("ending_hook"),
        summary_payload.get("ending_hook"),
        summary_payload.get("hooks"),
        max_length=80,
    )

    preview_parts: List[str] = []
    if scene_objective:
        preview_parts.append(scene_objective)
    for beat in key_beats:
        if beat not in preview_parts:
            preview_parts.append(beat)
    if ending_hook:
        preview_parts.append(f"钩子：{ending_hook}")

    if preview_parts:
        return "；".join(preview_parts[:4])

    content_preview = _clean_prompt_text(content[:200], max_length=220)
    if content_preview and len(content) > 200:
        return f"{content_preview}..."
    return content_preview or "本章已有正文，待后续协同扩展时继续承接。"


def build_written_chapter_outline_from_assets(
    *,
    chapter_number: int,
    title: str,
    summary: str,
    summary_data: Any,
) -> Dict[str, Any] | None:
    summary_payload = load_summary_data(summary_data)
    chapter_title = title or f"第{chapter_number}章"
    summary_text = _pick_first_text(
        summary_payload.get("core_summary"),
        summary,
        max_length=220,
    )
    drama_hint = build_drama_adaptation_hint(
        summary_payload,
        chapter_title=chapter_title,
        chapter_summary=summary_text or summary,
    )
    scene_goal = _pick_first_text(
        drama_hint.get("scene_objective"),
        summary_payload.get("scene_goal"),
        summary_payload.get("plot_advancement"),
        summary_text,
        max_length=120,
    )
    conflict_design = _pick_first_text(
        drama_hint.get("core_conflict"),
        summary_payload.get("plot_advancement"),
        summary_payload.get("conflict_arc"),
        summary_text,
        max_length=260,
    )
    highlight_type = _pick_first_text(
        summary_payload.get("highlight"),
        drama_hint.get("visual_hooks"),
        max_length=120,
    )
    involved_characters = "、".join(
        _normalize_prompt_list(
            summary_payload.get("appearing_characters") or summary_payload.get("key_characters"),
            max_items=6,
            max_length=20,
        )
    )
    character_progress = _pick_first_text(
        summary_payload.get("character_progress"),
        summary_payload.get("relationship_shift"),
        summary_payload.get("gains"),
        max_length=140,
    )
    plot_function = _pick_first_text(
        summary_payload.get("plot_function"),
        summary_payload.get("plot_advancement"),
        summary_text,
        max_length=160,
    )
    ending_hook = _pick_first_text(
        drama_hint.get("ending_hook"),
        summary_payload.get("ending_hook"),
        summary_payload.get("hooks"),
        max_length=120,
    )
    foreshadowing_item = " / ".join(
        _normalize_prompt_list(
            summary_payload.get("foreshadowing"),
            max_items=3,
            max_length=60,
        )
    )
    key_events = _normalize_prompt_list(
        summary_payload.get("key_events") or drama_hint.get("key_beats"),
        max_items=5,
        max_length=60,
    )
    if not key_events and summary_text:
        key_events = [summary_text]

    if not any(
        (
            summary_text,
            scene_goal,
            conflict_design,
            involved_characters,
            character_progress,
            plot_function,
            ending_hook,
            key_events,
            highlight_type,
            foreshadowing_item,
        )
    ):
        return None

    has_structured_summary = any(
        summary_payload.get(key)
        for key in (
            "scene_goal",
            "conflict_arc",
            "highlight",
            "ending_hook",
            "foreshadowing",
            "gains",
        )
    )

    return {
        "chapter_number": chapter_number,
        "title": chapter_title,
        "scene_goal": scene_goal or "场景目标待补充",
        "conflict_design": conflict_design or summary_text or "冲突设计待补充",
        "involved_characters": involved_characters or "待补充",
        "character_progress": character_progress or "人物关系或状态出现阶段性变化。",
        "plot_function": plot_function or "承接已写剧情并推动主线继续展开。",
        "ending_hook": ending_hook,
        "key_events": key_events,
        "highlight_type": highlight_type,
        "foreshadowing_item": foreshadowing_item,
        "extraction_method": "structured_summary_reuse" if has_structured_summary else "summary_reuse",
    }


async def process_written_chapters(
    project_id: int,
    preserve_written_mode: str,
    project_genre: str,
    combined_world_setting: str,
    db: Session,
    extractor_llm: Any,
    ws_manager: Any = None,
    task_id: str = "",
) -> Tuple[int, str]:
    """
    处理已写章节，返回章节数和上下文文本
    
    Args:
        project_id: 项目ID
        preserve_written_mode: 处理模式 (extract_extend/preserve_written/regenerate_all)
        project_genre: 项目题材
        combined_world_setting: 世界观设定
        db: 数据库会话
        extractor_llm: LLM实例（用于提取）
        ws_manager: WebSocket管理器（可选）
        task_id: 任务ID（可选）
    
    Returns:
        (written_count, extracted_outline_text): 已写章节数和提取的大纲文本
    """
    
    # 1. 查询已写章节
    written_chapters_query = text("""
        SELECT chapter_number, title, content, summary, summary_data
        FROM chapters
        WHERE project_id = :project_id
          AND content IS NOT NULL
          AND content != ''
        ORDER BY chapter_number ASC
    """)
    
    written_chapters_result = db.execute(
        written_chapters_query,
        {"project_id": project_id}
    ).fetchall()
    
    written_count = len(written_chapters_result)
    logger.info(f"🔍 检测到 {written_count} 章已有内容")
    
    if written_count == 0:
        return 0, ""
    
    # 2. 根据模式处理
    extracted_outline_text = ""
    
    logger.info(f"📦 已写章节处理模式: {preserve_written_mode}")
    
    if preserve_written_mode == "extract_extend":
        # 模式1：提取+扩展（默认，质量最佳）
        logger.info("🔍 开始提取已写章节的细纲...")
        
        if ws_manager and task_id:
            await ws_manager.send_task_progress(
                project_id=project_id,
                task_id=task_id,
                progress=10,
                message=f"🔍 正在提取已写{written_count}章的细纲..."
            )
        
        # 导入细纲提取器
        from app.services.agents.outline_extractor import create_outline_extractor
        extractor = create_outline_extractor(llm=extractor_llm)

        outline_by_index: Dict[int, Dict[str, Any]] = {}
        chapters_to_extract: List[Dict[str, Any]] = []
        reused_from_structured_summary = 0
        reused_from_basic_summary = 0

        for row_index, row in enumerate(written_chapters_result):
            chapter_number, title, content, summary, summary_data = row
            outline_data = build_written_chapter_outline_from_assets(
                chapter_number=chapter_number,
                title=title or "",
                summary=summary or "",
                summary_data=summary_data,
            )
            if outline_data is not None:
                outline_by_index[row_index] = outline_data
                if outline_data.get("extraction_method") == "structured_summary_reuse":
                    reused_from_structured_summary += 1
                else:
                    reused_from_basic_summary += 1
                continue

            chapters_to_extract.append(
                {
                    "row_index": row_index,
                    "chapter_number": chapter_number,
                    "title": title or "",
                    "content": content or "",
                }
            )

        reused_count = reused_from_structured_summary + reused_from_basic_summary
        if reused_count:
            logger.info(
                "♻️ 已复用 %s 章摘要资产（结构化摘要 %s 章，基础摘要 %s 章）",
                reused_count,
                reused_from_structured_summary,
                reused_from_basic_summary,
            )
            if ws_manager and task_id:
                await ws_manager.send_task_progress(
                    project_id=project_id,
                    task_id=task_id,
                    progress=10 + int((reused_count / written_count) * 30),
                    message=(
                        f"♻️ 已复用{reused_count}章章节摘要资产"
                        + (
                            f"，继续补提{len(chapters_to_extract)}章细纲..."
                            if chapters_to_extract else "。"
                        )
                    ),
                )

        def progress_callback(current: int, total: int, chapter_num: int) -> None:
            # 计算进度：10%-40%，并将已复用的章节计入整体完成度
            completed = reused_count + current
            progress = 10 + int((completed / written_count) * 30)
            if ws_manager and task_id:
                asyncio.create_task(
                    ws_manager.send_task_progress(
                        project_id=project_id,
                        task_id=task_id,
                        progress=progress,
                        message=f"🔍 正在提取第{chapter_num}章细纲... ({completed}/{written_count})",
                    )
                )

        def extract_missing_outlines() -> List[Tuple[int, Dict[str, Any]]]:
            extracted_results: List[Tuple[int, Dict[str, Any]]] = []
            total = len(chapters_to_extract)
            for current, chapter_data in enumerate(chapters_to_extract, 1):
                outline_data = extractor.extract_from_chapter(
                    chapter_content=chapter_data["content"],
                    chapter_number=chapter_data["chapter_number"],
                    chapter_title=chapter_data["title"] or f"第{chapter_data['chapter_number']}章",
                    genre=project_genre,
                    world_context=combined_world_setting[:500],
                )
                extracted_results.append((chapter_data["row_index"], outline_data))
                progress_callback(current, total, chapter_data["chapter_number"])
            return extracted_results

        if chapters_to_extract:
            extracted_results = await asyncio.to_thread(extract_missing_outlines)
            for row_index, outline_data in extracted_results:
                outline_by_index[row_index] = outline_data

        extracted_texts = []
        for row_index in range(len(written_chapters_result)):
            outline_data = outline_by_index.get(row_index)
            if not outline_data:
                continue
            extracted_texts.append(extractor.format_outline_text(outline_data))

        extracted_outline_text = "\n".join(extracted_texts)
        logger.info(
            "✅ 已整理 %s 章扩展底稿（复用摘要 %s 章，全文提取 %s 章），总长度: %s 字符",
            len(extracted_texts),
            reused_count,
            len(chapters_to_extract),
            len(extracted_outline_text),
        )
        
    elif preserve_written_mode == "preserve_written":
        # 模式2：仅保护（不提取，只使用摘要）
        logger.info("🔒 仅保护已写章节，使用摘要作为上下文")
        
        summaries = []
        for row in written_chapters_result:
            ch_num, title, content, summary, summary_data = row
            preview_text = build_written_chapter_summary_preview(
                chapter_number=ch_num,
                title=title or "",
                content=content or "",
                summary=summary or "",
                summary_data=summary_data,
            )
            summaries.append(f"第{ch_num}章：{title or f'第{ch_num}章'}\n{preview_text}")
        
        extracted_outline_text = "\n\n".join(summaries)
        logger.info(f"📝 已收集 {written_count} 章摘要")
        
    elif preserve_written_mode == "regenerate_all":
        # 模式3：重新生成全部（忽略已写内容）
        logger.info(f"🔄 重新生成模式：将忽略已写的 {written_count} 章")
        extracted_outline_text = ""
        written_count = 0  # 重置为0，表示忽略已写内容
    
    return written_count, extracted_outline_text
