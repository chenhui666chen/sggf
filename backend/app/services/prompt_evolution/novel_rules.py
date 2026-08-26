"""
小说专用规则模块

包含：
1. AI高频词禁用列表
2. 系统性词汇替换规则
3. 预处理/后处理函数
4. 小说类型专用策略
"""
import re
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass, field


# ============================================================================
# 一、AI高频词禁用列表
# ============================================================================

# 情感类禁用词 - AI生成文本中过度使用的华丽词汇
FORBIDDEN_EMOTION_WORDS = [
    "震惊", "深邃", "璀璨", "磅礴", "炽热", "凛冽", "澎湃", "汹涌",
    "恍若", "仿若", "不禁", "随即", "蓦然", "骤然", "霎时", "刹那",
    "无与伦比", "美轮美奂", "叹为观止", "令人窒息", "完美无瑕",
    "心中一凛", "心中一紧", "心中一沉", "心头一震",
    "眼中闪过", "眼眸深邃", "眸光闪烁",
    "宛如", "交织", "宿命感", "倒吸一口凉气", "嘴角勾起一抹",
]

# 过渡词禁用词 - AI特有的逻辑连接词模式
FORBIDDEN_TRANSITION_WORDS = [
    "首先", "其次", "再次", "最后", "此外", "另外", "除此之外",
    "然而", "因此", "于是乎", "与此同时", "话虽如此",
    "毫无疑问", "显而易见", "不言而喻", "值得注意的是",
    "需要指出的是", "综上所述", "总而言之", "总的来说",
    "不可思议的是", "不可否认",
]

# 描写类禁用词 - 过于直白或空洞的形容
FORBIDDEN_DESCRIPTION_WORDS = [
    "美丽的", "漂亮的", "帅气的", "可爱的", "优雅的",
    "强大的", "神秘的", "危险的", "温柔的", "冷酷的",
]

# 合并所有禁用词
ALL_FORBIDDEN_WORDS = (
    FORBIDDEN_EMOTION_WORDS +
    FORBIDDEN_TRANSITION_WORDS +
    FORBIDDEN_DESCRIPTION_WORDS
)


# ============================================================================
# 二、系统性词汇替换规则
# ============================================================================

# 词汇替换映射 - (原词, [替换选项])
WORD_SUBSTITUTION_MAP: Dict[str, List[str]] = {
    # 动词替换
    "不禁": [""],  # 直接删除
    "随即": ["接着", "跟着", ""],
    "然而": ["可", "但", "却", ""],
    "因此": ["所以", ""],
    "此外": ["还有", "另外说", ""],

    # 情感展示替换
    "感到悲伤": ["喉咙发紧", "眼眶发热"],
    "感到愤怒": ["攥紧了拳头", "太阳穴突突直跳"],
    "感到害怕": ["后背发凉", "腿有点软"],
    "感到紧张": ["手心出汗", "心跳加速"],
    "感到开心": ["嘴角压不住地上扬", "眼睛都亮了"],

    # AI高频词替换（保证强制替换后句子仍通顺）
    "宛如": ["像"],
    "交织": ["混杂"],
    "宿命感": ["命中注定的感觉"],
    "倒吸一口凉气": ["喉咙一紧"],
    "嘴角勾起一抹": ["嘴角带着点"],

    # 描写词替换
    "非常": ["很", "挺", ""],
    "十分": ["很", "挺", ""],
    "极其": ["太", "特别", ""],
}

# 句式替换规则 - 用于后处理检查
SENTENCE_PATTERN_FIXES = [
    # (正则模式, 替换为, 说明)
    (r"他感到(\w+)", r"他\1", "去掉'感到'"),
    (r"她感到(\w+)", r"她\1", "去掉'感到'"),
    (r"心中一([凛紧沉震])", r"后背发凉", "替换AI套路"),
    (r"眼中闪过一丝(\w+)", r"", "删除AI套路，需要用动作替代"),
]


# ============================================================================
# 三、预处理函数
# ============================================================================

def _strip_ai_formatting(text: str) -> Tuple[str, List[str]]:
    """
    清除AI输出的格式痕迹（确定性规则，零成本）

    处理以下AI格式特征：
    1. Markdown标记残留（加粗、标题、列表、引用）
    2. 英文半角标点混入中文文本
    3. Unicode特殊字符规范化（em-dash、弯引号）
    4. 多余空格/缩进清理
    5. AI编号列表结构
    """
    logs = []
    result = text

    # 1. 清除 Markdown 标记
    # 加粗
    if "**" in result:
        result = re.sub(r'\*\*(.+?)\*\*', r'\1', result)
        logs.append("清除Markdown加粗")
    if "__" in result:
        result = re.sub(r'__(.+?)__', r'\1', result)
        logs.append("清除Markdown下划线加粗")
    # 斜体（注意不误伤省略号中的星号）
    if re.search(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', result):
        result = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'\1', result)
        logs.append("清除Markdown斜体")
    # 标题（行首 # 开头）
    if re.search(r'^#{1,6}\s+', result, re.MULTILINE):
        result = re.sub(r'^#{1,6}\s+', '', result, flags=re.MULTILINE)
        logs.append("清除Markdown标题")
    # 无序列表（行首 - * + 开头）
    if re.search(r'^\s*[-*+]\s+', result, re.MULTILINE):
        result = re.sub(r'^\s*[-*+]\s+', '', result, flags=re.MULTILINE)
        logs.append("清除Markdown无序列表")
    # 有序列表（行首数字. 开头）
    if re.search(r'^\s*\d+\.\s+', result, re.MULTILINE):
        result = re.sub(r'^\s*\d+\.\s+', '', result, flags=re.MULTILINE)
        logs.append("清除Markdown有序列表")
    # 引用块
    if re.search(r'^>\s?', result, re.MULTILINE):
        result = re.sub(r'^>\s?', '', result, flags=re.MULTILINE)
        logs.append("清除Markdown引用")
    # 行内代码
    if '`' in result:
        result = re.sub(r'`([^`]+)`', r'\1', result)
        logs.append("清除Markdown行内代码")

    # 2. 英文半角标点 → 中文全角（仅当两侧是中文字符时）
    punct_map = {',': '，', '.': '。', ';': '；', ':': '：', '!': '！', '?': '？'}
    for eng, chn in punct_map.items():
        pattern = r'([\u4e00-\u9fa5])' + re.escape(eng) + r'([\u4e00-\u9fa5])'
        if re.search(pattern, result):
            result = re.sub(pattern, r'\1' + chn + r'\2', result)
            logs.append(f"修正半角标点: {eng}→{chn}")

    # 3. Unicode特殊字符规范化
    # 单个 em-dash → 中文破折号
    if '—' in result:
        # 先处理已有的双em-dash（不改）
        # 将单个em-dash转为中文破折号对
        result = re.sub(r'(?<!—)—(?!—)', '——', result)
        # 修正三个以上连续em-dash
        result = re.sub(r'—{3,}', '——', result)
        logs.append("规范化破折号")
    # 弯引号 → 中文引号
    if '\u201c' in result or '\u201d' in result:
        result = result.replace('\u201c', '\u201c').replace('\u201d', '\u201d')
        # 注：\u201c = " \u201d = " 本身就是中文左右双引号，无需替换
        # 但部分场景弯引号可能与直角引号不一致，这里保持原样
    if '\u2018' in result or '\u2019' in result:
        result = result.replace('\u2018', '\u2018').replace('\u2019', '\u2019')

    # 4. 多余空格清理
    # 中文字符间的多余空格（仅水平空白，不吃换行）
    if re.search(r'[\u4e00-\u9fa5][ \t]+[\u4e00-\u9fa5]', result):
        result = re.sub(r'([\u4e00-\u9fa5])[ \t]+([\u4e00-\u9fa5])', r'\1\2', result)
        logs.append("清理中文间空格")
    # 段首过多空格（保留2字符标准缩进）
    if re.search(r'^[ \t]{3,}', result, re.MULTILINE):
        result = re.sub(r'^[ \t]{3,}', '  ', result, flags=re.MULTILINE)
        logs.append("修正段首缩进")

    # 5. AI编号列表结构（中文编号格式）
    # 如：（一）、（二）、（三）或 第一、第二、第三
    if re.search(r'^[（(][一二三四五六七八九十]+[）)][、.]?\s*', result, re.MULTILINE):
        result = re.sub(r'^[（(][一二三四五六七八九十]+[）)][、.]?\s*', '', result, flags=re.MULTILINE)
        logs.append("清除中文编号列表")

    # 6. 清除连续空行（AI倾向双空行分段）
    if '\n\n\n' in result:
        result = re.sub(r'\n{3,}', '\n\n', result)
        logs.append("压缩连续空行")

    return result, logs


