import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from app.api.v1.workflow.story_helpers import _prioritize_recent_avoidance_groups


def test_prioritize_recent_avoidance_groups_keeps_highest_risk_groups():
    groups = {
        "高频开局身份": ["宗门杂役", "废灵根"],
        "高频金手指": ["逆修系统"],
        "已用世界名": ["玄穹界"],
        "高频终局真相": ["飞升骗局"],
        "未知分组": ["某元素"],
    }

    prioritized = _prioritize_recent_avoidance_groups(groups, max_groups=3)

    assert prioritized == [
        ("已用世界名", ["玄穹界"]),
        ("高频终局真相", ["飞升骗局"]),
        ("高频金手指", ["逆修系统"]),
    ]
