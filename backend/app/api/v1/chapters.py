"""
章节API路由
"""
from typing import cast, List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.models.user import User
from app.models.project import Project, Chapter, ChapterRevision
from app.schemas.project import ChapterUpdate, ChapterResponse, ChapterCreate, ChapterRevisionResponse
from app.core.security import get_current_user
import re
from io import BytesIO
from datetime import datetime
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT

router = APIRouter(prefix="/api/v1/chapters", tags=["chapters"])


def extract_title_from_content(content: str, chapter_number: int) -> str:
    """
    从章节内容中智能提取标题
    
    核心原则：
    - 只提取纯标题文字，不包含任何章节编号
    - 章节序号完全由数据库自动分配
    - 只提取标题文字，不包含正文内容
    
    优先级:
    1. Markdown加粗标题: **第一章：标题** → 提取"标题"
    2. 普通标题: 第一章：标题 → 提取"标题"
    3. 引号标题: "标题" → 提取"标题"
    4. 第一行前20字作为标题预览
    5. 兜底: "未命名章节"
    
    Args:
        content: 章节内容
        chapter_number: 数据库分配的章节编号
        
    Returns:
        完整标题字符串（格式：第X章：标题）
    """
    if not content or not content.strip():
        return f"第{chapter_number}章：未命名章节"
    
    # 提取第一行（去除前后空白）
    first_line = content.split('\n')[0].strip()
    
    # 🔥 策略1: 匹配 Markdown 加粗标题 **第X章：标题**
    pattern_bold = r'\*\*第[一二三四五六七八九十\d]+章[：:]\s*(.+?)\*\*'
    match_bold = re.match(pattern_bold, first_line)
    if match_bold:
        title_only = match_bold.group(1).strip()
        # 递归去除所有嵌套的"第X章："前缀
        title_only = _remove_chapter_prefix(title_only)
        # 🆕 只保留标题文字，移除后面的正文内容
        title_only = _extract_title_only(title_only)
        return f"第{chapter_number}章：{title_only}"
    
    # 🔥 策略2: 匹配普通标题 第X章：标题
    clean_line = first_line.replace('*', '').strip()
    pattern_normal = r'第[一二三四五六七八九十\d]+章[：:]\s*(.+)'
    match_normal = re.match(pattern_normal, clean_line)
    if match_normal:
        title_only = match_normal.group(1).strip()
        # 递归去除所有嵌套的"第X章："前缀
        title_only = _remove_chapter_prefix(title_only)
        # 🆕 只保留标题文字，移除后面的正文内容
        title_only = _extract_title_only(title_only)
        return f"第{chapter_number}章：{title_only}"
    
    # 🔥 策略3: 匹配引号包裹的标题 "标题" 或 "第X章：标题"
    pattern_quoted = r'["\'](.+?)["\']'
    match_quoted = re.match(pattern_quoted, clean_line)
    if match_quoted:
        title_only = match_quoted.group(1).strip()
        # 去除可能的章节前缀
        title_only = _remove_chapter_prefix(title_only)
        # 🆕 只保留标题文字
        title_only = _extract_title_only(title_only)
        return f"第{chapter_number}章：{title_only}"
    
    # 策略4: 使用第一行前20个字符作为标题预览
    clean_preview = clean_line[:20].strip()
    if clean_preview:
        # 确保预览内容也不包含章节前缀
        clean_preview = _remove_chapter_prefix(clean_preview)
        return f"第{chapter_number}章：{clean_preview}"
    
    # 兜底: 使用默认标题
    return f"第{chapter_number}章：未命名章节"


def _remove_chapter_prefix(text: str) -> str:
    """
    递归移除文本中的所有"第X章："前缀
    
    示例:
    - "第1章：深夜解密" → "深夜解密"
    - "第1章：第2章：标题" → "标题"
    - "深夜解密" → "深夜解密"
    """
    text = text.strip().strip('"\'')
    pattern = r'^第[一二三四五六七八九十\d]+章[：:]\s*(.+)'
    match = re.match(pattern, text)
    if match:
        # 递归处理，直到没有"第X章："前缀
        return _remove_chapter_prefix(match.group(1))
    return text


