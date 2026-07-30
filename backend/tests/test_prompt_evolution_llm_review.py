import json
from unittest.mock import AsyncMock

import pytest

from app.services.prompt_evolution.semantic_judge import SemanticJudge


@pytest.mark.asyncio
async def test_semantic_judge_parses_review_and_applies_hard_gate():
    client = AsyncMock()
    client.chat = AsyncMock(return_value=json.dumps({
        "semantic_fidelity": {"score": 76, "reason": "否定关系发生变化", "issues": ["原文未答应，改写后变成答应"]},
        "fact_consistency": {"score": 92, "reason": "其他事实一致", "issues": []},
        "information_completeness": {"score": 88, "reason": "信息基本完整", "issues": []},
        "readability": {"score": 91, "reason": "表达流畅", "issues": []},
        "writing_naturalness": {"score": 86, "reason": "语言自然", "issues": []},
        "genre_consistency": {"score": 90, "reason": "题材一致", "issues": []},
        "over_rewrite_risk": "low",
        "confidence": 0.93
    }, ensure_ascii=False))

    review = await SemanticJudge(client).evaluate("他没有答应。", "他答应了。", "都市")

    assert review["available"] is True
    assert review["hard_fail"] is True
    assert "语义保真度低于80" in review["hard_fail_reasons"]
    assert review["semantic_fidelity"]["score"] == 76


@pytest.mark.asyncio
async def test_semantic_judge_does_not_invent_scores_for_invalid_json():
    client = AsyncMock()
    client.chat = AsyncMock(return_value="不是JSON")

    review = await SemanticJudge(client).evaluate("原文", "改写", "通用")

    assert review == {
        "available": False,
        "hard_fail": False,
        "hard_fail_reasons": [],
        "error": "评审模型返回格式无效",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("risk", "confidence", "expected_risk", "expected_confidence"),
    [
        ("低风险", 92, "low", 0.92),
        ("中等", "85%", "medium", 0.85),
        ("HIGH RISK", "0.73", "high", 0.73),
    ],
)
async def test_semantic_judge_normalizes_common_risk_and_confidence_formats(
    risk, confidence, expected_risk, expected_confidence
):
    client = AsyncMock()
    dimension = {"score": 95, "reason": "通过", "issues": []}
    client.chat = AsyncMock(return_value=json.dumps({
        "semantic_fidelity": dimension,
        "fact_consistency": dimension,
        "information_completeness": dimension,
        "readability": dimension,
        "writing_naturalness": dimension,
        "genre_consistency": dimension,
        "over_rewrite_risk": risk,
        "confidence": confidence,
    }, ensure_ascii=False))

    review = await SemanticJudge(client).evaluate("原文", "改写", "通用")

    assert review["available"] is True
    assert review["over_rewrite_risk"] == expected_risk
    assert review["confidence"] == expected_confidence


@pytest.mark.asyncio
async def test_semantic_judge_accepts_structured_over_rewrite_risk():
    client = AsyncMock()
    dimension = {"score": 95, "reason": "通过", "issues": []}
    client.chat = AsyncMock(return_value=json.dumps({
        "semantic_fidelity": dimension,
        "fact_consistency": dimension,
        "information_completeness": dimension,
        "readability": dimension,
        "writing_naturalness": dimension,
        "genre_consistency": dimension,
        "over_rewrite_risk": {
            "level": "high",
            "reason": "改变叙事视角并舍弃原始人物和设定",
        },
        "confidence": 0.96,
    }, ensure_ascii=False))

    review = await SemanticJudge(client).evaluate("原文", "改写", "玄幻")

    assert review["available"] is True
    assert review["over_rewrite_risk"] == "high"
    assert review["over_rewrite_reason"] == "改变叙事视角并舍弃原始人物和设定"
    assert review["hard_fail"] is True
    assert "过度改写风险高" in review["hard_fail_reasons"]


@pytest.mark.asyncio
async def test_semantic_judge_accepts_risk_level_in_score_field():
    client = AsyncMock()
    dimension = {"score": 95, "reason": "通过", "issues": []}
    client.chat = AsyncMock(return_value=json.dumps({
        "semantic_fidelity": dimension,
        "fact_consistency": dimension,
        "information_completeness": dimension,
        "readability": dimension,
        "writing_naturalness": dimension,
        "genre_consistency": dimension,
        "over_rewrite_risk": {
            "score": "medium",
            "reason": "增加较多细节但故事主线未变",
            "issues": [],
        },
        "confidence": 0.9,
    }, ensure_ascii=False))

    review = await SemanticJudge(client).evaluate("原文", "改写", "通用")

    assert review["available"] is True
    assert review["over_rewrite_risk"] == "medium"
    assert review["over_rewrite_reason"] == "增加较多细节但故事主线未变"
    assert review["hard_fail"] is False
