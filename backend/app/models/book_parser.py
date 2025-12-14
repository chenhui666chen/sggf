"""
拆书工具数据模型

BookSource - 原书来源信息
BookChapter - 原书章节
BookAnalysis - 分析结果
"""
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, Text, ForeignKey, DateTime, Integer, Float, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.db.base import Base
import enum

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.project import Project


class SourceType(str, enum.Enum):
    """书籍来源类型"""
    TEXT = "text"           # 直接粘贴文本
    TXT_FILE = "txt"        # TXT文件上传
    EPUB_FILE = "epub"      # EPUB文件上传
    PDF_FILE = "pdf"        # PDF文件上传
    URL = "url"             # 网页URL


class ParseStatus(str, enum.Enum):
    """解析状态"""
    PENDING = "pending"         # 待解析
    PARSING = "parsing"         # 解析中
    CHAPTERS_DONE = "chapters_done"  # 章节切分完成
    ANALYZING = "analyzing"     # 分析中
    COMPLETED = "completed"     # 完成
    FAILED = "failed"           # 失败


class AnalysisType(str, enum.Enum):
    """分析类型"""
    CHARACTERS = "characters"       # 人物体系
    WORLDVIEW = "worldview"         # 世界观设定
    PLOT_STRUCTURE = "plot"         # 情节脉络
    WRITING_STYLE = "style"         # 写作风格
    KEY_CONCEPTS = "concepts"       # 关键概念/术语
    CHAPTER_SUMMARY = "summary"     # 章节摘要
    THEMES = "themes"               # 主题思想


class BookSource(Base):
    """
    原书来源表
    
    存储导入的书籍基本信息，作为拆书分析的源数据
    """
    __tablename__ = "book_sources"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    
    # 书籍基本信息
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="书名")
    author: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, comment="作者")
    isbn: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="ISBN")
    publisher: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, comment="出版社")
    publish_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="出版年份")
    genre: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="类型/题材")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="书籍简介")
    cover_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="封面URL")
    
    # 来源信息
    source_type: Mapped[str] = mapped_column(
        String(20), 
        default=SourceType.TEXT.value, 
        comment="来源类型: text/txt/epub/pdf/url"
    )
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="文件存储路径")
    original_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True, comment="原始URL")
    
    # 统计信息
    total_words: Mapped[int] = mapped_column(Integer, default=0, comment="总字数")
    total_chapters: Mapped[int] = mapped_column(Integer, default=0, comment="总章节数")
    total_volumes: Mapped[int] = mapped_column(Integer, default=0, comment="总卷数")
    
    # 解析状态
    status: Mapped[str] = mapped_column(
        String(20), 
        default=ParseStatus.PENDING.value,
        comment="解析状态"
    )
    parse_progress: Mapped[int] = mapped_column(Integer, default=0, comment="解析进度0-100")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="错误信息")
    
    # 关联的项目（如果已导入为工作流项目）
    imported_project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        comment="导入后创建的项目ID"
    )
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now(), onupdate=func.now()
    )
    parsed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="解析完成时间"
    )
    
    # 关系定义
    chapters: Mapped[List["BookChapter"]] = relationship(
        "BookChapter",
        back_populates="book",
        lazy="select",
        cascade="all, delete-orphan",
        order_by="BookChapter.chapter_number"
    )
    analyses: Mapped[List["BookAnalysis"]] = relationship(
        "BookAnalysis",
        back_populates="book",
        lazy="select",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self):
        return f"<BookSource {self.title} by {self.author}>"


