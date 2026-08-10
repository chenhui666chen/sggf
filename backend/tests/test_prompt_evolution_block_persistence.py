# -*- coding: utf-8 -*-
"""保真条款块确定性追加守卫：反过度改写与防压缩两块随进化代数不丢失。

取证（2026-08-08，科幻批 c15c5ebf）：两块只写进 SAFE_INITIAL_PROMPT 初始
版，变体提示词由元优化器重写生成且无确定性追加保障——前半程（初始版与
第一代变体）段落级丢失硬失败归零，后半程（iter7）信息完整度<75 形态复发
2 例，时间线与条款随进化代数丢失完全吻合。修复：在 _enforce_fidelity_constraint
的确定性追加入口为两块建立与 VARIANT_* 约束同级的标记防重复追加机制。
"""
import pytest

from app.services.prompt_evolution import meta_optimizer as mo


class TestDeterministicBlockAppend:
    def test_bare_variant_gets_both_blocks(self):
        # 不含任何块的变体提示词，追加后两块齐全
        out = mo.MetaOptimizer._enforce_fidelity_constraint("你是文字编辑。请降低AI痕迹。")
        assert mo.ANTI_OVERREWRITE_MARKER in out
        assert mo.ANTI_COMPRESSION_MARKER in out

    def test_append_is_idempotent(self):
        # 已含块的提示词（如初始版衍生变体）不重复追加
        once = mo.MetaOptimizer._enforce_fidelity_constraint("你是文字编辑。请降低AI痕迹。")
        twice = mo.MetaOptimizer._enforce_fidelity_constraint(once)
        assert once == twice
        assert twice.count(mo.ANTI_OVERREWRITE_MARKER) == 1
        assert twice.count(mo.ANTI_COMPRESSION_MARKER) == 1

    def test_blocks_appended_after_variant_constraints(self):
        # 追加顺序：保真条款块落在三个 VARIANT_* 硬约束之后
        out = mo.MetaOptimizer._enforce_fidelity_constraint("你是文字编辑。请降低AI痕迹。")
        idx_strategy = out.index(mo.VARIANT_DETECTION_STRATEGY_MARKER)
        idx_over = out.index(mo.ANTI_OVERREWRITE_MARKER)
        idx_comp = out.index(mo.ANTI_COMPRESSION_MARKER)
        assert idx_strategy < idx_over < idx_comp

    def test_partial_block_presence_only_appends_missing(self):
        # 只含反过度改写块的提示词，仅补防压缩块
        partial = f"你是文字编辑。\n\n{mo.ANTI_OVERREWRITE_BLOCK}"
        out = mo.MetaOptimizer._enforce_fidelity_constraint(partial)
        assert out.count(mo.ANTI_OVERREWRITE_MARKER) == 1
        assert mo.ANTI_COMPRESSION_MARKER in out

    def test_appended_prompt_passes_safety(self):
        # 追加后的完整变体提示词必须通过安全校验
        out = mo.MetaOptimizer._enforce_fidelity_constraint("你是文字编辑。请降低AI痕迹。")
        assert mo.MetaOptimizer._validate_prompt_safety(out)

    def test_existing_variant_constraints_still_appended(self):
        # 原有三个 VARIANT_* 约束的追加行为不回归
        out = mo.MetaOptimizer._enforce_fidelity_constraint("你是文字编辑。请降低AI痕迹。")
        assert mo.VARIANT_FIDELITY_MARKER in out
        assert mo.VARIANT_LENGTH_MARKER in out
        assert mo.VARIANT_DETECTION_STRATEGY_MARKER in out


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
