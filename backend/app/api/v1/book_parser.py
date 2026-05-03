"""
拆书工具 API 接口

提供书籍上传、解析、分析、导入等功能
"""
import os
import json
import asyncio
import threading
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict, Field

from app.db.base import get_db
from app.core.security import get_current_user
from app.models.book_parser import BookSource, BookChapter, BookAnalysis, ParseStatus, AnalysisType as DBAnalysisType
from app.models.project import Project
from app.services.points_usage_pricing import (
    build_points_billing_precheck,
    build_points_billing_precheck_error_detail,
    build_points_usage_charge_estimate,
    estimate_book_analyze_basis_yuan,
    estimate_book_parse_basis_yuan,
)
from app.services.user_center_points_events import (
    POINTS_BILLING_MODULE_BOOK_PARSER,
    build_points_billing_key,
    record_points_billing_freeze,
    record_points_billing_release,
    record_points_billing_settle,
)
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
_REPO_ROOT = Path(__file__).resolve().parents[4]


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
    cover_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


def _build_book_response(book: BookSource) -> BookResponse:
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
        cover_url=book.cover_url,
    )


def _save_parsed_cover_image(parsed: ParsedContent, book_id: int) -> Optional[str]:
    metadata = parsed.metadata or {}
    cover_bytes = metadata.get("cover_image_bytes")
    if not isinstance(cover_bytes, (bytes, bytearray)) or not cover_bytes:
        return None

    extension = str(metadata.get("cover_image_extension") or ".jpg").lower()
    if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        extension = ".jpg"

    cover_dir = _REPO_ROOT / "backend" / "data" / "book_covers"
    cover_dir.mkdir(parents=True, exist_ok=True)
    cover_path = cover_dir / f"book_{int(book_id)}{extension}"
    cover_path.write_bytes(bytes(cover_bytes))
    try:
        return cover_path.relative_to(_REPO_ROOT).as_posix()
    except Exception:
        return cover_path.as_posix()


