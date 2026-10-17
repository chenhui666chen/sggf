"""经验池写入侧安全校验（TDD - RED 阶段）

问题背景（真实轮次 c9ccd818 取证，非推测）：
  P8 放开保真门后，真实版本仍被**安全门**正确拦下，原因是提示词含固定语境
  整句示例，如：
    - 词汇层简化：…同时保持书面语域（"风声不断，刮过乱石"vs"夜色浓稠如墨"）
    - 场景细节感官化：…减少模板化意象（"体内灵力按法门一遍遍运转"替代…）

  追查来源：这6 条带示例策略沉淀在 `data/prompt_evolution/experience_reports/`
  的 3 份经验报告里（effective_strategies / best_practices）。

  **消费侧有校验、写入侧没有**：
  - `build_seeded_strategies_block`（meta_optimizer.py:1029）逐条过
    `_prompt_safety_reason`，只能拦下游；
  - 但两处**写入点**直接把内容 append 进经验池，从不校验：
    · `_parse_response`（:2538/2549/2581/2602）—— 解析 LLM 输出时写入
    · `_load_experience`（:1671/1677/1683/1689）—— 加载历史报告时写入

  即：LLM 或历史报告里出现带示例的策略，就会永久污染经验池，
  每一轮都被重新注入新提示词 —— 正是 2026-08-07 批次 db1cdd3e 取证的
  「带毒提示词进入传承链」同一形态。

本文件先以失败测试锁定正确语义，实现前必须先 RED。
"""
import pytest


def _optimizer():
    from app.services.prompt_evolution.meta_optimizer import (
        ExperienceRecord, MetaOptimizer,
    )
    mo = MetaOptimizer.__new__(MetaOptimizer)
    mo.experience = ExperienceRecord()
    mo.previous_analyses = []
    return mo


class TestParseResponseRejectsUnsafe:
    """_parse_response 写入经验池前必须过安全校验。"""

    def test_unsafe_example_strategy_not_stored(self):
        """含固定语境整句示例的策略不得进入 effective_strategies。"""
        mo = _optimizer()
        resp = (
            "===EFFECTIVE_STRATEGIES===\n"
            '- 词汇层简化：保持书面语域（“风声不断，刮过乱石”vs“夜色浓稠如墨”）\n'
            "===EFFECTIVE_STRATEGIES_END===\n"
        )
        mo._parse_response(resp)
        assert mo.experience.effective_strategies == [], (
            f"带示例策略被写入经验池：{mo.experience.effective_strategies}"
        )

    def test_unsafe_authorization_strategy_not_stored(self):
        """授权增量类策略不得进入 effective_strategies。"""
        mo = _optimizer()
        resp = (
            "===EFFECTIVE_STRATEGIES===\n"
            "- 细节补全时可以被授权补全其必然伴随的物理现象\n"
            "===EFFECTIVE_STRATEGIES_END===\n"
        )
        mo._parse_response(resp)
        assert mo.experience.effective_strategies == [], (
            f"授权增量策略被写入：{mo.experience.effective_strategies}"
        )

    def test_unsafe_best_practice_not_stored(self):
        """best_practices 同样必须校验（它也进注入块）。"""
        mo = _optimizer()
        resp = (
            "===BEST_PRACTICES===\n"
            '- 保持语域统一，例如写成“夜色浓稠如墨”那样\n'            "===BEST_PRACTICES_END===\n"
        )
        mo._parse_response(resp)
        assert mo.experience.best_practices == [], (
            f"带示例最佳实践被写入：{mo.experience.best_practices}"
        )

    def test_unsafe_insight_not_stored(self):
        """strategic_insights 也走注入路径，须一并校验。"""
        mo = _optimizer()
        resp = (
            "===STRATEGIC_INSIGHT===\n"
            '- 可以采用“他忽然明白”这类转折替代铺垫\n'
            "===STRATEGIC_INSIGHT_END===\n"
        )
        mo._parse_response(resp)
        assert mo.experience.strategic_insights == [], (
            f"带示例洞察被写入：{mo.experience.strategic_insights}"
        )

    def test_safe_strategy_still_stored(self):
        """正向用例：安全策略必须正常入库，否则修复会毁掉经验池。"""
        mo = _optimizer()
        resp = (
            "===EFFECTIVE_STRATEGIES===\n"
            "- 用听觉、触觉细节替代视觉静态铺陈，减少模板化意象\n"
            "- 交替句首结构，打破连续相同句法骨架\n"
            "===EFFECTIVE_STRATEGIES_END===\n"
        )
        mo._parse_response(resp)
        assert len(mo.experience.effective_strategies) == 2, (
            f"安全策略应正常入库，实得 {mo.experience.effective_strategies}"
        )

    def test_mixed_batch_keeps_only_safe(self):
        """混合批次：只留安全项，且不影响解析流程。"""
        mo = _optimizer()
        resp = (
            "===EFFECTIVE_STRATEGIES===\n"
            "- 交替句首结构，打破连续相同句法骨架\n"
            '- 保持书面语域（“风声不断，刮过乱石”）\n'
            "- 清理空泛套话\n"
            "===EFFECTIVE_STRATEGIES_END===\n"
            '===IMPROVED_PROMPT===\n安全的提示词正文\n===IMPROVED_PROMPT_END===\n'
        )
        prompt, _ = mo._parse_response(resp)
        assert len(mo.experience.effective_strategies) == 2
        assert prompt == "安全的提示词正文", "被拒策略不得影响提示词解析"


