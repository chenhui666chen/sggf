# -*- coding: utf-8 -*-
"""Phase 2.8 端到端测试：verify_full_chain 跑全链 8 阶段 + 8 项验收清单。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
import scripts.verify_full_chain as V


def test_full_chain_all_pass():
    report = V.run_full_chain()
    # 链路阶段齐全（8 步）
    stages = [s["stage"] for s in report["chain"]]
    for stage in ["script", "contract", "state_engine", "am15",
                  "repair_router", "state_recalc", "synthesis", "reproducibility"]:
        assert stage in stages, f"链路缺阶段 {stage}"
    # 验收清单 8 项
    items = report["acceptance"]
    assert len(items) == 8
    assert report["all_pass"] is True, json.dumps(items, ensure_ascii=False)
    # 关键产物存在性
    assert report["chain"][0]["provenance"] == "read_only_text_source"  # provenance 登记四元组
    assert report["chain"][1]["r_pre_marked"] >= 1, "高价值 beat 必须有 R-pre 标记"
    assert report["chain"][3]["verdict"] in ("pass", "fail_state"), "AM-15 verdict 合法"
    assert report["chain"][4]["r_level"] in ("R2", "R3"), "修复路由 R 级正确"
    assert report["chain"][6]["jianying_draft"] is True, "剪映草稿生成"
    assert report["chain"][7]["status"] == "match", "输入哈希 pin 一致"


def test_full_chain_json_output():
    """--json 模式输出可解析 JSON。"""
    report = V.run_full_chain()
    # round-trip
    assert json.loads(json.dumps(report, ensure_ascii=False))["all_pass"] == report["all_pass"]
