"""派生执行事实分阶段冻结合同测试（GUIDE R9/P0-4，R10/P1-2，验收 37/51）。

覆盖：
- 冻结推进（generated_script_facts → voice_resolution → scene_topology）
- append-only：已冻结子项拒绝覆盖
- 恢复阶段决策（最后冻结子项的下一阶段）
- 各子项 hash 独立校验（篡改暴露）
- 中间缺失视为未冻结（顺序推进不跳过）
"""

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")

from app.services.audiobook.derived_facts_service import (  # noqa: E402
    DERIVED_FACT_STAGES,
    freeze_derived_fact,
    resolve_resume_stage,
    summarize_frozen_stages,
    verify_derived_facts,
)


def test_stage_order_contract():
    """阶段顺序：generated_script_facts → voice_resolution → scene_topology"""
    assert DERIVED_FACT_STAGES == (
        "generated_script_facts",
        "voice_resolution",
        "scene_topology",
    )


def test_freeze_and_resume_after_script_facts():
    """仅剧本冻结 → 恢复从 voice_binding 继续（不重跑剧本生成）"""
    checkpoint = {}
    result = freeze_derived_fact(
        checkpoint,
        stage="generated_script_facts",
        fact_payload={"segments": [{"text": "第一段"}]},
    )
    assert result["frozen"] is True
    assert result["fact_hash"]
    assert checkpoint["generated_script_facts_hash"] == result["fact_hash"]
    assert resolve_resume_stage(checkpoint) == "voice_binding"


def test_freeze_and_resume_after_voice_resolution():
    """剧本 + voice 冻结 → 恢复从 scene_planning 继续"""
    checkpoint = {}
    freeze_derived_fact(checkpoint, stage="generated_script_facts", fact_payload={"s": 1})
    freeze_derived_fact(checkpoint, stage="voice_resolution", fact_payload={"voices": ["a"]})
    assert resolve_resume_stage(checkpoint) == "scene_planning"


def test_freeze_and_resume_after_scene_topology():
    """三子项全冻结 → 恢复从 scene_rendering 继续"""
    checkpoint = {}
    freeze_derived_fact(checkpoint, stage="generated_script_facts", fact_payload={"s": 1})
    freeze_derived_fact(checkpoint, stage="voice_resolution", fact_payload={"v": 1})
    freeze_derived_fact(checkpoint, stage="scene_topology", fact_payload={"t": 1})
    assert resolve_resume_stage(checkpoint) == "scene_rendering"


def test_freeze_is_append_only():
    """append-only：已冻结子项拒绝覆盖（验收 37 冻结不可覆盖）"""
    checkpoint = {}
    freeze_derived_fact(checkpoint, stage="generated_script_facts", fact_payload={"s": 1})
    original_hash = checkpoint["generated_script_facts_hash"]

    again = freeze_derived_fact(
        checkpoint, stage="generated_script_facts", fact_payload={"s": 999},
    )
    assert again["frozen"] is False
    assert again["reason"] == "already_frozen"
    # 原值未被覆盖
    assert checkpoint["generated_script_facts_hash"] == original_hash
    assert checkpoint["derived_execution_facts"]["generated_script_facts"]["value"] == {"s": 1}


def test_resume_stage_none_without_facts():
    """无冻结 → 恢复阶段 None（回退既有恢复行为）"""
    assert resolve_resume_stage(None) is None
    assert resolve_resume_stage({}) is None
    assert resolve_resume_stage({"derived_execution_facts": {}}) is None


def test_resume_stage_stops_at_gap():
    """中间缺失视为未冻结（顺序推进不跳过）：有 script 无 voice → 仍从 voice_binding"""
    checkpoint = {}
    freeze_derived_fact(checkpoint, stage="generated_script_facts", fact_payload={"s": 1})
    # 直接冻结 scene_topology（跳过 voice_resolution）→ 中间断裂
    checkpoint["derived_execution_facts"]["scene_topology"] = {
        "value": {"t": 1},
        "hash": "x" * 64,
    }
    assert resolve_resume_stage(checkpoint) == "voice_binding"


def test_verify_hashes_valid():
    """hash 校验通过（值未被篡改）"""
    checkpoint = {}
    freeze_derived_fact(checkpoint, stage="generated_script_facts", fact_payload={"s": 1})
    freeze_derived_fact(checkpoint, stage="voice_resolution", fact_payload={"v": 1})
    result = verify_derived_facts(checkpoint)
    assert result["valid"] is True
    assert result["checked"] == 2


def test_verify_hashes_detects_tamper():
    """hash 校验暴露篡改（验收 37：子项 hash 独立校验）"""
    checkpoint = {}
    freeze_derived_fact(checkpoint, stage="generated_script_facts", fact_payload={"s": 1})
    # 篡改值但不更新 hash
    checkpoint["derived_execution_facts"]["generated_script_facts"]["value"] = {"s": 999}
    result = verify_derived_facts(checkpoint)
    assert result["valid"] is False
    assert result["mismatch"] == ["generated_script_facts"]


def test_summarize_frozen_stages():
    """冻结摘要（审计用）"""
    checkpoint = {}
    freeze_derived_fact(checkpoint, stage="generated_script_facts", fact_payload={"s": 1})
    summary = summarize_frozen_stages(checkpoint)
    assert summary["frozen_stages"] == ["generated_script_facts"]
    assert summary["resume_stage"] == "voice_binding"
