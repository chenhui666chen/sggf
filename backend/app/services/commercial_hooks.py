# -*- coding: utf-8 -*-
"""Phase 4 商业化预挂钩（4.3 合规 / 4.4 SaaS / 4.5 批量栏目）。

三件套：
  4.3 合规预挂钩——AI 标注字段 + 生产留痕 + 跨平台发布参照（MoneyPrinterTurbo）
  4.4 SaaS 挂钩——积分计量 + 管理后台数据源 + 预算管控三档（总额/单步/超限熔断）
  4.5 批量栏目——模板化验证 + brand-lock 品牌锁定 + 批量渲染参数注入
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ============================================================
# 4.3 合规预挂钩：AI 标注 + 生产留痕 + 跨平台发布
# ============================================================
@dataclass
class ComplianceRecord:
    """生产留痕：谁/何时/哪个模型/哪个知识单元/是否 AI 生成。"""
    run_id: str
    stage: str
    model: str = ""
    knowledge_ids: str = ""        # comma-separated CF-xxx/DC-xxx
    ai_generated: bool = True       # 默认 AI 生成
    content_safety_passed: bool = True
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_compliance_record(
    *,
    run_id: str,
    stage: str,
    model: str = "",
    knowledge_ids: List[str] = None,
    content_safety_passed: bool = True,
) -> ComplianceRecord:
    """AI 标注 + 生产留痕（对齐 2026-09-01《微短剧发展管理办法》11 条红线）。"""
    return ComplianceRecord(
        run_id=run_id, stage=stage, model=model,
        knowledge_ids=",".join(knowledge_ids or []),
        content_safety_passed=content_safety_passed,
    )


# 跨平台发布参照（MoneyPrinterTurbo 的发布能力映射）
PLATFORM_PUBLISH_MAP: Dict[str, Dict[str, Any]] = {
    "youtube": {
        "endpoint": "YouTube Data API v3",
        "auto_ai_label": True,  # YouTube 自动标注 AI 生成内容
        "format": "16:9",
        "max_duration_s": 600,
    },
    "tiktok": {
        "endpoint": "TikTok Content Posting API",
        "auto_ai_label": False,  # 需手动标注
        "format": "9:16",
        "max_duration_s": 600,
    },
    "instagram": {
        "endpoint": "Instagram Graph API",
        "auto_ai_label": False,
        "format": "9:16",
        "max_duration_s": 90,
    },
}


def publish_compliance_check(*, platform: str, ai_generated: bool, duration_s: float) -> Dict[str, Any]:
    """发布合规检查：AI 标注需求 + 时长限制 + 格式匹配。"""
    spec = PLATFORM_PUBLISH_MAP.get(platform.lower())
    if not spec:
        return {"platform": platform, "status": "unknown_platform"}
    issues: List[str] = []
    if ai_generated and not spec["auto_ai_label"]:
        issues.append("需手动标注 AI 生成内容（平台不自动标注）")
    if duration_s > spec["max_duration_s"]:
        issues.append(f"时长 {duration_s}s 超限 {spec['max_duration_s']}s")
    return {
        "platform": platform, "format": spec["format"],
        "auto_ai_label": spec["auto_ai_label"],
        "ai_label_required": ai_generated,
        "issues": issues,
        "status": "pass" if not issues else "fail",
    }


# ============================================================
# 4.4 SaaS 挂钩：积分计量 + 管理后台 + 预算管控
# ============================================================
@dataclass
class BudgetControl:
    """预算管控三档（指导文档 4.4）：项目总额 / 单步阈值 / 超限熔断。"""
    project_total_cap: float = 0.0       # 0 = 不限
    per_step_threshold: float = 0.0      # 0 = 不限
    accumulated: float = 0.0
    blocked: bool = False

    def charge(self, *, cost: float, step: str = "") -> Dict[str, Any]:
        """计费：单步超阈值 → 需人工审批；总额超限 → 熔断（不静默扣费）。"""
        self.accumulated += float(cost)
        step_exceeded = self.per_step_threshold > 0 and cost > self.per_step_threshold
        total_exceeded = self.project_total_cap > 0 and self.accumulated > self.project_total_cap
        if total_exceeded:
            self.blocked = True
            return {
                "action": "block", "step": step, "cost": cost,
                "accumulated": round(self.accumulated, 4),
                "cap": self.project_total_cap,
                "reason": "项目总额超限→熔断（不静默扣费）",
            }
        if step_exceeded:
            return {
                "action": "require_approval", "step": step, "cost": cost,
                "threshold": self.per_step_threshold,
                "reason": "单步费用超阈值→需人工审批",
            }
        return {"action": "pass", "step": step, "cost": cost, "accumulated": round(self.accumulated, 4)}


def points_charge(*, stage: str, model: str, tokens: int, seconds: float = 0.0) -> Dict[str, Any]:
    """积分计量：按阶段 × 模型 × token/秒数 换算积分消耗。

    阶段权重：SCRIPT 1.0 / STORYBOARD 0.5（确定性引擎零 LLM）/ KEYFRAMES 3.0 / VIDEO 5.0
    """
    stage_weights = {"SCRIPT": 1.0, "STORYBOARD": 0.5, "KEYFRAMES": 3.0, "VIDEO": 5.0,
                     "EDIT": 1.0, "REVIEW": 0.5, "ASSET_LIBRARY": 2.0}
    weight = stage_weights.get(str(stage).upper(), 1.0)
    base_points = max(tokens / 1000, seconds / 10)  # 1k token = 1 point; 10s = 1 point
    points = round(base_points * weight, 2)
    return {"stage": stage, "model": model, "tokens": tokens, "seconds": seconds,
            "weight": weight, "points": points, "note": "知识中枢调用纳入积分计量"}


def admin_dashboard_data(
    *,
    audit_entries: List[Dict[str, Any]],
    repair_history: List[Dict[str, Any]],
    knowledge_governance: Dict[str, Any],
) -> Dict[str, Any]:
    """管理后台展示数据源：知识验证状态 + 修复成功率 + 调用统计。"""
    total = len(repair_history)
    success = sum(1 for r in repair_history if r.get("success"))
    return {
        "knowledge_verification_summary": knowledge_governance,
        "repair_stats": {
            "total_repair_attempts": total,
            "success_count": success,
            "success_rate": round(success / total, 3) if total else 0.0,
        },
        "audit_stats": {
            "total_calls": len(audit_entries),
            "stages": sorted({e.get("stage") for e in audit_entries if e.get("stage")}),
            "knowledge_ids_used": len({e.get("applied_knowledge_id") for e in audit_entries if e.get("applied_knowledge_id")}),
        },
        "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


# ============================================================
# 4.5 批量栏目：模板化 + brand-lock + 批量渲染参数注入
# ============================================================
@dataclass
class BrandLock:
    """品牌锁定快照（Shotkit brand-lock 模式）：品牌资产→冻结参数。"""
    brand_id: str
    style_prompt: str
    style_preset: str
    image_config: Dict[str, Any]
    video_config: Dict[str, Any]
    snapshot_hash: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.snapshot_hash:
            content = json.dumps({
                "style_prompt": self.style_prompt, "style_preset": self.style_preset,
                "image_config": self.image_config, "video_config": self.video_config,
            }, sort_keys=True, ensure_ascii=False)
            self.snapshot_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def batch_render_plan(
    *,
    template: Dict[str, Any],
    dataset: List[Dict[str, Any]],
    brand_lock: Optional[BrandLock] = None,
) -> Dict[str, Any]:
    """批量渲染参数注入：一条通过验收的模板 + JSON 数据集 → N 条成片。

    边际成本趋零验证路径：固定模板 + 变量注入 + brand-lock 保证一致性。
    """
    items: List[Dict[str, Any]] = []
    for i, row in enumerate(dataset):
        params = dict(template)
        params["source_text"] = str(row.get("source_text") or row.get("text") or "")
        params["run_id"] = f"batch_{brand_lock.brand_id if brand_lock else 'default'}_{i:03d}" if brand_lock else f"batch_{i:03d}"
        if brand_lock:
            params["style_prompt"] = brand_lock.style_prompt
            params["style_preset"] = brand_lock.style_preset
            params["image_config"] = brand_lock.image_config
            params["video_config"] = brand_lock.video_config
            params["brand_lock_snapshot"] = brand_lock.snapshot_hash
        items.append(params)
    return {
        "template_keys": sorted(template.keys()),
        "dataset_rows": len(dataset),
        "batch_count": len(items),
        "brand_lock": brand_lock.to_dict() if brand_lock else None,
        "note": "固定栏目模板化：一条通过验收的模板 + JSON 数据集 → 参数注入 → 批量渲染 N 条成片",
        "cost_projection": "边际成本趋零（模板复用 + 知识缓存 + brand-lock 保证一致性）",
        "items_preview": items[:3],
        "items_total": len(items),
    }
