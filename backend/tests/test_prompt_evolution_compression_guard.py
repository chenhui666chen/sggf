# -*- coding: utf-8 -*-
"""防压缩丢失守卫：治理质地转换力度上升后的压缩式细节丢失硬失败。

取证（2026-08-08，四题材批次）：反过度改写块生效后硬失败形态从系统性
过度改写转为轻度压缩细节丢失——漏"最后/再次"类限定词、"量子泡沫"被
简化为"量子"、"切伦科夫辐射"被改为"蓝的辐射"、删升华段致信息完整度
低于 75，科幻批因此连续两轮零产出。本块与反过度改写块正交：前者禁
过度改造，本块禁信息丢失。条款均转写为无引号抽象规则以通过安全守卫。

扩展取证（2026-08-08，科幻批 c15c5ebf）：防压缩块治好了段落级丢失
（信息完整度硬失败归零），但词级事实保真仍漏——天文名词被泛化替换
（小行星连续两批被改为大行星）、物体位置姿态与状态被篡改（悬浮改为
贴壁、舒展收缩改为缠成一团，同一样本两轮复发）。补充两条词级条款。

二次扩展取证（2026-08-08，言情批 81586519 + 玄幻批 f221ff6c）：人物
动作姿态被替换跨题材复发——言情里手里捧改为膝盖上搁（同一样本两轮
连犯）、悬在门锁上方改为搭在门锁上、回过头改为没回头；玄幻里盘膝坐
改为缩着贴岩壁。现有条款只覆盖物体的位置姿态，人物动作姿态与接触
状态未入事实层。将物体状态条款扩展为物体+人物双覆盖。
"""
import pytest

from app.services.prompt_evolution import meta_optimizer as mo


class TestCompressionGuardBlock:
    def test_block_present_in_safe_initial_prompt(self):
        assert mo.ANTI_COMPRESSION_MARKER in mo.SAFE_INITIAL_PROMPT

    def test_preserves_proper_nouns_and_terms_verbatim(self):
        # 专名、科技术语必须逐字保留，不得简化为日常说法
        assert "逐字保留" in mo.ANTI_COMPRESSION_BLOCK
        assert "专有名词" in mo.ANTI_COMPRESSION_BLOCK
        assert "科技术语" in mo.ANTI_COMPRESSION_BLOCK

    def test_preserves_semantic_qualifiers(self):
        # 次数、顺序、终结、重复类限定词不得丢失（取证：漏"最后/再次"）
        assert "限定词" in mo.ANTI_COMPRESSION_BLOCK

    def test_forbids_whole_paragraph_deletion(self):
        # 不得整段删除结尾或情绪承载段落（取证：删升华段致完整度<75）
        assert "整段删除" in mo.ANTI_COMPRESSION_BLOCK

    def test_information_completeness_priority(self):
        # 精简表达与保留信息冲突时优先保留信息
        assert "信息完整度" in mo.ANTI_COMPRESSION_BLOCK

    def test_preserves_domain_terms_and_parameters(self):
        # 专业领域名词与数值参数逐字保留（取证：小行星→大行星、氧气浓度参数被替换）
        assert "专业领域" in mo.ANTI_COMPRESSION_BLOCK
        assert "数值参数" in mo.ANTI_COMPRESSION_BLOCK

    def test_preserves_object_state_as_fact(self):
        # 物体位置、姿态、状态、数量属性属事实层（取证：悬浮→贴壁、舒展收缩→缠成一团）
        assert "姿态" in mo.ANTI_COMPRESSION_BLOCK
        assert "运动状态" in mo.ANTI_COMPRESSION_BLOCK

    def test_preserves_character_action_as_fact(self):
        # 人物动作与接触状态属事实层（取证：手里捧→膝盖上搁、悬在→搭上、回过头→没回头）
        assert "人物" in mo.ANTI_COMPRESSION_BLOCK
        assert "接触状态" in mo.ANTI_COMPRESSION_BLOCK

    def test_character_clause_covers_posture_and_action(self):
        # 人物条款须同时覆盖动作与姿态两类形态（取证：盘膝坐→缩着贴岩壁属姿态替换）
        assert "动作" in mo.ANTI_COMPRESSION_BLOCK

    def test_block_has_no_quoted_examples(self):
        # 带引号示例会被安全守卫拦截（批次 430ebd7c 取证），必须无引号
        for ch in ('"', "'", "\u201c", "\u201d", "\u2018", "\u2019", "\u300c", "\u300d"):
            assert ch not in mo.ANTI_COMPRESSION_BLOCK

    def test_block_and_full_prompt_pass_safety(self):
        assert mo.MetaOptimizer._prompt_safety_reason(mo.ANTI_COMPRESSION_BLOCK) is None
        assert mo.MetaOptimizer._validate_prompt_safety(mo.SAFE_INITIAL_PROMPT)

    def test_block_position_between_anti_overrewrite_and_self_check(self):
        # 落在反过度改写块之后、输出前自检之前
        idx_over = mo.SAFE_INITIAL_PROMPT.index(mo.ANTI_OVERREWRITE_MARKER)
        idx_block = mo.SAFE_INITIAL_PROMPT.index(mo.ANTI_COMPRESSION_MARKER)
        idx_check = mo.SAFE_INITIAL_PROMPT.index("# 输出前自检")
        assert idx_over < idx_block < idx_check


class TestInitialPromptIntegration:
    def test_initial_prompt_keeps_block_with_seeding(self):
        opt = mo.MetaOptimizer()
        opt.experience.effective_strategies = ["交替句首结构，打破连续相同句法骨架"]
        prompt = opt.get_initial_prompt(genre="科幻")
        assert mo.ANTI_COMPRESSION_MARKER in prompt
        assert prompt.index(mo.ANTI_COMPRESSION_MARKER) < prompt.index("输出前自检")
        assert mo.MetaOptimizer._validate_prompt_safety(prompt)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