def _extract_title_only(text: str) -> str:
    """
    从文本中只提取标题部分，移除后面的正文内容
    
    示例:
    - "深夜解密\\n\\nAlex的处理器" → "深夜解密"
    - "深夜解密" → "深夜解密"
    - "标题 正文开始" → "标题"
    
    策略：
    1. 如果包含\\n\\n（两个换行），只取第一部分
    2. 如果包含\\n（单个换行），只取第一部分
    3. 去除引号
    4. 限制长度为50字符（超过50字可能包含正文）
    """
    text = text.strip().strip('"\'')
    
    # 移除\\n\\n后面的内容（正文开始）
    if '\\n\\n' in text:
        text = text.split('\\n\\n')[0].strip()
    
    # 移除单个\\n后面的内容
    if '\\n' in text:
        text = text.split('\\n')[0].strip()
    
    # 限制最大长度（标题一般不会超过50字）
    if len(text) > 50:
        text = text[:50].strip()
    
    return text


@router.post("/", response_model=ChapterResponse, status_code=status.HTTP_201_CREATED)
async def create_chapter(
    chapter_data: ChapterCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建章节"""
    # 验证项目存在且属于当前用户
    project = db.query(Project).filter(
        (Project.id == chapter_data.project_id) & (Project.user_id == current_user.id)
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # 计算章节编号
    if hasattr(chapter_data, 'chapter_number') and chapter_data.chapter_number:
        chapter_number = chapter_data.chapter_number
    else:
        # 自动计算下一个章节号
        max_chapter = db.query(Chapter).filter(
            Chapter.project_id == chapter_data.project_id
        ).order_by(Chapter.chapter_number.desc()).first()
        chapter_number = (max_chapter.chapter_number + 1) if max_chapter else 1
    
    # 🆕 智能标题提取
    if chapter_data.title:
        # 用户手动指定标题，优先使用
        final_title = chapter_data.title
    else:
        # 从内容中智能提取标题
        final_title = extract_title_from_content(
            chapter_data.content or "", 
            chapter_number
        )
    
    # 创建章节
    chapter = Chapter(
        project_id=chapter_data.project_id,
        chapter_number=chapter_number,
        title=final_title,
        content=chapter_data.content or "",
        # 🔧 修复：使用正确的中文字数统计
        word_count=len(re.sub(r'\s', '', chapter_data.content)) if chapter_data.content else 0
    )
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter


@router.get("/{chapter_id}", response_model=ChapterResponse)
async def get_chapter(
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取章节详情"""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 检查权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated project not found"
        )
    
    # 类型断言：在此时project已经确认不为None
    project_user_id: int = cast(int, project.user_id)
    current_user_id: int = cast(int, current_user.id)
    
    if project_user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    return chapter


