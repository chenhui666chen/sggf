"""
语气词标签解析器 - MiniMax 特有语气词注入

核心功能：
1. 解析/注入 MiniMax 支持的语气词标签
2. 将剧本 performance_notes 映射为合适的语气词
3. 在 TTS 文本中插入语气词
4. 兼容其他模型的降级处理

MiniMax 支持的语气词标签（19种）：
- (laughs) (chuckles) (giggles) (sighs) (gasps)
- (coughs) (clear-throat) (breath) (sniffs) (sneezes)
- (exhales) (inhales) (smacks) (hmm) (uh)
- (ah) (oh) (wow) (oops)
"""
import re
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# MiniMax 支持的语气词标签
MINIMAX_INTERJECTIONS = [
    "(laughs)", "(chuckles)", "(giggles)", "(sighs)", "(gasps)",
    "(coughs)", "(clear-throat)", "(breath)", "(sniffs)", "(sneezes)",
    "(exhales)", "(inhales)", "(smacks)", "(hmm)", "(uh)",
    "(ah)", "(oh)", "(wow)", "(oops)"
]

# performance_notes 到语气词的映射
PERFORMANCE_TO_INTERJECTION = {
    # 笑声相关
    "笑": "(laughs)",
    "轻笑": "(chuckles)",
    "偷笑": "(giggles)",
    "大笑": "(laughs)",
    
    # 叹气相关
    "叹气": "(sighs)",
    "叹息": "(sighs)",
    "深呼吸": "(sighs)",
    
    # 惊讶相关
    "惊讶": "(gasps)",
    "震惊": "(gasps)",
    "倒吸一口凉气": "(gasps)",
    
    # 咳嗽相关
    "咳嗽": "(coughs)",
    "清了清嗓子": "(clear-throat)",
    "清嗓": "(clear-throat)",
    
    # 呼吸相关
    "呼吸": "(breath)",
    "急促呼吸": "(breath)",
    "深吸气": "(inhales)",
    "呼气": "(exhales)",
    
    # 犹豫相关
    "犹豫": "(hmm)",
    "迟疑": "(hmm)",
    "思考": "(hmm)",
    
    # 感叹
    "惊叹": "(wow)",
    "惊喜": "(wow)",
    "惊讶": "(oh)",
}


@dataclass
class InterjectionMatch:
    """语气词匹配结果"""
    interjection: str       # 语气词标签
    position: str           # 插入位置：before | after | middle
    text_segment: str       # 原始文本片段
    confidence: float = 1.0  # 置信度


