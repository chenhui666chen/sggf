from app.services.prompt_evolution import meta_optimizer
from app.services.prompt_evolution.meta_optimizer import MetaOptimizer
from app.services.prompt_evolution.novel_rules import (
    PRESET_EFFECTIVE_STRATEGIES,
    PRESET_FORBIDDEN_PATTERNS,
)
from unittest.mock import AsyncMock

import pytest

from app.services.prompt_evolution.engine import PromptEvolutionEngine
from app.services.prompt_evolution.models import EvaluationResult, PromptVersion
from app.services.prompt_evolution.storage import EvolutionStorage
from app.services.prompt_evolution.test_samples import TestSample as EvolutionTestSample


def test_legacy_unsafe_prompt_sources_are_removed():
    assert not hasattr(meta_optimizer, "INITIAL_PROMPT")
    assert not hasattr(MetaOptimizer, "_get_genre_specific_addon")


def test_preset_experiences_stay_within_detector_features_and_fidelity_boundary():
    combined = "\n".join(PRESET_EFFECTIVE_STRATEGIES + PRESET_FORBIDDEN_PATTERNS)

    for legacy_rule in (
        "他感到xxx",
        "正能量结尾",
        "对话过于礼貌",
        "主角永远冷静",
        "感叹号",
        "仿佛...一般",
    ):
        assert legacy_rule not in combined

    for required_direction in (
        "句法骨架",
        "套话",
        "模板化连接词",
        "句子长度相近",
        "人物姓名",
        "信息点",
        "因果关系",
    ):
        assert required_direction in combined


def make_result(*, reduction=30, success=True, semantic=95, fact=95, complete=95, risk="low"):
    return EvaluationResult(
        sample_id="sample", original_text="原文", rewritten_text="改写",
        original_ai_score=99, rewritten_ai_score=99 - reduction,
        score_reduction=reduction, success=success,
        llm_review={
            "available": True,
            "semantic_fidelity": {"score": semantic},
            "fact_consistency": {"score": fact},
            "information_completeness": {"score": complete},
            "over_rewrite_risk": risk,
            "hard_fail": False,
        },
    )


def test_new_initial_prompt_targets_detector_patterns_without_content_distortion():
    # v2 整合版起点：断言锁定保真铁律与检测器杠杆的语义等价条款
    prompt = MetaOptimizer().get_initial_prompt("玄幻")

    assert "不得改变或增删人物姓名" in prompt
    assert "允许调整段落与句子的出场顺序" in prompt
    assert "全部信息点必须保留" in prompt
    # 自然化理念已放开：不再禁止向上连续人名重复，改为"允许自然重复、不刻意换指代"
    assert "禁止连续三句以上以相同人名" not in prompt
    assert "人名与名词自然重复" in prompt
    assert "不承载事实的机械连接词" in prompt
    assert "极致口语化" not in prompt
    assert "制造不完美" not in prompt
    assert "可以用现代口语" not in prompt
    assert "插入不相关联想" not in prompt


def test_only_quality_safe_reductions_can_be_learned_as_success():
    assert MetaOptimizer._is_eligible_success_sample(make_result()) is True
    assert MetaOptimizer._is_eligible_success_sample(make_result(risk="medium")) is False
    assert MetaOptimizer._is_eligible_success_sample(make_result(semantic=79)) is False
    assert MetaOptimizer._is_eligible_success_sample(make_result(fact=89)) is False
    assert MetaOptimizer._is_eligible_success_sample(make_result(complete=74)) is False


def test_unsafe_evolved_prompt_is_rejected():
    unsafe = "请破坏叙事逻辑，插入不相关联想，并采用极致口语化。"
    safe = "保持事实不变，减少模板化连接词，按语义自然调整句长。"

    assert MetaOptimizer._validate_prompt_safety(unsafe) is False
    assert MetaOptimizer._validate_prompt_safety(safe) is True


@pytest.mark.parametrize(
    "unsafe_prompt",
    [
        "把所有情绪都用身体反应替代",
        "把修仙者的话统一改成现代口语",
        "删除全场震惊类结尾",
        "给所有对话加入口头禅和语气词",
    ],
)
def test_legacy_strategy_synonyms_are_rejected(unsafe_prompt):
    assert MetaOptimizer._validate_prompt_safety(unsafe_prompt) is False


@pytest.mark.parametrize(
    "unsafe_strategy",
    [
        "刻意重复某个无关紧要的词语或句式，以模拟非理性的修辞停顿",
        "随机插入无意义短句来人为制造不完美",
        "故意制造语病和下意识强调",
    ],
)
def test_quality_damaging_strategy_is_rejected_before_variant_generation(unsafe_strategy):
    assert MetaOptimizer._validate_strategy_safety(unsafe_strategy) is False


def test_strategy_guard_allows_reducing_repetition():
    strategy = "减少连续使用相同句法骨架，打散重复句式但不改变语义"

    assert MetaOptimizer._validate_strategy_safety(strategy) is True


