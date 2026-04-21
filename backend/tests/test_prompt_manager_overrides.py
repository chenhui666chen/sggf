import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from app.services.prompts.manager import PromptManager


def test_prompt_manager_persists_overrides(tmp_path):
    base_path = tmp_path / "agents.json"
    overrides_path = tmp_path / "agents.overrides.json"

    base_payload = {
        "version": "test",
        "agents": {
            "creative_director": {
                "name": "创意总监",
                "system_prompt": "默认系统提示词",
            }
        },
        "user_prompts": {
            "quality_reviewer_assessment": {
                "description": "质量评审",
                "template": "默认用户提示词",
            }
        },
        "agent_user_prompt_map": {
            "quality_reviewer": ["quality_reviewer_assessment"],
        },
    }
    base_path.write_text(
        json.dumps(base_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    manager = PromptManager(str(base_path), overrides_path=str(overrides_path))
    assert manager.load()

    assert manager.update_agent_prompt("creative_director", "自定义系统提示词")
    assert manager.update_user_prompt("quality_reviewer_assessment", "自定义用户提示词")

    reloaded = PromptManager(str(base_path), overrides_path=str(overrides_path))
    assert reloaded.load()
    assert reloaded.get_agent_prompt("creative_director") == "自定义系统提示词"
    assert reloaded.get_user_prompt("quality_reviewer_assessment") == "自定义用户提示词"
    assert reloaded.get_agent_prompt("creative_director", force_default=True) == "默认系统提示词"
    assert reloaded.get_user_prompt("quality_reviewer_assessment", force_default=True) == "默认用户提示词"


def test_prompt_manager_reset_removes_overrides(tmp_path):
    base_path = tmp_path / "agents.json"
    overrides_path = tmp_path / "agents.overrides.json"

    base_payload = {
        "version": "test",
        "agents": {
            "world_architect": {
                "name": "世界观架构师",
                "system_prompt": "默认世界观提示词",
            }
        },
        "user_prompts": {
            "event_validator_validate": {
                "description": "事件验证",
                "template": "默认事件验证模板",
            }
        },
        "agent_user_prompt_map": {},
    }
    base_path.write_text(
        json.dumps(base_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    manager = PromptManager(str(base_path), overrides_path=str(overrides_path))
    assert manager.load()
    assert manager.update_agent_prompt("world_architect", "覆盖后的世界观提示词")
    assert manager.update_user_prompt("event_validator_validate", "覆盖后的事件验证模板")

    assert manager.reset_agent_prompt("world_architect")
    assert manager.reset_user_prompt("event_validator_validate")
    assert manager.get_agent_prompt("world_architect") == "默认世界观提示词"
    assert manager.get_user_prompt("event_validator_validate") == "默认事件验证模板"

    if overrides_path.exists():
        overrides_payload = json.loads(overrides_path.read_text(encoding="utf-8"))
        assert not overrides_payload.get("agents")
        assert not overrides_payload.get("user_prompts")
