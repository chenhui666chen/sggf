# -*- coding: utf-8 -*-
"""编排套件（Phase 2.6）：阶段契约 / handoff 3E 门位 / 版本图寻址+哈希 pin /
重试只补失败项 / 成本可见 / 探索轨 / AM-15 编排接线。

设计原则（对齐指导文档 10.2/10.3/10.4/10.5 摘取视图）：
  - 纯增量：不改状态机阶段流，run_until_done 单点记录 handoff；
  - 门位默认 warn 不阻断（现网安全），env 可切 block；
  - 版本寻址 round×shot，run.json 内容哈希 pin 全部输入（可复现闭环）；
  - 重试只补失败项（成功项复用，不为已成功素材重复付费）；
  - 成本台账逐资产记录（模型/token/秒数/费用），按镜头/模型聚合；
  - 探索轨试错不写 Canon、不占编辑链预算，提交时重过 QC；
  - AM-15 报告双格式挂 payload，repair_dispatch 供修复路由消费。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------- ① 阶段契约（强类型语义）
# 每阶段必需产出（缺一即 handoff 失败——3E 的 Examine 门位）；
# optional 为记录性产出（缺席只提示不判失败）。
STAGE_CONTRACTS: Dict[str, Dict[str, Any]] = {
    "SCRIPT": {
        "required": ["script_text", "script_entities", "script_review", "script_requires_review"],
        "optional": ["script_document", "story_graph", "character_profiles", "audio_markers"],
        "produces": "结构化剧本（2.2 剧本引擎）",
    },
    "STORYBOARD": {
        "required": ["storyboard", "storyboard_generation"],
        "optional": ["shot_contracts", "camera_states", "camera_tree", "storyboard_subject_pos"],
        "produces": "Shot Contract + 兼容分镜（2.3 Contract 引擎）",
    },
    "ASSET_LIBRARY": {
        "required": [],
        "optional": ["asset_library_spec", "project_assets"],
        "produces": "定妆图/资产（多角度分级）",
    },
    "KEYFRAMES": {
        "required": [],
        "optional": ["keyframes_meta"],
        "produces": "首尾帧（R-pre 双候选择优）",
    },
    "MIDFRAMES": {
        "required": [],
        "optional": [],
        "produces": "中间帧",
    },
    "VIDEO": {
        "required": [],
        "optional": ["video_done", "video_clips"],
        "produces": "视频片段（State Engine 锚定）",
    },
    "EDIT": {
        "required": [],
        "optional": ["edit_meta"],
        "produces": "合成成片",
    },
    "REVIEW": {
        "required": ["autoqc"],
        "optional": ["am15_report", "audit"],
        "produces": "QC 结果 + 修复路由 + AM-15 评价",
    },
}


def check_stage_handoff(stage: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """3E 的 Examine 门位：阶段必需产出齐全性检查（handoff_contract 强化）。"""
    name = str(stage or "").strip().upper()
    contract = STAGE_CONTRACTS.get(name)
    if not contract:
        return {"stage": name, "status": "no_contract", "missing": [], "optional_missing": []}
    required = contract["required"]
    missing = [k for k in required if not _has_payload_value(payload.get(k))]
    optional_missing = [k for k in contract.get("optional", []) if not _has_payload_value(payload.get(k))]
    status = "pass" if not missing else "fail"
    return {
        "stage": name,
        "status": status,
        "missing": missing,
        "optional_missing": optional_missing,
        "required_keys": required,
        "produces": contract.get("produces", ""),
    }


def _has_payload_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, dict)):
        return len(value) > 0
    if isinstance(value, str):
        return bool(value.strip())
    return True


def record_stage_handoff(payload: Dict[str, Any], stage: str) -> Dict[str, Any]:
    """记录一次 handoff 检查（payload['stage_handoffs'] 追加；默认 warn 不阻断）。"""
    report = check_stage_handoff(stage, payload)
    report["mode"] = str(os.getenv("DREAMWEAVER_HANDOFF_MODE", "warn") or "warn").strip().lower()
    hands = payload.get("stage_handoffs")
    payload["stage_handoffs"] = hands if isinstance(hands, list) else []
    payload["stage_handoffs"].append(report)
    # block 模式：缺必需产出直接抛错（宁可早失败）
    if report["mode"] == "block" and report["status"] == "fail":
        raise RuntimeError(f"stage {stage} handoff failed: missing {report['missing']}")
    return report


# ---------------------------------------------------------------- ② 版本图 round×shot 寻址 + 哈希 pin
def shot_address(run_id: str, round_no: int, shot_id: str) -> str:
    """round×shot 寻址（10.2 reproducibility_addressing）：round 2 永不覆盖 round 1。"""
    return f"runs/{run_id}/round_{max(1, int(round_no))}/{shot_id}"


def _content_sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def pin_run_inputs(
    run_dir: Path,
    *,
    round_no: int,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """run.json 内容哈希 pin：prompt/参考图引用/模型/参数/知识版本全部固定。

    返回 pinned 清单并写出 run.json（round 目录下，不覆盖历史 round）。
    """
    run_dir = Path(run_dir)
    inputs = {
        "style_prompt": str(payload.get("style_prompt") or ""),
        "style_preset": str(payload.get("style_preset") or ""),
        "image_config": payload.get("image_config") if isinstance(payload.get("image_config"), dict) else {},
        "video_config": payload.get("video_config") if isinstance(payload.get("video_config"), dict) else {},
        "storyboard": payload.get("storyboard") if isinstance(payload.get("storyboard"), list) else [],
        "shot_contracts": payload.get("shot_contracts") if isinstance(payload.get("shot_contracts"), list) else [],
        "script_source_version": (payload.get("script_document") or {}).get("source", {}).get("chapter_version")
        if isinstance(payload.get("script_document"), dict) else None,
    }
    pinned = {
        "round": int(round_no),
        "input_sha256": _content_sha(inputs),
        "inputs": inputs,
    }
    round_dir = run_dir / f"round_{max(1, int(round_no))}"
    round_dir.mkdir(parents=True, exist_ok=True)
    (round_dir / "run.json").write_text(
        json.dumps(pinned, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return pinned


def verify_reproducibility(run_dir: Path, *, round_no: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    """复现验证：同输入二次生成逐帧对比的前提——输入哈希一致（渲染可复现率 KPI 的输入侧）。"""
    round_dir = Path(run_dir) / f"round_{max(1, int(round_no))}"
    run_json = round_dir / "run.json"
    if not run_json.exists():
        return {"status": "no_pinned_inputs", "round": round_no}
    try:
        pinned = json.loads(run_json.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"status": "corrupt_run_json", "round": round_no}
    current = _content_sha({
        "style_prompt": str(payload.get("style_prompt") or ""),
        "style_preset": str(payload.get("style_preset") or ""),
        "image_config": payload.get("image_config") if isinstance(payload.get("image_config"), dict) else {},
        "video_config": payload.get("video_config") if isinstance(payload.get("video_config"), dict) else {},
        "storyboard": payload.get("storyboard") if isinstance(payload.get("storyboard"), list) else [],
        "shot_contracts": payload.get("shot_contracts") if isinstance(payload.get("shot_contracts"), list) else [],
        "script_source_version": (payload.get("script_document") or {}).get("source", {}).get("chapter_version")
        if isinstance(payload.get("script_document"), dict) else None,
    })
    return {
        "status": "match" if current == pinned.get("input_sha256") else "drift",
        "round": round_no,
        "pinned_sha": pinned.get("input_sha256"),
        "current_sha": current,
    }


# ---------------------------------------------------------------- ③ 重试只补失败项
def select_retry_items(
    all_ids: List[str],
    failed_ids: List[str],
    *,
    succeeded_cache: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """重试纪律（10.4 retry_discipline）：逐项返回成败，重试只补失败项——成功项直接复用。"""
    all_set = [str(i) for i in all_ids or []]
    failed = [str(i) for i in failed_ids or [] if str(i) in all_set]
    failed_set = set(failed)
    succeeded = [i for i in all_set if i not in failed_set]
    return {
        "retry_ids": failed,
        "reuse_ids": succeeded,
        "reused_from_cache": [i for i in succeeded if isinstance(succeeded_cache, dict) and i in succeeded_cache],
        "policy": "retry_only_failed（不为已成功素材重复付费）",
    }


# ---------------------------------------------------------------- ④ 成本台账
class CostLedger:
    """逐资产成本可见（10.4 cost_visibility）：生成前预估 + 生成后实际对账。"""

    def __init__(self) -> None:
        self._entries: List[Dict[str, Any]] = []

    def record(
        self,
        *,
        asset_id: str,
        model: str,
        cost: float,
        tokens: int = 0,
        seconds: float = 0.0,
        shot_id: str = "",
        stage: str = "",
        kind: str = "actual",
    ) -> None:
        self._entries.append({
            "asset_id": str(asset_id), "model": str(model), "cost": float(cost or 0),
            "tokens": int(tokens or 0), "seconds": float(seconds or 0),
            "shot_id": str(shot_id), "stage": str(stage), "kind": str(kind),
        })

    def summary(self) -> Dict[str, Any]:
        by_model: Dict[str, float] = {}
        by_shot: Dict[str, float] = {}
        total = 0.0
        for e in self._entries:
            total += e["cost"]
            by_model[e["model"]] = by_model.get(e["model"], 0.0) + e["cost"]
            key = e["shot_id"] or "-"
            by_shot[key] = by_shot.get(key, 0.0) + e["cost"]
        return {
            "total_cost": round(total, 4),
            "entries": len(self._entries),
            "by_model": {k: round(v, 4) for k, v in sorted(by_model.items())},
            "by_shot": {k: round(v, 4) for k, v in sorted(by_shot.items())},
        }

    def to_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        summary = self.summary()
        payload["cost_ledger"] = {"summary": summary, "entries": self._entries[-200:]}
        return payload["cost_ledger"]


# ---------------------------------------------------------------- ⑤ 探索轨（10.3 exploration_track）
class ExplorationTrack:
    """修复试错双轨：探索轨不写 Canon、不占编辑链预算；提交时重过 QC。"""

    def __init__(self, *, per_shot_cost_cap: float = 0.0) -> None:
        self.attempts: List[Dict[str, Any]] = []
        self.committed: List[str] = []
        self.per_shot_cost_cap = float(per_shot_cost_cap)  # 0 = 未设（调度侧按主轨减半注入）

    def try_record(self, *, shot_id: str, action: str, cost: float = 0.0, result: Any = None) -> Dict[str, Any]:
        entry = {
            "shot_id": str(shot_id), "action": str(action),
            "cost": float(cost or 0), "result": result,
            "writes_canon": False, "consumes_edit_budget": False,
        }
        self.attempts.append(entry)
        return entry

    def commit(self, *, shot_id: str) -> Dict[str, Any]:
        """提交回主管线：走版本节点 + 依赖校验 + 重过 QC（探索不豁免质量）。"""
        sid = str(shot_id)
        self.committed.append(sid)
        return {
            "shot_id": sid,
            "committed": True,
            "requires_qc": True,
            "attempts_used": sum(1 for a in self.attempts if a["shot_id"] == sid),
            "policy": "exploration_commit_requires_qc",
        }

    def report(self) -> Dict[str, Any]:
        return {
            "total_attempts": len(self.attempts),
            "total_cost": round(sum(a["cost"] for a in self.attempts), 4),
            "committed": list(dict.fromkeys(self.committed)),
            "canon_polluted": False,  # 探索轨设计上不写 Canon
        }


# ---------------------------------------------------------------- ⑥ AM-15 编排接线
def run_am15_stage(payload: Dict[str, Any], *, vlm_chat: Any = None) -> Dict[str, Any]:
    """REVIEW 阶段接线：AM-15 报告双格式挂 payload，repair_dispatch 供修复路由消费。

    失败静默降级（骨架报告保证可测）；视频路径探测留空 → 廉价自检 skipped。
    """
    enabled = str(os.getenv("DREAMWEAVER_AM15", "1") or "1").strip().lower() not in {"0", "false", "no"}
    if not enabled:
        payload["am15_report"] = {"status": "disabled"}
        return payload["am15_report"]
    try:
        from pipeline.autoqc_pkg._am15 import run_am15_evaluation

        video_paths = _detect_video_paths(payload)
        out = run_am15_evaluation(payload=payload, video_paths=video_paths, vlm_chat=vlm_chat)
        payload["am15_report"] = {
            "status": "ok",
            "markdown": out["markdown"],
            "critique": out["critique"],
        }
        # 修复路由消费入口：verdict/r_level_hint/重算标记
        payload["am15_repair_dispatch"] = out["critique"].get("repair_dispatch", {})
    except Exception as exc:  # noqa: BLE001 — AM-15 失败不阻断出片
        payload["am15_report"] = {"status": "error", "error": str(exc)[:200]}
    return payload["am15_report"]


def _detect_video_paths(payload: Dict[str, Any]) -> List[Path]:
    """从 payload 探测已生成视频片段路径（runs/{run_id}/ 下的 mp4）。"""
    run_id = str(payload.get("run_id") or "")
    if not run_id:
        return []
    candidates = [
        Path("runs") / run_id,
        Path("backend") / "runs" / run_id,
    ]
    for base in candidates:
        if base.exists():
            return sorted(p for p in base.rglob("*.mp4") if p.is_file())[:40]
    return []
