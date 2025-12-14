"""
已写章节处理器 - 用于大纲扩展时处理已有章节内容

功能：
1. 检测数据库中已有内容的章节
2. 根据模式提取细纲或摘要
3. 为AI扩展提供准确的上下文
"""

from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text
import logging
import asyncio

logger = logging.getLogger(__name__)


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
        SELECT chapter_number, title, content, summary
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
        
        # 批量提取
        chapters_data = [
            {
                "chapter_number": row[0],
                "title": row[1],
                "content": row[2]
            }
            for row in written_chapters_result
        ]
        
        def progress_callback(current, total, chapter_num):
            # 计算进度：10%-40%
            progress = 10 + int((current / total) * 30)
            if ws_manager and task_id:
                asyncio.create_task(
                    ws_manager.send_task_progress(
                        project_id=project_id,
                        task_id=task_id,
                        progress=progress,
                        message=f"🔍 正在提取第{chapter_num}章细纲... ({current}/{total})"
                    )
                )
        
        extracted_outlines = await asyncio.to_thread(
            extractor.extract_batch,
            chapters=chapters_data,
            genre=project_genre,
            world_context=combined_world_setting[:500],
            progress_callback=progress_callback
        )
        
        # 格式化为文本
        extracted_texts = []
        for outline_data in extracted_outlines:
            formatted_text = extractor.format_outline_text(outline_data)
            extracted_texts.append(formatted_text)
        
        extracted_outline_text = "\n".join(extracted_texts)
        logger.info(f"✅ 已提取 {len(extracted_outlines)} 章细纲，总长度: {len(extracted_outline_text)} 字符")
        
    elif preserve_written_mode == "preserve_written":
        # 模式2：仅保护（不提取，只使用摘要）
        logger.info("🔒 仅保护已写章节，使用摘要作为上下文")
        
        summaries = []
        for row in written_chapters_result:
            ch_num, title, content, summary = row
            # 优先使用summary，如果没有则截取内容
            if summary:
                summaries.append(f"第{ch_num}章：{title}\n{summary}")
            else:
                content_preview = content[:200] if content else ""
                summaries.append(f"第{ch_num}章：{title}\n{content_preview}...")
        
        extracted_outline_text = "\n\n".join(summaries)
        logger.info(f"📝 已收集 {written_count} 章摘要")
        
    elif preserve_written_mode == "regenerate_all":
        # 模式3：重新生成全部（忽略已写内容）
        logger.info(f"🔄 重新生成模式：将忽略已写的 {written_count} 章")
        extracted_outline_text = ""
        written_count = 0  # 重置为0，表示忽略已写内容
    
    return written_count, extracted_outline_text
