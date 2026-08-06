"""
提示词进化系统 - 元优化器（增强版）

让LLM分析提示词效果并生成改进版本
包含成功/失败经验总结、策略追踪和趋势分析
"""
import re
import logging
import copy
from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass, field

from core.unified_llm_client import get_llm_client
from core.model_resolution import TaskType

from .models import PromptVersion, EvaluationResult
from .novel_rules import (
    PRESET_EFFECTIVE_STRATEGIES,
    PRESET_INEFFECTIVE_STRATEGIES,
    PRESET_FORBIDDEN_PATTERNS,
)
from .experience_optimizer import get_experience_optimizer, ExperienceItem

logger = logging.getLogger(__name__)


@dataclass
class ExperienceRecord:
    """经验记录"""
    effective_strategies: List[str] = field(default_factory=list)    # 有效策略
    ineffective_strategies: List[str] = field(default_factory=list)  # 无效策略
    forbidden_patterns: List[str] = field(default_factory=list)      # 需避免的模式
    best_practices: List[str] = field(default_factory=list)          # 最佳实践
    # 🆕 方向性洞察：战略级方向判断（跨批次软引导，区别于原子策略）
    strategic_insights: List[str] = field(default_factory=list)
    # 🔧 新增：权重配置和阈值参数
    weight_config: Optional[Dict] = None                             # 评分权重配置
    threshold_config: Optional[Dict] = None                          # 阈值参数配置
    genre: Optional[str] = None                                      # 适用题材


# 初始提示词模板（小说专用版）
_REMOVED_LEGACY_INITIAL_PROMPT = """你是一位资深网文作者，擅长将文字改写得更具"人味"，同时保持文笔优美流畅，尽量降低AI生成痕迹。

# 核心任务
将输入的小说片段进行深度改写，保持故事内容不变，同时：
1. 让文字风格更像真人写作
2. 确保文笔优美、行文流畅、富有文学美感

# 改写七维策略

## 1. 词汇层 - 去AI化
【禁用词】震惊、深邃、璀璨、磅礴、不禁、随即、然而、因此、此外
【禁用词】首先、其次、再次、最后、综上所述、值得注意的是
【禁用词】宛如、交织、宿命感、倒吸一口凉气、嘴角勾起一抹弧度、不可思议的是、不可否认
【替换规则】
- "他感到悲伤" → 用身体反应表现（喉咙发紧、眼眶发热、鼻子发酸）
- "她很愤怒" → 攥紧拳头、太阳穴突突跳、咬紧后槽牙
- "非常/十分/极其" → 删除或换成"很/挺/太"
【原则】用简单词替代华丽词，用具体词替代抽象词

## 2. 句式层 - 打破均匀
- 长句后必须接1-2个短句，制造节奏变化
- 适当使用碎片句、省略句、倒装句
- 减少"主语+谓语+宾语"的工整结构
- 允许不完整的句子。像这样。就一两个字。
【示例】
原文："他站在那里，看着远方的山峰，陷入了沉思"
改写："他站着。远处的山，灰蒙蒙一片。"

## 3. 情感层 - 展示而非说明（最重要！）
【绝对禁止】直接写"他很生气"、"她感到害怕"、"心中一凛"
【必须要求】用动作、表情、身体反应、环境感知来展示情感
【示例】
原文："他非常愤怒"
改写："他攥紧拳头，指节咔咔作响。"

原文："她心中一紧"
改写："她后背一凉，汗毛都竖起来了。"

## 4. 对话层 - 极致口语化
- 加入语气词：嗯、啊、哦、呢、吧、呗、嘛、啥
- 加入口语省略："你干嘛去？" "买菜。"
- 允许打断、重复、话说一半
- 对话不必每句都完整，可以有"废话"
【示例】
原文："我认为这件事情需要仔细考虑"
改写："这事儿……得琢磨琢磨。"

原文："你为什么要这样做？"
改写："你……你咋想的啊？"

## 5. 描写层 - 感官细节
【禁止】堆砌形容词（美丽的、漂亮的、强大的、神秘的）
【要求】用1-2个具体感官细节替代
【示例】
原文："她有一双美丽的眼睛"
改写："她眨眼的时候，睫毛会在脸颊上投下一小片阴影。"

原文："他的剑很锋利"
改写："剑刃上还沾着血，在月光下泛着冷光。"

## 6. 结构层 - 制造不完美
- 适当加入"废话"和口水话（人类写作的自然特征）
- 允许轻微的啰嗦和重复
- 在关键处留白，不必事事说明
- 段落长度可以参差不齐

## 7. 文笔层 - 顺畅易懂（核心！）
【总原则】在降低AI痕迹的同时，必须保持行文顺畅、表意清晰
【顺畅要求】
- 句子之间衔接自然，避免生硬跳跃
- 长短句搭配得当，读起来不卡顿
- 避免机械连接词堆砌（然后、接着、于是）
【易懂要求】
- 用词简洁明了，不用生僻词
- 句子不要太长太绕，一读就懂
- 避免冗余啰嗦的表达
【节奏要求】
- 适度变化句子长度，避免单调
- 不要全是短句（碎片化），也不要全是长句（费劲）
- 自然的过渡词让文章更连贯
【示例】
原文："然后他进行了思考。之后他开始继续处理这件事。"
改写："他想了想，继续忙手上的事。"

原文："对于这件事情来说的话，实际上基本上是没有问题的。"
改写："这事没问题。"

原文："他。站着。看着她。不说话。"
改写："他站在那儿看着她，一言不发。"

# 标点符号优化
1. 减少句号的主导，增加节奏感
2. 对话中多用逗号制造停顿
3. 用省略号表示犹豫或停顿："我其实……算了。"
4. 用破折号插入补充想法
5. 避免连续使用感叹号

# 绝对禁止
1. 不得改变故事情节和人物关系
2. 不得添加原文没有的重要信息
3. 不得使用禁用词列表中的词汇
4. 不得输出任何解释、注释或标签
5. 不得使用"眼中闪过一丝xxx"这类AI套路
6. 不得让主角永远冷静，适当加入慌乱
7. 不得使用"在这片XX的大陆上"这类模板化开篇句，改用具体场景切入

# 完整改写示例

【示例1：情感展示】
原文：他非常愤怒，感到心中一阵火热。然而，他知道此刻不是发火的时候。
改写：他攥紧拳头，指节咔咔作响。不是时候……还不是时候。

【示例2：对话口语化】
原文："我认为我们应该仔细考虑这个问题，毕竟这关系到很多人的利益。"
改写："这事儿……得好好琢磨。牵扯太多人了。"

【示例3：句式碎片化】
原文：夜晚的城市非常安静，街道上几乎看不到行人，只有路灯发出微弱的光芒。
改写：城市睡了。街上没人。路灯亮着，光很弱。

【示例4：感官细节】
原文：她有一双美丽的大眼睛，看起来非常动人。
改写：她眨眼的时候，睫毛会在脸颊上投一小片阴影。

【示例5：标点革命】
原文：他看着眼前的景象，感到非常震惊。这怎么可能？他无法相信自己的眼睛。
改写：他愣住了。这……怎么可能？不对，一定是看错了——他揉了揉眼睛。

# 输出要求
只输出改写后的文本，保持原文段落结构，不要任何解释。"""


