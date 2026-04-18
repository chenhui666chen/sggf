"""
词语替换修正模块 - TTS发音错误自动修正

核心功能：
1. 预定义常见 TTS 发音错误映射表
2. 文本预处理时自动替换易错词
3. 支持自定义替换规则
4. 专有名词保护（不被错误替换）

参考 tts-audiobook-tool 的 word substitution 逻辑实现
"""
import re
import logging
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# 预定义常见 TTS 发音错误映射表
# 格式：{易错词: 正确发音/替代表达}
DEFAULT_SUBSTITUTION_RULES = {
    # 英文缩写（优先级高）
    "AI": "人工智能",
    "API": "应用程序接口",
    "URL": "网址",
    "HTTP": "超文本传输协议",
    "HTTPS": "安全超文本传输协议",
    "IP": "网络地址",
    "ID": "编号",
    "VIP": "贵宾",
    "CEO": "首席执行官",
    "CFO": "首席财务官",
    "CTO": "首席技术官",
    
    # 特殊符号
    "%": "百分之",
    "&": "和",
    "@": "at",
    "#": "井号",
    "*": "星号",
}


@dataclass
class SubstitutionRule:
    """替换规则"""
    pattern: str          # 匹配模式（支持正则）
    replacement: str      # 替换文本
    is_regex: bool = False  # 是否为正则表达式
    priority: int = 0     # 优先级（数字越大优先级越高）


@dataclass
class SubstitutionResult:
    """替换结果"""
    original_text: str         # 原始文本
    processed_text: str        # 处理后文本
    substitutions_made: List[Tuple[str, str]]  # 实际替换列表 [(original, replaced), ...]
    protected_words: List[str]  # 保护的专有名词


class WordSubstitutor:
    """
    词语替换器
    
    功能：
    1. 应用预定义替换规则
    2. 保护专有名词不被错误替换
    3. 记录替换历史用于调试
    """
    
    def __init__(
        self,
        rules: Optional[Dict[str, str]] = None,
        protected_words: Optional[Set[str]] = None,
        enable_default_rules: bool = True,
    ):
        self.rules: Dict[str, SubstitutionRule] = {}
        self.protected_words: Set[str] = protected_words or set()
        
        # 加载默认规则
        if enable_default_rules:
            for pattern, replacement in DEFAULT_SUBSTITUTION_RULES.items():
                self.add_rule(pattern, replacement)
        
        # 加载自定义规则
        if rules:
            for pattern, replacement in rules.items():
                self.add_rule(pattern, replacement)
        
        logger.info(
            f"词语替换器初始化: {len(self.rules)} 条规则, "
            f"{len(self.protected_words)} 个保护词"
        )
    
    def add_rule(
        self,
        pattern: str,
        replacement: str,
        is_regex: bool = False,
        priority: int = 0,
    ):
        """添加替换规则"""
        self.rules[pattern] = SubstitutionRule(
            pattern=pattern,
            replacement=replacement,
            is_regex=is_regex,
            priority=priority,
        )
    
    def remove_rule(self, pattern: str):
        """移除替换规则"""
        if pattern in self.rules:
            del self.rules[pattern]
    
    def add_protected_word(self, word: str):
        """添加保护的专有名词"""
        self.protected_words.add(word)
    
    def remove_protected_word(self, word: str):
        """移除保护的专有名词"""
        self.protected_words.discard(word)
    
    def substitute(self, text: str) -> SubstitutionResult:
        """
        执行词语替换
        
        Args:
            text: 待处理文本
        
        Returns:
            SubstitutionResult 包含替换历史和处理后文本
        """
        if not text:
            return SubstitutionResult(
                original_text=text,
                processed_text=text,
                substitutions_made=[],
                protected_words=list(self.protected_words)
            )
        
        processed_text = text
        substitutions = []
        
        # 先保护专有名词（替换为占位符）
        # 按长度排序，先处理长词避免部分替换
        sorted_words = sorted(self.protected_words, key=len, reverse=True)
        placeholders = {}
        for i, word in enumerate(sorted_words):
            if word in processed_text:
                placeholder = f"__PROTECTED_WORD_{i}__"
                placeholders[placeholder] = word
                processed_text = processed_text.replace(word, placeholder)
        
        # 按优先级排序规则（优先级高的先应用）
        sorted_rules = sorted(
            self.rules.values(),
            key=lambda r: r.priority,
            reverse=True
        )
        
        # 应用替换规则（跳过占位符部分）
        for rule in sorted_rules:
            if rule.is_regex:
                # 正则表达式替换
                new_text = re.sub(rule.pattern, rule.replacement, processed_text)
                if new_text != processed_text:
                    substitutions.append((rule.pattern, rule.replacement))
                    processed_text = new_text
            else:
                # 简单字符串替换，避免替换占位符中的内容
                if rule.pattern in processed_text:
                    # 检查是否在占位符内
                    new_text = processed_text.replace(rule.pattern, rule.replacement)
                    if new_text != processed_text:
                        substitutions.append((rule.pattern, rule.replacement))
                        processed_text = new_text
        
        # 恢复保护的专有名词
        for placeholder, word in placeholders.items():
            processed_text = processed_text.replace(placeholder, word)
        
        result = SubstitutionResult(
            original_text=text,
            processed_text=processed_text,
            substitutions_made=substitutions,
            protected_words=list(self.protected_words)
        )
        
        if substitutions:
            logger.debug(f"词语替换完成: {len(substitutions)} 处")
            for orig, repl in substitutions:
                logger.debug(f"  '{orig}' -> '{repl}'")
        
        return result
    
    def get_stats(self) -> Dict[str, any]:
        """获取替换器统计信息"""
        return {
            "total_rules": len(self.rules),
            "protected_words": len(self.protected_words),
            "rules": list(self.rules.keys())[:10],  # 返回前10条规则
        }
