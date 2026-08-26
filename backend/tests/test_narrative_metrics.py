"""量化质量监控测试（P3：张力趋势 + 浅层文风漂移）。

覆盖：
- 张力指标校验裁剪与滚动沉淀
- 趋势告警策略（连续低谷→规划诊断；钩子+推进同低→定向修订；正常无告警）
- 浅层风格特征计算（句长/对话占比/套话密度）
- 文风漂移判定（基线不足不判定；显著偏离触发信号；只记录不覆盖）
"""
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.narrative_metrics import (
    QUALITY_TREND_KEY,
    STYLE_TREND_KEY,
    TREND_WINDOW,
    compute_style_features,
    detect_style_drift,
    evaluate_quality_trend_alerts,
    format_quality_trend_advice,
    record_quality_metrics,
    record_style_trend,
    validate_quality_metrics,
)


def test_validate_quality_metrics_clamps_and_filters():
    metrics = validate_quality_metrics(
        {
            "tension_score": 120,
            "conflict_progress_score": -5,
            "emotion_change_score": "66",
            "information_gain_score": None,
            "ending_hook_score": 80,
            "unknown_field": 50,
        }
    )
    assert metrics["tension_score"] == 100
    assert metrics["conflict_progress_score"] == 0
    assert metrics["emotion_change_score"] == 66
    assert "information_gain_score" not in metrics
    assert metrics["ending_hook_score"] == 80
    assert "unknown_field" not in metrics
    assert validate_quality_metrics(None) == {}
    assert validate_quality_metrics("not-a-dict") == {}


def test_record_metrics_rolls_window_and_evaluates_alerts():
    review_meta: dict = {}
    for chapter in range(1, TREND_WINDOW + 5):
        record_quality_metrics(
            review_meta,
            chapter,
            {"tension_score": 70, "ending_hook_score": 70, "conflict_progress_score": 70},
        )
    chapters = review_meta[QUALITY_TREND_KEY]["chapters"]
    assert len(chapters) == TREND_WINDOW
    assert str(TREND_WINDOW + 4) in chapters and "1" not in chapters
    assert review_meta[QUALITY_TREND_KEY]["alerts"] == []


def test_consecutive_low_tension_triggers_planning_diagnosis():
    review_meta: dict = {}
    record_quality_metrics(review_meta, 10, {"tension_score": 35})
    assert review_meta[QUALITY_TREND_KEY]["alerts"] == []  # 单章低谷只记录
    record_quality_metrics(review_meta, 11, {"tension_score": 30})
    alert_types = {a["type"] for a in review_meta[QUALITY_TREND_KEY]["alerts"]}
    assert alert_types == {"planning_diagnosis"}
    advice = format_quality_trend_advice(review_meta)
    assert "质量趋势告警" in advice and "张力连续低于阈值" in advice


def test_low_hook_and_progress_triggers_targeted_revision():
    review_meta: dict = {}
    record_quality_metrics(
        review_meta, 5, {"ending_hook_score": 20, "conflict_progress_score": 25, "tension_score": 60}
    )
    alert_types = {a["type"] for a in review_meta[QUALITY_TREND_KEY]["alerts"]}
    assert alert_types == {"targeted_revision"}


def test_no_alerts_on_healthy_chapters():
    review_meta: dict = {}
    record_quality_metrics(
        review_meta,
        3,
        {
            "tension_score": 75,
            "ending_hook_score": 80,
            "conflict_progress_score": 70,
        },
    )
    assert review_meta[QUALITY_TREND_KEY]["alerts"] == []
    assert format_quality_trend_advice(review_meta) == ""
    assert format_quality_trend_advice({}) == ""


def test_style_features_basic_computation():
    assert compute_style_features("短句。") == {}  # 文本过短不计算
    dialogue_heavy = ("「你好。」" * 80) + ("他说。" * 80)
    narration_heavy = "他沿着长街慢慢走着，心里想着昨天的事。" * 30
    features_d = compute_style_features(dialogue_heavy)
    features_n = compute_style_features(narration_heavy)
    assert features_d["dialogue_ratio"] > features_n["dialogue_ratio"]
    assert features_n["avg_sentence_len"] > 0
    assert "cliches_per_1k" in features_d and "exclamation_per_1k" in features_d


def test_style_drift_requires_enough_baseline():
    review_meta: dict = {}
    features = compute_style_features("他沿着长街慢慢走着，心里想着昨天的事。" * 30)
    # 无基线：只记录不判定
    result = detect_style_drift(review_meta, 4, features)
    assert result["drift"] is False and result["baseline_size"] == 0


def test_style_drift_detects_sentence_length_shift():
    review_meta: dict = {}
    base_text = "他沿着长街慢慢走着，心里想着昨天的事，风吹过他的衣角。" * 15
    base_features = compute_style_features(base_text)
    for chapter in range(1, 5):
        record_style_trend(review_meta, chapter, base_text)
    # 第5章突然全部短句
    shifted_text = "他停下。风很冷。他回头。没有人。" * 60
    result = record_style_trend(review_meta, 5, shifted_text)
    assert result["drift"] is True
    flagged_fields = {flag["field"] for flag in result["flags"]}
    assert "avg_sentence_len" in flagged_fields
    # 漂移信号只记录在 style_trend.last_drift，不修改任何稿件
    trend = review_meta[STYLE_TREND_KEY]
    assert trend["last_drift"]["chapter"] == 5
    assert str(5) in trend["chapters"]


def test_style_drift_stable_chapter_no_flag():
    review_meta: dict = {}
    text = "他沿着长街慢慢走着，心里想着昨天的事，风吹过他的衣角。" * 15
    for chapter in range(1, 5):
        record_style_trend(review_meta, chapter, text)
    result = record_style_trend(review_meta, 5, text)
    assert result["drift"] is False
    assert result["flags"] == []
