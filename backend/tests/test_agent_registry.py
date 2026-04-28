import asyncio
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

from app.services.agent_coordinator import AgentCoordinator, AgentStatus, AgentType, StageType
from app.services.agent_registry import (
    get_agent_definition,
    get_main_workflow_agent_definitions,
    get_stage_agent_payloads,
    iter_agent_definitions,
)
from app.services.prompts.manager import prompt_manager


def test_main_workflow_agent_registry_matches_agent_type_order() -> None:
    registry_ids = [definition.id for definition in get_main_workflow_agent_definitions()]
    enum_ids = [agent_type.value for agent_type in AgentType]

    assert registry_ids == enum_ids


def test_stage_agent_payloads_are_shared_status_source() -> None:
    assert get_stage_agent_payloads("structure", include_stage=True) == [
        {"id": "plot_architect", "name": "情节架构师", "stage": "structure"},
        {"id": "event_validator", "name": "事件验证官", "stage": "structure"},
    ]
    assert get_stage_agent_payloads("iteration", include_stage=True) == [
        {"id": "iteration_coordinator", "name": "迭代协调官", "stage": "iteration"},
        {"id": "content_reviser", "name": "内容修订师", "stage": "iteration"},
        {"id": "final_reviewer", "name": "最终审核官", "stage": "iteration"},
    ]


def test_auxiliary_agents_are_registered_without_status_participation() -> None:
    outline_parser = get_agent_definition("outline_plan_parser")
    logic_checker = get_agent_definition("chapter_logic_checker")

    assert outline_parser is not None
    assert outline_parser.default_enabled is False
    assert outline_parser.is_status_agent is False
    assert logic_checker is not None
    assert logic_checker.default_enabled is False
    assert logic_checker.is_status_agent is False


def test_agent_coordinator_templates_are_built_from_registry() -> None:
    coordinator = AgentCoordinator()
    coordinator._coordinator_initialized = True

    asyncio.run(coordinator.initialize_agents())

    agents = coordinator.get_agents()
    assert list(agents) == [definition.id for definition in get_main_workflow_agent_definitions()]
    assert agents["creative_director"]["stage"] == StageType.CONCEPT
    assert agents["creative_director"]["status"] == AgentStatus.IDLE
    assert agents["iteration_coordinator"]["role"] == "分析反馈制定改进计划"
    assert agents["iteration_coordinator"]["is_prompt_editable"] is True


def test_prompt_registry_contains_registered_agent_prompts() -> None:
    missing = [
        definition.id
        for definition in iter_agent_definitions()
        if definition.is_prompt_editable
        and not prompt_manager.get_agent_prompt(definition.id, force_default=True)
    ]

    assert missing == []
