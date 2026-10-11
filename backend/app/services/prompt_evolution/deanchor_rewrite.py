"""
去锚定重新生成（De-anchored Regeneration）

## 为什么需要它

项目原有的降 AI 率范式是「提示词 + 原文 → 改写」。2026-10-08 用真实朱雀网关做的
受控实验（10 组）表明，该范式存在天花板：

| 方案                       | AI 判定占比 | 疑似占比 | 人工占比 |
|----------------------------|-------------|----------|----------|
| 原文                       | 100%        | 0%       | 0%       |
| 单次改写（5 个模型）       | 50%~100%    | 0~50%    | 0%       |
| 多轮迭代（2 轮后饱和）     | 50.4%       | 49.6%    | 0%       |
| 自蒸馏（模仿人工段）       | 75.3%       | 24.7%    | 0%       |
| **去锚定重新生成 + 1 轮**  | **0%**      | **100%** | 0%       |
| 人类写作基线               | 0%          | 0%       | 100%     |

根因：让模型「改写」时，原文的措辞与 token 分布会锚定输出，改写结果仍落在 LLM 分布内，
检测器照判 AI。先压成事实要点、再据要点重写，可切断这层锚定。

## 实测结论（工程据此设参）

- 去锚定 + 1 轮迭代质量合格：语义保真 92 / 事实一致 96 / 信息完整 88，hard_fail=False
- 迭代收益在第 2 轮后归零（50.4% → 50.5% → 50.4%），故 `second_round` 默认仅 1 轮

## ⚠️ 已废弃的旧结论（2026-10-08 订正，勿再引用）

原注释写过「『人工』判定是真人写作的领地，LLM 上限为 100% 疑似」。该结论已被证伪：
同一模型在同一批 AI 源文本上多次稳定产出「人工」判定段落且质量达标，见下。

正确表述：**「人工」判定可以在满足项目质量门槛的前提下达成，但高度依赖「模型 × 样本」组合，
不可迁移。** 因此优化目标仍应取 ai_ratio（确定AI占比，越低越好），
而不是指望 human_ratio 稳定提升 —— 前者在所有样本上都 reproducible，后者只在特定组合上出现。

## ❌ 已验证无效的三条路（别再试，均有对照数据）

1. **往重写提示词里堆风格指令**（名家语域 / 统计特征如"句长要大起大落、多用破折号和语气词"）
   → 实验13（24 组）：人工占比恒为 0.000，且主指标**变差**（fantasy 上 AI 占比 0.19 → 0.55/0.64）。
   风格指令会挤占事实约束的注意力预算，质量与 AI 指标双输。
2. **提高采样温度 / 调 top_p**（想抬高困惑度骗过检测器）
   → 实验14（16 组）：AI 占比 0.190 / 0.213 / 0.217 / 0.162，全在噪声内；T1.2 且让质量合格率减半。
3. **强制篇幅对齐**（假设"压缩=丢掉人类式的冗余"）
   → 实验15（16 组）：整体无单调关系。同一个 85%~100% 篇幅在 scifi 样本上让人工占比升到 0.19，
   在 fantasy 样本上反而把 AI 占比从 0.29 推到 0.69。篇幅不是自变量。

## 唯一被反复验证有效的手段

**保持本文件"裸"的去锚定提示词 + 选对模型。** 多模型淘汰赛（9 模型 8 轮 75 次生成）显示：
`doubao-seed-evolving` 是唯一能反复把确定AI占比打到 0.000 且质量合格的模型，
且在 scifi_001 上三次独立复现「AI=0.000 / 人工≈0.17~0.20 / 语义96 / 事实100 / 信息97」。
模型选择 ≫ 提示词微调。
"""
from typing import Any, Optional

from core.unified_llm_client import get_llm_client
from core.model_resolution import build_thinking_disabled_extra_body

# 要点抽取：必须精简且不成句，否则等于把原文重写一遍，去锚定失效
#
# ⚠️ 事实完整性是去锚定的主要风险点（2026-10-08 多模型淘汰赛实测）：
# 重新生成时模型易改动数值、专名与因果，导致 fact_consistency 跌破 90 门槛而整批 hard_fail。
# 故要点阶段强制逐项锁死数字/专名/对白，且上限随原文长度放宽（900 字对长文不够用）。
OUTLINE_PROMPT = (
    "请把下面的文本压缩成一份事实要点清单（控制在 {limit} 字以内）。\n"
    "只列：人物及其身份、时间、地点、事件先后、因果关系、专有名词、对白原文。\n"
    "【必须逐项照抄、不得改写或省略】\n"
    "- 所有数字与数量：百分比、金额、年龄、时长、距离、排名、编号；\n"
    "- 所有专有名词：人名、地名、门派、功法、兵器、丹药、机构、称谓；\n"
    "- 所有对白原文。\n"
    "遗漏或改动上述任一项，后续重写会被判定为不合格。\n"
    "硬性要求：不要用完整句子复述情节，不要保留原文措辞、修辞、解释和总结，"
    "用最朴素的短语或极短句罗列。清单本身不追求通顺。\n"
    "【输出】只输出要点清单。\n【原文】\n"
)

