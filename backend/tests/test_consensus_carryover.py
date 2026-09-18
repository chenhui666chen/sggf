"""多模型评审《一致意见》到修订执行的贯通测试。

背景：线上项目实测发现，交叉印证的《一致意见》里点名的"巡捕房信息倾销"没有被主审
写进《最终修改建议》的【必改】条目，而修订师只按带标签的条目执行，问题整章未处理。
一致意见是多个模型共同指出的高可信问题，不得在汇总与执行两处环节被静默丢弃。
"""

from app.services.agents.multi_model_review_service import MultiModelReviewService
from app.services.prompts.workflow_runtime import (
    build_iteration_loop_review_user_prompt,
    build_iteration_revision_user_prompt,
    get_iteration_revision_system_prompt,
)


def test_summarize_instruction_forbids_dropping_consensus_issues():
    instruction = MultiModelReviewService._build_summarize_instruction()

    assert "一致意见" in instruction
    assert "不得静默丢弃" in instruction
    # 问题类一致意见必须落到最终修改建议并给出优先级
    assert "最终修改建议" in instruction


def test_revision_user_prompt_requires_consensus_execution():
    prompt = build_iteration_revision_user_prompt(
        chapter_number=3,
        chapter_content="正文",
        review_text="### 一致意见（交叉印证，高可信）\n- 巡捕房搜掠段信息倾倒\n\n### 最终修改建议\n1. 【建议】措辞重复",
    )

    assert "巡捕房搜掠段信息倾倒" in prompt


def test_revision_system_prompt_treats_consensus_as_must_fix():
    system_prompt = get_iteration_revision_system_prompt()

    assert "《一致意见》" in system_prompt
    assert "与【必改】同等执行" in system_prompt


def test_loop_review_prompt_verifies_consensus_items_too():
    prompt = build_iteration_loop_review_user_prompt(
        chapter_number=3,
        chapter_content="修订后正文",
        review_text="### 一致意见\n- 巡捕房搜掠段信息倾倒",
    )

    assert "一致意见" in prompt
