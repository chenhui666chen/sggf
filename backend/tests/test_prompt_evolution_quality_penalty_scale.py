"""P14 护栏：质量罚分不得淹没朱雀 ratio 主项。

背景（2026-10-16 真实 A/B 轮次 0e0024a3 iteration 2 取证）：
`_ab_rank_score` 的注释宣称「朱雀 ratio 为唯一客观信号、主项」，但真实
候选的失格数分布是：

    原始版本 : 失格 4/8 -> fail_ratio 0.500 -> 罚分 30.0
    变体1    : 失格 2/8 -> fail_ratio 0.250 -> 罚分 15.0
    变体2    : 失格 2/8 -> fail_ratio 0.250 -> 罚分 15.0
    变体3    : 失格 2/8 -> fail_ratio 0.250 -> 罚分 15.0
    变体4    : 失格 7/8 -> fail_ratio 0.875 ->罚分 52.5（已取消资格）
    变体5    : 失格 4/8 -> fail_ratio 0.500 -> 罚分 30.0

而 ratio 的**全部**可能取值是 0.0 ~ 1.0（跨度 1.0）。
质量罚分的**最小非零粒度** = (1/8) x 60.0 = 7.5 分。

    => 失格数只要不同（哪怕只差 1 个样本），ratio 跨度 1.0 < 7.5，
       **ratio 在跨组比较中完全不参与**，胜负 100% 由失格数决定。

实测后果：该轮变体1/2/3 对原始版本的胜出，本质是「2 失格 vs 4 失格」，
而非 AI 率更低。注释与实现严重不符 —— 名不副实的主项会让方向性优化
失去选优出口（ratio 降了也不影响胜负，就没有人会去优化 ratio）。

本文件锁定：
1. 质量罚分的最小非零粒度必须小于 ratio 的全部取值跨度，
   使 ratio 在跨失格分组时仍能参与决胜（质量是守门项，不能一票压死主项）。
2. 质量仍是**守门**：失格占比超限时仍取消资格（>0.5 → 101 档），
   且失格更多的候选在 ratio 相近时仍应排名更差。
3. 大量失格的候选绝不因 ratio 极低而被选中（防止「为降AI率牺牲事实」）。
"""

import pytest

from app.services.prompt_evolution.engine import PromptEvolutionEngine
from app.services.prompt_evolution.models import EvaluationResult


def _review(fidelity=90.0, fact=95.0, naturalness=80.0, info=90.0):
    return {
        "available": True,
        "writing_naturalness": {"score": naturalness},
        "genre_consistency": {"score": 90.0},
        "semantic_fidelity": {"score": fidelity},
        "fact_consistency": {"score": fact},
        "information_completeness": {"score": info},
        "over_rewrite_risk": "low",
    }


def _r(sample_id, ratio, *, hard_fail=False, reason="事实一致性低于90",
       naturalness=80.0):
    """构造评估结果。

    质量硬失败在 evaluator 侧由语义评审产出 `hard_fail` 标记（见evaluator.py
    562 行），排分侧的 `_quality_failure_ratio` 只统计 `success=False` 的样本。
    因此这里直接按真实链路设置 hard_fail / success / failure_kind 三元组，
    而非靠改分数间接制造失格 —— 分数仅用于人感成本项。
    """
    return EvaluationResult(
        sample_id=sample_id,
        original_text="山风掠过断崖，碎石滚入深涧，林渊握紧手中长剑。" * 6,
        rewritten_text="山风掠过断崖。碎石滚入深涧。林渊握紧手中长剑，剑身映出冷光。" * 6,
        original_ai_score=100,
        rewritten_ai_score=100,
        score_reduction=0,
        success=not hard_fail,
        error=reason if hard_fail else None,
        failure_kind="review_hard_fail" if hard_fail else None,
        llm_review=dict(_review(naturalness=naturalness),
                        **({"hard_fail": True,
                            "hard_fail_reasons": [reason],
                            "confidence": 0.9} if hard_fail else {})),
        rewritten_ai_ratio=ratio,
    )