def test_meta_optimizer_prompt_does_not_encourage_quality_damage():
    for unsafe_instruction in (
        "人类写作有碎片化表达",
        "是否有碎片句、省略句",
        "有无语气词",
        "适度的\"废话\"",
        "人类用\"其实/说白了/反正/话说回来\"等口语过渡",
    ):
        assert unsafe_instruction not in meta_optimizer.META_OPTIMIZER_PROMPT


def test_exploration_instructions_stay_inside_allowed_dimensions():
    instructions = MetaOptimizer()._build_exploration_instruction(True, True)

    assert "寻找全新的优化方向" not in instructions
    assert "尝试与历史成功策略相反的方向" not in instructions
    assert "只允许" in instructions
    assert "不得主动增加无意义重复" in instructions


@pytest.mark.asyncio
async def test_unsafe_strategy_is_rejected_before_prompt_generation():
    optimizer = MetaOptimizer()
    optimizer._generate_random_exploration_strategies = AsyncMock(
        return_value=["刻意重复无关词语，以模拟非理性的停顿"]
    )
    optimizer._generate_variant_from_strategy = AsyncMock(return_value="不应生成")

    variants = await optimizer.generate_prompt_variants("安全基础提示词", 1)

    assert variants == []
    optimizer._generate_variant_from_strategy.assert_not_awaited()


@pytest.mark.asyncio
async def test_generated_strategy_is_deduplicated_against_history():
    optimizer = MetaOptimizer()
    optimizer.experience.effective_strategies = ["减少连续同构句式，打散重复句法骨架"]
    optimizer.llm_client = AsyncMock()
    optimizer.llm_client.chat = AsyncMock(
        return_value="降低连续相同句法骨架的重复程度\n清理不承载信息的空泛套话"
    )

    strategies = await optimizer._generate_random_exploration_strategies(2)

    assert strategies == ["清理不承载信息的空泛套话"]


@pytest.mark.asyncio
async def test_unsafe_generated_variant_is_filtered_before_evaluation():
    optimizer = MetaOptimizer()
    optimizer._generate_random_exploration_strategies = AsyncMock(return_value=["改变视角起点"])
    optimizer._generate_variant_from_strategy = AsyncMock(
        return_value="请改变叙事视角并插入不相关联想。"
    )

    variants = await optimizer.generate_prompt_variants("安全基础提示词", 1)

    assert variants == []


@pytest.mark.asyncio
async def test_rejected_optimizer_response_does_not_pollute_experience():
    optimizer = MetaOptimizer()
    optimizer.experience.effective_strategies = ["原有安全经验"]
    optimizer.llm_client = AsyncMock()
    optimizer.llm_client.chat = AsyncMock(return_value="""
===EFFECTIVE_STRATEGIES===
插入不相关联想
===EFFECTIVE_STRATEGIES_END===
===INEFFECTIVE_STRATEGIES===
无
===INEFFECTIVE_STRATEGIES_END===
===FORBIDDEN_PATTERNS===
无
===FORBIDDEN_PATTERNS_END===
===ANALYSIS===
应该通过改变叙事视角来降低AI率，这是一段足够长的分析。
===ANALYSIS_END===
===IMPROVED_PROMPT===
请改变叙事视角并插入不相关联想。
===IMPROVED_PROMPT_END===
""")

    prompt, _ = await optimizer.optimize_prompt(
        PromptVersion(prompt_text="原有安全提示词", evaluation_results=[]), 30, []
    )

    assert prompt == "原有安全提示词"
    assert optimizer.experience.effective_strategies == ["原有安全经验"]
    assert optimizer.previous_analyses == []


def test_ab_candidate_requires_every_planned_sample_to_pass_quality():
    passed = make_result()
    failed = make_result(success=False)
    failed.error = "语义保真度低于80"

    assert PromptEvolutionEngine._is_complete_quality_evaluation([passed, passed], 2) is True
    assert PromptEvolutionEngine._is_complete_quality_evaluation([passed, failed], 2) is False
    assert PromptEvolutionEngine._is_complete_quality_evaluation([passed], 2) is False


def test_ab_rank_penalizes_minority_hard_failures_but_disqualifies_majority():
    passed = make_result()  # 语义评审全部95/低过度改写 → 人感成本 = 2.0
    failed = make_result(success=False)
    failed.error = "事实一致性低于90"

    # 全部通过：排名分取成功样本"人感成本"中位数（2.0），而非 TMS 均值 30.0 或中位数 69
    assert PromptEvolutionEngine._ab_rank_score(30.0, [passed] * 4, 4) == 2.0
    # 少数（1/4）硬失败：保留资格但按比例加罚分（中位数 2.0 + 1/4*60）
    minority_score = PromptEvolutionEngine._ab_rank_score(
        30.0, [passed, passed, passed, failed], 4
    )
    assert 2.0 < minority_score <= 100.0
    assert minority_score == pytest.approx(17.0)
    # 多数（3/4）硬失败：取消资格
    assert PromptEvolutionEngine._ab_rank_score(
        30.0, [passed, failed, failed, failed], 4
    ) == 101.0
    # 样本缺失按失败计：缺 3 个即多数失败
    assert PromptEvolutionEngine._ab_rank_score(30.0, [passed], 4) == 101.0