class BookChapter(Base):
    """
    原书章节表
    
    存储切分后的章节内容
    """
    __tablename__ = "book_chapters"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    book_id: Mapped[int] = mapped_column(
        ForeignKey("book_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # 章节信息
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False, comment="章节序号")
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="章节标题")
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="章节内容")
    word_count: Mapped[int] = mapped_column(Integer, default=0, comment="字数")
    
    # 卷/部信息（可选）
    volume_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="卷号")
    volume_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="卷标题")
    part_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="部号")
    part_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="部标题")
    
    # 章节类型（正文/序章/番外等）
    chapter_type: Mapped[str] = mapped_column(
        String(20), 
        default="normal",
        comment="章节类型: normal/prologue/epilogue/extra/interlude"
    )
    
    # 原文位置（用于定位和验证）
    start_position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="在原文中的起始位置")
    end_position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="在原文中的结束位置")
    
    # 分析结果缓存
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="章节摘要")
    key_events: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="关键事件(JSON)")
    appearing_characters: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="出场人物(JSON)")
    
    # 🆕 完整细纲数据（包含场景目标、冲突弧、情绪曲线、爽点、结尾钩子等）
    outline_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="细纲数据(JSON)")
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    # 关系定义
    book: Mapped["BookSource"] = relationship("BookSource", back_populates="chapters")
    
    def __repr__(self):
        return f"<BookChapter {self.chapter_number}: {self.title}>"


class BookAnalysis(Base):
    """
    书籍分析结果表
    
    存储AI提取的各类分析结果（人物、世界观、情节等）
    每种分析类型单独存储，便于增量更新和查询
    """
    __tablename__ = "book_analyses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    book_id: Mapped[int] = mapped_column(
        ForeignKey("book_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # 分析类型
    analysis_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="分析类型: characters/worldview/plot/style/concepts/summary/themes"
    )
    
    # 分析内容（JSON格式存储）
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="分析结果(JSON)")
    
    # 分析质量评估
    confidence: Mapped[float] = mapped_column(Float, default=0.8, comment="置信度0-1")
    completeness: Mapped[float] = mapped_column(Float, default=0.8, comment="完整度0-1")
    
    # 分析覆盖范围
    chapter_range_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="分析起始章节")
    chapter_range_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="分析结束章节")
    
    # 元数据
    extra_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="额外元数据(JSON)")
    model_used: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="使用的AI模型")
    
    # 版本控制
    version: Mapped[int] = mapped_column(Integer, default=1, comment="版本号")
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now(), onupdate=func.now()
    )
    
    # 关系定义
    book: Mapped["BookSource"] = relationship("BookSource", back_populates="analyses")
    
    def __repr__(self):
        return f"<BookAnalysis {self.analysis_type} for book {self.book_id}>"


# ==================== 分析结果内容结构说明 ====================
"""
BookAnalysis.content 字段存储 JSON 格式数据，各类型结构如下：

1. characters (人物体系):
{
    "main_characters": [
        {
            "name": "张三",
            "aliases": ["阿三", "三哥"],
            "role": "protagonist",
            "description": "...",
            "personality": ["勇敢", "正义"],
            "relationships": [{"target": "李四", "relation": "师徒"}],
            "first_appearance_chapter": 1,
            "importance_score": 0.9
        }
    ],
    "supporting_characters": [...],
    "minor_characters": [...]
}

2. worldview (世界观设定):
{
    "world_type": "玄幻/修仙",
    "time_period": "...",
    "locations": [
        {"name": "青云门", "type": "门派", "description": "..."}
    ],
    "power_systems": [
        {"name": "修仙体系", "levels": ["练气", "筑基", "金丹"]}
    ],
    "factions": [...],
    "rules": [...]
}

3. plot (情节脉络):
{
    "main_plot": "...",
    "plot_arcs": [
        {"name": "第一卷", "summary": "...", "chapters": [1, 50]}
    ],
    "key_events": [
        {"chapter": 1, "event": "...", "impact": "..."}
    ],
    "turning_points": [...],
    "conflicts": [...]
}

4. style (写作风格):
{
    "narrative_perspective": "第三人称全知",
    "tone": "轻松幽默",
    "sentence_style": {"avg_length": 20, "complexity": "中等"},
    "vocabulary_features": ["古风用词", "..."],
    "dialogue_ratio": 0.3,
    "description_style": "细腻"
}

5. concepts (关键概念):
{
    "terms": [
        {"term": "金丹", "definition": "...", "first_mention_chapter": 5}
    ],
    "special_items": [...],
    "techniques": [...]
}

6. themes (主题思想):
{
    "main_themes": ["成长", "正义"],
    "sub_themes": [...],
    "moral_messages": [...]
}
"""