# 增强版元优化提示词
META_OPTIMIZER_PROMPT = """你是一个提示词优化专家。你的任务是深入分析"降低AI痕迹"提示词的效果，总结成功和失败经验，并生成改进版本。

【当前提示词】
{current_prompt}

【测试结果概览】
- 平均AI检测得分: {avg_score}/100 (目标: ≤{target_score})
- 成功样本: {success_count}/{total_count}
- 平均降分幅度: {avg_reduction}分

═══════════════════════════════════════
【成功样本分析】- 降分效果好的案例
═══════════════════════════════════════
{success_analysis}

═══════════════════════════════════════
【失败样本分析】- 降分效果差或失败的案例
═══════════════════════════════════════
{failure_analysis}

═══════════════════════════════════════
【历史迭代趋势】
═══════════════════════════════════════
{trend_analysis}

═══════════════════════════════════════
【累积经验库】
═══════════════════════════════════════
{experience_summary}

═══════════════════════════════════════
【历史分析对比】
═══════════════════════════════════════
{previous_analysis_summary}

**重要要求**：以数据重复验证为准，不为追求新颖而强行发明新结论。
- 已在多个同题材样本稳定复现的结论可以重复确认
- 单个样本的偶然降分不得直接归纳为通用策略
- 智能评审为medium/high风险或任一质量硬门槛失败的样本不得作为成功依据

═══════════════════════════════════════
【AI检测核心原理】（优化参考）
═══════════════════════════════════════
AI检测器通过多维度"指纹"识别AI文本，需要综合优化：

1. **标点符号模式**
   - AI文本句号使用过多，节奏单一
   - AI很少使用问号、感叹号、破折号、省略号

2. **句式结构均匀**
   - AI句子长度相似，缺乏长短变化
   - AI喜欢"主句+逗号+从句+句号"的固定模式
   - 只在语义和语法允许时调整句长与句法，不能刻意制造碎片、倒装或省略

3. **词汇选择**
   - 检查高频模板词、空泛修饰和重复搭配
   - 保持题材语域和人物身份，不把书面语机械改成口语或方言
   - 优先准确表达，不进行固定词表的一对一替换

4. **过渡词模式化**
   - "首先/其次/此外/然而/因此"是AI标志词
   - 仅减少不承载逻辑的机械过渡，不统一替换成口语连接词

5. **情感表达**
   - 检查情感表达是否重复使用固定模板
   - 不得新增原文没有的情绪、身体反应、主观判断或个人偏好

6. **叙述视角**
   - 必须保持原文叙述视角、信息边界和认知范围
   - 不得通过换视角、增加盲点或主观评论来制造所谓真人感

═══════════════════════════════════════
【小说专用六维检测】（核心分析维度）
═══════════════════════════════════════

请从以下六个维度分析改写效果：

1. **词汇层**：
   - 是否还有禁用词（震惊/深邃/璀璨/不禁/随即）？
   - 是否用简单词替代了华丽词？
   - 是否用具体词替代了抽象词？

2. **句式层**：
   - 句子长度是否有变化（长短交替）？
   - 是否减少了连续同构句，同时保持语法和语义完整？
   - 句法调整是否自然，而非机械打破正常结构？

3. **情感层**（最重要！）：
   - 是否减少了重复套用的情感表达模板？
   - 是否保留原文已有的情绪、动作和主观信息？
   - 是否避免用固定身体反应替换原文情感陈述？

4. **对话层**：
   - 对话是否符合人物身份和原文语域？
   - 是否避免统一添加语气词、方言、打断或省略？
   - 是否完整保留说话者、事实信息和态度？

5. **描写层**：
   - 是否还在堆砌形容词？
   - 是否用感官细节替代了抽象描写？
   - 比喻是否过于华丽或连续出现？

6. **结构层**：
   - 是否还有"首先/其次/最后"的三段式？
   - 是否减少段落模板循环，同时保持原有段落功能？
   - 是否清理不承载信息的套话，而非主动增加废话或留白？

7. **🆕 文笔层**（顺畅易懂维度）：
   - 读起来是否顺畅？有没有卡顿的地方？
   - 表意是否清晰？能否一读就懂？
   - 是否避免了机械连接词（然后/接着/于是/之后）？
   - 是否避免了冗余啰嗦的表达？
   - 句子长度变化是否自然？不会太单调？
   - 有没有过长难懂的句子？
   - ⚠️ 警惕：不要为降AI而牺牲顺畅度！

8. **🆕 可读性层**（重要保护维度）：
   - 句子是否过于碎片化？平均句长是否低于5字？
   - 短句比例是否超过50%？
   - 省略号、破折号是否过度使用？
   - 文本是否仍然流畅可读？
   - 语义是否完整连贯？

═══════════════════════════════════════
【⚠️ 可读性保护原则】（必须遵守！）
═══════════════════════════════════════

**核心原则：降低AI检测分数不能以牺牲可读性为代价！**

以下是过度优化的警示信号：
1. 平均句长低于5个字 → 过度碎片化
2. 短句比例超过50% → 表达支离破碎
3. 省略号超过句子总数的30% → 标点滥用
4. 连续出现3个以上单字句 → 语义断裂
5. 内容密度低于60% → 标点过密

**改写时必须保证**：
- 故事情节仍然流畅
- 情感传达仍然到位
- 读者能够顺畅阅读
- 不会有"机器翻译"感

═══════════════════════════════════════
【深度分析任务】
═══════════════════════════════════════

请完成以下分析：

1. **八维分析**（六维AI痕迹 + 文笔 + 可读性）：
   - 逐一检查上述八个维度的改写效果
   - 标注每个维度的得分（1-5分）
   - 🆕 特别关注文笔是否优美、可读性是否受损

2. **成功经验总结**：
   - 成功样本中，哪些改写策略生效了？
   - 是哪个维度的改造贡献最大？
   - 🆕 文笔和可读性是否保持良好？

3. **失败原因诊断**：
   - 失败样本为什么效果不好？
   - 改写后仍保留了哪些AI痕迹特征？
   - 🆕 是否存在过度优化导致文笔干涩或可读性下降？

4. **策略有效性判断**：
   - 当前提示词中哪些指令是有效的（应保留）？
   - 哪些指令是无效的（应删除或修改）？
   - 🆕 哪些指令可能导致过度优化或牺牲文笔？

5. **趋势判断**：
   - 得分是否在收敛？还是在震荡？
   - 需要大改还是微调？
   - 🆕 文笔和可读性趋势如何？是否在下降？

【输出格式】
请严格按以下格式输出：

===EFFECTIVE_STRATEGIES===
[列出本次有效的策略，每行一条]
===EFFECTIVE_STRATEGIES_END===

===INEFFECTIVE_STRATEGIES===
[列出本次无效的策略，每行一条]
===INEFFECTIVE_STRATEGIES_END===

===FORBIDDEN_PATTERNS===
[列出应避免的AI痕迹模式，每行一条]
===FORBIDDEN_PATTERNS_END===

===ANALYSIS===
[综合分析，150字以内，包含成功原因、失败原因、改进方向]
===ANALYSIS_END===

===STRATEGIC_INSIGHT===
[可选：仅当发现"方向级"的战略判断时输出（如"应从拆碎句子转向重构信息流"这类整体方向结论），每行一条，最多2条，50字以内。没有则留空]
===STRATEGIC_INSIGHT_END===

===IMPROVED_PROMPT===
[改进后的完整提示词，要求：
1. 保留有效策略
2. 修正或删除无效策略
3. 增加针对失败样本问题的新指令
4. 包含具体的禁用词汇/句式列表
5. 标点只能按语义和语法自然调整，不得强制增加问号、感叹号、破折号或省略号
6. 必须包含专名、事实、设定、事件顺序、因果、否定关系和题材语域保护]
===IMPROVED_PROMPT_END==="""


SAFE_INITIAL_PROMPT = """你是一位严谨的中文小说文字编辑。请在不改变内容事实的前提下，降低文本中可能被AI检测器识别的机械生成特征。

# 第一优先级：内容不可变
- 不得改变人物姓名、称谓、身份、关系和说话者。
- 不得改变地点、时间、数量、物品名、功法名、境界名和世界观设定。
- 不得改变事件顺序、因果关系、肯定否定、人物动机和情绪方向。
- 不得删除关键情节、线索、动作、结论，也不得补写原文没有的事实、比喻、感官和内心活动。
- 原文没有对话时不要新增对话；原文没有心理活动时不要新增心理活动。

# 优化方向：只处理语言表达
1. 避免句长和句式高度均匀，但句长变化必须服从原文语义和阅读节奏，不机械拆句。
2. 减少模板化连接词、总结词和连续同构句式；语义需要时可以保留正常连接词。
3. 删除不承载信息的套话、重复解释和空泛形容，不得删除具体事实。
4. 优先使用准确、常见、符合题材语域的词，避免生硬同义替换和固定“去AI词库”替换。
5. 对话只做符合人物身份的轻度自然化，不统一添加语气词、方言、现代网络用语或废话。
6. 标点按语义正常使用，不为制造随机性而堆叠短句、省略号、破折号、问号或感叹号。
7. 保持原叙事视角、语气、段落功能和题材风格，不把严肃文本改成吐槽或段子。

# 输出前自检
- 逐项核对专名、数字、否定词、事件顺序、因果和结尾结论。
- 若某处改写可能改变含义，保留原句或只做最小修改。
- 只输出改写后的正文，不输出标题、说明、标签、分析或Markdown。
"""

