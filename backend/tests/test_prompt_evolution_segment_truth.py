"""P4-b 护栏：朱雀段落级真值必须进入提示词进化归因闭环。

背景（2026-10-16 代码审计取证）：
- zhuque_ai_detect.py 返回的字段名是 segment_labels（含每段 text/label/conf），
  但 evaluator.py:352/378 读的是 ai_trace_details —— 朱雀根本不返回该字段，
  于是 original_trace_detail / rewritten_trace_detail 恒为 None，
  _build_trace_detail 永远输出「无法获取AI痕迹详情」。
- 段落真值此前只用于「改写层定点指令」（novel_rules.build_detector_segment_hint），
  从未进入「进化层归因」：优化器只知道 ratio 数值，不知道被判定为AI的段落
  长什么样，无法归纳系统性模式（句长、开头/结尾词、段落位置）。

本文件锁定：段落标注落盘、序列化可往返、特征聚合可产出统计结论。
"""

import pytest

from app.services.prompt_evolution.meta_optimizer import META_OPTIMIZER_PROMPT, MetaOptimizer
from app.services.prompt_evolution.models import EvaluationResult, PromptVersion


def _segment(text, label, conf=0.95, start=0):
    return {"text": text, "label": label, "conf": conf, "start": start}


def _result(sample_id, segments, *, ratio=0.5):
    return EvaluationResult(
        sample_id=sample_id,
        original_text="原文内容。" * 30,
        rewritten_text="改写内容。" * 30,
        original_ai_score=100,
        rewritten_ai_score=100,
        score_reduction=20,
        success=True,
        llm_review={
            "available": True, "hard_fail": False,
            "semantic_fidelity": {"score": 92.0},
            "fact_consistency": {"score": 93.0},
            "information_completeness": {"score": 92.0},
            "writing_naturalness": {"score": 88.0},
            "genre_consistency": {"score": 90.0},
            "over_rewrite_risk": "low",
        },
        rewritten_ai_ratio=ratio,
        rewritten_segments=segments,
    )


class TestSegmentTruthRoundTrip:
    """段落真值必须能落盘并读回，否则重启后归因退化为空。"""

    def test_to_dict_contains_segments(self):
        version = PromptVersion(
            prompt_text="p",
            evaluation_results=[
                _result("s1", [_segment("被判AI的段落", 1), _segment("人工段落", 0)])
            ],
        )
        data = version.to_dict()
        assert len(data["evaluation_results"][0]["rewritten_segments"]) == 2

    def test_round_trip_preserves_segments(self):
        segs = [_segment("段落A", 1, conf=0.88, start=10)]
        version = PromptVersion(prompt_text="p", evaluation_results=[_result("s1", segs)])
        restored = PromptVersion.from_dict(version.to_dict())
        assert restored.evaluation_results[0].rewritten_segments == segs

    def test_legacy_archive_degrades_to_empty(self):
        """旧存档缺该字段时降级为空列表，不得抛异常。"""
        version = PromptVersion(prompt_text="p", evaluation_results=[_result("s1", [])])
        data = version.to_dict()
        data["evaluation_results"][0].pop("rewritten_segments")
        restored = PromptVersion.from_dict(data)
        assert restored.evaluation_results[0].rewritten_segments == []


class TestSegmentInsightAggregation:
    """段落特征聚合：让优化器看到系统性模式而非单一样本。"""

    def _opt(self):
        opt = MetaOptimizer.__new__(MetaOptimizer)
        return opt

    def test_counts_ai_segments_across_samples(self):
        opt = self._opt()
        results = [
            _result("s1", [_segment("甲", 1), _segment("乙", 1), _segment("丙", 0)]),
            _result("s2", [_segment("丁", 1), _segment("戊", 0), _segment("己", 0)]),
        ]

        text = opt._build_segment_insight(results)

        assert "3" in text  # 共 3 段被判确定AI
        assert "6" in text  # 总段落数

    def test_reports_average_length_of_ai_segments(self):
        opt = self._opt()
        ai_seg = "他缓步走到窗前，推开半掩的雕花木窗。"   # 18 字
        results = [_result("s1", [_segment(ai_seg, 1), _segment("短。", 0)])]

        text = opt._build_segment_insight(results)

        assert "18" in text

    def test_reports_frequent_opening_and_ending_patterns(self):
        """高频开头/结尾是检测器最可能的匹配模式，必须显式给出。"""
        opt = self._opt()
        results = [
            _result("s1", [_segment("随后他站起身，走向门口。", 1),
                           _segment("他的目光落在桌上。", 1)]),
            _result("s2", [_segment("随后她转过身，看向窗外。", 1)]),
        ]

        text = opt._build_segment_insight(results)

        assert "随后" in text

    def test_no_segment_data_returns_explicit_na(self):
        opt = self._opt()
        results = [_result("s1", [])]
        text = opt._build_segment_insight(results)
        assert "N/A" in text or "无段落" in text

    def test_suspect_segments_excluded_from_ai_stats(self):
        """label=2（疑似）不是优化目标，不得混入确定AI 的统计。"""
        opt = self._opt()
        ai_text = "确定AI段落，这是被确定的。"
        suspect_text = "疑似段落，这是疑似的，这里还多几个字凑长度。"
        assert len(suspect_text) > len(ai_text) + 5, "用例前提：疑似段须显著更长，否则测不出混入"
        results = [_result("s1", [_segment(ai_text, 1), _segment(suspect_text, 2)])]

        text = opt._build_segment_insight(results)

        # 只统计确定AI：均值应为 ai_text 自身长度（混入则均值被拉高）
        assert f"{len(ai_text)} 字" in text
        assert "共 2 段落" in text
        assert "1 段被判" in text


class TestSegmentInsightReachesPrompt:
    def test_prompt_has_placeholder(self):
        assert "{segment_insight}" in META_OPTIMIZER_PROMPT

    def test_placeholder_renders(self):
        rendered = META_OPTIMIZER_PROMPT.format(
            current_prompt="p", avg_score="100.0", target_score=60,
            avg_reduction="12.0", ai_ratio_pct="18.5",
            success_count=2, total_count=4,
            quality_gap_analysis="q", segment_insight="<<<段落特征>>>",
            success_analysis="s", failure_analysis="f", trend_analysis="t",
            experience_summary="e", previous_analysis_summary="p",
        )
        assert "<<<段落特征>>>" in rendered

    def test_prompt_explains_how_to_use_segment_features(self):
        """必须说明这是检测器真值，且要求按系统模式而非个例归因。"""
        assert "段落" in META_OPTIMIZER_PROMPT


class TestEvaluatorReadsRealSegmentField:
    """🔴 回归护栏：evaluator 必须读朱雀真实返回的 segment_labels。

    历史上误读 ai_trace_details（朱雀从不返回该键），导致段落真值恒为空、
    定点改写退回正则盲猜、进化归因完全拿不到段落信息。
    """

    def test_source_field_name_is_segment_labels(self):
        import inspect

        from app.services.prompt_evolution import evaluator as ev

        src = inspect.getsource(ev)
        assert 'get("segment_labels"' in src
        assert 'get("ai_trace_details", {})' not in src