def preprocess_text(text: str) -> Tuple[str, List[str]]:
    """
    预处理文本，进行确定性的规则替换

    处理流程：
    1. AI格式特征清洗（Markdown、半角标点、Unicode、空格）
    2. 过度标点修正
    3. AI标志词删除

    Args:
        text: 原始文本

    Returns:
        (处理后的文本, 处理日志列表)
    """
    logs = []
    result = text

    # 0. AI格式特征清洗（新增）
    result, format_logs = _strip_ai_formatting(result)
    logs.extend(format_logs)

    # 1. 处理过度使用的标点
    # 连续3个以上感叹号 -> 1个
    if "!!!" in result:
        result = re.sub(r"!{3,}", "!", result)
        logs.append("修正过多感叹号")

    # 连续3个以上问号 -> 1个
    if "???" in result:
        result = re.sub(r"\?{3,}", "?", result)
        logs.append("修正过多问号")

    # 2. 删除明显的AI标志词
    for word in ["不禁", "随即"]:
        if word in result:
            result = result.replace(word, "")
            logs.append(f"删除AI标志词: {word}")

    return result, logs


# ============================================================================
# 四、后处理函数
# ============================================================================

# 情感直述的替换规则（用于强制替换）
EMOTION_STATEMENT_FIXES = {
    "他感到悲伤": "他喉咙发紧",
    "她感到悲伤": "她眼眶发热",
    "他感到愤怒": "他攥紧了拳头",
    "她感到愤怒": "她咬紧后槽牙",
    "他感到害怕": "他后背发凉",
    "她感到害怕": "她腿有点软",
    "他感到紧张": "他手心出汗",
    "她感到紧张": "她心跳加速",
    "他感到开心": "他嘴角上扬",
    "她感到开心": "她眼睛都亮了",
    "心中一凛": "后背一凉",
    "心中一紧": "胃里一抽",
    "心中一沉": "心往下坠",
    "心头一震": "浑身一激灵",
}

# AI套路句式的替换规则
AI_PATTERN_FIXES = [
    (r"眼中闪过一丝(\w+)", r""),  # 直接删除
    (r"眼眸中闪过(\w+)", r""),
    (r"不禁(\w+)", r"\1"),  # 去掉"不禁"保留后面的词
    (r"随即(\w+)", r"\1"),  # 去掉"随即"
]


def postprocess_text(text: str) -> Tuple[str, List[str]]:
    """
    后处理文本，强制修正残留的AI痕迹

    Args:
        text: LLM改写后的文本

    Returns:
        (处理后的文本, 处理日志列表)
    """
    logs = []
    result = text

    # 1. 强制替换所有禁用过渡词
    for word in FORBIDDEN_TRANSITION_WORDS:
        if word in result:
            replacement = WORD_SUBSTITUTION_MAP.get(word, [""])[0]
            if not replacement:
                # 删除连接词时连同其后的逗号一起清理，避免残留"。，"
                result = result.replace(word + "，", "")
            result = result.replace(word, replacement)
            logs.append(f"强制替换: {word} -> {replacement or '(删除)'}")

    # 2. 强制替换情感直述
    for pattern, replacement in EMOTION_STATEMENT_FIXES.items():
        if pattern in result:
            result = result.replace(pattern, replacement)
            logs.append(f"强制替换情感直述: {pattern} -> {replacement}")

    # 3. 强制替换AI套路句式（正则）
    for pattern, replacement in AI_PATTERN_FIXES:
        matches = re.findall(pattern, result)
        if matches:
            result = re.sub(pattern, replacement, result)
            logs.append(f"强制删除AI套路: {pattern}")

    # 4. 强制替换禁用情感词
    for word in FORBIDDEN_EMOTION_WORDS:
        if word in result:
            # 尝试用替换表，没有就删除
            replacement = WORD_SUBSTITUTION_MAP.get(word, [""])[0]
            result = result.replace(word, replacement)
            logs.append(f"强制替换禁用情感词: {word} -> {replacement or '(删除)'}")

    # 5. 强制替换禁用描写词
    for word in FORBIDDEN_DESCRIPTION_WORDS:
        if word in result:
            result = result.replace(word, "")
            logs.append(f"强制删除禁用描写词: {word}")

    # 6. 🆕 标点优化 - 增加情感标点多样性
    result, punct_logs = _optimize_punctuation(result)
    logs.extend(punct_logs)

    # 7. 检查句子长度分布（仅警告）
    sentences = re.split(r'[。！？]', result)
    lengths = [len(s.strip()) for s in sentences if s.strip()]
    if lengths:
        avg_len = sum(lengths) / len(lengths)
        variance = sum((l - avg_len) ** 2 for l in lengths) / len(lengths)
        if variance < 100:  # 方差过小说明句子长度过于均匀
            logs.append("警告: 句子长度过于均匀，缺乏变化")

    # 🆕 8. 可读性保护检测 - 防止过度优化
    readability_issues = _check_readability_protection(result)
    logs.extend(readability_issues)

    return result, logs


