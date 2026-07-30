"""提示词进化的独立大模型语义评审。"""
import json
import logging
import re
from typing import Any, Dict

from core.model_resolution import TaskType

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
            response = await self.llm_client.chat(
                messages=[
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": self._user_prompt(original, rewritten, genre)},
                ],
                task_type=TaskType.REVIEW_CHECK,
                temperature=0.0,
                use_cache=False,
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

按约定JSON结构评价。不要因措辞不同扣分，只有语义、事实、信息或阅读质量变化才扣分。"""

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
    """将朱雀、本地规则和语义评审归一为越低越好的成本分。"""
    if not review.get("available"):
        return local_score
    score = (
        ai_score * 0.35
        + (100 - review["semantic_fidelity"]["score"]) * 0.20
        + (100 - review["fact_consistency"]["score"]) * 0.10
        + (100 - review["information_completeness"]["score"]) * 0.10
        + (100 - review["readability"]["score"]) * 0.10
        + (100 - review["writing_naturalness"]["score"]) * 0.10
        + local_score * 0.05
    )
    return max(0.0, min(100.0, score))
