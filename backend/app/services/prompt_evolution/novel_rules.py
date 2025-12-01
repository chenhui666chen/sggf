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
]

# 过渡词禁用词 - AI特有的逻辑连接词模式
FORBIDDEN_TRANSITION_WORDS = [
    "首先", "其次", "再次", "最后", "此外", "另外", "除此之外",
    "然而", "因此", "于是乎", "与此同时", "话虽如此",
    "毫无疑问", "显而易见", "不言而喻", "值得注意的是",
    "需要指出的是", "综上所述", "总而言之", "总的来说",
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

def preprocess_text(text: str) -> Tuple[str, List[str]]:
    """
    预处理文本，进行确定性的规则替换
    
    Args:
        text: 原始文本
        
    Returns:
        (处理后的文本, 处理日志列表)
    """
    logs = []
    result = text
    
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
    "用身体反应替代情感陈述（如'喉咙发紧'替代'感到悲伤'）",
    "对话中增加语气词和省略（'嗯''啊''呢'）",
    "长句后接1-2个短句制造节奏变化",
    "用具体感官细节替代形容词堆砌",
    "减少'然而''因此'等逻辑连接词",
    "允许适度的'废话'和重复（人类写作特征）",
    "使用'把'字句替代被动句式",
    "适当使用省略号制造停顿感",
    "对话中加入打断和话说一半的情况",
    "用动作细节展示情绪而非直接说明",
]

# 预置无效策略
PRESET_INEFFECTIVE_STRATEGIES = [
    "简单同义词替换（效果有限）",
    "只改标点不改内容",
    "过度口语化导致失去小说感",
    "堆砌破折号和省略号",
    "所有句子都改成短句",
]

# 预置禁止模式
PRESET_FORBIDDEN_PATTERNS = [
    "使用'震惊''深邃''璀璨'等AI高频词",
    "使用'不禁''随即'等AI标志词",
    "直接陈述情感'他感到xxx'",
    "过度使用感叹号",
    "比喻句式连续出现'仿佛...一般'",
    "使用'首先/其次/最后'的三段式结构",
    "每段都以正能量结尾",
    "对话过于礼貌和完整",
    "主角永远冷静不慌乱",
    "所有句子长度相近",
]


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
        return {
            "vocabulary_score": self.vocabulary_score,
            "sentence_score": self.sentence_score,
            "punctuation_score": self.punctuation_score,
            "emotion_score": self.emotion_score,
            "dialogue_score": self.dialogue_score,
            "structure_score": self.structure_score,
            "readability_score": self.readability_score,
            "overall_score": self.overall_score,
            "readability_warnings": self.readability_warnings,
            "details": self.details
        }

    def to_summary(self) -> str:
        warning_mark = "⚠️" if self.readability_warnings else ""
        return (f"词汇:{self.vocabulary_score:.0f} 句式:{self.sentence_score:.0f} "
                f"标点:{self.punctuation_score:.0f} 情感:{self.emotion_score:.0f} "
                f"对话:{self.dialogue_score:.0f} 结构:{self.structure_score:.0f} "
                f"可读性:{self.readability_score:.0f}{warning_mark} "
                f"→ 综合:{self.overall_score:.0f}")


# 🆕 多维评分默认权重（可配置）
# AI检测维度权重（总和0.7）
DEFAULT_SCORE_WEIGHTS = {
    "vocabulary": 0.15,   # 词汇维度
    "sentence": 0.12,     # 句式维度
    "punctuation": 0.15,  # 标点维度
    "emotion": 0.13,      # 情感维度
    "dialogue": 0.10,     # 对话维度
    "structure": 0.05,    # 结构维度
    # 🆕 可读性维度权重（占0.3，作为保护性约束）
    "readability": 0.30   # 可读性维度 - 重要！防止过度优化
}

# 🆕 可读性阈值配置
READABILITY_THRESHOLDS = {
    "min_avg_sentence_length": 5,      # 最小平均句长（太短表示过度碎片化）
    "max_short_sentence_ratio": 0.5,   # 短句比例上限（超过表示过度碎片化）
    "min_content_density": 0.6,        # 最小内容密度（标点太多表示过度优化）
    "max_ellipsis_ratio": 0.15,        # 省略号比例上限
    "min_complete_sentence_ratio": 0.7, # 最小完整句比例
}


def calculate_multi_dimension_score(
    text: str,
    metrics: TextMetrics = None,
    weights: Dict[str, float] = None
) -> MultiDimensionScore:
    """
    🆕 计算文本的多维AI痕迹评分

    评分逻辑：
    - 每个维度 0-100 分，越低表示AI痕迹越少
    - 综合得分是各维度的加权平均

    Args:
        text: 待评估的文本
        metrics: 预计算的指标（可选）
        weights: 各维度权重（可选，默认使用 DEFAULT_SCORE_WEIGHTS）

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

    # 🆕 7. 可读性维度评分（越高越好，与其他维度相反）
    score.readability_score, score.readability_warnings = _calculate_readability_score(text, metrics)
    score.details["readability"] = f"可读性{score.readability_score:.0f}"

    # 计算综合得分（加权平均）
    # 🆕 使用传入的权重或默认权重
    w = weights if weights else DEFAULT_SCORE_WEIGHTS

    # 🆕 AI检测维度得分（越低越好）
    ai_detection_score = (
        score.vocabulary_score * w.get("vocabulary", 0.15) +
        score.sentence_score * w.get("sentence", 0.12) +
        score.punctuation_score * w.get("punctuation", 0.15) +
        score.emotion_score * w.get("emotion", 0.13) +
        score.dialogue_score * w.get("dialogue", 0.10) +
        score.structure_score * w.get("structure", 0.05)
    ) / (1 - w.get("readability", 0.30))  # 归一化到0-100

    # 🆕 可读性惩罚：可读性越低，综合得分越高（越差）
    # 可读性分数反转：100分的可读性 = 0分惩罚，0分可读性 = 100分惩罚
    readability_penalty = (100 - score.readability_score)

    # 综合得分 = AI检测得分 * 0.7 + 可读性惩罚 * 0.3
    readability_weight = w.get("readability", 0.30)
    score.overall_score = (
        ai_detection_score * (1 - readability_weight) +
        readability_penalty * readability_weight
    )

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
