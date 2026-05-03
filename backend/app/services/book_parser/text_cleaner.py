"""
文本清洗器

对原始文本进行预处理，包括：
- 编码转换
- 格式统一
- 去除无效字符
- 段落整理
"""
import re
from typing import Optional
from dataclasses import dataclass

from app.services.book_parser.text_metrics import count_readable_units


@dataclass
class CleanResult:
    """清洗结果"""
    text: str                    # 清洗后的文本
    original_length: int         # 原始长度
    cleaned_length: int          # 清洗后长度
    word_count: int              # 可朗读文本单位（中文按字，英文/数字按词）
    paragraph_count: int         # 段落数
    has_bom: bool               # 是否有BOM头
    detected_encoding: str       # 检测到的编码


class TextCleaner:
    """
    文本清洗器
    
    负责对原始书籍文本进行预处理，确保后续切分的准确性
    """
    
    # 需要移除的特殊字符
    INVALID_CHARS = [
        '\x00', '\x01', '\x02', '\x03', '\x04', '\x05', '\x06', '\x07',
        '\x08', '\x0b', '\x0c', '\x0e', '\x0f', '\x10', '\x11', '\x12',
        '\x13', '\x14', '\x15', '\x16', '\x17', '\x18', '\x19', '\x1a',
        '\x1b', '\x1c', '\x1d', '\x1e', '\x1f',
    ]
    
    # BOM 标记
    BOM_MARKS = {
        '\ufeff': 'UTF-8-BOM',
        '\ufffe': 'UTF-16-LE-BOM',
    }
    
    def __init__(self):
        # 编译正则表达式
        self._multi_newline_pattern = re.compile(r'\n{3,}')
        self._multi_space_pattern = re.compile(r'[ \t]{2,}')
        self._leading_space_pattern = re.compile(r'^[ \t]+', re.MULTILINE)
        self._empty_line_pattern = re.compile(r'\n[ \t]*\n')
        self._hyphenated_line_break_pattern = re.compile(r'(?<=[A-Za-z])-\n(?=[A-Za-z])')
        self._isbn_line_pattern = re.compile(
            r'(?im)^[^\n]{0,40}\bISBN(?:-1[03])?\b[-: \t]*[0-9Xx][0-9Xx\- \t]{8,}[^\n]*$'
        )
        
    def clean(self, text: str, preserve_paragraphs: bool = True) -> CleanResult:
        """
        清洗文本
        
        Args:
            text: 原始文本
            preserve_paragraphs: 是否保留段落结构
            
        Returns:
            CleanResult: 清洗结果
        """
        original_length = len(text)
        has_bom = False
        detected_encoding = 'UTF-8'
        
        # 1. 检测并移除 BOM
        for bom, encoding in self.BOM_MARKS.items():
            if text.startswith(bom):
                text = text[1:]
                has_bom = True
                detected_encoding = encoding
                break
        
        # 2. 移除无效控制字符
        for char in self.INVALID_CHARS:
            text = text.replace(char, '')
        
        # 3. 统一换行符
        text = text.replace('\r\n', '\n').replace('\r', '\n')

        # 移除独立 ISBN/书号元数据行，避免被读成正文
        text = self._isbn_line_pattern.sub('', text)

        # 修复英文 PDF/EPUB 中常见的断词换行: "exam-\nple" -> "example"
        text = self._hyphenated_line_break_pattern.sub('', text)
        
        # 4. 处理全角/半角空格
        text = text.replace('\u3000', '  ')  # 全角空格转两个半角
        text = text.replace('\xa0', ' ')     # 不间断空格转普通空格
        
        # 5. 清理多余空白
        if preserve_paragraphs:
            # 保留段落结构，但合并过多空行
            text = self._multi_newline_pattern.sub('\n\n', text)
            # 清理行内多余空格
            text = self._multi_space_pattern.sub(' ', text)
        else:
            # 合并所有空白为单个空格
            text = ' '.join(text.split())
        
        # 6. 清理每行开头的空格（保留首行缩进2个空格）
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped:
                # 如果原本有缩进，保留2空格缩进
                if line.startswith(' ') or line.startswith('\t'):
                    cleaned_lines.append('  ' + stripped)
                else:
                    cleaned_lines.append(stripped)
            else:
                cleaned_lines.append('')
        text = '\n'.join(cleaned_lines)
        
        # 7. 再次合并过多空行
        text = self._multi_newline_pattern.sub('\n\n', text)
        
        # 8. 去除首尾空白
        text = text.strip()
        
        # 计算统计信息
        cleaned_length = len(text)
        word_count = self._count_readable_units(text)
        paragraph_count = self._count_paragraphs(text)
        
        return CleanResult(
            text=text,
            original_length=original_length,
            cleaned_length=cleaned_length,
            word_count=word_count,
            paragraph_count=paragraph_count,
            has_bom=has_bom,
            detected_encoding=detected_encoding
        )
    
    def _count_readable_units(self, text: str) -> int:
        """
        统计可朗读文本单位
        """
        return count_readable_units(text)
    
    def _count_paragraphs(self, text: str) -> int:
        """
        统计段落数
        
        以空行分隔的非空文本块为一个段落
        """
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        return len(paragraphs)
    
    def normalize_punctuation(self, text: str) -> str:
        """
        标点符号规范化
        
        将英文标点转换为中文标点（用于中文小说）
        """
        # 使用 Unicode 编码避免引号嵌套问题
        replacements = {
            ',': '\uff0c',  # 中文逗号
            '.': '\u3002',  # 中文句号
            '?': '\uff1f',  # 中文问号
            '!': '\uff01',  # 中文叹号
            ':': '\uff1a',  # 中文冒号
            ';': '\uff1b',  # 中文分号
            '(': '\uff08',  # 中文左括号
            ')': '\uff09',  # 中文右括号
        }
        for eng, chn in replacements.items():
            # 只替换独立的英文标点（前后是中文的情况）
            text = re.sub(
                rf'(?<=[\u4e00-\u9fff]){re.escape(eng)}(?=[\u4e00-\u9fff\s])',
                chn,
                text
            )
        return text
    
    def extract_metadata_from_header(self, text: str) -> dict:
        """
        从文本头部提取元数据
        
        尝试识别书名、作者等信息
        """
        metadata = {}
        
        # 取前1000字符分析
        header = text[:1000]
        lines = header.split('\n')
        
        for line in lines[:20]:  # 只看前20行
            line = line.strip()
            if not line:
                continue
                
            # 书名模式
            title_patterns = [
                r'^《(.+?)》',
                r'^书名[：:]\s*(.+)',
                r'^名称[：:]\s*(.+)',
            ]
            for pattern in title_patterns:
                match = re.match(pattern, line)
                if match:
                    metadata['title'] = match.group(1).strip()
                    break
            
            # 作者模式
            author_patterns = [
                r'^作者[：:]\s*(.+)',
                r'^著者[：:]\s*(.+)',
                r'^by[：:\s]+(.+)',
                r'^作\s*者[：:]\s*(.+)',
            ]
            for pattern in author_patterns:
                match = re.match(pattern, line, re.IGNORECASE)
                if match:
                    metadata['author'] = match.group(1).strip()
                    break
            
            # 简介模式
            if '简介' in line or '内容简介' in line or '内容介绍' in line:
                # 下一行可能是简介内容
                idx = lines.index(line)
                if idx + 1 < len(lines):
                    metadata['description'] = lines[idx + 1].strip()
        
        return metadata
