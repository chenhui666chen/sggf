# -*- coding: utf-8 -*-
"""Phase 3 测试：调用审计 / 知识治理 / Learning Loop / 有声书增强。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from backend.app.services.audiobook_enhancements import (
    VoiceDNA,
    audiobook_am15_eval,
    build_voice_dna_from_character,
    inject_sound_design,
)
from backend.app.services.knowledge_hub import (
    AuditEntry,
    AuditTrail,
    KnowledgeGovernance,
    LearningLoop,
)


# ---------------------------------------------------------------- 3.1 调用审计
def test_audit_trail_quad(tmp_path: Path):
    trail = AuditTrail(db_path=tmp_path / "audit.jsonl")
    e = trail.record_knowledge_usage(
        run_id="run-p3", stage="REVIEW", trigger_type="T1",
        problem="state_continuity_mismatch", knowledge_id="CF-030",
        delete_test="pass", model="qwen-plus", cost=0.05, shot_id="shot_001",
    )
    assert e.applied_knowledge_id == "CF-030"
    assert e.delete_test_result == "pass"
    # 回放视图
    trail.record_knowledge_usage(
        run_id="run-p3", stage="STORYBOARD", trigger_type="T2",
        problem="beat 分叉", knowledge_id="DC-035", model="qwen-plus", cost=0.02,
    )
    view = trail.replay_view("run-p3")
    assert view["total_entries"] == 2
    assert set(view["stages"]) == {"REVIEW", "STORYBOARD"}
    assert view["total_cost"] == 0.07
    assert "qwen-plus" in view["models_used"]


def test_audit_empty_replay(tmp_path: Path):
    trail = AuditTrail(db_path=tmp_path / "audit.jsonl")
    view = trail.replay_view("nonexistent")
    assert view["total_entries"] == 0


# ---------------------------------------------------------------- 3.2 知识治理
def test_governance_status_ladder(tmp_path: Path):
    """pending→verified→deprecated 单向流转；verified→pending 拒绝。"""
    # 构造临时知识文件
    kd = tmp_path / "domains"
    kd.mkdir(parents=True)
    (kd / "production.json").write_text(json.dumps({
        "units": {
            "test_unit": {
                "domain": "production", "title": "测试", "principle": "p", "content": [],
                "source_type": "external_paper", "verification_status": "pending",
                "trust_weight": 0.7, "added": "2026-10-07",
            }
        }
    }, ensure_ascii=False), encoding="utf-8")
    gov = KnowledgeGovernance(knowledge_dir=tmp_path)

    r1 = gov.promote_status("test_unit", new_status="verified")
    assert r1["new_status"] == "verified"
    assert r1["trust_weight"] == 1.0

    r2 = gov.promote_status("test_unit", new_status="pending")
    assert "不能降级" in r2.get("note", "")

    r3 = gov.promote_status("test_unit", new_status="deprecated")
    assert r3["new_status"] == "deprecated"
    assert r3["trust_weight"] == 0.3


def test_governance_stale_check():
    gov = KnowledgeGovernance()
    fresh = gov.stale_check("u1", added_date="2026-09-01")
    assert fresh["stale"] is False
    assert fresh["retrieval_priority_factor"] == 1.0
    stale = gov.stale_check("u1", added_date="2025-01-01")
    assert stale["stale"] is True
    assert stale["retrieval_priority_factor"] == 0.7


def test_governance_l3_sort_key():
    gov = KnowledgeGovernance()
    high = gov.l3_sort_key({"trust_weight": 1.0, "source_type": "benchmark", "added": "2026-09-01"})
    low = gov.l3_sort_key({"trust_weight": 0.6, "source_type": "external_opensource", "added": "2025-01-01"})
    assert high > low, "benchmark+新鲜 应排在外部+过期 之前"


# ---------------------------------------------------------------- 3.3 Learning Loop
def test_repair_success_rate():
    loop = LearningLoop()
    loop.record_repair(cf_id="CF-030", repair_model_used="拆ActionUnit", success=True)
    loop.record_repair(cf_id="CF-030", repair_model_used="拆ActionUnit", success=True)
    loop.record_repair(cf_id="CF-030", repair_model_used="拆ActionUnit", success=False)
    stats = loop.repair_success_rate("CF-030")
    assert stats["total"] == 3
    assert stats["success_rate"] == 0.667


def test_b_to_a_upgrade():
    loop = LearningLoop()
    ok = loop.check_b_to_a_upgrade("story_graph_ingestion", calls=5, delete_tests_passed=5)
    assert ok["eligible_for_upgrade"] is True
    not_enough = loop.check_b_to_a_upgrade("hybrid_review_protocol", calls=3, delete_tests_passed=3)
    assert not_enough["eligible_for_upgrade"] is False


def test_mab_ucb_and_preload():
    loop = LearningLoop()
    for _ in range(10):
        loop.mab_record("冷峻悬疑", reward=0.8)
    for _ in range(10):
        loop.mab_record("温暖治愈", reward=0.6)
    best = loop.mab_best_arm()
    assert best["best_arm"] == "冷峻悬疑"
    preload = loop.mab_preload_config()
    assert preload["status"] == "converged"
    assert preload["preload"] is True


def test_persona_signals():
    loop = LearningLoop()
    loop.record_persona_signal(persona_id="p1", hook_retention=8, emotion_curve="前紧后松", drop_point="第二场")
    loop.record_persona_signal(persona_id="p2", hook_retention=6, emotion_curve="平淡", drop_point="")
    s = loop.audience_signal_summary()
    assert s["avg_hook_retention"] == 7.0
    assert len(s["drop_points"]) == 1


def test_rlvr_readiness():
    loop = LearningLoop()
    r = loop.rlvr_readiness()
    assert r["ready"] is False
    assert r["gap"] == 500
    for _ in range(500):
        loop.record_repair(cf_id="CF-001", repair_model_used="x", success=True)
    r2 = loop.rlvr_readiness()
    assert r2["ready"] is True


# ---------------------------------------------------------------- 3.4 有声书增强
def test_voice_dna_from_emotion():
    dna = build_voice_dna_from_character(character_id="c1", name="林晚", emotion="sad")
    assert dna.voice_style == "deep"
    assert dna.speech_rate == "slow"
    assert dna.pitch_range == "low"
    happy = build_voice_dna_from_character(character_id="c2", name="小陈", emotion="happy")
    assert happy.voice_style == "bright"


def test_audiobook_am15_variant():
    cards = [build_voice_dna_from_character(character_id="c1", name="林晚", emotion="sad")]
    result = audiobook_am15_eval(
        audio_paths=[], voice_dna_cards=cards, asr_transcript="林晚说了一句话",
    )
    assert result["schema"] == "am15_audiobook_variant/1.0"
    assert result["perception"]["asr_transcript_chars"] == 7
    assert result["evaluation"]["voice_consistency"] == "checked"
    assert result["verdict"] == "pass"


def test_inject_sound_design():
    config = inject_sound_design(
        storyboard=[{"shot_id": "s1", "motion_desc": "金属碰撞", "desc": "x"}],
        emotion="sad", scene_type="室内",
    )
    assert config["bgm"]["genre"] == "melancholic"
    assert config["bgm"]["mix_style"] == "dry_close"
    assert config["sfx_count"] == 1
    assert "声音设计公式" in config["formula"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
