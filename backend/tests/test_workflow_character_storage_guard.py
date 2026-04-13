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

from app.api.v1 import workflow as workflow_module


class DummyRealCoordinator:
    def __init__(self, rewritten_text: str):
        self.rewritten_text = rewritten_text
        self.calls = []

    def _normalize_character_cards_if_needed(self, characters_text: str, **kwargs) -> str:
        self.calls.append(
            {
                "characters_text": characters_text,
                **kwargs,
            }
        )
        return self.rewritten_text


class DummyCoordinator:
    def __init__(self, workflow_state=None, real_coordinator=None):
        self.workflow_state = workflow_state or {}
        self.real_coordinator = real_coordinator

    def get_workflow_state(self, project_id=None):
        return self.workflow_state

    def get_real_coordinator(self, project_id=None):
        return self.real_coordinator


def test_normalize_concept_stage_characters_for_storage_keeps_structured_cards(monkeypatch) -> None:
    clean_cards = """### 【姓名】：苏妄
【年龄/性别】：25岁/男
【故事立场】：主角方
【角色定位】：主角
【所属势力】：待补充
【重要性】：主角"""

    monkeypatch.setattr(
        workflow_module,
        "coordinator",
        DummyCoordinator(workflow_state={"requirement": "主打悬疑修仙"}),
    )

    result = workflow_module._normalize_concept_stage_characters_for_storage(
        1,
        clean_cards,
        concept_text="主角代人承劫，逐渐找回被抹除的身份。",
        world_setting_text="天道会清除异常存在。",
    )

    assert result == clean_cards


def test_normalize_concept_stage_characters_for_storage_rewrites_legacy_text(monkeypatch) -> None:
    legacy_text = """# 《代劫》主要人物设定

一、主角：苏妄
二、关键配角
1. 红绡
三、主要反派/对立力量
1. 洛天衡"""

    normalized_cards = """### 【姓名】：苏妄
【年龄/性别】：25岁/男
【故事立场】：主角方
【角色定位】：主角
【所属势力】：待补充
【重要性】：主角"""

    real_coordinator = DummyRealCoordinator(normalized_cards)
    monkeypatch.setattr(
        workflow_module,
        "coordinator",
        DummyCoordinator(
            workflow_state={"requirement": "主打悬疑修仙"},
            real_coordinator=real_coordinator,
        ),
    )

    result = workflow_module._normalize_concept_stage_characters_for_storage(
        1,
        legacy_text,
        concept_text="主角代人承劫，逐渐找回被抹除的身份。",
        world_setting_text="天道会清除异常存在。",
    )

    assert result == normalized_cards
    assert len(real_coordinator.calls) == 1
    assert real_coordinator.calls[0]["requirement"] == "主打悬疑修仙"


def test_normalize_concept_stage_characters_for_storage_uses_rule_conversion_without_real_coordinator(monkeypatch) -> None:
    legacy_text = """# 《代劫》主要人物设定

一、主角：苏妄
二、关键配角
1. 红绡"""

    monkeypatch.setattr(
        workflow_module,
        "coordinator",
        DummyCoordinator(workflow_state={"requirement": "主打悬疑修仙"}),
    )

    result = workflow_module._normalize_concept_stage_characters_for_storage(
        1,
        legacy_text,
        concept_text="主角代人承劫，逐渐找回被抹除的身份。",
        world_setting_text="天道会清除异常存在。",
    )

    assert result
    assert "### 【姓名】：" in result


def test_build_concept_stage_character_prompts_uses_standard_schema() -> None:
    system_prompt, user_prompt = workflow_module._build_concept_stage_character_prompts(
        project_genre="都市言情",
        requirement="主打破镜重圆与情感博弈",
        concept_text="女主是情感清算师，重逢十年前初恋。",
        world_setting_text="澄心局负责清算错缘，维持情感因果律。",
    )

    assert "标准人物卡" in system_prompt
    assert "【故事立场】只能从以下值中选择：主角方 / 反派方 / 中立方 / 亦正亦邪" in user_prompt
    assert "【关键关系】必须按“角色名：关系性质/当前张力”的方式书写" in user_prompt
    assert "【故事概念】" in user_prompt
    assert "【世界观设定】" in user_prompt
