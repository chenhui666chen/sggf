"""修订新增事实溯源守卫测试。

背景：线上项目实测发现，迭代修订为应付【必改】会凭空写出前文不存在的事实
（例如"三天前她把剪报塞进我口袋"、"他留了封求援信"），复评只看"必改项是否有对应文字"
便判为已执行，导致硬伤随章节数累积。本守卫要求复评对修订新增的关键事实做溯源比对，
查无出处即判 HIGH 失败码 NEW_FACT_UNSOURCED 并阻断达标。
"""

from app.api.v1.workflow.routes_chapter import (
    _iteration_review_has_unresolved_required_items,
)
from app.services.prompts.narrative_quality import (
    FAILURE_CODE_OUTPUT_SPEC,
    NOVEL_FAILURE_CODES,
    build_repair_hints,
    extract_failure_codes,
    review_has_unsourced_new_fact,
)
from app.services.prompts.workflow_runtime import (
    build_iteration_loop_review_user_prompt,
    get_iteration_revision_system_prompt,
)


def _review_with(*, severity: str) -> str:
    return (
        "综合评分：8.6/10分\n\n"
        "## 评审要求执行核验表\n"
        "| 要求ID/来源 | 状态（已执行/部分执行/未执行） | 修改后证据 | 未完成原因 |\n"
        "|---|---|---|---|\n"
        "| R0-MUST-1 | 已执行 | 补写了苏砚的说明 |\n\n"
        "## 失败码清单\n"
        f"NEW_FACT_UNSOURCED|{severity}|苏砚三天前把剪报塞进主角口袋（前文与规划均无此事）\n\n"
        "结论：通过"
    )


def test_failure_code_is_registered_for_local_repair():
    entry = NOVEL_FAILURE_CODES["NEW_FACT_UNSOURCED"]

    assert entry["name"] == "无出处新事实"
    # 编造事实靠删改单点即可修复，路由为局部修订；阻断力来自严重度而非 class
    assert entry["class"] == "light"


def test_failure_code_output_spec_lists_every_registered_code():
    """枚举清单必须由失败码目录派生，避免两处不同步导致模型不输出新码。"""
    for code in NOVEL_FAILURE_CODES:
        assert code in FAILURE_CODE_OUTPUT_SPEC


def test_extract_failure_codes_parses_unsourced_fact_line():
    codes = extract_failure_codes(_review_with(severity="HIGH"))

    matched = [c for c in codes if c["code"] == "NEW_FACT_UNSOURCED"]
    assert len(matched) == 1
    assert matched[0]["severity"] == "HIGH"
    assert "塞进主角口袋" in matched[0]["evidence"]


def test_only_high_severity_counts_as_unsourced_fact():
    assert review_has_unsourced_new_fact(_review_with(severity="HIGH")) is True
    assert review_has_unsourced_new_fact(_review_with(severity="MED")) is False
    assert review_has_unsourced_new_fact("综合评分：9.0/10分\n失败码清单：\n无") is False


def test_unsourced_high_code_blocks_iteration_acceptance():
    """核验表全部已执行、结论写"通过"，仍不得绕过无出处新事实。"""
    assert _iteration_review_has_unresolved_required_items(_review_with(severity="HIGH")) is True
    assert _iteration_review_has_unresolved_required_items(_review_with(severity="MED")) is False


def test_repair_hint_is_available_for_unsourced_fact():
    hints = build_repair_hints(
        [{"code": "NEW_FACT_UNSOURCED", "name": NOVEL_FAILURE_CODES["NEW_FACT_UNSOURCED"]["name"]}]
    )

    assert "NEW_FACT_UNSOURCED" in hints
    assert "出处" in hints


def test_review_prompt_requires_diffing_against_previous_version():
    prompt = build_iteration_loop_review_user_prompt(
        chapter_number=3,
        chapter_content="修订后正文：苏砚三天前把剪报塞进了我口袋。",
        review_text="R0-MUST-1：补齐苏砚的动机",
        previous_content="修订前正文：苏砚当场出示了一张旧剪报。",
    )

    assert "【修订前正文】" in prompt
    assert "修订前正文：苏砚当场出示了一张旧剪报。" in prompt
    assert "NEW_FACT_UNSOURCED" in prompt
    assert "无出处" in prompt


def test_review_prompt_omits_previous_version_block_when_absent():
    prompt = build_iteration_loop_review_user_prompt(
        chapter_number=3,
        chapter_content="正文",
        review_text="R0-MUST-1：补齐苏砚的动机",
    )

    assert "【修订前正文】" not in prompt


def test_revision_prompt_forbids_inventing_facts_to_satisfy_review():
    system_prompt = get_iteration_revision_system_prompt()

    assert "不得新增前文与规划之外的事实" in system_prompt
    assert "改按现有可溯源素材重写" in system_prompt
