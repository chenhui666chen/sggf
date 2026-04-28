"""Central registry for novel workflow Agent metadata."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class AgentDefinition:
    """Static metadata shared by workflow status, routing, and prompt tooling."""

    id: str
    name: str
    role: str
    stage: str
    is_runtime_agent: bool = True
    is_status_agent: bool = True
    is_prompt_editable: bool = True
    default_enabled: bool = True
    supported_workflows: Tuple[str, ...] = ("inspiration_ark",)


MAIN_WORKFLOW_AGENT_DEFINITIONS: Tuple[AgentDefinition, ...] = (
    AgentDefinition(
        id="creative_director",
        name="创意总监",
        role="协调整个创作流程",
        stage="concept",
    ),
    AgentDefinition(
        id="world_architect",
        name="世界观架构师",
        role="设计故事世界观",
        stage="concept",
    ),
    AgentDefinition(
        id="character_designer",
        name="人物设计师",
        role="设计故事人物",
        stage="concept",
    ),
    AgentDefinition(
        id="plot_architect",
        name="情节架构师",
        role="设计故事情节",
        stage="structure",
    ),
    AgentDefinition(
        id="event_validator",
        name="事件验证官",
        role="验证事件序列质量",
        stage="structure",
    ),
    AgentDefinition(
        id="content_creator",
        name="内容创作师",
        role="创作章节内容",
        stage="content",
    ),
    AgentDefinition(
        id="style_optimizer",
        name="文风优化师",
        role="优化文风和语言",
        stage="content",
    ),
    AgentDefinition(
        id="quality_reviewer",
        name="质量评审官",
        role="评审内容质量",
        stage="review",
    ),
    AgentDefinition(
        id="iteration_coordinator",
        name="迭代协调官",
        role="分析反馈制定改进计划",
        stage="iteration",
    ),
    AgentDefinition(
        id="content_reviser",
        name="内容修订师",
        role="执行内容修订优化",
        stage="iteration",
    ),
    AgentDefinition(
        id="final_reviewer",
        name="最终审核官",
        role="最终审核确认",
        stage="iteration",
    ),
)


AUXILIARY_AGENT_DEFINITIONS: Tuple[AgentDefinition, ...] = (
    AgentDefinition(
        id="outline_plan_parser",
        name="大纲规划解析器",
        role="解析用户大纲规划为结构化数据",
        stage="structure",
        is_status_agent=False,
        default_enabled=False,
        supported_workflows=("outline_expansion", "inspiration_ark"),
    ),
    AgentDefinition(
        id="chapter_logic_checker",
        name="章节逻辑检查官",
        role="检查章节能力、境界和设定约束一致性",
        stage="review",
        is_runtime_agent=False,
        is_status_agent=False,
        default_enabled=False,
        supported_workflows=("chapter_generation", "inspiration_ark"),
    ),
)


ALL_AGENT_DEFINITIONS: Tuple[AgentDefinition, ...] = (
    *MAIN_WORKFLOW_AGENT_DEFINITIONS,
    *AUXILIARY_AGENT_DEFINITIONS,
)

_AGENT_BY_ID: Dict[str, AgentDefinition] = {
    definition.id: definition for definition in ALL_AGENT_DEFINITIONS
}


def iter_agent_definitions(*, status_only: bool = False) -> Iterable[AgentDefinition]:
    definitions = ALL_AGENT_DEFINITIONS
    if status_only:
        return (definition for definition in definitions if definition.is_status_agent)
    return iter(definitions)


def get_agent_definition(agent_id: str) -> Optional[AgentDefinition]:
    return _AGENT_BY_ID.get(agent_id)


def get_main_workflow_agent_definitions() -> Tuple[AgentDefinition, ...]:
    return MAIN_WORKFLOW_AGENT_DEFINITIONS


def get_stage_agent_definitions(stage: str) -> List[AgentDefinition]:
    return [
        definition
        for definition in MAIN_WORKFLOW_AGENT_DEFINITIONS
        if definition.stage == stage and definition.default_enabled
    ]


def get_stage_agent_payloads(stage: str, *, include_stage: bool = False) -> List[Dict[str, str]]:
    payloads: List[Dict[str, str]] = []
    for definition in get_stage_agent_definitions(stage):
        payload = {"id": definition.id, "name": definition.name}
        if include_stage:
            payload["stage"] = definition.stage
        payloads.append(payload)
    return payloads


def get_stage_agents_map(*, include_stage: bool = False) -> Dict[str, List[Dict[str, str]]]:
    stages = ("concept", "structure", "content", "review", "iteration")
    return {
        stage: get_stage_agent_payloads(stage, include_stage=include_stage)
        for stage in stages
    }
