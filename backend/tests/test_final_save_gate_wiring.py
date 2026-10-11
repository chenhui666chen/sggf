# -*- coding: utf-8 -*-
"""第十三轮外部审查 P1-1/P1-2/P2-1/P2-2 的接线契约与 final_validation 观测单测。

审查证实四处真实 worker 控制流缺陷：①截断重试成功条件用"长度+句末"局部判断，重试稿>200且句末
但重复/占位时 retry_status=succeeded 与随后 verdict 的 output_status=rejected 矛盾；②最终保存前
无统一验收，clean_final_output 清空的终稿 / 同步 optimize_chapter fallback 的未验收稿可绕过 F.6
落库（第五条路径）；③结构重生成执行了重试但 retry_* 仍是默认 not_needed；④正文重试失败置
fallback_to_previous_output=True，但正文主生成无本章上一版可回退（实际是熔断终止），语义误导。

用户选定"纯函数 + 源码接线断言"策略：resolve_final_version 回退优先级全场景见
test_resolve_final_version.py；本文件锁定 routes_chapter 接线契约 + final_validation 观测快照。
"""
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.api.v1.workflow.routes_chapter import _record_final_validation_observation
from app.services.context_observability import collector

ROUTES_SRC = (
    ROOT_DIR / "app" / "api" / "v1" / "workflow" / "routes_chapter.py"
).read_text(encoding="utf-8")


def test_content_retry_success_uses_unified_verdict():
    # P1-1：正文截断重试成功条件统一为 verdict.accepted，旧的"长度+句末"局部判断已移除
    assert "_content_retry_verdict = evaluate_chapter_output(retry_draft, previous_full_text)" in ROUTES_SRC
    assert "if _content_retry_verdict.accepted:" in ROUTES_SRC
    assert "not _is_likely_truncated_chapter(retry_draft) and len(retry_draft) > 200" not in ROUTES_SRC


def test_revision_retry_success_uses_unified_verdict():
    # P1-1：改稿截断重试成功条件统一为 verdict.accepted
    assert "_rev_retry_verdict = evaluate_chapter_output(retry_revised, previous_full_text)" in ROUTES_SRC
    assert "if _rev_retry_verdict.accepted:" in ROUTES_SRC
    assert "not _is_likely_truncated_chapter(retry_revised) and len(retry_revised) > 200" not in ROUTES_SRC


def test_content_retry_failure_does_not_claim_fallback_to_previous():
    # P2-2：正文主生成无本章上一版可回退，重试失败保持 content_fallback_to_prev=False（终止语义，
    # 由 output_status=rejected + 熔断 raise 表达），不再误报"回退上一版"。改稿路径用 rev_fallback_to_prev。
    assert "content_fallback_to_prev = True" not in ROUTES_SRC


def test_final_save_gate_before_persistence():
    # P1-2：最终保存前统一验收 gate，且位于 project_settings.final_version 与 chapters.content 落库之前
    gate_idx = ROUTES_SRC.find("resolve_final_version(")
    assert gate_idx > 0
    settings_idx = ROUTES_SRC.find("final_version=final_version,", gate_idx)
    assert settings_idx > gate_idx  # project_settings 保存在 gate 之后
    chapter_idx = ROUTES_SRC.find("_create_generated_chapter(", gate_idx)
    assert chapter_idx > gate_idx  # chapters 保存在 gate 之后
    # 三者全无效（source=="none"）时终止保存，不落库
    assert '_final_resolution.source == "none"' in ROUTES_SRC
    # 回退时同步配套评审（best→best_review / draft→review_report）
    assert "final_review = best_review if _final_resolution.source" in ROUTES_SRC


