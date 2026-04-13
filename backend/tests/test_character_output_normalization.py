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

from app.services.agents.agent_coordinator import CreativeDirectorCoordinator
from app.services.character_parser import CharacterTextParser, has_parseable_character_cards


class DummyCharacterDesigner:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def process(self, prompt, context=None, temperature=None):
        self.calls.append(
            {
                "prompt": prompt,
                "context": context,
                "temperature": temperature,
            }
        )
        if not self.outputs:
            raise AssertionError("No stubbed character output provided")
        return self.outputs.pop(0)


def test_character_output_normalization_rewrites_legacy_grouped_text() -> None:
    legacy_text = """# 《器劫》人物设定

一、主角：苏砚
被废后流落边荒，执着追查器劫真相。

二、关键配角
1. 陆青冥：主角的匠道引路人。

三、核心反派
1. 柳玄音：维护天命秩序的巡天司首座。

四、人物关系网与动态
苏砚与陆青冥是师徒，和柳玄音属于核心对抗。"""

    normalized_cards = """### 【姓名】：苏砚
【年龄/性别】：25岁/男
【故事立场】：主角方
【角色定位】：主角
【所属势力】：待补充
【重要性】：主角

### 【姓名】：陆青冥
【年龄/性别】：待补充
【故事立场】：主角方
【角色定位】：导师
【所属势力】：待补充
【重要性】：重要角色"""

    coordinator = CreativeDirectorCoordinator.__new__(CreativeDirectorCoordinator)
    coordinator.character_designer = DummyCharacterDesigner([normalized_cards])

    result = coordinator._normalize_character_cards_if_needed(
        legacy_text,
        requirement="主打智斗与器道悬疑",
        concept="主角窥探残器未来，逆推器劫真相。",
        world_setting="上界以天命碑维持秩序。",
    )

    assert result == normalized_cards
    assert has_parseable_character_cards(result) is True
    assert len(coordinator.character_designer.calls) == 1
    assert coordinator.character_designer.calls[0]["temperature"] == 0.2
    assert "只做结构化重排" in coordinator.character_designer.calls[0]["prompt"]


def test_character_output_normalization_skips_clean_cards() -> None:
    clean_cards = """### 【姓名】：苏砚
【年龄/性别】：25岁/男
【故事立场】：主角方
【角色定位】：主角
【所属势力】：待补充
【重要性】：主角"""

    coordinator = CreativeDirectorCoordinator.__new__(CreativeDirectorCoordinator)
    coordinator.character_designer = DummyCharacterDesigner([])

    result = coordinator._normalize_character_cards_if_needed(
        clean_cards,
        requirement="主打智斗与器道悬疑",
        concept="主角窥探残器未来，逆推器劫真相。",
        world_setting="上界以天命碑维持秩序。",
    )

    assert result == clean_cards
    assert coordinator.character_designer.calls == []


def test_character_output_normalization_polishes_structured_card_values() -> None:
    parseable_cards = """### 【姓名】：「判官」
【年龄/性别】：非人存在/无
【故事立场】：系统方
【角色定位】：系统/辅助
【所属势力】：澄心局
【关键关系】：林晚；澄心局执棋者

### 【姓名】：苏蔓
【年龄/性别】：28岁/女
【故事立场】：亦正亦邪/转向主角方
【角色定位】：盟友/对照组
【所属势力】：星耀传媒"""

    coordinator = CreativeDirectorCoordinator.__new__(CreativeDirectorCoordinator)
    coordinator.character_designer = DummyCharacterDesigner([])

    result = coordinator._normalize_character_cards_if_needed(
        parseable_cards,
        requirement="主打都市言情与情感博弈",
        concept="女主介入顶流婚约调查，重逢十年前初恋。",
        world_setting="澄心局负责清算错缘。",
    )

    assert "### 【姓名】：判官" in result
    assert "【故事立场】：主角方" in result
    assert "【角色定位】：情报角色" in result
    assert "【故事立场】：亦正亦邪" in result
    assert "【角色定位】：盟友" in result
    assert coordinator.character_designer.calls == []


def test_character_structure_inspection_reports_legacy_reason() -> None:
    legacy_text = """# 《器劫》人物设定

一、主角：苏砚
被废后流落边荒，执着追查器劫真相。
"""

    coordinator = CreativeDirectorCoordinator.__new__(CreativeDirectorCoordinator)
    analysis = coordinator._inspect_character_card_structure(legacy_text)

    assert analysis["parseable"] is False
    assert analysis["contains_legacy_sections"] is True
    assert analysis["needs_normalization"] is True
    assert analysis["reason"] == "no_parseable_cards"


def test_character_structure_inspection_reports_ok_for_parseable_cards() -> None:
    cards = """### 【姓名】：苏砚
【年龄/性别】：25岁/男
【故事立场】：主角方
【角色定位】：主角
【所属势力】：无
【外貌锚点】：黑发清瘦
【性格锚点】：性格：冷静谨慎
价值倾向：重承诺
【背景/当前处境】：正在调查器劫真相。
【核心动机】：活下去并查明真相。
【能力与限制】：能力：器纹推演
限制：灵力枯竭
【关键关系】：陆青冥：导师/信任与试探并存
【主线绑定】：剧情职责：推动器劫调查。
关联线索：残器异动。"""

    coordinator = CreativeDirectorCoordinator.__new__(CreativeDirectorCoordinator)
    analysis = coordinator._inspect_character_card_structure(cards)

    assert analysis["parseable"] is True
    assert analysis["contains_legacy_sections"] is False
    assert analysis["needs_normalization"] is False
    assert analysis["reason"] == "ok"


def test_character_output_normalization_falls_back_to_rule_conversion_when_rewrite_is_still_invalid() -> None:
    legacy_text = """# 《器劫》人物设定

一、主角：苏砚
二、关键配角
1. 陆青冥
四、人物关系网与动态"""

    still_invalid = """# 仍然是旧式人物稿

一、主角：苏砚
二、关键配角
1. 陆青冥"""

    coordinator = CreativeDirectorCoordinator.__new__(CreativeDirectorCoordinator)
    coordinator.character_designer = DummyCharacterDesigner([still_invalid])

    result = coordinator._normalize_character_cards_if_needed(
        legacy_text,
        requirement="主打智斗与器道悬疑",
        concept="主角窥探残器未来，逆推器劫真相。",
        world_setting="上界以天命碑维持秩序。",
    )

    assert result != legacy_text
    assert has_parseable_character_cards(result) is True
    parsed = CharacterTextParser().parse_all_characters(result)
    assert len(parsed) == 2
    assert len(coordinator.character_designer.calls) == 1
    assert "【故事立场】只能从“主角方 / 反派方 / 中立方 / 亦正亦邪”四个值中选择" in coordinator.character_designer.calls[0]["prompt"]
    assert "【关键关系】必须写成“角色名：关系性质/当前张力”的格式" in coordinator.character_designer.calls[0]["prompt"]