class TestLoadExperienceRejectsUnsafe:
    """加载历史经验报告时同样必须校验（存量已污染，需在读取侧拦住）。"""

    def test_unsafe_report_entries_skipped(self):
        """存量报告里的带示例策略不得被载入内存经验池。

        取证形态：3 份历史报告里 6 条带示例策略，全是括号对照式。
        """
        from app.services.prompt_evolution.meta_optimizer import (
            ExperienceRecord, MetaOptimizer,
        )

        mo = MetaOptimizer.__new__(MetaOptimizer)
        mo.experience = ExperienceRecord()
        reports = [{
            "effective_strategies": [
                '- 词汇层简化：保持书面语域（“风声不断，刮过乱石”vs“夜色浓稠如墨”）',
                "- 交替句首结构，打破连续相同句法骨架",
            ],
            "best_practices": [
                '- 场景细节感官化（“体内灵力按法门一遍遍运转”替代“功法特有灵力波动”）',
            ],
            "ineffective_strategies": ["可以替换人物姓名以降低重复"],
            "forbidden_patterns": ["乱石铺陈（“风声不断，刮过乱石”这类铺陈）"],
            "strategic_insights": [
                '- 采用“夜色浓稠如墨”这类表达',
            ],
        }]

        mo.load_historical_experience(reports)

        assert mo.experience.effective_strategies == [
            "- 交替句首结构，打破连续相同句法骨架",
        ], f"存量带示例策略被载入：{mo.experience.effective_strategies}"
        assert mo.experience.best_practices == [], (
            f"存量带示例最佳实践被载入：{mo.experience.best_practices}"
        )
        assert mo.experience.strategic_insights == [], (
            f"存量带示例洞察被载入：{mo.experience.strategic_insights}"
        )


