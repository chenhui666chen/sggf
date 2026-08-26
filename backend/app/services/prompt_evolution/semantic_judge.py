"""提示词进化的独立大模型语义评审。"""
import json
import logging
import re
from typing import Any, Dict

from core.model_resolution import TaskType, build_thinking_disabled_extra_body

logger = logging.getLogger(__name__)

DIMENSIONS = (
    "semantic_fidelity", "fact_consistency", "information_completeness",
    "readability", "writing_naturalness", "genre_consistency",
)


class SemanticJudge:
    """比较原文与改写文，不评判 AI 生成概率。"""

    def __init__(self, llm_client: Any):
        self.llm_client = llm_client

    async def evaluate(self, original: str, rewritten: str, genre: str) -> Dict[str, Any]:
        try:
            # 🔧 评审是 checklist 式清单打分，不依赖深度推理；显式关思考以避免
            #    thinking tokens 吃光 max_tokens 导致 finish_reason=length 截断
            #    JSON（与 meta_optimizer 的同名修复一致）。REVIEW_CHECK 主路由
            #    deepseek-v4-pro 的 YAML 默认 thinking=enabled，需调用方覆盖。
            #    参数按模型族分发（doubao 系拒绝 reasoning_effort+thinking 同传）。
            response = await self.llm_client.chat(
                messages=[
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": self._user_prompt(original, rewritten, genre)},
                ],
                task_type=TaskType.REVIEW_CHECK,
                temperature=0.0,
                use_cache=False,
                extra_body=build_thinking_disabled_extra_body(),
            )
            return self._normalize(self._parse_json(response))
        except (json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
            logger.warning("提示词进化语义评审返回无效: %s", exc)
            return self._unavailable("评审模型返回格式无效")
        except Exception as exc:
            logger.warning("提示词进化语义评审调用失败: %s", exc)
            return self._unavailable(f"评审模型调用失败: {exc}")

    @staticmethod
    def _system_prompt() -> str:
        return """你是独立的中文小说改写质量评审。比较原文和候选改写，不评价AI生成概率。
重点识别否定反转、人物/时间/数量/因果/设定变化、关键信息遗漏、病句和过度重写。
保真评分按四层判据执行：
1事实层（硬，计入fact_consistency）：专名、数字、时空、因果、物品属性（如武器名）、动作姿态，任何改变都扣分。
2命题层（硬，计入semantic_fidelity）：句子断言须等价，包括肯否定、主客关系、数量、程度；段落与句子的出场顺序不属于断言，顺序不同不构成保真损失。
3情绪方向层（计入semantic_fidelity）：情绪极性与强度须不变（悲仍悲、紧张不减）；承载情绪的意象与比喻允许同喻域等义替换，仅意象载体更换而情绪方向一致时不得扣semantic_fidelity；情绪方向或强度明显偏离才扣分；整段删除意象计入information_completeness而非保真。
4表达层（零扣分）：措辞、句法、句长、语序、语域、段落与句子的出场顺序属改写的合法操作空间，顺序调整但信息点完整不扣分，表达差异不是缺陷，一律不扣分。
语病、生造词（如“上个古遗迹”）计入readability或writing_naturalness，不计入fact_consistency。
所有分数为0-100且越高越好。只输出合法JSON，不要Markdown。每个维度必须包含score、reason、issues。
六个评分维度格式固定为：{"score": 数值, "reason": "原因", "issues": []}。
over_rewrite_risk格式固定为：{"level": "low|medium|high", "reason": "原因", "issues": []}。
confidence必须是0-1数值。输出字段：semantic_fidelity、fact_consistency、information_completeness、readability、writing_naturalness、genre_consistency、over_rewrite_risk、confidence。"""

    @staticmethod
    def _user_prompt(original: str, rewritten: str, genre: str) -> str:
        return f"""题材：{genre or '通用'}

【原文】
{original[:5000]}

【候选改写】
{rewritten[:5000]}

按约定JSON结构评价。严格按四层判据归类扣分：事实与命题变化才扣保真；情绪意象同喻域替换不扣保真；措辞、句法、句长等表达差异零扣分。"""

    @staticmethod
    def _parse_json(response: Any) -> Dict[str, Any]:
        if not isinstance(response, str):
            raise TypeError("响应不是字符串")
        text = response.strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if not match:
                raise
            value = json.loads(match.group(1))
        if not isinstance(value, dict):
            raise TypeError("响应根节点不是对象")
        return value

    @staticmethod
    def _normalize(payload: Dict[str, Any]) -> Dict[str, Any]:
        result: Dict[str, Any] = {"available": True}
        for name in DIMENSIONS:
            dimension = payload[name]
            if not isinstance(dimension, dict):
                raise TypeError(f"{name}不是对象")
            score = float(dimension["score"])
            if not 0 <= score <= 100:
                raise ValueError(f"{name}分数越界")
            issues = dimension.get("issues", [])
            if not isinstance(issues, list):
                raise TypeError(f"{name}.issues不是数组")
            result[name] = {
                "score": score,
                "reason": str(dimension.get("reason", ""))[:300],
                "issues": [str(issue)[:300] for issue in issues[:5]],
            }

        raw_risk = payload.get("over_rewrite_risk", "medium")
        raw_confidence = payload.get("confidence", 0.0)
        risk_reason = ""
        risk_value = raw_risk
        if isinstance(raw_risk, dict):
            risk_value = raw_risk.get(
                "level",
                raw_risk.get("risk", raw_risk.get("value", raw_risk.get("score"))),
            )
            risk_reason = str(raw_risk.get("reason", ""))[:500]
        try:
            risk = SemanticJudge._normalize_risk(risk_value)
            confidence = SemanticJudge._normalize_confidence(raw_confidence)
        except ValueError as exc:
            raise ValueError(
                f"风险或置信度无效: over_rewrite_risk={raw_risk!r}, confidence={raw_confidence!r}"
            ) from exc

        reasons = []
        if result["semantic_fidelity"]["score"] < 80:
            reasons.append("语义保真度低于80")
        if result["fact_consistency"]["score"] < 90:
            reasons.append("事实一致性低于90")
        if result["information_completeness"]["score"] < 75:
            reasons.append("信息完整度低于75")
        if risk == "high":
            reasons.append("过度改写风险高")
        if confidence < 0.6:
            reasons.append("评审置信度不足")
        result.update({
            "over_rewrite_risk": risk, "confidence": confidence,
            "over_rewrite_reason": risk_reason,
            "hard_fail": bool(reasons), "hard_fail_reasons": reasons,
        })
        return result

    @staticmethod
    def _normalize_risk(value: Any) -> str:
        text = str(value).strip().lower()
        compact = re.sub(r"[\s_-]+", "", text)
        aliases = {
            "low": "low", "lowrisk": "low", "低": "low", "较低": "low", "低风险": "low",
            "medium": "medium", "moderate": "medium", "mediumrisk": "medium",
            "中": "medium", "中等": "medium", "中风险": "medium", "中等风险": "medium",
            "high": "high", "highrisk": "high", "高": "high", "较高": "high", "高风险": "high",
        }
        normalized = aliases.get(compact)
        if normalized is None:
            raise ValueError("无法识别风险等级")
        return normalized

    @staticmethod
    def _normalize_confidence(value: Any) -> float:
        if isinstance(value, bool):
            raise ValueError("布尔值不是有效置信度")
        text = str(value).strip()
        is_percent = text.endswith("%")
        if is_percent:
            text = text[:-1].strip()
        confidence = float(text)
        if is_percent or 1 < confidence <= 100:
            confidence /= 100
        if not 0 <= confidence <= 1:
            raise ValueError("置信度越界")
        return confidence

    @staticmethod
    def _unavailable(error: str) -> Dict[str, Any]:
        return {"available": False, "hard_fail": False, "hard_fail_reasons": [], "error": error}


def calculate_hybrid_score(ai_score: float, local_score: float, review: Dict[str, Any]) -> float:
    """将朱雀、本地规则和语义评审归一为越低越好的成本分。

    2026-08-23 黄金对照实验证伪 TMS：GPT人工化金标准(朱雀0%) TMS=97、
    AI原文 TMS=0、用户手写 TMS=92、金庸 TMS=0——TMS 是文风分类器
    (长句文学腔→0/短句网文腔→高)，与真实AI痕迹反向且与题材强相关，
    任何正向权重都会把优化方向拉向"文学腔"，故权重清零（保留参数
    兼容调用方，不再参与计分）。主信号：语义人感 writing_naturalness
    (0.20)、genre_consistency(0.15)、over_rewrite_risk(0.10 加项)、
    事实/保真维度，控制"自然化不得以失真为代价"。
    """
    if not review.get("available"):
        return local_score

    def _d(key: str) -> float:
        v = review.get(key)
        return v.get("score", 100) if isinstance(v, dict) else 100.0

    over = str(review.get("over_rewrite_risk", "low")).strip().lower()
    over_cost = {"low": 0, "medium": 25, "high": 60}.get(over, 0)

    score = (
        (100 - _d("semantic_fidelity")) * 0.20
        + (100 - _d("fact_consistency")) * 0.15
        + (100 - _d("information_completeness")) * 0.15
        + (100 - _d("readability")) * 0.05
        + (100 - _d("writing_naturalness")) * 0.20
        + (100 - _d("genre_consistency")) * 0.15
        + local_score * 0.10
        + over_cost * 0.10
    )
    return max(0.0, min(100.0, score))
