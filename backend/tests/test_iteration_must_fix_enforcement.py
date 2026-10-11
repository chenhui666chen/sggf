import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.v1.workflow.helpers import _build_iteration_revision_prompt
from app.api.v1.workflow.routes_chapter import _iteration_review_has_unresolved_required_items
from app.services.prompts.workflow_runtime import get_iteration_revision_system_prompt


def test_revision_prompt_prioritizes_must_fix_cuts_over_length_floor():
    user_prompt = _build_iteration_revision_prompt(
        chapter_number=5,
        chapter_content="孙妈催租正文",
        review_text="1. 【必改】删除或大幅压缩孙妈催租的前40%篇幅",
        iteration_plan="## 本轮必做项\n1. 压缩催租，提前让阿九入场",
    )
    system_prompt = get_iteration_revision_system_prompt()
    combined = user_prompt + "\n" + system_prompt
    assert "【必改】" in combined
    assert "删减优先" in combined or "压缩优先" in combined
    assert "不得为了保篇幅而保留已被判定为注水的桥段" in combined
    assert "完整保留原有情节发展，篇幅不应少于原稿字数的90%" not in system_prompt


def test_unresolved_required_items_detects_table_must_unexecuted():
    review = """综合评分：7/10分

## 评审要求执行核验表
| 要求ID/来源 | 状态（已执行/部分执行/未执行） | 修改后证据 | 未完成原因 |
|---|---|---|---|
| R0-MUST-1 | 未执行 | 无 | 仍保留催租闹剧 |
"""
    assert _iteration_review_has_unresolved_required_items(review) is True


def test_unresolved_required_items_detects_remaining_must_fix_without_table():
    review = """综合评分：6/10分

## 剩余关键问题
1. 【必改】删除或大幅压缩孙妈催租的前40%篇幅，将阿九入场的时机提前
2. 情报重复仍在

结论：继续修改
"""
    assert _iteration_review_has_unresolved_required_items(review) is True


def test_unresolved_required_items_false_when_must_executed():
    review = """综合评分：9/10分

## 评审要求执行核验表
| 要求ID/来源 | 状态 | 修改后证据 | 未完成原因 |
| R0-MUST-1 | 已执行 | 催租压缩到一段 | 无 |

## 剩余关键问题
1. 可再增强结尾钩子

结论：通过
"""
    assert _iteration_review_has_unresolved_required_items(review) is False
