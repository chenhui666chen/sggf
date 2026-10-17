# -*- coding: utf-8 -*-
"""ai_trace 降低接口的检测失败语义守卫。

## 问题（2026-10-08 记录为 P1/P2，至今未修）

`app/api/v1/ai_trace.py` 的`/reduce` 链路把「检测失败」伪装成
「检测成功但没有效果」：

1. 原文检测失败 → `original_score` 兜底为**魔数 50**（无任何依据说明）
2. 改写后检测失败 → `new_score` 兜底为 `original_score`
   ⇒ `improvement` 恒为 0，与「真的没效果」完全无法区分
3. 但响应仍 `success=True` **硬编码**
4. `new_result.get("label", "Unknown")` —— 朱雀检测的顶层返回
   **根本没有 label 键**（label 只存在于 `segment_labels` 的每一段里）
   ⇒ 该字段**恒为 "Unknown"**

## 为什么这条必须先修

P20 实测 72 次评估里 63 次「下降 0」。这63 次里有多少是真的没效果、
有多少是检测失败被兜底掉了 —— 在本守卫修好之前**根本分不清**。
也就是说，这个接口正在污染整个进化系统最关键的优化信号。

## 参照实现

`app/services/prompt_evolution/evaluator.py:600-606` 早已正确处理同一问题，
并留下了判据说明：
    「检测失败优先于成功：ratio=None 时该样本对适应度毫无信息量，
      若仍标success=True，会造成『质量门槛算它通过、ratio 统计却缺它』」
本守卫要求API 层与之一致。
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
# 与既有跨仓库守卫（test_asset_studio_sound_effect_vidu_removal）同口径：
# REPO_ROOT 是仓库根，源码路径需带 backend/ 前缀。
AI_TRACE_API = "backend/app/api/v1/ai_trace.py"
EVALUATOR = "backend/app/services/prompt_evolution/evaluator.py"


def _src(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


class TestDetectionFailureIsNotSilentlyDowngraded:
    def test_no_magic_fifty_fallback(self):
        """原文检测失败不得再兜底为魔数 50。"""
        src = _src(AI_TRACE_API)
        # 去掉注释行后再找，避免命中历史说明性文字
        code = "\n".join(
            line for line in src.splitlines() if not line.strip().startswith("#")
        )
        assert "else 50" not in code, (
            "原文检测失败仍兜底为魔数 50——该魔数无任何依据，"
            "会把检测失败伪装成『原文 50 分』"
        )

    def test_rewritten_detection_failure_marked_not_success(self):
        """改写后检测失败必须显式标记，不得静默套用 original_score。"""
        src = _src(AI_TRACE_API)
        code = "\n".join(
            line for line in src.splitlines() if not line.strip().startswith("#")
        )
        assert "else original_score" not in code, (
            "改写后检测失败仍兜底为 original_score ⇒ improvement 恒 0，"
            "与『真的没效果』无法区分"
        )

    def test_detection_failure_reuses_project_failure_kind(self):
        """必须复用项目已有的 `detect_failed` 受控词，不自造词汇。"""
        src = _src(AI_TRACE_API)
        assert "detect_failed" in src, (
            "应复用 evaluator/engine 已有的 detect_failed 受控词"
        )


class TestResponseContractRevealsDetectionFailure:
    def test_improvement_may_be_none(self):
        """检测失败时 improvement 应为 None（不可知），不是 0。"""
        from app.api.v1.ai_trace import ReduceResponse

        fields = ReduceResponse.model_fields
        for name in ("new_ai_score", "improvement", "original_ai_score"):
            assert fields[name].default is None, f"{name} 应允许 None"

    def test_label_field_is_populated_from_real_source(self):
        """label 不得再是恒为 'Unknown' 的死字段。

        朱雀检测顶层无 label 键（label 只在 segment_labels 段内），
        所以正确做法是删掉这个字段、或如实反映段级标注，
        而不是 `get('label', 'Unknown')` 兜底。
        """
        src = _src(AI_TRACE_API)
        code = "\n".join(
            line for line in src.splitlines() if not line.strip().startswith("#")
        )
        assert '"Unknown"' not in code and "'Unknown'" not in code, (
            "label 仍以 'Unknown' 兜底——朱雀顶层返回根本没有 label 键，"
            "该字段恒为 Unknown"
        )


class TestAlignsWithEvaluatorSemantics:
    def test_evaluator_already_handles_detect_failed(self):
        """参照实现本身必须仍然正确——若它被改坏，本守卫要报警。"""
        src = _src(EVALUATOR)
        assert 'failure_kind = "detect_failed"' in src, (
            "参照实现 evaluator.py 不再标记 detect_failed，"
            "需重新对齐两侧语义"
        )


class TestMagicNumberIsGone:
    def test_no_bare_fifty_in_detection_branch(self):
        """检测相关分支内不得出现裸 50。"""
        src = _src(AI_TRACE_API)
        code_lines = [
            line for line in src.splitlines()
            if not line.strip().startswith("#")
        ]
        offenders = [
            line.strip() for line in code_lines
            if "50" in line and "ai_score" in line and "original_score" in line
        ]
        assert not offenders, f"检测分支仍有裸 50：{offenders}"


@pytest.mark.parametrize("rel", [AI_TRACE_API])
def test_file_readable(rel):
    assert REPO_ROOT.joinpath(rel).exists(), rel


def test_inspect_reexports_route():
    """确保被测模块可正常导入（防止改动引入语法/导入错误）。"""
    import app.api.v1.ai_trace as mod

    assert inspect.isfunction(mod.reduce_ai_trace), "reduce_ai_trace 应为路由函数"