class InterjectionParser:
    """
    语气词标签解析器
    
    功能：
    1. 从 performance_notes 提取语气词
    2. 在文本中插入语气词标签
    3. 清理/验证语气词标签
    4. 为非 MiniMax 模型提供降级方案
    """
    
    def __init__(self, model: str = "minimax-speech-2.8-hd"):
        self.model = model
        self.supports_interjections = model.startswith("minimax-speech")
        logger.info(
            f"InterjectionParser 初始化: model={model}, "
            f"supports_interjections={self.supports_interjections}"
        )
    
    def parse_performance_notes(self, performance_notes: str) -> List[InterjectionMatch]:
        """
        从 performance_notes 提取语气词
        
        Args:
            performance_notes: 表演提示，如"轻笑着说""叹了口气"
        
        Returns:
            匹配的 Interjection 列表
        """
        if not performance_notes:
            return []
        
        matches = []
        notes_lower = performance_notes.lower()
        
        for keyword, interjection in PERFORMANCE_TO_INTERJECTION.items():
            if keyword in notes_lower or keyword in performance_notes:
                # 根据关键词位置判断插入位置
                position = self._determine_position(keyword, performance_notes)
                matches.append(InterjectionMatch(
                    interjection=interjection,
                    position=position,
                    text_segment=performance_notes,
                    confidence=0.8 if keyword in notes_lower else 0.6
                ))
        
        # 按置信度排序，返回最高置信度的
        if matches:
            matches.sort(key=lambda m: m.confidence, reverse=True)
            return [matches[0]]  # 只返回最佳匹配，避免多个语气词冲突
        
        return []
    
    def inject_interjections(
        self,
        text: str,
        performance_notes: str = "",
        emotion: str = "neutral"
    ) -> str:
        """
        在文本中插入语气词标签
        
        Args:
            text: 原始台词文本
            performance_notes: 表演提示
            emotion: 情感标签
        
        Returns:
            插入语气词后的文本（如果不支持则返回原文本）
        """
        if not self.supports_interjections:
            return text
        
        if not text:
            return text
        
        # 从 performance_notes 提取语气词
        matches = self.parse_performance_notes(performance_notes)
        
        if not matches:
            return text
        
        # 取最佳匹配
        match = matches[0]
        interjection = match.interjection
        position = match.position
        
        # 根据位置插入语气词
        if position == "before":
            return f"{interjection}{text}"
        elif position == "after":
            return f"{text}{interjection}"
        elif position == "middle":
            # 在文本中间插入（通常在标点符号后）
            return self._insert_in_middle(text, interjection)
        
        return text
    
    def extract_existing_interjections(self, text: str) -> Tuple[str, List[str]]:
        """
        从文本中提取已有的语气词标签
        
        Args:
            text: 可能包含语气词的文本
        
        Returns:
            (清理后的文本, 提取的语气词列表)
        """
        found = []
        cleaned = text
        
        for interjection in MINIMAX_INTERJECTIONS:
            if interjection in cleaned:
                found.append(interjection)
                cleaned = cleaned.replace(interjection, "")
        
        return cleaned.strip(), found
    
    def validate_interjection(self, interjection: str) -> bool:
        """验证语气词标签是否有效"""
        return interjection in MINIMAX_INTERJECTIONS
    
    def get_supported_interjections(self) -> List[str]:
        """获取所有支持的语气词标签"""
        return MINIMAX_INTERJECTIONS.copy()
    
    def _determine_position(self, keyword: str, performance_notes: str) -> str:
        """根据关键词确定语气词插入位置"""
        # 如果提示词在开头，语气词在台词前
        if performance_notes.startswith(keyword) or keyword in ["笑", "轻笑", "叹气", "咳嗽", "清嗓"]:
            return "before"
        
        # 如果提示词在结尾，语气词在台词后
        if performance_notes.endswith(keyword):
            return "after"
        
        # 默认在开头
        return "before"
    
    def _insert_in_middle(self, text: str, interjection: str) -> str:
        """在文本中间插入语气词（寻找合适的插入点）"""
        # 优先在标点后插入
        punctuation_positions = []
        for i, char in enumerate(text):
            if char in ['，', ',', '。', '.', '！', '!', '？', '?', '：', ':', '；', ';']:
                punctuation_positions.append(i)
        
        if punctuation_positions:
            # 选择中间位置的标点
            mid_pos = len(punctuation_positions) // 2
            insert_pos = punctuation_positions[mid_pos] + 1
            return text[:insert_pos] + interjection + text[insert_pos:]
        
        # 没有标点，返回原文本
        return text
    
    def get_fallback_performance_note(self, interjection: str) -> str:
        """
        为非 MiniMax 模型生成替代的表演提示
        
        当模型不支持语气词时，用括号标注表演方式
        """
        fallback_map = {
            "(laughs)": "（笑）",
            "(chuckles)": "（轻笑）",
            "(giggles)": "（偷笑）",
            "(sighs)": "（叹气）",
            "(gasps)": "（惊讶）",
            "(coughs)": "（咳嗽）",
            "(clear-throat)": "（清嗓）",
            "(breath)": "（呼吸）",
            "(sniffs)": "（吸鼻）",
            "(sneezes)": "（打喷嚏）",
            "(exhales)": "（呼气）",
            "(inhales)": "（吸气）",
            "(smacks)": "（咂嘴）",
            "(hmm)": "（思考）",
            "(uh)": "（嗯）",
            "(ah)": "（啊）",
            "(oh)": "（哦）",
            "(wow)": "（哇）",
            "(oops)": "（哎呀）",
        }
        return fallback_map.get(interjection, "")
    
    def apply_with_fallback(
        self,
        text: str,
        performance_notes: str = "",
        emotion: str = "neutral"
    ) -> str:
        """
        应用语气词（带降级处理）
        
        如果模型不支持 MiniMax 语气词，使用降级方案：
        - 将语气词转换为括号标注的表演提示
        - 或者完全移除语气词
        """
        if self.supports_interjections:
            return self.inject_interjections(text, performance_notes, emotion)
        else:
            # 降级：提取语气词并替换为中文表演提示
            matches = self.parse_performance_notes(performance_notes)
            if not matches:
                return text
            
            match = matches[0]
            fallback = self.get_fallback_performance_note(match.interjection)
            
            if fallback:
                return f"{fallback}{text}"
            return text
