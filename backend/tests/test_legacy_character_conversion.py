import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DEBUG", "false")

from app.services.character_parser import (
    CharacterTextParser,
    convert_legacy_grouped_characters_to_cards,
    has_parseable_character_cards,
)


def test_convert_legacy_grouped_characters_to_cards_supports_grouped_essay_format() -> None:
    legacy_text = """# 《代劫》主要人物设定

一、主角：苏妄
身份：无魂无魄之体的代劫人。
核心能力体系
- 虚相心域：主动进入他人心魔幻境。
内在矛盾与成长弧光
- 初始状态：把自己当作工具。

二、关键配角
1. 红绡
身份：红尘殿真传弟子，兼渡厄墟高级情报官。
与苏妄关系：固定情报源与委托介绍人。
能力特色：修炼《七情典》，擅长情报布局。

2. 渡厄真人
身份：渡厄墟创始人，前任代劫人。
与苏妄关系：如师如父。

三、主要反派/对立力量
1. 洛天衡
身份：太虚剑宗执法长老。
理念：坚信天道法则绝对正确。
与苏妄冲突：视苏妄为系统漏洞。
"""

    converted = convert_legacy_grouped_characters_to_cards(legacy_text)

    assert converted
    assert has_parseable_character_cards(converted) is True
    assert "### 【姓名】：" in converted
    assert "【故事立场】：" in converted
    assert "【角色定位】：" in converted

    parsed = CharacterTextParser().parse_all_characters(converted)
    assert len(parsed) == 4


def test_convert_legacy_grouped_characters_to_cards_returns_empty_for_non_character_text() -> None:
    converted = convert_legacy_grouped_characters_to_cards("这是一段普通说明文字，没有人物分组结构。")

    assert converted == ""
