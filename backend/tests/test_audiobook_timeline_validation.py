"""阶段 0 时间轴验证基础设施单元测试。

覆盖：五类固定场景集冻结稳定性、广告样例与探针结构、字幕解析与对齐、
四项误差指标、eligible 判定、以及默认模型口径不改写历史配置的回归。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = Path(__file__).resolve().parents[2]
for _path in (ROOT_DIR, PROJECT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.project_audio_config import (  # noqa: E402
    DEFAULT_SEED_AUDIO_MODEL,
    SEED_AUDIO_MODEL_MULTILINGUAL,
    get_seed_audio_model,
    set_seed_audio_model,
)
from app.services.audiobook.seed_scene_test_unit import get_seed_scene_test_case  # noqa: E402
from app.services.audiobook.timeline_validation import (  # noqa: E402
    EligibilityThresholds,
    RunMetrics,
    SubtitleEvent,
    aggregate_run_metrics,
    align_speech_events,
    build_baseline_catalog,
    catalog_canonical_hash,
    compute_run_metrics,
    decide_timeline_eligibility,
    extract_subtitle_events,
    percentile,
)
from app.services.audiobook.timeline_validation.ad_timeline_sample import (  # noqa: E402
    AD_TARGET_EVENTS,
    TIMELINE_SYNTAX_CANONICAL,
    TIMELINE_SYNTAX_VARIANTS,
    ad_compliance_target,
    build_boundary_probes,
    build_failure_probes,
    build_syntax_probes,
    build_timeline_prompt,
    render_window,
)

_EXPECTED_SCENARIO_IDS = [
    "phone_distortion_dialogue",
    "lingshan_battle",
    "narrative_monologue",
    "live_commerce",
    "ad_timeline",
]

# 基线冻结哈希：任何对冻结 Prompt/结构的改动都会使本断言失败；
# 确需演进时提升 BASELINE_CATALOG_VERSION、更新本哈希并按 DEC 模板登记。
_FROZEN_CATALOG_SHA256 = (
    "afe3a885b948b96d8c144dccc29c4d3118e45c2df03121d6ded88cfad8d4de65"
)


class TestBaselineCatalog:
    def test_catalog_contains_five_frozen_scenarios(self) -> None:
        catalog = build_baseline_catalog()
        assert catalog["catalog_id"] == "seed-audio-v2-phase0-scenarios"
        assert catalog["catalog_version"] == "1.0.0"
        assert [scenario["id"] for scenario in catalog["scenarios"]] == _EXPECTED_SCENARIO_IDS
        for scenario in catalog["scenarios"]:
            assert scenario["prompt"].strip()
            assert scenario["expected_texts"]
            assert scenario["expected_duration_s"] > 0
            assert scenario["prompt_sha256"] == hashlib.sha256(
                scenario["prompt"].encode("utf-8")
            ).hexdigest()

    def test_reused_v1_scenarios_are_verbatim_from_v1_catalog(self) -> None:
        catalog = build_baseline_catalog()
        by_id = {scenario["id"]: scenario for scenario in catalog["scenarios"]}

        phone_case = get_seed_scene_test_case("phone_confrontation")
        phone_variant = next(
            item for item in phone_case["variants"] if item["id"] == "described_voices"
        )
        assert by_id["phone_distortion_dialogue"]["prompt"] == phone_variant["prompt"]
        assert by_id["phone_distortion_dialogue"]["expected_texts"] == list(
            phone_case["expected_texts"]
        )

        monologue_case = get_seed_scene_test_case("single_voice_memory")
        monologue_variant = next(
            item for item in monologue_case["variants"] if item["id"] == "described_voices"
        )
        assert by_id["narrative_monologue"]["prompt"] == monologue_variant["prompt"]

    def test_catalog_hash_is_deterministic(self) -> None:
        assert catalog_canonical_hash() == catalog_canonical_hash(build_baseline_catalog())

    def test_catalog_hash_matches_frozen_baseline(self) -> None:
        assert catalog_canonical_hash() == _FROZEN_CATALOG_SHA256


class TestAdTimelineSample:
    def test_canonical_prompt_contains_windows_and_lines(self) -> None:
        prompt = build_timeline_prompt(TIMELINE_SYNTAX_CANONICAL)
        assert "[2.0s:6.0s]" in prompt
        assert "[8.0s:13.0s]" in prompt
        assert "[16.0s:21.0s]" in prompt
        for event in AD_TARGET_EVENTS:
            if event["kind"] == "speech":
                assert event["text"] in prompt

    def test_syntax_variants_render_distinct_windows(self) -> None:
        rendered = {
            syntax: render_window(2.0, 6.0, syntax)
            for syntax in TIMELINE_SYNTAX_VARIANTS
        }
        assert rendered["seconds_s"] == "[2.0s:6.0s]"
        assert rendered["milliseconds"] == "[2000ms:6000ms]"
        assert rendered["seconds_cn"] == "[2.0秒:6.0秒]"
        assert rendered["fullwidth_colon"] == "[2.0s：6.0s]"
        assert rendered["spaced"] == "[ 2.0s : 6.0s ]"
        assert len(set(rendered.values())) == len(rendered)

    def test_probe_sets_are_complete(self) -> None:
        syntax_probes = build_syntax_probes()
        assert [probe["probe_id"] for probe in syntax_probes] == [
            f"syntax_{syntax}" for syntax in TIMELINE_SYNTAX_VARIANTS
        ]
        boundary_ids = {probe["probe_id"] for probe in build_boundary_probes()}
        assert boundary_ids == {
            "boundary_min_window",
            "boundary_over_120s_window",
            "boundary_window_beyond_total",
            "boundary_overlapping_windows",
        }
        failure_ids = {probe["probe_id"] for probe in build_failure_probes()}
        assert failure_ids == {
            "failure_inverted_window",
            "failure_non_numeric_window",
            "failure_empty_events",
        }
        target = ad_compliance_target()
        assert target["sample_id"] == "ad_timeline_fixed_v1"
        assert target["total_duration_s"] == 30.0
        assert target["expected_texts"] == [
            "深夜加班，胃在抗议。",
            "一杯温热，三分钟回到状态。",
            "现在下单，第二件半价。",
        ]


class TestSubtitleParsingAndAlignment:
    def test_extract_subtitle_events_supports_both_shapes(self) -> None:
        sentences = [
            {"text": "深夜加班，胃在抗议。", "start_time": 2100, "end_time": 5800},
            {"text": "一杯温热，三分钟回到状态。", "start_time": 8200, "end_time": 12900},
        ]
        from_dict = extract_subtitle_events({"subtitles": {"sentences": sentences}})
        from_list = extract_subtitle_events({"subtitles": sentences})
        from_json_string = extract_subtitle_events(
            {"subtitles": json.dumps({"sentences": sentences})}
        )
        assert from_dict == from_list == from_json_string
        assert from_dict[0] == SubtitleEvent(start_ms=2100, end_ms=5800, text="深夜加班，胃在抗议。")
        assert extract_subtitle_events(None) == []
        assert extract_subtitle_events({"subtitles": "not-json"}) == []

    def test_align_speech_events_matches_by_text_and_order(self) -> None:
        events = [event for event in AD_TARGET_EVENTS if event["kind"] == "speech"]
        subtitles = [
            SubtitleEvent(start_ms=8200, end_ms=12900, text="一杯温热，三分钟回到状态。"),
            SubtitleEvent(start_ms=2100, end_ms=5800, text="深夜加班，胃在抗议。"),
            SubtitleEvent(start_ms=16400, end_ms=20800, text="现在下单，第二件半价。"),
        ]
        alignment = align_speech_events(events, subtitles)
        assert alignment["unmatched"] == []
        assert alignment["alignment_ratio"] == 1.0
        assert [item["text"] for item in alignment["matched"]] == [
            "深夜加班，胃在抗议。",
            "一杯温热，三分钟回到状态。",
            "现在下单，第二件半价。",
        ]
        # 乱序字幕也必须按目标窗口就近归位
        assert alignment["matched"][0]["actual_start_ms"] == 2100.0

    def test_align_reports_unmatched_and_extra_subtitles(self) -> None:
        events = [event for event in AD_TARGET_EVENTS if event["kind"] == "speech"]
        subtitles = [SubtitleEvent(start_ms=100, end_ms=900, text="完全无关的声音")]
        alignment = align_speech_events(events, subtitles)
        assert len(alignment["unmatched"]) == 3
        assert alignment["alignment_ratio"] == 0.0
        assert alignment["unmatched_subtitles"][0]["text"] == "完全无关的声音"


class TestRunMetrics:
    def _events(self):
        return [event for event in AD_TARGET_EVENTS if event["kind"] == "speech"]

    def test_perfect_run_yields_zero_errors(self) -> None:
        subtitles = [
            SubtitleEvent(start_ms=2000, end_ms=6000, text="深夜加班，胃在抗议。"),
            SubtitleEvent(start_ms=8000, end_ms=13000, text="一杯温热，三分钟回到状态。"),
            SubtitleEvent(start_ms=16000, end_ms=21000, text="现在下单，第二件半价。"),
        ]
        metrics = compute_run_metrics(
            "r1",
            success=True,
            events=self._events(),
            subtitles=subtitles,
            total_duration_s=30.0,
            observed_duration_ms=30000.0,
        )
        assert metrics.start_errors_ms == [0.0, 0.0, 0.0]
        assert metrics.end_errors_ms == [0.0, 0.0, 0.0]
        assert metrics.duration_error_ms == 0.0
        assert metrics.alignment_ratio == 1.0
        assert metrics.within_window_ratio == 1.0

    def test_failed_run_skips_metrics(self) -> None:
        metrics = compute_run_metrics(
            "r2",
            success=False,
            events=self._events(),
            subtitles=[],
            total_duration_s=30.0,
            error="provider_error",
        )
        assert metrics.start_errors_ms == []
        assert metrics.duration_error_ms is None

    def test_missing_observed_duration_leaves_duration_error_none(self) -> None:
        metrics = compute_run_metrics(
            "r3",
            success=True,
            events=self._events(),
            subtitles=[SubtitleEvent(start_ms=2000, end_ms=6000, text="深夜加班，胃在抗议。")],
            total_duration_s=30.0,
            observed_duration_ms=None,
        )
        assert metrics.duration_error_ms is None
        assert metrics.alignment_ratio == pytest.approx(1.0 / 3.0)


class TestPercentileAndAggregate:
    def test_percentile_linear_interpolation(self) -> None:
        assert percentile([], 95) is None
        assert percentile([42.0], 95) == 42.0
        assert percentile([0.0, 10.0], 50) == 5.0
        values = [float(item) for item in range(101)]
        assert percentile(values, 95) == 95.0

    def test_aggregate_collects_across_runs(self) -> None:
        runs = [
            RunMetrics(run_id="a", success=True, start_errors_ms=[100.0], end_errors_ms=[200.0]),
            RunMetrics(run_id="b", success=True, start_errors_ms=[300.0], end_errors_ms=[400.0]),
            RunMetrics(run_id="c", success=False),
        ]
        aggregate = aggregate_run_metrics(runs)
        assert aggregate["run_count"] == 3
        assert aggregate["successful_run_count"] == 2
        assert aggregate["start_error_ms"]["max"] == 300.0
        assert aggregate["end_error_ms"]["count"] == 2


def _perfect_runs(count: int = 3, *, start_offset_ms: float = 0.0) -> list[RunMetrics]:
    runs = []
    for index in range(count):
        runs.append(
            RunMetrics(
                run_id=f"r{index}",
                success=True,
                start_errors_ms=[start_offset_ms] * 3,
                end_errors_ms=[start_offset_ms] * 3,
                duration_error_ms=0.0,
                event_alignment_errors_ms=[start_offset_ms] * 3,
                alignment_ratio=1.0,
                within_window_ratio=1.0 if start_offset_ms <= 2000.0 else 0.0,
            )
        )
    return runs


class TestEligibilityDecision:
    def test_perfect_runs_are_eligible_for_both_modes(self) -> None:
        verdict = decide_timeline_eligibility(_perfect_runs())
        assert verdict["strict_timeline_eligible"] is True
        assert verdict["bounded_timeline_eligible"] is True
        assert verdict["policy_version"] == "1.0.0"

    def test_insufficient_runs_block_both_modes(self) -> None:
        verdict = decide_timeline_eligibility(_perfect_runs(count=2))
        assert verdict["strict_timeline_eligible"] is False
        assert verdict["bounded_timeline_eligible"] is False

    def test_moderate_error_blocks_strict_but_keeps_bounded(self) -> None:
        # 1200ms 恒定偏差：strict 的 P50 上限为 800ms，bounded 容忍 2000ms。
        verdict = decide_timeline_eligibility(_perfect_runs(start_offset_ms=1200.0))
        assert verdict["strict_timeline_eligible"] is False
        assert verdict["bounded_timeline_eligible"] is True
        assert any("P50" in reason for reason in verdict["strict_reasons"])

    def test_thresholds_are_overridable_and_versioned(self) -> None:
        policy = EligibilityThresholds.from_mapping({"strict_start_end_p50_ms": 2000.0})
        verdict = decide_timeline_eligibility(
            _perfect_runs(start_offset_ms=1200.0), policy
        )
        assert verdict["strict_timeline_eligible"] is True
        assert verdict["thresholds"]["strict_start_end_p50_ms"] == 2000.0


class TestDefaultSwitchDoesNotRewriteHistory:
    """阶段 0 承诺：默认口径切换只发生在解析层，不改写历史配置/checkpoint。

    阶段 1 默认切换后：新任务默认 multilingual；历史显式配置仍解析为原模型。
    """

    def test_default_resolution_returns_current_default(self) -> None:
        assert get_seed_audio_model({}) == DEFAULT_SEED_AUDIO_MODEL == "seed-audio-1.0-multilingual"

    def test_historical_standard_config_keeps_original_model(self) -> None:
        historical = {"seed_audio_model": "seed-audio-1.0"}
        resolved = get_seed_audio_model(historical)
        assert resolved == "seed-audio-1.0"
        # 解析层不得就地改写历史配置值
        assert historical["seed_audio_model"] == "seed-audio-1.0"

    def test_historical_multilingual_config_is_not_rewritten(self) -> None:
        historical = {"seed_audio_model": SEED_AUDIO_MODEL_MULTILINGUAL}
        resolved = get_seed_audio_model(historical)
        assert resolved == SEED_AUDIO_MODEL_MULTILINGUAL
        # 解析层不得就地改写历史配置值
        assert historical["seed_audio_model"] == SEED_AUDIO_MODEL_MULTILINGUAL

    def test_set_rejects_model_outside_open_set(self) -> None:
        config: dict = {}
        with pytest.raises(ValueError):
            set_seed_audio_model(config, "seed-audio-2.0")
        assert config == {}


class TestValidationScriptDryRun:
    def test_dry_run_writes_plan_without_paid_calls(self, tmp_path: Path) -> None:
        from scripts.validate_seed_audio_timeline import main

        exit_code = main(
            [
                "--repeats",
                "3",
                "--output-root",
                str(tmp_path),
            ]
        )
        assert exit_code == 0
        run_dirs = list(tmp_path.glob("run_*"))
        assert len(run_dirs) == 1
        plan = json.loads((run_dirs[0] / "plan.json").read_text(encoding="utf-8"))
        assert plan["paid"] is False
        assert plan["model"] == "seed-audio-1.0-multilingual"
        assert plan["repeats"] == 3
        assert plan["baseline_catalog_sha256"] == catalog_canonical_hash()

    def test_paid_flag_requires_confirmation(self, tmp_path: Path) -> None:
        from scripts.validate_seed_audio_timeline import main

        assert main(["--paid", "--output-root", str(tmp_path)]) == 2
        assert main(["--repeats", "1", "--output-root", str(tmp_path)]) == 2
