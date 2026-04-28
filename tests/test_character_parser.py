from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parent.parent
for path in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from backend.app.services.agents.outline_expander import OutlineExpander
from backend.app.services.character_parser import (
    CharacterTextParser,
    has_parseable_character_cards,
    parse_and_sync_relationships,
)


def test_character_text_parser_supports_formal_story_expansion_labels() -> None:
    text = """
### 【姓名】：顾晚
【年龄/性别】：23岁/女
【故事立场】：主角方
【所属势力】：青石司
【重要性】：重要角色
【角色定位】：情报盟友
【外貌特征】：清瘦冷白，眼神凌厉。
【性格特点】：克制谨慎，但关键时刻极有决断。
【背景故事】：出身寒门，长期潜伏于青石城情报网。
【世界观/价值观立场】：相信秩序，但不盲从权力。
【核心动机】：查清旧案真相并保护线人。
【能力与限制】：能力：情报搜集、伪装潜行。
限制：过度独自承担风险。
【主线绑定】：剧情职责：帮助主角切入旧案核心。
关联线索：旧案、城防司、失踪线人。
【成长方向】：从独行者转向建立信任。
【关键关系】：与林舟互为盟友。
""".strip()

    parsed = CharacterTextParser().parse_all_characters(text)

    assert len(parsed) == 1
    character = parsed[0]
    assert character.name == "顾晚"
    assert character.role == "主角方"
    assert character.role_position == "情报盟友"
    assert character.importance_level == "重要角色"
    assert character.personality == "克制谨慎，但关键时刻极有决断。"
    assert character.background == "出身寒门，长期潜伏于青石城情报网。"
    assert character.worldview == "相信秩序，但不盲从权力。"
    assert character.abilities == "情报搜集、伪装潜行。"
    assert character.limitation == "过度独自承担风险。"
    assert character.mainline_role == "帮助主角切入旧案核心。"
    assert character.growth_direction == "从独行者转向建立信任。"
    assert character.relationships == "与林舟互为盟友。"
    assert character.mainline_clues == "旧案、城防司、失踪线人。"


def test_outline_expander_character_cards_use_parser_compatible_labels() -> None:
    text, names = OutlineExpander._story_render_character_cards(
        [
            {
                "name": "顾晚",
                "age_gender": "23岁/女",
                "story_stance": "主角方",
                "affiliation": "青石司",
                "importance": "重要角色",
                "role_position": "情报盟友",
                "appearance_anchor": "清瘦冷白，眼神凌厉。",
                "personality_anchor": "性格：克制谨慎，但关键时刻极有决断。\n价值倾向：相信秩序，但不盲从权力。",
                "background_status": "出身寒门，长期潜伏于青石城情报网。",
                "motivation": "查清旧案真相并保护线人。",
                "ability_outline": "情报搜集、伪装潜行。",
                "limitation": "过度独自承担风险。",
                "mainline_role": "帮助主角切入旧案核心。",
                "growth_direction": "从独行者转向建立信任。",
                "key_relationships": "与林舟互为盟友。",
                "mainline_clues": "旧案、城防司、失踪线人。",
            }
        ]
    )

    assert names == ["顾晚"]
    assert "【角色定位】" in text
    assert "【外貌锚点】" in text
    assert "【性格锚点】" in text
    assert "【背景/当前处境】" in text
    assert "【能力与限制】" in text
    assert "【主线绑定】" in text
    assert "【成长方向】" in text
    assert "【角色重要性】" not in text
    assert "【角色类型】" not in text
    assert "【背景经历】" not in text
    assert "【价值立场】" not in text
    assert "【重要性】" not in text

    parsed = CharacterTextParser().parse_all_characters(text)

    assert len(parsed) == 1
    character = parsed[0]
    assert character.name == "顾晚"
    assert character.importance_level == "次要角色"
    assert character.background == "出身寒门，长期潜伏于青石城情报网。"
    assert character.worldview == "相信秩序，但不盲从权力。"
    assert character.abilities == "情报搜集、伪装潜行。"
    assert character.mainline_role == "帮助主角切入旧案核心。"
    assert character.growth_direction == "从独行者转向建立信任。"


def test_character_text_parser_supports_loose_story_expansion_card_format() -> None:
    text = """
### 顾晚
- 角色定位：情报盟友
- 性格特点：克制谨慎，但关键时刻极有决断。
- 背景故事：出身寒门，长期潜伏于青石城情报网。
- 核心动机：查清旧案真相并保护线人。

姓名：沈砚
故事立场：对手阵营
角色定位：审讯官
背景故事：奉命调查旧案，怀疑主角另有所图。
关键关系：与顾晚互相试探。

## 关系补丁
- 顾晚 ↔ 沈砚：互相试探（因旧案结下警惕）
""".strip()

    parsed = CharacterTextParser().parse_all_characters(text)

    assert [character.name for character in parsed] == ["顾晚", "沈砚"]
    assert parsed[0].role == "主角方"
    assert parsed[0].role_position == "情报盟友"
    assert parsed[0].background == "出身寒门，长期潜伏于青石城情报网。"
    assert parsed[0].motivation == "查清旧案真相并保护线人。"
    assert parsed[1].role == "反派方"
    assert parsed[1].role_position == "审讯官"
    assert parsed[1].background == "奉命调查旧案，怀疑主角另有所图。"
    assert parsed[1].relationships == "与顾晚互相试探。"


def test_has_parseable_character_cards_accepts_loose_card_blocks() -> None:
    loose_cards = """
### 顾晚
角色定位：情报盟友
背景故事：长期潜伏于青石城情报网。
""".strip()

    relation_patch_only = """
## 关系补丁
- 顾晚 ↔ 林舟：盟友（共同调查旧案）
""".strip()

    assert has_parseable_character_cards(loose_cards) is True
    assert has_parseable_character_cards(relation_patch_only) is False


def test_parse_and_sync_relationships_supports_story_expansion_relation_lines() -> None:
    class _FakeQuery:
        def __init__(self, items: list[SimpleNamespace]) -> None:
            self._items = items

        def filter(self, *args: object, **kwargs: object) -> "_FakeQuery":
            return self

        def all(self) -> list[SimpleNamespace]:
            return list(self._items)

    class _FakeDBSession:
        def __init__(self, items: list[SimpleNamespace]) -> None:
            self._items = items
            self.committed = False

        def query(self, model: object) -> _FakeQuery:
            return _FakeQuery(self._items)

        def commit(self) -> None:
            self.committed = True

    characters = [
        SimpleNamespace(id=1, name="林舟", relations=None),
        SimpleNamespace(id=2, name="顾晚", relations=None),
    ]
    fake_db = _FakeDBSession(characters)

    result = parse_and_sync_relationships(
        project_id=1,
        relationships_text="- 林舟 ↔ 顾晚：盟友（共同调查旧案）",
        db_session=fake_db,
    )

    assert result == {
        "parsed": 1,
        "saved": 1,
        "characters_updated": 1,
    }
    assert fake_db.committed is True

    relations_payload = json.loads(characters[0].relations)
    assert len(relations_payload["items"]) == 1
    assert relations_payload["items"][0]["target"] == "顾晚"
    assert relations_payload["items"][0]["type"] == "盟友"