SAFE_GENRE_ADDONS = {
    "玄幻": """# 玄幻题材约束
- 完整保留人物、宗门、法宝、武器、妖兽、功法、境界和招式名称。
- 不把古典或严肃语域统一改成现代口语，不新增吐槽和生活化类比。
- 可减少空泛威势总结，但不能改写战斗动作、修炼结果和力量关系。""",
    "都市": """# 都市题材约束
- 保留职业关系、聊天内容、时间、金额、地点和现实事件。
- 口语化程度以原人物身份为准，不统一添加方言、语气词和网络用语。""",
    "言情": """# 言情题材约束
- 保留感情方向、关系状态、动作发起者和潜台词，不擅自增加暧昧、冲突或和解。
- 可以清理套话，但不得用固定身体反应替换所有情绪陈述。""",
    "悬疑": """# 悬疑题材约束
- 完整保留证据、数字、时间线、人物位置、推理步骤和信息揭示顺序。
- 不新增线索，不提前揭示结论，不为制造跳跃感打乱因果。""",
    "科幻": """# 科幻题材约束
- 保留技术名词、参数、规则、实体关系和因果机制，不用日常类比替换关键设定。""",
    "历史": """# 历史题材约束
- 保留时代、官职、称谓、制度和礼仪语域，不现代口语化。""",
    "武侠": """# 武侠题材约束
- 保留门派、招式、兵器、穴位、人物称谓和江湖语域，不改成现代网络表达。""",
}