@router.put("/{chapter_id}", response_model=ChapterResponse)
async def update_chapter(
    chapter_id: int,
    chapter_data: ChapterUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新章节"""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 检查权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated project not found"
        )
    
    # 类型断言：在此时project已经确认不为None
    project_user_id: int = cast(int, project.user_id)
    current_user_id: int = cast(int, current_user.id)
    
    if project_user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # 更新字段
    if chapter_data.title is not None:
        chapter.title = cast(str, chapter_data.title)  # type: ignore[assignment]
    if chapter_data.content is not None:
        # 🆕 保存前先创建版本快照
        if chapter.content and chapter.content != chapter_data.content:
            revision = ChapterRevision(
                chapter_id=chapter_id,
                content=chapter.content,
                word_count=chapter.word_count,
                revision_note="手动保存前的版本",
                created_by=current_user.id
            )
            db.add(revision)
        
        chapter.content = cast(str, chapter_data.content)  # type: ignore[assignment]
        # 🔧 修复：使用正确的中文字数统计
        import re
        chapter.word_count = len(re.sub(r'\s', '', chapter_data.content))  # type: ignore[assignment]
    if chapter_data.status is not None:
        chapter.status = cast(str, chapter_data.status)  # type: ignore[assignment]
    
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter


@router.delete("/{chapter_id}")
async def delete_chapter(
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """删除章节"""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 检查权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated project not found"
        )
    
    # 类型断言：在此时project已经确认不为None
    project_user_id: int = cast(int, project.user_id)
    current_user_id: int = cast(int, current_user.id)
    
    if project_user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # 🆕 清理记忆数据：如果某个记忆的 current_chapter 指向被删除的章节，将其置为 NULL
    from app.models.memory import Memory
    db.query(Memory).filter(
        (Memory.project_id == chapter.project_id) & 
        (Memory.current_chapter == chapter.chapter_number)
    ).update({Memory.current_chapter: None})
    
    # 🆕 同步删除知识库中的相关条目
    try:
        from app.models.knowledge_base import KnowledgeBase
        # 删除与该章节相关的知识库条目
        db.query(KnowledgeBase).filter(
            (KnowledgeBase.project_id == chapter.project_id) &
            (KnowledgeBase.type == 'chapter') &
            (KnowledgeBase.content.like(f"%第{chapter.chapter_number}章%"))
        ).delete(synchronize_session=False)
        db.commit()
    except Exception as e:
        # 不中断主流程，记录错误
        import logging
        logger = logging.getLogger("uvicorn.error")
        logger.warning(f"⚠️ 删除章节时清理知识库失败: {e}")
        db.rollback()
    
    # 🆕 同步删除向量库中的相关向量数据
    try:
        from app.services.agents.knowledge_base import NovelKnowledgeBase
        import logging
        logger = logging.getLogger("uvicorn.error")

        logger.info(f"   🗑️  同步删除向量库中的章节数据...")

        # 使用知识库的删除方法
        kb = NovelKnowledgeBase()
        deleted_count = kb.delete_chapter(
            chapter_number=chapter.chapter_number,
            project_id=chapter.project_id
        )

        if deleted_count > 0:
            logger.info(f"   ✅ 已从向量库删除 {deleted_count} 个文档")
        else:
            logger.info(f"   ℹ️  向量库中未找到第{chapter.chapter_number}章的数据")

    except Exception as e:
        # 不中断主流程，记录错误
        import logging
        logger = logging.getLogger("uvicorn.error")
        logger.warning(f"⚠️ 删除章节时清理向量库失败: {e}")
        import traceback
        logger.debug(traceback.format_exc())
    
    # 删除章节（评审数据会自动级联删除）
    db.delete(chapter)
    db.commit()
    return {"message": "Chapter deleted successfully"}


@router.post("/{chapter_id}/auto-save")
async def auto_save_chapter(
    chapter_id: int,
    chapter_data: ChapterUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """自动保存章节"""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 检查权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated project not found"
        )
    
    # 类型断言：在此时project已经确认不为None
    project_user_id: int = cast(int, project.user_id)
    current_user_id: int = cast(int, current_user.id)
    
    if project_user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # 更新内容
    if chapter_data.content is not None:
        # 🆕 自动保存时也创建版本快照（但频率较低，每5分钟最多1次）
        from datetime import timedelta
        should_create_revision = True
        
        # 检查最近的版本是否在5分钟内
        latest_revision = db.query(ChapterRevision).filter(
            ChapterRevision.chapter_id == chapter_id
        ).order_by(ChapterRevision.created_at.desc()).first()
        
        if latest_revision:
            time_diff = datetime.now() - latest_revision.created_at.replace(tzinfo=None)
            if time_diff < timedelta(minutes=5):
                should_create_revision = False
        
        # 如果内容变化且距离上次版本超过5分钟，创建版本
        if should_create_revision and chapter.content and chapter.content != chapter_data.content:
            revision = ChapterRevision(
                chapter_id=chapter_id,
                content=chapter.content,
                word_count=chapter.word_count,
                revision_note="自动保存的版本",
                created_by=current_user.id
            )
            db.add(revision)
        
        chapter.content = cast(str, chapter_data.content)  # type: ignore[assignment]
        # 🔧 修复：使用正确的中文字数统计（移除空白字符后的字符数）
        import re
        chapter.word_count = len(re.sub(r'\s', '', chapter_data.content))  # type: ignore[assignment]
    
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    
    return {
        "message": "Chapter auto-saved successfully",
        "chapter": ChapterResponse.from_orm(chapter)
    }


# ===========================
# 版本历史API端点
# ===========================

@router.get("/{chapter_id}/revisions", response_model=List[ChapterRevisionResponse])
async def get_chapter_revisions(
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取章节的所有版本历史（按时间倒序）"""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 验证权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if project is None or project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # 获取版本历史（按时间倒序）
    revisions = db.query(ChapterRevision).filter(
        ChapterRevision.chapter_id == chapter_id
    ).order_by(ChapterRevision.created_at.desc()).all()
    
    return revisions


@router.post("/{chapter_id}/revisions/{revision_id}/restore", response_model=ChapterResponse)
async def restore_chapter_revision(
    chapter_id: int,
    revision_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """从历史版本恢复章节内容"""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 验证权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if project is None or project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # 获取版本历史
    revision = db.query(ChapterRevision).filter(
        (ChapterRevision.id == revision_id) & 
        (ChapterRevision.chapter_id == chapter_id)
    ).first()
    
    if revision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Revision not found"
        )
    
    # 保存当前版本到历史
    if chapter.content:
        current_revision = ChapterRevision(
            chapter_id=chapter_id,
            content=chapter.content,
            word_count=chapter.word_count,
            revision_note="恢复前的版本",
            created_by=current_user.id
        )
        db.add(current_revision)
    
    # 恢复内容
    chapter.content = cast(str, revision.content)  # type: ignore[assignment]
    chapter.word_count = revision.word_count  # type: ignore[assignment]
    
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    
    return chapter


# ===========================
# 导出API端点
# ===========================

@router.get("/{chapter_id}/export/txt")
async def export_chapter_txt(
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """导出章节为TXT格式（UTF-8编码）"""
    from urllib.parse import quote
    
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 验证权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if project is None or project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # 生成TXT内容（UTF-8编码）
    content = f"{chapter.title}\n\n{chapter.content or ''}"
    
    # 对文件名进行URL编码以支持中文
    filename_encoded = quote(f"{chapter.title}.txt")
    
    # 返回TXT文件
    return Response(
        content=content.encode('utf-8'),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"
        }
    )


@router.get("/{chapter_id}/export/docx")
async def export_chapter_docx(
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """导出章节为DOCX格式（专业排版）"""
    from urllib.parse import quote
    
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 验证权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if project is None or project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # 创建DOCX文档
    doc = Document()
    
    # 添加标题（居中、加粗、16磅）
    title_para = doc.add_paragraph(chapter.title)
    title_para.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    title_run = title_para.runs[0]
    title_run.bold = True
    title_run.font.size = Pt(16)
    
    # 添加空行
    doc.add_paragraph()
    
    # 添加正文（按段落分割）
    if chapter.content:
        paragraphs = chapter.content.split('\n')
        for para_text in paragraphs:
            if para_text.strip():
                para = doc.add_paragraph(para_text.strip())
                # 设置正文格式：首行缩进2字符
                para.paragraph_format.first_line_indent = Inches(0.5)
    
    # 将文档保存到BytesIO
    docx_io = BytesIO()
    doc.save(docx_io)
    docx_io.seek(0)
    
    # 对文件名进行URL编码以支持中文
    filename_encoded = quote(f"{chapter.title}.docx")
    
    # 返回DOCX文件
    return StreamingResponse(
        docx_io,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"
        }
    )

