# -*- coding: utf-8 -*-
"""阿里云百炼 decision-model-preview 决策模型客户端。

一个客户端同时承担编排器的两个辅助决策 Port（见 docs 路由指南 §7.3）：
- IntentClassifier.classify_mode：仅"恰好 2 图"歧义时调用（choice 题）；
- ContentRiskScorer.score_risk：提交前违规概率（noul 题，P(yes)=违规概率）。

接口契约：POST {base_url}/v1/systemone，一次前向返回各问题答案，不生成文本。
任何 HTTP 非 200 / 传输异常 / 响应缺字段均向上抛错，由调用方按既有约定处理
（意图仲裁保守回退 multi_image；风险闸门 fail-open），客户端自身不做静默降级。
"""
from __future__ import annotations

from typing import Optional

from ..adapters.base import UrllibTransport
from ..catalog import Mode
from ..catalog.intent import ModeDecision
from ..orchestrator.service import ContentRiskDecision

_MODEL = "decision-model-preview"

# 歧义模式选项的中文判据（选项名必须等于 Mode.value，供答案直接反解）
_MODE_CRITERIA = {
    Mode.FIRST_LAST_FRAME: "首尾帧补全：用户给出开头画面与结尾画面，要求生成中间运动过程",
    Mode.MULTI_IMAGE: "多图参考：用户提供若干参考图，要求参考其风格、角色、场景或元素生成视频",
}

_MODE_QUESTION_ID = "intent_mode"
_RISK_QUESTION_ID = "content_risk"
_RISK_INSTRUCTION = (
    "该视频生成提示词是否可能生成色情、暴力、血腥、违法或平台禁止的内容？"
    "确定安全回答否，明确违规回答是，拿不准则倾向否。")


class DecisionModelError(Exception):
    """决策模型返回非 200 或响应体不可用。"""


class DecisionModelClient:
    def __init__(self, *, base_url: str, api_key: str,
                 transport=None, model: str = _MODEL, timeout: int = 30):
        # base_url 形如 https://{workspace}.cn-beijing.maas.aliyuncs.com/compatible-mode
        self._url = base_url.rstrip("/") + "/v1/systemone"
        self._api_key = api_key
        self._http = transport or UrllibTransport()
        self._model = model
        self._timeout = timeout

    def _ask(self, state, questions: dict) -> dict:
        status, body = self._http.request(
            "POST", self._url,
            headers={"Authorization": f"Bearer {self._api_key}",
                     "Content-Type": "application/json"},
            body={"model": self._model, "state": state, "questions": questions},
            timeout=self._timeout)
        if status != 200:
            raise DecisionModelError(f"decision-model HTTP {status}: {body!r}")
        answers = body.get("answers")
        if not isinstance(answers, dict):
            raise DecisionModelError(f"响应缺少 answers 对象: {body!r}")
        return answers

    # ---------- IntentClassifier Port ----------

    def classify_mode(self, prompt: str, *, image_count: int,
                      candidates: tuple[Mode, ...]) -> ModeDecision:
        criteria = {mode.value: _MODE_CRITERIA[mode] for mode in candidates}
        answers = self._ask(
            {"prompt": prompt, "image_count": image_count},
            {_MODE_QUESTION_ID: {
                "type": "choice",
                "instructions": "用户用两张图生成视频，意图是首尾帧补全还是多图参考？",
                "criteria": criteria}})
        answer = answers[_MODE_QUESTION_ID]
        # 未知选项名会抛 ValueError，交由 resolve_mode 捕获后保守回退
        return ModeDecision(mode=Mode(answer["choice"]),
                            confidence=float(answer["confidence"]))

    # ---------- ContentRiskScorer Port ----------

    def score_risk(self, prompt: str) -> ContentRiskDecision:
        answers = self._ask(
            prompt,
            {_RISK_QUESTION_ID: {"type": "noul",
                                 "instructions": _RISK_INSTRUCTION}})
        answer = answers[_RISK_QUESTION_ID]
        return ContentRiskDecision(score=float(answer["noul"]))