class TestRealPollutedEntriesAreRejected:
    """真实存量污染文本必须被拒（c9ccd818 取证的实际形态）。

    取证细节：这两条在真实运行中**确实被安全门拦下了整个提示词**，
    但逐条送检时全部放行 —— 因为现有的两条示例正则都要求特定上下文：
    · `_SENTENCE_EXAMPLE_PATTERN` 要求「…→/改为/替换为…」的替换对结构
    · `_INSTRUCTION_EXAMPLE_PATTERN` 要求「如/例如/示例」引导词
    而经验池里的策略多写成「…（"A"vs"B"）」「…（"A"替代"B"）」这种
    括号对照结构，两条正则都不匹配 —— 这就是写入侧能长期积累污染的原因。
    """

    def test_bracket_contrast_example_rejected(self):
        mo = _optimizer()
        polluted = (
            '- 词汇层简化：选用高精度具体动词替代抽象静态描写，'
            '同时保持书面语域（“风声不断，刮过乱石”vs“夜色浓稠如墨”）'
        )
        mo._parse_response(
            "===EFFECTIVE_STRATEGIES===\n" + polluted + "\n===EFFECTIVE_STRATEGIES_END===\n"
        )
        assert mo.experience.effective_strategies == [], (
            f"括号对照式示例未被拒：{mo.experience.effective_strategies}"
        )

    def test_bracket_replace_example_rejected(self):
        mo = _optimizer()
        polluted = (
            '- 场景细节感官化：用听觉、触觉细节替代视觉静态铺陈，'
            '减少模板化意象（“体内灵力按法门一遍遍运转”替代“功法特有灵力波动”）'
        )
        mo._parse_response(
            "===EFFECTIVE_STRATEGIES===\n" + polluted + "\n===EFFECTIVE_STRATEGIES_END===\n"
        )
        assert mo.experience.effective_strategies == [], (
            f"括号替换式示例未被拒：{mo.experience.effective_strategies}"
        )

    def test_guidance_word_example_rejected(self):
        """肯定语境的引导词示例须拒（现有正则已覆盖，防回退）。

        注意：否定语境（「不要写成如…」）是 2026-08-07 取证确立的**豁免**，
        因而不作为拒的用例 —— 那是负向禁用清单，本就该放行。
        """
        mo = _optimizer()
        polluted = '- 保持书面语域，采用如“夜色浓稠如墨”这类意象'
        mo._parse_response(
            "===EFFECTIVE_STRATEGIES===\n" + polluted + "\n===EFFECTIVE_STRATEGIES_END===\n"
        )
        assert mo.experience.effective_strategies == [], (
            f"肯定语境引导词示例未被拒：{mo.experience.effective_strategies}"
        )

    def test_ordinary_quote_words_not_over_blocked(self):
        """防误伤：短引号词（如「深邃」）与正常引用不得被拦。

        修复不能退化成「见引号就拦」——那是另一种失真。
        """
        mo = _optimizer()
        safe = [
            '- 保持语域的“书面感”，避免口语化词汇',
            '- 用“深邃”这类形容词时要谨慎',   # 2 字，低于示例下限 4
        ]
        for s in safe:
            mo._parse_response(
                f"===EFFECTIVE_STRATEGIES===\n{s}\n===EFFECTIVE_STRATEGIES_END===\n"
            )
        assert len(mo.experience.effective_strategies) == 2, (
            f"正常引号用法被误伤：{mo.experience.effective_strategies}"
        )


class TestSharedValidationEntry:
    """写入侧必须复用既有校验器，不得另写一套（否则再次漂移）。"""

    def test_single_validation_helper_exists(self):
        """应有一个统一的入库校验入口。"""
        from app.services.prompt_evolution.meta_optimizer import MetaOptimizer
        assert hasattr(MetaOptimizer, "_is_storable_strategy"), (
            "需统一入口 _is_storable_strategy，"
            "避免写入侧各处自行实现校验而与 _prompt_safety_reason 漂移"
        )

    def test_helper_rejects_empty_and_unsafe(self):
        from app.services.prompt_evolution.meta_optimizer import MetaOptimizer
        assert MetaOptimizer._is_storable_strategy("") is False
        assert MetaOptimizer._is_storable_strategy("   ") is False
        # 授权增量类（词表项，无需示例上下文即可判定）
        assert MetaOptimizer._is_storable_strategy(
            "- 可以被授权补全其必然伴随的物理现象"
        ) is False
        # 括号对照式示例（真实污染形态）
        assert MetaOptimizer._is_storable_strategy(
            '- 保持书面语域（“风声不断，刮过乱石”vs“夜色浓稠如墨”）'
        ) is False
        # 普通安全策略
        assert MetaOptimizer._is_storable_strategy(
            "- 交替句首结构，打破连续句法骨架"
        ) is True
        # 负向禁用清单应放行（2026-08-07 取证确立的豁免，防回归）
        assert MetaOptimizer._is_storable_strategy(
            '- 不得使用“然而/因为/因此”这类连接词'
        ) is True
