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

from app.services.agents.agents import CharacterDesignerAgent
from app.services.prompts.stages.world_building import CharacterDesignPrompts


def test_character_prompt_uses_standard_card_schema_without_legacy_group_sections() -> None:
    prompt = CharacterDesignPrompts.get_character_prompt(
        requirement="主角要偏智斗流",
        genre_extra_fields="",
    )

    assert "### 【姓名】：" in prompt
    assert "【故事立场】" in prompt
    assert "【角色定位】" in prompt
    assert "【关键关系】" in prompt
    assert "【主线绑定】" in prompt
    assert "【能力与限制】" in prompt
    assert "【故事立场】只能从以下值中选择：主角方 / 反派方 / 中立方 / 亦正亦邪" in prompt
    assert "【角色定位】要写成" in prompt
    assert "单一定位" in prompt
    assert "【关键关系】必须按“角色名：关系性质/当前张力”的方式书写" in prompt
    assert "主角、主要反派、核心盟友" in prompt
    assert "只输出连续的人物卡正文" in prompt
    assert "禁止输出“核心主角 / 核心盟友 / 核心反派 / 人物关系网 / 动态演变 / mermaid 图 / 关系总表”等旧式策划结构" in prompt
    assert "## 一、核心主角" not in prompt
    assert "## 二、核心盟友" not in prompt
    assert "## 三、核心对手/复杂关系者" not in prompt
    assert "## 四、人物关系网络与动态演变" not in prompt


def test_character_designer_agent_system_prompt_emphasizes_parseable_cards() -> None:
    prompt = CharacterDesignerAgent().get_system_prompt()

    assert "标准人物卡" in prompt
    assert "### 【姓名】：" in prompt
    assert "不要输出“核心主角/核心盟友/核心反派/人物关系网/mermaid/总结”" in prompt
    assert "【故事立场】只能从“主角方 / 反派方 / 中立方 / 亦正亦邪”四选一" in prompt
    assert "【关键关系】必须写成“角色名：关系性质/当前张力”" in prompt