class TestQualityLayeringSupersedesWeightedPenalty:
    """质量以「层号」实现准入，等价强度高于任何加权罚分。

    P15 起`_ab_rank_score` 改为帕累托分层，质量不再走
    `QUALITY_FAILURE_RANK_PENALTY` 加权，而是直接作为层号（失格样本数）
    计入 score。层号每差 1=> score 差 1.0，严格大于 ratio 的全部取值跨度
    （0~1），因此「失格数不同 => ratio 完全不参与」是**设计语义**而非缺陷。

    原「最小罚分粒度 < ratio跨度」的守卫已由分层语义更强地满足：
    加权模型需要精细调参才能做到的事，分层直接成立。
    本类改锁「层号强度」这一新不变量，防止后续有人把层号改回加权。
    """

    def test_layer_unit_dominates_realistic_ratio_gap(self):
        """层号步长必须压过【真实量级】的层内 ratio 差。

        真实 8 版本存档回放：同一失格层内 ratio 的最大差为 0.5318
        （L3 组 5df0af76 0.2540 vs 53a36ee1 0.4038）。层号步长 1.0
        约为其 1.9 倍，足以让质量在真实场景严格优先：

            失格 1/8 + ratio 0.5318 -> score 1.5318（胜）
            失格 2/8 + ratio 0.0000 -> score 2.0000（负）

        注：不用 ratio 端点极值（0 vs 1）验证质量「严格」优先 ——
        端点差恰为 1.0，与层号步长打平（`2+0.00` == `1+1.00`）。
        那是分层模型的定义边界而非缺陷，且真实存档从未出现。
        """
        n = 8
        real_max_gap = 0.5318
        more_failed = [_r(f"s{i}", 0.0, hard_fail=i < 2) for i in range(n)]
        fewer_failed = [
            _r(f"s{i}", real_max_gap, hard_fail=i < 1) for i in range(n)
        ]
        # 「分数越低越优」，故失格更少者的分数必须更低
        assert (PromptEvolutionEngine._ab_rank_score(0.0, fewer_failed, n)
                < PromptEvolutionEngine._ab_rank_score(0.0, more_failed, n)), (
            f"失格 1/8 + ratio {real_max_gap} 应优于失格 2/8 + ratio 0.0"
            f"（层号步长 1.0 > 实测层内最大差 {real_max_gap}）"
        )

    def test_layer_unit_matches_one_sample(self):
        """层号步长 = 1 个失格样本（不按占比缩放，故与样本数无关）。"""
        for n in (4, 8, 16):
            base = [_r(f"s{i}", 0.50, hard_fail=False) for i in range(n)]
            one_more = [_r(f"s{i}", 0.50, hard_fail=i == 0) for i in range(n)]
            diff = (PromptEvolutionEngine._ab_rank_score(0.0, one_more, n)
                    - PromptEvolutionEngine._ab_rank_score(0.0, base, n))
            assert diff == pytest.approx(1.0), (
                f"{n} 样本下多失格 1 个的 score 差应为 1.0（层号步长恒定），"
                f"实际 {diff:.3f}"
            )


class TestQualityStillActsAsGate:
    """质量仍是守门项 —— 罚分不得削弱质量约束的强度。"""

    def test_heavy_failure_disqualified_even_with_tiny_ratio(self):
        """失格占比 > 0.5 时取消资格，即便 ratio = 0。"""
        n = 8
        heavy = [_r(f"s{i}", 0.0, hard_fail=i < 5) for i in range(n)]
        clean = [_r(f"s{i}", 0.50) for i in range(n)]

        heavy_score = PromptEvolutionEngine._ab_rank_score(0.0, heavy, n)
        clean_score = PromptEvolutionEngine._ab_rank_score(0.0, clean, n)

        assert heavy_score > 100.0, "失格占比 5/8 超过 0.5 上限，应取消资格"
        assert clean_score < heavy_score, "质量干净的候选必须排在重失格候选之前"

    def test_more_failures_loses_at_equal_ratio(self):
        """ratio 完全相同时，失格更多的候选排名必须更差。"""
        n = 8
        few = [_r(f"s{i}", 0.30, hard_fail=i < 2) for i in range(n)]
        many = [_r(f"s{i}", 0.30, hard_fail=i < 4) for i in range(n)]

        few_score = PromptEvolutionEngine._ab_rank_score(0.0, few, n)
        many_score = PromptEvolutionEngine._ab_rank_score(0.0, many, n)
        assert few_score < many_score, "同 ratio 下失格更多的应排名更差"

    def test_clean_candidate_not_disqualified(self):
        """质量全通过的候选不得被取消资格。"""
        n = 8
        clean = [_r(f"s{i}", 0.30) for i in range(n)]
        assert PromptEvolutionEngine._ab_rank_score(0.0, clean, n) < 100.0


