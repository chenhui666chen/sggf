"""
提示词进化系统 - 元优化器（增强版）

让LLM分析提示词效果并生成改进版本
包含成功/失败经验总结、策略追踪和趋势分析
"""
import re
import logging
from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass, field

from app.services.llm_client import get_llm_client
from app.services.model_optimizer import TaskType

from .models import PromptVersion, EvaluationResult
from .novel_rules import (
    PRESET_EFFECTIVE_STRATEGIES,
    PRESET_INEFFECTIVE_STRATEGIES,
    PRESET_FORBIDDEN_PATTERNS,
)

logger = logging.getLogger(__name__)


@dataclass
class ExperienceRecord:
    """经验记录"""
    effective_strategies: List[str] = field(default_factory=list)    # 有效策略
    ineffective_strategies: List[str] = field(default_factory=list)  # 无效策略
    forbidden_patterns: List[str] = field(default_factory=list)      # 需避免的模式
    best_practices: List[str] = field(default_factory=list)          # 最佳实践


# 初始提示词模板（小说专用版）
INITIAL_PROMPT = """你是一位资深网文作者，擅长将文字改写得更具"人味"，能够骗过AI检测器。

# 核心任务
将输入的小说片段进行深度改写，保持故事内容不变，但让文字风格更像真人写作。

# 改写六维策略

## 1. 词汇层 - 去AI化
【禁用词】震惊、深邃、璀璨、磅礴、不禁、随即、然而、因此、此外
【禁用词】首先、其次、再次、最后、综上所述、值得注意的是
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
【⚠️ 历史分析对比 - 必须差异化！】
═══════════════════════════════════════
{previous_analysis_summary}

**重要要求**：你的分析必须与上述历史分析不同！
- 如果历史分析提到"标点革命失败"，这次请分析其他维度
- 如果历史分析总是提"句式碎片化有效"，这次请找其他有效点
- 禁止使用与历史分析相同的措辞和结论
- 每次分析必须发现新问题或新洞察

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
   - 人类写作有碎片化表达、倒装、省略

3. **词汇选择**
   - AI偏好书面语、正式词汇
   - 人类使用口语化、方言化、个性化词汇
   - AI喜欢"华丽"词藻，人类用词更朴素直接

4. **过渡词模式化**
   - "首先/其次/此外/然而/因此"是AI标志词
   - 人类用"其实/说白了/反正/话说回来"等口语过渡

5. **情感和主观性**
   - AI文本客观中立，缺乏情感色彩
   - 人类写作带有主观判断、情绪波动、个人偏好

6. **叙述视角**
   - AI保持全知全能的上帝视角
   - 人类有观点偏向、信息盲点、认知局限

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
   - 是否有碎片句、省略句？
   - 是否打破了"主谓宾"的工整结构？

3. **情感层**（最重要！）：
   - 是否还有"他感到xxx"的直接陈述？
   - 是否用身体反应/动作展示情感？
   - 是否还有"心中一凛/眼中闪过"等AI套路？

4. **对话层**：
   - 对话是否口语化？有无语气词（嗯/啊/呢/吧）？
   - 是否有打断、省略、话说一半？
   - 对话是否过于礼貌和完整？

5. **描写层**：
   - 是否还在堆砌形容词？
   - 是否用感官细节替代了抽象描写？
   - 比喻是否过于华丽或连续出现？

6. **结构层**：
   - 是否还有"首先/其次/最后"的三段式？
   - 段落长度是否参差不齐？
   - 是否有适度的"废话"和留白？

7. **🆕 可读性层**（重要保护维度）：
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

1. **七维分析**（六维AI痕迹 + 可读性）：
   - 逐一检查上述七个维度的改写效果
   - 标注每个维度的得分（1-5分）
   - 🆕 特别关注可读性是否受损

2. **成功经验总结**：
   - 成功样本中，哪些改写策略生效了？
   - 是哪个维度的改造贡献最大？
   - 🆕 可读性是否保持良好？

3. **失败原因诊断**：
   - 失败样本为什么效果不好？
   - 改写后仍保留了哪些AI痕迹特征？
   - 🆕 是否存在过度优化导致可读性下降？

4. **策略有效性判断**：
   - 当前提示词中哪些指令是有效的（应保留）？
   - 哪些指令是无效的（应删除或修改）？
   - 🆕 哪些指令可能导致过度优化？

5. **趋势判断**：
   - 得分是否在收敛？还是在震荡？
   - 需要大改还是微调？
   - 🆕 可读性趋势如何？是否在下降？

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

===IMPROVED_PROMPT===
[改进后的完整提示词，要求：
1. 保留有效策略
2. 修正或删除无效策略
3. 增加针对失败样本问题的新指令
4. 包含具体的禁用词汇/句式列表
5. **必须包含标点符号优化的明确指令**：
   - 要求减少句号主导
   - 要求使用问号、感叹号表达情感
   - 要求使用破折号、分号、省略号
   - 要求逗号使用更口语化
6. 如有必要，添加改写示例展示标点变化]
===IMPROVED_PROMPT_END==="""


