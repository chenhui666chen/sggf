"""
同步轻量判定器测试（设计文档 §5.3 / §14 第 5 步）

覆盖：硬门槛（空/过短、长度收缩、数字丢失、禁用词/模板残留/提示泄漏、段落破坏、
AI 检测未过、内容安全未过、显式人名表实体丢失）、排序分、不对称 margin 择优。
纯函数，无 IO / 无外部 API。
"""
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for path in (BACKEND_ROOT, PROJECT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.prompt_evolution.light_judge import (
    HardFailResult,
    LightJudgeResult,
    check_hard_fail,
    compute_ranking_score,
    count_paragraphs,
    extract_number_tokens,
    find_missing_numbers,
    has_prompt_leak,
    has_template_residue,
    judge_pair,
)

_ORIGINAL = "少年在第三年春天推开木门，看见院中那棵老树。他握紧手中的两枚铜钱，转身走向远方。"
_GOOD_REWRITE = "第三年的春天，少年推开木门，望见院里那棵老树。他攥着手里的两枚铜钱，转身朝远方走去。"


# ============ 数字抽取与比对 ============

def test_extract_number_tokens():
    tokens = extract_number_tokens("他有3个苹果和15元钱")
    assert "3" in tokens
    assert "15" in tokens


def test_find_missing_numbers_none():
    assert find_missing_numbers("有3个苹果5元", "还剩3个苹果共5元") == []


def test_find_missing_numbers_detects_loss():
    missing = find_missing_numbers("第三年有2枚铜钱共15元", "有2枚铜钱")
    assert "15" in missing


# ============ 模板残留 / 提示泄漏 ============

def test_has_template_residue_markdown():
    assert has_template_residue("**加粗标题**\n- 列表项一\n- 列表项二") is True


def test_has_template_residue_clean():
    assert has_template_residue("少年推开木门，望见院里那棵老树。") is False


def test_has_prompt_leak_hits():
    assert has_prompt_leak("以下是改写后的文本：少年推开木门") is True


def test_has_prompt_leak_clean():
    assert has_prompt_leak("少年推开木门，望见院里那棵老树。") is False


# ============ 段落计数 ============

def test_count_paragraphs():
    assert count_paragraphs("第一段。\n\n第二段。\n第三段。") == 3


# ============ 硬门槛 ============

def _hard_kwargs(**overrides):
    data = dict(
        text=_GOOD_REWRITE,
        reference_text=_ORIGINAL,
        ai_score=20,
        ai_threshold=50,
        content_safety_passed=True,
        detector_available=True,
        required_entities=(),
    )
    data.update(overrides)
    return data


def test_hard_fail_all_pass():
    result = check_hard_fail(**_hard_kwargs())
    assert isinstance(result, HardFailResult)
    assert result.failed is False
    assert result.reasons == []


def test_hard_fail_empty_text():
    result = check_hard_fail(**_hard_kwargs(text="  "))
    assert result.failed is True
    assert any("空" in r or "过短" in r for r in result.reasons)


def test_hard_fail_too_short():
    result = check_hard_fail(**_hard_kwargs(text="太短了"))
    assert result.failed is True


def test_hard_fail_length_shrink():
    long_ref = (
        "少年在第三年的春天推开那扇斑驳的木门，看见院子中央那棵苍老的大树静静伫立在那里。"
        "他握紧手中的两枚铜钱，深吸一口气，转身缓缓走向远方那条蜿蜒曲折的山路。"
    )
    # 改写文 ≥30 字（越过过短门槛），但仍不足参照的一半 → 触发收缩
    result = check_hard_fail(**_hard_kwargs(text="第三年的春天少年推开那扇木门看见院子中央的老树握紧铜钱转身走向远方", reference_text=long_ref))
    assert result.failed is True
    assert any("收缩" in r for r in result.reasons)


def test_hard_fail_number_loss():
    # 改写文丢失原文数字 15
    rewrite = "第三年的春天，少年推开木门，望见院里那棵老树。他攥着手里的铜钱，转身朝远方走去了呀。"
    result = check_hard_fail(**_hard_kwargs(text=rewrite, reference_text="第三年有两枚铜钱共15元钱在少年手里紧紧攥着舍不得花掉一分一毫呢真的"))
    assert result.failed is True
    assert any("数字" in r for r in result.reasons)


def test_hard_fail_ai_detection_not_passed():
    result = check_hard_fail(**_hard_kwargs(ai_score=80, ai_threshold=50))
    assert result.failed is True
    assert any("AI" in r for r in result.reasons)


def test_hard_fail_content_safety():
    result = check_hard_fail(**_hard_kwargs(content_safety_passed=False))
    assert result.failed is True
    assert any("安全" in r for r in result.reasons)


def test_hard_fail_template_residue():
    result = check_hard_fail(**_hard_kwargs(text="**改写**\n- 第三年的春天少年推开了木门望见那棵老树两枚铜钱转身走向远方去了呀真好"))
    assert result.failed is True
    assert any("模板" in r for r in result.reasons)


def test_hard_fail_prompt_leak():
    result = check_hard_fail(**_hard_kwargs(text="以下是改写后的文本：第三年春天少年推开木门望见老树握紧两枚铜钱转身走向远方去了真的好"))
    assert result.failed is True
    assert any("泄漏" in r or "泄露" in r for r in result.reasons)


def test_hard_fail_required_entity_missing():
    result = check_hard_fail(**_hard_kwargs(required_entities=("李慕白",)))
    assert result.failed is True
    assert any("实体" in r or "人物" in r for r in result.reasons)


def test_hard_fail_detector_unavailable():
    result = check_hard_fail(**_hard_kwargs(detector_available=False))
    assert result.failed is True
    assert any("检测" in r for r in result.reasons)


# ============ 排序分 ============

def test_ranking_score_rewards_improvement():
    low = compute_ranking_score(
        original_text=_ORIGINAL, rewritten_text=_GOOD_REWRITE,
        original_ai_score=90, rewritten_ai_score=80,
    )
    high = compute_ranking_score(
        original_text=_ORIGINAL, rewritten_text=_GOOD_REWRITE,
        original_ai_score=90, rewritten_ai_score=20,
    )
    assert high > low


def test_ranking_score_penalizes_forbidden_words():
    clean = compute_ranking_score(
        original_text=_ORIGINAL, rewritten_text=_GOOD_REWRITE,
        original_ai_score=90, rewritten_ai_score=20,
    )
    dirty = compute_ranking_score(
        original_text=_ORIGINAL,
        rewritten_text=_GOOD_REWRITE + "他震惊无比，美轮美奂。",
        original_ai_score=90, rewritten_ai_score=20,
    )
    assert dirty < clean


def test_ranking_score_in_range():
    score = compute_ranking_score(
        original_text=_ORIGINAL, rewritten_text=_GOOD_REWRITE,
        original_ai_score=90, rewritten_ai_score=20,
    )
    assert 0.0 <= score <= 100.0


# ============ 成对择优 + 不对称 margin ============

def _pair_kwargs(**overrides):
    data = dict(
        original_text=_ORIGINAL,
        champion_text=_GOOD_REWRITE,
        challenger_text=_GOOD_REWRITE,
        champion_ai_score=40,
        challenger_ai_score=40,
        ai_threshold=60,
        champion_content_safety_passed=True,
        challenger_content_safety_passed=True,
        detector_available=True,
        margin=5.0,
    )
    data.update(overrides)
    return data


def test_judge_pair_tie_returns_champion():
    result = judge_pair(**_pair_kwargs())
    assert isinstance(result, LightJudgeResult)
    assert result.hard_fail is False
    assert result.returned_variant == "champion"
    assert result.margin_passed is False


def test_judge_pair_challenger_wins_with_margin():
    # 挑战者 AI 分显著更低（改善更大）→ 排序分显著领先
    result = judge_pair(**_pair_kwargs(champion_ai_score=50, challenger_ai_score=10))
    assert result.returned_variant == "challenger"
    assert result.margin_passed is True


def test_judge_pair_small_win_returns_champion():
    # 挑战者仅微弱领先，未过 margin → 返回冠军
    result = judge_pair(**_pair_kwargs(champion_ai_score=42, challenger_ai_score=40, margin=10.0))
    assert result.returned_variant == "champion"
    assert result.margin_passed is False


def test_judge_pair_challenger_hard_fail_returns_champion():
    result = judge_pair(**_pair_kwargs(challenger_text="太短", champion_ai_score=50, challenger_ai_score=10))
    assert result.returned_variant == "champion"
    assert result.hard_fail is False  # 冠军仍可用，本路整体不算硬失败


def test_judge_pair_both_hard_fail():
    result = judge_pair(**_pair_kwargs(champion_text="短", challenger_text="也短"))
    assert result.hard_fail is True
    assert result.returned_variant == "champion"
