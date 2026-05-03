"""
章节智能切分器

支持多种章节格式识别：
- 中文数字: 第一章、第十二章
- 阿拉伯数字: 第1章、第12章
- 英文格式: Chapter 1、Chapter One
- 结构标题: Act I、Scene 2、Section III、第三幕
- 卷/部识别: 第一卷、第一部、Vol.1
- 特殊章节: 序章、楔子、番外、后记
"""
import re
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

from app.services.book_parser.text_metrics import count_readable_units


class ChapterType(str, Enum):
    """章节类型"""
    NORMAL = "normal"           # 普通章节
    PROLOGUE = "prologue"       # 序章/楔子
    EPILOGUE = "epilogue"       # 尾声/后记
    EXTRA = "extra"             # 番外
    INTERLUDE = "interlude"     # 幕间/间章


class VolumeType(str, Enum):
    """卷类型"""
    VOLUME = "volume"   # 卷
    PART = "part"       # 部
    BOOK = "book"       # 册
    ARC = "arc"         # 篇


@dataclass
class ChapterInfo:
    """章节信息"""
    number: int                         # 章节序号（全书连续编号）
    title: str                          # 章节标题
    content: str                        # 章节内容
    word_count: int                     # 字数
    chapter_type: ChapterType = ChapterType.NORMAL
    
    # 原始匹配信息
    raw_title: str = ""                 # 原始标题行
    original_number: Optional[str] = None  # 原始章节号（如"第一章"）
    
    # 卷/部归属
    volume_number: Optional[int] = None
    volume_title: Optional[str] = None
    part_number: Optional[int] = None
    part_title: Optional[str] = None
    
    # 位置信息
    start_position: int = 0
    end_position: int = 0


@dataclass
class VolumeInfo:
    """卷/部信息"""
    number: int
    title: str
    volume_type: VolumeType
    start_chapter: int
    end_chapter: int = 0
    chapter_count: int = 0


@dataclass
class SplitResult:
    """切分结果"""
    chapters: List[ChapterInfo] = field(default_factory=list)
    volumes: List[VolumeInfo] = field(default_factory=list)
    total_words: int = 0
    total_chapters: int = 0
    total_volumes: int = 0
    has_prologue: bool = False
    has_epilogue: bool = False
    has_extras: bool = False
    warnings: List[str] = field(default_factory=list)


