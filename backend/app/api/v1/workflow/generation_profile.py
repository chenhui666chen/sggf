"""生成档位（GenerationProfile）解析。

原则：
- ``generation_tier`` 请求字段只表达用户意图，不是权限依据
- 最终档位由服务端权益判定决定；免费档强制开关开启后，
  无标准档角色的用户无论传什么都落入免费档
- 端点解析出不可变 profile，后台任务只接受解析后的明确参数
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.config import settings
from app.api.v1.workflow.model_selection import resolve_workflow_generation_model

FREE_TIER_MODEL_ID = "qwen3.7-flash"

VALID_GENERATION_TIERS = {"free", "standard"}


@dataclass(frozen=True)
class GenerationProfile:
    tier: str                          # "free" | "standard"
    model: Optional[str]               # 免费档强制 qwen3.7-flash；标准档为用户所选模型
    max_iteration_rounds: int          # 免费档 1；标准档沿用 settings 默认
    enable_multi_model_review: bool    # 免费档 False
    max_llm_attempts: int              # 总尝试次数（含首次）
    allow_model_fallback: bool         # 免费档 False：禁止 catalog guard 换模型
    quota_enabled: bool                # 免费档 True


FREE_PROFILE = GenerationProfile(
    tier="free",
    model=FREE_TIER_MODEL_ID,
    max_iteration_rounds=1,
    enable_multi_model_review=False,
    max_llm_attempts=2,
    allow_model_fallback=False,
    quota_enabled=True,
)


def _standard_role_codes() -> set[str]:
    raw = str(getattr(settings, "FREE_TIER_STANDARD_ROLE_CODES", "") or "")
    return {code.strip() for code in raw.split(",") if code.strip()}


def user_has_standard_generation_access(current_user) -> bool:
    """按角色码判定用户是否具备标准档权益（复用现有 Role 体系）。"""
    allowed_codes = _standard_role_codes()
    if not allowed_codes:
        return False
    for role in getattr(current_user, "roles", None) or []:
        if getattr(role, "is_active", False) and getattr(role, "code", None) in allowed_codes:
            return True
    return False


def build_standard_profile(requested_model: Optional[str]) -> GenerationProfile:
    """标准档 profile：模型准入校验失败时抛 ValueError（与既有行为一致）。"""
    resolved_model = resolve_workflow_generation_model(requested_model)
    return GenerationProfile(
        tier="standard",
        model=resolved_model,
        max_iteration_rounds=int(getattr(settings, "ITERATION_MAX_ROUNDS", 2)),
        enable_multi_model_review=True,
        max_llm_attempts=3,
        allow_model_fallback=True,
        quota_enabled=False,
    )


def resolve_generation_profile(
    *,
    current_user,
    requested_tier: Optional[str],
    requested_model: Optional[str],
) -> GenerationProfile:
    """服务端解析最终生成档位。

    行为矩阵：
    - 显式请求 free：始终落免费档
    - 强制开关关闭：standard/缺省 走标准档（与现状一致）
    - 强制开关开启且用户无标准档角色：无论传什么都落免费档
    """
    tier = (requested_tier or "standard").strip().lower()
    if tier not in VALID_GENERATION_TIERS:
        raise ValueError(f"Unsupported generation tier: {requested_tier}")
    if tier == "free":
        return FREE_PROFILE
    if getattr(settings, "FREE_TIER_ENFORCEMENT_ENABLED", False) and not user_has_standard_generation_access(current_user):
        return FREE_PROFILE
    return build_standard_profile(requested_model)
