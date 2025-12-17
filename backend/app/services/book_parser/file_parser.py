"""
多格式文件解析器

支持格式：
- TXT: 纯文本
- EPUB: 电子书标准格式
- PDF: 便携式文档格式
"""

import io
import logging
from typing import Dict, Any, Optional
from pathlib import Path
from dataclasses import dataclass
from enum import Enum

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


class FileParser:
    """
    多格式文件解析器
    
    支持 TXT/EPUB/PDF 格式的文本提取
    """
    
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
        if ext == 'txt':
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
        
        logger.info(f"✅ TXT 解析成功 ({detected_encoding}): {len(text)} 字符")
        
        return ParsedContent(
            text=text,
            format=FileFormat.TXT,
            metadata={"encoding": detected_encoding},
            success=True
        )
    
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
            from ebooklib import epub
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
            
            # 提取文本内容
            text_parts = []
            
            for item in book.get_items():
                if item.get_type() == epub.ITEM_DOCUMENT:
                    # 使用 BeautifulSoup 提取纯文本
                    html = item.get_content().decode('utf-8', errors='ignore')
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # 移除脚本和样式
                    for script in soup(['script', 'style']):
                        script.decompose()
                    
                    text = soup.get_text(separator='\n')
                    if text.strip():
                        text_parts.append(text.strip())
            
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
                    "items_count": len(list(book.get_items()))
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
            text_parts = []
            num_pages = len(pdf_reader.pages)
            
            for page_num in range(num_pages):
                page = pdf_reader.pages[page_num]
                text = page.extract_text()
                if text.strip():
                    text_parts.append(text.strip())
            
            full_text = '\n\n'.join(text_parts)
            
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
