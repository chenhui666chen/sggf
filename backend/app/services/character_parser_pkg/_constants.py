"""
人物卡解析常量定义
"""
import re

CANONICAL_STORY_STANCES = ("主角方", "反派方", "中立方", "亦正亦邪")
_EXPLICIT_STORY_STANCE_PATTERNS = (
    re.compile(r"(?:\*\*)?【故事立场】(?:\*\*)?[：:]\s*(主角方|反派方|中立方|亦正亦邪)"),
    re.compile(r"故事立场[：:]\s*(主角方|反派方|中立方|亦正亦邪)"),
)
_PRO_STORY_STANCE_PHRASES = (
    "从敌对到生死相托的战友",
    "互不背叛",
    "投资者与引路人",
    "镜像与救赎",
    "功能性伙伴",
    "精神导师",
    "现实导师",
    "核心护卫",
    "信任圈内",
    "向导与组织接口",
    "技术协作者",
    "数据遗产继承者",
    "生死相托",
)
_ANTI_STORY_STANCE_PHRASES = (
    "主要追捕者",
    "武力对抗符号",
    "学术讨伐",
    "天道正义围剿",
    "秩序暴力",
    "污名为",
)
_NEUTRAL_STORY_STANCE_PHRASES = (
    "记忆崩解受害者",
    "旁观者",
    "游离于多方",
)
_AMBIGUOUS_STORY_STANCE_PHRASES = (
    "立场游移",
    "两面下注",
)