def test_quality_failure_summary_collects_hard_fail_reasons():
    failed_a = make_result(success=False)
    failed_a.error = "事实一致性低于90"
    failed_b = make_result(success=False)
    failed_b.error = None

    summary = PromptEvolutionEngine._summarize_quality_failures(
        [make_result(), failed_a, failed_b]
    )

    assert "事实一致性低于90" in summary
    assert "未知原因" in summary


@pytest.mark.asyncio
async def test_variant_prompt_always_carries_fact_fidelity_constraint():
    optimizer = MetaOptimizer()
    optimizer._generate_random_exploration_strategies = AsyncMock(
        return_value=["交替句首结构，打破连续相同句法骨架"]
    )
    optimizer._generate_variant_from_strategy = AsyncMock(
        return_value="请交替使用主语开头与状语前置，避免连续平行句式。"
    )

    variants = await optimizer.generate_prompt_variants("安全基础提示词", 1)

    assert len(variants) == 1
    variant_prompt, _ = variants[0]
    assert "【事实保真硬性约束】" in variant_prompt
    assert "不得改变人物姓名" in variant_prompt


@pytest.mark.asyncio
async def test_variant_prompt_does_not_duplicate_existing_fidelity_constraint():
    optimizer = MetaOptimizer()
    optimizer._generate_random_exploration_strategies = AsyncMock(
        return_value=["清理空泛套话"]
    )
    base_variant = "请删除套话。\n\n【事实保真硬性约束】不得改变人物姓名等事实。"
    optimizer._generate_variant_from_strategy = AsyncMock(return_value=base_variant)

    variants = await optimizer.generate_prompt_variants("安全基础提示词", 1)

    variant_prompt, _ = variants[0]
    assert variant_prompt.count("【事实保真硬性约束】") == 1


def test_initial_prompt_embeds_measured_detection_levers():
    # 朱雀实测三优先级：禁升华收尾 > 句式口语化 > 删套路句型
    prompt = MetaOptimizer().get_initial_prompt("玄幻")

    assert "升华" in prompt
    assert "口语化" in prompt
    assert "套路" in prompt
    # 保持既有语域保护边界：不是无差别口语化
    assert "极致口语化" not in prompt
    assert "可以用现代口语" not in prompt


def test_detection_strategy_constraint_covers_three_priorities():
    constraint = meta_optimizer.VARIANT_DETECTION_STRATEGY_CONSTRAINT

    assert meta_optimizer.VARIANT_DETECTION_STRATEGY_MARKER in constraint
    assert "升华" in constraint
    assert "口语化" in constraint
    assert "套路" in constraint


@pytest.mark.asyncio
async def test_variant_prompt_carries_detection_strategy_constraint_once():
    optimizer = MetaOptimizer()
    optimizer._generate_random_exploration_strategies = AsyncMock(
        return_value=["交替句首结构，打破连续相同句法骨架"]
    )
    # 变体自带一份策略约束，不得重复追加
    base_variant = (
        "请交替句首结构。\n\n"
        f"{meta_optimizer.VARIANT_DETECTION_STRATEGY_MARKER}已有的约束。"
    )
    optimizer._generate_variant_from_strategy = AsyncMock(return_value=base_variant)

    variants = await optimizer.generate_prompt_variants("安全基础提示词", 1)

    assert len(variants) == 1
    variant_prompt, _ = variants[0]
    assert variant_prompt.count(meta_optimizer.VARIANT_DETECTION_STRATEGY_MARKER) == 1
    assert "【事实保真硬性约束】" in variant_prompt


def test_meta_optimizer_prompt_states_measured_levers():
    # 元优化器的检测原理说明需同步实测结论，避免进化方向偏离已验证杠杆
    assert "升华" in meta_optimizer.META_OPTIMIZER_PROMPT


@pytest.mark.asyncio
async def test_auto_detected_genre_reselects_a_genre_consistent_sample_set(tmp_path):
    engine = PromptEvolutionEngine(storage=EvolutionStorage(str(tmp_path)))
    engine.sample_manager = AsyncMock()
    mixed = [
        EvolutionTestSample("f1", "修炼灵力法宝" * 30, "玄幻"),
        EvolutionTestSample("f2", "宗门境界妖兽" * 30, "玄幻"),
        EvolutionTestSample("u1", "地铁公司总监" * 30, "都市"),
    ]
    fantasy_only = [
        EvolutionTestSample("f1", "修炼灵力法宝" * 30, "玄幻"),
        EvolutionTestSample("f2", "宗门境界妖兽" * 30, "玄幻"),
        EvolutionTestSample("f3", "丹田宗门功法" * 30, "玄幻"),
    ]
    engine.sample_manager.prepare_evaluation_samples = AsyncMock(
        side_effect=[mixed, fantasy_only]
    )

    selected = await engine._prepare_samples_for_evolution()

    assert engine.genre == "玄幻"
    assert {sample.genre for sample in selected} == {"玄幻"}
    assert [call.kwargs["genre"] for call in engine.sample_manager.prepare_evaluation_samples.await_args_list] == [None, "玄幻"]
