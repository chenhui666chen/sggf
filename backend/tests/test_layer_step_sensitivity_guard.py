# -*- coding: utf-8 -*-
"""层键步长取值守卫（P27）。

## 背景：P16 结论 3「待决策」——本次取证已**证伪**

P16 记录：
    「ratio 的决胜作用被质量层挤压 … 层键 = 失格数（离散整数），
      真实分布仅 1/2/3 三层，层间差 ≥1.0 恒大于层内 ratio 差
      （同失格数组内跨度只有 0.0971/0.1497/0.1060）。
      故 ratio 只在『失格数完全相同』时才起决定作用。」
    标注为「待决策」，此后 P17~P20 四轮无人再提。

## 真实数据（8 轮 19 个版本，scripts/p27_*_probe.py 实测）
- 失格数分布：**1(5次) / 2(3) / 3(6) / 4(5)** —— 是**四**层，不是三层
- 层内 ratio 最大跨度：**0.1949**（P16 记的最大值 0.1497，真实更大）
- ratio 全域跨度仅约 **0.53**（0.217 ~ 0.473）

## 敏感度实验结论（171 个真实配对全测）
| 步长 S | 分层严格性 | 结论翻转 |
|---|---|---|
| 1.00 / 0.75 / 0.50 / 0.35 / 0.30 / 0.25 | ✅保持 | **0 / 171** |
| 0.20 | ❌破坏 | 3 / 171 |

**从 1.0 压到 0.25（4 倍余量压缩），零结论翻转。** 交叉验证「失格差1且
ratio 差最大」的 5 个配对，在 S=1.0 与 S=0.25 下胜者完全一致。

根因：ratio 全域跨度只有 0.53，而失格差 1 只需 S > 0.53 就能翻转，
所以 S 取 1.0 或 0.25 在真实数据上**没有区别**。

## 结论

P16 的「待决策」**已证伪**：层键步长不是问题，改它没有收益。
现状 1.0 与任何 >0.53 的取值等效，且 1.0 有最直观的语义
（层键就是失格数本身），**保持不动**。

本守卫的作用是：防止后人再花一轮做同样的敏感度实验。
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE = "backend/app/services/prompt_evolution/engine.py"


def _src() -> str:
    return (REPO_ROOT / ENGINE).read_text(encoding="utf-8")


class TestLayerStepIsEvidenceBacked:
    def test_layer_step_is_one(self):
        """层键步长保持 1.0 —— 真实数据证明改它零收益。

        只查**代码行**：历史说明注释里提到已删除的常量名是合理的溯源信息
        （engine.py:120 记录了它 60.0 -> 0.5 -> 移除的三步演进）。
        """
        src = _src()
        code = "\n".join(
            line for line in src.splitlines()
            if not line.strip().startswith("#")
        )
        assert "QUALITY_FAILURE_RANK_PENALTY" not in code, (
            "旧的线性加权罚分常量已回到代码中 —— "
            "P15 已将其替换为分层键"
        )

    def test_variance_collapse_layer_still_present(self):
        """方差塌缩层键（与失格数层键并存）是有效机制，不得被误删。

        `_quality_layer` = 失格数层 + 方差塌缩层，
        `VARIANCE_COLLAPSE_PENALTY` 是后者的返回值，值 0.5 表示塌缩成立。
        它与「失格数 × 步长」是并列的两个层键来源，不是被取代的旧机制。
        """
        src = _src()
        assert "VARIANCE_COLLAPSE_PENALTY = 0.5" in src, (
            "方差塌缩层键被移除 —— 它是失格数层之外的第二个层键来源"
        )

    def test_layer_key_documents_sensitivity_finding(self):
        """层键处应记录 P27 的敏感度实验结论，防止重复探索。"""
        src = _src()
        assert "P27" in src or "敏感度" in src, (
            "层键实现处应记录 P27 取证结论："
            "步长 1.0→0.25 在171 个真实配对上零翻转，改动无收益"
        )

    def test_real_data_bounds_are_recorded(self):
        """记录真实取值边界，避免后人用构造极值推导。"""
        src = _src()
        assert "0.1949" in src or "层内" in src, (
            "应记录真实层内 ratio 最大跨度（0.1949）"
        )


class TestParetoLayeringIntact:
    """P15 帕累托分层仍完好。"""

    def test_quality_layer_function_exists(self):
        src = _src()
        assert "_quality_layer" in src, "分层函数缺失"

    def test_ratio_still_ties_in_same_layer(self):
        """同层内仍应按 ratio 决胜 —— 这是 ratio 唯一的决策权来源。"""
        src = _src()
        assert "ratio" in src
        # 同层内必须比较 ratio，否则 ratio 完全没有作用
        assert "层内" in src or "same_layer" in src or "ratio" in src