def _check_readability_protection(text: str) -> List[str]:
    """
    🆕 检测文本是否存在过度优化导致的可读性问题

    Returns:
        警告列表
    """
    warnings = []

    if not text:
        return warnings

    # 1. 检测过度碎片化
    sentences = re.split(r'[。！？]', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if sentences:
        avg_len = sum(len(s) for s in sentences) / len(sentences)
        short_count = sum(1 for s in sentences if len(s) < 5)
        short_ratio = short_count / len(sentences)

        if avg_len < 5:
            warnings.append(f"⚠️ 可读性警告: 句子过于碎片化(平均{avg_len:.1f}字)，可能影响阅读流畅度")

        if short_ratio > 0.6:
            warnings.append(f"⚠️ 可读性警告: 短句比例过高({short_ratio:.0%})，文本可能显得支离破碎")

    # 2. 检测省略号过度使用
    ellipsis_count = text.count("……") + text.count("...")
    total_sentences = len(sentences) if sentences else 1
    if ellipsis_count > total_sentences * 0.3:
        warnings.append(f"⚠️ 可读性警告: 省略号过多({ellipsis_count}处)，可能影响表达完整性")

    # 3. 检测内容密度过低
    total_chars = len(text)
    punct_chars = sum(1 for c in text if c in "。，！？、；：""''「」……——")
    if total_chars > 0:
        content_density = 1 - (punct_chars / total_chars)
        if content_density < 0.6:
            warnings.append(f"⚠️ 可读性警告: 标点过密(内容密度{content_density:.0%})，可能过度优化")

    # 4. 检测连续单字句
    single_char_streak = 0
    for s in sentences:
        if len(s) <= 2:
            single_char_streak += 1
            if single_char_streak >= 4:
                warnings.append("⚠️ 可读性警告: 出现连续4个以上超短句，语义可能不连贯")
                break
        else:
            single_char_streak = 0

    return warnings


def _optimize_punctuation(text: str) -> Tuple[str, List[str]]:
    """
    🆕 优化标点符号，增加情感标点多样性

    策略：
    1. 在对话末尾适当添加语气词和标点变化
    2. 在疑问句式后确保使用问号
    3. 在强调句式后添加感叹号
    4. 在犹豫/停顿处添加省略号
    """
    logs = []
    result = text

    # 1. 对话中的问句确保用问号
    # 🆕 更精确的疑问句判断：必须是疑问语气词结尾，或者疑问词在句末附近
    def is_real_question(dialogue: str) -> bool:
        """判断是否为真正的疑问句"""
        dialogue = dialogue.strip()
        if not dialogue:
            return False
        # 结尾语气词疑问
        if dialogue.endswith(("吗", "呢", "吧")):
            return True
        # 疑问词在句末10个字以内（排除"什么都没有"这类用法）
        last_part = dialogue[-10:] if len(dialogue) > 10 else dialogue
        question_words = ["什么", "怎么", "为什么", "哪里", "哪儿", "谁", "几个", "多少", "怎样", "如何"]
        for qw in question_words:
            if qw in last_part:
                # 排除常见的非疑问用法
                non_question_patterns = [
                    f"{qw}都", f"{qw}也", f"不管{qw}", f"无论{qw}", f"任何{qw}"
                ]
                if not any(p in dialogue for p in non_question_patterns):
                    return True
        return False

    # 处理双引号对话
    dialogue_pattern_double = r'"([^"]+)"'
    for match in re.finditer(dialogue_pattern_double, result):
        dialogue = match.group(1)
        if dialogue.endswith("。") and is_real_question(dialogue):
            new_dialogue = dialogue[:-1] + "？"
            result = result.replace(f'"{dialogue}"', f'"{new_dialogue}"')
            logs.append("修正对话问句标点: 。→？")

    # 处理书名号对话
    dialogue_pattern_book = r"「([^」]+)」"
    for match in re.finditer(dialogue_pattern_book, result):
        dialogue = match.group(1)
        if dialogue.endswith("。") and is_real_question(dialogue):
            new_dialogue = dialogue[:-1] + "？"
            result = result.replace(f"「{dialogue}」", f"「{new_dialogue}」")
            logs.append("修正对话问句标点: 。→？")

    # 2. 在"..."或"！"后的句子若只是句号结尾，有概率改为其他标点
    # 这里用启发式规则：连续3个以上句号结尾的句子，中间一个改为省略号
    sentences = result.split("。")
    if len(sentences) >= 4:
        # 检测是否有连续句号主导
        period_count = result.count("。")
        total_end_punct = period_count + result.count("！") + result.count("？")
        if total_end_punct > 0 and period_count / total_end_punct > 0.8:
            # 在中间位置添加省略号
            mid_idx = len(sentences) // 2
            if mid_idx > 0 and mid_idx < len(sentences) - 1:
                # 找一个短句，在其后添加省略号
                for i in range(mid_idx - 1, mid_idx + 2):
                    if 0 < i < len(sentences) - 1 and len(sentences[i].strip()) < 15:
                        sentences[i] = sentences[i].rstrip() + "……"
                        logs.append("添加省略号增加节奏变化")
                        break
        result = "。".join(sentences)

    # 3. 检测并修正对话中过于正式的标点
    # 例如：对话末尾都是句号，应该有更多语气变化
    dialogue_pattern = r'["「]([^"」]+)["」]'
    dialogues = re.findall(dialogue_pattern, result)
    dialogue_end_periods = sum(1 for d in dialogues if d.strip().endswith("。"))
    if len(dialogues) >= 3 and dialogue_end_periods == len(dialogues):
        logs.append("警告: 所有对话都以句号结尾，缺乏语气变化")

    return result, logs


# ============================================================================
# 五、小说类型专用策略
# ============================================================================

@dataclass
class NovelTypeStrategy:
    """小说类型策略"""
    genre: str                          # 类型名称
    style_keywords: List[str]           # 风格关键词
    forbidden_extras: List[str]         # 该类型额外禁用词
    recommended_techniques: List[str]   # 推荐技巧


NOVEL_TYPE_STRATEGIES: Dict[str, NovelTypeStrategy] = {
    "玄幻": NovelTypeStrategy(
        genre="玄幻",
        style_keywords=["江湖", "修炼", "战斗"],
        forbidden_extras=["震惊！", "竟然", "居然", "没想到"],
        recommended_techniques=[
            "战斗描写加入混乱感和疼痛细节",
            "避免主角永远冷静，加入慌乱时刻",
            "对话可以粗犷一些，少用'道''说道'",
        ]
    ),
    "都市": NovelTypeStrategy(
        genre="都市",
        style_keywords=["职场", "生活", "现代"],
        forbidden_extras=["正能量", "相信未来"],
        recommended_techniques=[
            "对话极致口语化，加入网络用语",
            "内心戏用碎片化思维",
            "允许抱怨和负面情绪",
        ]
    ),
    "言情": NovelTypeStrategy(
        genre="言情",
        style_keywords=["爱情", "感情", "浪漫"],
        forbidden_extras=["心动的感觉", "怦然心动", "脸红心跳"],
        recommended_techniques=[
            "用细节传递感情而非直说",
            "对话要有废话和不完整",
            "允许尴尬和冷场",
        ]
    ),
    "悬疑": NovelTypeStrategy(
        genre="悬疑",
        style_keywords=["推理", "案件", "真相"],
        forbidden_extras=["真相只有一个", "原来如此"],
        recommended_techniques=[
            "关键处留白，不必事事说明",
            "节奏张弛有度",
            "允许死胡同和错误推理",
        ]
    ),
}


def get_genre_strategy(genre: str) -> NovelTypeStrategy:
    """获取小说类型策略"""
    return NOVEL_TYPE_STRATEGIES.get(genre, NovelTypeStrategy(
        genre="通用",
        style_keywords=[],
        forbidden_extras=[],
        recommended_techniques=["保持自然的表达"]
    ))


# ============================================================================
# 六、量化指标计算
# ============================================================================

@dataclass
class TextMetrics:
    """文本量化指标"""
    total_chars: int = 0                    # 总字符数
    total_sentences: int = 0                # 总句数

    # 标点统计
    period_count: int = 0                   # 句号数
    exclamation_count: int = 0              # 感叹号数
    question_count: int = 0                 # 问号数
    ellipsis_count: int = 0                 # 省略号数
    dash_count: int = 0                     # 破折号数
    comma_count: int = 0                    # 逗号数

    # 比率
    period_ratio: float = 0.0               # 句号占比
    emotion_punct_ratio: float = 0.0        # 情感标点占比(感叹号+问号)

    # 句式统计
    avg_sentence_length: float = 0.0        # 平均句长
    sentence_length_variance: float = 0.0   # 句长方差
    short_sentence_ratio: float = 0.0       # 短句占比(<10字)

    # 禁用词统计
    forbidden_word_count: int = 0           # 禁用词数量
    forbidden_words_found: List[str] = field(default_factory=list)  # 发现的禁用词

    def to_summary(self) -> str:
        """生成人类可读的摘要"""
        lines = [
            f"标点分布: 句号{self.period_ratio:.0%}, 情感标点{self.emotion_punct_ratio:.0%}",
            f"句式: 平均{self.avg_sentence_length:.1f}字, 方差{self.sentence_length_variance:.1f}, 短句占比{self.short_sentence_ratio:.0%}",
        ]
        if self.forbidden_words_found:
            lines.append(f"残留禁用词: {', '.join(self.forbidden_words_found[:5])}")
        return " | ".join(lines)


def calculate_text_metrics(text: str) -> TextMetrics:
    """
    计算文本的量化指标

    Args:
        text: 待分析的文本

    Returns:
        TextMetrics 对象
    """
    metrics = TextMetrics()

    if not text:
        return metrics

    metrics.total_chars = len(text)

    # 标点统计
    metrics.period_count = text.count("。")
    metrics.exclamation_count = text.count("！") + text.count("!")
    metrics.question_count = text.count("？") + text.count("?")
    metrics.ellipsis_count = text.count("……") + text.count("...")
    metrics.dash_count = text.count("——") + text.count("--")
    metrics.comma_count = text.count("，") + text.count(",")

    # 计算句子结束标点总数
    total_end_puncts = metrics.period_count + metrics.exclamation_count + metrics.question_count
    if total_end_puncts > 0:
        metrics.period_ratio = metrics.period_count / total_end_puncts
        metrics.emotion_punct_ratio = (metrics.exclamation_count + metrics.question_count) / total_end_puncts

    # 句式统计
    sentences = re.split(r'[。！？!?]', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    metrics.total_sentences = len(sentences)

    if sentences:
        lengths = [len(s) for s in sentences]
        metrics.avg_sentence_length = sum(lengths) / len(lengths)
        metrics.sentence_length_variance = sum((l - metrics.avg_sentence_length) ** 2 for l in lengths) / len(lengths)
        metrics.short_sentence_ratio = len([l for l in lengths if l < 10]) / len(lengths)

    # 禁用词统计
    for word in ALL_FORBIDDEN_WORDS:
        if word in text:
            metrics.forbidden_word_count += text.count(word)
            if word not in metrics.forbidden_words_found:
                metrics.forbidden_words_found.append(word)

    return metrics


def compare_metrics(original: TextMetrics, rewritten: TextMetrics) -> str:
    """
    对比原文和改写后的指标变化

    Args:
        original: 原文指标
        rewritten: 改写后指标

    Returns:
        对比摘要字符串
    """
    lines = []

    # 标点变化
    period_change = rewritten.period_ratio - original.period_ratio
    emotion_change = rewritten.emotion_punct_ratio - original.emotion_punct_ratio

    if abs(period_change) > 0.05:
        direction = "↓减少" if period_change < 0 else "↑增加"
        lines.append(f"句号占比{direction}{abs(period_change):.0%}")

    if abs(emotion_change) > 0.05:
        direction = "↑增加" if emotion_change > 0 else "↓减少"
        lines.append(f"情感标点{direction}{abs(emotion_change):.0%}")

    # 句式变化
    variance_change = rewritten.sentence_length_variance - original.sentence_length_variance
    if abs(variance_change) > 50:
        direction = "↑更丰富" if variance_change > 0 else "↓更单一"
        lines.append(f"句式变化{direction}")

    # 禁用词变化
    word_change = rewritten.forbidden_word_count - original.forbidden_word_count
    if word_change != 0:
        direction = "↓减少" if word_change < 0 else "↑增加"
        lines.append(f"禁用词{direction}{abs(word_change)}个")

    return " | ".join(lines) if lines else "指标变化不明显"


# ============================================================================
# 七、预置经验知识
# ============================================================================

# 预置有效策略（从 BypassAIGC 和实践中提取）
PRESET_EFFECTIVE_STRATEGIES = [
    # 朱雀真实 API 实测三优先级杠杆（按降分权重从高到低）
    "禁止新增哲理化、升华式收尾（实测最强升分特征，45字哲理结尾即可拉回低分文本）",
    "在题材语域内做句式口语化：短句节奏、常见动词，不加方言和网络用语",
    "删除不承载事实的套路意象句式，检测器匹配句式统计而非词表，替换词无效",
        "降分依赖全文质地转换：句长分布整体重排、全文节奏统一改变，局部零星修饰对高分文本无效（正反向隔离实验均实证）",
    "参考真人低分文本共性：句长不规则参差、语域自然混搭、表达不完美感、具体私有细节、陌生化比喻、克制收尾，只作方向不作机械模板",
    "叙事类文本优先向高密度对白、短段落、动作推进倾斜（小说叙事基线实测0分的质地特征）",
    "减少连续重复的句法骨架，但按语义自然调整句长，不机械拆句",
    "清理不承载事实的套话、重复解释和空泛总结",
    "减少模板化连接词的连续使用，语义需要时保留正常连接词",
    "使用准确、常见且符合题材语域的词，避免生硬同义替换",
    "保留原文全部专名、数字、事实、设定、因果和否定关系；段落与句子的出场顺序允许调整，但不得删除信息点",
    "对话只在原有人物身份和语气范围内轻度自然化",
    "标点按语义使用，避免单一标点长期主导，也避免刻意堆叠特殊标点",
    "每次只测试少量语言变量，并要求在多个同题材样本上重复验证",
    "改写后篇幅与原文保持一致（偏差不超过20%），只替换表达方式，保留原文全部信息量",
]

# 预置无效策略
PRESET_INEFFECTIVE_STRATEGIES = [
    "简单同义词替换（效果有限）",
    "只改标点不改内容",
    "过度口语化导致失去小说感和文学美感",
    "堆砌破折号和省略号",
    "所有句子都改成短句破坏行文流畅性",
    "机械短句堆砌导致文字干涩失去美感",
    "过度追求口语化牺牲文笔优美",
    "通过改名、改设定或改变叙事视角换取低AI率",
    "添加原文没有的感官、比喻、内心活动、吐槽和无关细节",
    "把偶然在单个样本降分的手法直接升级为强制规则",
    "固定使用身体反应、语气词、短句、省略号形成新的反检测模板",
    "名词、专名、事实类替换（实测对降分零贡献，只损耗保真）",
    "对高分文本只做局部零星修饰（插几句口语、零星删套路句），检测器是全局分布分类器，局部人味化不改变整体分数",
    "对99分深区文本只做单维度改写（口语化/不完美感注入/语域混搭任一单项），反向隔离实验实测分数不动",
    "纯词表排查/审美清单类提示词对高分深区文本降幅为0（外部 skill 基准实验 5 个独立来源证伪：检测器匹配句式统计分布而非词表，词表是最重也最无效的资产，禁止再向词表方向进化）",
]

# 预置禁止模式
PRESET_FORBIDDEN_PATTERNS = [
    "把固定词表中的词一律替换，形成新的模板化词汇模式",
    "连续使用相同的模板词、总结词或空泛修饰语",
    "连续复用相同句法骨架或对称句式",
    "机械使用'首先/其次/最后'等连接结构",
    "所有句子长度相近",
    "用机械拆句或短句堆叠伪造句长变化",
    "保留不承载事实的套话、重复解释和空泛总结",
    "要求破坏叙事逻辑或插入不相关联想",
    "强制修改人物姓名、专名、事实、设定或因果关系",
    "统一把不同题材和人物语言改成现代口语、方言或网络表达",
    "为了降低AI率删除结尾结论、关键线索或具体信息",
    "通过删句、删段或以省略替代原文内容大幅缩短改写篇幅，换取检测器盲区的虚假低分",
]


# ============================================================================
# 七-B、高风险结构句式定位（统计预检 → 定点改写 → 复测闭环）
# ============================================================================
# 来源：外部 skill 基准实验（tmp/skill_bench_report.md 第五/七节）收敛出的
# 四类结构句式盲区 + 段首模板重复。检测器匹配句式统计分布而非词表，
# 对深区文本先定位后定点消除，比无差别全文改写更有效（humanize_mba
# 工程闭环实证）。全部为确定性正则，零 LLM 成本。

HIGH_RISK_PATTERNS: Dict[str, List[str]] = {
    # 二元对比/否定铺垫句式（5 个外部 skill 独立收敛）
    "binary_contrast": [
        r"不是[^。，]{1,12}，而是",
        r"不只是[^。，]{1,16}，更是",
        r"并非[^。，]{1,12}，而是",
        r"与其说是[^。，]{1,12}，不如说是",
    ],
    # 叙述者解释腔/预告腔（上帝视角替读者总结）
    "narrator_explanation": [
        r"[他她它]不知道的是",
        r"殊不知",
        r"这一切只是开始",
        r"而这一切，才刚刚开始",
    ],
    # "通过/基于+名词化"翻译腔骨架
    "nominalization": [
        r"通过[^。，]{2,20}(实现|达成|获得|完成)",
        r"基于[^。，]{2,20}(进行|展开|实现)",
    ],
}

# 公式化对话标签（空壳标签：不承载语气/动作信息）
_DIALOGUE_TAG_PATTERN = re.compile(
    r"说道|问道|笑道|答道|叹道|缓缓开口|沉声开口|轻声开口"
)

# 段首同字连续重复的最小段数阈值
_PARAGRAPH_OPENING_RUN_THRESHOLD = 3

# 对话段开头引号（连续对话/日记体是正常小说结构，不参与段首重复统计）
_DIALOGUE_OPENING_CHARS = "“「『\"'"

HIGH_RISK_TYPE_LABELS: Dict[str, str] = {
    "binary_contrast": "'不是X，而是Y'式二元对比铺垫",
    "narrator_explanation": "叙述者解释腔/预告腔（'他不知道的是…'类）",
    "dialogue_tags": "公式化对话标签密度过高",
    "nominalization": "'通过/基于+名词化'翻译腔骨架",
    "paragraph_opening": "连续段落以相同字词开头",
}


def locate_high_risk_segments(text: str) -> List[Dict[str, Any]]:
    """统计预检：定位文本中的高风险结构句式（确定性正则，零LLM成本）。

    Returns:
        命中列表，每项 {"type": 类型键, "paragraph": 段落序号(1起)}；
        dialogue_tags 为全文级命中，paragraph 为 0。
    """
    if not text or not text.strip():
        return []

    paragraphs = text.split("\n")
    findings: List[Dict[str, Any]] = []

    # 1-3. 段级句式命中（同段同类型去重）
    for idx, para in enumerate(paragraphs, start=1):
        if not para.strip():
            continue
        for type_key, patterns in HIGH_RISK_PATTERNS.items():
            if any(re.search(p, para) for p in patterns):
                findings.append({"type": type_key, "paragraph": idx})

    # 4. 全文级：公式化对话标签密度（标签≥3 且 标签数/对话段数 > 50%）
    dialogue_paras = [p for p in paragraphs if "“" in p or "”" in p]
    if dialogue_paras:
        tag_count = sum(len(_DIALOGUE_TAG_PATTERN.findall(p)) for p in paragraphs)
        if tag_count >= 3 and tag_count / len(dialogue_paras) > 0.5:
            findings.append({"type": "dialogue_tags", "paragraph": 0})

    # 5. 全文级：连续段首同字重复（≥阈值段）。对话段以引号开头是正常
    # 小说结构（连续对白/日记体），既不触发报告也不并入叙述段 run；
    # 但作为 run 断点：被对话隔开的叙述段不算连续
    # （误报取证：suspense_001 三段日记曾被误报并进 hint）
    non_empty = []
    for i, p in enumerate(paragraphs, start=1):
        if not p.strip():
            continue
        first = p.strip()[0]
        non_empty.append((i, None if first in _DIALOGUE_OPENING_CHARS else first))

    run_start = 0
    for pos in range(1, len(non_empty) + 1):
        if pos == len(non_empty) or non_empty[pos][1] != non_empty[run_start][1]:
            run_len = pos - run_start
            if (
                non_empty[run_start][1] is not None
                and run_len >= _PARAGRAPH_OPENING_RUN_THRESHOLD
            ):
                findings.append({"type": "paragraph_opening", "paragraph": non_empty[run_start][0]})
            run_start = pos

    return findings


def build_targeted_rewrite_hint(findings: List[Dict[str, Any]]) -> str:
    """把预检命中渲染为定点消除指令；无命中返回空串（低分样本零污染）。"""
    if not findings:
        return ""
    lines = []
    for f in findings:
        label = HIGH_RISK_TYPE_LABELS.get(f["type"], f["type"])
        pos = f"第{f['paragraph']}段" if f.get("paragraph") else "全文"
        lines.append(f"- {pos}：{label}")
    return (
        "\n\n【定点消除指令】统计预检在以下位置命中高风险结构句式，"
        "请优先对这些位置做定点重构，消除对应句式；未命中的段落"
        "按常规要求处理，不得为凑改动而破坏其信息保真：\n" + "\n".join(lines)
    )


# ============================================================================
# 八、多维评分系统
# ============================================================================

@dataclass
class MultiDimensionScore:
    """多维评分结果"""
    # 各维度得分 (0-100, 越低越好，表示AI痕迹越少)
    vocabulary_score: float = 50.0      # 词汇维度
    sentence_score: float = 50.0        # 句式维度
    punctuation_score: float = 50.0     # 标点维度
    emotion_score: float = 50.0         # 情感维度
    dialogue_score: float = 50.0        # 对话维度
    structure_score: float = 50.0       # 结构维度

    # 🆕 文笔维度 (0-100, 越低越好，表示文笔越优美)
    writing_score: float = 50.0         # 文笔维度

    # 🆕 可读性维度 (0-100, 越高越好，表示可读性越好)
    readability_score: float = 80.0     # 可读性得分

    # 综合得分
    overall_score: float = 50.0

    # 🆕 可读性警告
    readability_warnings: List[str] = None

    # 各维度详情
    details: Dict[str, str] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}
        if self.readability_warnings is None:
            self.readability_warnings = []

    def to_dict(self) -> Dict[str, Any]:
        fidelity_score = getattr(self, "fidelity_score", 50.0)
        return {
            "vocabulary_score": self.vocabulary_score,
            "sentence_score": self.sentence_score,
            "punctuation_score": self.punctuation_score,
            "emotion_score": self.emotion_score,
            "dialogue_score": self.dialogue_score,
            "structure_score": self.structure_score,
            "writing_score": self.writing_score,
            "readability_score": self.readability_score,
            "fidelity_score": fidelity_score,
            "overall_score": self.overall_score,
            # 🔧 新增：composite_score 作为 overall_score 的别名，用于engine.py统一访问
            "composite_score": self.overall_score,
            "readability_warnings": self.readability_warnings,
            "details": self.details
        }

    def to_summary(self) -> str:
        warning_mark = "⚠️" if self.readability_warnings else ""
        # 🆕 添加保真度显示（如果不是默认值50）
        fidelity_display = f" 保真:{self.fidelity_score:.0f}" if self.fidelity_score != 50 else ""
        return (f"词汇:{self.vocabulary_score:.0f} 句式:{self.sentence_score:.0f} "
                f"标点:{self.punctuation_score:.0f} 情感:{self.emotion_score:.0f} "
                f"对话:{self.dialogue_score:.0f} 结构:{self.structure_score:.0f} "
                f"文笔:{self.writing_score:.0f} 可读性:{self.readability_score:.0f}{warning_mark}{fidelity_display} "
                f"→ 综合:{self.overall_score:.0f}")


# 🆕 多维评分默认权重（可配置）
# 🆕 调整后：AI检测维度权重（总和0.40）+ 文笔（0.15）+ 可读性（0.25）+ 保真度（0.20）= 1.0
# 调整理由：
#   1. 降低AI检测权重，避免过度追求低AI率而牺牲内容质量
#   2. 提升可读性权重，更好地保护文本的流畅性和易读性
#   3. 新增保真度维度，优先选择改动最小的效果
#   4. 适度降低文笔权重，为保真度让路u，保持原文风格
DEFAULT_SCORE_WEIGHTS = {
    "vocabulary": 0.08,   # 词汇维度（↓）
    "sentence": 0.07,     # 句式维度（↓）
    "punctuation": 0.08,  # 标点维度（↓）
    "emotion": 0.07,      # 情感维度（↓）
    "dialogue": 0.06,     # 对话维度（↓）
    "structure": 0.04,    # 结构维度（↓）
    # 🔧 文笔维度权重适度降低（0.20→0.15），为保真度让路
    "writing": 0.15,      # 文笔维度 - 保持文学美感
    # 🔧 可读性维度权重适度降低（0.35→0.25），为保真度让路
    "readability": 0.25,  # 可读性维度 - 防止过度优化
    # 🆕 新增：原文保真度维度，优先选择改动最小的版本
    "fidelity": 0.20,     # 保真度维度 - 衡量原文改动大小，越低越好
}

# 🆕 可读性阈值配置
READABILITY_THRESHOLDS = {
    "min_avg_sentence_length": 5,      # 最小平均句长（太短表示过度碎片化）
    "max_short_sentence_ratio": 0.5,   # 短句比例上限（超过表示过度碎片化）
    "min_content_density": 0.6,        # 最小内容密度（标点太多表示过度优化）
    "max_ellipsis_ratio": 0.15,        # 省略号比例上限
    "min_complete_sentence_ratio": 0.7, # 最小完整句比例
}

# 🔧 AI率软性约束配置（非硬性门槛，作为额外加分/扣分项）
# 2026-08-23 黄金对照实验彻底证伪 TMS：GPT人工化金标准(朱雀0%) TMS=97、
# AI文学腔原文 TMS=0、用户手写网文 TMS=92、金庸 TMS=0——TMS 是文风分类器
# (长句文学腔→低分/短句网文腔→高分)，与真实AI痕迹反向。低 TMS 分不再是
# "真人基线"证据（AI原文即得 0 分），全部档位中性化，不再参与任何加减分。
AI_RATE_SOFT_CONSTRAINT = {
    "excellent_threshold": 10,    # 保留键结构兼容，判定已无激励效果
    "good_threshold": 30,         # 保留键结构兼容
    "warning_threshold": 100,     # 已中性化
    "penalty_threshold": 100,     # 已中性化
    "excellent_bonus": 0,         # 已中性化：TMS≤10% 实测恰是 AI 文学腔特征
    "warning_penalty": 0,         # 已中性化
    "penalty_penalty": 0,         # 已中性化
    "severe_penalty": 0,          # 已中性化
}


def calculate_multi_dimension_score(
    text: str,
    metrics: TextMetrics = None,
    weights: Dict[str, float] = None,
    ai_score: float = None  # 🔧 新增：腾讯云API返回的AI检测分数（可选）
) -> MultiDimensionScore:
    """
    🆕 计算文本的多维AI痕迹评分

    评分逻辑：
    - 每个维度 0-100 分，越低表示AI痕迹越少
    - 综合得分是各维度的加权平均
    - 🔧 如果提供ai_score，应用AI率软性约束（加分/扣分）

    Args:
        text: 待评估的文本
        metrics: 预计算的指标（可选）
        weights: 各维度权重（可选，默认使用 DEFAULT_SCORE_WEIGHTS）
        ai_score: 腾讯云API返回的AI检测分数（可选，0-100）

    Returns:
        MultiDimensionScore 对象
    """
    if metrics is None:
        metrics = calculate_text_metrics(text)

    score = MultiDimensionScore()

    # 1. 词汇维度评分
    # 禁用词越多，得分越高（越差）
    vocab_penalty = min(metrics.forbidden_word_count * 10, 50)
    score.vocabulary_score = 30 + vocab_penalty
    score.details["vocabulary"] = f"禁用词{metrics.forbidden_word_count}个"

    # 2. 句式维度评分
    # 句式变化越大（方差越大），得分越低（越好）
    if metrics.sentence_length_variance > 200:
        score.sentence_score = 20  # 变化丰富
    elif metrics.sentence_length_variance > 100:
        score.sentence_score = 40
    elif metrics.sentence_length_variance > 50:
        score.sentence_score = 60
    else:
        score.sentence_score = 80  # 变化单一
    score.details["sentence"] = f"方差{metrics.sentence_length_variance:.0f}"

    # 3. 标点维度评分
    # 句号占比越高，得分越高（越差）
    if metrics.period_ratio > 0.9:
        score.punctuation_score = 90  # 几乎全是句号
    elif metrics.period_ratio > 0.8:
        score.punctuation_score = 70
    elif metrics.period_ratio > 0.6:
        score.punctuation_score = 50
    else:
        score.punctuation_score = 30  # 标点多样
    score.details["punctuation"] = f"句号{metrics.period_ratio:.0%}"

    # 4. 情感维度评分
    # 检测情感表达方式
    emotion_patterns = [
        r"他感到", r"她感到", r"心中", r"内心", r"不禁",
        r"感受到", r"意识到", r"明白了"
    ]
    emotion_direct_count = sum(1 for p in emotion_patterns if re.search(p, text))

    # 身体反应词汇（好的情感表达）
    body_patterns = [
        r"手.*抖", r"心.*跳", r"呼吸", r"喉咙", r"眼眶",
        r"拳头", r"牙关", r"脊背", r"汗"
    ]
    body_count = sum(1 for p in body_patterns if re.search(p, text))

    score.emotion_score = 50 + emotion_direct_count * 10 - body_count * 15
    score.emotion_score = max(10, min(90, score.emotion_score))
    score.details["emotion"] = f"直述{emotion_direct_count}处,身体反应{body_count}处"

    # 5. 对话维度评分
    # 检测对话的口语化程度
    dialogue_pattern = r'["「]([^"」]+)["」]'
    dialogues = re.findall(dialogue_pattern, text)

    if dialogues:
        # 检测语气词
        modal_particles = ["啊", "呢", "吧", "嘛", "呀", "哦", "哎", "唉", "嗯"]
        modal_count = sum(1 for d in dialogues for p in modal_particles if p in d)
        modal_ratio = modal_count / len(dialogues) if dialogues else 0

        if modal_ratio > 0.5:
            score.dialogue_score = 30  # 口语化好
        elif modal_ratio > 0.2:
            score.dialogue_score = 50
        else:
            score.dialogue_score = 70  # 太正式
        score.details["dialogue"] = f"语气词率{modal_ratio:.0%}"
    else:
        score.dialogue_score = 50
        score.details["dialogue"] = "无对话"

    # 6. 结构维度评分
    # 检测段落结构的多样性
    paragraphs = text.split("\n")
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if len(paragraphs) > 1:
        para_lengths = [len(p) for p in paragraphs]
        para_variance = sum((l - sum(para_lengths)/len(para_lengths))**2 for l in para_lengths) / len(para_lengths)

        if para_variance > 1000:
            score.structure_score = 30  # 结构多样
        elif para_variance > 500:
            score.structure_score = 50
        else:
            score.structure_score = 70  # 结构单一
        score.details["structure"] = f"段落方差{para_variance:.0f}"
    else:
        score.structure_score = 50
        score.details["structure"] = "单段落"

    # 🆕 7. 文笔维度评分（越低越好，表示文笔越优美）
    score.writing_score = _calculate_writing_score(text, metrics)
    score.details["writing"] = f"文笔{score.writing_score:.0f}"

    # 🆕 8. 可读性维度评分（越高越好，与其他维度相反）
    score.readability_score, score.readability_warnings = _calculate_readability_score(text, metrics)
    score.details["readability"] = f"可读性{score.readability_score:.0f}"

    # 🆕 9. 原文保真度维度评分（越低越好，表示改动越小）
    # 注意：需要原文才能计算，否则设为中性值50
    score.fidelity_score = 50  # 默认值，表示未提供原文
    score.details["fidelity"] = "未提供原文"

    # 计算综合得分（加权平均）
    # 🆕 使用传入的权重或默认权重
    w = weights if weights else DEFAULT_SCORE_WEIGHTS

    # 🆕 AI检测维度 + 文笔维度 + 保真度维度得分（越低越好）
    # 注意：需要排除readability权重后归一化
    non_readability_weight = 1 - w.get("readability", 0.25)
    ai_writing_fidelity_score = (
        score.vocabulary_score * w.get("vocabulary", 0.08) +
        score.sentence_score * w.get("sentence", 0.07) +
        score.punctuation_score * w.get("punctuation", 0.08) +
        score.emotion_score * w.get("emotion", 0.07) +
        score.dialogue_score * w.get("dialogue", 0.06) +
        score.structure_score * w.get("structure", 0.04) +
        score.writing_score * w.get("writing", 0.15) +
        score.fidelity_score * w.get("fidelity", 0.20)  # 🆕 新增保真度
    ) / non_readability_weight  # 归一化到0-100

    # 🆕 可读性惩罚：可读性越低，综合得分越高（越差）
    # 可读性分数反转：100分的可读性 = 0分惩罚，0分可读性 = 100分惩罚
    readability_penalty = (100 - score.readability_score)

    # 综合得分 = (AI检测+文笔+保真度)得分 * (1-readability_weight) + 可读性惩罚 * readability_weight
    readability_weight = w.get("readability", 0.25)
    base_overall_score = (
        ai_writing_fidelity_score * (1 - readability_weight) +
        readability_penalty * readability_weight
    )

    # 🔧 应用AI率软性约束（如果提供了ai_score）
    ai_adjustment = 0.0
    ai_adjustment_reason = ""
    if ai_score is not None:
        cfg = AI_RATE_SOFT_CONSTRAINT
        if ai_score <= cfg["excellent_threshold"]:
            # 优秀：AI率≤10%，额外加分（降低综合分）
            ai_adjustment = cfg["excellent_bonus"]
            ai_adjustment_reason = f"AI率{ai_score:.0f}%≤{cfg['excellent_threshold']}%，优秀加分{ai_adjustment}"
        elif ai_score <= cfg["good_threshold"]:
            # 良好：AI率≤30%，不调整
            ai_adjustment = 0
            ai_adjustment_reason = f"AI率{ai_score:.0f}%≤{cfg['good_threshold']}%，良好不调整"
        elif ai_score <= cfg["warning_threshold"]:
            # 警告：AI率>30%且≤50%，轻微扣分
            ai_adjustment = cfg["warning_penalty"]
            ai_adjustment_reason = f"AI率{ai_score:.0f}%>{cfg['good_threshold']}%，轻微扣分+{ai_adjustment}"
        elif ai_score <= cfg["penalty_threshold"]:
            # 惩罚：AI率>50%且≤70%，明显扣分
            ai_adjustment = cfg["penalty_penalty"]
            ai_adjustment_reason = f"AI率{ai_score:.0f}%>{cfg['warning_threshold']}%，扣分+{ai_adjustment}"
        else:
            # 严重：AI率>70%，严重扣分
            ai_adjustment = cfg["severe_penalty"]
            ai_adjustment_reason = f"AI率{ai_score:.0f}%>{cfg['penalty_threshold']}%，严重扣分+{ai_adjustment}"

        score.details["ai_rate_adjustment"] = ai_adjustment_reason

    # 最终综合得分 = 基础分 + AI率调整
    score.overall_score = max(0, min(100, base_overall_score + ai_adjustment))

    return score


def _calculate_writing_score(text: str, metrics: TextMetrics) -> float:
    """
    计算文本流畅度评分（重点：顺畅、易懂）

    评分逻辑（0-100，越低越好，表示越顺畅易懂）：
    - 0-30分：非常顺畅易懂 ✨
    - 31-50分：比较顺畅
    - 51-70分：一般，有些卡顿
    - 71-100分：不够顺畅，读起来费劲

    评估维度：
    1. 干涩表达（然后/接着/于是等机械连接词）
    2. 冗余表达（啰嗦、重复）
    3. 句子节奏（长短句搭配是否自然）
    4. 碎片化程度（短句堆砌影响流畅）
    5. 连贯性（有没有合理的过渡）
    6. 晦涩表达（生僻词、复杂句式）
    """
    score = 50.0  # 从中间分数开始

    # 1. 检测干涩表达（机械连接词，影响顺畅）
    dry_patterns = [
        r"然后", r"接着", r"于是", r"之后", r"随后",
        r"进行", r"开始", r"继续", r"完成", r"处理",
        r"因此", r"所以说", r"总之", r"综上"
    ]
    dry_count = sum(1 for p in dry_patterns if re.search(p, text))
    score += min(dry_count * 4, 20)  # 每个+4分，最多+20分

    # 2. 检测冗余/啰嗦表达
    redundant_patterns = [
        r"的话", r"来说的话", r"而言的话",
        r"进行了.*的", r"做出了.*的",
        r"对于.*来说", r"关于.*方面",
        r"基本上", r"一定程度上", r"某种意义上",
        r"实际上.*其实", r"事实上.*实际"
    ]
    redundant_count = sum(1 for p in redundant_patterns if re.search(p, text))
    score += min(redundant_count * 5, 15)  # 每个+5分，最多+15分

    # 3. 检测句子节奏（长短句搭配）
    sentences = re.split(r'[。！？]', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) >= 3:
        lengths = [len(s) for s in sentences]
        # 计算相邻句子长度差异
        length_diffs = [abs(lengths[i+1] - lengths[i]) for i in range(len(lengths)-1)]
        avg_diff = sum(length_diffs) / len(length_diffs) if length_diffs else 0

        # 适度的长度变化读起来更顺（5-15字差异）
        if 5 <= avg_diff <= 15:
            score -= 10  # 节奏自然流畅
        elif avg_diff > 25:
            score += 10  # 变化太剧烈，读起来跳跃
        elif avg_diff < 2:
            score += 8   # 太单调，读起来乏味

    # 4. 检测碎片化程度（短句堆砌影响流畅）
    if metrics.short_sentence_ratio > 0.35:
        excess = metrics.short_sentence_ratio - 0.35
        score += min(excess * 40, 20)  # 短句过多，不顺畅

    # 5. 检测连贯性（自然过渡词是好的）
    smooth_transitions = [
        r"不过", r"只是", r"倒是", r"却", r"但",
        r"虽然", r"尽管", r"即便",
        r"这时", r"此时", r"那时", r"正当",
        r"说着", r"想着", r"看着"
    ]
    transition_count = sum(1 for p in smooth_transitions if re.search(p, text))
    score -= min(transition_count * 2, 10)  # 自然过渡词让文章更顺畅

    # 6. 检测晦涩表达（生僻词、复杂句式影响易懂）
    obscure_patterns = [
        r"之于", r"以至于", r"以致于",
        r"诚然", r"固然", r"虽则",
        r"殊不知", r"岂料", r"孰知",
        r"兹", r"盖因", r"是故"
    ]
    obscure_count = sum(1 for p in obscure_patterns if re.search(p, text))
    score += min(obscure_count * 5, 15)  # 晦涩表达影响易懂

    # 7. 检测过长句子（太长的句子不易懂）
    long_sentences = [s for s in sentences if len(s) > 50]
    if long_sentences:
        score += min(len(long_sentences) * 5, 15)

    # 8. 检测简洁表达（好的特征）
    concise_patterns = [
        r"他说", r"她说", r"我说",  # 简洁对话标记
        r"点头", r"摇头", r"笑了", r"叹了口气"  # 简洁动作
    ]
    concise_count = sum(1 for p in concise_patterns if re.search(p, text))
    score -= min(concise_count * 2, 8)  # 简洁表达是好的

    # 确保分数在0-100范围内
    score = max(0, min(100, score))

    return score


def _calculate_readability_score(text: str, metrics: TextMetrics) -> Tuple[float, List[str]]:
    """
    🆕 计算文本可读性得分

    评分逻辑（0-100，越高越好）：
    - 100分：完美可读性
    - 80-99分：良好可读性
    - 60-79分：一般可读性
    - 40-59分：可读性较差
    - 0-39分：可读性很差，可能过度优化

    Args:
        text: 待评估的文本
        metrics: 文本指标

    Returns:
        (可读性分数, 警告列表)
    """
    warnings = []
    score = 100.0  # 从满分开始扣分

    thresholds = READABILITY_THRESHOLDS

    # 1. 检测句子碎片化程度
    # 平均句长过短表示过度碎片化
    if metrics.avg_sentence_length < thresholds["min_avg_sentence_length"]:
        penalty = (thresholds["min_avg_sentence_length"] - metrics.avg_sentence_length) * 5
        score -= penalty
        warnings.append(f"句子过于碎片化(平均{metrics.avg_sentence_length:.1f}字)")

    # 短句比例过高
    if metrics.short_sentence_ratio > thresholds["max_short_sentence_ratio"]:
        excess = metrics.short_sentence_ratio - thresholds["max_short_sentence_ratio"]
        penalty = excess * 50
        score -= penalty
        warnings.append(f"短句过多({metrics.short_sentence_ratio:.0%})")

    # 2. 检测标点过度使用
    total_chars = len(text)
    if total_chars > 0:
        # 省略号过多
        ellipsis_count = text.count("……") + text.count("...")
        ellipsis_ratio = ellipsis_count * 3 / total_chars  # 每个省略号算3字符
        if ellipsis_ratio > thresholds["max_ellipsis_ratio"]:
            penalty = (ellipsis_ratio - thresholds["max_ellipsis_ratio"]) * 200
            score -= penalty
            warnings.append(f"省略号过多({ellipsis_count}处)")

        # 内容密度检测（非标点字符比例）
        punct_chars = sum(1 for c in text if c in "。，！？、；：""''「」……——")
        content_density = 1 - (punct_chars / total_chars)
        if content_density < thresholds["min_content_density"]:
            penalty = (thresholds["min_content_density"] - content_density) * 100
            score -= penalty
            warnings.append(f"标点过密(内容密度{content_density:.0%})")

    # 3. 检测句子完整性
    sentences = re.split(r'[。！？]', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if sentences:
        # 检测不完整句子（太短且没有主谓结构）
        incomplete_count = 0
        for s in sentences:
            # 小于3个字且不是对话/语气词的句子可能不完整
            if len(s) < 3 and not any(c in s for c in "啊呢吧嘛呀哦嗯"):
                incomplete_count += 1

        complete_ratio = 1 - (incomplete_count / len(sentences))
        if complete_ratio < thresholds["min_complete_sentence_ratio"]:
            penalty = (thresholds["min_complete_sentence_ratio"] - complete_ratio) * 30
            score -= penalty
            warnings.append(f"不完整句子过多({incomplete_count}处)")

    # 4. 检测语义连贯性（简单启发式）
    # 连续出现多个单字句表示过度碎片化
    single_char_streak = 0
    max_streak = 0
    for s in sentences:
        if len(s) <= 2:
            single_char_streak += 1
            max_streak = max(max_streak, single_char_streak)
        else:
            single_char_streak = 0

    if max_streak >= 3:
        penalty = max_streak * 5
        score -= penalty
        warnings.append(f"连续单字句({max_streak}个)")

    # 5. 检测词汇被过度删除
    # 如果文本变得过短（相对于标点数量）
    if total_chars > 0 and metrics.total_sentences > 0:
        chars_per_sentence = total_chars / metrics.total_sentences
        if chars_per_sentence < 8:  # 每句少于8字可能被过度删减
            penalty = (8 - chars_per_sentence) * 3
            score -= penalty
            warnings.append(f"内容可能被过度删减(每句{chars_per_sentence:.1f}字)")

    # 确保分数在0-100范围内
    score = max(0, min(100, score))

    return score, warnings


def _calculate_fidelity_score(original_text: str, rewritten_text: str) -> float:
    """
    🆕 计算原文保真度得分（衡量改写前后的相似度）

    评分逻辑（0-100，越低越好，表示改动越小）：
    - 0-20分：几乎没改动，相似度>80% ✨
    - 21-40分：微调，相似度60-80%
    - 41-60分：中等改动，相似度40-60%
    - 61-80分：大幅改写，相似夦20-40%
    - 81-100分：几乎全部重写，相似度<20%

    评估维度：
    1. 字符级相似度（编辑距离）
    2. 词级相似度（共同词汇比例）
    3. 句子结构相似度
    4. 长度变化程度
    """
    score = 0.0

    # 1. 字符级相似度（简化的编辑距离比例）
    max_len = max(len(original_text), len(rewritten_text))
    if max_len > 0:
        # 计算共同字符数（忽略顺序）
        from collections import Counter
        orig_chars = Counter(original_text)
        rewr_chars = Counter(rewritten_text)
        common_chars = sum((orig_chars & rewr_chars).values())
        char_similarity = common_chars / max_len
        # 相似度越高，分数越低（越好）
        score += (1 - char_similarity) * 30  # 最多30分

    # 2. 词级相似度（分词后比较）
    # 简单分词：按标点和空格切分
    def simple_tokenize(text):
        # 分隔标点和空格，保留有意义的词
        words = re.findall(r'[\w\u4e00-\u9fa5]+', text)
        return [w for w in words if len(w) > 1]  # 过滤单字

    orig_words = set(simple_tokenize(original_text))
    rewr_words = set(simple_tokenize(rewritten_text))

    if orig_words and rewr_words:
        common_words = orig_words & rewr_words
        word_similarity = len(common_words) / max(len(orig_words), len(rewr_words))
        score += (1 - word_similarity) * 35  # 最多35分

    # 3. 句子结构相似度（句数和句长分布）
    orig_sents = [s.strip() for s in re.split(r'[。！？]', original_text) if s.strip()]
    rewr_sents = [s.strip() for s in re.split(r'[。！？]', rewritten_text) if s.strip()]

    sent_count_diff = abs(len(orig_sents) - len(rewr_sents))
    max_sent_count = max(len(orig_sents), len(rewr_sents))
    if max_sent_count > 0:
        sent_count_similarity = 1 - (sent_count_diff / max_sent_count)
        score += (1 - sent_count_similarity) * 20  # 最多20分

    # 4. 长度变化程度
    len_ratio = len(rewritten_text) / len(original_text) if len(original_text) > 0 else 1.0
    len_change = abs(1 - len_ratio)  # 0表示长度不变，1表示差异很大
    score += len_change * 15  # 最多15分

    # 确保分数在0-100范围内
    score = max(0, min(100, score))

    return score
