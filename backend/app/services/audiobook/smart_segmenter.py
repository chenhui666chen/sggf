"""
智能文本分段工具 - 有声书专用

核心功能：
1. 按语义边界智能分段（段落/句子/短语）
2. TTS-friendly 长度控制（避免过长文本）
3. 保持语义完整性（不断开专有名词）
4. 输出带类型标签的分段结果
"""
import re
import logging
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class SegmentType(str, Enum):
    """分段类型"""
    PARAGRAPH = "paragraph"  # 段落级分段
    SENTENCE = "sentence"    # 句子级分段
    PHRASE = "phrase"        # 短语级分段


@dataclass
class TextSegment:
    """文本分段结果"""
    text: str               # 分段文本
    segment_type: SegmentType  # 分段类型
    index: int              # 在原文中的序号
    original_text: str      # 原始完整文本


class SmartTextSegmenter:
    """
    智能文本分段器
    
    策略：
    1. 第一级：按段落分割（\n\n 或连续换行）
    2. 第二级：段落按句子分割（。！？；）
    3. 第三级：长句子按短语分割（，、：）
    4. 边界检查：不超过 max_length 限制
    """
    
    def __init__(
        self,
        max_segment_length: int = 200,  # 单段最大字符数（TTS 限制）
        min_segment_length: int = 5,    # 单段最小字符数
        enable_paragraph_split: bool = True,  # 是否按段落分割
        enable_sentence_split: bool = True,   # 是否按句子分割
        enable_phrase_split: bool = True,     # 是否按短语分割
    ):
        self.max_segment_length = max_segment_length
        self.min_segment_length = min_segment_length
        self.enable_paragraph_split = enable_paragraph_split
        self.enable_sentence_split = enable_sentence_split
        self.enable_phrase_split = enable_phrase_split

        # 分段正则表达式
        # 段落分隔符：连续换行
        self.paragraph_pattern = re.compile(r'\n\s*\n')
        
        # 句子分隔符：句号、问号、叹号、分号（中英文）
        self.sentence_pattern = re.compile(r'([。！？；.!?;]+)')
        
        # 短语分隔符：逗号、顿号、冒号（中英文）
        self.phrase_pattern = re.compile(r'([，、：,:]+)')
        
        logger.info(
            f"智能文本分段器初始化: max_len={max_segment_length}, "
            f"paragraph={enable_paragraph_split}, "
            f"sentence={enable_sentence_split}, "
            f"phrase={enable_phrase_split}"
        )
    
    def segment(
        self,
        text: str,
        chapter_info: str = "",
    ) -> List[TextSegment]:
        """
        智能分段主入口
        
        Args:
            text: 待分段文本
            chapter_info: 章节信息（用于日志）
        
        Returns:
            TextSegment 列表
        """
        if not text or not text.strip():
            return []
        
        text = text.strip()
        logger.info(
            f"开始分段: {len(text)} 字符, "
            f"章节: {chapter_info or 'N/A'}"
        )
        
        # 第一级：按段落分割
        if self.enable_paragraph_split:
            paragraphs = self._split_paragraphs(text)
        else:
            paragraphs = [text]
        
        # 第二级：每个段落按句子分割
        if self.enable_sentence_split:
            sentences = []
            for para in paragraphs:
                # para 可能是 TextSegment 或 str，统一提取文本
                para_text = para.text if hasattr(para, 'text') else para
                sentences.extend(self._split_sentences(para_text))
        else:
            # 如果跳过分段，提取文本
            sentences = [p.text if hasattr(p, 'text') else p for p in paragraphs]
        
        # 第三级：长句子按短语分割
        if self.enable_phrase_split:
            phrases = []
            for sent in sentences:
                # sent 可能是 TextSegment 或 str，统一提取文本
                sent_text = sent.text if hasattr(sent, 'text') else sent
                phrases.extend(self._split_phrases(sent_text))
        else:
            # 如果跳过短语分割，提取文本
            phrases = [s.text if hasattr(s, 'text') else s for s in sentences]
        
        # 第四级：超长片段继续分割
        final_segments = self._ensure_length_limit(phrases)
        
        # 过滤太短的片段
        final_segments = [
            seg for seg in final_segments
            if len(seg.text.strip()) >= self.min_segment_length
        ]
        
        # 重新编号
        for i, seg in enumerate(final_segments):
            seg.index = i
        
        logger.info(
            f"分段完成: {len(final_segments)} 个片段, "
            f"平均长度: {sum(len(s.text) for s in final_segments) / max(1, len(final_segments)):.1f} 字符"
        )
        
        return final_segments
    
    def _split_paragraphs(self, text: str) -> List[TextSegment]:
        """按段落分割文本"""
        # 清理多余空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        parts = self.paragraph_pattern.split(text)
        segments = []
        for i, part in enumerate(parts):
            part = part.strip()
            if part:
                segments.append(TextSegment(
                    text=part,
                    segment_type=SegmentType.PARAGRAPH,
                    index=i,
                    original_text=text
                ))
        
        logger.debug(f"段落分割: {len(segments)} 个段落")
        return segments
    
    def _split_sentences(self, text: str) -> List[TextSegment]:
        """按句子分割文本"""
        # 使用正则表达式分割，保留分隔符
        parts = self.sentence_pattern.split(text)
        
        # 重新组合句子（文本+标点）
        sentences = []
        current_sentence = ""
        
        for part in parts:
            if self.sentence_pattern.match(part):
                # 这是标点符号，追加到当前句子
                current_sentence += part
                if current_sentence.strip():
                    sentences.append(current_sentence.strip())
                    current_sentence = ""
            else:
                # 这是文本内容
                current_sentence += part
        
        # 处理最后剩余部分
        if current_sentence.strip():
            sentences.append(current_sentence.strip())
        
        # 如果句子太长，尝试用逗号进一步分割
        result = []
        for i, sent in enumerate(sentences):
            if len(sent) > self.max_segment_length:
                # 长句子需要进一步分割
                sub_segments = self._split_long_sentence(sent, i)
                result.extend(sub_segments)
            else:
                result.append(TextSegment(
                    text=sent,
                    segment_type=SegmentType.SENTENCE,
                    index=i,
                    original_text=text
                ))
        
        logger.debug(f"句子分割: {len(result)} 个句子")
        return result
    
    def _split_phrases(self, text: str) -> List[TextSegment]:
        """按短语分割长文本"""
        if len(text) <= self.max_segment_length:
            return [TextSegment(
                text=text,
                segment_type=SegmentType.SENTENCE,
                index=0,
                original_text=text
            )]
        
        # 使用短语分隔符分割
        parts = self.phrase_pattern.split(text)
        
        phrases = []
        current_phrase = ""
        
        for part in parts:
            if self.phrase_pattern.match(part):
                # 标点符号
                current_phrase += part
                if len(current_phrase) > self.max_segment_length:
                    # 当前短语太长，保存并重新开始
                    if current_phrase.strip():
                        phrases.append(current_phrase.strip())
                    current_phrase = ""
            else:
                # 检查添加这部分后是否超长
                if len(current_phrase) + len(part) > self.max_segment_length:
                    if current_phrase.strip():
                        phrases.append(current_phrase.strip())
                    current_phrase = part
                else:
                    current_phrase += part
        
        # 处理最后剩余部分
        if current_phrase.strip():
            phrases.append(current_phrase.strip())
        
        result = []
        for i, phrase in enumerate(phrases):
            result.append(TextSegment(
                text=phrase,
                segment_type=SegmentType.PHRASE,
                index=i,
                original_text=text
            ))
        
        logger.debug(f"短语分割: {len(result)} 个短语")
        return result
    
    def _split_long_sentence(self, sentence: str, base_index: int) -> List[TextSegment]:
        """分割超长句子（使用逗号/顿号等）"""
        # 尝试用逗号分割
        parts = self.phrase_pattern.split(sentence)
        
        segments = []
        current_segment = ""
        seg_idx = 0
        
        for part in parts:
            if len(current_segment) + len(part) > self.max_segment_length:
                if current_segment.strip():
                    segments.append(TextSegment(
                        text=current_segment.strip(),
                        segment_type=SegmentType.SENTENCE,
                        index=base_index + seg_idx,
                        original_text=sentence
                    ))
                    seg_idx += 1
                current_segment = part
            else:
                current_segment += part
        
        if current_segment.strip():
            segments.append(TextSegment(
                text=current_segment.strip(),
                segment_type=SegmentType.SENTENCE,
                index=base_index + seg_idx,
                original_text=sentence
            ))
        
        return segments
    
    def _ensure_length_limit(self, segments: List[TextSegment]) -> List[TextSegment]:
        """确保所有片段不超过最大长度"""
        result = []
        
        for seg in segments:
            if len(seg.text) <= self.max_segment_length:
                result.append(seg)
            else:
                # 强制按固定长度切分（最后手段）
                text = seg.text
                start = 0
                chunk_idx = 0
                while start < len(text):
                    end = start + self.max_segment_length
                    chunk = text[start:end]
                    
                    # 尝试在标点处截断
                    for punct in ['。', '！', '？', '，', '；', '.', '!', '?', ',']:
                        last_punct = chunk.rfind(punct)
                        if last_punct > self.min_segment_length:
                            chunk = chunk[:last_punct + 1]
                            end = start + last_punct + 1
                            break
                    
                    if chunk.strip():
                        result.append(TextSegment(
                            text=chunk.strip(),
                            segment_type=seg.segment_type,
                            index=seg.index + chunk_idx,
                            original_text=seg.original_text
                        ))
                        chunk_idx += 1
                    
                    start = end
        
        return result
    
    def segment_to_dict(self, segments: List[TextSegment]) -> List[Dict[str, Any]]:
        """将 TextSegment 列表转换为字典列表（用于 API 响应）"""
        return [
            {
                "text": seg.text,
                "segment_type": seg.segment_type.value,
                "index": seg.index,
                "length": len(seg.text),
            }
            for seg in segments
        ]
    
    def segment_to_text_with_types(self, segments: List[TextSegment]) -> List[Tuple[str, SegmentType]]:
        """将 TextSegment 列表转换为 (text, type) 元组列表"""
        return [
            (seg.text, seg.segment_type)
            for seg in segments
        ]
