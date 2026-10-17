"""提示词进化的独立大模型语义评审。"""
import json
import logging
import re
from typing import Any, Dict, Optional

from core.model_resolution import TaskType, build_thinking_disabled_extra_body

logger = logging.getLogger(__name__)

DIMENSIONS = (
    "semantic_fidelity", "fact_consistency", "information_completeness",
    "readability", "writing_naturalness", "genre_consistency",
)


class SemanticJudge:
    """比较原文与改写文，不评判 AI 生成概率。"""

    # 🔧 2026-10-16：评审置信度下限。此前是 `_normalize` 里的裸字面量 0.6，
    # 引擎侧（版本准入的保真门）需要同一判据来区分「内容有缺陷」与
    # 「评审自己都说不准」。两处各写一份必然漂移，故立为类常量。
    MIN_CONFIDENCE = 0.6

    # 🔧 2026-10-17：三个 hard_fail 阈值提为类常量。
    # 此前是 `_normalize` 里的裸字面量（80 / 90 / 75），与引擎侧版本准入的
    # 保真门各写一份必然漂移（同 MIN_CONFIDENCE 立常量的理由）。
    #
    # 🔧 事实一致性阈值 90 **刻意不上调**，取值依据是本轮 112 个真实评审样本：
    # 分布为 最低 65 / P25 88 / 中位 92 / 最高 100。降到 85 会让样本失格率
    # 从 35.7% 跌到 16.1%、可入围版本从 10 涨到 16 —— 质量门槛基本失效。
    # 真正的缺陷在判据（「任何改变都扣分」把表达扩展当失真），
    # 已在 _system_prompt 的事实层判据中修正，不靠调阈值掩盖。
    MIN_SEMANTIC_FIDELITY = 80
    MIN_FACT_CONSISTENCY = 90
    MIN_INFORMATION_COMPLETENESS = 75

    def __init__(self, llm_client: Any):
        self.llm_client = llm_client

    async def evaluate(self, original: str, rewritten: str, genre: str) -> Dict[str, Any]:
        try:
            # 🔧 评审是 checklist 式清单打分，不依赖深度推理；显式关思考以避免
            #    thinking tokens 吃光 max_tokens 导致 finish_reason=length 截断
            #    JSON（与 meta_optimizer 的同名修复一致）。REVIEW_CHECK 主路由
            #    deepseek-pro 的 YAML 默认 thinking=enabled，需调用方覆盖。
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
    def _system_prompt() -> str:        return """你是独立的中文小说改写质量评审。比较原文和候选改写，不评价AI生成概率。
重点识别否定反转、人物/时间/数量/因果/设定变化、关键信息遗漏、病句和过度重写。
保真评分按四层判据执行：
1事实层（硬，计入fact_consistency）：专名、数字、时空、因果、物品属性（如武器名）、动作姿态。
  只对「真失真」扣分——即改写让读者得到与原文相反或无法回溯到原文的信息：
  专名被改、数字被改、时空矛盾、因果倒置、物品属性改变、凭空新增与原文冲突的设定。
  以下属【表达扩展】，是在原文范围内的合法细化，不构成事实矛盾，
  不计入fact_consistency，按表达层零扣分处理：
  · 泛指变具体（「周围的树木」→「几棵树木」）；
  · 补充了不改变既有事实的动作细节（新增一个修饰性的动作）；
  · 意象同义替换而所指相同（「闪烁嗜血的光芒」→「满是嗜血之意」，事实性质一致）；
  · 原文未交代细节时改写作了不冲突的补白。
  判别口诀：把改写句回填到原文位置，读者对事实的理解会不会被误导？
  会→扣fact_consistency；不会→属表达扩展，不扣。
2命题层（硬，计入semantic_fidelity）：句子断言须等价，包括肯否定、主客关系、数量、程度；段落与句子的出场顺序不属于断言，顺序不同不构成保真损失。
3情绪方向层（计入semantic_fidelity）：情绪极性与强度须不变（悲仍悲、紧张不减）；承载情绪的意象与比喻允许同喻域等义替换，仅意象载体更换而情绪方向一致时不得扣semantic_fidelity；情绪方向或强度明显偏离才扣分；整段删除意象计入information_completeness而非保真。
4表达层（零扣分）：措辞、句法、句长、语序、语域、段落与句子的出场顺序、以及上述表达扩展，属改写的合法操作空间，顺序调整但信息点完整不扣分，表达差异不是缺陷，一律不扣分。
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
        """解析评审响应 JSON，容忍三类真实失败（2026-10-17 取证，80 样本 4 次）。

        🔧 取证：原实现只做「剥 markdown 代码块」一层兜底，实测仍有三类失败：
          1. 响应正文混入裸控制字符 → `Invalid control character at: line 4`
             （JSON 规范不允许字符串内出现裸换行/制表，属**可无损修复**）
          2. 维度写成裸数字（`92` 而非 `{"score": 92}`）→ `xxx不是对象`
             （模型漏写外层对象，属**可无损规范化**）
          3. JSON 前后带解说文字
        这三类失败的共同后果是 `_unavailable` ⇒ 样本被判失格 ⇒
        P15 质量层键被**基础设施噪声**推高，属「用故障冒充质量缺陷」。

        ⚠️ 边界：容错只作用于格式，不放宽任何阈值。越界分数、缺维度、
        非对象根节点仍须照旧抛错（见 TestStillFailsWhenItShould）。
        """
        if not isinstance(response, str):
            raise TypeError("响应不是字符串")
        text = response.strip()
        value = SemanticJudge._loads_lenient(text)
        if not isinstance(value, dict):
            raise TypeError("响应根节点不是对象")
        return SemanticJudge._normalize_shape(value)

    # 🔧 JSON 字符串内允许的转义序列（其余 C0 控制字符一律非法）
    _VALID_ESCAPES = '"\\/bfnrtu'

    @staticmethod
    def _strip_control_chars(text: str) -> str:
        """把 JSON 字符串内出现的裸控制字符替换为对应转义序列（无损）。

        直接删除会粘连词语，替换为 `\\n`/`\\t` 等合法转义才能保留语义。
        控制字符本身在 JSON 语境中没有承载语义，因此这是无损修复。
        """
        out: List[str] = []
        in_string = False
        escaped = False
        for ch in text:
            if in_string:
                if escaped:
                    escaped = False
                    out.append(ch)
                    continue
                if ch == "\\":
                    escaped = True
                    out.append(ch)
                    continue
                if ch == '"':
                    in_string = False
                    out.append(ch)
                    continue
                code = ord(ch)
                if code < 0x20:
                    if ch == "\n":
                        out.append("\\n")
                    elif ch == "\r":
                        out.append("\\r")
                    elif ch == "\t":
                        out.append("\\t")
                    else:
                        out.append(" ")
                    continue
                out.append(ch)
            else:
                if ch == '"':
                    in_string = True
                out.append(ch)
        return "".join(out)

    @staticmethod
    def _first_complete_object(text: str) -> Optional[str]:
        """从第一个 `{` 起做花括号配对扫描，返回**第一个完整对象**的原文。

        🔧 2026-10-17（P18 真实轮次补充）：原先用 `find("{") ... rfind("}")`
        剥离前后杂文，但模型连续输出两个 JSON 时（实测 `Extra data` 失败），
        `rfind("}")` 会取到第二个对象的结尾，把两段都圈进来反而必然失败。
        配对扫描只取第一段，且跳过字符串内的花括号。
        """
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            ch = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]
        return None

    @staticmethod
    def _loads_lenient(text: str) -> Any:
        """按「严格 → 去控制字符 → 剥代码块 → 取首个完整对象」逐级降级解析。"""
        # 1. 直接严格解析（Markdown 代码块先剥掉）
        stripped = text
        match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
        if match:
            stripped = match.group(1)
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

        # 2. 清洗裸控制字符后重试（成因 1：Invalid control character）
        cleaned = SemanticJudge._strip_control_chars(stripped)
        if cleaned != stripped:
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

        # 3. 取首个花括号配对完整的对象（成因 2：Extra data / 前后杂文）
        #    必须配对扫描而非 rfind("}")：连续两个 JSON 时 rfind 会圈进两个对象。
        for candidate in (cleaned, stripped):
            obj = SemanticJudge._first_complete_object(candidate)
            if obj is None:
                continue
            try:
                return json.loads(obj)
            except json.JSONDecodeError:
                repaired = SemanticJudge._strip_control_chars(obj)
                if repaired != obj:
                    try:
                        return json.loads(repaired)
                    except json.JSONDecodeError:
                        pass

        # 4. 交回原始异常，保持既有失败语义（浅层语法错如缺逗号不在容错范围，
        #    那类需要重试调用模型而非在解析层猜补）
        return json.loads(stripped)

    @staticmethod
    def _normalize_shape(value: Dict[str, Any]) -> Dict[str, Any]:
        """把「维度写成裸数字/裸字符串」的常见漏写补成标准结构（成因 2）。

        只补形状，不改分数：数值原样保留，越界仍由 `_normalize` 拒绝。
        """
        for name in DIMENSIONS:
            dimension = value.get(name)
            if isinstance(dimension, dict):
                continue
            if isinstance(dimension, (int, float)) and not isinstance(dimension, bool):
                value[name] = {"score": dimension, "reason": "", "issues": []}
        risk = value.get("over_rewrite_risk")
        if isinstance(risk, str):
            value["over_rewrite_risk"] = {"level": risk, "reason": "", "issues": []}
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
        if result["semantic_fidelity"]["score"] < SemanticJudge.MIN_SEMANTIC_FIDELITY:
            reasons.append(f"语义保真度低于{SemanticJudge.MIN_SEMANTIC_FIDELITY}")
        if result["fact_consistency"]["score"] < SemanticJudge.MIN_FACT_CONSISTENCY:
            reasons.append(f"事实一致性低于{SemanticJudge.MIN_FACT_CONSISTENCY}")
        if result["information_completeness"]["score"] < SemanticJudge.MIN_INFORMATION_COMPLETENESS:
            reasons.append(f"信息完整度低于{SemanticJudge.MIN_INFORMATION_COMPLETENESS}")
        if risk == "high":
            reasons.append("过度改写风险高")
        if confidence < SemanticJudge.MIN_CONFIDENCE:
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

    2026-08-23 黄金对照实验后，2026-08-27 格式复验确认：当时的"证伪"
    实为格式假象——TMS 对段落空格/开头空行敏感（真人文本加空行即判
    97/Block），格式干净后真人与 AI 均得 0，无真阳性能力；TMS 已于
    2026-08-27 全库移除，权重清零（保留参数兼容调用方，不再参与计分）。
    主信号：语义人感 writing_naturalness
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
