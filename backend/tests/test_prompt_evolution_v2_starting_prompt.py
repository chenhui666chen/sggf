# -*- coding: utf-8 -*-
"""v2 整合版起点提示词守卫：SAFE_INITIAL_PROMPT 升级为实测验证的 v2 结构。

取证（2026-08-09）：v1 起点（SAFE_INITIAL_PROMPT）结构停留在初代五操作，
缺失两代进化实证的最优杠杆——心理呈现外部化（初代核心）、d15b07f4 的执行
流程/僵化修饰/万能动词/隐性时序杠杆（武侠 37.5 分新范式）、二代黑名单并集。
人工整合 v2 经安全校验与单臂实测（言情 4 样本，doubao-seed-evolving，均分
21.8，3/4 零分，保真全绿：fid>=95/fact=100/over_rw 全 low，取证
tmp/v2_test_report.txt），作为全题材新起点落盘。

守卫内容：
①v2 核心结构齐全（六法重构/心理外部化/执行流程/语言精炼/负面清单并集）
②系统三块（质地验收/反过度改写/防压缩）继续嵌入且顺序不变
③情绪意象操作边界与判侧对齐条款不丢失
④输出前自检锚点保留（经验注入锚位）
⑤整体通过安全校验
"""
import pytest

from app.services.prompt_evolution import meta_optimizer as mo


class TestV2CoreStructure:
    def test_contains_six_method_reconstruction(self):
        # v2 核心操作升级为六法重构
        # （2026-08-23 自然化纪律重构：心理呈现外部化->心理去解释化、
        #   静态描写动态化->氛围句限流，禁止把心理全动作化与强制动态化）
        prompt = mo.SAFE_INITIAL_PROMPT
        assert "六法重构" in prompt
        for method in ("句法异构化", "修饰关系动态化", "氛围句限流",
                       "逻辑连接内隐化", "去模板化收尾"):
            assert method in prompt, f"缺失方法：{method}"

    def test_contains_psychological_externalization(self):
        # v1 缺失的初代核心杠杆：情绪名词与心理解释动词不得保留
        # （自然化纪律重构后为心理去解释化：保留信息、压缩重复解释、
        #   不强转动作、不新增身体反应）
        prompt = mo.SAFE_INITIAL_PROMPT
        assert "心理去解释化" in prompt
        assert "禁止保留抽象情绪名词" in prompt

    def test_contains_execution_flow_checklist(self):
        # d15b07f4 新范式杠杆：五步工作程序
        prompt = mo.SAFE_INITIAL_PROMPT
        assert "# 执行流程" in prompt
        for step in ("通读理解", "连接词评估", "表达优化", "节奏微调", "最终核查"):
            assert step in prompt, f"缺失流程步骤：{step}"

    def test_contains_language_refinement(self):
        # d15b07f4 杠杆：僵化修饰与万能动词治理
        # （自然化纪律重构：主语自然切换->人名与名词自然重复，禁止为
        #   词汇丰富强行换指代/换主语）
        prompt = mo.SAFE_INITIAL_PROMPT
        assert "# 语言精炼" in prompt
        assert "缓缓、微微" in prompt
        assert "进行、做出、感到" in prompt
        assert "人名与名词自然重复" in prompt

    def test_negative_list_is_union_of_generations(self):
        # 负面清单为历代黑名单并集（含 d15b07f4 扩展词与二代套路意象句）
        prompt = mo.SAFE_INITIAL_PROMPT
        for word in ("肃杀", "幽蓝", "混沌", "古老回响"):
            assert word in prompt, f"缺失黑名单词：{word}"
        assert "光影斑驳" in prompt


class TestSystemBlocksPreserved:
    def test_texture_target_block_still_embedded(self):
        assert mo.TEXTURE_TARGET_MARKER in mo.SAFE_INITIAL_PROMPT

    def test_both_guard_blocks_still_embedded(self):
        assert mo.ANTI_OVERREWRITE_MARKER in mo.SAFE_INITIAL_PROMPT
        assert mo.ANTI_COMPRESSION_MARKER in mo.SAFE_INITIAL_PROMPT

    def test_block_order_unchanged(self):
        # 质地验收 → 反过度改写 → 防压缩 → 输出前自检
        prompt = mo.SAFE_INITIAL_PROMPT
        idx_texture = prompt.index(mo.TEXTURE_TARGET_MARKER)
        idx_over = prompt.index(mo.ANTI_OVERREWRITE_MARKER)
        idx_comp = prompt.index(mo.ANTI_COMPRESSION_MARKER)
        idx_check = prompt.index("# 输出前自检")
        assert idx_texture < idx_over < idx_comp < idx_check

    def test_imagery_boundary_clauses_preserved(self):
        # 判侧写侧对齐：同喻域等义替换合法，情绪方向不可变
        prompt = mo.SAFE_INITIAL_PROMPT
        assert "同喻域" in prompt
        assert "情绪方向" in prompt
        assert "不得换成情绪相反的意象" in prompt


class TestCompatibility:
    def test_self_check_anchor_ends_prompt(self):
        # 经验注入锚位与既有断言兼容：以自检最后一条收尾
        assert mo.SAFE_INITIAL_PROMPT.endswith(
            "只输出改写后的正文，不输出标题、说明、标签、分析或Markdown。\n"
        )

    def test_no_quote_characters(self):
        # 安全词表要求：全文无引号字符
        for char in "\"'\u201c\u201d\u2018\u2019\u300c\u300d":
            assert char not in mo.SAFE_INITIAL_PROMPT

    def test_still_passes_safety_validation(self):
        assert mo.MetaOptimizer._validate_prompt_safety(mo.SAFE_INITIAL_PROMPT)

    def test_get_initial_prompt_genre_addon_compatible(self):
        # 题材附加与安全校验链路不因起点替换而破坏
        opt = mo.MetaOptimizer()
        opt.experience.effective_strategies = []
        opt.experience.best_practices = []
        prompt = opt.get_initial_prompt(genre="言情")
        assert "# 言情题材约束" in prompt
        assert mo.MetaOptimizer._validate_prompt_safety(prompt)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
