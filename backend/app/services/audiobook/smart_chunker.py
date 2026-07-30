"""
智能分块服务 - 根据 Token 限制智能分割文本

参考: AI-Audiobook-Maker 的 1800 token 安全模式
功能:
1. 估算文本 Token 数量
2. 超过限制时智能分割（保持语义完整性）
3. 支持段落/句子级别的分割策略
"""
import re
import math
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class TextChunk:
    """文本分块"""
    index: int
    text: str
    estimated_tokens: int
    original_segment_index: Optional[int] = None  # 原始片段索引


class SmartChunker:
    """智能分块器"""

    # 默认配置
    DEFAULT_MAX_TOKENS = 1800  # 安全模式上限
    DEFAULT_MIN_TOKENS = 50    # 最小分块（过短不分割）
    CHINESE_CHAR_TO_TOKEN_RATIO = 1.5  # 中文字符与 token 的比例
    ENGLISH_WORD_TO_TOKEN_RATIO = 1.3  # 英文单词与 token 的比例

    def __init__(
        self,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        min_tokens: int = DEFAULT_MIN_TOKENS,
        chinese_ratio: float = CHINESE_CHAR_TO_TOKEN_RATIO,
        english_ratio: float = ENGLISH_WORD_TO_TOKEN_RATIO,
    ):
        """
        Args:
            max_tokens: 单个分块最大 token 数
            min_tokens: 最小分块 token 数（低于此值不分割）
            chinese_ratio: 中文字符到 token 的转换比例
            english_ratio: 英文单词到 token 的转换比例
        """
        self.max_tokens = max_tokens
        self.min_tokens = min_tokens
        self.chinese_ratio = chinese_ratio
        self.english_ratio = english_ratio

    def estimate_tokens(self, text: str) -> int:
        """
        估算文本的 token 数量

        采用简化的估算策略：
        - 中文字符：每 1.5 个字符约 1 token
        - 英文单词：每 1.3 个单词约 1 token
        - 标点符号和特殊字符：每 3 个约 1 token
        """
        if not text:
            return 0

        # 分离中英文
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]', text))
        english_words = len(re.findall(r'[a-zA-Z]+', text))
        punctuation = len(re.findall(r"[，。！？、；：\"'（）【】《》.,!?;:()\[\]{}]", text))

        # 估算 token 数
        chinese_tokens = math.ceil(chinese_chars / self.chinese_ratio)
        english_tokens = math.ceil(english_words / self.english_ratio)
        punctuation_tokens = math.ceil(punctuation / 3)

        return chinese_tokens + english_tokens + punctuation_tokens

    def needs_chunking(self, text: str) -> bool:
        """判断文本是否需要分块"""
        return self.estimate_tokens(text) > self.max_tokens

    def chunk_text(self, text: str, original_segment_index: Optional[int] = None) -> List[TextChunk]:
        """
        智能分割文本

        策略：
        1. 优先在段落边界分割
        2. 其次在句子边界分割
        3. 最后在短语边界分割
        4. 确保每个分块不超过 max_tokens
        """
        if not self.needs_chunking(text):
            return [TextChunk(
                index=0,
                text=text,
                estimated_tokens=self.estimate_tokens(text),
                original_segment_index=original_segment_index,
            )]

        chunks = []
        remaining_text = text
        chunk_index = 0

        while remaining_text and self.estimate_tokens(remaining_text) > self.max_tokens:
            # 找到最佳分割点
            split_text, remaining_text = self._find_best_split_point(remaining_text)

            if not split_text:
                # 无法再分割，强制截取
                split_text = self._force_split(remaining_text)
                remaining_text = remaining_text[len(split_text):]

            chunk_tokens = self.estimate_tokens(split_text)
            if chunk_tokens >= self.min_tokens or not chunks:
                chunks.append(TextChunk(
                    index=chunk_index,
                    text=split_text.strip(),
                    estimated_tokens=chunk_tokens,
                    original_segment_index=original_segment_index,
                ))
                chunk_index += 1

        # 处理剩余文本
        if remaining_text.strip():
            remaining_tokens = self.estimate_tokens(remaining_text)
            if remaining_tokens >= self.min_tokens or not chunks:
                chunks.append(TextChunk(
                    index=chunk_index,
                    text=remaining_text.strip(),
                    estimated_tokens=remaining_tokens,
                    original_segment_index=original_segment_index,
                ))
            elif chunks:
                # 剩余文本过短，合并到最后一个分块
                chunks[-1].text += " " + remaining_text.strip()
                chunks[-1].estimated_tokens = self.estimate_tokens(chunks[-1].text)

        return chunks

    def chunk_segments(self, segments: List[dict]) -> List[dict]:
        """
        对剧本片段列表进行智能分块

        Args:
            segments: 剧本片段列表

        Returns:
            分块后的片段列表（可能比原始列表长）
        """
        result = []
        current_chunk_text = ""
        current_chunk_tokens = 0
        chunk_segments = []

        for i, segment in enumerate(segments):
            segment_text = segment.get("text", "")
            segment_tokens = self.estimate_tokens(segment_text)

            # 如果当前片段本身就超过限制
            if segment_tokens > self.max_tokens:
                # 先输出已有的分块
                if current_chunk_text:
                    result.append(self._create_chunk_segment(
                        chunk_segments,
                        current_chunk_text,
                        current_chunk_tokens,
                    ))
                    current_chunk_text = ""
                    current_chunk_tokens = 0
                    chunk_segments = []

                # 单独分块该片段
                text_chunks = self.chunk_text(segment_text, original_segment_index=i)
                for chunk in text_chunks:
                    result.append({
                        **segment,
                        "text": chunk.text,
                        "estimated_tokens": chunk.estimated_tokens,
                        "is_chunked": True,
                        "original_segment_index": i,
                        "chunk_index": chunk.index,
                    })

                continue

            # 检查加入当前分块后是否超过限制
            if current_chunk_tokens + segment_tokens > self.max_tokens and current_chunk_text:
                # 输出当前分块
                result.append(self._create_chunk_segment(
                    chunk_segments,
                    current_chunk_text,
                    current_chunk_tokens,
                ))
                current_chunk_text = ""
                current_chunk_tokens = 0
                chunk_segments = []

            # 加入当前分块
            current_chunk_text += segment_text + " "
            current_chunk_tokens += segment_tokens
            chunk_segments.append(segment)

        # 输出最后一个分块
        if current_chunk_text:
            result.append(self._create_chunk_segment(
                chunk_segments,
                current_chunk_text,
                current_chunk_tokens,
            ))

        return result

    def _find_best_split_point(self, text: str) -> Tuple[str, str]:
        """
        找到最佳分割点

        优先级：
        1. 段落边界（双换行）
        2. 句子边界（。！？.!?）
        3. 短语边界（，；,;）
        4. 空格边界
        """
        # 1. 段落边界
        para_match = re.search(r'\n\n', text)
        if para_match:
            pos = para_match.start()
            # 检查分割后两部分是否都在限制内
            first_part = text[:pos]
            remaining = text[pos:]
            if self.estimate_tokens(first_part) <= self.max_tokens:
                return first_part, remaining
            # 否则继续寻找更小的分割点

        # 2. 句子边界
        sentence_patterns = [r'(?<=[。！？\.!?])', r'(?<=[\n\r])']
        for pattern in sentence_patterns:
            matches = list(re.finditer(pattern, text))
            for match in reversed(matches):
                pos = match.end()
                first_part = text[:pos]
                if self.estimate_tokens(first_part) <= self.max_tokens and self.estimate_tokens(first_part) >= self.min_tokens:
                    return first_part, text[pos:]

        # 3. 短语边界
        phrase_match = re.search(r'(?<=[，；,;])', text)
        if phrase_match:
            pos = phrase_match.end()
            first_part = text[:pos]
            if self.estimate_tokens(first_part) <= self.max_tokens and self.estimate_tokens(first_part) >= self.min_tokens:
                return first_part, text[pos:]

        # 4. 空格边界
        space_match = re.search(r'\s+', text[self.max_tokens // 2:])
        if space_match:
            pos = space_match.start() + (self.max_tokens // 2)
            first_part = text[:pos]
            if self.estimate_tokens(first_part) <= self.max_tokens:
                return first_part, text[pos:]

        return "", text

    def _force_split(self, text: str, max_length: int = 500) -> str:
        """强制分割（当找不到合适边界时）"""
        if len(text) <= max_length:
            return text

        # 尝试在接近 max_length 的位置找到标点
        search_start = max_length // 2
        search_end = min(max_length, len(text))

        for i in range(search_end - 1, search_start - 1, -1):
            if text[i] in '，。！？；,.!?;':
                return text[:i + 1]

        return text[:max_length]

    def _create_chunk_segment(self, segments: List[dict], text: str, tokens: int) -> dict:
        """创建分块后的片段"""
        if not segments:
            return {"text": text.strip(), "estimated_tokens": tokens, "type": "narration"}

        # 继承第一个片段的属性
        base_segment = segments[0].copy()
        base_segment["text"] = text.strip()
        base_segment["estimated_tokens"] = tokens
        base_segment["is_chunked"] = True
        base_segment["chunk_segment_count"] = len(segments)

        # 如果有多个片段，标记为混合类型
        if len(segments) > 1:
            types = set(s.get("type", "narration") for s in segments)
            base_segment["mixed_types"] = list(types)

        return base_segment

    def get_chunk_stats(self, chunks: List[TextChunk]) -> dict:
        """获取分块统计信息"""
        if not chunks:
            return {
                "total_chunks": 0,
                "total_tokens": 0,
                "avg_tokens_per_chunk": 0,
                "max_tokens_in_chunk": 0,
                "min_tokens_in_chunk": 0,
            }

        token_counts = [c.estimated_tokens for c in chunks]

        return {
            "total_chunks": len(chunks),
            "total_tokens": sum(token_counts),
            "avg_tokens_per_chunk": sum(token_counts) / len(token_counts),
            "max_tokens_in_chunk": max(token_counts),
            "min_tokens_in_chunk": min(token_counts),
        }
