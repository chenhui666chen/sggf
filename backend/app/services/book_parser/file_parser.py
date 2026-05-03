"""
多格式文件解析器

支持格式：
- TXT: 纯文本
- EPUB: 电子书标准格式
- PDF: 便携式文档格式
"""

import io
import logging
import posixpath
import re
import tempfile
import unicodedata
import urllib.parse
import zipfile
from collections import Counter
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


class FileFormat(str, Enum):
    """文件格式枚举"""
    TXT = "txt"
    EPUB = "epub"
    PDF = "pdf"
    UNKNOWN = "unknown"


@dataclass
class ParsedContent:
    """解析后的内容"""
    text: str
    title: Optional[str] = None
    author: Optional[str] = None
    metadata: Dict[str, Any] = None
    format: FileFormat = FileFormat.UNKNOWN
    success: bool = True
    error: Optional[str] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass(frozen=True)
class _EpubNavEntry:
    """EPUB 导航切片入口。"""
    title: str
    doc_href: str
    position: int
    doc_order: int


class FileParser:
    """
    多格式文件解析器
    
    支持 TXT/EPUB/PDF 格式的文本提取
    """

    _CHAPTER_HEADING_BOUNDARY_CHARS = ":：.。,-_—–·、;；!！?？)）]】"
    _TXT_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    _TXT_HEADING_VOICE_HINT_RE = re.compile(r"^(?P<title>.+?)\s+%\s+(?P<speaker>\S(?:.*\S)?)$")
    _TXT_FRONT_MATTER_FIELD_RE = re.compile(r"^([A-Za-z_\-\s\u4e00-\u9fff]+)\s*:\s*(.+?)\s*$")
    _TXT_SCENE_GOALS_HEADING_RE = re.compile(
        r"^(?:#{1,6}\s*)?(?:scene goals?|场景目标|场景目的)\s*$",
        re.IGNORECASE,
    )
    _TXT_SCENE_BREAK_LINE_RE = re.compile(r"^(?:\*\s*){3,}$|^-{3,}$|^_{3,}$")
    _TXT_MANUSCRIPT_METADATA_LINE_RE = re.compile(
        r"^\*\*\s*(?:"
        r"pov|timeline|location|day|word count|tempo|level|"
        r"视角|时间线|地点|日期|字数|节奏"
        r")\s*:?\s*\*\*\s*:?.*$",
        re.IGNORECASE,
    )
    _TXT_HEADER_METADATA_PATTERNS = (
        ("title", re.compile(r"^(?:title|书名|标题|名称)\s*[:：]\s*(.+?)\s*$", re.IGNORECASE)),
        ("author", re.compile(r"^(?:author|作者|著者|作\s*者)\s*[:：]\s*(.+?)\s*$", re.IGNORECASE)),
        ("description", re.compile(r"^(?:description|summary|简介|内容简介|内容介绍)\s*[:：]\s*(.+?)\s*$", re.IGNORECASE)),
    )
    _EPUB_FOOTNOTE_ATTR_RE = re.compile(
        r"(^|[\s_\-])(footnotes?|endnotes?|rearnotes?|noteref|fnref)(?=$|[\s_\-]|\d)",
        re.IGNORECASE,
    )
    _EPUB_FOOTNOTE_CONTAINER_TAGS = {"aside", "section", "ol", "ul", "li", "div"}
    _EPUB_NON_NARRATIVE_TITLE_EXACT = {
        "about the author",
        "about the authors",
        "about the publisher",
        "acknowledgments",
        "acknowledgements",
        "also by",
        "bibliography",
        "books by",
        "colophon",
        "contents",
        "copyright",
        "copyright page",
        "credits",
        "endnotes",
        "footnotes",
        "glossary",
        "index",
        "list of figures",
        "list of illustrations",
        "notes",
        "other books by",
        "permissions",
        "praise",
        "praise for",
        "references",
        "table of contents",
        "title page",
        "版权",
        "版权页",
        "版权信息",
        "版權",
        "版權頁",
        "版權資訊",
        "目录",
        "目錄",
        "索引",
        "参考文献",
        "參考文獻",
        "注释",
        "註釋",
        "脚注",
        "註腳",
        "作者简介",
        "作者簡介",
        "致谢",
        "致謝",
        "鸣谢",
        "鳴謝",
        "出版说明",
        "出版說明",
        "封面",
        "扉页",
        "扉頁",
    }
    _EPUB_NON_NARRATIVE_TITLE_PREFIX = (
        "about the ",
        "also by",
        "books by",
        "copyright",
        "list of ",
        "other books",
        "praise for",
        "references",
        "版权",
        "版權",
        "目录",
        "目錄",
        "参考",
        "參考",
    )
    _EPUB_CONTENT_TITLE_RE = re.compile(
        r"^(?:"
        r"第[\u96f6一二三四五六七八九十百千万两\d]+[章节回卷部册篇]"
        r"|chapter\s+[\divxlcdm]+"
        r"|ch\.?\s*[\divxlcdm]+"
        r"|part\s+[\divxlcdm]+"
        r"|book\s+[\divxlcdm]+"
        r"|prologue|epilogue|foreword|preface|introduction|afterword"
        r"|序章|楔子|引子|前言|后记|後記|尾声|尾聲|番外"
        r")\b",
        re.IGNORECASE,
    )
    _EPUB_COPYRIGHT_CONTENT_RE = re.compile(
        r"(copyright|\u00a9|all rights reserved|isbn[-:\s]*[\d\-x]{10,}|"
        r"published by|no part of this (?:book|publication)|library of congress|"
        r"版权所有|版權所有|著作权|著作權|书号|書號|出版社|出版发行|出版發行)",
        re.IGNORECASE,
    )
    _EPUB_TOC_LINE_RE = re.compile(
        r"^\s*(?:第[\u96f6一二三四五六七八九十百千万两\d]+[章节回]|chapter\s+[\divxlcdm]+|"
        r"part\s+[\divxlcdm]+|\d+[\.\u3001])?.{2,80}(?:\.{2,}|…{2,}|\s{2,})\d{1,4}\s*$",
        re.IGNORECASE,
    )
    _EPUB_INDEX_LINE_RE = re.compile(r"^\s*[A-Za-z][A-Za-z\s'\-]{1,50},\s*\d[\d,\s\-]*\s*$")
    _EPUB_BIBLIOGRAPHY_RE = re.compile(
        r"(^\s*\[\d+\]\s+|\bet al\.|\bpp?\.\s*\d+|\bvol\.\s*\d+|\(\d{4}\))",
        re.IGNORECASE | re.MULTILINE,
    )
    _EPUB_INLINE_NOTES_TITLE_EXACT = {
        "notes",
        "notes:",
        "endnotes",
        "endnotes:",
        "footnotes",
        "footnotes:",
        "注释",
        "注释:",
        "注释：",
        "註釋",
        "註釋:",
        "註釋：",
        "尾注",
        "尾注:",
        "尾注：",
        "脚注",
        "脚注:",
        "脚注：",
        "註腳",
        "註腳:",
        "註腳：",
    }
    _EPUB_INLINE_NOTE_LINE_RE = re.compile(
        r"^\s*(?:\[\d{1,4}\]|\d{1,4}[\.)、．]|[*†‡§]+)\s+.+"
    )
    _EPUB_READING_BLOCK_TAGS = {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "blockquote",
        "figcaption",
        "li",
        "dt",
        "dd",
    }
    _EPUB_SEMANTIC_BLOCK_CLASSES = {
        "caption",
        "center",
        "chapno",
        "epi",
        "epigraph",
        "fext",
        "h",
        "poem",
        "quote",
        "right",
        "tr-caption",
        "ts",
        "wp-caption-text",
    }
    _EPUB_NON_READING_HTML_BASENAME_HINTS = {
        "nav",
        "toc",
        "contents",
        "cover",
        "titlepage",
    }
    _EPUB_LINE_BREAK_PAUSE_MARKER = "[pause:0.5s]"
    _EPUB_SCENE_BREAK_PAUSE_MARKER = "[pause:1.5s]"
    _PDF_BOUNDARY_LINE_SCAN_COUNT = 2
    _PDF_PAGE_NUMBER_RE = re.compile(
        r"^(?:page\s*)?\d{1,5}(?:\s*/\s*\d{1,5})?$|^第\s*\d{1,5}\s*页$",
        re.IGNORECASE,
    )
    
    def __init__(self):
        # 检查依赖库可用性
        self.epub_available = self._check_epub_support()
        self.pdf_available = self._check_pdf_support()
        
        logger.info(f"✅ 文件解析器初始化完成 (EPUB={self.epub_available}, PDF={self.pdf_available})")
    
    def _check_epub_support(self) -> bool:
        """检查 EPUB 支持"""
        try:
            import ebooklib
            return True
        except ImportError:
            logger.warning("⚠️ ebooklib 未安装，EPUB 解析不可用")
            logger.warning("   安装: pip install ebooklib")
            return False
    
    def _check_pdf_support(self) -> bool:
        """检查 PDF 支持"""
        try:
            import PyPDF2
            return True
        except ImportError:
            logger.warning("⚠️ PyPDF2 未安装，PDF 解析不可用")
            logger.warning("   安装: pip install PyPDF2")
            return False
    
    def detect_format(self, filename: str, content_bytes: bytes = None) -> FileFormat:
        """
        检测文件格式
        
        Args:
            filename: 文件名
            content_bytes: 文件内容（可选，用于魔数检测）
        
        Returns:
            文件格式枚举
        """
        # 1. 根据扩展名判断
        ext = Path(filename).suffix.lower().lstrip('.')
        if ext in {'txt', 'md', 'markdown'}:
            return FileFormat.TXT
        elif ext == 'epub':
            return FileFormat.EPUB
        elif ext == 'pdf':
            return FileFormat.PDF
        
        # 2. 魔数检测（如果提供了内容）
        if content_bytes:
            # EPUB 实际是 ZIP 格式
            if content_bytes[:4] == b'PK\x03\x04':
                return FileFormat.EPUB
            # PDF 魔数
            if content_bytes[:4] == b'%PDF':
                return FileFormat.PDF
        
        return FileFormat.UNKNOWN
    
    def parse(
        self,
        file_content: bytes,
        filename: str,
        format_hint: Optional[FileFormat] = None
    ) -> ParsedContent:
        """
        解析文件内容
        
        Args:
            file_content: 文件字节流
            filename: 文件名
            format_hint: 格式提示（可选）
        
        Returns:
            解析结果
        """
        # 检测格式
        file_format = format_hint or self.detect_format(filename, file_content)
        
        logger.info(f"📖 开始解析文件: {filename} (格式: {file_format.value})")
        
        # 根据格式调用对应解析器
        try:
            if file_format == FileFormat.TXT:
                return self._parse_txt(file_content, filename)
            elif file_format == FileFormat.EPUB:
                return self._parse_epub(file_content, filename)
            elif file_format == FileFormat.PDF:
                return self._parse_pdf(file_content, filename)
            else:
                return ParsedContent(
                    text="",
                    format=FileFormat.UNKNOWN,
                    success=False,
                    error="不支持的文件格式"
                )
        except Exception as e:
            logger.error(f"❌ 文件解析失败: {e}")
            import traceback
            traceback.print_exc()
            return ParsedContent(
                text="",
                format=file_format,
                success=False,
                error=str(e)
            )
    
    def _parse_txt(self, content: bytes, filename: str) -> ParsedContent:
        """解析 TXT 文件"""
        # 尝试多种编码
        text = None
        detected_encoding = None
        
        for encoding in ['utf-8', 'gbk', 'gb2312', 'utf-16', 'big5', 'latin-1']:
            try:
                text = content.decode(encoding)
                detected_encoding = encoding
                break
            except UnicodeDecodeError:
                continue
        
        if text is None:
            return ParsedContent(
                text="",
                format=FileFormat.TXT,
                success=False,
                error="无法识别文件编码"
            )
        
        text, front_matter_metadata = self._extract_txt_front_matter_metadata(text)
        text, header_metadata = self._extract_txt_header_metadata(text)
        text = self._strip_txt_manuscript_metadata(text)
        text, chapter_voice_hints = self._format_txt_markdown_chapter_markers(text)
        metadata: Dict[str, Any] = {"encoding": detected_encoding}
        metadata.update(front_matter_metadata)
        metadata.update(header_metadata)
        if chapter_voice_hints:
            metadata["chapter_voice_hints"] = chapter_voice_hints

        logger.info(f"✅ TXT 解析成功 ({detected_encoding}): {len(text)} 字符")
        
        return ParsedContent(
            text=text,
            title=header_metadata.get("title") or front_matter_metadata.get("title"),
            author=header_metadata.get("author") or front_matter_metadata.get("author"),
            format=FileFormat.TXT,
            metadata=metadata,
            success=True
        )

    @staticmethod
    def _extract_txt_front_matter_metadata(text: str) -> Tuple[str, Dict[str, str]]:
        """提取 Markdown YAML front matter 中的基础元数据，并从正文中移除。"""
        lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if not lines or lines[0].lstrip("\ufeff").strip() != "---":
            return text, {}

        closing_index = None
        for index, line in enumerate(lines[1:80], start=1):
            if line.strip() == "---":
                closing_index = index
                break

        if closing_index is None:
            return text, {}

        metadata: Dict[str, str] = {}
        key_map = {
            "title": "title",
            "书名": "title",
            "标题": "title",
            "author": "author",
            "作者": "author",
            "description": "description",
            "summary": "description",
            "简介": "description",
            "内容简介": "description",
        }
        for line in lines[1:closing_index]:
            match = FileParser._TXT_FRONT_MATTER_FIELD_RE.match(line.strip())
            if not match:
                continue
            raw_key = re.sub(r"\s+", " ", match.group(1).strip().lower())
            key = key_map.get(raw_key)
            if not key or key in metadata:
                continue
            value = FileParser._normalize_epub_text(match.group(2).strip().strip("'\""))
            if value:
                metadata[key] = value

        body = "\n".join(lines[closing_index + 1:]).lstrip()
        return body, metadata

    @staticmethod
    def _extract_txt_header_metadata(text: str) -> Tuple[str, Dict[str, str]]:
        """提取 TXT 文件头部的显式元数据，并从正文中移除这些行。"""
        lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        metadata: Dict[str, str] = {}
        removable_indexes = set()

        for index, line in enumerate(lines[:20]):
            stripped = line.strip()
            if not stripped:
                continue

            matched = False
            for key, pattern in FileParser._TXT_HEADER_METADATA_PATTERNS:
                match = pattern.match(stripped)
                if not match:
                    continue
                value = FileParser._normalize_epub_text(match.group(1))
                if value and key not in metadata:
                    metadata[key] = value
                removable_indexes.add(index)
                matched = True
                break

            if matched:
                continue
            break

        if not removable_indexes:
            return text, metadata

        body = "\n".join(
            line
            for index, line in enumerate(lines)
            if index not in removable_indexes
        ).lstrip()
        return body, metadata

    @staticmethod
    def _strip_txt_manuscript_metadata(text: str) -> str:
        """移除 Markdown 手稿中不应进入朗读正文的编辑元信息。"""
        processed = re.sub(r"<!--.*?-->", "", str(text or ""), flags=re.DOTALL)
        lines = processed.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        clean_lines: List[str] = []
        in_scene_goals = False

        for line in lines:
            stripped = line.strip()
            if in_scene_goals:
                if re.match(r"^[-*]\s+\[[ xX]\]\s+", stripped):
                    continue
                if not stripped:
                    in_scene_goals = False
                    continue
                in_scene_goals = False

            if FileParser._TXT_SCENE_GOALS_HEADING_RE.match(stripped):
                in_scene_goals = True
                continue
            if FileParser._TXT_MANUSCRIPT_METADATA_LINE_RE.match(stripped):
                continue
            if FileParser._TXT_SCENE_BREAK_LINE_RE.match(stripped):
                clean_lines.append(FileParser._EPUB_SCENE_BREAK_PAUSE_MARKER)
                continue

            clean_lines.append(line)

        return "\n".join(clean_lines).strip()


    @staticmethod
    def _format_txt_markdown_chapter_markers(text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """将 TXT/Markdown 中稳定的标题层级转换为显式章节标记。"""
        lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        heading_levels: Dict[int, int] = {}
        for line in lines:
            match = FileParser._TXT_MARKDOWN_HEADING_RE.match(line.strip())
            if not match:
                continue
            level = len(match.group(1))
            title = match.group(2).strip()
            if title:
                heading_levels[level] = heading_levels.get(level, 0) + 1

        selected_level = next(
            (level for level in sorted(heading_levels) if heading_levels[level] >= 2),
            None,
        )
        if selected_level is None:
            return text, []

        chapter_index = 0
        voice_hints: List[Dict[str, Any]] = []
        formatted_lines: List[str] = []
        for line in lines:
            stripped = line.strip()
            match = FileParser._TXT_MARKDOWN_HEADING_RE.match(stripped)
            if not match or len(match.group(1)) != selected_level:
                formatted_lines.append(line)
                continue

            raw_title = match.group(2).strip()
            title, voice_hint = FileParser._split_txt_heading_voice_hint(raw_title)
            title = FileParser._normalize_epub_text(title).replace(">>", "> >")
            if not title:
                formatted_lines.append(line)
                continue

            chapter_index += 1
            formatted_lines.append(f"<<CHAPTER_MARKER:{title}>>")
            if voice_hint:
                voice_hints.append({
                    "chapter_index": chapter_index,
                    "title": title,
                    "voice_hint": voice_hint,
                })

        return "\n".join(formatted_lines).strip(), voice_hints

    @staticmethod
    def _split_txt_heading_voice_hint(title: str) -> Tuple[str, Optional[str]]:
        match = FileParser._TXT_HEADING_VOICE_HINT_RE.match(str(title or "").strip())
        if not match:
            return title, None
        clean_title = match.group("title").strip()
        speaker = match.group("speaker").strip()
        if (
            not clean_title
            or not speaker
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{1,80}", speaker)
        ):
            return title, None
        return clean_title, speaker
    
    def _parse_epub(self, content: bytes, filename: str) -> ParsedContent:
        """解析 EPUB 文件"""
        if not self.epub_available:
            return ParsedContent(
                text="",
                format=FileFormat.EPUB,
                success=False,
                error="EPUB 解析不可用，请安装 ebooklib"
            )
        
        try:
            from ebooklib import ITEM_DOCUMENT, epub
            from bs4 import BeautifulSoup
        except ImportError as e:
            return ParsedContent(
                text="",
                format=FileFormat.EPUB,
                success=False,
                error=f"缺少依赖: {str(e)}"
            )
        
        try:
            # 从字节流创建 EPUB 对象
            book = epub.read_epub(io.BytesIO(content))
            
            # 提取元数据
            title = book.get_metadata('DC', 'title')
            title = title[0][0] if title else None
            
            author = book.get_metadata('DC', 'creator')
            author = author[0][0] if author else None
            
            language = book.get_metadata('DC', 'language')
            language = language[0][0] if language else None
            description = self._first_epub_metadata(book, 'DC', 'description')
            publisher = self._first_epub_metadata(book, 'DC', 'publisher')
            publish_date = self._first_epub_metadata(book, 'DC', 'date')
            publish_year = self._extract_year(publish_date)
            cover_payload = self._extract_epub_cover_payload(content)
            
            # 优先按 EPUB nav/NCX 的章节锚点切片；失败时保留 spine 顺序回退。
            chapter_parts = self._extract_epub_navigation_text_parts(
                book,
                ITEM_DOCUMENT,
                BeautifulSoup,
            )
            nav_chapter_count = len(chapter_parts)
            toc_titles_by_href = self._epub_toc_titles_by_href(book)
            toc_title_fallback_count = 0
            item_title_fallback_count = 0
            skipped_non_narrative_parts: List[Dict[str, Any]] = []
            if chapter_parts:
                chapter_parts, skipped_non_narrative_parts = self._filter_epub_non_narrative_parts(
                    chapter_parts
                )
                text_parts = [
                    self._format_epub_chapter_marker(title, text)
                    for title, text in chapter_parts
                    if text.strip()
                ]
            else:
                fallback_parts: List[Tuple[str, str]] = []
                for item in self._ordered_epub_documents(book, ITEM_DOCUMENT):
                    html = item.get_content().decode('utf-8', errors='ignore')
                    text = self._extract_epub_document_text(html, BeautifulSoup)
                    if text.strip():
                        title_hint = self._extract_epub_document_title(html, BeautifulSoup)
                        if not title_hint:
                            title_hint = self._epub_toc_title_for_item(item, toc_titles_by_href)
                            if title_hint:
                                toc_title_fallback_count += 1
                        if not title_hint:
                            title_hint = self._infer_epub_title_from_item(item)
                            if title_hint:
                                item_title_fallback_count += 1
                        fallback_parts.append((title_hint or "", text))
                fallback_parts, skipped_non_narrative_parts = self._filter_epub_non_narrative_parts(
                    fallback_parts
                )
                text_parts = [
                    self._format_epub_chapter_marker(title_hint, text)
                    if title_hint
                    else text.strip()
                    for title_hint, text in fallback_parts
                    if text.strip()
                ]
            
            full_text = '\n\n'.join(text_parts)
            
            logger.info(f"✅ EPUB 解析成功: {len(full_text)} 字符")
            logger.info(f"   书名: {title}, 作者: {author}")
            
            return ParsedContent(
                text=full_text,
                title=title,
                author=author,
                format=FileFormat.EPUB,
                metadata={
                    "language": language,
                    "description": description,
                    "publisher": publisher,
                    "publish_date": publish_date,
                    "publish_year": publish_year,
                    "nav_chapter_count": nav_chapter_count,
                    "toc_title_fallback_count": toc_title_fallback_count,
                    "item_title_fallback_count": item_title_fallback_count,
                    "skipped_non_narrative_parts": skipped_non_narrative_parts,
                    "items_count": len(list(book.get_items())),
                    **(cover_payload or {}),
                },
                success=True
            )
            
        except Exception as e:
            logger.error(f"❌ EPUB 解析失败: {e}")
            return ParsedContent(
                text="",
                format=FileFormat.EPUB,
                success=False,
                error=f"EPUB 解析失败: {str(e)}"
            )

    @staticmethod
    def _ordered_epub_documents(book: Any, item_document_type: Any) -> list[Any]:
        items = [
            item
            for item in book.get_items()
            if FileParser._epub_item_is_reading_document(item, item_document_type)
        ]
        by_id = {item.get_id(): item for item in items}
        ordered = []
        seen = set()
        excluded = set()

        for spine_entry in getattr(book, "spine", []) or []:
            item_id = spine_entry[0] if isinstance(spine_entry, (list, tuple)) and spine_entry else spine_entry
            linear = spine_entry[1] if isinstance(spine_entry, (list, tuple)) and len(spine_entry) > 1 else "yes"
            if linear == "no":
                excluded.add(item_id)
                continue
            if item_id in seen:
                continue
            item = by_id.get(item_id)
            if not item:
                continue
            ordered.append(item)
            seen.add(item_id)

        for item in items:
            item_id = item.get_id()
            if item_id in seen or item_id in excluded:
                continue
            ordered.append(item)
            seen.add(item_id)

        return ordered

    @staticmethod
    def _epub_item_is_reading_document(item: Any, item_document_type: Any) -> bool:
        if not hasattr(item, "get_type"):
            return False
        if FileParser._epub_item_is_non_reading_html(item):
            return False
        if item.get_type() == item_document_type:
            return True
        return FileParser._epub_item_is_html(item)

    @staticmethod
    def _epub_item_is_html(item: Any) -> bool:
        name = FileParser._epub_item_name(item).lower()
        media_type = str(getattr(item, "media_type", "") or "").lower()
        return (
            name.endswith((".xhtml", ".html", ".htm"))
            or media_type in {"application/xhtml+xml", "text/html"}
        )

    @staticmethod
    def _epub_item_is_non_reading_html(item: Any) -> bool:
        name = FileParser._epub_item_name(item).lower()
        basename = posixpath.basename(name)
        stem = basename.rsplit(".", 1)[0] if "." in basename else basename
        properties = {
            str(prop).lower()
            for prop in (getattr(item, "properties", []) or [])
        }
        return (
            "nav" in properties
            or stem in FileParser._EPUB_NON_READING_HTML_BASENAME_HINTS
            or stem.endswith("-nav")
            or stem.endswith("_nav")
            or stem.endswith("-toc")
            or stem.endswith("_toc")
        )

    @staticmethod
    def _epub_item_name(item: Any) -> str:
        if not hasattr(item, "get_name"):
            return ""
        try:
            return str(item.get_name() or "")
        except Exception:
            return ""

    @staticmethod
    def _epub_toc_titles_by_href(book: Any) -> Dict[str, str]:
        if not hasattr(book, "get_toc"):
            return {}
        try:
            toc = book.get_toc() or []
        except Exception:
            return {}

        titles: Dict[str, str] = {}
        for entry in FileParser._walk_epub_toc_items(toc):
            href = str(getattr(entry, "href", "") or "").strip()
            title = FileParser._normalize_epub_text(getattr(entry, "title", "") or "")
            if not href or not FileParser._looks_like_epub_title(title):
                continue
            normalized_href = FileParser._normalize_epub_href(href)
            if not normalized_href:
                continue
            titles.setdefault(normalized_href, title)
            basename = posixpath.basename(normalized_href)
            if basename:
                titles.setdefault(basename, title)
        return titles

    @staticmethod
    def _walk_epub_toc_items(toc: Any) -> List[Any]:
        items: List[Any] = []
        for entry in toc or []:
            if isinstance(entry, tuple):
                for part in entry:
                    if isinstance(part, (list, tuple)):
                        items.extend(FileParser._walk_epub_toc_items(part))
                    else:
                        items.append(part)
            elif isinstance(entry, list):
                items.extend(FileParser._walk_epub_toc_items(entry))
            else:
                items.append(entry)
        return items

    @staticmethod
    def _epub_toc_title_for_item(item: Any, toc_titles_by_href: Dict[str, str]) -> Optional[str]:
        if not toc_titles_by_href:
            return None
        for candidate in FileParser._epub_item_href_candidates(item):
            title = toc_titles_by_href.get(candidate)
            if title:
                return title
        return None

    @staticmethod
    def _epub_item_href_candidates(item: Any) -> List[str]:
        values = [
            FileParser._epub_item_name(item),
            str(item.get_id() or "") if hasattr(item, "get_id") else "",
        ]
        candidates: List[str] = []
        seen = set()
        for value in values:
            normalized = FileParser._normalize_epub_href(value)
            if not normalized:
                continue
            for candidate in (normalized, posixpath.basename(normalized)):
                if candidate and candidate not in seen:
                    candidates.append(candidate)
                    seen.add(candidate)
        return candidates

    @staticmethod
    def _normalize_epub_href(value: str) -> str:
        href = str(value or "").strip().replace("\\", "/")
        if not href:
            return ""
        path = urllib.parse.urlsplit(href).path
        path = urllib.parse.unquote(path).replace("\\", "/")
        normalized = posixpath.normpath(path)
        if normalized in {".", "/"}:
            return ""
        return normalized.lstrip("/")

    @staticmethod
    def _infer_epub_title_from_item(item: Any) -> Optional[str]:
        for raw_value in (FileParser._epub_item_name(item), str(item.get_id() or "") if hasattr(item, "get_id") else ""):
            title = FileParser._infer_epub_title_from_identifier(raw_value)
            if title:
                return title
        return None

    @staticmethod
    def _infer_epub_title_from_identifier(value: str) -> Optional[str]:
        normalized = FileParser._normalize_epub_href(value)
        if not normalized:
            return None
        stem = posixpath.basename(normalized)
        stem = stem.rsplit(".", 1)[0] if "." in stem else stem
        if not stem:
            return None
        lower = stem.lower()
        if lower in FileParser._EPUB_NON_READING_HTML_BASENAME_HINTS:
            return None
        readable = re.sub(r"[_\-.]+", " ", stem).strip()
        readable = re.sub(r"\s+", " ", readable)
        if not readable or len(readable) > 80:
            return None
        if re.search(r"第[\u96f6一二三四五六七八九十百千万两\d]+[章节回卷部册篇]", readable):
            return FileParser._normalize_epub_text(readable)
        if not re.search(
            r"(?i)\b(?:chapter|chap|ch|part|book|volume|vol|section|sect)\s*(?:\d+|[ivxlcdm]+)?\b|^c\d+\b",
            readable,
        ):
            return None
        return FileParser._normalize_epub_text(readable.title())

    @staticmethod
    def _filter_epub_non_narrative_parts(
        parts: List[Tuple[str, str]],
    ) -> Tuple[List[Tuple[str, str]], List[Dict[str, Any]]]:
        """只裁掉 EPUB 首尾的版权/目录/索引等非正文块，避免误删中间正文。"""
        items = [
            (str(title or "").strip(), str(text or "").strip())
            for title, text in parts or []
            if str(text or "").strip()
        ]
        if len(items) <= 1:
            return items, []

        reasons = [
            FileParser._classify_epub_non_narrative_part(title, text)
            for title, text in items
        ]
        start = 0
        end = len(items)
        front_limit = max(1, len(items) // 5)
        back_limit = max(1, len(items) // 5)
        skipped: List[Dict[str, Any]] = []

        while start < end and start < front_limit and reasons[start]:
            skipped.append({
                "index": start,
                "title": items[start][0],
                "reason": reasons[start],
            })
            start += 1

        while end > start and (len(items) - end) < back_limit and reasons[end - 1]:
            skipped.append({
                "index": end - 1,
                "title": items[end - 1][0],
                "reason": reasons[end - 1],
            })
            end -= 1

        if start >= end:
            return items, []
        return items[start:end], sorted(skipped, key=lambda item: int(item["index"]))

    @staticmethod
    def _classify_epub_non_narrative_part(title: str, text: str) -> Optional[str]:
        clean_title = FileParser._normalize_epub_text(title or "")
        normalized_title = FileParser._normalize_heading_text(clean_title)
        body = str(text or "").strip()
        if not body:
            return "empty"
        if normalized_title and FileParser._EPUB_CONTENT_TITLE_RE.match(normalized_title):
            return None

        title_is_junk = normalized_title in FileParser._EPUB_NON_NARRATIVE_TITLE_EXACT or any(
            normalized_title.startswith(prefix)
            for prefix in FileParser._EPUB_NON_NARRATIVE_TITLE_PREFIX
        )
        if title_is_junk and len(body) < 2500:
            return "title"

        sample = body[:5000]
        copyright_hits = len(FileParser._EPUB_COPYRIGHT_CONTENT_RE.findall(sample))
        if copyright_hits >= 2 or (copyright_hits >= 1 and len(body) < 1200):
            return "copyright"

        lines = [line.strip() for line in sample.splitlines() if line.strip()]
        toc_hits = sum(1 for line in lines if FileParser._EPUB_TOC_LINE_RE.match(line))
        if toc_hits >= 4:
            return "toc"

        index_hits = sum(1 for line in lines if FileParser._EPUB_INDEX_LINE_RE.match(line))
        if index_hits >= 6:
            return "index"

        bibliography_hits = len(FileParser._EPUB_BIBLIOGRAPHY_RE.findall(sample))
        if bibliography_hits >= 4:
            return "bibliography"

        if title_is_junk:
            return "title"
        return None

    @staticmethod
    def _first_epub_metadata(book: Any, namespace: str, name: str) -> Optional[str]:
        try:
            items = book.get_metadata(namespace, name)
        except Exception:
            return None
        if not items:
            return None
        value = items[0][0] if items[0] else None
        value = re.sub(r"<[^>]+>", " ", str(value or "")).strip()
        value = FileParser._normalize_epub_text(value)
        return value or None

    @staticmethod
    def _extract_year(value: Optional[str]) -> Optional[int]:
        match = re.search(r'\b(19|20)\d{2}\b', str(value or ""))
        return int(match.group(0)) if match else None

    @staticmethod
    def _format_epub_chapter_marker(title: str, text: str) -> str:
        clean_title = FileParser._normalize_epub_text(title or "").replace(">>", "> >")
        clean_text = str(text or "").strip()
        if not clean_title:
            return clean_text
        clean_text = FileParser._strip_duplicate_chapter_heading(clean_title, clean_text)
        return f"<<CHAPTER_MARKER:{clean_title}>>\n{clean_text}"

    @staticmethod
    def _strip_duplicate_chapter_heading(title: str, text: str) -> str:
        source_text = str(text or "").strip()
        if not source_text or not FileParser._simplify_chapter_heading(title):
            return source_text

        lines = source_text.splitlines()
        kept_lines: List[str] = []
        removed = False
        for line in lines:
            stripped = line.strip()
            if not removed and stripped:
                if FileParser._chapter_headings_equivalent(stripped, title):
                    removed = True
                    continue
            kept_lines.append(line)

        if not removed:
            return source_text

        while kept_lines and not kept_lines[0].strip():
            kept_lines.pop(0)
        return "\n".join(kept_lines).strip()

    @staticmethod
    def _chapter_headings_equivalent(left: str, right: str) -> bool:
        simple_left = FileParser._simplify_chapter_heading(left)
        simple_right = FileParser._simplify_chapter_heading(right)
        if not simple_left or not simple_right:
            return False
        if simple_left == simple_right:
            return True
        return FileParser._chapter_heading_prefix_equivalent(left, right)

    @staticmethod
    def _simplify_chapter_heading(value: str) -> str:
        normalized = FileParser._normalize_heading_text(value)
        if normalized.startswith("chapter") and (
            len(normalized) == 7 or not normalized[7].isalpha()
        ):
            normalized = normalized[7:]
        elif normalized.startswith("ch.") and (
            len(normalized) == 3 or not normalized[3].isalpha()
        ):
            normalized = normalized[3:]
        return re.sub(r"[\W_]+", "", normalized)

    @staticmethod
    def _chapter_heading_prefix_equivalent(left: str, right: str) -> bool:
        left_normalized = FileParser._normalize_heading_text(left)
        right_normalized = FileParser._normalize_heading_text(right)
        for shorter, longer in (
            (left_normalized, right_normalized),
            (right_normalized, left_normalized),
        ):
            if not shorter or len(shorter) >= len(longer) or not longer.startswith(shorter):
                continue
            remainder = longer[len(shorter):]
            if not remainder:
                return True
            next_char = remainder[0]
            if shorter[-1].isdigit() and next_char.isdigit():
                continue
            if next_char.isspace() or next_char in FileParser._CHAPTER_HEADING_BOUNDARY_CHARS:
                return True
            if FileParser._is_complete_chapter_heading_prefix(shorter):
                return True
        return False

    @staticmethod
    def _normalize_heading_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", str(value or ""))
        return FileParser._normalize_epub_text(normalized).lower()

    @staticmethod
    def _is_complete_chapter_heading_prefix(value: str) -> bool:
        normalized = FileParser._normalize_heading_text(value)
        if re.fullmatch(r"第[\u96f6一二三四五六七八九十百千万两\d]+[章节回]", normalized):
            return True
        if re.fullmatch(
            r"(?:chapter|ch\.?)\s*(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten)",
            normalized,
            re.IGNORECASE,
        ):
            return True
        return normalized in {
            "序",
            "序章",
            "楔子",
            "引子",
            "前言",
            "prologue",
            "epilogue",
        }

    @staticmethod
    def _extract_epub_navigation_text_parts(
        book: Any,
        item_document_type: Any,
        beautiful_soup_factory: Any,
    ) -> List[Tuple[str, str]]:
        nav_item, nav_type = FileParser._find_epub_navigation_item(book)
        if not nav_item or not nav_type:
            return []

        documents = FileParser._ordered_epub_documents(book, item_document_type)
        spine_docs = [
            item.get_name()
            for item in documents
            if hasattr(item, "get_name") and item.get_name()
        ]
        if not spine_docs:
            return []

        doc_order = {href: index for index, href in enumerate(spine_docs)}
        doc_content: Dict[str, str] = {}
        for item in documents:
            href = item.get_name()
            if not href:
                continue
            try:
                doc_content[href] = item.get_content().decode('utf-8', errors='ignore')
            except Exception:
                doc_content[href] = ""

        try:
            nav_content = nav_item.get_content().decode('utf-8', errors='ignore')
        except Exception:
            return []

        parser_type = 'xml' if nav_type == 'ncx' else 'html.parser'
        nav_soup = beautiful_soup_factory(nav_content, parser_type)
        nav_base_href = nav_item.get_name() if hasattr(nav_item, "get_name") else ""
        entries = FileParser._collect_epub_nav_entries(
            nav_soup,
            nav_type,
            nav_base_href,
            doc_order,
            doc_content,
            beautiful_soup_factory,
        )
        if not entries:
            return []

        entries.sort(key=lambda entry: (entry.doc_order, entry.position))
        chapters = FileParser._slice_epub_nav_entries(
            entries,
            spine_docs,
            doc_content,
            beautiful_soup_factory,
        )
        return chapters

    @staticmethod
    def _find_epub_navigation_item(book: Any) -> Tuple[Optional[Any], Optional[str]]:
        try:
            items = list(book.get_items())
        except Exception:
            return None, None

        html_candidates = []
        ncx_candidates = []
        for item in items:
            if not hasattr(item, "get_name"):
                continue
            name = str(item.get_name() or "")
            lower_name = name.lower()
            properties = {
                str(prop).lower()
                for prop in (getattr(item, "properties", []) or [])
            }
            media_type = str(getattr(item, "media_type", "") or "").lower()
            is_html = lower_name.endswith((".xhtml", ".html", ".htm"))
            if is_html and (
                "nav" in properties
                or lower_name.endswith("nav.xhtml")
                or "nav" in posixpath.basename(lower_name)
            ):
                html_candidates.append(item)
            elif is_html and media_type in {"application/xhtml+xml", "text/html"}:
                html_candidates.append(item)
            elif lower_name.endswith(".ncx"):
                ncx_candidates.append(item)

        if html_candidates:
            preferred = next(
                (
                    item
                    for item in html_candidates
                    if "nav" in posixpath.basename(str(item.get_name()).lower())
                ),
                html_candidates[0],
            )
            return preferred, "html"
        if ncx_candidates:
            return ncx_candidates[0], "ncx"
        return None, None

    @staticmethod
    def _collect_epub_nav_entries(
        nav_soup: Any,
        nav_type: str,
        nav_base_href: str,
        doc_order: Dict[str, int],
        doc_content: Dict[str, str],
        beautiful_soup_factory: Any,
    ) -> List[_EpubNavEntry]:
        entries: List[_EpubNavEntry] = []
        if nav_type == 'ncx':
            nav_map = nav_soup.find("navMap")
            if not nav_map:
                return entries
            for nav_point in nav_map.find_all("navPoint", recursive=False):
                FileParser._parse_epub_ncx_navpoint(
                    nav_point,
                    entries,
                    nav_base_href,
                    doc_order,
                    doc_content,
                    beautiful_soup_factory,
                )
            return entries

        toc_nav = FileParser._find_epub_toc_nav(nav_soup)
        if toc_nav is None:
            return entries
        top_ol = toc_nav.find("ol", recursive=False)
        if top_ol is None:
            return entries
        for li in top_ol.find_all("li", recursive=False):
            FileParser._parse_epub_html_nav_li(
                li,
                entries,
                nav_base_href,
                doc_order,
                doc_content,
                beautiful_soup_factory,
            )
        return entries

    @staticmethod
    def _find_epub_toc_nav(nav_soup: Any) -> Optional[Any]:
        for nav in nav_soup.find_all("nav"):
            epub_type = str(nav.get("epub:type") or nav.get("type") or "").lower()
            role = str(nav.get("role") or "").lower()
            if "toc" in epub_type.split() or role == "doc-toc":
                return nav
        for nav in nav_soup.find_all("nav"):
            if nav.find("ol"):
                return nav
        return None

    @staticmethod
    def _parse_epub_ncx_navpoint(
        nav_point: Any,
        entries: List[_EpubNavEntry],
        nav_base_href: str,
        doc_order: Dict[str, int],
        doc_content: Dict[str, str],
        beautiful_soup_factory: Any,
    ) -> None:
        nav_label = nav_point.find("navLabel")
        label_text = nav_label.find("text") if nav_label else None
        title = label_text.get_text(strip=True) if label_text else "未命名章节"
        content = nav_point.find("content")
        src = content.get("src") if content and content.has_attr("src") else None
        if src:
            entry = FileParser._build_epub_nav_entry(
                str(src),
                title,
                nav_base_href,
                doc_order,
                doc_content,
                beautiful_soup_factory,
            )
            if entry:
                entries.append(entry)

        for child in nav_point.find_all("navPoint", recursive=False):
            FileParser._parse_epub_ncx_navpoint(
                child,
                entries,
                nav_base_href,
                doc_order,
                doc_content,
                beautiful_soup_factory,
            )

    @staticmethod
    def _parse_epub_html_nav_li(
        li_element: Any,
        entries: List[_EpubNavEntry],
        nav_base_href: str,
        doc_order: Dict[str, int],
        doc_content: Dict[str, str],
        beautiful_soup_factory: Any,
    ) -> None:
        link = li_element.find("a", recursive=False)
        span = li_element.find("span", recursive=False)
        src = str(link.get("href")) if link and link.has_attr("href") else ""
        title = ""
        if link:
            title = link.get_text(strip=True)
        if not title and span:
            title = span.get_text(strip=True)
        if not title:
            title = "".join(li_element.stripped_strings).strip()

        if src:
            entry = FileParser._build_epub_nav_entry(
                src,
                title or "未命名章节",
                nav_base_href,
                doc_order,
                doc_content,
                beautiful_soup_factory,
            )
            if entry:
                entries.append(entry)

        for child_ol in li_element.find_all("ol", recursive=False):
            for child_li in child_ol.find_all("li", recursive=False):
                FileParser._parse_epub_html_nav_li(
                    child_li,
                    entries,
                    nav_base_href,
                    doc_order,
                    doc_content,
                    beautiful_soup_factory,
                )

    @staticmethod
    def _build_epub_nav_entry(
        src: str,
        title: str,
        nav_base_href: str,
        doc_order: Dict[str, int],
        doc_content: Dict[str, str],
        beautiful_soup_factory: Any,
    ) -> Optional[_EpubNavEntry]:
        base_href, fragment = src.split("#", 1) if "#" in src else (src, None)
        doc_href = FileParser._resolve_epub_doc_href(base_href, nav_base_href, doc_order)
        if doc_href is None:
            return None
        html = doc_content.get(doc_href, "")
        position = FileParser._find_epub_fragment_position(
            html,
            fragment,
            beautiful_soup_factory,
        )
        return _EpubNavEntry(
            title=FileParser._normalize_epub_text(title or "未命名章节"),
            doc_href=doc_href,
            position=position,
            doc_order=doc_order[doc_href],
        )

    @staticmethod
    def _resolve_epub_doc_href(
        base_href: str,
        nav_base_href: str,
        doc_order: Dict[str, int],
    ) -> Optional[str]:
        decoded = urllib.parse.unquote(str(base_href or "")).strip()
        candidates = [decoded]
        if nav_base_href and decoded:
            nav_dir = posixpath.dirname(urllib.parse.unquote(nav_base_href))
            candidates.append(posixpath.normpath(posixpath.join(nav_dir, decoded)))
        for candidate in candidates:
            if candidate in doc_order:
                return candidate

        base_name = posixpath.basename(decoded).lower()
        if not base_name:
            return None
        for href in doc_order:
            if posixpath.basename(urllib.parse.unquote(href)).lower() == base_name:
                return href
        return None

    @staticmethod
    def _find_epub_fragment_position(
        html: str,
        fragment: Optional[str],
        beautiful_soup_factory: Any,
    ) -> int:
        if not html or not fragment:
            return 0
        fragment_id = urllib.parse.unquote(str(fragment)).strip()
        if not fragment_id:
            return 0

        try:
            soup = beautiful_soup_factory(html, 'html.parser')
            target = soup.find(id=fragment_id) or soup.find(attrs={"name": fragment_id})
            if target:
                snippet = str(target)
                position = html.find(snippet[: min(len(snippet), 200)])
                if position >= 0:
                    return position
        except Exception:
            pass

        safe_fragment_id = re.escape(fragment_id)
        pattern = re.compile(
            rf"<[^>]+(?:id|name)\s*=\s*['\"]{safe_fragment_id}['\"]",
            re.IGNORECASE,
        )
        match = pattern.search(html)
        return match.start() if match else 0

    @staticmethod
    def _slice_epub_nav_entries(
        entries: List[_EpubNavEntry],
        spine_docs: List[str],
        doc_content: Dict[str, str],
        beautiful_soup_factory: Any,
    ) -> List[Tuple[str, str]]:
        chapters: List[Tuple[str, str]] = []
        if not entries:
            return chapters

        first = entries[0]
        prefix_html = ""
        try:
            first_doc_index = spine_docs.index(first.doc_href)
        except ValueError:
            first_doc_index = -1
        if first_doc_index > 0:
            for doc_href in spine_docs[:first_doc_index]:
                prefix_html += doc_content.get(doc_href, "")
        prefix_html += doc_content.get(first.doc_href, "")[: first.position]
        prefix_text = FileParser._extract_epub_document_text(prefix_html, beautiful_soup_factory)
        if prefix_text:
            chapters.append(("导言", prefix_text))

        for index, entry in enumerate(entries):
            next_entry = entries[index + 1] if index + 1 < len(entries) else None
            slice_html = FileParser._slice_epub_html_between_entries(
                entry,
                next_entry,
                spine_docs,
                doc_content,
            )
            text = FileParser._extract_epub_document_text(slice_html, beautiful_soup_factory)
            if text:
                chapters.append((entry.title, text))
        return chapters

    @staticmethod
    def _slice_epub_html_between_entries(
        current: _EpubNavEntry,
        next_entry: Optional[_EpubNavEntry],
        spine_docs: List[str],
        doc_content: Dict[str, str],
    ) -> str:
        current_html = doc_content.get(current.doc_href, "")
        if not current_html:
            return ""

        if next_entry and next_entry.doc_href == current.doc_href:
            return current_html[current.position: next_entry.position]

        slice_html = current_html[current.position:]
        try:
            current_index = spine_docs.index(current.doc_href)
        except ValueError:
            current_index = -1

        if next_entry is None:
            if current_index >= 0:
                for doc_href in spine_docs[current_index + 1:]:
                    slice_html += doc_content.get(doc_href, "")
            return slice_html

        try:
            next_index = spine_docs.index(next_entry.doc_href)
        except ValueError:
            next_index = -1

        if current_index >= 0 and next_index > current_index:
            for doc_href in spine_docs[current_index + 1: next_index]:
                slice_html += doc_content.get(doc_href, "")
        slice_html += doc_content.get(next_entry.doc_href, "")[: next_entry.position]
        return slice_html

    @staticmethod
    def _extract_epub_document_text(html: str, beautiful_soup_factory: Any) -> str:
        soup = beautiful_soup_factory(html, 'html.parser')

        for node in soup(['script', 'style', 'noscript', 'header', 'footer', 'nav', 'meta', 'head', 'input']):
            node.decompose()

        for node in list(soup.find_all(list(FileParser._EPUB_FOOTNOTE_CONTAINER_TAGS))):
            if FileParser._epub_node_has_footnote_marker(node):
                node.decompose()

        for node in list(soup.find_all('sup')):
            if FileParser._epub_sup_looks_like_note_ref(node):
                node.decompose()

        for anchor in soup.find_all('a', href=True):
            anchor_text = anchor.get_text(strip=True)
            if FileParser._epub_node_has_footnote_marker(anchor) or (
                anchor_text and not any(char.isalpha() for char in anchor_text)
            ):
                anchor.decompose()

        blocks = FileParser._extract_epub_reading_blocks(soup)

        if not blocks:
            raw_text = soup.get_text(separator='\n')
            blocks = [
                FileParser._normalize_epub_text(line)
                for line in raw_text.splitlines()
                if line.strip()
            ]

        blocks = FileParser._strip_epub_inline_note_blocks(blocks)
        return '\n'.join(blocks)

    @staticmethod
    def _extract_epub_reading_blocks(soup: Any) -> List[str]:
        """按 EPUB HTML 的阅读顺序提取可朗读块，并保留基础停顿结构。"""
        root = getattr(soup, "body", None) or soup
        blocks: List[str] = []

        for node in getattr(root, "descendants", []):
            name = str(getattr(node, "name", "") or "").lower()
            if not name:
                continue

            if name == "hr":
                FileParser._append_epub_block(blocks, FileParser._EPUB_SCENE_BREAK_PAUSE_MARKER)
                continue

            if name == "br":
                if not FileParser._epub_has_reading_block_ancestor(node):
                    FileParser._append_epub_block(blocks, FileParser._EPUB_LINE_BREAK_PAUSE_MARKER)
                continue

            if not FileParser._epub_node_is_reading_block(node):
                continue
            if FileParser._epub_has_reading_block_ancestor(node):
                continue

            text = FileParser._extract_epub_block_text(node)
            if text:
                FileParser._append_epub_block(blocks, text)

        return blocks

    @staticmethod
    def _extract_epub_block_text(node: Any) -> str:
        br_nodes = list(node.find_all("br")) if hasattr(node, "find_all") else []
        for br in br_nodes:
            br.replace_with(f" {FileParser._EPUB_LINE_BREAK_PAUSE_MARKER} ")
        return FileParser._normalize_epub_text(" ".join(node.stripped_strings))

    @staticmethod
    def _append_epub_block(blocks: List[str], text: str) -> None:
        value = FileParser._normalize_epub_text(text)
        if not value:
            return
        if blocks and blocks[-1] == value and value.startswith("[pause:"):
            return
        blocks.append(value)

    @staticmethod
    def _strip_epub_inline_note_blocks(blocks: List[str]) -> List[str]:
        """裁掉章节末尾直接内嵌的尾注/脚注段落，避免被当作正文朗读。"""
        items = [
            FileParser._normalize_epub_text(block)
            for block in blocks or []
            if FileParser._normalize_epub_text(block)
        ]
        if len(items) < 4:
            return items

        boundary_start = max(0, int(len(items) * 0.65))
        for index in range(boundary_start, len(items)):
            title = FileParser._normalize_heading_text(items[index])
            if title not in FileParser._EPUB_INLINE_NOTES_TITLE_EXACT:
                continue
            trailing = items[index + 1:]
            if trailing and any(FileParser._epub_block_looks_like_inline_note(block) for block in trailing):
                return items[:index]

        scan_start = max(0, int(len(items) * 0.7))
        consecutive_notes = 0
        notes_start: Optional[int] = None
        for index in range(len(items) - 1, scan_start - 1, -1):
            if FileParser._epub_block_looks_like_inline_note(items[index]):
                consecutive_notes += 1
                notes_start = index
                continue
            if consecutive_notes >= 3 and notes_start is not None:
                return items[:notes_start]
            consecutive_notes = 0
            notes_start = None

        if consecutive_notes >= 3 and notes_start is not None:
            return items[:notes_start]
        return items

    @staticmethod
    def _epub_block_looks_like_inline_note(block: str) -> bool:
        value = FileParser._normalize_epub_text(block)
        if not value or len(value) > 1200:
            return False
        return bool(FileParser._EPUB_INLINE_NOTE_LINE_RE.match(value))

    @staticmethod
    def _epub_node_is_reading_block(node: Any) -> bool:
        name = str(getattr(node, "name", "") or "").lower()
        if name in FileParser._EPUB_READING_BLOCK_TAGS:
            return True
        classes = FileParser._epub_node_classes(node)
        return bool(classes.intersection(FileParser._EPUB_SEMANTIC_BLOCK_CLASSES))

    @staticmethod
    def _epub_has_reading_block_ancestor(node: Any) -> bool:
        parent = getattr(node, "parent", None)
        while parent is not None:
            if FileParser._epub_node_is_reading_block(parent):
                return True
            parent = getattr(parent, "parent", None)
        return False

    @staticmethod
    def _epub_node_classes(node: Any) -> set[str]:
        value = node.get("class") if hasattr(node, "get") else None
        if not value:
            return set()
        if isinstance(value, str):
            return {part.strip().lower() for part in value.split() if part.strip()}
        return {str(part).strip().lower() for part in value if str(part).strip()}

    @staticmethod
    def _extract_epub_document_title(html: str, beautiful_soup_factory: Any) -> Optional[str]:
        soup = beautiful_soup_factory(html, 'html.parser')

        for tag_name in ("h1", "h2", "h3"):
            heading = soup.find(tag_name)
            title = FileParser._normalize_epub_text(
                " ".join(heading.stripped_strings) if heading else ""
            )
            if FileParser._looks_like_epub_title(title):
                return title

        title_classes = {"chapter", "chapter-title", "title", "heading", "chapterhead"}
        for node in soup.find_all(class_=True):
            classes = {
                str(item).strip().lower()
                for item in (node.get("class") or [])
                if str(item).strip()
            }
            if not classes.intersection(title_classes):
                continue
            title = FileParser._normalize_epub_text(" ".join(node.stripped_strings))
            if FileParser._looks_like_epub_title(title):
                return title
        return None

    @staticmethod
    def _looks_like_epub_title(text: str) -> bool:
        value = str(text or "").strip()
        if not value or len(value) > 120:
            return False
        return any(char.isalnum() or "\u4e00" <= char <= "\u9fff" for char in value)

    @staticmethod
    def _epub_node_has_footnote_marker(node: Any) -> bool:
        marker_parts = []
        for attr_name in ("epub:type", "type", "role", "class", "id", "href"):
            value = node.get(attr_name) if hasattr(node, "get") else None
            if isinstance(value, list):
                marker_parts.extend(str(item) for item in value)
            elif value:
                marker_parts.append(str(value))
        marker_text = " ".join(marker_parts)
        return bool(FileParser._EPUB_FOOTNOTE_ATTR_RE.search(marker_text))

    @staticmethod
    def _epub_sup_looks_like_note_ref(node: Any) -> bool:
        if FileParser._epub_node_has_footnote_marker(node):
            return True
        text = node.get_text("", strip=True) if hasattr(node, "get_text") else ""
        compact = re.sub(r"\s+", "", str(text or ""))
        if not compact or len(compact) > 12:
            return False
        return not any(char.isalpha() for char in compact)

    @staticmethod
    def _normalize_epub_text(text: str) -> str:
        normalized = str(text or "").translate(
            str.maketrans({
                "“": '"',
                "”": '"',
                "‘": "'",
                "’": "'",
            })
        )
        return re.sub(r'\s+', ' ', normalized).strip()

    @staticmethod
    def _extract_epub_cover_payload(content: bytes) -> Optional[Dict[str, Any]]:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                container_xml = archive.read("META-INF/container.xml")
                container_root = ET.fromstring(container_xml)
                rootfiles = container_root.findall(".//{*}rootfile")
                if not rootfiles:
                    return None

                rootfile_path = rootfiles[0].attrib.get("full-path")
                if not rootfile_path:
                    return None

                opf_root = ET.fromstring(archive.read(rootfile_path))
                manifest_items = opf_root.findall(".//{*}manifest/{*}item")
                cover_id = FileParser._find_epub_cover_id(opf_root)
                cover_item = FileParser._find_epub_cover_item(manifest_items, cover_id)
                if cover_item is None:
                    return None

                href = str(cover_item.attrib.get("href") or "").strip()
                if not href:
                    return None

                cover_path = posixpath.normpath(posixpath.join(posixpath.dirname(rootfile_path), href))
                cover_bytes = archive.read(cover_path)
                if not cover_bytes:
                    return None

                media_type = str(cover_item.attrib.get("media-type") or "").strip()
                extension = FileParser._cover_extension_from_media_type(media_type)
                if not extension:
                    extension = Path(cover_path).suffix.lower()
                if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
                    extension = ".jpg"

                return {
                    "cover_image_bytes": cover_bytes,
                    "cover_image_extension": extension,
                    "cover_image_media_type": media_type,
                    "cover_image_path": cover_path,
                }
        except Exception:
            return None

    @staticmethod
    def _find_epub_cover_id(opf_root: Any) -> Optional[str]:
        metadata_nodes = opf_root.findall(".//{*}metadata/{*}meta")
        for meta in metadata_nodes:
            name = str(meta.attrib.get("name") or "").strip().lower()
            if name == "cover":
                cover_id = str(meta.attrib.get("content") or "").strip()
                if cover_id:
                    return cover_id

        for meta in metadata_nodes:
            prop = str(meta.attrib.get("property") or "").strip().lower()
            if prop == "cover":
                cover_id = str(meta.text or meta.attrib.get("content") or "").strip()
                if cover_id:
                    return cover_id
        return None

    @staticmethod
    def _find_epub_cover_item(manifest_items: list[Any], cover_id: Optional[str]) -> Optional[Any]:
        if cover_id:
            for item in manifest_items:
                if str(item.attrib.get("id") or "").strip() == cover_id:
                    return item

        for item in manifest_items:
            properties = str(item.attrib.get("properties") or "").lower().split()
            if "cover-image" in properties:
                return item

        for item in manifest_items:
            media_type = str(item.attrib.get("media-type") or "").lower()
            if not media_type.startswith("image/"):
                continue
            item_id = str(item.attrib.get("id") or "").lower()
            href = str(item.attrib.get("href") or "").lower()
            if "cover" in item_id or "cover" in href:
                return item
        return None

    @staticmethod
    def _cover_extension_from_media_type(media_type: str) -> str:
        normalized = str(media_type or "").strip().lower()
        if normalized in {"image/jpeg", "image/jpg"}:
            return ".jpg"
        if normalized == "image/png":
            return ".png"
        if normalized == "image/webp":
            return ".webp"
        return ""
    
    def _parse_pdf(self, content: bytes, filename: str) -> ParsedContent:
        """解析 PDF 文件"""
        if not self.pdf_available:
            return ParsedContent(
                text="",
                format=FileFormat.PDF,
                success=False,
                error="PDF 解析不可用，请安装 PyPDF2"
            )
        
        try:
            import PyPDF2
        except ImportError:
            return ParsedContent(
                text="",
                format=FileFormat.PDF,
                success=False,
                error="缺少依赖: PyPDF2"
            )
        
        try:
            # 从字节流创建 PDF 阅读器
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(content))
            
            # 提取元数据
            metadata = pdf_reader.metadata or {}
            title = metadata.get('/Title')
            author = metadata.get('/Author')
            
            # 提取文本
            page_texts = []
            num_pages = len(pdf_reader.pages)
            
            for page_num in range(num_pages):
                page = pdf_reader.pages[page_num]
                text = str(page.extract_text() or "").strip()
                page_texts.append(text)
            page_texts, pdf_boundary_lines_removed = self._strip_pdf_repeated_boundary_lines(
                page_texts
            )
            
            outline_entries = self._extract_pdf_outline_entries(pdf_reader)
            pdf_chapter_source = "outline" if outline_entries else "pages"
            if outline_entries:
                full_text = self._format_pdf_text_with_outline(page_texts, outline_entries)
            else:
                markdown_text = self._extract_pdf_markdown_text(content)
                markdown_full_text, markdown_chapter_count = self._format_pdf_markdown_chapter_markers(
                    markdown_text or ""
                )
                if markdown_chapter_count:
                    full_text = markdown_full_text
                    pdf_chapter_source = "markdown_headings"
                else:
                    full_text = self._format_pdf_text_with_outline(page_texts, outline_entries)
            
            logger.info(f"✅ PDF 解析成功: {num_pages} 页, {len(full_text)} 字符")
            if title:
                logger.info(f"   书名: {title}")
            if author:
                logger.info(f"   作者: {author}")
            
            return ParsedContent(
                text=full_text,
                title=title,
                author=author,
                format=FileFormat.PDF,
                metadata={
                    "pages": num_pages,
                    "pdf_outline_count": len(outline_entries),
                    "pdf_chapter_source": pdf_chapter_source,
                    "pdf_boundary_lines_removed": pdf_boundary_lines_removed,
                    "producer": metadata.get('/Producer'),
                    "creator": metadata.get('/Creator')
                },
                success=True
            )
            
        except Exception as e:
            logger.error(f"❌ PDF 解析失败: {e}")
            return ParsedContent(
                text="",
                format=FileFormat.PDF,
                success=False,
                error=f"PDF 解析失败: {str(e)}"
            )

    @staticmethod
    def _strip_pdf_repeated_boundary_lines(page_texts: List[str]) -> Tuple[List[str], int]:
        """移除 PDF 每页首尾重复页眉/页脚和独立页码，降低朗读噪声。"""
        pages = [str(text or "") for text in page_texts or []]
        line_pages = [
            [line.strip() for line in page.splitlines() if line.strip()]
            for page in pages
        ]
        non_empty_page_count = sum(1 for lines in line_pages if lines)
        if non_empty_page_count < 3:
            return pages, 0

        boundary_candidates: List[str] = []
        scan_count = FileParser._PDF_BOUNDARY_LINE_SCAN_COUNT
        for lines in line_pages:
            if not lines:
                continue
            for line in lines[:scan_count]:
                boundary_candidates.append(FileParser._normalize_pdf_boundary_line(line))
            for line in lines[-scan_count:]:
                boundary_candidates.append(FileParser._normalize_pdf_boundary_line(line))

        min_repeats = max(3, non_empty_page_count // 2)
        counts = Counter(line for line in boundary_candidates if line)
        repeated_boundary_lines = {
            line
            for line, count in counts.items()
            if count >= min_repeats and FileParser._pdf_boundary_line_can_repeat(line)
        }
        if not repeated_boundary_lines:
            repeated_boundary_lines = set()

        cleaned_pages: List[str] = []
        removed_count = 0
        for lines in line_pages:
            cleaned_lines = list(lines)
            front_removed = 0
            while cleaned_lines and front_removed < scan_count:
                normalized = FileParser._normalize_pdf_boundary_line(cleaned_lines[0])
                if not FileParser._should_strip_pdf_boundary_line(normalized, repeated_boundary_lines):
                    break
                cleaned_lines.pop(0)
                front_removed += 1
                removed_count += 1

            back_removed = 0
            while cleaned_lines and back_removed < scan_count:
                normalized = FileParser._normalize_pdf_boundary_line(cleaned_lines[-1])
                if not FileParser._should_strip_pdf_boundary_line(normalized, repeated_boundary_lines):
                    break
                cleaned_lines.pop()
                back_removed += 1
                removed_count += 1

            cleaned_pages.append("\n".join(cleaned_lines).strip())

        return cleaned_pages, removed_count

    @staticmethod
    def _normalize_pdf_boundary_line(line: str) -> str:
        return FileParser._normalize_epub_text(unicodedata.normalize("NFKC", str(line or "")))

    @staticmethod
    def _pdf_boundary_line_can_repeat(line: str) -> bool:
        value = str(line or "").strip()
        if not value or len(value) > 120:
            return False
        if FileParser._PDF_PAGE_NUMBER_RE.match(value):
            return False
        return bool(re.search(r"[A-Za-z0-9\u3400-\u4dbf\u4e00-\u9fff]", value))

    @staticmethod
    def _should_strip_pdf_boundary_line(line: str, repeated_boundary_lines: set[str]) -> bool:
        value = str(line or "").strip()
        return bool(
            value
            and (
                value in repeated_boundary_lines
                or FileParser._PDF_PAGE_NUMBER_RE.match(value)
            )
        )

    @staticmethod
    def _extract_pdf_markdown_text(content: bytes) -> Optional[str]:
        """可选使用 pymupdf4llm 提取 PDF Markdown，用于无书签 PDF 的标题恢复。"""
        try:
            import pymupdf4llm
        except Exception:
            return None

        temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
                temp_file.write(bytes(content or b""))
                temp_path = Path(temp_file.name)

            try:
                markdown = pymupdf4llm.to_markdown(str(temp_path), show_progress=False)
            except TypeError:
                markdown = pymupdf4llm.to_markdown(str(temp_path))
            return str(markdown or "").strip() or None
        except Exception as exc:
            logger.debug("PDF Markdown fallback unavailable: %s", exc)
            return None
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    @staticmethod
    def _format_pdf_markdown_chapter_markers(markdown_text: str) -> Tuple[str, int]:
        """将 PDF Markdown 中稳定重复的标题层级转换为显式章节标记。"""
        lines = str(markdown_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        heading_levels: Dict[int, int] = {}
        for line in lines:
            match = FileParser._TXT_MARKDOWN_HEADING_RE.match(line.strip())
            if not match:
                continue
            title = FileParser._normalize_epub_text(match.group(2))
            if not FileParser._looks_like_epub_title(title):
                continue
            level = len(match.group(1))
            heading_levels[level] = heading_levels.get(level, 0) + 1

        selected_level = next(
            (level for level in sorted(heading_levels) if heading_levels[level] >= 2),
            None,
        )
        if selected_level is None:
            return "", 0

        formatted_lines: List[str] = []
        chapter_count = 0
        for line in lines:
            stripped = line.strip()
            match = FileParser._TXT_MARKDOWN_HEADING_RE.match(stripped)
            if not match or len(match.group(1)) != selected_level:
                formatted_lines.append(line)
                continue

            title = FileParser._normalize_epub_text(match.group(2)).replace(">>", "> >")
            if not FileParser._looks_like_epub_title(title):
                formatted_lines.append(line)
                continue

            chapter_count += 1
            formatted_lines.append(f"<<CHAPTER_MARKER:{title}>>")

        return "\n".join(formatted_lines).strip(), chapter_count

    @staticmethod
    def _extract_pdf_outline_entries(pdf_reader: Any) -> List[Dict[str, Any]]:
        outline = getattr(pdf_reader, "outline", None)
        if outline is None:
            outline = getattr(pdf_reader, "outlines", None)
        entries: List[Dict[str, Any]] = []

        def walk(items: Any) -> None:
            if not items:
                return
            if not isinstance(items, (list, tuple)):
                items = [items]
            for item in items:
                if isinstance(item, (list, tuple)):
                    walk(item)
                    continue
                title = FileParser._pdf_outline_title(item)
                page_index = FileParser._pdf_outline_page_index(pdf_reader, item)
                if title and page_index is not None:
                    entries.append({"title": title, "page_index": page_index})

        walk(outline)
        return FileParser._dedupe_pdf_outline_entries(entries)

    @staticmethod
    def _pdf_outline_title(item: Any) -> str:
        value = None
        if isinstance(item, dict):
            value = item.get("/Title") or item.get("title") or item.get("Title")
        if value is None:
            value = getattr(item, "title", None)
        return FileParser._normalize_epub_text(value or "")

    @staticmethod
    def _pdf_outline_page_index(pdf_reader: Any, item: Any) -> Optional[int]:
        for method_name in ("get_destination_page_number", "getDestinationPageNumber"):
            method = getattr(pdf_reader, method_name, None)
            if not callable(method):
                continue
            try:
                page_index = int(method(item))
                return page_index if page_index >= 0 else None
            except Exception:
                continue
        return None

    @staticmethod
    def _dedupe_pdf_outline_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        seen_pages = set()
        for entry in sorted(entries or [], key=lambda item: int(item.get("page_index") or 0)):
            title = FileParser._normalize_epub_text(entry.get("title") or "")
            try:
                page_index = int(entry.get("page_index"))
            except Exception:
                continue
            if not title or page_index < 0 or page_index in seen_pages:
                continue
            deduped.append({"title": title, "page_index": page_index})
            seen_pages.add(page_index)
        return deduped

    @staticmethod
    def _format_pdf_text_with_outline(
        page_texts: List[str],
        outline_entries: List[Dict[str, Any]],
    ) -> str:
        pages = [str(text or "").strip() for text in page_texts or []]
        entries = [
            entry
            for entry in FileParser._dedupe_pdf_outline_entries(outline_entries or [])
            if int(entry.get("page_index") or -1) < len(pages)
        ]
        if not entries:
            return "\n\n".join(text for text in pages if text)

        parts: List[str] = []
        first_page = int(entries[0]["page_index"])
        if first_page > 0:
            prefix = "\n\n".join(text for text in pages[:first_page] if text)
            if prefix:
                parts.append(FileParser._format_epub_chapter_marker("导言", prefix))

        for index, entry in enumerate(entries):
            start_page = int(entry["page_index"])
            end_page = (
                int(entries[index + 1]["page_index"])
                if index + 1 < len(entries)
                else len(pages)
            )
            chapter_text = "\n\n".join(text for text in pages[start_page:end_page] if text)
            if not chapter_text:
                continue
            parts.append(FileParser._format_epub_chapter_marker(entry["title"], chapter_text))

        return "\n\n".join(parts).strip()