REWRITE_PROMPT = (
    "你是一位小说作者。请只根据下面这份事实要点，把这个场景重新写成小说正文。\n"
    "要求：\n"
    "1. 不要复述要点清单，要写成有对白、有人物行动的完整叙事。\n"
    "2. 信息跟着人物的行动和当下需要处理的事情出现，不要按「时间—地点—人物—设定」依次交代。\n"
    "3. 不要替读者解释、总结、下结论；事实自己会形成逻辑。\n"
    "4. 不要机械切短句，不要每句都单独成段；普通叙述写成完整句。\n"
    "5. 篇幅要写足：目标约 {target} 字，与要点信息量相称，不要压缩成梗概。\n"
    "【事实底线（逐项核对，违反即不合格）】\n"
    "- 所有数字与数量必须原样保留：百分比、金额、年龄、时长、距离、排名、编号；\n"
    "- 所有专有名词必须原样保留：人名、地名、门派、功法、兵器、丹药、机构、称谓；\n"
    "- 对白内容不得改写或增删；事件先后与因果关系不得改变；\n"
    "- 不得新增原文没有的动作、物件、心理或设定。\n"
    "【输出】只输出正文，不要标题、说明或 Markdown。\n【事实要点】\n"
)

SECOND_ROUND_PROMPT = (
    "下面是一版已经重写过的小说正文，仍残留模型的加工痕迹。请再做一轮重构：\n"
    "1. 仍然在替读者解释、总结、下结论的句子，直接删掉，不要换说法再写一遍。\n"
    "2. 仍然按「时间—地点—人物—设定」依次交代的段落，改成让信息跟着人物行动自然出现。\n"
    "3. 已经自然的句子原样保留，不要为了改而改，不要机械切短句。\n"
    "4. 篇幅必须写足：目标约 {target} 字。绝不允许压缩成梗概或删减信息密集段——\n"
    "   实测去锚定天然倾向压缩（部分模型产出仅原文的 49%），会被篇幅守门判死。\n"
    "【事实底线】人名、地名、时间、数量、事件先后、因果关系、专有名词不得改变；"
    "不得新增原文没有的动作、物件、心理或设定。\n"
    "【输出】只输出正文，不要标题、说明或 Markdown。\n【待改正文】\n"
)

SYSTEM_PROMPT = "你是一位资深中文小说编辑。"

# 空响应重试上限：思考型模型（step 系实测）在 max_tokens 被 reasoning tokens 吃光时
# 会返回 finish_reason=length 的空响应，需关思考并重试
MAX_EMPTY_RETRY = 3


class DeanchorRewriter:
    """两阶段去锚定重写：原文 → 事实要点 → 重新生成正文。"""

    def __init__(self, model_id: Optional[str] = None, llm_client: Optional[Any] = None):
        # llm_client 可注入：调用方（如 PromptEvaluator）应传入自己的 client，
        # 避免绕过其缓存/代理/测试替身（2026-10-08 实测：自建 client 会让
        # evaluator 的 llm_client mock 失效，导致 8 个改写链路测试失败）
        self.model_id = model_id
        self.llm_client = llm_client

    async def _chat(self, prompt: str, text: str, temperature: float = 0.8) -> str:
        client = self.llm_client or get_llm_client()
        kwargs = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"{prompt}{text}"},
            ],
            "model": self.model_id,
            "temperature": temperature,
            "max_tokens": 8192,
        }
        # 🔧 改写链路统一关思考（与 evaluator/ai_trace_competition 保持一致）：
        # 风格转换任务无深度推理收益，思考常开会吃掉 max_tokens 预算导致空响应
        try:
            kwargs["extra_body"] = build_thinking_disabled_extra_body(self.model_id)
        except Exception:
            pass

        result = ""
        for _ in range(MAX_EMPTY_RETRY):
            result = await client.chat(**kwargs) or ""
            if result.strip():
                return result
        return result

    async def extract_outline(self, text: str) -> str:
        """阶段一：把原文压成事实要点，切断原文措辞的锚定。"""
        # 上限随原文长度放宽：900 字对 3000+ 字的文本装不下全部数值与专名，
        # 实测会因要点缺项导致重写后 fact_consistency 跌破 90。
        limit = min(2000, max(900, int(len(text) * 0.5)))
        return (await self._chat(
            OUTLINE_PROMPT.format(limit=limit), text, temperature=0.3
        )).strip()

    async def rewrite(
        self,
        text: str,
        target_length: Optional[int] = None,
        second_round: bool = True,
        temperature: float = 0.8,
        targeted_hint: str = "",
    ) -> str:
        """阶段二：据要点重写；可选再迭代 1 轮（实测第 2 轮后收益归零）。"""
        target = target_length or len(text)
        outline = await self.extract_outline(text)
        if not outline:
            return ""

        # 定点消除指令（深区样本预检命中时由调用方传入）必须透传，
        # 否则去锚定会丢掉定向修复能力
        rewrite_prompt = REWRITE_PROMPT.format(target=target)
        if targeted_hint:
            rewrite_prompt = f"{rewrite_prompt}\n【定点消除指令】\n{targeted_hint}\n"

        result = (await self._chat(
            rewrite_prompt, outline, temperature=temperature
        )).strip()

        # 🔧 篇幅守卫重试：部分模型（step 系实测产出仅 266 字）会中途截断，
        # 短于目标一半时重试一次并取较长者，避免后续被篇幅守门直接判死
        if len(result) < target * 0.5:
            retry = (await self._chat(
                rewrite_prompt, outline, temperature=temperature
            )).strip()
            if len(retry) > len(result):
                result = retry

        if second_round and result:
            rewritten = (await self._chat(
                SECOND_ROUND_PROMPT.format(target=target), result, temperature=temperature
            )).strip()
            # 迭代轮若产出异常短的文本，视为回退信号，保留第一轮结果
            if len(rewritten) >= len(result) * 0.6:
                result = rewritten
        return result
