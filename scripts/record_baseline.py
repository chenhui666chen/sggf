# -*- coding: utf-8 -*-
"""Phase 0 基线记录脚本（降级模式）：小说链路 + 短剧链路各跑一遍并输出基线报告。

用法：
    python scripts/record_baseline.py              # 跑两条链路 + 输出报告
    python scripts/record_baseline.py --novel      # 仅小说
    python scripts/record_baseline.py --drama      # 仅短剧
    python scripts/record_baseline.py --json       # 仅 JSON 输出

基线记录（指导文档 Phase 0.3/0.4）：
  小说（0.3）：1 章——生成耗时 / 失败码 / 修订路由模式 / 字数
  短剧（0.4）：1 镜——分镜→帧 prompt→Contract 全链耗时 / 镜数 / 预检结果

真实生成 API 成本（painter 生图 / dreamweaver 生视频）不在降级范围——
脚本记录知识层与编排层的耗时与结构基线，作为 Phase 4.2 基准对比的输入。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
# backend 模块以 app.* 导入自身包
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def baseline_novel() -> dict:
    """Phase 0.3 · 小说链路基线：Story Graph + 剧本引擎（无 LLM 降级）。"""
    os.environ.setdefault("DREAMWEAVER_SCRIPT_ENABLE_LLM", "false")
    from backend.app.services.prompts.narrative_quality import extract_failure_codes, resolve_revision_mode
    from backend.app.services.prompts.novel_enhancements import build_review_payload

    source = (
        "夜班第三个小时，急诊室的走廊灯闪烁了一下。林晚抬头，一封匿名信滑了出来。\n"
        "她拆开信封，一张化验单滑落。签名是三年前那个人的字迹。\n"
        "林晚攥紧化验单，转身拨通了那个删掉过三次的号码。城市灯火一盏一盏熄灭。"
    )

    t0 = time.perf_counter()
    # 模拟评审输出（真实场景由 LLM 产出，降级用固定样例）
    sample_review = (
        "## 评审报告\n总体：尚可，钩子偏弱。\n"
        "HOOK_WEAK | MED | 开场前三百字悬念不足\n"
        "DIALOG_STIFF | LOW | 对白略有录音棚感\n"
    )
    codes = extract_failure_codes(sample_review)
    mode = resolve_revision_mode(codes)
    payload = build_review_payload(
        review_text=sample_review, chapter_number=1,
        revision_mode=mode[0] if isinstance(mode, tuple) else mode,
    )
    elapsed = round((time.perf_counter() - t0) * 1000, 1)

    return {
        "phase": "0.3_novel_baseline",
        "source_chars": len(source),
        "extraction_time_ms": elapsed,
        "failure_codes_detected": len(codes),
        "failure_codes": [c.get("code") for c in codes],
        "revision_mode": payload["revision_mode"],
        "has_heavy": payload["has_heavy"],
        "machine_readable": payload["machine_readable"],
        "sample_review_lines": sample_review.count("\n") + 1,
        "note": "降级模式：评审样例固定，真实基线需 LLM 在线（Phase 4.2 前置）",
    }


def baseline_drama() -> dict:
    """Phase 0.4 · 短剧链路基线：剧本引擎 → Contract 引擎 → T3 → R-pre 全链。"""
    os.environ.setdefault("DREAMWEAVER_SCRIPT_ENABLE_LLM", "false")
    from agents import scripter, storyboarder
    from pipeline.autoqc_pkg._routing import _route_from_failures
    from pipeline.autoqc_pkg._dataclasses import AutoQCFailure

    source = (
        "夜班第三个小时，急诊室的走廊灯闪烁了一下。林晚抬头，一封匿名信滑了出来。\n"
        "她拆开信封，一张化验单滑落。签名是三年前那个人的字迹。林晚崩溃落泪。\n"
        "林晚攥紧化验单，转身拨通了那个删掉过三次的号码。城市灯火一盏一盏熄灭。"
    )

    payload = {
        "run_id": "baseline-0-4",
        "chapter_ids": [1],
        "source_text": source,
        "quality_mode": "fast",
        "video_config": {"engine": "wan2.7-i2v"},
        "image_config": {"ratio": "9:16"},
    }
    ctx = SimpleNamespace(payload=payload)

    t0 = time.perf_counter()
    scripter.run(ctx)
    t1 = time.perf_counter()
    storyboarder.run(ctx)
    t2 = time.perf_counter()
    # 模拟 QC failure → 修复路由
    route = _route_from_failures(
        failures=[AutoQCFailure(
            failure_type="state_continuity_mismatch", severity="hard",
            shot_key="shot_001", message="gap",
            meta={"shot_keys": ["shot_001"]},
        )],
        payload=payload,
    )
    t3 = time.perf_counter()

    rk = route.patch["repair_knowledge"]
    return {
        "phase": "0.4_drama_baseline",
        "script_engine": {
            "time_ms": round((t1 - t0) * 1000, 1),
            "mode": payload["script_generation"]["mode"],
            "scenes": len(payload["script_document"]["scenes"]),
            "provenance": payload["script_document"]["source"]["provenance"][0]["reuse_mode"],
        },
        "contract_engine": {
            "time_ms": round((t2 - t1) * 1000, 1),
            "engine": payload["storyboard_generation"]["engine"],
            "shots": len(payload["shot_contracts"]),
            "total_duration_s": payload["storyboard_generation"]["total_duration_s"],
            "r_pre_marked": payload["storyboard_generation"]["contract_report"]["r_pre_eligible"],
            "precheck_issues": payload["storyboard_generation"]["precheck"]["issues_total"],
        },
        "repair_router": {
            "time_ms": round((t3 - t2) * 1000, 1),
            "r_level": rk["r_level"],
            "cf_hit": rk["cf_hits"][0]["cf_id"] if rk["cf_hits"] else None,
        },
        "full_chain_time_ms": round((t3 - t0) * 1000, 1),
        "note": "降级模式：知识层全链（无生成 API 调用）；真实基线需 LLM + 生图/生视频 API",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--novel", action="store_true")
    ap.add_argument("--drama", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    run_novel = args.novel or not (args.novel or args.drama)
    run_drama = args.drama or not (args.novel or args.drama)

    report: dict = {"recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "degraded"}

    if run_novel:
        report["novel"] = baseline_novel()
    if run_drama:
        report["drama"] = baseline_drama()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=" * 60)
        print("Phase 0 基线记录（降级模式）")
        print("=" * 60)
        for key in ("novel", "drama"):
            if key not in report:
                continue
            b = report[key]
            print(f"\n[{b['phase']}]")
            for k, v in b.items():
                if k not in ("phase", "note"):
                    print(f"  {k}: {v}")
            if b.get("note"):
                print(f"  ※ {b['note']}")

        # 写入基线文件
        out = REPO_ROOT / "ai_director_os" / "baseline_phase0.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n基线文件已写入：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
