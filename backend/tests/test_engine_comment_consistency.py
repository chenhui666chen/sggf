# -*- coding: utf-8 -*-
"""注释与代码一致性守卫（P24）。

## 问题

`engine.py:1799` 的注释写「语义保真<90样本的版本不得入选最佳列表」，
但同文件 `engine.py:1906` 实际用的是：

    MetaOptimizer.QUALITY_GATES["semantic_fidelity"]   # = 80.0

P7（2026-10-16）已把该门从 90 降到 80（依据真实轮次取证），
但这条注释从未同步 —— 于是它成了**假事实**：
后来者（或未来的我）读到它会以为门槛是 90，从而做出错误判断。

## 为什么值得单独修

项目记忆 MEMORY.md 自己立过一条纪律：

    「注释里的**前提断言**必须验证 —— "定点指令已含事实条款"
      这个前提错了很久」

以及 P17 的教训「观测到的『恒为某值』≠ 公式保证」。

这条注释恰好是**该纪律的反例**：它写的是一个具体数字，
而那个数字早已被改掉、注释却留着。留着比没有更糟 ——
没有注释时人会去读代码，有错误注释时人会相信注释。

## 守卫口径

要求注释若提到保真门槛，必须与 `QUALITY_GATES` 的真实取值一致。
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE = "backend/app/services/prompt_evolution/engine.py"


def _src(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


class TestFidelityGateCommentMatchesCode:
    def test_comment_does_not_claim_ninety(self):
        """注释不得再声称门槛是 90（实际是 80）。"""
        src = _src(ENGINE)
        comment_lines = [
            line for line in src.splitlines()
            if line.strip().startswith("#")
        ]
        offenders = [
            line.strip() for line in comment_lines
            if "保真<90" in line or "保真 < 90" in line
            or "保真<80" in line or "保真 < 80" in line
        ]
        assert not offenders, (
            f"注释仍写死保真门槛数字，与代码不符：{offenders}"
        )

    def test_code_actually_uses_quality_gates(self):
        """代码侧仍须引用 QUALITY_GATES —— 若它被改坏，本守卫要报警。"""
        src = _src(ENGINE)
        assert 'QUALITY_GATES["semantic_fidelity"]' in src, (
            "engine.py 应引用 MetaOptimizer.QUALITY_GATES"
        )

    def test_gate_value_is_eighty(self):
        """当前真实取值是 80（2026-10-16 P7 取证下调的结果）。"""
        from app.services.prompt_evolution.meta_optimizer import MetaOptimizer

        assert MetaOptimizer.QUALITY_GATES["semantic_fidelity"] == 80.0

    def test_no_hardcoded_number_in_gate_comparison(self):
        """准入判断处不得再有裸数字比较。"""
        src = _src(ENGINE)
        code = "\n".join(
            line for line in src.splitlines()
            if not line.strip().startswith("#")
        )
        assert 'QUALITY_GATES["semantic_fidelity"]' in code, (
            "准入判断应引用 QUALITY_GATES"
        )


class TestSimilarStaleCommentsAbsent:
    """同类问题全仓扫一遍：注释里写死的门槛数字。

    注意排除「提示词模板文本」—— 里面的「事实一致性<90」是给 LLM 的
    约束语句（要求它把事实一致性打到 90 以上），不是对代码行为的描述，
    属正当用法，不能一并判死。
    """

    def test_no_other_stale_gate_numbers_in_comments(self):
        import re

        targets = (
            "backend/app/services/ai_trace_competition.py",
            "backend/app/services/prompt_evolution/meta_optimizer.py",
            "backend/app/services/prompt_evolution/semantic_judge.py",
        )
        # 只匹配「门槛描述句」：关键词后紧跟比较符与数字
        pattern = re.compile(
            r"(保真|事实一致|信息完整|置信度)(?:门槛|样本|版本|准入)?"
            r"[，,、\s]*[<>]=?\s*(\d{2,3})\b"
        )
        offenders = []
        for rel in targets:
            for line in _src(rel).splitlines():
                stripped = line.strip()
                if not stripped.startswith("#"):
                    continue
                # 提示词模板里的约束语不是代码注释
                if "反过度改写" in stripped or "最小干预" in stripped:
                    continue
                for label, num in pattern.findall(stripped):
                    offenders.append(f"{rel}: {label}->{num} | {stripped[:70]}")
        assert not offenders, "注释写死了门槛数字：\n" + "\n".join(offenders)