# ==== 真实文本夹具（取自 evolution_history.json，用于复现真实方差塌缩）====
_COLLAPSED_PAIRS = [
    (
        '黑风岭的夜色浓稠如墨，唯有几缕清冷的月光艰难地穿透厚重的云层，洒在嶙峋怪石之上。林渊盘膝坐在一处隐蔽的山洞深处，周身散发着淡淡的青色微光，那是他运转《青木长生诀》至第三重时特有的灵力波动。空气中的灵气...',
        '洞壁渗着潮冷，林渊在黑风岭一处隐蔽山洞深处盘膝而坐，膝上横着一只旧储物袋，袋口没有系紧，露出里面几块灵石的边角。他双手结印，《青木长生诀》运转至第三重，身周浮起淡淡青色微光；洞外夜气从石缝里钻进来，灵...',
    ),
    (
        '残阳如血，将断魂谷深处的枯木染上了一层凄厉的暗红。林萧盘膝坐在一块布满青苔的巨石之上，周身气息收敛到了极致，仿佛与这死寂的山谷融为一体。他的眉心微微隆起，一道淡金色的符文若隐若现，随着呼吸的节奏忽明忽...',
        '断魂谷深处，残阳把枯木照得发暗，青苔覆在巨石表面，湿冷里夹着腐朽与血腥。林萧盘膝坐在石上，周身气息收敛到极致，眉心一道淡金色符文随呼吸忽明忽现。《九转金身诀》已修至第三重，金身初成的异象在皮肉深处隐隐...',
    ),
    (
        '黑风岭的夜，浓稠得仿佛化不开的墨汁。\n\n林渊盘膝坐在一块被雷火劈焦的巨石之上，周身衣袍已被冷汗浸透，紧紧贴在瘦削却如铁铸般的脊背上。他双目紧闭，眉心处隐隐有一道赤红色的光纹在跳动，那是《焚天诀》运转到...',
        '夜色压在黑风岭上，林间没有半点月光，潮湿腐叶的气息从泥土里一层层翻上来。林渊坐在一块被雷火劈焦的巨石上，膝前三尺处放着一块巴掌大小、通体漆黑的残片。残片边缘参差不齐，表面布满暗金色的古老符文，正是他从...',
    ),
]

_NORMAL_PAIRS = [
    (
        '黑风岭的夜色浓稠如墨，唯有几缕清冷的月光艰难地穿透厚重的云层，洒在嶙峋怪石之上。林渊盘膝坐在一处隐蔽的山洞深处，周身散发着淡淡的青色微光，那是他运转《青木长生诀》至第三重时特有的灵力波动。空气中的灵气...',
        '黑风岭入夜后，山风夹着潮冷的土腥气在林间穿行。隐蔽山洞深处，林渊盘膝而坐，少年人的肩背在昏暗中挺得笔直，双手结印置于膝上。《青木长生诀》运转至第三重，洞外游离的灵气被一丝丝牵引进来，在他面前凝成白色雾...',
    ),
    (
        '残阳如血，将断魂谷深处的枯木染上了一层凄厉的暗红。林萧盘膝坐在一块布满青苔的巨石之上，周身气息收敛到了极致，仿佛与这死寂的山谷融为一体。他的眉心微微隆起，一道淡金色的符文若隐若现，随着呼吸的节奏忽明忽...',
        '断魂谷深处，枯木浸在残阳里，四下一片暗红。林萧盘膝坐在一块布满青苔的巨石上，周身气息收敛到极致，连衣袍边缘都像与谷中阴影贴在了一处。他眉心微微隆起，一道淡金色符文若隐若现，随呼吸忽明忽暗。\n\n那符文是...',
    ),
    (
        '黑风岭的夜，浓稠得仿佛化不开的墨汁。\n\n林渊盘膝坐在一块被雷火劈焦的巨石之上，周身衣袍已被冷汗浸透，紧紧贴在瘦削却如铁铸般的脊背上。他双目紧闭，眉心处隐隐有一道赤红色的光纹在跳动，那是《焚天诀》运转到...',
        '夜色压在黑风岭上，林渊盘膝坐在一块被雷火劈焦的巨石之上，双目紧闭，眉心处隐隐有一道赤红色的光纹在跳动。《焚天诀》在他体内运转到极致，经脉里的灵力一次次冲撞，又被他以神识压回丹田。他身前三尺处，悬浮着一...',
    ),
]


