# -*- coding: utf-8 -*-
"""百炼 decision-model-preview 决策模型客户端单测（假传输，不触网）。

契约来源：百炼《决策模型 API》systemone 接口（POST /compatible-mode/v1/systemone）。
客户端同时实现 IntentClassifier（2 图歧义 choice）与 ContentRiskScorer（noul）两个 Port；
任何解析/传输失败直接抛异常，由编排层既有兜底处理（保守回退 / fail-open）。
"""
import pytest

from router_gateway.adapters.base import RetriableTransportError
from router_gateway.catalog import Mode
from router_gateway.catalog.intent import ModeDecision
from router_gateway.decision import DecisionModelClient, DecisionModelError
from router_gateway.orchestrator.service import ContentRiskDecision

_BASE = "https://ws-1.cn-beijing.maas.aliyuncs.com/compatible-mode"


class FakeTransport:
    def __init__(self, status=200, body=None, exc=None):
        self.status = status
        self.body = body or {}
        self.exc = exc
        self.calls = []

    def request(self, method, url, headers=None, body=None, timeout=60):
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "body": body, "timeout": timeout})
        if self.exc is not None:
            raise self.exc
        return self.status, self.body


def _client(transport):
    return DecisionModelClient(base_url=_BASE, api_key="sk-test", transport=transport)


def test_classify_mode发choice请求并解析模式与置信度():
    transport = FakeTransport(body={"answers": {"intent_mode": {
        "type": "choice", "choice": "first_last_frame", "confidence": 0.91,
        "probabilities": {"first_last_frame": 0.91, "multi_image": 0.09}}}})
    client = _client(transport)

    decision = client.classify_mode(
        "第一张图开场，最后一张图收尾，中间补全运动过程",
        image_count=2, candidates=(Mode.FIRST_LAST_FRAME, Mode.MULTI_IMAGE))

    assert decision == ModeDecision(Mode.FIRST_LAST_FRAME, 0.91)
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == _BASE + "/v1/systemone"
    assert call["headers"]["Authorization"] == "Bearer sk-test"
    assert call["body"]["model"] == "decision-model-preview"
    assert call["body"]["state"] == {
        "prompt": "第一张图开场，最后一张图收尾，中间补全运动过程",
        "image_count": 2}
    question = call["body"]["questions"]["intent_mode"]
    assert question["type"] == "choice"
    assert set(question["criteria"]) == {"first_last_frame", "multi_image"}


def test_classify_mode候选项以外的返回值抛错交上层兜底():
    transport = FakeTransport(body={"answers": {"intent_mode": {
        "type": "choice", "choice": "text_to_video", "confidence": 0.8}}})
    client = _client(transport)
    with pytest.raises(Exception):
        client.classify_mode(
            "参考这些图的画风", image_count=2,
            candidates=(Mode.FIRST_LAST_FRAME, Mode.MULTI_IMAGE))


def test_score_risk发noul请求并解析违规概率():
    transport = FakeTransport(body={"answers": {"content_risk": {
        "type": "noul", "noul": 0.97}}})
    client = _client(transport)

    decision = client.score_risk("一段正常的风景提示词")

    assert decision == ContentRiskDecision(score=0.97)
    question = transport.calls[0]["body"]["questions"]["content_risk"]
    assert question["type"] == "noul"
    assert transport.calls[0]["body"]["state"] == "一段正常的风景提示词"


def test_HTTP非200抛DecisionModelError():
    client = _client(FakeTransport(status=429, body={"code": "Throttling"}))
    with pytest.raises(DecisionModelError):
        client.score_risk("测试")


def test_传输层异常原样传播():
    client = _client(FakeTransport(exc=RetriableTransportError("timeout")))
    with pytest.raises(RetriableTransportError):
        client.score_risk("测试")


def test_响应缺少答案字段抛错():
    client = _client(FakeTransport(body={"answers": {}}))
    with pytest.raises(Exception):
        client.score_risk("测试")