def _parse_optional_publish_year(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        match = re.search(r"\b(19|20)\d{2}\b", str(value))
        if not match:
            return None
        year = int(match.group(0))
    return year if 1000 <= year <= 9999 else None


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

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


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
_task_status_lock = threading.Lock()


def _build_task_status_payload(
    book_id: int,
    status: str,
    progress: int,
    message: str,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """构建任务状态快照。"""
    return {
        "book_id": book_id,
        "status": status,
        "progress": max(0, min(100, int(progress))),
        "message": message,
        "error": error,
        "updated_at": datetime.now().isoformat()
    }


def _book_parser_billing_key(book_id: int, stage: str) -> str:
    return build_points_billing_key(POINTS_BILLING_MODULE_BOOK_PARSER, f"{stage}:{int(book_id or 0)}")


def _book_parser_username(user: object) -> str:
    return str(getattr(user, "username", None) or getattr(user, "email", None) or "system").strip() or "system"


def _freeze_book_parser_billing(
    *,
    db: Session,
    book: BookSource,
    current_user: object,
    stage: str,
    basis_yuan: float,
    summary: str,
) -> None:
    module_label = "拆书分析"
    billing_key = _book_parser_billing_key(book.id, stage)
    precheck = build_points_billing_precheck(
        db=db,
        user_id=int(book.user_id or 0),
        billing_key=billing_key,
        module_key=POINTS_BILLING_MODULE_BOOK_PARSER,
        module_label=module_label,
        basis_yuan=basis_yuan,
    )
    if not precheck.allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=build_points_billing_precheck_error_detail(
                precheck=precheck,
                default_message="拆书任务积分预检未通过",
            ),
        )

    record_points_billing_freeze(
        db=db,
        actor_user_id=int(getattr(current_user, "id", book.user_id) or book.user_id or 0),
        actor_username=_book_parser_username(current_user),
        target_user_id=int(book.user_id or 0),
        billing_key=billing_key,
        module_key=POINTS_BILLING_MODULE_BOOK_PARSER,
        amount_points=precheck.required_frozen_points,
        amount_yuan=precheck.estimated_yuan,
        title=f"拆书{('章节切分' if stage == 'parse' else 'AI分析')}：{book.title}",
        summary=summary,
        action_path=f"/book-parser/{int(book.id or 0)}",
        action_label="查看拆书任务",
        default_request_method="POST",
        default_request_path=f"/api/v1/book-parser/{int(book.id or 0)}/{stage}",
        operation_desc=f"拆书{stage}任务冻结积分 {precheck.required_frozen_points:.2f}",
        extra_payload={
            "book_id": int(book.id or 0),
            "stage": stage,
            "total_words": int(book.total_words or 0),
            "total_chapters": int(book.total_chapters or 0),
        },
    )


def _settle_book_parser_billing_safely(
    *,
    db: Session,
    book: BookSource,
    stage: str,
    basis_yuan: float,
    summary: str,
) -> None:
    try:
        estimate = build_points_usage_charge_estimate(
            db=db,
            module_key=POINTS_BILLING_MODULE_BOOK_PARSER,
            basis_yuan=basis_yuan,
            include_freeze_buffer=False,
        )
        record_points_billing_settle(
            db=db,
            actor_user_id=int(book.user_id or 0),
            actor_username=f"user-{int(book.user_id or 0)}",
            target_user_id=int(book.user_id or 0),
            billing_key=_book_parser_billing_key(book.id, stage),
            module_key=POINTS_BILLING_MODULE_BOOK_PARSER,
            amount_points=estimate.estimated_points,
            amount_yuan=estimate.basis_yuan,
            title=f"拆书{('章节切分' if stage == 'parse' else 'AI分析')}：{book.title}",
            summary=summary,
            action_path=f"/book-parser/{int(book.id or 0)}",
            action_label="查看拆书任务",
            default_request_path=f"/internal/book-parser/{int(book.id or 0)}/{stage}/billing-settle",
            extra_payload={
                "book_id": int(book.id or 0),
                "stage": stage,
                "total_words": int(book.total_words or 0),
                "total_chapters": int(book.total_chapters or 0),
            },
            require_active_freeze=True,
        )
    except Exception as billing_error:
        logger.warning("拆书任务积分结算失败: book_id=%s, stage=%s, error=%s", book.id, stage, billing_error)


def _release_book_parser_billing_safely(
    *,
    db: Session,
    book: BookSource | None,
    book_id: int,
    stage: str,
    reason: str,
) -> None:
    if book is None:
        return
    try:
        try:
            db.rollback()
        except Exception:
            pass
        record_points_billing_release(
            db=db,
            actor_user_id=int(book.user_id or 0),
            actor_username=f"user-{int(book.user_id or 0)}",
            target_user_id=int(book.user_id or 0),
            billing_key=_book_parser_billing_key(book_id, stage),
            module_key=POINTS_BILLING_MODULE_BOOK_PARSER,
            reason=reason,
            default_request_path=f"/internal/book-parser/{int(book_id or 0)}/{stage}/billing-release",
            extra_payload={
                "book_id": int(book_id or 0),
                "stage": stage,
            },
        )
    except Exception as billing_error:
        logger.warning("拆书任务积分释放失败: book_id=%s, stage=%s, error=%s", book_id, stage, billing_error)


def get_task_status(book_id: int) -> Optional[Dict[str, Any]]:
    """获取任务状态。"""
    with _task_status_lock:
        snapshot = _task_status.get(str(book_id))
        return dict(snapshot) if snapshot else None


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
    """更新任务状态。"""
    payload = _build_task_status_payload(book_id, status, progress, message, error)
    with _task_status_lock:
        _task_status[str(book_id)] = payload


def _reserve_task_status(
    book_id: int,
    status: str,
    progress: int,
    message: str,
    error: Optional[str] = None,
) -> tuple[Dict[str, Any], bool]:
    """为任务预留状态位，防止并发恢复时重复启动。"""
    with _task_status_lock:
        existing = _task_status.get(str(book_id))
        if existing:
            return dict(existing), False

        payload = _build_task_status_payload(book_id, status, progress, message, error)
        _task_status[str(book_id)] = payload
        return dict(payload), True


def _default_status_message(status: str) -> str:
    """当内存状态丢失时，基于数据库状态兜底提示文案。"""
    messages = {
        ParseStatus.PENDING.value: "等待开始处理...",
        ParseStatus.PARSING.value: "正在解析章节...",
        ParseStatus.CHAPTERS_DONE.value: "章节解析完成",
        ParseStatus.ANALYZING.value: "正在进行 AI 分析...",
        ParseStatus.COMPLETED.value: "分析完成",
        ParseStatus.FAILED.value: "处理失败",
    }
    return messages.get(status, "任务状态未知")


def _normalized_recovery_progress(book: BookSource) -> int:
    """修正热重载后可能残留的进度值。"""
    progress = max(0, min(100, int(book.parse_progress or 0)))
    if book.status in {ParseStatus.PARSING.value, ParseStatus.ANALYZING.value} and progress >= 100:
        return 0
    if book.status in {ParseStatus.PARSING.value, ParseStatus.ANALYZING.value}:
        return min(progress, 95)
    return progress


def _launch_parse_task(book_id: int):
    """启动章节解析线程。"""
    thread = threading.Thread(
        target=lambda: _do_parse_book(book_id),
        daemon=True,
        name=f"book-parser-parse-{book_id}"
    )
    thread.start()


def _launch_analyze_task(book_id: int):
    """启动 AI 分析线程。"""
    thread = threading.Thread(
        target=lambda: asyncio.run(_do_analyze_book(book_id)),
        daemon=True,
        name=f"book-parser-analyze-{book_id}"
    )
    thread.start()


def _recover_interrupted_task(book: BookSource) -> Optional[Dict[str, Any]]:
    """当开发服务器热重载导致内存任务丢失时，自动恢复任务。"""
    if book.status not in {ParseStatus.PARSING.value, ParseStatus.ANALYZING.value}:
        return None

    snapshot, should_start = _reserve_task_status(
        book.id,
        book.status,
        _normalized_recovery_progress(book),
        "检测到后台任务上下文丢失，正在自动恢复..."
    )
    if not should_start:
        return snapshot

    logger.warning(
        "检测到 book_parser 任务上下文丢失，准备自动恢复 | book_id=%s | status=%s",
        book.id,
        book.status,
    )
    try:
        if book.status == ParseStatus.PARSING.value:
            _launch_parse_task(book.id)
        else:
            _launch_analyze_task(book.id)
    except Exception as exc:
        logger.exception("自动恢复 book_parser 任务失败 | book_id=%s", book.id)
        update_task_status(book.id, ParseStatus.FAILED.value, 0, "自动恢复失败", str(exc))

    return get_task_status(book.id)


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
    
    return _build_book_response(book)


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
    
    支持 TXT、Markdown、EPUB、PDF 格式文件
    """
    # 验证文件名
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    
    filename = file.filename.lower()
    
    # 验证文件格式
    if not any(filename.endswith(ext) for ext in ['.txt', '.md', '.markdown', '.epub', '.pdf']):
        raise HTTPException(
            status_code=400, 
            detail="仅支持 TXT、Markdown、EPUB、PDF 格式文件"
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
    parsed_metadata = parsed.metadata or {}
    
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
        publisher=parsed_metadata.get("publisher"),
        publish_year=_parse_optional_publish_year(
            parsed_metadata.get("publish_year") or parsed_metadata.get("publish_date")
        ),
        genre=genre,
        description=metadata.get("description") or parsed_metadata.get("description"),
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
    book.cover_url = _save_parsed_cover_image(parsed, book.id)
    db.commit()
    
    logger.info(f"✅ 书籍文件上传成功: {book.title} (ID: {book.id}, 格式: {parsed.format.value})")
    
    return _build_book_response(book)


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
    
    return [_build_book_response(book) for book in books]


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
    
    return _build_book_response(book)


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
    
    active_task = get_task_status(book_id)
    if book.status == ParseStatus.PARSING.value and active_task:
        return {
            "message": "章节解析任务已在进行中",
            "book_id": book_id,
            "status": "parsing"
        }

    _freeze_book_parser_billing(
        db=db,
        book=book,
        current_user=current_user,
        stage="parse",
        basis_yuan=estimate_book_parse_basis_yuan(book.total_words),
        summary="拆书章节切分任务已启动，积分已按原文字数冻结。",
    )

    # 更新状态
    book.status = ParseStatus.PARSING.value
    book.parse_progress = 0
    book.error_message = None
    db.commit()
    
    update_task_status(book_id, "parsing", 0, "开始解析章节...")
    
    # 启动后台任务
    _launch_parse_task(book_id)
    
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
        
        book.status = ParseStatus.PARSING.value
        if (book.parse_progress or 0) >= 100:
            book.parse_progress = 0
        book.error_message = None
        db.commit()
        
        # 读取文本
        with open(book.file_path, "r", encoding="utf-8") as f:
            text = f.read()
        
        update_task_status(book_id, "parsing", 20, "正在分析章节结构...")
        book.parse_progress = 20
        db.commit()
        
        # 切分章节
        splitter = ChapterSplitter()
        result = splitter.split(text)
        
        update_task_status(book_id, "parsing", 60, f"识别到 {len(result.chapters)} 个章节，正在保存...")
        book.parse_progress = 60
        db.commit()
        
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
        book.error_message = None
        
        db.commit()
        
        _settle_book_parser_billing_safely(
            db=db,
            book=book,
            stage="parse",
            basis_yuan=estimate_book_parse_basis_yuan(book.total_words),
            summary=f"拆书章节切分已完成，共识别 {len(result.chapters)} 章。",
        )

        update_task_status(book_id, "chapters_done", 100, f"章节解析完成，共 {len(result.chapters)} 章")
        logger.info(f"✅ 书籍章节解析完成: {book.title} ({len(result.chapters)} 章)")
        
    except Exception as e:
        logger.error(f"❌ 书籍解析失败: {e}")
        update_task_status(book_id, "failed", 0, "解析失败", str(e))
        
        try:
            book = db.query(BookSource).filter(BookSource.id == book_id).first()
            if book:
                book.status = ParseStatus.FAILED.value
                book.parse_progress = 0
                book.error_message = str(e)
                db.commit()
                _release_book_parser_billing_safely(
                    db=db,
                    book=book,
                    book_id=book_id,
                    stage="parse",
                    reason="拆书章节切分失败，已释放冻结积分。",
                )
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
    
    active_task = get_task_status(book_id)
    if book.status == ParseStatus.ANALYZING.value and active_task:
        return {
            "message": "AI 分析任务已在进行中",
            "book_id": book_id,
            "status": "analyzing"
        }
    
    if book.status not in [
        ParseStatus.CHAPTERS_DONE.value,
        ParseStatus.COMPLETED.value,
        ParseStatus.ANALYZING.value,
    ]:
        raise HTTPException(status_code=400, detail="请先完成章节切分")
    
    _freeze_book_parser_billing(
        db=db,
        book=book,
        current_user=current_user,
        stage="analyze",
        basis_yuan=estimate_book_analyze_basis_yuan(book.total_words, book.total_chapters),
        summary="拆书 AI 分析任务已启动，积分已按原文字数与章节数冻结。",
    )

    # 更新状态
    book.status = ParseStatus.ANALYZING.value
    book.parse_progress = 0
    book.error_message = None
    db.commit()
    
    update_task_status(book_id, "analyzing", 0, "开始AI分析...")
    
    # 启动后台任务
    _launch_analyze_task(book_id)
    
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
        
        book.status = ParseStatus.ANALYZING.value
        if (book.parse_progress or 0) >= 100:
            book.parse_progress = 0
        book.error_message = None
        db.commit()
        
        # 获取章节
        chapters_db = db.query(BookChapter).filter(
            BookChapter.book_id == book_id
        ).order_by(BookChapter.chapter_number).all()
        
        if not chapters_db:
            update_task_status(book_id, "failed", 0, "没有章节数据", "请先执行章节切分")
            book.status = ParseStatus.FAILED.value
            book.parse_progress = 0
            book.error_message = "请先执行章节切分"
            db.commit()
            _release_book_parser_billing_safely(
                db=db,
                book=book,
                book_id=book_id,
                stage="analyze",
                reason="拆书 AI 分析缺少章节数据，已释放冻结积分。",
            )
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
            normalized_progress = max(0, min(100, int(progress)))
            if book.parse_progress != normalized_progress or book.status != ParseStatus.ANALYZING.value:
                book.status = ParseStatus.ANALYZING.value
                book.parse_progress = normalized_progress
                book.error_message = None
                db.commit()
        
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
        book.parse_progress = 100
        book.parsed_at = datetime.now()
        book.error_message = None
        db.commit()
        
        _settle_book_parser_billing_safely(
            db=db,
            book=book,
            stage="analyze",
            basis_yuan=estimate_book_analyze_basis_yuan(book.total_words, book.total_chapters),
            summary=f"拆书 AI 分析已完成，共提取 {len(results)} 类信息。",
        )

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
                book.parse_progress = 0
                book.error_message = str(e)
                db.commit()
                _release_book_parser_billing_safely(
                    db=db,
                    book=book,
                    book_id=book_id,
                    stage="analyze",
                    reason="拆书 AI 分析失败，已释放冻结积分。",
                )
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
    if task_status is None:
        task_status = _recover_interrupted_task(book)

    db_status = book.status
    status_value = task_status.get("status") if task_status else db_status
    if db_status in {
        ParseStatus.CHAPTERS_DONE.value,
        ParseStatus.COMPLETED.value,
        ParseStatus.FAILED.value,
    }:
        status_value = db_status

    progress_value = int(task_status.get("progress", book.parse_progress) if task_status else (book.parse_progress or 0))
    if status_value in {ParseStatus.CHAPTERS_DONE.value, ParseStatus.COMPLETED.value}:
        progress_value = 100

    message_value = task_status.get("message") if task_status else ""
    if not message_value:
        message_value = _default_status_message(status_value)
    
    return ParseStatusResponse(
        status=status_value,
        progress=progress_value,
        message=message_value,
        chapters_count=book.total_chapters,
        error=(task_status.get("error") if task_status else None) or book.error_message,
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