class MetaOptimizer:
    """元优化器（增强版） - 分析并改进提示词，包含经验累积"""

    def __init__(self):
        self.llm_client = get_llm_client()
        # 累积经验库
        self.experience = ExperienceRecord()
        # 🆕 历史分析记录（用于强制差异化）
        self.previous_analyses: List[str] = []

    def get_initial_prompt(self) -> str:
        """获取初始提示词"""
        return INITIAL_PROMPT

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
        logger.info(f"📚 预置小说专用经验: 有效策略{len(PRESET_EFFECTIVE_STRATEGIES)}条, "
                   f"禁止模式{len(PRESET_FORBIDDEN_PATTERNS)}条")

    def load_historical_experience(self, historical_reports: List[Dict]) -> int:
        """
        从历史经验报告中加载经验（跨批次传承）

        Args:
            historical_reports: 历史经验报告列表

        Returns:
            加载的经验条数
        """
        if not historical_reports:
            return 0

        loaded_count = 0

        # 按时间排序，优先使用最近的经验
        sorted_reports = sorted(
            historical_reports,
            key=lambda x: x.get("created_at", ""),
            reverse=True
        )

        # 只取最近 5 个批次的经验，避免累积过多
        recent_reports = sorted_reports[:5]

        for report in recent_reports:
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
        self.experience.effective_strategies = self.experience.effective_strategies[:15]
        self.experience.ineffective_strategies = self.experience.ineffective_strategies[:15]
        self.experience.forbidden_patterns = self.experience.forbidden_patterns[:10]
        self.experience.best_practices = self.experience.best_practices[:10]

        logger.info(f"📚 从历史加载经验: {loaded_count} 条 (来自 {len(recent_reports)} 个批次)")

        return loaded_count

    async def optimize_prompt(
        self,
        current_version: PromptVersion,
        target_score: int,
        history: List[PromptVersion]
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
        success_samples = [r for r in results if r.success and r.score_reduction > 10]
        failure_samples = [r for r in results if not r.success or r.score_reduction <= 10]

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

        messages = [
            {"role": "system", "content": "你是提示词工程专家，擅长通过分析成功和失败案例来优化提示词。"},
            {"role": "user", "content": optimization_prompt}
        ]

        # 使用 REVIEW_CHECK 任务类型，会自动选择 chat 模型（更快）
        response = await self.llm_client.chat(
            messages=messages,
            task_type=TaskType.REVIEW_CHECK,
            temperature=0.7,
            use_cache=False
        )

        # 解析响应并更新经验库
        improved_prompt, analysis = self._parse_response(response)

        if not improved_prompt:
            logger.warning("⚠️ 无法解析改进后的提示词，使用原提示词")
            improved_prompt = current_version.prompt_text
            analysis = "解析失败，保持原提示词"

        return improved_prompt, analysis

    async def generate_prompt_variants(
        self,
        base_prompt: str,
        num_variants: int = 2
    ) -> List[Tuple[str, str]]:
        """
        🆕 生成多个提示词变体用于A/B测试

        Args:
            base_prompt: 基础提示词
            num_variants: 生成变体数量

        Returns:
            [(变体提示词, 变体描述), ...]
        """
        variants = []

        # 变体策略
        variant_strategies = [
            ("aggressive_punctuation", "激进标点策略：强制要求至少30%的句子使用非句号标点"),
            ("emotion_focus", "情感聚焦策略：将所有情感描写规则权重提升到最高"),
            ("dialogue_extreme", "对话极端口语化：要求对话中必须包含语气词和不完整句"),
            ("short_sentence", "短句主导策略：要求平均句长不超过15字"),
        ]

        for i in range(min(num_variants, len(variant_strategies))):
            strategy_name, strategy_desc = variant_strategies[i]

            # 生成变体提示词
            variant_prompt = await self._generate_variant(base_prompt, strategy_name, strategy_desc)
            if variant_prompt:
                variants.append((variant_prompt, strategy_desc))
                logger.info(f"📝 生成变体 {i+1}: {strategy_name}")

        return variants

    async def _generate_variant(self, base_prompt: str, strategy_name: str, strategy_desc: str) -> str:
        """生成单个变体"""
        messages = [
            {"role": "system", "content": "你是提示词变体生成专家。"},
            {"role": "user", "content": f"""请基于以下提示词生成一个变体版本。

【原始提示词】
{base_prompt[:2000]}...

【变体策略】
{strategy_name}: {strategy_desc}

【要求】
1. 保持原始提示词的核心结构
2. 根据变体策略，强化或弱化某些方面
3. 直接输出变体提示词，不要解释

请输出变体提示词："""}
        ]

        try:
            response = await self.llm_client.chat(
                messages=messages,
                task_type=TaskType.REVIEW_CHECK,
                temperature=0.8,
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
                lines.append(f"""
【失败样本{i}】错误: {r.error}
┌─ 原文 ─────────────────────────────────
│ {r.original_text[:200]}...
└─ 问题：改写过程出错，需要检查提示词是否有歧义
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
        priority_keywords = ["情感", "身体反应", "动作", "标点", "省略号", "问号", "感叹号", "对话", "口语"]

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
                   f"禁止模式{len(self.experience.forbidden_patterns)}条")

        return improved_prompt, analysis

    def get_experience_report(self) -> Dict:
        """获取经验报告"""
        return {
            "effective_strategies": self.experience.effective_strategies,
            "ineffective_strategies": self.experience.ineffective_strategies,
            "forbidden_patterns": self.experience.forbidden_patterns,
            "best_practices": self.experience.best_practices
        }