def test_best_version_initialized_before_iteration_try():
    # P1-2 gate 在 try 之后引用 best_version/best_review；迭代早期异常（选模型/广播失败）会在
    # try 内赋值前跳到 except 回退，若无预初始化则保存前 gate 触发 NameError。锁定 8 空格缩进
    # （函数体级、try 外）的兜底初始化，且位于 gate 之前。
    assert re.search(r"^        best_version = chapter_draft$", ROUTES_SRC, re.MULTILINE)
    assert re.search(r"^        best_review = review_report$", ROUTES_SRC, re.MULTILINE)
    init_idx = ROUTES_SRC.find("        best_version = chapter_draft")
    gate_idx = ROUTES_SRC.find("resolve_final_version(")
    assert 0 < init_idx < gate_idx


def test_regeneration_wired_through_boundary_helper():
    # P2-1（第十三轮）+ 第十四轮 P1/P2：结构重生成的 retry_*/fallback 语义已下沉到模块级 helper
    # _regenerate_and_review_on_structural_failure（异常边界拆分，行为契约见
    # test_regeneration_review_boundary.py）。本测试锁定 worker 接线：重生成观测经 record_regen
    # 回调注入且绑定 "regeneration" kind，worker 通过 helper 编排而非内联 try/except。
    assert "_regenerate_and_review_on_structural_failure(" in ROUTES_SRC
    assert "record_regen=_record_regen" in ROUTES_SRC
    # _record_regen 闭包绑定 regeneration kind，model/prompt/calls 由闭包补齐、语义字段由 helper 传入
    record_regen_idx = ROUTES_SRC.find("def _record_regen(**kwargs)")
    assert record_regen_idx > 0
    record_block = ROUTES_SRC[record_regen_idx:record_regen_idx + 400]
    assert '_record_downstream_observation(' in record_block
    assert '"regeneration"' in record_block
    # helper 异常分支补 fallback_to_previous_output=True（P2：重生成失败保留分段初稿）
    helper_idx = ROUTES_SRC.find("async def _regenerate_and_review_on_structural_failure(")
    assert helper_idx > 0
    helper_src = ROUTES_SRC[helper_idx:helper_idx + 3000]
    assert "fallback_to_previous_output=True" in helper_src


def test_final_validation_snapshot_records_rejected_and_fallback():
    # final_validation 观测：保存前拦截无效终稿并回退，无 LLM 调用（calls=0）、prompt -1 哨兵
    project_id = 990050
    _record_final_validation_observation(
        project_id=project_id,
        next_chapter_number=7,
        task_id="task-final-gate-1",
        output_status="rejected",
        output_reject_reason="EmptyOutput",
        fallback_to_previous_output=True,
        context_payload={"resolution_source": "best", "final_version_chars": 0},
    )
    snaps = collector.list_for_project(project_id, limit=10, request_kind="final_validation")
    assert len(snaps) == 1
    s = snaps[0]
    assert s.request_kind == "final_validation"
    assert s.request_status == "ok"  # gate 逻辑正常执行（终止由 output_status=rejected + raise 表达）
    assert s.output_status == "rejected"
    assert s.output_reject_reason == "EmptyOutput"
    assert s.fallback_to_previous_output is True  # 已回退到 best/draft 有效版本
    assert s.online_llm_calls == 0  # 保存前校验无 LLM 调用
    assert s.prompt_request_bytes == -1  # 无 prompt，-1 哨兵
    assert s.context_payload_bytes > 0  # payload 含 resolution_source 等诊断


def test_final_validation_abort_snapshot_fallback_false():
    # 三者全无效终止：fallback_to_previous_output=False（未回退，终止保存 + 熔断）
    project_id = 990051
    _record_final_validation_observation(
        project_id=project_id,
        next_chapter_number=8,
        task_id="task-final-gate-2",
        output_status="rejected",
        output_reject_reason="TruncatedOutput",
        fallback_to_previous_output=False,
        context_payload={"resolution_source": "none"},
    )
    snaps = collector.list_for_project(project_id, limit=10, request_kind="final_validation")
    assert len(snaps) == 1
    assert snaps[0].fallback_to_previous_output is False
    assert snaps[0].output_reject_reason == "TruncatedOutput"
