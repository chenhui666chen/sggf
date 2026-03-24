"""
拆书工具 API 接口

提供书籍上传、解析、分析、导入等功能
"""
import os
import json
import asyncio
import threading
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.db.base import get_db
from app.core.security import get_current_user
from app.models.book_parser import BookSource, BookChapter, BookAnalysis, ParseStatus, AnalysisType as DBAnalysisType
from app.models.project import Project
from app.services.book_parser import (
    ChapterSplitter, 
    TextCleaner, 
    ContentAnalyzer,
    AnalysisType,
    FileParser,
    FileFormat,
    ParsedContent,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/book-parser", tags=["book-parser"])


# ==================== 请求/响应模型 ====================

class UploadTextRequest(BaseModel):
    """文本上传请求"""
    title: str
    content: str
    author: Optional[str] = None
    genre: Optional[str] = None
    description: Optional[str] = None


class BookResponse(BaseModel):
    """书籍响应"""
    id: int
    title: str
    author: Optional[str]
    genre: Optional[str]
    description: Optional[str]
    source_type: str
    status: str
    parse_progress: int
    total_words: int
    total_chapters: int
    total_volumes: int
    created_at: str
    imported_project_id: Optional[int]

    class Config:
        from_attributes = True


class ChapterResponse(BaseModel):
    """章节响应"""
    id: int
    chapter_number: int
    title: str
    word_count: int
    chapter_type: str
    volume_number: Optional[int]
    volume_title: Optional[str]
    summary: Optional[str]

    class Config:
        from_attributes = True


class ChapterContentResponse(BaseModel):
    """章节详情响应"""
    chapter_number: int
    title: str
    content: str
    word_count: int
    summary: Optional[str] = None
    key_events: List[str] = Field(default_factory=list)
    appearing_characters: List[str] = Field(default_factory=list)
    outline_data: Dict[str, Any] = Field(default_factory=dict)


class AnalysisResponse(BaseModel):
    """分析结果响应"""
    id: int
    analysis_type: str
    content: Dict[str, Any]
    confidence: float
    completeness: float
    extra_data: Optional[Dict[str, Any]] = None
    created_at: str

    class Config:
        from_attributes = True


class ParseStatusResponse(BaseModel):
    """解析状态响应"""
    status: str
    progress: int
    message: str
    chapters_count: Optional[int] = None
    error: Optional[str] = None


class ImportRequest(BaseModel):
    """导入项目请求"""
    project_title: Optional[str] = None
    import_settings: bool = True
    import_characters: bool = True
    import_chapters: bool = False  # 🆕 导入章节内容
    start_from_chapter: Optional[int] = None


# ==================== 后台任务存储 ====================

# 存储后台任务状态
_task_status: Dict[str, Dict[str, Any]] = {}


def get_task_status(book_id: int) -> Dict[str, Any]:
    """获取任务状态"""
    return _task_status.get(str(book_id), {
        "status": "unknown",
        "progress": 0,
        "message": "未找到任务"
    })


def _safe_parse_json_field(raw_value: Any, default: Any) -> Any:
    """安全解析 JSON 字段，失败时回退默认值。"""
    if raw_value is None or raw_value == "":
        return default

    if isinstance(raw_value, str):
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError:
            return default

    return raw_value


def _build_chapter_content_response(chapter: BookChapter) -> ChapterContentResponse:
    """构建带结构化资产的章节详情响应。"""
    key_events = _safe_parse_json_field(chapter.key_events, [])
    if not isinstance(key_events, list):
        key_events = []

    appearing_characters = _safe_parse_json_field(chapter.appearing_characters, [])
    if not isinstance(appearing_characters, list):
        appearing_characters = []

    outline_data = _safe_parse_json_field(chapter.outline_data, {})
    if not isinstance(outline_data, dict):
        outline_data = {}

    return ChapterContentResponse(
        chapter_number=chapter.chapter_number,
        title=chapter.title,
        content=chapter.content or "",
        word_count=chapter.word_count,
        summary=chapter.summary,
        key_events=key_events,
        appearing_characters=appearing_characters,
        outline_data=outline_data,
    )


def update_task_status(book_id: int, status: str, progress: int, message: str, error: Optional[str] = None):
    """更新任务状态"""
    _task_status[str(book_id)] = {
        "status": status,
        "progress": progress,
        "message": message,
        "error": error,
        "updated_at": datetime.now().isoformat()
    }


# ==================== API 接口 ====================

@router.post("/upload-text", response_model=BookResponse)
async def upload_text(
    request: UploadTextRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    上传文本内容
    
    创建一个新的书籍记录，存储原始文本
    """
    # 创建文本清洗器
    cleaner = TextCleaner()
    clean_result = cleaner.clean(request.content)
    
    # 尝试从文本中提取元数据
    metadata = cleaner.extract_metadata_from_header(request.content)
    
    # 创建书籍记录
    book = BookSource(
        user_id=current_user.id,
        title=request.title or metadata.get("title", "未命名书籍"),
        author=request.author or metadata.get("author"),
        genre=request.genre,
        description=request.description or metadata.get("description"),
        source_type="text",
        total_words=clean_result.word_count,
        status=ParseStatus.PENDING.value,
    )
    
    db.add(book)
    db.commit()
    db.refresh(book)
    
    # 存储清洗后的文本（存为临时文件）
    text_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "book_texts")
    os.makedirs(text_dir, exist_ok=True)
    text_path = os.path.join(text_dir, f"book_{book.id}.txt")
    
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(clean_result.text)
    
    book.file_path = text_path
    db.commit()
    
    logger.info(f"✅ 书籍文本上传成功: {book.title} (ID: {book.id})")
    
    return BookResponse(
        id=book.id,
        title=book.title,
        author=book.author,
        genre=book.genre,
        description=book.description,
        source_type=book.source_type,
        status=book.status,
        parse_progress=book.parse_progress,
        total_words=book.total_words,
        total_chapters=book.total_chapters,
        total_volumes=book.total_volumes,
        created_at=book.created_at.isoformat() if book.created_at else "",
        imported_project_id=book.imported_project_id,
    )


@router.post("/upload-file", response_model=BookResponse)
async def upload_file(
    file: UploadFile = File(...),
    title: str = Form(None),
    author: str = Form(None),
    genre: str = Form(None),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    上传文件
    
    支持 TXT、EPUB、PDF 格式文件
    """
    # 验证文件名
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    
    filename = file.filename.lower()
    
    # 验证文件格式
    if not any(filename.endswith(ext) for ext in ['.txt', '.epub', '.pdf']):
        raise HTTPException(
            status_code=400, 
            detail="仅支持 TXT、EPUB、PDF 格式文件"
        )
    
    # 读取文件内容
    content = await file.read()
    
    # 使用多格式解析器
    parser = FileParser()
    parsed = parser.parse(content, file.filename)
    
    if not parsed.success:
        raise HTTPException(
            status_code=400,
            detail=f"文件解析失败: {parsed.error}"
        )
    
    # 清洗文本
    cleaner = TextCleaner()
    clean_result = cleaner.clean(parsed.text)
    
    # 元数据提取（优先使用文件内提取的元数据）
    metadata = cleaner.extract_metadata_from_header(parsed.text)
    
    # 确定书名和作者（优先级：用户输入 > 文件元数据 > 文本元数据 > 文件名）
    book_title = (
        title 
        or parsed.title 
        or metadata.get("title") 
        or file.filename.rsplit('.', 1)[0]
    )
    
    book_author = (
        author 
        or parsed.author 
        or metadata.get("author")
    )
    
    # 创建书籍记录
    book = BookSource(
        user_id=current_user.id,
        title=book_title,
        author=book_author,
        genre=genre,
        description=metadata.get("description"),
        source_type=parsed.format.value,  # txt/epub/pdf
        total_words=clean_result.word_count,
        status=ParseStatus.PENDING.value,
    )
    
    db.add(book)
    db.commit()
    db.refresh(book)
    
    # 存储文件（统一保存为 TXT 格式）
    text_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "book_texts")
    os.makedirs(text_dir, exist_ok=True)
    text_path = os.path.join(text_dir, f"book_{book.id}.txt")
    
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(clean_result.text)
    
    book.file_path = text_path
    db.commit()
    
    logger.info(f"✅ 书籍文件上传成功: {book.title} (ID: {book.id}, 格式: {parsed.format.value})")
    
    return BookResponse(
        id=book.id,
        title=book.title,
        author=book.author,
        genre=book.genre,
        description=book.description,
        source_type=book.source_type,
        status=book.status,
        parse_progress=book.parse_progress,
        total_words=book.total_words,
        total_chapters=book.total_chapters,
        total_volumes=book.total_volumes,
        created_at=book.created_at.isoformat() if book.created_at else "",
        imported_project_id=book.imported_project_id,
    )


@router.get("/list", response_model=List[BookResponse])
async def list_books(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取用户的书籍列表
    """
    books = db.query(BookSource).filter(
        BookSource.user_id == current_user.id
    ).order_by(BookSource.created_at.desc()).all()
    
    return [
        BookResponse(
            id=book.id,
            title=book.title,
            author=book.author,
            genre=book.genre,
            description=book.description,
            source_type=book.source_type,
            status=book.status,
            parse_progress=book.parse_progress,
            total_words=book.total_words,
            total_chapters=book.total_chapters,
            total_volumes=book.total_volumes,
            created_at=book.created_at.isoformat() if book.created_at else "",
            imported_project_id=book.imported_project_id,
        )
        for book in books
    ]


@router.get("/{book_id}", response_model=BookResponse)
async def get_book(
    book_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取书籍详情
    """
    book = db.query(BookSource).filter(
        BookSource.id == book_id,
        BookSource.user_id == current_user.id
    ).first()
    
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    
    return BookResponse(
        id=book.id,
        title=book.title,
        author=book.author,
        genre=book.genre,
        description=book.description,
        source_type=book.source_type,
        status=book.status,
        parse_progress=book.parse_progress,
        total_words=book.total_words,
        total_chapters=book.total_chapters,
        total_volumes=book.total_volumes,
        created_at=book.created_at.isoformat() if book.created_at else "",
        imported_project_id=book.imported_project_id,
    )


@router.get("/{book_id}/chapters", response_model=List[ChapterResponse])
async def get_book_chapters(
    book_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取书籍章节列表
    """
    book = db.query(BookSource).filter(
        BookSource.id == book_id,
        BookSource.user_id == current_user.id
    ).first()
    
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    
    chapters = db.query(BookChapter).filter(
        BookChapter.book_id == book_id
    ).order_by(BookChapter.chapter_number).all()
    
    return [
        ChapterResponse(
            id=ch.id,
            chapter_number=ch.chapter_number,
            title=ch.title,
            word_count=ch.word_count,
            chapter_type=ch.chapter_type,
            volume_number=ch.volume_number,
            volume_title=ch.volume_title,
            summary=ch.summary,
        )
        for ch in chapters
    ]


@router.get("/{book_id}/analyses", response_model=List[AnalysisResponse])
async def get_book_analyses(
    book_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取书籍分析结果
    """
    book = db.query(BookSource).filter(
        BookSource.id == book_id,
        BookSource.user_id == current_user.id
    ).first()
    
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    
    analyses = db.query(BookAnalysis).filter(
        BookAnalysis.book_id == book_id
    ).all()
    
    return [
        AnalysisResponse(
            id=a.id,
            analysis_type=a.analysis_type,
            content=json.loads(a.content) if isinstance(a.content, str) else a.content,
            confidence=a.confidence,
            completeness=a.completeness,
            extra_data=json.loads(a.extra_data) if isinstance(a.extra_data, str) and a.extra_data else a.extra_data,
            created_at=a.created_at.isoformat() if a.created_at else "",
        )
        for a in analyses
    ]


@router.post("/{book_id}/parse")
async def parse_book(
    book_id: int,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    执行章节切分（异步）
    
    返回任务ID，前端通过 /status 接口轮询进度
    """
    book = db.query(BookSource).filter(
        BookSource.id == book_id,
        BookSource.user_id == current_user.id
    ).first()
    
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    
    if not book.file_path or not os.path.exists(book.file_path):
        raise HTTPException(status_code=400, detail="书籍文本文件不存在")
    
    # 更新状态
    book.status = ParseStatus.PARSING.value
    book.parse_progress = 0
    db.commit()
    
    update_task_status(book_id, "parsing", 0, "开始解析章节...")
    
    # 启动后台任务
    def run_parse():
        _do_parse_book(book_id)
    
    thread = threading.Thread(target=run_parse, daemon=True)
    thread.start()
    
    return {
        "message": "章节解析任务已启动",
        "book_id": book_id,
        "status": "parsing"
    }


def _do_parse_book(book_id: int):
    """
    执行章节切分（后台线程）
    """
    from app.db.base import SessionLocal
    db = SessionLocal()
    
    try:
        book = db.query(BookSource).filter(BookSource.id == book_id).first()
        if not book:
            update_task_status(book_id, "failed", 0, "书籍不存在", "书籍记录未找到")
            return
        
        # 读取文本
        with open(book.file_path, "r", encoding="utf-8") as f:
            text = f.read()
        
        update_task_status(book_id, "parsing", 20, "正在分析章节结构...")
        
        # 切分章节
        splitter = ChapterSplitter()
        result = splitter.split(text)
        
        update_task_status(book_id, "parsing", 60, f"识别到 {len(result.chapters)} 个章节，正在保存...")
        
        # 删除旧章节
        db.query(BookChapter).filter(BookChapter.book_id == book_id).delete()
        
        # 保存章节
        for ch_info in result.chapters:
            chapter = BookChapter(
                book_id=book_id,
                chapter_number=ch_info.number,
                title=ch_info.title,
                content=ch_info.content,
                word_count=ch_info.word_count,
                chapter_type=ch_info.chapter_type.value,
                volume_number=ch_info.volume_number,
                volume_title=ch_info.volume_title,
                part_number=ch_info.part_number,
                part_title=ch_info.part_title,
                start_position=ch_info.start_position,
                end_position=ch_info.end_position,
            )
            db.add(chapter)
        
        # 更新书籍统计
        book.total_chapters = len(result.chapters)
        book.total_volumes = result.total_volumes
        book.total_words = result.total_words
        book.status = ParseStatus.CHAPTERS_DONE.value
        book.parse_progress = 100
        
        db.commit()
        
        update_task_status(book_id, "chapters_done", 100, f"章节解析完成，共 {len(result.chapters)} 章")
        logger.info(f"✅ 书籍章节解析完成: {book.title} ({len(result.chapters)} 章)")
        
    except Exception as e:
        logger.error(f"❌ 书籍解析失败: {e}")
        update_task_status(book_id, "failed", 0, "解析失败", str(e))
        
        try:
            book = db.query(BookSource).filter(BookSource.id == book_id).first()
            if book:
                book.status = ParseStatus.FAILED.value
                book.error_message = str(e)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.post("/{book_id}/analyze")
async def analyze_book(
    book_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    执行AI内容分析（异步）
    
    需要先完成章节切分
    """
    book = db.query(BookSource).filter(
        BookSource.id == book_id,
        BookSource.user_id == current_user.id
    ).first()
    
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    
    if book.status not in [ParseStatus.CHAPTERS_DONE.value, ParseStatus.COMPLETED.value]:
        raise HTTPException(status_code=400, detail="请先完成章节切分")
    
    # 更新状态
    book.status = ParseStatus.ANALYZING.value
    db.commit()
    
    update_task_status(book_id, "analyzing", 0, "开始AI分析...")
    
    # 启动后台任务
    def run_analyze():
        asyncio.run(_do_analyze_book(book_id))
    
    thread = threading.Thread(target=run_analyze, daemon=True)
    thread.start()
    
    return {
        "message": "AI分析任务已启动",
        "book_id": book_id,
        "status": "analyzing"
    }


async def _do_analyze_book(book_id: int):
    """
    执行AI内容分析（后台线程）
    """
    from app.db.base import SessionLocal
    db = SessionLocal()
    
    try:
        book = db.query(BookSource).filter(BookSource.id == book_id).first()
        if not book:
            update_task_status(book_id, "failed", 0, "书籍不存在", "书籍记录未找到")
            return
        
        # 获取章节
        chapters_db = db.query(BookChapter).filter(
            BookChapter.book_id == book_id
        ).order_by(BookChapter.chapter_number).all()
        
        if not chapters_db:
            update_task_status(book_id, "failed", 0, "没有章节数据", "请先执行章节切分")
            return
        
        # 转换为 ChapterInfo 对象
        from app.services.book_parser.chapter_splitter import ChapterInfo, ChapterType
        chapters = []
        for ch in chapters_db:
            chapters.append(ChapterInfo(
                number=ch.chapter_number,
                title=ch.title,
                content=ch.content or "",
                word_count=ch.word_count,
                chapter_type=ChapterType(ch.chapter_type) if ch.chapter_type else ChapterType.NORMAL,
                volume_number=ch.volume_number,
                volume_title=ch.volume_title,
            ))
        
        # 创建分析器
        analyzer = ContentAnalyzer()
        
        # 进度回调
        async def on_progress(stage: str, progress: int, message: str):
            update_task_status(book_id, "analyzing", progress, message)
        
        # 执行分析
        results, chapter_summaries = await analyzer.analyze_all(chapters, on_progress=on_progress)
        
        # 🆕 保存章节细纲到 BookChapter 表
        if chapter_summaries:
            for summary in chapter_summaries:
                chapter_num = summary.get("chapter_number")
                if chapter_num:
                    book_chapter = db.query(BookChapter).filter(
                        BookChapter.book_id == book_id,
                        BookChapter.chapter_number == chapter_num
                    ).first()
                    if book_chapter:
                        # 保存基础摘要
                        book_chapter.summary = summary.get("summary", "")
                        book_chapter.key_events = json.dumps(
                            summary.get("key_events", []), ensure_ascii=False
                        )
                        book_chapter.appearing_characters = json.dumps(
                            summary.get("characters_appeared", []), ensure_ascii=False
                        )
                        # 🆕 保存完整细纲数据
                        outline_data = {
                            "scene_goal": summary.get("scene_goal", ""),
                            "conflict_arc": summary.get("conflict_arc", {}),
                            "emotion_curve": summary.get("emotion_curve", ""),
                            "highlight": summary.get("highlight", {}),
                            "ending_hook": summary.get("ending_hook", {}),
                            "gains": summary.get("gains", {}),
                            "foreshadowing": summary.get("foreshadowing", []),
                            "setting": summary.get("setting", ""),
                            "conflict": summary.get("conflict", ""),
                            "emotion_tone": summary.get("emotion_tone", "")
                        }
                        book_chapter.outline_data = json.dumps(outline_data, ensure_ascii=False)
            logger.info(f"✅ 保存了 {len(chapter_summaries)} 章细纲数据")
        
        # 删除旧的分析结果
        db.query(BookAnalysis).filter(BookAnalysis.book_id == book_id).delete()
        
        # 保存分析结果
        for result in results:
            analysis = BookAnalysis(
                book_id=book_id,
                analysis_type=result.analysis_type.value,
                content=json.dumps(result.content, ensure_ascii=False),
                confidence=result.confidence,
                completeness=result.confidence,  # 暂时使用相同值
                chapter_range_start=result.chapter_range[0],
                chapter_range_end=result.chapter_range[1],
                extra_data=json.dumps(result.extra_data, ensure_ascii=False) if result.extra_data else None,
                model_used=result.model_used,
            )
            db.add(analysis)
        
        book.status = ParseStatus.COMPLETED.value
        book.parsed_at = datetime.now()
        db.commit()
        
        update_task_status(book_id, "completed", 100, f"分析完成，提取了 {len(results)} 类信息")
        logger.info(f"✅ 书籍AI分析完成: {book.title}")
        
    except Exception as e:
        logger.error(f"❌ 书籍AI分析失败: {e}")
        import traceback
        traceback.print_exc()
        update_task_status(book_id, "failed", 0, "分析失败", str(e))
        
        try:
            book = db.query(BookSource).filter(BookSource.id == book_id).first()
            if book:
                book.status = ParseStatus.FAILED.value
                book.error_message = str(e)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.get("/{book_id}/status", response_model=ParseStatusResponse)
async def get_parse_status(
    book_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取解析/分析状态
    """
    book = db.query(BookSource).filter(
        BookSource.id == book_id,
        BookSource.user_id == current_user.id
    ).first()
    
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    
    # 获取任务状态
    task_status = get_task_status(book_id)
    
    return ParseStatusResponse(
        status=task_status.get("status", book.status),
        progress=task_status.get("progress", book.parse_progress),
        message=task_status.get("message", ""),
        chapters_count=book.total_chapters,
        error=task_status.get("error") or book.error_message,
    )


@router.delete("/{book_id}")
async def delete_book(
    book_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除书籍
    """
    book = db.query(BookSource).filter(
        BookSource.id == book_id,
        BookSource.user_id == current_user.id
    ).first()
    
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    
    # 删除文本文件
    if book.file_path and os.path.exists(book.file_path):
        try:
            os.remove(book.file_path)
        except Exception as e:
            logger.warning(f"删除文件失败: {e}")
    
    # 删除数据库记录（级联删除章节和分析结果）
    db.delete(book)
    db.commit()
    
    logger.info(f"✅ 书籍已删除: {book.title} (ID: {book_id})")
    
    return {"message": "删除成功", "book_id": book_id}


@router.get("/{book_id}/chapter/{chapter_number}/content", response_model=ChapterContentResponse)
async def get_chapter_content(
    book_id: int,
    chapter_number: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取章节内容
    """
    book = db.query(BookSource).filter(
        BookSource.id == book_id,
        BookSource.user_id == current_user.id
    ).first()
    
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    
    chapter = db.query(BookChapter).filter(
        BookChapter.book_id == book_id,
        BookChapter.chapter_number == chapter_number
    ).first()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    return _build_chapter_content_response(chapter)


@router.get("/{book_id}/preview")
async def preview_structure(
    book_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    预览书籍结构（不执行完整切分）
    """
    book = db.query(BookSource).filter(
        BookSource.id == book_id,
        BookSource.user_id == current_user.id
    ).first()
    
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    
    if not book.file_path or not os.path.exists(book.file_path):
        raise HTTPException(status_code=400, detail="书籍文本文件不存在")
    
    # 读取文本
    with open(book.file_path, "r", encoding="utf-8") as f:
        text = f.read()
    
    # 分析结构
    splitter = ChapterSplitter()
    structure = splitter.analyze_structure(text)
    
    return {
        "book_id": book_id,
        "title": book.title,
        "structure": structure
    }


@router.get("/{book_id}/import-preview")
async def get_import_preview(
    book_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取导入预览信息
    
    显示可导入的内容和选项
    """
    book = db.query(BookSource).filter(
        BookSource.id == book_id,
        BookSource.user_id == current_user.id
    ).first()
    
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    
    from app.services.book_parser import ProjectBridge
    bridge = ProjectBridge(db)
    preview = bridge.get_import_preview(book_id)
    
    return preview


@router.post("/{book_id}/import")
async def import_to_project(
    book_id: int,
    request: ImportRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    将书籍导入为工作流项目
    
    创建新项目并导入设定、人物等
    """
    book = db.query(BookSource).filter(
        BookSource.id == book_id,
        BookSource.user_id == current_user.id
    ).first()
    
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    
    if book.status != ParseStatus.COMPLETED.value:
        raise HTTPException(status_code=400, detail="请先完成AI分析")
    
    if book.imported_project_id:
        raise HTTPException(status_code=400, detail="该书籍已导入为项目")
    
    try:
        from app.services.book_parser import ProjectBridge
        bridge = ProjectBridge(db)
        
        project = bridge.import_to_project(
            book_id=book_id,
            user_id=current_user.id,
            project_title=request.project_title,
            import_settings=request.import_settings,
            import_characters=request.import_characters,
            import_chapters=request.import_chapters,  # 🆕 使用用户选择
            start_from_chapter=request.start_from_chapter,
        )
        
        logger.info(f"✅ 书籍导入成功: {book.title} -> 项目 {project.id}")
        
        return {
            "message": "导入成功",
            "project_id": project.id,
            "project_title": project.title,
        }
        
    except Exception as e:
        logger.error(f"❌ 书籍导入失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{book_id}/import")
async def reset_import_status(
    book_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    重置书籍的导入状态
    
    清除 imported_project_id，允许重新导入
    """
    book = db.query(BookSource).filter(
        BookSource.id == book_id,
        BookSource.user_id == current_user.id
    ).first()
    
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    
    if not book.imported_project_id:
        raise HTTPException(status_code=400, detail="该书籍尚未导入")
    
    # 清除导入状态
    book.imported_project_id = None
    db.commit()
    
    logger.info(f"✅ 已重置书籍导入状态: {book.title} (ID: {book.id})")
    
    return {
        "message": "已重置导入状态，可以重新导入",
        "book_id": book.id,
        "title": book.title,
    }
