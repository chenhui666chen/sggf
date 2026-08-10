# -*- coding: utf-8 -*-
"""P1 写侧方向性强化守卫：质地转换验收标准 + 实测有效策略注入初始提示词。

取证（2026-08-07 批次 430ebd7c）：99 分高原六轮无版本达入选线。根因：
①SAFE_INITIAL_PROMPT 只有程序化指令（全文质地转换），没有"转换后的文本应
具备什么特征"的验收标准——改写模型无具体方向只能微调句长；实证低分质地
知识（句长参差/语域混搭/不完美感/对白动作推进等）只喂给了元优化器。
②经验库 effective/best_practice 策略只喂元优化器决策，未注入起点改写提示词，
每个批次从裸 SAFE_INITIAL_PROMPT 重新摸索。
"""
import pytest

from app.services.prompt_evolution import meta_optimizer as mo


class TestTextureTargetStandard:
    def test_safe_initial_prompt_contains_texture_target(self):
        # 验收标准块必须存在且给出可执行的质地特征方向
        assert mo.TEXTURE_TARGET_MARKER in mo.SAFE_INITIAL_PROMPT
        for feature in ("句长", "语域", "对白"):
            assert feature in mo.SAFE_INITIAL_PROMPT

    def test_texture_target_forbids_mechanical_template(self):
        # 验收标准是统计倾向而非机械模板，防止改写模型抄写套路
        assert "不得抄写为机械模板" in mo.TEXTURE_TARGET_BLOCK

    def test_safe_initial_prompt_still_passes_safety(self):
        # 新块自身及整体不得触发安全词表/示例模式误伤
        assert mo.MetaOptimizer._prompt_safety_reason(mo.TEXTURE_TARGET_BLOCK) is None
        assert mo.MetaOptimizer._validate_prompt_safety(mo.SAFE_INITIAL_PROMPT)


class TestExperienceSeeding:
    def _make_optimizer(self):
        return mo.MetaOptimizer()

    def test_seeding_block_filters_unsafe_and_dedupes(self):
        opt = self._make_optimizer()
        opt.experience.effective_strategies = [
            "交替句首结构，打破连续相同句法骨架",
            "交替句首结构，打破连续相同句法骨架",  # 重复项只注入一次
            "在原文信息基础上进行逻辑推演补充细节",  # 命中风险词表，禁止注入
            "清理不承载事实的空泛套话",
        ]
        block = opt.build_seeded_strategies_block()
        assert block is not None
        assert mo.EXPERIENCE_SEED_MARKER in block
        assert block.count("交替句首结构") == 1
        assert "逻辑推演" not in block
        assert "清理不承载事实的空泛套话" in block

    def test_seeding_includes_best_practices(self):
        opt = self._make_optimizer()
        opt.experience.effective_strategies = []
        opt.experience.best_practices = ["对白密集段落保持短段落推进节奏"]
        block = opt.build_seeded_strategies_block()
        assert block is not None and "短段落推进节奏" in block

    def test_seeding_returns_none_when_empty(self):
        opt = self._make_optimizer()
        opt.experience.effective_strategies = []
        opt.experience.best_practices = []
        assert opt.build_seeded_strategies_block() is None

    def test_seeding_caps_entry_count(self):
        opt = self._make_optimizer()
        opt.experience.effective_strategies = [f"有效策略方向第{i}条" for i in range(30)]
        block = opt.build_seeded_strategies_block()
        injected = sum(1 for i in range(30) if f"第{i}条" in block)
        assert injected == mo.MAX_SEEDED_STRATEGIES

    def test_initial_prompt_injects_seeded_strategies_before_self_check(self):
        # 注入块必须落在"输出前自检"之前，避免改写模型把它当正文输出
        opt = self._make_optimizer()
        opt.experience.effective_strategies = ["交替句首结构，打破连续相同句法骨架"]
        prompt = opt.get_initial_prompt(genre=None)
        assert mo.EXPERIENCE_SEED_MARKER in prompt
        assert prompt.index(mo.EXPERIENCE_SEED_MARKER) < prompt.index("输出前自检")
        assert prompt.endswith("只输出改写后的正文，不输出标题、说明、标签、分析或Markdown。\n")

    def test_initial_prompt_without_experience_unchanged_structure(self):
        opt = self._make_optimizer()
        opt.experience.effective_strategies = []
        opt.experience.best_practices = []
        prompt = opt.get_initial_prompt(genre=None)
        assert mo.EXPERIENCE_SEED_MARKER not in prompt
        assert mo.TEXTURE_TARGET_MARKER in prompt

    def test_seeded_prompt_passes_safety_validation(self):
        # 注入后的完整初始提示词必须整体通过安全校验
        opt = self._make_optimizer()
        opt.experience.effective_strategies = ["交替句首结构，打破连续相同句法骨架"]
        prompt = opt.get_initial_prompt(genre="科幻")
        assert mo.MetaOptimizer._validate_prompt_safety(prompt)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
