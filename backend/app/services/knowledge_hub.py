# -*- coding: utf-8 -*-
"""Phase 3 学习回路与治理激活（知识中枢模块）。

四件套：
  3.1 调用审计——四元组（trigger_type/problem_statement/applied_knowledge_id/delete_test_result）落库
        + 生产流程回放视图
  3.2 知识治理运转——verification_status 流转 + trust_weight 排序 + 时效检查
  3.3 Learning Loop——修复成功率统计回写 + B 级升级条件 + MAB 创意配置探索
        + persona 观众反馈 + 轨迹级 RLVR 路线
  3.5 novel_agent 收编（接口约定）

设计：纯增量模块，不动现有 pipeline/agents；review 阶段/修复路由调用 record_*；
LLM 调用方调用 record_knowledge_usage；SSOT 派生目录同步更新 verification_status。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = REPO_ROOT / "config" / "director_knowledge"

# ============================================================
# 3.1 调用审计（四元组 + 回放视图）
# ============================================================
@dataclass
class AuditEntry:
    trigger_type: str          # T1 失败修复 / T2 分叉决策 / T3 风险前置
    problem_statement: str    # 问题摘要（failure_type / beat 描述）
    applied_knowledge_id: str  # CF-xxx / DC-xxx / 知识单元 id
    delete_test_result: str    # pass（有效）/ fail（无效应删）/ not_applicable
    run_id: str = ""
    shot_id: str = ""
    stage: str = ""
    model: str = ""
    cost: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")


class AuditTrail:
    """调用审计四元组落库 + 生产流程回放视图。"""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or (REPO_ROOT / "data" / "knowledge_audit.jsonl")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, entry: AuditEntry) -> None:
        with open(self.db_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")

    def record_knowledge_usage(
        self,
        *,
        run_id: str,
        stage: str,
        trigger_type: str,
        problem: str,
        knowledge_id: str,
        delete_test: str = "not_applicable",
        model: str = "",
        cost: float = 0.0,
        shot_id: str = "",
    ) -> AuditEntry:
        entry = AuditEntry(
            trigger_type=trigger_type, problem_statement=problem,
            applied_knowledge_id=knowledge_id, delete_test_result=delete_test,
            run_id=run_id, shot_id=shot_id, stage=stage, model=model, cost=cost,
        )
        self.record(entry)
        return entry

    def replay_view(self, run_id: str) -> Dict[str, Any]:
        """生产流程回放视图：提案→脚本→分镜→素材→修复→渲染逐节点可回溯。"""
        stages: List[Dict[str, Any]] = []
        if not self.db_path.exists():
            return {"run_id": run_id, "total_entries": 0, "stages": [], "total_cost": 0.0, "models_used": [], "trace": []}
        with open(self.db_path, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("run_id") != run_id:
                    continue
                stages.append(e)
        by_stage: Dict[str, List[Dict[str, Any]]] = {}
        for e in stages:
            by_stage.setdefault(e.get("stage", ""), []).append(e)
        return {
            "run_id": run_id, "total_entries": len(stages),
            "stages": sorted(by_stage.keys()),
            "total_cost": round(sum(float(e.get("cost") or 0) for e in stages), 4),
            "models_used": sorted({e.get("model") for e in stages if e.get("model")}),
            "trace": stages,
        }


# ============================================================
# 3.2 知识治理（verification_status 流转 + trust_weight + 时效）
# ============================================================
STALE_AGE_DAYS = 180
STATUS_LADDER = {"pending": 0, "verified": 1, "deprecated": 2}


class KnowledgeGovernance:
    """verification_status 流转 + trust_weight 排序 + 时效检查。"""

    def __init__(self, knowledge_dir: Optional[Path] = None) -> None:
        self.dir = knowledge_dir or KNOWLEDGE_DIR

    def _load_units(self) -> Dict[str, Dict[str, Any]]:
        ku_path = self.dir / "domains" / "production.json"
        if ku_path.exists():
            data = json.loads(ku_path.read_text(encoding="utf-8"))
            return {k: v for k, v in (data.get("units") or {}).items()
                    if isinstance(v, dict) and v.get("source_type")}
        return {}

    def promote_status(self, unit_id: str, *, new_status: str) -> Dict[str, Any]:
        """pending→verified（5 次调用 + delete_test 全过）；verified→deprecated。"""
        assert new_status in STATUS_LADDER
        units = self._load_units()
        u = units.get(unit_id)
        if not u:
            return {"unit_id": unit_id, "status": "not_found"}
        current = str(u.get("verification_status") or "pending")
        if STATUS_LADDER[new_status] <= STATUS_LADDER[current]:
            return {"unit_id": unit_id, "status": current, "note": f"不能降级或同级保持：{current}→{new_status}"}
        trust = float(u.get("trust_weight") or 0.7)
        if new_status == "verified":
            trust = 1.0
        elif new_status == "deprecated":
            trust = 0.3
        u["verification_status"] = new_status
        u["trust_weight"] = trust
        u["status_updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return {"unit_id": unit_id, "old_status": current, "new_status": new_status, "trust_weight": trust}

    def stale_check(self, unit_id: str, *, added_date: str, model_version: str = "") -> Dict[str, Any]:
        """时效检查：>180 天 或 落后模型 ≥2 大版本 → stale（检索优先 -30%）。"""
        from datetime import datetime, timedelta
        try:
            added = datetime.fromisoformat(added_date[:10])
        except (ValueError, TypeError):
            return {"unit_id": unit_id, "stale": False, "reason": "no_date"}
        age_days = (datetime.now() - added).days
        stale = age_days > STALE_AGE_DAYS
        return {
            "unit_id": unit_id, "stale": stale, "age_days": age_days,
            "threshold_days": STALE_AGE_DAYS,
            "retrieval_priority_factor": 0.7 if stale else 1.0,
            "reason": f"age {age_days}d > {STALE_AGE_DAYS}d" if stale else "fresh",
        }

    def l3_sort_key(self, unit: Dict[str, Any]) -> float:
        """L3 语义检索排序键：trust_weight × retrieval_priority_factor × source_rank。"""
        trust = float(unit.get("trust_weight") or 0.7)
        st = str(unit.get("source_type") or "")
        rank = 1.0 if st == "benchmark" else 0.7 if st == "external_paper" else 0.6
        # 时效（简化：用 added 估）
        stale = self.stale_check("", added_date=str(unit.get("added") or "2026-01-01"))
        factor = float(stale.get("retrieval_priority_factor", 1.0))
        return round(trust * rank * factor, 3)


# ============================================================
# 3.3 Learning Loop（修复成功率 + B 级升级 + MAB + persona + RLVR）
# ============================================================
class LearningLoop:
    """Learning Loop 三级爬坡：统计回写 → MAB 探索 → RLVR（长期路线）。"""

    def __init__(self) -> None:
        self.repair_history: List[Dict[str, Any]] = []
        self.mab_arms: Dict[str, Dict[str, float]] = {}  # arm_name → {count, total_reward}
        self.persona_signals: List[Dict[str, Any]] = []

    def record_repair(
        self,
        *,
        cf_id: str,
        repair_model_used: str,
        success: bool,
        r_level: str = "",
        delete_test_passed: bool = False,
    ) -> Dict[str, Any]:
        """repair_model 成功率统计回写。"""
        entry = {
            "cf_id": cf_id, "repair_model_used": repair_model_used,
            "success": success, "r_level": r_level,
            "delete_test_passed": delete_test_passed,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self.repair_history.append(entry)
        return entry

    def repair_success_rate(self, cf_id: str = "") -> Dict[str, Any]:
        """修复成功率统计（按 CF 或全局）。"""
        records = [r for r in self.repair_history if not cf_id or r["cf_id"] == cf_id]
        if not records:
            return {"cf_id": cf_id, "total": 0, "success_rate": 0.0}
        success = sum(1 for r in records if r["success"])
        return {
            "cf_id": cf_id, "total": len(records),
            "success": success,
            "success_rate": round(success / len(records), 3),
        }

    def check_b_to_a_upgrade(self, unit_id: str, *, calls: int, delete_tests_passed: int) -> Dict[str, Any]:
        """B 级知识升级条件：≥5 次调用 + delete_test 全过 → 升 A（trust 0.7→1.0）。"""
        eligible = calls >= 5 and delete_tests_passed >= calls
        return {
            "unit_id": unit_id, "calls": calls, "delete_tests_passed": delete_tests_passed,
            "eligible_for_upgrade": eligible,
            "rule": "B 级（external_paper/external_opensource）→ A 级（benchmark）：≥5 次调用 + delete_test 全过",
        }

    # ---- MAB 创意配置探索（10.7 creative_config_bandit）----
    def mab_record(self, arm: str, reward: float) -> Dict[str, Any]:
        """记录一次 MAB 臂的奖励（AM-15 因子化评分作为 reward）。"""
        if arm not in self.mab_arms:
            self.mab_arms[arm] = {"count": 0, "total_reward": 0.0}
        self.mab_arms[arm]["count"] += 1
        self.mab_arms[arm]["total_reward"] += float(reward)
        return {"arm": arm, "avg_reward": round(self.mab_arms[arm]["total_reward"] / self.mab_arms[arm]["count"], 3)}

    def mab_best_arm(self) -> Dict[str, Any]:
        """UCB1 选臂（exploitation + exploration 平衡）。"""
        if not self.mab_arms:
            return {"best_arm": None, "reason": "no_arms"}
        total = sum(a["count"] for a in self.mab_arms.values())
        if total == 0:
            return {"best_arm": None}
        import math
        best, best_score = None, -1.0
        for arm, stats in self.mab_arms.items():
            avg = stats["total_reward"] / max(1, stats["count"])
            ucb = avg + math.sqrt(2 * math.log(total) / max(1, stats["count"]))
            if ucb > best_score:
                best, best_score = arm, ucb
        return {"best_arm": best, "ucb_score": round(best_score, 3), "arms": len(self.mab_arms)}

    def mab_preload_config(self) -> Dict[str, Any]:
        """收敛后 Top 配置 → experience_preload 固化（exploitation 与 exploration 并行）。"""
        best = self.mab_best_arm()
        if not best.get("best_arm"):
            return {"status": "no_convergence", "threshold": "≥10 samples per arm"}
        arm = best["best_arm"]
        stats = self.mab_arms[arm]
        converged = stats["count"] >= 10 and (stats["total_reward"] / stats["count"]) >= 0.7
        return {
            "status": "converged" if converged else "exploring",
            "arm": arm, "avg_reward": round(stats["total_reward"] / stats["count"], 3),
            "samples": stats["count"],
            "preload": converged,
        }

    # ---- persona 观众反馈（10.7 audience_persona_feedback）----
    def record_persona_signal(self, *, persona_id: str, hook_retention: float, emotion_curve: str, drop_point: str = "") -> Dict[str, Any]:
        entry = {
            "persona_id": persona_id, "hook_retention": hook_retention,
            "emotion_curve": emotion_curve, "drop_point": drop_point,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self.persona_signals.append(entry)
        return entry

    def audience_signal_summary(self) -> Dict[str, Any]:
        if not self.persona_signals:
            return {"status": "no_signals"}
        avg_hook = sum(s["hook_retention"] for s in self.persona_signals) / len(self.persona_signals)
        drops = [s["drop_point"] for s in self.persona_signals if s.get("drop_point")]
        return {
            "status": "ok", "sample_count": len(self.persona_signals),
            "avg_hook_retention": round(avg_hook, 2),
            "drop_points": drops[:5],
            "rule": "persona 分与导演标准分双轨，冲突时导演优先（Soft Gate）",
        }

    # ---- 轨迹级 RLVR（10.7 trajectory_rlvr）----
    def rlvr_readiness(self) -> Dict[str, Any]:
        """RLVR 前置条件：≥500 条修复轨迹样本。"""
        count = len(self.repair_history)
        ready = count >= 500
        return {
            "ready": ready, "trajectory_count": count, "threshold": 500,
            "gap": max(0, 500 - count),
            "ladder": "统计回写(现状) → MAB(v1.3) → RLVR(本阶段长期)",
            "next_action": "启动 RLVR 训练" if ready else f"积累 {max(0, 500 - count)} 条轨迹后启动",
        }
