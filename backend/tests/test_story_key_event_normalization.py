from app.services.story_expansion_coord_pkg import normalize_outline_text
from app.services.story_text_utils import split_story_event_items


def test_split_story_event_items_supports_dense_dash_separated_text() -> None:
    value = (
        "苏璃以自由灵盟技术人员身份接近城寨卫队技术官获取二寨主近期活动情报"
        "——四天前秘密出城与斗篷人接头"
        "——发现其自身因果线被巧妙动过"
    )

    assert split_story_event_items(value) == [
        "苏璃以自由灵盟技术人员身份接近城寨卫队技术官获取二寨主近期活动情报",
        "四天前秘密出城与斗篷人接头",
        "发现其自身因果线被巧妙动过",
    ]


def test_normalize_outline_text_promotes_key_events_into_canonical_field_order() -> None:
    outline = """
第44章：城寨暗流
- 场景目标：渗透城寨内部势力分析二寨主与神秘人真实意图
- 冲突设计：二寨主对信物碎片觊觎与铁棘残余支持者防守 vs 利用噬因能力暗中调查二寨主一方因果异常
- 涉及人物：顾长庚、苏璃、红蔓
- 人物推进：对因果线分析能力愈精进，从只能感知到可判别篡改痕迹
- 情节作用：揭开城寨内斗深层逻辑
- 结尾钩子：苏璃判断神秘人正在为某种准备了数百年的大规模行动制造安全区
关键事件：
苏璃以自由灵盟技术人员身份接近城寨卫队技术官获取二寨主近期活动情报——四天前秘密出城与斗篷人接头——发现其自身因果线被巧妙动过
- 伏笔事项：屏蔽装置的异常篡改手段为后续识别神秘人技术体系提供线索
"""

    normalized = normalize_outline_text(outline)

    assert "- 关键事件：" in normalized
    assert (
        "苏璃以自由灵盟技术人员身份接近城寨卫队技术官获取二寨主近期活动情报；"
        "四天前秘密出城与斗篷人接头；"
        "发现其自身因果线被巧妙动过"
    ) in normalized
    assert normalized.index("- 冲突设计") < normalized.index("- 关键事件")
    assert normalized.index("- 关键事件") < normalized.index("- 涉及人物")
