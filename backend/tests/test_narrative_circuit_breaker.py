"""P4：可暂停自动推进与熔断（narrative_circuit_breaker）单元测试"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.narrative_circuit_breaker import (
    CIRCUIT_BREAKER_KEY,
    DIGEST_FAILURE_THRESHOLD,
    GATE_BLOCKING_THRESHOLD,
    confirm_and_resume,
    get_breaker_state,
    get_pause_info,
    is_paused,
    record_generation_signal,
)


def test_default_not_paused():
    meta = {}
    assert not is_paused(meta)
    state = get_breaker_state(meta)
    assert state["paused"] is False
    assert state["streaks"]["gate_blocking"] == 0
    assert meta[CIRCUIT_BREAKER_KEY] is state


def test_gate_blocking_two_consecutive_pauses():
    meta = {}
    record_generation_signal(meta, chapter_number=10, event="gate_blocking")
    assert not is_paused(meta)
    record_generation_signal(meta, chapter_number=11, event="gate_blocking")
    assert is_paused(meta)
    info = get_pause_info(meta)
    assert info["paused"] is True
    assert info["paused_at_chapter"] == 11
    assert "闸门" in info["reason"]
    assert GATE_BLOCKING_THRESHOLD == 2


def test_generation_success_resets_gate_streak():
    meta = {}
    record_generation_signal(meta, chapter_number=10, event="gate_blocking")
    record_generation_signal(meta, chapter_number=11, event="generation_success")
    record_generation_signal(meta, chapter_number=12, event="gate_blocking")
    # 连续计数已被成功章节打断，不应熔断
    assert not is_paused(meta)
    assert get_breaker_state(meta)["streaks"]["gate_blocking"] == 1


def test_digest_failure_three_consecutive_pauses():
    meta = {}
    for chapter in (5, 6):
        record_generation_signal(meta, chapter_number=chapter, event="digest_failure")
        assert not is_paused(meta)
    record_generation_signal(meta, chapter_number=7, event="digest_failure")
    assert is_paused(meta)
    assert "提取失败" in get_pause_info(meta)["reason"]
    assert DIGEST_FAILURE_THRESHOLD == 3


def test_digest_success_resets_digest_streak():
    meta = {}
    record_generation_signal(meta, chapter_number=5, event="digest_failure")
    record_generation_signal(meta, chapter_number=6, event="digest_failure")
    record_generation_signal(meta, chapter_number=7, event="digest_success")
    record_generation_signal(meta, chapter_number=8, event="digest_failure")
    record_generation_signal(meta, chapter_number=9, event="digest_failure")
    assert not is_paused(meta)


def test_ledger_corrupt_pauses_immediately():
    meta = {}
    record_generation_signal(meta, chapter_number=3, event="ledger_corrupt", detail="entries 非列表")
    assert is_paused(meta)
    assert "账本" in get_pause_info(meta)["reason"]


def test_empty_output_pauses_immediately():
    meta = {}
    record_generation_signal(meta, chapter_number=3, event="empty_output")
    assert is_paused(meta)


def test_confirm_and_resume_clears_pause():
    meta = {}
    record_generation_signal(meta, chapter_number=10, event="gate_blocking")
    record_generation_signal(meta, chapter_number=11, event="gate_blocking")
    assert is_paused(meta)
    state = confirm_and_resume(meta, chapter_number=11)
    assert state["paused"] is False
    assert state["streaks"]["gate_blocking"] == 0
    assert state["streaks"]["digest_failure"] == 0
    assert not is_paused(meta)
    # history 保留且记录了人工恢复事件
    events = [item["event"] for item in state["history"]]
    assert "manual_resume" in events


def test_malformed_review_meta_never_raises():
    # None / 非法状态结构均不抛异常
    assert not is_paused(None)
    assert get_pause_info(None)["paused"] is False
    meta = {CIRCUIT_BREAKER_KEY: "corrupted"}
    record_generation_signal(meta, chapter_number=1, event="gate_blocking")
    assert not is_paused(meta) or is_paused(meta)  # 不抛异常即可
    meta2 = {CIRCUIT_BREAKER_KEY: {"paused": True, "streaks": "bad", "history": "bad"}}
    assert is_paused(meta2)
    state = get_breaker_state(meta2)
    assert isinstance(state["streaks"], dict)
    assert isinstance(state["history"], list)
    confirm_and_resume(meta2)
    assert not is_paused(meta2)


def test_history_capped():
    meta = {}
    for chapter in range(1, 31):
        record_generation_signal(meta, chapter_number=chapter, event="digest_success")
    history = get_breaker_state(meta)["history"]
    assert len(history) <= 20
    # 保留最近的记录
    assert history[-1]["chapter"] == 30


def test_schema_has_resume_field():
    """P4 恢复入口：GenerateNextChapterRequest 必须提供 resume_after_confirmation 字段。"""
    from app.api.v1.workflow.schemas import GenerateNextChapterRequest

    request = GenerateNextChapterRequest()
    assert request.resume_after_confirmation is False
    request2 = GenerateNextChapterRequest(resume_after_confirmation=True)
    assert request2.resume_after_confirmation is True


def test_endpoint_wiring_exists():
    """静态回归：endpoint 必须接入熔断检查与恢复分支。"""
    routes_path = (
        ROOT_DIR / "app" / "api" / "v1" / "workflow" / "routes_chapter.py"
    )
    source = routes_path.read_text(encoding="utf-8")
    assert "is_paused(breaker_meta)" in source
    assert "resume_after_confirmation" in source
    assert "confirm_and_resume(breaker_meta" in source
    assert 'event="gate_blocking"' in source
    assert 'event="generation_success"' in source
    assert 'event="ledger_corrupt"' in source
    assert 'event="empty_output"' in source


def test_empty_output_wired_at_content_validation_point():
    routes_path = (
        ROOT_DIR / "app" / "api" / "v1" / "workflow" / "routes_chapter.py"
    )
    source = routes_path.read_text(encoding="utf-8")
    detection_index = source.find("detect_invalid_chapter_output(chapter_draft, previous_full_text)")
    assert detection_index > 0
    signal_index = source.find('event="empty_output"', detection_index)
    assert signal_index > detection_index
    raise_index = source.find("raise RuntimeError", signal_index)
    quota_index = source.find("chapter_content_produced = True", signal_index)
    assert 0 < raise_index < quota_index
    assert "previous_full_text" in source


def test_detect_invalid_chapter_output_empty_and_placeholder():
    from app.services.narrative_circuit_breaker import detect_invalid_chapter_output
    assert detect_invalid_chapter_output("") == "正文输出为空"
    placeholder = "第3章内容\n\n（此处为生成的章节内容）"
    assert "占位" in detect_invalid_chapter_output(placeholder)


def test_detect_invalid_chapter_output_repeat_and_unique():
    from app.services.narrative_circuit_breaker import detect_invalid_chapter_output
    previous = "林烬推开密室的门，烛火晃了一下。" * 40
    assert "重复" in (detect_invalid_chapter_output(previous, previous) or "")
    unique = "沈砚把证物收回袖中，决定先不惊动任何人。" * 40
    assert detect_invalid_chapter_output(unique, previous) is None
    assert detect_invalid_chapter_output("短文本", previous) is None
