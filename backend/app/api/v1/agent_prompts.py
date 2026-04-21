"""
Agent 提示词管理 API

提供 Agent 提示词的查看、编辑和重置功能。
用户可以在前端编辑提示词，并通过一键恢复按钮还原到系统默认提示词。
"""
import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.models.user import User
from app.services.prompts.manager import (
    prompt_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agent-prompts", tags=["Agent Prompts"])


# ============================================================================
# 数据模型
# ============================================================================

class AgentPromptInfo(BaseModel):
    """Agent 提示词基本信息"""
    key: str
    name: str
    prompt: str


class AgentPromptListResponse(BaseModel):
    """Agent 提示词列表响应"""
    agents: Dict[str, AgentPromptInfo]
    count: int


class AgentPromptUpdateRequest(BaseModel):
    """Agent 提示词更新请求"""
    prompt: str = Field(..., min_length=1, description="新的提示词内容")


class AgentPromptResetRequest(BaseModel):
    """Agent 提示词重置请求（不需要 body，从 JSON 重新加载）"""
    pass


class AgentPromptResetResponse(BaseModel):
    """Agent 提示词重置响应"""
    success: bool
    key: str
    message: str
    restored_prompt_length: int


class AgentPromptDetailResponse(BaseModel):
    """Agent 提示词详情响应"""
    key: str
    name: str
    prompt: str
    default_prompt: str
    is_customized: bool
    user_prompts: Dict[str, Dict[str, Any]] = {}


# ============================================================================
# API 端点
# ============================================================================

@router.get("/list", response_model=AgentPromptListResponse)
async def list_agent_prompts(current_user: User = Depends(get_current_user)):
    """获取所有 Agent 的提示词列表"""
    prompt_manager.reload()
    agents = prompt_manager.list_agents()
    result = {}
    for key, name in agents.items():
        prompt = prompt_manager.get_agent_prompt(key)
        result[key] = AgentPromptInfo(key=key, name=name, prompt=prompt)
    return AgentPromptListResponse(agents=result, count=len(result))


@router.get("/detail/{agent_key}", response_model=AgentPromptDetailResponse)
async def get_agent_prompt_detail(
    agent_key: str,
    current_user: User = Depends(get_current_user),
):
    """获取指定 Agent 的提示词详情（含默认值对比和关联的 user prompt）"""
    prompt_manager.reload()
    name = prompt_manager.get_agent_name(agent_key)
    if not name:
        raise HTTPException(status_code=404, detail=f"Agent 不存在: {agent_key}")

    current_prompt = prompt_manager.get_agent_prompt(agent_key)
    default_prompt = prompt_manager.get_agent_prompt(agent_key, force_default=True)
    is_customized = current_prompt != default_prompt if default_prompt else False

    user_prompt_keys = prompt_manager.get_agent_user_prompt_keys(agent_key)
    user_prompts: Dict[str, Any] = {}
    for pk in user_prompt_keys:
        current_tpl = prompt_manager.get_user_prompt(pk)
        default_tpl = prompt_manager.get_user_prompt(pk, force_default=True)
        user_prompts[pk] = {
            "key": pk,
            "template": current_tpl,
            "default_template": default_tpl,
            "is_customized": current_tpl != default_tpl if default_tpl else False,
        }

    return AgentPromptDetailResponse(
        key=agent_key,
        name=name,
        prompt=current_prompt,
        default_prompt=default_prompt or current_prompt,
        is_customized=is_customized,
        user_prompts=user_prompts,
    )


@router.put("/update-user-prompt/{prompt_key}")
async def update_user_prompt(
    prompt_key: str,
    request: AgentPromptUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """更新指定 user prompt 模板"""
    prompt_manager.reload()
    prompts = prompt_manager.list_user_prompts()
    if prompt_key not in prompts:
        raise HTTPException(status_code=404, detail=f"User prompt 不存在: {prompt_key}")

    success = prompt_manager.update_user_prompt(prompt_key, request.prompt)
    if not success:
        raise HTTPException(status_code=500, detail="User prompt 更新失败")

    return {"success": True, "message": f"User prompt [{prompt_key}] 已更新"}


@router.post("/reset-user-prompt/{prompt_key}")
async def reset_user_prompt(
    prompt_key: str,
    current_user: User = Depends(get_current_user),
):
    """一键恢复 user prompt 模板到系统默认值"""
    prompt_manager.reload()
    prompts = prompt_manager.list_user_prompts()
    if prompt_key not in prompts:
        raise HTTPException(status_code=404, detail=f"User prompt 不存在: {prompt_key}")

    restored = prompt_manager.get_user_prompt(prompt_key, force_default=True)
    if not restored:
        raise HTTPException(status_code=404, detail=f"User prompt 默认模板未找到: {prompt_key}")

    success = prompt_manager.reset_user_prompt(prompt_key)
    if not success:
        raise HTTPException(status_code=500, detail="User prompt 重置失败")

    return {
        "success": True,
        "message": f"User prompt [{prompt_key}] 已恢复为默认值",
        "restored_template_length": len(restored),
    }


@router.put("/update/{agent_key}")
async def update_agent_prompt(
    agent_key: str,
    request: AgentPromptUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """更新指定 Agent 的提示词"""
    prompt_manager.reload()
    name = prompt_manager.get_agent_name(agent_key)
    if not name:
        raise HTTPException(status_code=404, detail=f"Agent 不存在: {agent_key}")

    success = prompt_manager.update_agent_prompt(agent_key, request.prompt)
    if not success:
        raise HTTPException(status_code=500, detail="提示词更新失败")

    return {"success": True, "message": f"Agent [{name}] 的提示词已更新"}


@router.post("/reset/{agent_key}", response_model=AgentPromptResetResponse)
async def reset_agent_prompt(
    agent_key: str,
    current_user: User = Depends(get_current_user),
):
    """一键恢复 Agent 的提示词到系统默认值"""
    prompt_manager.reload()
    name = prompt_manager.get_agent_name(agent_key)
    if not name:
        raise HTTPException(status_code=404, detail=f"Agent 不存在: {agent_key}")

    restored_prompt = prompt_manager.get_agent_prompt(agent_key, force_default=True)
    if not restored_prompt:
        raise HTTPException(status_code=404, detail=f"Agent 默认提示词未找到: {agent_key}")

    success = prompt_manager.reset_agent_prompt(agent_key)
    if not success:
        raise HTTPException(status_code=500, detail="提示词重置失败")

    return AgentPromptResetResponse(
        success=True,
        key=agent_key,
        message=f"Agent [{name}] 的提示词已恢复为默认值",
        restored_prompt_length=len(restored_prompt),
    )


@router.get("/user-prompts")
async def list_user_prompts(current_user: User = Depends(get_current_user)):
    """获取所有 user prompt 模板列表"""
    prompt_manager.reload()
    prompts = prompt_manager.list_user_prompts()
    result = {}
    for key, description in prompts.items():
        template = prompt_manager.get_user_prompt(key)
        result[key] = {
            "key": key,
            "description": description,
            "template": template,
        }
    return {"prompts": result, "count": len(result)}
