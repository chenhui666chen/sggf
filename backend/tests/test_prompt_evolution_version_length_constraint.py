"""版本提示词内置篇幅约束测试：所有用于改写的提示词自身必须携带反删减约束。

背景缺陷：篇幅约束此前只确定性追加在 A/B 变体上；初始提示词仅禁止
"删除关键情节"而无整体篇幅要求，常规进化轮产出的改进提示词更是完全
未经约束强制，导致版本提示词自身可能指导改写模型大幅删减内容。

覆盖要求：
1. SAFE_INITIAL_PROMPT 内置篇幅对齐条款；
2. optimize_prompt 产出的改进提示词确定性携带【篇幅对齐硬性约束】（幂等，
   即使元优化器 LLM 输出未包含该约束）。
"""
from unittest.mock import AsyncMock

import pytest

from app.services.prompt_evolution import meta_optimizer
from app.services.prompt_evolution.meta_optimizer import MetaOptimizer
from app.services.prompt_evolution.models import PromptVersion


def test_initial_prompt_embeds_length_alignment_rule():
    """初始提示词必须内置篇幅对齐要求，不依赖后续追加。"""
    prompt = MetaOptimizer().get_initial_prompt("玄幻")

    assert "篇幅" in prompt
    assert "不得删句" in prompt or "不得删除句子" in prompt or "删句" in prompt
    # 篇幅条款应位于内容保真区（第一优先级），而非仅优化方向
    assert "篇幅" in prompt.split("# 优化方向")[0]


def _mock_compliant_response(improved_prompt: str) -> str:
    return f"""
===EFFECTIVE_STRATEGIES===
无
===EFFECTIVE_STRATEGIES_END===
===INEFFECTIVE_STRATEGIES===
无
===INEFFECTIVE_STRATEGIES_END===
===FORBIDDEN_PATTERNS===
无
===FORBIDDEN_PATTERNS_END===
===ANALYSIS===
这是一段足够长的合规分析内容。
===ANALYSIS_END===
===IMPROVED_PROMPT===
{improved_prompt}
===IMPROVED_PROMPT_END===
"""


@pytest.mark.asyncio
async def test_improved_prompt_carries_length_constraint_even_if_llm_omits_it():
    """常规进化轮产出的改进提示词必须确定性携带篇幅约束。"""
    optimizer = MetaOptimizer()
    optimizer.llm_client = AsyncMock()
    optimizer.llm_client.chat = AsyncMock(return_value=_mock_compliant_response(
        "保持事实不变，减少模板化连接词，按语义自然调整句长。"
    ))

    improved, _ = await optimizer.optimize_prompt(
        PromptVersion(prompt_text="原有安全提示词", evaluation_results=[]), 30, []
    )

    assert meta_optimizer.VARIANT_LENGTH_MARKER in improved
    assert "不得删句" in improved


@pytest.mark.asyncio
async def test_improved_prompt_does_not_duplicate_constraints():
    """当前版本已含约束时，改进提示词不得重复追加。"""
    base_with_constraints = (
        "保持事实不变，减少模板化连接词。"
        + meta_optimizer.VARIANT_FIDELITY_CONSTRAINT
        + meta_optimizer.VARIANT_LENGTH_CONSTRAINT
    )
    optimizer = MetaOptimizer()
    optimizer.llm_client = AsyncMock()
    optimizer.llm_client.chat = AsyncMock(return_value=_mock_compliant_response(
        base_with_constraints + " 另外按语义调整句长。"
    ))

    improved, _ = await optimizer.optimize_prompt(
        PromptVersion(prompt_text="原有安全提示词", evaluation_results=[]), 30, []
    )

    assert improved.count(meta_optimizer.VARIANT_LENGTH_MARKER) == 1
    assert improved.count(meta_optimizer.VARIANT_FIDELITY_MARKER) == 1
