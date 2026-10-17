# -*- coding: utf-8 -*-
"""HIGH_SCORE_RETRY 死代码处置守卫（P26）。

## 背景

`evaluator.py` 保留了一段「高方差模型高分重试」逻辑
（`HIGH_SCORE_RETRY_THRESHOLD/MAX/MODEL_PREFIXES` + 约 20 行循环）。
`HIGH_SCORE_RETRY_MAX = 0` 使 `if` 条件编译期可判定恒假，从未执行。

原注释说：
    「HIGH_SCORE_RETRY_MAX 已置 0，保留代码结构备后续接入朱雀等
      正向检测器时重新启用。」

## 为什么本次是「删除」而不是「启用」

前提已经变了：朱雀**早已接入**（`self.ai_detector` 就是朱雀检测器），
所以注释设想的「重新启用条件」早已满足。但启用它会引入**不可靠依据**：

重试循环的择优判据是 `if alt_score < rewritten_score`，
用的是 `ai_score`。而 P20 实测（75 次真实检测）证明：

- `ai_score = ratio_confidence × 100`，把「确定AI(1)」与「疑似AI(2)」**合并计数**
- LLM 改写的典型效果正是 **确定AI → 疑似AI**，这一步 ratio_confidence 不变
- 实测 `ratio_confidence >= 0.999` 为 **0/75** —— 它既不恒 100，也不灵敏

即：用 `ai_score` 在两个改写版本间择优，会把「AI→疑似」这种真实进步
判为「没变化」，从而**选出错误的更优版本**。

正确做法是删除这段死代码；若将来确需多版本择优，
判据必须换成有分辨力的 `ai_ratio`（确定AI占比），而非 `ai_score`。

## 守卫口径

要求这段死代码不再存在于evaluator，且常量一并移除 ——
保留「注释说备将来启用」的结构性死代码，只会让后人误以为它是有效路径。
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVALUATOR = "backend/app/services/prompt_evolution/evaluator.py"


def _src() -> str:
    return (REPO_ROOT / EVALUATOR).read_text(encoding="utf-8")


class TestHighScoreRetryCodeRemoved:
    def test_constants_gone(self):
        src = _src()
        for name in ("HIGH_SCORE_RETRY_THRESHOLD",
                     "HIGH_SCORE_RETRY_MAX",
                     "HIGH_SCORE_RETRY_MODEL_PREFIXES"):
            assert name not in src, (
                f"{name} 仍存在——这是 TMS 时代的遗留，"
                "启用前提（正向检测器）虽已满足，但判据 ai_score 无分辨力，"
                "正确处置是删除而非启用"
            )

    def test_retry_loop_gone(self):
        """重试循环已删除。

        只查代码区域：注释里会写「已删除高方差模型高分重试」这类说明，
        那正是我们要保留的溯源信息，不能一并判死。
        """
        code = "\n".join(
            line for line in _src().splitlines()
            if not line.strip().startswith("#")
        )
        assert "高方差模型高分重试" not in code, "重试循环仍存在"
        assert "🎲" not in code, "重试日志标记仍存在"
        # 溯源注释应保留（记录为何删除），但不得包含可执行的旧逻辑
        assert "P26" in _src(), "应保留说明删除原因的溯源注释"

    def test_no_retry_branch_in_ast(self):
        """AST 层面确认：不含引用已删常量的分支（避免残留死代码）。"""
        tree = ast.parse(_src())
        consts = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                consts.add(node.id)
        assert not any(
            name.startswith("HIGH_SCORE_RETRY") for name in consts
        ), "AST 中仍引用 HIGH_SCORE_RETRY_* —— 死代码未删干净"


class TestRatioIsTheReliableSignal:
    """若将来恢复多版本择优，判据必须是有分辨力的 ratio。"""

    def test_evaluator_exposes_ai_ratio(self):
        from app.services.prompt_evolution.evaluator import PromptEvaluator

        src = _src()
        assert "rewritten_ai_ratio" in src, (
            "evaluator 仍应记录 rewritten_ai_ratio —— "
            "它是比 ai_score 更有分辨力的择优依据"
        )

    def test_zhuque_is_the_active_detector(self):
        """确认前提：朱雀已接入（死代码注释设想的启用条件）。"""
        src = _src()
        assert "zhuque_ai_detect_service" in src or "ai_detector" in src