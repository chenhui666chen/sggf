# -*- coding: utf-8 -*-
"""
AI Director OS · SSOT 知识拆分挂载脚本（落地实施指导 v1.5 · Phase 2.1）
================================================================
把 ai_director_os 三件套 SSOT JSON 按消费方拆分为可挂载知识文件，输出到
config/director_knowledge/，并生成挂载清单 manifest.json 与完整性校验。

用法：
    python scripts/split_director_knowledge.py                 # 拆分 + 校验
    python scripts/split_director_knowledge.py --check-only    # 只校验已有产物
    python scripts/split_director_knowledge.py --source <json> --out <dir>

约定（对齐指导文档 §8.1 / §三）：
  - JSON 为 SSOT，本目录全部产物均为派生文件，禁止手改（改 SSOT 后重跑本脚本）；
  - 未登记不进检索池：content_status=pending_content 的单元不出现在检索池，
    仅在域文件中保留 id 注册（内容回填 SSOT knowledge_units 后重新派生）；
  - 检索通道：L1=失败码直索（failure_cases.json 按 CF id）；
              L2=结构化触发（beat_family_routing.json / cf_triggers.json）；
              L3=语义兜底（运行时由宿主 semantic_asset_index 实现，本目录提供索引字段）。
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------- 常量
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "ai_director_os" / "AI_Director_OS_V5_Agent_Training_R6_11_MASTER_CONTENT_INTEGRITY_CHECK.json"
DEFAULT_OUT = REPO_ROOT / "config" / "director_knowledge"

GUIDE_VERSION = "v1.5"
SCHEMA_VERSION = "1.0"

# SSOT 基线计数（与指导文档 §1.1 / 校验记录一致）
EXPECTED = {
    "director_cases": 37,
    "failure_cases": 102,
    "knowledge_units_total": 94,   # 7 域单元总数（2026-10-07 图片层+8 / 大象学长+3）
    "am_modules": 17,
    "model_router_families": 7,
    "beat_families": 7,
}

# image_generation 域索引名 → SSOT image_generation 块键名 的别名映射
IG_KEY_ALIAS = {"asset_qc": "qc_checks"}

# 优先回填清单（Phase 2.2/2.3 实现急需、当前 index-only 的单元 → 用途）
PRIORITY_BACKFILL = {
    "shot_size_system": "Phase 2.3 五级景别系统（Contract 引擎核心）",
    "technique_interference_check": "Phase 2.3 T3 预检·技巧干涉预算",
    "camera_lighting_prompt_lexicon": "Phase 2.3 模型执行词典（高/中/低服从度）",
    "cinematography_decision_library": "Phase 2.3 摄影决策库（DC-035/036 之外的总纲）",
    "cut_technique_library": "Phase 2.3 切换技法库（切换选型）",
    "transition_library": "Phase 2.3 转场库",
    "dialogue_coverage": "Phase 2.2 对白镜头覆盖（剧本引擎）",
    "resonance_design": "Phase 2.2 共鸣设计（剧本引擎）",
}


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dump_json(path: Path, obj) -> dict:
    """写出 JSON 并返回文件条目（含哈希）。用 write_bytes 保证与哈希计算的字节完全一致。"""
    payload = (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "path": path.relative_to(DEFAULT_OUT).as_posix() if path.is_relative_to(DEFAULT_OUT) else str(path),
        "type": obj.get("_type", "knowledge"),
        "count": obj.get("_count"),
        "sha256": sha256_of(payload),
    }


# ---------------------------------------------------------------- 拆分逻辑
def resolve_unit_content(uid: str, domain: str, ssot: dict) -> tuple[dict, str]:
    """按优先级解析单元内容来源：knowledge_units > image_generation 块 > volume10.10.3。
    返回 (unit_obj, source_tag)；无法解析时返回 pending 占位。"""
    ku = ssot.get("knowledge_units", {}).get("units", {})
    if uid in ku:
        return dict(ku[uid]), "knowledge_units"
    if domain == "image_generation":
        key = IG_KEY_ALIAS.get(uid, uid)
        ig = ssot.get("image_generation", {})
        if key in ig:
            return {"content": ig[key], "source_project": "SSOT image_generation 板块"}, f"image_generation.{key}"
    v103 = ssot["volume10"].get("10.3_continuity_dependency_minimal_rework", {})
    if uid in v103:
        return {"content": v103[uid]}, f"volume10.10.3.{uid}"
    return {
        "content_status": "pending_content",
        "note": "内容在归档 DOCX/XLSX（v1.2 起只读），待回填 SSOT knowledge_units 后重新派生",
        "priority_backfill": PRIORITY_BACKFILL.get(uid),
    }, "pending"


def load_and_validate(source: Path) -> dict:
    with open(source, encoding="utf-8") as f:
        ssot = json.load(f)
    checks = {
        "director_cases": len(ssot["director_cases"]),
        "failure_cases": len(ssot["failure_cases"]),
        "knowledge_units_total": sum(len(v) for v in ssot["core_knowledge"].values()),
        "am_modules": len(ssot["directing_systems"]["modules"]),
        "model_router_families": len(ssot["model_router"]),
    }
    for k, exp in EXPECTED.items():
        if k == "beat_families":
            continue
        if checks[k] != exp:
            raise SystemExit(f"[FAIL] SSOT 计数不符：{k}={checks[k]}（期望 {exp}）——请先核对 SSOT 与指导文档")
    t2 = ssot["volume10"]["10.5_multi_agent_production_orchestrator"]["knowledge_dispatch_orchestration"]["t2_beat_routing"]
    if len(t2["beat_families"]) != EXPECTED["beat_families"]:
        raise SystemExit("[FAIL] beat 族数不是 7")
    print(f"[OK] SSOT 基线校验通过：{checks}")
    return ssot


def split(ssot: dict, source: Path, out: Path) -> dict:
    files = []
    src_bytes = source.read_bytes()
    src_sha = sha256_of(src_bytes)

    # ---------- 1. 七域知识文件 ----------
    stats_units = {"with_content": 0, "pending_content": 0}
    pending_list = []
    for domain, unit_ids in ssot["core_knowledge"].items():
        units = {}
        for uid in unit_ids:
            content, tag = resolve_unit_content(uid, domain, ssot)
            units[uid] = content
            if tag == "pending":
                stats_units["pending_content"] += 1
                pending_list.append(f"{domain}/{uid}")
            else:
                stats_units["with_content"] += 1
        entry = dump_json(out / "domains" / f"{domain}.json", {
            "_type": "domain",
            "domain": domain,
            "unit_count": len(unit_ids),
            "units": units,
        })
        entry["count"] = len(unit_ids)
        files.append(entry)

    # ---------- 2. 案例库 ----------
    dcs = ssot["director_cases"]
    files.append(dump_json(out / "cases" / "director_cases.json", {
        "_type": "director_cases", "_count": len(dcs), "cases": dcs,
    }))

    cfs = ssot["failure_cases"]
    files.append(dump_json(out / "cases" / "failure_cases.json", {
        "_type": "failure_cases", "_count": len(cfs),
        "index_note": "L1 直索通道：按 CF id 直接命中；repair_model 优先于 repair（双视角修复）",
        "cases": cfs,
    }))

    # 资产生成层 CF（image_generation 板块内 8 条）
    ag_cf = ssot.get("image_generation", {}).get("failure_cases", [])
    if ag_cf:
        files.append(dump_json(out / "cases" / "asset_generation_failures.json", {
            "_type": "asset_generation_failures", "_count": len(ag_cf), "cases": ag_cf,
        }))

    # ---------- 3. T2 beat 七族路由 ----------
    kdo = ssot["volume10"]["10.5_multi_agent_production_orchestrator"]["knowledge_dispatch_orchestration"]
    t2 = kdo["t2_beat_routing"]
    dc_ids = {c["id"] for c in dcs}
    routed = set()
    for fam in t2["beat_families"]:
        for dc_id in fam["dispatch"]:
            if dc_id not in dc_ids:
                raise SystemExit(f"[FAIL] beat 族 {fam['family']} 引用了不存在的 {dc_id}")
            routed.add(dc_id)
    unrouted = sorted(dc_ids - routed, key=lambda x: int(x.split("-")[1]))
    files.append(dump_json(out / "cases" / "beat_family_routing.json", {
        "_type": "beat_family_routing", "_count": len(t2["beat_families"]),
        "purpose": t2["purpose"],
        "routing_key": t2["routing_key"],
        "beat_families": t2["beat_families"],
        "fallback": t2["fallback"],
        "unrouted_note": "未登记 beat 族的 DC（技法/剪辑/运镜/灯光类，按阶段或 T2 分叉触发，不走路由；无触发不检索）：",
        "unrouted_dc_ids": unrouted,
    }))

    # ---------- 4. T3 预检触发器（结构化 auto_trigger + CF-088 qc 特例） ----------
    structured = []
    for c in cfs:
        if isinstance(c.get("auto_trigger"), dict):
            structured.append({
                "cf_id": c["id"],
                "title": c.get("title"),
                "trigger_condition": c["auto_trigger"].get("trigger_condition"),
                "judgment_signals": c["auto_trigger"].get("judgment_signals"),
                "disposition": c["auto_trigger"].get("disposition"),
            })
    # CF-088 的 qc 字段内嵌 EMOTION_STALL_CHECK 结构（指导文档 T3 预检清单的第 16 条）
    cf088 = next((c for c in cfs if c["id"] == "CF-088"), None)
    esc_added = False
    if cf088 and isinstance(cf088.get("qc"), dict):
        esc = cf088["qc"].get("emotion_stall_check")
        if esc:
            structured.append({
                "cf_id": "CF-088",
                "title": cf088.get("title"),
                "trigger_condition": esc.get("trigger_condition") or esc.get("trigger"),
                "judgment_signals": esc.get("judgment_signals") or esc.get("signals"),
                "disposition": esc.get("disposition"),
                "source_field": "qc.emotion_stall_check",
            })
            esc_added = True
    files.append(dump_json(out / "cases" / "cf_triggers.json", {
        "_type": "cf_triggers", "_count": len(structured),
        "purpose": "T3 风险前置：Shot Contract 生成前的结构化预检（先于生成，对齐 10.6 candidate_selection_gate 之前的门位）",
        "unstructured_note": f"其余 {len(cfs) - len(structured) + (1 if esc_added else 0)} 条 CF 暂无结构化 auto_trigger，"
                             "走 L1（事后修复直索）与 L3（语义），按治理协议逐步补结构化",
        "triggers": structured,
    }))

    # ---------- 5. AM 模块与模型路由 ----------
    files.append(dump_json(out / "modules" / "am_modules.json", {
        "_type": "am_modules", "_count": len(ssot["directing_systems"]["modules"]),
        "schema": ssot["directing_systems"].get("schema"),
        "modules": ssot["directing_systems"]["modules"],
    }))
    files.append(dump_json(out / "modules" / "model_router.json", {
        "_type": "model_router", "_count": len(ssot["model_router"]),
        "families": ssot["model_router"],
    }))

    # ---------- 6. 编排协议（2.2-2.6 实现直接消费的字段，按模块摘取） ----------
    v10 = ssot["volume10"]
    o55 = v10["10.5_multi_agent_production_orchestrator"]
    orch = {
        "_type": "orchestration",
        "note": "volume10 中 Phase 2.2-2.6 实现所需关键字的摘取视图；完整定义以 SSOT 为准",
        "state_engine_10_1": {
            "principle": v10["10.1_episode_state_engine"].get("principle"),
            "transition_rule": v10["10.1_episode_state_engine"].get("transition_rule"),
            "state_domains": v10["10.1_episode_state_engine"].get("state_domains"),
            "hard_soft": v10["10.1_episode_state_engine"].get("hard_soft"),
        },
        "version_graph_10_2": {
            "version_compare_protocol": v10["10.2_version_graph_state_diff_rollback"].get("version_compare_protocol"),
            "reproducibility_addressing": v10["10.2_version_graph_state_diff_rollback"].get("reproducibility_addressing"),
        },
        "rework_10_3": {
            "edit_chain_degradation_budget": v10["10.3_continuity_dependency_minimal_rework"].get("edit_chain_degradation_budget"),
            "r3_edit_capability_map": v10["10.3_continuity_dependency_minimal_rework"].get("r3_edit_capability_map"),
            "exploration_track": v10["10.3_continuity_dependency_minimal_rework"].get("exploration_track"),
            "priority_score": v10["10.3_continuity_dependency_minimal_rework"].get("priority_score"),
        },
        "scheduler_10_4": {
            "retry_discipline": v10["10.4_episode_production_scheduler"].get("retry_discipline"),
            "cost_visibility": v10["10.4_episode_production_scheduler"].get("cost_visibility"),
            "failure_policy": v10["10.4_episode_production_scheduler"].get("failure_policy"),
        },
        "orchestrator_10_5": {
            "collaboration_protocols": o55.get("collaboration_protocols"),
            "hierarchical_creative_config": o55.get("hierarchical_creative_config"),
            "context_discipline": o55.get("context_discipline"),
            "stage_completeness_3e": o55.get("stage_completeness_3e"),
            "knowledge_dispatch_orchestration": kdo,
            "first_generation_knowledge_flow": o55.get("first_generation_knowledge_flow"),
            "human_gates": o55.get("human_gates"),
            "handoff_contract": o55.get("handoff_contract"),
        },
        "qc_10_6": {
            "hard_gates": v10["10.6_qc_acceptance_system"].get("hard_gates"),
            "soft_dimensions": v10["10.6_qc_acceptance_system"].get("soft_dimensions"),
            "candidate_selection_gate": v10["10.6_qc_acceptance_system"].get("candidate_selection_gate"),
            "machine_readable_critique": v10["10.6_qc_acceptance_system"].get("machine_readable_critique"),
            "qc_report_fields": v10["10.6_qc_acceptance_system"].get("qc_report_fields"),
            "failure_codes": v10["10.6_qc_acceptance_system"].get("failure_codes"),
            "repair_dual_perspective": v10["10.6_qc_acceptance_system"].get("repair_dual_perspective"),
        },
        "learning_loop_10_7": {
            "creative_config_bandit": v10["10.7_production_learning_loop"].get("creative_config_bandit"),
            "audience_persona_feedback": v10["10.7_production_learning_loop"].get("audience_persona_feedback"),
            "knowledge_governance": v10["10.7_production_learning_loop"].get("knowledge_governance"),
            "learning_loop": v10["10.7_production_learning_loop"].get("learning_loop"),
        },
    }
    files.append(dump_json(out / "orchestration.json", orch))

    # ---------- 7. manifest ----------
    manifest = {
        "_type": "manifest",
        "schema_version": SCHEMA_VERSION,
        "guide_version": GUIDE_VERSION,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": {
            "file": source.name,
            "path": str(source.relative_to(REPO_ROOT)) if source.is_relative_to(REPO_ROOT) else str(source),
            "version": ssot.get("version"),
            "sha256": src_sha,
        },
        "counts": {
            "director_cases": len(dcs),
            "failure_cases": len(cfs),
            "asset_generation_failures": len(ag_cf),
            "knowledge_units_total": sum(len(v) for v in ssot["core_knowledge"].values()),
            "knowledge_units_with_content": stats_units["with_content"],
            "knowledge_units_pending_content": stats_units["pending_content"],
            "am_modules": len(ssot["directing_systems"]["modules"]),
            "model_router_families": len(ssot["model_router"]),
            "beat_families": len(t2["beat_families"]),
            "beat_routed_dc": len(routed),
            "technique_dc_unrouted": len(unrouted),
            "structured_triggers": len(structured),
        },
        "retrieval_channels": {
            "L1_failure_code_direct": "cases/failure_cases.json（按 CF id 直索；Phase 2.5 与 autoqc failure_type 建映射）",
            "L2_structured_trigger": "cases/beat_family_routing.json（T2 分叉）+ cases/cf_triggers.json（T3 预检）",
            "L3_semantic_fallback": "运行时由宿主 semantic_asset_index / 向量检索实现；索引字段定义见 orchestration.orchestrator_10_5.knowledge_dispatch_orchestration.l3_index_schema",
        },
        "content_policy": {
            "rule": "content_status=pending_content 的单元不进检索池（未登记不进检索池）；本目录产物均为派生文件，禁止手改，改 SSOT 后重跑 split_director_knowledge.py",
            "pending_units": pending_list,
            "priority_backfill": PRIORITY_BACKFILL,
        },
        "governance": {
            "note": "knowledge_units 新增单元均带 source_type/verification_status/trust_weight/depends_on；检索池使用方须按 trust_weight 排序、跳过 pending 之外仍需遵循时效检查（180 天/落后模型 2 版本降权 30%）",
        },
        "files": files,
    }
    dump_json(out / "manifest.json", manifest)
    return manifest


# ---------------------------------------------------------------- 校验
def verify(out: Path) -> bool:
    """回读全部产物做往返校验：计数、id 集合、beat 引用、depends_on 完整性。"""
    with open(out / "manifest.json", encoding="utf-8") as f:
        m = json.load(f)
    ok = True

    def fail(msg):
        nonlocal ok
        ok = False
        print(f"[FAIL] {msg}")

    # 逐文件哈希
    for fe in m["files"]:
        p = out / fe["path"]
        if not p.exists():
            fail(f"缺文件 {fe['path']}")
            continue
        if sha256_of(p.read_bytes()) != fe["sha256"]:
            fail(f"哈希不符 {fe['path']}（产物被手改？请重跑派生）")

    # 关键计数
    c = m["counts"]
    for k, exp in [("director_cases", 37), ("failure_cases", 102),
                   ("knowledge_units_total", EXPECTED["knowledge_units_total"]),
                   ("am_modules", 17), ("model_router_families", 7), ("beat_families", 7)]:
        if c[k] != exp:
            fail(f"manifest.{k}={c[k]} ≠ {exp}")

    # 案例文件往返
    dcj = json.loads((out / "cases" / "director_cases.json").read_text(encoding="utf-8"))
    cfj = json.loads((out / "cases" / "failure_cases.json").read_text(encoding="utf-8"))
    if len(dcj["cases"]) != 37 or len({x["id"] for x in dcj["cases"]}) != 37:
        fail("DC 往返计数/去重失败")
    if len(cfj["cases"]) != 102 or len({x["id"] for x in cfj["cases"]}) != 102:
        fail("CF 往返计数/去重失败")
    dc_ids = {x["id"] for x in dcj["cases"]}

    # beat 路由引用
    brt = json.loads((out / "cases" / "beat_family_routing.json").read_text(encoding="utf-8"))
    for fam in brt["beat_families"]:
        for dc_id in fam["dispatch"]:
            if dc_id not in dc_ids:
                fail(f"beat 族 {fam['family']} 引用不存在 DC {dc_id}")

    # 域文件：单元 id 全集 = 82，depends_on 完整
    all_ids = set()
    dom_dir = out / "domains"
    for p in sorted(dom_dir.glob("*.json")):
        dj = json.loads(p.read_text(encoding="utf-8"))
        all_ids.update(dj["units"].keys())
    if len(all_ids) != EXPECTED["knowledge_units_total"]:
        fail(f"域文件单元全集 {len(all_ids)} ≠ {EXPECTED['knowledge_units_total']}")
    for p in sorted(dom_dir.glob("*.json")):
        dj = json.loads(p.read_text(encoding="utf-8"))
        for uid, u in dj["units"].items():
            for dep in u.get("depends_on", []) or []:
                if dep not in all_ids:
                    fail(f"{uid} depends_on 引用不存在的 {dep}")

    print(f"[{'PASS' if ok else 'FAIL'}] 往返校验："
          f"DC=37 CF=102 单元={c['knowledge_units_total']} 触发器={c['structured_triggers']} "
          f"beat 路由 DC={c['beat_routed_dc']} 技法 DC={c['technique_dc_unrouted']} "
          f"内容覆盖 {c['knowledge_units_with_content']}/{c['knowledge_units_total']}（待回填 {c['knowledge_units_pending_content']}）")
    return ok


def main():
    ap = argparse.ArgumentParser(description="SSOT 知识拆分挂载（Phase 2.1）")
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--check-only", action="store_true", help="只校验已派生产物，不重新拆分")
    args = ap.parse_args()

    if args.check_only:
        sys.exit(0 if verify(args.out) else 1)

    ssot = load_and_validate(args.source)
    manifest = split(ssot, args.source, args.out)
    print(f"[OK] 已派生 {len(manifest['files'])} 个知识文件 → {args.out}")
    sys.exit(0 if verify(args.out) else 1)


if __name__ == "__main__":
    main()