class ChapterSplitter:
    """
    章节智能切分器
    
    能够识别多种章节格式，并自动处理卷/部层级结构
    """
    
    # ==================== 章节匹配模式 ====================
    
    # 中文数字映射
    CN_NUMBERS = {
        '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
        '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
        '十': 10, '百': 100, '千': 1000, '万': 10000,
        '〇': 0, '两': 2,
    }
    
    # 英文数字映射
    EN_NUMBERS = {
        'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
        'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
        'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14,
        'fifteen': 15, 'sixteen': 16, 'seventeen': 17, 'eighteen': 18,
        'nineteen': 19, 'twenty': 20,
    }
    ROMAN_NUMBERS = {
        'i': 1, 'v': 5, 'x': 10, 'l': 50, 'c': 100, 'd': 500, 'm': 1000,
    }
    
    # 章节标题正则模式（按优先级排序）
    CHAPTER_PATTERNS = [
        # 中文格式: 第X章 标题 (支持前缀有Markdown标记或空白)
        (r'^[\*\s#]*第([\u96f6一二三四五六七八九十百千万两\d]+)[章节回][\s：:.]*(.*)$', 'cn_chapter'),
        # 戏剧/论文结构: 第X幕/场/节 标题
        (r'^[\*\s#]*第([\u96f6一二三四五六七八九十百千万两\d]+)[幕场节][\s：:.]*(.*)$', 'cn_structural_chapter'),
        # 阻拉伯数字格式: 第1章 标题
        (r'^[\*\s#]*第(\d+)[章节回][\s：:.]*(.*)$', 'num_chapter'),
        # 英文格式: Chapter 1: Title
        (r'^[\*\s#]*[Cc]hapter\s+(\d+)\s*[：:.]?\s*(.*)$', 'en_chapter'),
        # 英文单词格式: Chapter One
        (r'^[\*\s#]*[Cc]hapter\s+([A-Za-z]+)\s*[：:.]?\s*(.*)$', 'en_word_chapter'),
        # 简写格式: Ch.1 或 Ch 1
        (r'^[\*\s#]*[Cc]h\.?\s*(\d+)\s*[：:.]?\s*(.*)$', 'ch_short'),
        # 戏剧/论文结构: Act I、Scene 2、Section III
        (r'^[\*\s#]*(?:[Aa]ct|[Ss]cene|[Ss]ection)\s+(\d+|[IVXLCDMivxlcdm]+)\s*[：:.]?\s*(.*)$', 'en_structural_chapter'),
        # 罗马数字格式: IV. Title 或 IV: Title
        (r'^[\*\s#]*([IVXLCDMivxlcdm]+)\s*[：:.]\s*(.*)$', 'roman_heading'),
        # 纯数字格式: 1. 标题 或 1、标题
        (r'^[\*\s#]*(\d+)\s*[\.\u3001]\s*(.+)$', 'pure_number'),
        # 括号格式: (1) 标题 或 【1】标题
        (r'^[\*\s#]*[\(（【\[](\d+)[\)）】\]]\s*(.*)$', 'bracket_number'),
    ]
    
    # 特殊章节模式
    SPECIAL_PATTERNS = [
        # 序章/楔子
        (r'^(序章|序|楔子|引子|开篇|前言)\s*[：:.]?\s*(.*)$', ChapterType.PROLOGUE),
        # 尾声/后记
        (r'^(尾声|后记|终章|结语|番末|完结)\s*[：:.]?\s*(.*)$', ChapterType.EPILOGUE),
        # 番外
        (r'^(番外|外传|特别篇|特别章)\s*[\d一二三四五六七八九十]*\s*[：:.]?\s*(.*)$', ChapterType.EXTRA),
        # 幕间
        (r'^(幕间|间章|插曲)\s*[：:.]?\s*(.*)$', ChapterType.INTERLUDE),
    ]
    
    # 卷/部模式
    VOLUME_PATTERNS = [
        # 中文卷: 第X卷 标题
        (r'^第([零一二三四五六七八九十百千万两\d]+)[卷部册篇]\s*[：:.]?\s*(.*)$', VolumeType.VOLUME),
        # 阿拉伯卷: 第1卷 标题
        (r'^第(\d+)[卷部册篇]\s*[：:.]?\s*(.*)$', VolumeType.VOLUME),
        # 英文卷: Volume 1 或 Vol.1
        (r'^[Vv]ol(?:ume)?\.?\s*(\d+)\s*[：:.]?\s*(.*)$', VolumeType.VOLUME),
        # 英文罗马数字卷: Volume IV / Vol.IV
        (r'^[Vv]ol(?:ume)?\.?\s*([IVXLCDMivxlcdm]+)\s*[：:.]?\s*(.*)$', VolumeType.VOLUME),
        # 英文部: Part 1
        (r'^[Pp]art\s+(\d+)\s*[：:.]?\s*(.*)$', VolumeType.PART),
        # 英文罗马数字部: Part IV
        (r'^[Pp]art\s+([IVXLCDMivxlcdm]+)\s*[：:.]?\s*(.*)$', VolumeType.PART),
        # 英文册: Book 1
        (r'^[Bb]ook\s+(\d+)\s*[：:.]?\s*(.*)$', VolumeType.BOOK),
        # 英文罗马数字册: Book IV
        (r'^[Bb]ook\s+([IVXLCDMivxlcdm]+)\s*[：:.]?\s*(.*)$', VolumeType.BOOK),
        # 上中下卷
        (r'^([上中下])[卷部册篇]\s*[：:.]?\s*(.*)$', VolumeType.VOLUME),
    ]

    EXPLICIT_CHAPTER_MARKER_PATTERN = r'^<<CHAPTER_MARKER:(.*?)>>$'
    
    def __init__(self, min_chapter_words: int = 100, max_title_length: int = 100):
        """
        初始化切分器
        
        Args:
            min_chapter_words: 最小章节字数（低于此值可能合并到上一章）
            max_title_length: 最大标题长度（超过此值不视为标题）
        """
        self.min_chapter_words = min_chapter_words
        self.max_title_length = max_title_length
        
        # 编译正则表达式
        self._chapter_patterns = [
            (re.compile(p, re.MULTILINE | re.IGNORECASE), t) 
            for p, t in self.CHAPTER_PATTERNS
        ]
        self._special_patterns = [
            (re.compile(p, re.MULTILINE | re.IGNORECASE), t) 
            for p, t in self.SPECIAL_PATTERNS
        ]
        self._volume_patterns = [
            (re.compile(p, re.MULTILINE | re.IGNORECASE), t) 
            for p, t in self.VOLUME_PATTERNS
        ]
        self._explicit_chapter_marker_pattern = re.compile(
            self.EXPLICIT_CHAPTER_MARKER_PATTERN,
            re.IGNORECASE,
        )
    
    def split(self, text: str) -> SplitResult:
        """
        切分文本为章节
        
        Args:
            text: 清洗后的书籍文本
            
        Returns:
            SplitResult: 切分结果
        """
        result = SplitResult()
        
        # 1. 预处理：按行分割
        lines = text.split('\n')
        
        # 2. 第一遍扫描：识别所有章节和卷标记的位置
        markers = self._scan_markers(lines)
        
        if not markers:
            # 没有识别到章节标记，尝试智能分段
            result.warnings.append("未检测到标准章节格式，将尝试智能分段")
            markers = self._fallback_split(lines)
        
        if not markers:
            # 仍然无法分段，将整个文本作为一章
            result.warnings.append("无法识别章节结构，将整个文本作为单一章节")
            chapter = ChapterInfo(
                number=1,
                title="全文",
                content=text,
                word_count=self._count_words(text),
                raw_title="全文",
                start_position=0,
                end_position=len(text)
            )
            result.chapters.append(chapter)
            result.total_chapters = 1
            result.total_words = chapter.word_count
            return result
        
        # 3. 第二遍扫描：提取章节内容
        chapters = self._extract_chapters(text, lines, markers)
        
        # 4. 处理卷/部归属
        self._assign_volumes(chapters, markers)
        
        # 5. 构建结果
        result.chapters = chapters
        result.total_chapters = len([c for c in chapters if c.chapter_type == ChapterType.NORMAL])
        result.total_words = sum(c.word_count for c in chapters)
        result.has_prologue = any(c.chapter_type == ChapterType.PROLOGUE for c in chapters)
        result.has_epilogue = any(c.chapter_type == ChapterType.EPILOGUE for c in chapters)
        result.has_extras = any(c.chapter_type == ChapterType.EXTRA for c in chapters)
        
        # 提取卷信息
        result.volumes = self._extract_volume_info(markers, chapters)
        result.total_volumes = len(result.volumes)
        
        return result
    
    def _scan_markers(self, lines: List[str]) -> List[Dict[str, Any]]:
        """
        扫描所有章节和卷标记
        
        Returns:
            标记列表，每个标记包含：
            - line_num: 行号
            - type: 'chapter' | 'volume' | 'special'
            - number: 章节/卷号
            - title: 标题
            - raw: 原始行文本
            - chapter_type: ChapterType (仅special类型)
            - volume_type: VolumeType (仅volume类型)
        """
        markers = []
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue

            explicit_marker = self._explicit_chapter_marker_pattern.match(line)
            if explicit_marker:
                chapter_number = len([
                    marker
                    for marker in markers
                    if marker['type'] in ('chapter', 'special')
                ]) + 1
                title = self._clean_title(explicit_marker.group(1).strip())
                markers.append({
                    'line_num': i,
                    'type': 'chapter',
                    'number': chapter_number,
                    'title': title or f"第{chapter_number}章",
                    'raw': title or f"第{chapter_number}章",
                    'pattern_type': 'explicit_marker',
                    'original_number': str(chapter_number),
                })
                continue

            if len(line) > self.max_title_length:
                continue
            
            marker = None
            
            # 检查卷/部标记
            for pattern, vol_type in self._volume_patterns:
                match = pattern.match(line)
                if match:
                    num_str = match.group(1)
                    title = match.group(2).strip() if match.lastindex >= 2 else ""
                    marker = {
                        'line_num': i,
                        'type': 'volume',
                        'number': self._parse_number(num_str),
                        'title': title,
                        'raw': line,
                        'volume_type': vol_type,
                    }
                    break
            
            if marker:
                markers.append(marker)
                continue
            
            # 检查特殊章节
            for pattern, ch_type in self._special_patterns:
                match = pattern.match(line)
                if match:
                    prefix = match.group(1)
                    title = match.group(2).strip() if match.lastindex >= 2 else ""
                    marker = {
                        'line_num': i,
                        'type': 'special',
                        'number': 0,
                        'title': title or prefix,
                        'raw': line,
                        'chapter_type': ch_type,
                    }
                    break
            
            if marker:
                markers.append(marker)
                continue
            
            # 检查普通章节
            for pattern, pat_type in self._chapter_patterns:
                match = pattern.match(line)
                if match:
                    num_str = match.group(1)
                    title = match.group(2).strip() if match.lastindex >= 2 else ""
                    # 清理标题中的Markdown标记
                    title = self._clean_title(title)
                    marker = {
                        'line_num': i,
                        'type': 'chapter',
                        'number': self._parse_number(num_str),
                        'title': title,
                        'raw': line,
                        'pattern_type': pat_type,
                        'original_number': num_str,
                    }
                    break
            
            if marker:
                markers.append(marker)
        
        return markers
    
    def _fallback_split(self, lines: List[str]) -> List[Dict[str, Any]]:
        """
        备用切分策略：基于空行和段落长度
        
        当无法识别标准章节格式时使用
        """
        markers = []
        
        # 查找可能的分隔点（连续空行后的段落）
        blank_count = 0
        chapter_num = 1
        
        for i, line in enumerate(lines):
            if not line.strip():
                blank_count += 1
            else:
                # 连续2个以上空行后的非空行可能是新章节开始
                if blank_count >= 2:
                    line_stripped = line.strip()
                    # 检查是否像标题（较短、无标点结尾）
                    if (len(line_stripped) <= 50 and 
                        not line_stripped.endswith(('。', '！', '？', '.', '!', '?', '，', ','))):
                        markers.append({
                            'line_num': i,
                            'type': 'chapter',
                            'number': chapter_num,
                            'title': line_stripped,
                            'raw': line_stripped,
                            'pattern_type': 'fallback',
                        })
                        chapter_num += 1
                blank_count = 0
        
        # 如果分出太少或太多，可能不准确
        if len(markers) < 2:
            return []
        if len(markers) > 500:  # 可能误识别了太多
            return []
            
        return markers
    
    def _extract_chapters(
        self, 
        text: str, 
        lines: List[str], 
        markers: List[Dict[str, Any]]
    ) -> List[ChapterInfo]:
        """
        提取章节内容
        """
        chapters = []
        
        # 只处理章节和特殊章节标记
        chapter_markers = [m for m in markers if m['type'] in ('chapter', 'special')]
        
        if not chapter_markers:
            return chapters
        
        # 计算每行在原文中的起始位置
        line_positions = [0]
        pos = 0
        for line in lines:
            pos += len(line) + 1  # +1 for newline
            line_positions.append(pos)
        
        # 重新编号（确保连续）
        chapter_num = 0
        
        for i, marker in enumerate(chapter_markers):
            # 确定内容范围
            start_line = marker['line_num'] + 1  # 标题行的下一行开始
            
            if i + 1 < len(chapter_markers):
                # 到下一个章节标记之前
                end_line = chapter_markers[i + 1]['line_num']
            else:
                # 最后一章，到文本结束
                end_line = len(lines)
            
            # 提取内容
            content_lines = lines[start_line:end_line]
            content = '\n'.join(content_lines).strip()
            
            # 跳过空章节
            if not content and marker['type'] != 'special':
                continue
            
            chapter_num += 1
            
            # 确定章节类型
            if marker['type'] == 'special':
                ch_type = marker['chapter_type']
            else:
                ch_type = ChapterType.NORMAL
            
            chapter = ChapterInfo(
                number=chapter_num,
                title=marker['title'] or marker['raw'],
                content=content,
                word_count=self._count_words(content),
                chapter_type=ch_type,
                raw_title=marker['raw'],
                original_number=marker.get('original_number'),
                start_position=line_positions[marker['line_num']],
                end_position=line_positions[end_line] if end_line < len(line_positions) else len(text),
            )
            chapters.append(chapter)
        
        return chapters
    
    def _assign_volumes(
        self, 
        chapters: List[ChapterInfo], 
        markers: List[Dict[str, Any]]
    ):
        """
        为章节分配卷/部归属
        """
        volume_markers = [m for m in markers if m['type'] == 'volume']
        
        if not volume_markers:
            return
        
        # 为每个章节找到其所属的卷
        current_volume = None
        chapter_index = 0
        
        for marker in markers:
            if marker['type'] == 'volume':
                current_volume = {
                    'number': marker['number'],
                    'title': marker['title'],
                    'type': marker['volume_type'],
                }
            elif marker['type'] in ('chapter', 'special'):
                if chapter_index < len(chapters) and current_volume:
                    ch = chapters[chapter_index]
                    if current_volume['type'] in (VolumeType.VOLUME, VolumeType.BOOK, VolumeType.ARC):
                        ch.volume_number = current_volume['number']
                        ch.volume_title = current_volume['title']
                    elif current_volume['type'] == VolumeType.PART:
                        ch.part_number = current_volume['number']
                        ch.part_title = current_volume['title']
                    chapter_index += 1
    
    def _extract_volume_info(
        self, 
        markers: List[Dict[str, Any]], 
        chapters: List[ChapterInfo]
    ) -> List[VolumeInfo]:
        """
        提取卷信息
        """
        volumes = []
        volume_markers = [m for m in markers if m['type'] == 'volume']
        
        for i, vm in enumerate(volume_markers):
            # 找到该卷的起始和结束章节
            start_ch = None
            end_ch = None
            
            for ch in chapters:
                if (ch.volume_number == vm['number'] or 
                    ch.part_number == vm['number']):
                    if start_ch is None:
                        start_ch = ch.number
                    end_ch = ch.number
            
            if start_ch is not None:
                volumes.append(VolumeInfo(
                    number=vm['number'],
                    title=vm['title'],
                    volume_type=vm['volume_type'],
                    start_chapter=start_ch,
                    end_chapter=end_ch or start_ch,
                    chapter_count=(end_ch or start_ch) - start_ch + 1,
                ))
        
        return volumes
    
    def _parse_number(self, num_str: str) -> int:
        """
        解析数字字符串（支持中文和英文数字）
        """
        if not num_str:
            return 0
        
        # 尝试直接转换
        try:
            return int(num_str)
        except ValueError:
            pass
        
        # 上中下转换
        if num_str in ('上', '前'):
            return 1
        if num_str in ('中',):
            return 2
        if num_str in ('下', '后'):
            return 3
        
        # 尝试中文数字
        num_str = num_str.strip()
        if all(c in self.CN_NUMBERS for c in num_str):
            return self._parse_chinese_number(num_str)
        
        roman_number = self._parse_roman_number(num_str)
        if roman_number is not None:
            return roman_number

        # 尝试英文数字
        lower = num_str.lower()
        if lower in self.EN_NUMBERS:
            return self.EN_NUMBERS[lower]
        
        return 0
    
    def _parse_chinese_number(self, cn_str: str) -> int:
        """
        解析中文数字
        
        支持：一、十二、一百二十三、二百、三千五百
        """
        if not cn_str:
            return 0
        
        # 简单情况：单个字符
        if len(cn_str) == 1:
            return self.CN_NUMBERS.get(cn_str, 0)
        
        result = 0
        temp = 0
        
        for char in cn_str:
            num = self.CN_NUMBERS.get(char, 0)
            
            if num >= 10:  # 是单位
                if temp == 0:
                    temp = 1  # "十二" 的情况
                result += temp * num
                temp = 0
            else:
                temp = num
        
        result += temp
        return result

    def _parse_roman_number(self, value: str) -> Optional[int]:
        """
        解析罗马数字章节号。
        """
        token = str(value or "").strip().lower()
        if not token or not re.fullmatch(r"[ivxlcdm]+", token):
            return None

        total = 0
        previous = 0
        for char in reversed(token):
            current = self.ROMAN_NUMBERS.get(char, 0)
            if current < previous:
                total -= current
            else:
                total += current
                previous = current
        return total if total > 0 else None
    
    def _clean_title(self, title: str) -> str:
        """
        清理标题中的Markdown标记和多余字符
        """
        if not title:
            return title
        
        # 移除Markdown标记: ** __ # ~~~
        title = re.sub(r'^[\*#_~\s]+', '', title)
        title = re.sub(r'[\*#_~\s]+$', '', title)
        
        # 移除前后的冒号、空格
        title = title.strip('：:. ')
        
        return title.strip()
    
    def _count_words(self, text: str) -> int:
        """
        统计可朗读文本单位
        """
        return count_readable_units(text)
    
    def analyze_structure(self, text: str) -> Dict[str, Any]:
        """
        分析文本结构（不进行切分）
        
        返回检测到的章节格式信息，用于预览
        """
        lines = text.split('\n')
        markers = self._scan_markers(lines)
        
        # 统计各类型标记
        chapter_count = len([m for m in markers if m['type'] == 'chapter'])
        volume_count = len([m for m in markers if m['type'] == 'volume'])
        special_count = len([m for m in markers if m['type'] == 'special'])
        
        # 检测主要章节格式
        pattern_types = [m.get('pattern_type') for m in markers if m['type'] == 'chapter']
        main_pattern = max(set(pattern_types), key=pattern_types.count) if pattern_types else None
        
        # 采样一些标题
        sample_titles = [m['raw'] for m in markers[:10] if m['type'] in ('chapter', 'special')]
        
        return {
            'detected_chapters': chapter_count,
            'detected_volumes': volume_count,
            'detected_special': special_count,
            'main_pattern': main_pattern,
            'sample_titles': sample_titles,
            'has_structure': chapter_count > 0,
            'estimated_total_words': self._count_words(text),
        }
