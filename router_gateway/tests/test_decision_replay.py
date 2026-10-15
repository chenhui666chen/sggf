# -*- coding: utf-8 -*-
"""决策模型离线回放探针单测：只算准确率出报告，不触碰主链路。"""
from dataclasses import dataclass

from router_gateway.catalog import Mode
from router_gateway.catalog.intent import ModeDecision
from router_gateway.decision.replay import (
    ReplayCase,
    evaluate_classifier,
    evaluate_risk,
)
from router_gateway.orchestrator.service import ContentRiskDecision


@dataclass
class _FakeClassifier:
    answers: dict
    error: Exception | None = None

    def classify_mode(self, prompt, *, image_count, candidates):
        if self.error is not None:
            raise self.error
        return self.answers[prompt]


@dataclass
class _FakeScorer:
    answers: dict
    error: Exception | None = None

    def score_risk(self, prompt):
        if self.error is not None:
            raise self.error
        return self.answers[prompt]


def test_歧义分类全部判对时报告准确率1并过95门槛():
    cases = [
        ReplayCase("以第一张图为开头、最后一张图为结尾补全视频", Mode.FIRST_LAST_FRAME),
        ReplayCase("参考这两张图的画风和角色生成一段视频", Mode.MULTI_IMAGE),
    ]
    client = _FakeClassifier({
        cases[0].prompt: ModeDecision(Mode.FIRST_LAST_FRAME, 0.9),
        cases[1].prompt: ModeDecision(Mode.MULTI_IMAGE, 0.8),
    })
    report = evaluate_classifier(client, cases)
    assert report["total"] == 2 and report["correct"] == 2
    assert report["accuracy"] == 1.0
    assert report["threshold_passed"] is True


def test_歧义分类有判错时准确率如实计算且不过门槛():
    cases = [
        ReplayCase("首尾帧补全", Mode.FIRST_LAST_FRAME),
        ReplayCase("多图参考", Mode.MULTI_IMAGE),
    ]
    client = _FakeClassifier({
        "首尾帧补全": ModeDecision(Mode.FIRST_LAST_FRAME, 0.9),
        "多图参考": ModeDecision(Mode.FIRST_LAST_FRAME, 0.7),  # 判错
    })
    report = evaluate_classifier(client, cases)
    assert report["accuracy"] == 0.5
    assert report["threshold_passed"] is False
    wrong = report["items"][1]
    assert wrong["correct"] is False
    assert wrong["expected"] == "multi_image"
    assert wrong["predicted"] == "first_last_frame"


def test_分类器抛错时记为判错且探针不中断():
    cases = [ReplayCase("会报错的提示词", Mode.MULTI_IMAGE)]
    report = evaluate_classifier(
        _FakeClassifier({}, error=RuntimeError("500")), cases)
    assert report["total"] == 1 and report["correct"] == 0
    assert report["items"][0]["error"] is not None


def test_风险评分按探针阈值0点5比对期望标签():
    safe = ReplayCase("雪山日出航拍", False)
    risky = ReplayCase("违规内容描述", True)
    report = evaluate_risk(_FakeScorer({
        "雪山日出航拍": ContentRiskDecision(0.02),
        "违规内容描述": ContentRiskDecision(0.97),
    }), [safe, risky])
    assert report["accuracy"] == 1.0
    assert report["threshold_passed"] is True