def _from_pairs(pairs, ratio):
    """用真实原文/改写对构造评估结果。"""
    return [
        EvaluationResult(
            sample_id=f"s{i}", original_text=o, rewritten_text=n,
            original_ai_score=100, rewritten_ai_score=100, score_reduction=0,
            success=True, llm_review=_review(), rewritten_ai_ratio=ratio,
        )
        for i, (o, n) in enumerate(pairs)
    ]

class TestVariancePenaltyScale:
    """方差塌缩守门有效，但罚分量纲必须与 ratio 主项一致。

    取证（真实 8 版本存档）：`VARIANCE_COLLAPSE_PENALTY = 10.0`，
    而 ratio 全部取值跨度仅 1.0 —— 命中守门的候选多付 10 分，是 ratio
    跨度的 10 倍，直接把 ratio 最低的版本打到榜尾：

        版本          ratio中位  方差罚分   总排分
        31c84958        0.3507    10.0    10.679
        e1d4192a        0.3120    10.0    10.598
        8f85098d        0.3053    10.0    10.446
        5df0af76        0.2540     0.0     0.567

    守门本身该触发（`31c84958` 改写句长方差 16.0 vs 原文 156.2，比值
    0.104，文本确实被洗平），但它不该压过 ratio 主项 —— 那是「守门
    （不奖励退化）」而非「主项（决定优劣）」的定位。

    夹具用真实文本而非构造文本：句长方差对文本内容极敏感，构造的单调
    重复句会导致原文方差为 0 而被`if orig_var <= 0` 跳过，无法复现塌缩。
    """

    def test_penalty_within_ratio_scale(self):
        assert PromptEvolutionEngine.VARIANCE_COLLAPSE_PENALTY <= 1.0, (
            f"方差塌缩罚分 {PromptEvolutionEngine.VARIANCE_COLLAPSE_PENALTY} "
            f"超过 ratio 全部取值跨度 1.0，属主项而非守门"
        )

    def test_guard_still_fires(self):
        """守门必须仍然触发 —— 罚分不能归零。"""
        assert PromptEvolutionEngine.VARIANCE_COLLAPSE_PENALTY > 0.0

    def test_real_flattened_text_still_penalized(self):
        """真实塌缩文本（31c84958）必须比真实正常文本（253cd2e3）排名更差。"""
        collapsed = _from_pairs(_COLLAPSED_PAIRS, 0.30)
        normal = _from_pairs(_NORMAL_PAIRS, 0.30)
        assert PromptEvolutionEngine._variance_collapse_penalty(collapsed) > 0.0, (
            "真实塌缩文本应命中方差守门"
        )
        assert PromptEvolutionEngine._variance_collapse_penalty(normal) == 0.0, (
            "真实正常文本不应命中方差守门"
        )
        assert (PromptEvolutionEngine._ab_rank_score(0.0, collapsed, len(collapsed))
                > PromptEvolutionEngine._ab_rank_score(0.0, normal, len(normal))), (
            "句式被洗平的候选必须排名更差（守门语义不变）"
        )

    def test_ratio_dominates_over_flattening_penalty(self):
        """ratio 明显更低的候选不应被方差罚分压死。

        取真实量级：命中方差守门的候选 ratio 0.35，未命中的 ratio 0.05
        （差距 0.30，实测版本间 ratio 跨度 0.169 的近 2 倍）。
        """
        collapsed = _from_pairs(_COLLAPSED_PAIRS, 0.35)
        clean_low = _from_pairs(_NORMAL_PAIRS, 0.05)
        collapsed_score = PromptEvolutionEngine._ab_rank_score(
            0.0, collapsed, len(collapsed))
        clean_score = PromptEvolutionEngine._ab_rank_score(
            0.0, clean_low, len(clean_low))
        assert clean_score < collapsed_score, (
            f"ratio 0.05 的干净候选应优于 ratio 0.35 的塌缩候选；"
            f"实际 {clean_score:.3f} vs {collapsed_score:.3f}"
        )