class MetaOptimizer:
    """元优化器（增强版） - 分析并改进提示词，包含经验累积"""

    def __init__(self):
        self.llm_client = get_llm_client()
        # 累积经验库
        self.experience = ExperienceRecord()
        # 🆕 历史分析记录（用于强制差异化）
        self.previous_analyses: List[str] = []
        # 🆕 本次进化周期内已生成的变体策略（用于变体生成去重）
        self._session_strategy_history: List[str] = []
        # 🔧 当前题材
        self.current_genre: Optional[str] = None

    def get_initial_prompt(self, genre: Optional[str] = None) -> str:
        """
        🔧 获取初始提示词（支持按题材定制）

        Args:
            genre: 题材类型（玄幻/都市/言情/悬疑等）
        """
        base_prompt = SAFE_INITIAL_PROMPT

        if genre:
            self.current_genre = genre
            genre_addon = SAFE_GENRE_ADDONS.get(genre, "")
            if genre_addon:
                base_prompt = base_prompt + "\n\n" + genre_addon

        return base_prompt

    @staticmethod
    def _is_eligible_success_sample(result: EvaluationResult) -> bool:
        """只有真实降分且质量稳定的样本才允许沉淀为成功经验。"""
        if not result.success or result.score_reduction <= 10:
            return False
        review = result.llm_review or {}
        if not review.get("available") or review.get("hard_fail"):
            return False
        if review.get("over_rewrite_risk") != "low":
            return False
        return (
            review.get("semantic_fidelity", {}).get("score", 0) >= 80
            and review.get("fact_consistency", {}).get("score", 0) >= 90
            and review.get("information_completeness", {}).get("score", 0) >= 75
        )

    @staticmethod
    def _validate_prompt_safety(prompt: str) -> bool:
        """阻止元优化器把内容破坏包装成降低 AI 率策略。"""
        unsafe_patterns = (
            "破坏叙事逻辑", "重构内在逻辑", "插入不相关联想", "无关细节",
            "改变事件顺序", "重排事件", "极致口语化", "强制口语化",
            "制造不完美", "逻辑是跳跃的", "非线性叙事", "改变叙事视角",
            "改名", "替换人物姓名", "删除原文信息", "用身体反应替代",
            "统一改成现代口语", "删除全场震惊类结尾", "加入口头禅和语气词",
        )
        return bool(prompt.strip()) and not any(pattern in prompt for pattern in unsafe_patterns)

    @staticmethod
    def _validate_strategy_safety(strategy: str) -> bool:
        """在生成完整提示词前拒绝主动制造低质量特征的实验策略。"""
        if not strategy.strip() or not MetaOptimizer._validate_prompt_safety(strategy):
            return False

        direct_unsafe_patterns = (
            "模拟非理性", "下意识强调", "人为制造停顿", "故意制造语病",
            "随机插入", "无意义重复", "无关紧要的词语", "无意义短句",
        )
        if any(pattern in strategy for pattern in direct_unsafe_patterns):
            return False

        harmful_actions = ("刻意", "故意", "主动增加", "人为制造", "模拟", "随机")
        harmful_features = ("重复", "语病", "废话", "停顿", "跳跃", "错别字", "不完整句")
        return not (
            any(action in strategy for action in harmful_actions)
            and any(feature in strategy for feature in harmful_features)
        )

    @staticmethod
    def _strategy_fingerprint(strategy: str) -> str:
        """提取策略的动作和语言维度，用于低成本确定性去重。"""
        normalized = re.sub(r"[\W_]+", "", strategy.lower())
        action = "reduce" if any(
            word in normalized for word in ("减少", "降低", "清理", "删除", "打散", "避免")
        ) else "adjust"
        dimensions = []
        dimension_keywords = {
            "repeated_syntax": ("同构句", "相同句法", "句法骨架", "重复句式", "重复程度"),
            "sentence_length": ("句长", "句子长度", "长短句"),
            "template_words": ("模板词", "模板化", "连接词", "总结词"),
            "empty_phrases": ("套话", "空泛", "重复解释"),
            "fidelity": ("保真", "事实", "事件顺序", "因果", "人物姓名"),
        }
        for dimension, keywords in dimension_keywords.items():
            if any(keyword in normalized for keyword in keywords):
                dimensions.append(dimension)
        return f"{action}:{','.join(dimensions)}" if dimensions else normalized

    @classmethod
    def _filter_candidate_strategies(
        cls,
        strategies: List[str],
        explored_directions: List[str],
        limit: int,
    ) -> List[str]:
        """过滤危险策略及与历史方向重复的策略。"""
        seen = {cls._strategy_fingerprint(item) for item in explored_directions if item.strip()}
        accepted = []
        for strategy in strategies:
            fingerprint = cls._strategy_fingerprint(strategy)
            if not cls._validate_strategy_safety(strategy):
                logger.warning("丢弃高风险探索策略: %s", strategy[:80])
                continue
            if fingerprint in seen:
                logger.info("跳过与历史方向重复的探索策略: %s", strategy[:80])
                continue
            seen.add(fingerprint)
            accepted.append(strategy)
            if len(accepted) >= limit:
                break
        return accepted

    def _removed_legacy_genre_specific_addon(self, genre: str) -> str:
        """🔧 获取题材专用的提示词补充"""
        genre_addons = {
            "玄幻": """
# 🎯 玄幻修仙专用优化

## 战斗描写去AI化
【禁止套路】
- "剑光如虹"、"气势磅礴"、"威势惊人"等空洞描写
- "他脸色大变"、"眼中闪过惊恐"等直接心理描写
- "雷鸣般的掌声"、"全场震惊"等俗套结尾

【替换方案】
- 用具体的招式动作替代"剑光如虹"：剑身一横，侧划出一道弧线
- 用身体反应替代"脸色大变"：他往后踉跄一步，脚跟差点没站稳
- 删除"全场震惊"类结尾，让读者自行感受

## 境界修炼描写
【禁止】直接说"他感受到体内澎湃的力量"
【替换】用具体细节：丹田那块热得发烫，像是吞了块烧红的炭

## 对话口语化
修仙者说话不必文绉绉，可以用现代口语
- "道友请" → "你先"
- "敢问阁下" → "你谁啊"
""",
            "都市": """
# 🎯 都市现实专用优化

## 职场/生活场景
【禁止套路】
- "深知自己肩负的责任"等正能量废话
- "首先...其次...最后"的三段式
- "心中充满希望"等直接情感描写

【替换方案】
- 用具体行动替代：他把文件夹翻来覆去看了三遍
- 用生活细节：外卖盒还堆在桌角，咖啡早凉透了
- 用对话透露心情，而非直接说

## 对话真实感
办公室对话要有职场味：
- "我认为这个方案..." → "这个事儿吧..."
- "请问您有什么意见" → "老板怎么说的"
- 加入口头禅和语气词
""",
            "言情": """
# 🎯 言情小说专用优化

## 情感表达去AI化
【绝对禁止】
- "眼中闪过一丝xxx"、"嘴角微微上扬"
- "心中一动"、"心头涌起一股暖流"
- "他礼貌地回应"、"气氛略显尴尬"

【替换方案】
- 用小动作：她低头玩手机，其实屏幕早就黑了
- 用对话暗示：他说话时一直看着窗外
- 用环境映射：咖啡凉了，她也没发现

## 对话自然化
恋爱中的对话不会那么得体：
- 会打断、会沉默、会说错话
- 会重复、会绕弯子、会欲言又止
- "我觉得你很好，但是..." → "那个...其实..."
""",
            "悬疑": """
# 🎯 悬疑推理专用优化

## 推理过程去AI化
【禁止套路】
- "眼中闪过一丝精光"发现线索
- 过于清晰的逻辑链条
- "真相终于浮出水面"等套话

【替换方案】
- 线索发现要自然：他翻报告翻到第三遍才注意到那个数字
- 推理有曲折：一开始想岔了，后来才反应过来
- 保留悬念，不要每次都"终于"

## 场景氛围
不用"灯火通明"这种空洞描写：
- 具体的光影：荧光灯嗡嗡响，照得人脸色发青
- 具体的声音：走廊尽头有人咳嗽
- 具体的气味：咖啡机一直没关，整层楼都是焦味
"""
        }

        return genre_addons.get(genre, "")

    def reset_experience(self) -> None:
        """重置经验库并预置小说专用知识（新的进化周期开始时调用）"""
        # 使用预置的小说专用经验初始化
        self.experience = ExperienceRecord(
            effective_strategies=list(PRESET_EFFECTIVE_STRATEGIES),
            ineffective_strategies=list(PRESET_INEFFECTIVE_STRATEGIES),
            forbidden_patterns=list(PRESET_FORBIDDEN_PATTERNS),
            best_practices=[]
        )
        # 🆕 同时重置历史分析
        self.previous_analyses = []
        # 🆕 重置本周期变体策略历史
        self._session_strategy_history = []
        logger.info(f"📚 预置小说专用经验: 有效策略{len(PRESET_EFFECTIVE_STRATEGIES)}条, "
                   f"禁止模式{len(PRESET_FORBIDDEN_PATTERNS)}条")

    def _load_strategic_insights(self, historical_reports: List[Dict], genre: Optional[str] = None) -> int:
        """
        🆕 跨批次加载方向性洞察（同题材优先，保留最近5条）

        洞察是战略级方向判断，不参与经验优化器的原子策略去重流程，单独加载。
        """
        sorted_reports = sorted(
            historical_reports,
            key=lambda x: x.get("created_at", ""),
            reverse=True
        )
        if genre:
            genre_reports = [r for r in sorted_reports if r.get("genre") == genre]
            other_reports = [r for r in sorted_reports if r.get("genre") != genre]
            sorted_reports = genre_reports[:3] + other_reports[:2]
        else:
            sorted_reports = sorted_reports[:5]

        loaded = 0
        # 逆序遍历：让最近批次的洞察排在列表末尾（截断时最容易保留）
        for report in reversed(sorted_reports):
            for insight in report.get("strategic_insights", []):
                insight = (insight or "").strip()
                if insight and insight not in self.experience.strategic_insights:
                    self.experience.strategic_insights.append(insight)
                    loaded += 1
        self.experience.strategic_insights = self.experience.strategic_insights[-5:]

        if loaded:
            logger.info(f"🧭 跨批次加载方向性洞察: {loaded} 条")
        return loaded

    def load_historical_experience(self, historical_reports: List[Dict], genre: Optional[str] = None) -> int:
        """
        从历史经验报告中加载经验（跨批次传承）

        Args:
            historical_reports: 历史经验报告列表
            genre: 🔧 可选的题材过滤（优先加载同题材的经验）

        Returns:
            加载的经验条数
        """
        if not historical_reports:
            return 0

        loaded_count = 0

        # 🆕 先跨批次加载方向性洞察（不受"优化经验"分支 return 影响，独立于原子策略）
        self._load_strategic_insights(historical_reports, genre)

        # 🆕 尝试从 storage 加载优化后的经验
        from .storage import get_evolution_storage
        storage = get_evolution_storage()
        optimized_data = storage.load_optimized_experiences()
        
        if optimized_data:
            logger.info("🎯 检测到优化经验，优先使用")
            experiences = optimized_data.get("experiences", [])

            optimized_texts = {
                "effective": set(),
                "ineffective": set(),
                "forbidden": set(),
                "best_practice": set(),
            }

            def apply_to_list(target_list: List[str], text: str) -> None:
                # 让优化经验成为“更近期”的条目，避免被截断掉；同时保持去重
                if text in target_list:
                    target_list.remove(text)
                target_list.append(text)

            # 逆序应用：让排序更靠前（通常更重要）的经验最终处在列表更后侧（更容易保留）
            for exp_dict in reversed(experiences):
                try:
                    exp_item = ExperienceItem.from_dict(exp_dict)
                except Exception as e:
                    logger.warning(f"⚠️ 加载优化经验项失败: {e}")
                    continue

                category = exp_item.category
                text = (exp_item.text or "").strip()
                if not text:
                    continue

                if category in optimized_texts:
                    optimized_texts[category].add(text)

                if category == "effective":
                    apply_to_list(self.experience.effective_strategies, text)
                elif category == "ineffective":
                    apply_to_list(self.experience.ineffective_strategies, text)
                elif category == "forbidden":
                    apply_to_list(self.experience.forbidden_patterns, text)
                elif category == "best_practice":
                    apply_to_list(self.experience.best_practices, text)

            # 限制每类经验的最大数量（保留后N条，避免新经验被截断）
            self.experience.effective_strategies = self.experience.effective_strategies[-15:]
            self.experience.ineffective_strategies = self.experience.ineffective_strategies[-15:]
            self.experience.forbidden_patterns = self.experience.forbidden_patterns[-15:]
            self.experience.best_practices = self.experience.best_practices[-15:]

            applied_counts = {
                "effective": sum(1 for s in self.experience.effective_strategies if s in optimized_texts["effective"]),
                "ineffective": sum(1 for s in self.experience.ineffective_strategies if s in optimized_texts["ineffective"]),
                "forbidden": sum(1 for s in self.experience.forbidden_patterns if s in optimized_texts["forbidden"]),
                "best_practice": sum(1 for s in self.experience.best_practices if s in optimized_texts["best_practice"]),
            }
            loaded_count = sum(applied_counts.values())

            logger.info(
                f"📚 优化经验生效: {loaded_count} 条 "
                f"(effective={applied_counts['effective']}, "
                f"ineffective={applied_counts['ineffective']}, "
                f"forbidden={applied_counts['forbidden']}, "
                f"best_practice={applied_counts['best_practice']})"
            )

            return loaded_count
        
        # 如果没有优化经验，使用原始方式加载
        logger.info("📚 未找到优化经验，使用原始报告")

        # 按时间排序，优先使用最近的经验
        sorted_reports = sorted(
            historical_reports,
            key=lambda x: x.get("created_at", ""),
            reverse=True
        )

        # 🔧 如果指定了题材，优先加载同题材的经验
        if genre:
            genre_reports = [r for r in sorted_reports if r.get("genre") == genre]
            other_reports = [r for r in sorted_reports if r.get("genre") != genre]
            sorted_reports = genre_reports[:3] + other_reports[:2]  # 同题材3个 + 其他2个
        else:
            sorted_reports = sorted_reports[:5]

        # 🔧 加载权重配置（使用最近一个有效的配置）
        for report in sorted_reports:
            if report.get("weight_config") and not self.experience.weight_config:
                self.experience.weight_config = report["weight_config"]
                logger.info(f"📊 加载历史权重配置")
            if report.get("threshold_config") and not self.experience.threshold_config:
                self.experience.threshold_config = report["threshold_config"]
                logger.info(f"📊 加载历史阈值配置")

        for report in sorted_reports:
            # 加载有效策略（去重）
            for strategy in report.get("effective_strategies", []):
                if strategy and strategy not in self.experience.effective_strategies:
                    self.experience.effective_strategies.append(strategy)
                    loaded_count += 1

            # 加载无效策略（去重）
            for strategy in report.get("ineffective_strategies", []):
                if strategy and strategy not in self.experience.ineffective_strategies:
                    self.experience.ineffective_strategies.append(strategy)
                    loaded_count += 1

            # 加载禁止模式（去重）
            for pattern in report.get("forbidden_patterns", []):
                if pattern and pattern not in self.experience.forbidden_patterns:
                    self.experience.forbidden_patterns.append(pattern)
                    loaded_count += 1

            # 加载最佳实践（去重）
            for practice in report.get("best_practices", []):
                if practice and practice not in self.experience.best_practices:
                    self.experience.best_practices.append(practice)
                    loaded_count += 1

        # 限制每类经验的最大数量，避免prompt过长
        self.experience.effective_strategies = self.experience.effective_strategies[-15:]
        self.experience.ineffective_strategies = self.experience.ineffective_strategies[-15:]
        self.experience.forbidden_patterns = self.experience.forbidden_patterns[-15:]
        self.experience.best_practices = self.experience.best_practices[-15:]

        logger.info(f"📚 从历史加载经验: {loaded_count} 条 (来自 {len(sorted_reports)} 个批次)")

        return loaded_count

    async def optimize_prompt(
        self,
        current_version: PromptVersion,
        target_score: int,
        history: List[PromptVersion],
        exploration_mode: bool = False,
        reverse_optimization: bool = False
    ) -> Tuple[str, str]:
        """
        分析当前提示词并生成改进版本

        Args:
            current_version: 当前提示词版本
            target_score: 目标AI得分
            history: 历史版本列表

        Returns:
            (改进后的提示词, 分析说明)
        """
        results = current_version.evaluation_results

        # 分离成功和失败样本
        success_samples = [r for r in results if self._is_eligible_success_sample(r)]
        failure_samples = [r for r in results if not self._is_eligible_success_sample(r)]

        # 构建成功样本分析
        success_analysis = self._build_success_analysis(success_samples)

        # 构建失败样本分析
        failure_analysis = self._build_failure_analysis(failure_samples)

        # 构建趋势分析
        trend_analysis = self._build_trend_analysis(history, current_version)

        # 构建累积经验摘要
        experience_summary = self._build_experience_summary()

        # 🆕 构建历史分析对比
        previous_analysis_summary = self._build_previous_analysis_summary()
        
        # 🆕 构建探索模式和反向优化指令
        exploration_instruction = self._build_exploration_instruction(exploration_mode, reverse_optimization)

        # 计算平均降分
        valid_results = [r for r in results if r.success]
        avg_reduction = sum(r.score_reduction for r in valid_results) / len(valid_results) if valid_results else 0

        # 构建优化请求
        optimization_prompt = META_OPTIMIZER_PROMPT.format(
            current_prompt=current_version.prompt_text,
            avg_score=f"{current_version.avg_ai_score:.1f}",
            target_score=target_score,
            avg_reduction=f"{avg_reduction:.1f}",
            success_count=len(success_samples),
            total_count=len(results),
            success_analysis=success_analysis,
            failure_analysis=failure_analysis,
            trend_analysis=trend_analysis,
            experience_summary=experience_summary,
            previous_analysis_summary=previous_analysis_summary
        )
        optimization_prompt += """

【不可突破的进化边界】
- 只能优化可能影响AI检测的语言统计特征：模板化词汇、重复句式、句长过度均匀、机械连接和空泛套话。
- 降分样本只有在语义保真、事实一致、信息完整均通过且过度改写风险为low时，才可归纳为成功经验。
- 禁止把改名、删信息、换视角、改事件顺序、改因果、添加无关细节、强制口语化、制造病句归因成有效策略。
- 禁止要求破坏叙事逻辑、插入不相关联想、非线性重排、统一添加吐槽/方言/语气词/身体反应。
- 优先小幅修改和单变量实验；没有跨多个同题材样本重复验证的手法，不得写成强制规则。
- 改进后的提示词必须继续包含专名、事实、事件顺序、因果、否定关系和题材语域保护。
"""
        
        # 🆕 添加探索模式和反向优化指令
        if exploration_instruction:
            optimization_prompt += f"\n\n{exploration_instruction}"

        messages = [
            {"role": "system", "content": "你是提示词工程专家，擅长通过分析成功和失败案例来优化提示词。"},
            {"role": "user", "content": optimization_prompt}
        ]

        # 使用 REVIEW_CHECK 任务类型，会自动选择 chat 模型（更快）
        # 🆕 探索模式使用更高温度
        temperature = 0.9 if exploration_mode else 0.7
        response = await self.llm_client.chat(
            messages=messages,
            task_type=TaskType.REVIEW_CHECK,
            temperature=temperature,
            use_cache=False
        )

        # 先在当前实例上解析；若候选不安全，则用快照完整回滚经验变更。
        experience_snapshot = copy.deepcopy(self.experience)
        analyses_snapshot = list(self.previous_analyses)
        improved_prompt, analysis = self._parse_response(response)

        if not improved_prompt:
            logger.warning("⚠️ 无法解析改进后的提示词，使用原提示词")
            self.experience = experience_snapshot
            self.previous_analyses = analyses_snapshot
            improved_prompt = current_version.prompt_text
            analysis = "解析失败，保持原提示词"
        elif not self._validate_prompt_safety(improved_prompt):
            logger.warning("元优化器生成了高风险内容改写策略，拒绝该提示词并保留当前版本")
            self.experience = experience_snapshot
            self.previous_analyses = analyses_snapshot
            improved_prompt = current_version.prompt_text
            analysis = f"候选提示词包含可能破坏原文的策略，已拒绝。{analysis}".strip()

        return improved_prompt, analysis

    async def generate_prompt_variants(
        self,
        base_prompt: str,
        num_variants: int = 2,
        exploration_mode: bool = False
    ) -> List[Tuple[str, str]]:
        """
        🆕 生成多个提示词变体用于A/B测试（完全由AI动态随机探索）

        Args:
            base_prompt: 基础提示词
            num_variants: 生成变体数量
            exploration_mode: 是否处于探索模式

        Returns:
            [(变体提示词, 变体描述), ...]
        """
        variants = []
        
        # 🆕 第一步：让AI随机生成探索策略
        strategies = await self._generate_random_exploration_strategies(num_variants, exploration_mode)
        
        if not strategies:
            logger.warning("⚠️ AI策略生成失败，跳过变体生成")
            return []
        
        # 🆕 第二步：根据随机策略生成变体
        for i, strategy_desc in enumerate(strategies, 1):
            if not self._validate_strategy_safety(strategy_desc):
                logger.warning("生成提示词前丢弃高风险A/B策略: %s", strategy_desc[:80])
                continue
            # 探索模式使用更高温度
            temperature = 0.95 if exploration_mode else 0.8
            variant_prompt = await self._generate_variant_from_strategy(
                base_prompt, 
                strategy_desc, 
                temperature
            )
            
            if variant_prompt and self._validate_prompt_safety(variant_prompt):
                variants.append((variant_prompt, strategy_desc))
                mode_label = "🔍探索" if exploration_mode else "📝常规"
                logger.info(f"{mode_label} 生成变体 {i}: {strategy_desc[:50]}...")
            elif variant_prompt:
                logger.warning("丢弃包含高风险内容改写策略的A/B变体: %s", strategy_desc[:80])
        
        return variants
    
    async def _generate_random_exploration_strategies(
        self,
        num_strategies: int,
        exploration_mode: bool = False
    ) -> List[str]:
        """
        🆕 让AI随机生成探索策略（根本不使用硬编码）
        
        Args:
            num_strategies: 需要生成的策略数量
            exploration_mode: 是否为探索模式（影响激进程度）
        
        Returns:
            策略描述列表
        """
        mode_desc = "受控探索" if exploration_mode else "温和优化"

        # 🆕 汇总历史已探索方向（跨批次经验 + 本周期已生成的变体策略），用于避免重复探索
        explored_directions = (
            list(self.experience.effective_strategies)
            + list(self.experience.ineffective_strategies)
            + self._session_strategy_history
        )
        # 只保留最近的方向，避免提示词过长
        explored_directions = explored_directions[-20:]
        explored_section = ""
        if explored_directions:
            explored_lines = "\n".join(f"- {d[:60]}" for d in explored_directions)
            explored_section = f"""
【历史已探索方向】（以下方向已被尝试过，不得改写措辞后重复提交）
{explored_lines}
"""

        prompt = f"""你是提示词优化专家。所有实验必须降低机械语言特征并保持原文事实与表达质量。

你的任务：生成 {num_strategies} 个不同的{mode_desc}策略，用于测试和改进"降低AI痕迹"提示词。
{explored_section}
【核心要求】
1. 每条策略只改变一个可观测变量，且只能属于以下方向：减少模板化词汇、减少重复句法、自然调整句长分布、减少机械连接、清理空泛套话。
2. “重复”只能被减少或打散，绝对不得主动增加无意义重复。
3. 不得刻意制造语病、错别字、废话、非理性停顿、不完整表达或随机标点。
4. 不得改名、改变设定、叙事视角、事件顺序、因果、否定关系，不得删除事实或添加原文没有的细节。
5. {'可以组合尚未共同验证的统计指标，但每条策略仍只测试一个主要变量' if exploration_mode else '保持温和、可控，优先对已有有效方向做小幅参数调整'}。

【输出格式】
请直接输出 {num_strategies} 条策略，每行一条，不要编号，不要解释。
每条策略应该是一个简洁的描述性句子（30-50字）。

示例输出：
减少连续使用相同句法骨架，但不机械拆句或改变语义
清理不承载事实的套话和重复解释，保留全部具体信息
对话只在原有语气范围内轻度自然化，不新增方言或语气词

请开始生成："""
        
        try:
            messages = [
                {"role": "system", "content": "你是严谨的中文文本统计特征优化专家，只生成保真且可控的单变量策略。"},
                {"role": "user", "content": prompt}
            ]
            
            # 使用高温度生成随机性更强的策略
            temperature = 0.95 if exploration_mode else 0.85
            response = await self.llm_client.chat(
                messages=messages,
                task_type=TaskType.REVIEW_CHECK,
                temperature=temperature,
                use_cache=False  # 禁用缓存，确保每次都是新的
            )
            
            # 解析返回的策略列表
            strategies = []
            for line in response.strip().split('\n'):
                line = line.strip()
                # 过滤空行和编号
                if line and not line[0].isdigit() and line[0] not in ['-', '*', '·']:
                    strategies.append(line)
                elif line and (line[0].isdigit() or line[0] in ['-', '*', '·']):
                    # 移除编号标记
                    cleaned = line.lstrip('0123456789.-*· ')
                    if cleaned:
                        strategies.append(cleaned)
            
            strategies = self._filter_candidate_strategies(
                strategies,
                explored_directions,
                num_strategies,
            )

            # 🆕 记入本周期策略历史，供下次生成时去重
            self._session_strategy_history.extend(strategies)

            logger.info(f"🎲 AI随机生成 {len(strategies)} 个{mode_desc}策略")
            for i, s in enumerate(strategies, 1):
                logger.debug(f"  {i}. {s[:60]}...")
            
            return strategies
            
        except Exception as e:
            logger.error(f"❌ AI策略生成失败: {e}")
            return []
    
    async def _generate_variant_from_strategy(
        self,
        base_prompt: str,
        strategy_desc: str,
        temperature: float = 0.8
    ) -> str:
        """
        🆕 根据AI随机生成的策略生成变体
        
        Args:
            base_prompt: 基础提示词
            strategy_desc: AI生成的策略描述
            temperature: 生成温度
        
        Returns:
            变体提示词
        """
        prompt = f"""请基于以下提示词生成一个变体版本。

【原始提示词】
{base_prompt[:2000]}{'...' if len(base_prompt) > 2000 else ''}

【变体策略】
{strategy_desc}

【要求】
1. 保持原始提示词的核心结构和目标（降低AI痕迹）
2. 根据变体策略，强化、弱化或调整相关规则
3. 可以添加新的指令、示例或禁止项
4. 直接输出完整的变体提示词，不要任何解释或标记
5. 不得改变人物、专名、事实、设定、事件顺序、因果和叙事视角
6. 不得加入极致口语化、无关细节、非线性叙事、逻辑跳跃或强制标点规则

请输出变体提示词："""
        
        try:
            messages = [
                {"role": "system", "content": "你是提示词变体生成专家。"},
                {"role": "user", "content": prompt}
            ]
            
            response = await self.llm_client.chat(
                messages=messages,
                task_type=TaskType.REVIEW_CHECK,
                temperature=temperature,
                use_cache=False
            )
            
            return response.strip()
            
        except Exception as e:
            logger.error(f"生成变体失败: {e}")
            return ""

    def _build_success_analysis(self, samples: List[EvaluationResult]) -> str:
        """构建成功样本分析"""
        if not samples:
            return "本轮无明显成功的样本（降分>10分）"

        lines = ["以下样本降分效果较好，值得分析成功原因：\n"]

        # 按降分幅度排序
        sorted_samples = sorted(samples, key=lambda x: x.score_reduction, reverse=True)

        for i, r in enumerate(sorted_samples[:3], 1):
            # 构建AI痕迹对比信息
            trace_comparison = self._build_trace_comparison(r)

            lines.append(f"""
【成功样本{i}】降分: {r.score_reduction}分 ({r.original_ai_score}→{r.rewritten_ai_score})
┌─ 原文特征 ─────────────────────────────
│ {r.original_text[:200]}...
├─ 改写后 ───────────────────────────────
│ {r.rewritten_text[:200]}...
{trace_comparison}
└─ 成功点分析：请识别改写中哪些手法有效降低了AI痕迹
""")

        return "\n".join(lines)

    def _build_failure_analysis(self, samples: List[EvaluationResult]) -> str:
        """构建失败样本分析"""
        if not samples:
            return "本轮所有样本效果都不错！"

        lines = ["以下样本降分效果差或失败，需要分析原因：\n"]

        for i, r in enumerate(samples[:3], 1):
            if not r.success:
                review = r.llm_review or {}
                quality_details = ""
                if review.get("available"):
                    quality_details = (
                        f"\n├─ 语义保真: {review.get('semantic_fidelity', {}).get('score', '-')}"
                        f"，事实一致: {review.get('fact_consistency', {}).get('score', '-')}"
                        f"，信息完整: {review.get('information_completeness', {}).get('score', '-')}"
                        f"\n├─ 过度改写风险: {review.get('over_rewrite_risk', '-')}"
                        f"；{review.get('over_rewrite_reason', '')}"
                    )
                lines.append(f"""
【失败样本{i}】错误: {r.error}
┌─ 原文 ─────────────────────────────────
│ {r.original_text[:200]}...
├─ 改写后 ───────────────────────────────
│ {r.rewritten_text[:200]}...{quality_details}
└─ 问题：不得把该样本的降分手法归纳为成功经验；优先修复语义、事实、信息完整性和过度改写问题
""")
            else:
                # 构建AI痕迹详情
                trace_detail = self._build_trace_detail(r)

                # 🆕 构建量化指标对比
                metrics_info = self._build_metrics_info(r)

                lines.append(f"""
【效果差样本{i}】降分仅: {r.score_reduction}分 ({r.original_ai_score}→{r.rewritten_ai_score})
┌─ 原文 ─────────────────────────────────
│ {r.original_text[:200]}...
├─ 改写后 ───────────────────────────────
│ {r.rewritten_text[:200]}...
{trace_detail}
{metrics_info}
└─ 问题诊断：改写后仍保留了哪些AI痕迹？提示词的哪条指令没被执行？
""")

        return "\n".join(lines)

    def _build_metrics_info(self, result: EvaluationResult) -> str:
        """构建量化指标信息"""
        lines = []

        if result.original_metrics and result.rewritten_metrics:
            orig = result.original_metrics
            rewr = result.rewritten_metrics

            # 标点分析
            orig_period = orig.get("period_ratio", 0) * 100
            rewr_period = rewr.get("period_ratio", 0) * 100
            orig_emotion = orig.get("emotion_punct_ratio", 0) * 100
            rewr_emotion = rewr.get("emotion_punct_ratio", 0) * 100

            lines.append(f"├─ 📊 标点变化: 句号占比 {orig_period:.0f}%→{rewr_period:.0f}%, 情感标点 {orig_emotion:.0f}%→{rewr_emotion:.0f}%")

            # 句式分析
            orig_var = orig.get("sentence_length_variance", 0)
            rewr_var = rewr.get("sentence_length_variance", 0)
            orig_short = orig.get("short_sentence_ratio", 0) * 100
            rewr_short = rewr.get("short_sentence_ratio", 0) * 100

            lines.append(f"├─ 📊 句式变化: 句长方差 {orig_var:.0f}→{rewr_var:.0f}, 短句占比 {orig_short:.0f}%→{rewr_short:.0f}%")

            # 禁用词分析
            orig_forbidden = orig.get("forbidden_word_count", 0)
            rewr_forbidden = rewr.get("forbidden_word_count", 0)
            if orig_forbidden > 0 or rewr_forbidden > 0:
                lines.append(f"├─ 📊 禁用词: {orig_forbidden}→{rewr_forbidden}个")

            # 指标对比摘要
            if result.metrics_comparison:
                lines.append(f"├─ 📊 变化摘要: {result.metrics_comparison}")

        return "\n".join(lines) if lines else ""

    def _build_trace_comparison(self, result: EvaluationResult) -> str:
        """构建AI痕迹对比信息（成功样本用）"""
        lines = []

        # 原始文本的AI痕迹
        if result.original_trace_detail:
            orig = result.original_trace_detail
            if orig.hit_keywords:
                lines.append(f"├─ 原文AI痕迹关键词: {', '.join(orig.hit_keywords[:5])}")
            if orig.detection_method:
                lines.append(f"├─ 原文检测方法: {orig.detection_method}")

        # 改写后的AI痕迹
        if result.rewritten_trace_detail:
            rewr = result.rewritten_trace_detail
            if rewr.hit_keywords:
                lines.append(f"├─ 改写后仍有AI痕迹: {', '.join(rewr.hit_keywords[:5])}")
            else:
                lines.append(f"├─ ✅ 改写后无明显AI痕迹关键词")

        return "\n".join(lines) if lines else ""

    def _build_trace_detail(self, result: EvaluationResult) -> str:
        """构建AI痕迹详情（失败样本用）"""
        lines = []

        if result.rewritten_trace_detail:
            trace = result.rewritten_trace_detail

            # 检测方法
            if trace.detection_method:
                lines.append(f"├─ 🔍 检测方法: {trace.detection_method}")

            # 命中的关键词（最重要！）
            if trace.hit_keywords:
                lines.append(f"├─ 🚨 暴露AI痕迹的关键词: {', '.join(trace.hit_keywords[:10])}")

            # 各标签得分
            if trace.label_scores:
                high_scores = [(k, v) for k, v in trace.label_scores.items() if v > 50]
                if high_scores:
                    score_str = ", ".join([f"{k}:{v}" for k, v in high_scores])
                    lines.append(f"├─ 📊 高风险标签: {score_str}")

            # 问题片段（带位置）
            if trace.problematic_segments:
                lines.append(f"├─ 📍 问题片段详情:")
                for seg in trace.problematic_segments[:3]:
                    keyword = seg.get("keyword", "")
                    context = seg.get("context", "")
                    pos = seg.get("position", {})
                    lines.append(f"│   • [{pos.get('start', 0)}-{pos.get('end', 0)}] \"{keyword}\" → 上下文: ...{context}...")
        else:
            lines.append("├─ ⚠️ 无法获取AI痕迹详情（API未返回详细信息）")

        return "\n".join(lines) if lines else ""

    def _build_trend_analysis(self, history: List[PromptVersion], current: PromptVersion) -> str:
        """构建趋势分析"""
        if not history:
            return "这是第一次迭代，无历史趋势数据。"

        lines = ["迭代得分变化趋势：\n"]

        # 收集所有得分
        all_scores = [(v.iteration, v.avg_ai_score, v.avg_score_reduction) for v in history]
        all_scores.append((current.iteration, current.avg_ai_score, current.avg_score_reduction))
        all_scores.sort(key=lambda x: x[0])

        # 绘制简单趋势图
        for idx, (iteration, score, reduction) in enumerate(all_scores):
            bar_len = int(score / 5)  # 每5分一个块
            bar = "█" * bar_len + "░" * (20 - bar_len)
            # 计算趋势图标：得分下降=改善📈，得分上升=变差📉
            if idx > 0:
                prev_score = all_scores[idx - 1][1]
                trend_icon = "📈" if score < prev_score else "📉"
            else:
                trend_icon = ""
            lines.append(f"迭代{iteration}: [{bar}] {score:.1f}分 (降{reduction:.1f}分) {trend_icon}")

        # 趋势判断
        if len(all_scores) >= 3:
            recent_scores = [s[1] for s in all_scores[-3:]]
            if recent_scores == sorted(recent_scores, reverse=True):
                lines.append("\n⚠️ 趋势警告: 最近3次迭代得分持续上升（变差），可能需要大幅调整策略！")
            elif recent_scores == sorted(recent_scores):
                lines.append("\n✅ 趋势良好: 得分持续下降（改善），继续当前优化方向。")
            else:
                diff = abs(recent_scores[-1] - recent_scores[-2])
                if diff < 3:
                    lines.append("\n⚡ 趋势提示: 得分变化趋于平稳，可能接近收敛，尝试突破性改进。")
                else:
                    lines.append("\n🔄 趋势提示: 得分有波动，需要稳定优化策略。")

        return "\n".join(lines)

    def _build_experience_summary(self) -> str:
        """构建累积经验摘要，主动提取TOP策略"""
        lines = []

        # 🆕 方向性洞察（跨批次软引导：仅供参考，不强制执行）
        if self.experience.strategic_insights:
            lines.append("🧭 【历史验证的有效方向】（供参考，非强制）")
            for insight in self.experience.strategic_insights[-3:]:
                lines.append(f"   • {insight}")
            lines.append("   若当前方向仍在见效，请沿此深挖；若已停滞，再考虑新方向。")
            lines.append("")

        # 🆕 首先强调TOP3最有效策略（必须执行）
        if self.experience.effective_strategies:
            top_strategies = self._get_top_strategies()
            if top_strategies:
                lines.append("🔥🔥🔥 【TOP3 必须执行的策略】🔥🔥🔥")
                for i, s in enumerate(top_strategies, 1):
                    lines.append(f"   {i}. {s}")
                lines.append("")

        if self.experience.effective_strategies:
            lines.append("✅ 已验证有效的策略：")
            for s in self.experience.effective_strategies[-5:]:
                lines.append(f"   • {s}")

        if self.experience.ineffective_strategies:
            lines.append("\n❌ 已验证无效的策略（避免重复）：")
            for s in self.experience.ineffective_strategies[-5:]:
                lines.append(f"   • {s}")

        if self.experience.forbidden_patterns:
            lines.append("\n🚫 应避免的AI痕迹模式：")
            for p in self.experience.forbidden_patterns[-5:]:
                lines.append(f"   • {p}")

        if self.experience.best_practices:
            lines.append("\n💡 最佳实践：")
            for p in self.experience.best_practices[-3:]:
                lines.append(f"   • {p}")

        return "\n".join(lines) if lines else "暂无累积经验（第一次迭代）"

    def _get_top_strategies(self) -> List[str]:
        """
        🆕 提取TOP3最有效策略

        策略优先级：
        1. 出现频率最高的策略
        2. 与核心问题（情感层、标点层）相关的策略
        """
        if not self.experience.effective_strategies:
            return []

        # 核心关键词（这些维度的策略优先级更高）
        priority_keywords = [
            "情感", "身体反应", "动作", "标点", "省略号", "问号", "感叹号", "对话", "口语",
            # 🆕 文笔相关关键词
            "文笔", "优美", "流畅", "比喻", "拟人", "修辞", "韵律", "意境", "画面感", "踱步"
        ]

        # 计算策略优先级
        strategy_scores = []
        for strategy in self.experience.effective_strategies:
            score = 0
            # 基础分：出现越晚越重要（最近学到的）
            idx = self.experience.effective_strategies.index(strategy)
            score += idx * 0.1

            # 关键词加分
            for keyword in priority_keywords:
                if keyword in strategy:
                    score += 2

            strategy_scores.append((strategy, score))

        # 按分数排序，取TOP3
        sorted_strategies = sorted(strategy_scores, key=lambda x: x[1], reverse=True)
        return [s[0] for s in sorted_strategies[:3]]

    def _build_previous_analysis_summary(self) -> str:
        """🆕 构建历史分析摘要，用于强制差异化"""
        if not self.previous_analyses:
            return "这是第一次分析，无历史记录。请自由发挥，但要准确。"

        lines = ["以下是之前迭代的分析结论（你必须避免重复）：\n"]

        # 显示最近3次分析
        for i, analysis in enumerate(self.previous_analyses[-3:], 1):
            lines.append(f"【迭代{len(self.previous_analyses) - 3 + i}的分析】")
            lines.append(f"   {analysis[:200]}...")
            lines.append("")

        lines.append("⚠️ 请从不同角度分析，发现新问题！")

        return "\n".join(lines)
    
    def _build_exploration_instruction(self, exploration_mode: bool, reverse_optimization: bool) -> str:
        """
        🆕 构建探索模式和反向优化指令
        
        Args:
            exploration_mode: 是否处于探索模式
            reverse_optimization: 是否启用反向优化
        
        Returns:
            探索指令字符串
        """
        if not exploration_mode:
            return ""
        
        instruction_parts = []
        instruction_parts.append("═══════════════════════════════════════")
        instruction_parts.append("【🔍 探索模式激活】")
        instruction_parts.append("═══════════════════════════════════════")
        instruction_parts.append("")
        instruction_parts.append("当前处于探索模式，可以扩大语言统计特征的组合范围，但内容保真边界不可突破：")
        instruction_parts.append("")
        instruction_parts.append("1. **扩大可控实验范围**")
        instruction_parts.append("   - 只允许测试模板化词汇、重复句法、句长均匀、机械连接和空泛套话")
        instruction_parts.append("   - 每次优先改变一个语言变量，便于判断真实贡献")
        instruction_parts.append("   - 句式和标点实验必须服从语义、语法和题材语域")
        instruction_parts.append("")
        instruction_parts.append("2. **增加多样性**")
        instruction_parts.append("   - 可以调整五类允许维度的阈值或作用范围，不得主动增加无意义重复")
        instruction_parts.append("   - 不得刻意增加碎片句、语气词、废话、随机标点或非理性停顿")
        instruction_parts.append("   - 不得把单一词表替换包装成新策略")
        instruction_parts.append("")
        instruction_parts.append("3. **跳出局部最优**")
        instruction_parts.append("   - 可以重新检验历史语言策略，但不得忽略内容保真约束")
        instruction_parts.append("   - 重新评估之前认为无效的策略")
        instruction_parts.append("   - 新实验必须与历史策略具有不同的允许维度或明确不同的可测参数")
        instruction_parts.append("")
        
        if reverse_optimization:
            instruction_parts.append("4. **🔀 反向优化模式激活**")
            instruction_parts.append("   - 反向优化只允许回调历史策略的强度，不允许反向增加已知低质量特征")
            instruction_parts.append("   - 例如：若句长调整过强，则降低调整幅度并恢复自然连贯")
            instruction_parts.append("   - 目的：检验历史策略是否过度，而不是突破质量与保真边界")
            instruction_parts.append("")
        
        instruction_parts.append("⚠️ 注意：探索模式不是放弃原则，仍需：")
        instruction_parts.append("   - 保持文笔顺畅和可读性")
        instruction_parts.append("   - 不改变故事情节")
        instruction_parts.append("   - 不改变专名、事实、设定、事件顺序、因果和否定关系")
        instruction_parts.append("   - 不添加无关细节、吐槽、方言或原文没有的内心活动")
        instruction_parts.append("   - 保证输出质量")
        
        return "\n".join(instruction_parts)

    def _parse_response(self, response: str) -> Tuple[str, str]:
        """解析优化器响应并更新经验库"""

        # 提取有效策略
        effective_match = re.search(
            r"===EFFECTIVE_STRATEGIES===\s*(.*?)\s*===EFFECTIVE_STRATEGIES_END===",
            response, re.DOTALL
        )
        if effective_match:
            strategies = [s.strip() for s in effective_match.group(1).strip().split('\n') if s.strip()]
            for s in strategies:
                if s not in self.experience.effective_strategies:
                    self.experience.effective_strategies.append(s)

        # 提取无效策略
        ineffective_match = re.search(
            r"===INEFFECTIVE_STRATEGIES===\s*(.*?)\s*===INEFFECTIVE_STRATEGIES_END===",
            response, re.DOTALL
        )
        if ineffective_match:
            strategies = [s.strip() for s in ineffective_match.group(1).strip().split('\n') if s.strip()]
            for s in strategies:
                if s not in self.experience.ineffective_strategies:
                    self.experience.ineffective_strategies.append(s)

        # 提取禁止模式
        forbidden_match = re.search(
            r"===FORBIDDEN_PATTERNS===\s*(.*?)\s*===FORBIDDEN_PATTERNS_END===",
            response, re.DOTALL
        )
        if forbidden_match:
            patterns = [p.strip() for p in forbidden_match.group(1).strip().split('\n') if p.strip()]
            for p in patterns:
                if p not in self.experience.forbidden_patterns:
                    self.experience.forbidden_patterns.append(p)

        # 提取分析
        analysis_match = re.search(
            r"===ANALYSIS===\s*(.*?)\s*===ANALYSIS_END===",
            response, re.DOTALL
        )
        analysis = analysis_match.group(1).strip() if analysis_match else ""

        # 🆕 提取方向性洞察（战略级方向判断，跨批次沉淀）
        insight_match = re.search(
            r"===STRATEGIC_INSIGHT===\s*(.*?)\s*===STRATEGIC_INSIGHT_END===",
            response, re.DOTALL
        )
        if insight_match:
            insights = [s.strip() for s in insight_match.group(1).strip().split('\n') if s.strip()]
            for insight in insights[:2]:  # 每轮最多采纳2条
                # 过滤模板占位符残留
                if insight.startswith('[') or len(insight) < 8:
                    continue
                if insight not in self.experience.strategic_insights:
                    self.experience.strategic_insights.append(insight)
            # 洞察是高阶方向，保留最近5条即可
            self.experience.strategic_insights = self.experience.strategic_insights[-5:]

        # 提取改进后的提示词
        prompt_match = re.search(
            r"===IMPROVED_PROMPT===\s*(.*?)\s*===IMPROVED_PROMPT_END===",
            response, re.DOTALL
        )
        improved_prompt = prompt_match.group(1).strip() if prompt_match else ""

        # 记录本次分析作为经验
        if analysis and len(analysis) > 20:
            self.experience.best_practices.append(f"迭代分析: {analysis[:100]}...")
            # 🆕 保存到历史分析列表（用于强制差异化）
            self.previous_analyses.append(analysis)
            # 只保留最近5次分析
            if len(self.previous_analyses) > 5:
                self.previous_analyses = self.previous_analyses[-5:]

        logger.info(f"📚 经验库更新: 有效策略{len(self.experience.effective_strategies)}条, "
                   f"无效策略{len(self.experience.ineffective_strategies)}条, "
                   f"禁止模式{len(self.experience.forbidden_patterns)}条, "
                   f"方向洞察{len(self.experience.strategic_insights)}条")

        return improved_prompt, analysis

    def get_experience_report(self, weight_config: Optional[Dict] = None, threshold_config: Optional[Dict] = None) -> Dict:
        """
        🔧 获取经验报告（增强版：包含权重和阈值配置）

        Args:
            weight_config: 当前使用的评分权重配置
            threshold_config: 当前使用的阈值参数配置
        """
        return {
            "effective_strategies": self.experience.effective_strategies,
            "ineffective_strategies": self.experience.ineffective_strategies,
            "forbidden_patterns": self.experience.forbidden_patterns,
            "best_practices": self.experience.best_practices,
            # 🆕 方向性洞察（跨批次软引导）
            "strategic_insights": self.experience.strategic_insights,
            # 🔧 新增：保存权重和阈值配置
            "weight_config": weight_config or self.experience.weight_config,
            "threshold_config": threshold_config or self.experience.threshold_config,
            "genre": self.current_genre
        }

