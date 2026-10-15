# -*- coding: utf-8 -*-
"""决策模型离线回放探针：喂标注样本，只产出准确率报告，绝不接主路径。

上生产门槛（docs 路由指南 §7.3）：2 图歧义模式判定准确率 ≥ 0.95 才允许注入
Orchestrator；未达门槛维持 resolve_mode 保守回退（multi_image）。
探针自身不做任何接线决策，报告交给人判断。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..catalog import Mode

# 上生产准确率门槛
GATE_ACCURACY = 0.95
# 风险探针内部把 P(违规) 二值化的分界（仅用于回放统计，不影响线上 0.9 阻断阈值）
RISK_PROBE_THRESHOLD = 0.5

_AMBIGUOUS_CANDIDATES = (Mode.FIRST_LAST_FRAME, Mode.MULTI_IMAGE)


@dataclass(frozen=True)
class ReplayCase:
    prompt: str
    # 分类回放期望 Mode；风险回放期望 bool（True=违规）
    expected: object
    name: Optional[str] = None


def _summarize(items: list[dict], gate: float) -> dict:
    total = len(items)
    correct = sum(1 for item in items if item["correct"])
    accuracy = correct / total if total else 0.0
    return {"total": total, "correct": correct, "accuracy": accuracy,
            "gate": gate, "threshold_passed": total > 0 and accuracy >= gate,
            "items": items}


def evaluate_classifier(client, cases: list[ReplayCase], *,
                        image_count: int = 2,
                        candidates=_AMBIGUOUS_CANDIDATES,
                        gate: float = GATE_ACCURACY) -> dict:
    """对 2 图歧义分类器做标注回放；单次判错/异常都计入错误，不中断整批评测。"""
    items = []
    for case in cases:
        item = {"name": case.name or case.prompt[:20],
                "expected": case.expected.value, "predicted": None,
                "confidence": None, "correct": False, "error": None}
        try:
            decision = client.classify_mode(
                case.prompt, image_count=image_count, candidates=tuple(candidates))
            item["predicted"] = decision.mode.value
            item["confidence"] = decision.confidence
            item["correct"] = decision.mode is case.expected
        except Exception as exc:  # 探针必须跑完所有样本
            item["error"] = f"{type(exc).__name__}: {exc}"
        items.append(item)
    return _summarize(items, gate)


def evaluate_risk(client, cases: list[ReplayCase], *,
                  probe_threshold: float = RISK_PROBE_THRESHOLD,
                  gate: float = GATE_ACCURACY) -> dict:
    """对违规风险评分器做标注回放：P(违规) ≥ probe_threshold 判为违规。"""
    items = []
    for case in cases:
        item = {"name": case.name or case.prompt[:20],
                "expected": bool(case.expected), "predicted": None,
                "score": None, "correct": False, "error": None}
        try:
            decision = client.score_risk(case.prompt)
            item["score"] = decision.score
            item["predicted"] = decision.score >= probe_threshold
            item["correct"] = item["predicted"] == bool(case.expected)
        except Exception as exc:
            item["error"] = f"{type(exc).__name__}: {exc}"
        items.append(item)
    return _summarize(items, gate)
