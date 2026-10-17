from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.ai_trace_competition import (
    CombinationPerformanceRecord,
    ModelConfigStorage,
    ModelPerformanceRecord,
    MultiModelEvaluationService,
    SingleModelResult,
)
from app.services.prompt_evolution.genre import normalize_genre
from app.services.prompt_evolution.storage import EvolutionStorage


def test_normalize_genre_maps_project_values_and_rejects_unknown_values():
    assert normalize_genre("Fantasy") == "玄幻"
    assert normalize_genre("sci-fi") == "科幻"
    assert normalize_genre(" 武侠小说 ") == "武侠"
    assert normalize_genre("not-a-real-genre") == "通用"
    assert normalize_genre(None) == "通用"


def test_legacy_performance_migration_does_not_depend_on_current_model_whitelist(tmp_path):
    legacy_record = {
        "model_id": "retired-model",
        "model_name": "Retired",
        "provider": "legacy",
        "total_evaluations": 7,
        "total_success": 6,
        "avg_ai_score": 23.0,
        "avg_improvement": 30.0,
        "best_ai_score": 10.0,
        "avg_latency": 2.0,
        "last_evaluated_at": "",
    }
    (tmp_path / "model_performance.json").write_text(
        json.dumps({"retired-model": legacy_record}, ensure_ascii=False),
        encoding="utf-8",
    )

    storage = ModelConfigStorage(str(tmp_path))

    assert storage.load_performance("通用")["retired-model"].avg_ai_score == 23.0


def test_best_prompt_by_genre_uses_documented_fallback_chain(tmp_path):
    storage = EvolutionStorage(str(tmp_path))
    (tmp_path / "approved_prompts.json").write_text(
        json.dumps(
            [
                {"prompt_text": "通用批准", "genre": "通用", "approved_at": "2026-01-01"},
                {"prompt_text": "玄幻批准", "genre": "玄幻", "approved_at": "2026-01-02"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert storage.get_best_prompt_by_genre("玄幻") == "玄幻批准"
    assert storage.get_best_prompt_by_genre("历史") == "通用批准"


def test_best_prompt_by_genre_prefers_genre_history_before_general_approved(tmp_path):
    storage = EvolutionStorage(str(tmp_path))
    (tmp_path / "approved_prompts.json").write_text(
        json.dumps([{"prompt_text": "通用批准", "genre": "通用"}], ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "best_prompts.json").write_text(
        json.dumps(
            [
                {
                    "version_id": "urban-best",
                    "prompt_text": "都市历史最佳",
                    "avg_ai_score": 20.0,
                    "avg_composite_score": 25.0,
                    "genre": "都市",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert storage.get_best_prompt_by_genre("都市") == "都市历史最佳"


def test_challenge_round_counter_is_monotonic_across_evolution_runs(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    storage.save_config({"eliminated_models": {"玄幻": ["qwen-plus"]}})

    for _ in range(4):
        storage.record_regular_evaluation_round("玄幻")
    assert storage.should_run_challenge("玄幻") is False

    storage.record_regular_evaluation_round("玄幻")
    assert storage.should_run_challenge("玄幻") is True
    storage.mark_challenge_done("玄幻")

    # 模拟新的进化任务；计数不能因局部 iteration 从 1 开始而倒退。
    reloaded = ModelConfigStorage(str(tmp_path))
    for _ in range(5):
        reloaded.record_regular_evaluation_round("玄幻")
    assert reloaded.should_run_challenge("玄幻") is True


def test_revived_model_starts_new_statistics_with_challenge_result(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    storage.save_config({"eliminated_models": {"玄幻": ["qwen-plus"]}})
    storage.save_performance(
        {
            "qwen-plus": ModelPerformanceRecord(
                model_id="qwen-plus",
                model_name="Qwen",
                provider="alibaba",
                total_evaluations=8,
                total_success=8,
                avg_ai_score=70,
            )
        },
        "玄幻",
    )
    challenge = SingleModelResult(
        model_id="qwen-plus",
        model_name="Qwen",
        provider="alibaba",
        reduced_text="文本",
        ai_score=20,
        ai_ratio=0.20,
        latency_seconds=1.5,
        improvement=40,
        original_ai_ratio=0.70,
    )
    competitors = [
        challenge,
        SingleModelResult("m1", "M1", "p", "文本", 10, 1, improvement=40, ai_ratio=0.10,
                          original_ai_ratio=0.60),
        SingleModelResult("m2", "M2", "p", "文本", 30, 1, improvement=20, ai_ratio=0.30,
                          original_ai_ratio=0.80),
        SingleModelResult("m3", "M3", "p", "文本", 40, 1, improvement=10, ai_ratio=0.40,
                          original_ai_ratio=0.90),
    ]

    revived = storage.process_challenge_results("玄幻", [challenge], competitors)

    record = storage.load_performance("玄幻")["qwen-plus"]
    assert revived == ["qwen-plus"]
    assert record.total_evaluations == 1
    assert record.total_success == 1
    assert record.avg_ai_score == 20
    # 🔧 复活后的首条记录必须带上选型主项，否则会以默认 1.0 参与下一轮比较
    assert record.avg_ai_ratio == 0.20
    assert record.avg_improvement == 40


def _mature_record(model_id: str, score: float) -> ModelPerformanceRecord:
    """score 以「百分点」计（0-100），同时映射到选型主项 avg_ai_ratio（0-1）。

    🔧 2026-10-08：淘汰判据主键由 avg_ai_score 改为 avg_ai_ratio，
    故 avg_ai_ratio 是这里唯一被 evaluate_elimination 读取的字段；
    avg_ai_score 保留为诊断值（真实改写区间恒为 100，不参与比较）。
    """
    return ModelPerformanceRecord(
        model_id=model_id,
        model_name=model_id,
        provider="test",
        total_evaluations=5,
        total_success=5,
        avg_ai_score=score,
        avg_ai_ratio=score / 100.0,
        best_ai_ratio=score / 100.0,
    )


def test_elimination_starts_when_two_models_are_mature_and_uses_strict_gap(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    storage.save_performance(
        {
            "qwen-plus": _mature_record("qwen-plus", 10),
            "deepseek-flash": _mature_record("deepseek-flash", 31),
        },
        "玄幻",
    )

    assert storage.evaluate_elimination("玄幻") == ["deepseek-flash"]

    boundary_storage = ModelConfigStorage(str(tmp_path / "boundary"))
    boundary_storage.save_performance(
        {
            "qwen-plus": _mature_record("qwen-plus", 10),
            "deepseek-flash": _mature_record("deepseek-flash", 30),
        },
        "玄幻",
    )
    assert boundary_storage.evaluate_elimination("玄幻") == []


class TestAiRatioDrivesSelectionAndElimination:
    """🔧 2026-10-08：选型与淘汰判据统一到 avg_ai_ratio。

    旧口径取证：avg_ai_score 在 LLM 改写区间恒为 100，于是
    evaluate_elimination 的 threshold = 100 + 20 = 120，判据
    `avg_ai_score > 120` 永不成立 —— 性能淘汰从未真正触发过；
    update_auto_best_model 对恒等值取 min，等价于从字典里按插入序取一个。
    """

    def test_auto_best_model_follows_ai_ratio_not_ai_score(self, tmp_path):
        storage = ModelConfigStorage(str(tmp_path))
        good = _mature_record("doubao-seed-evolving", 100)  # ai_score 均为 100
        good.avg_ai_ratio = 0.05
        bad = _mature_record("glm", 100)
        bad.avg_ai_ratio = 0.90
        storage.save_performance(
            {"doubao-seed-evolving": good, "glm": bad}, "玄幻"
        )

        assert storage.update_auto_best_model("玄幻") == "doubao-seed-evolving"

    def test_elimination_uses_ai_ratio_gap(self, tmp_path):
        storage = ModelConfigStorage(str(tmp_path))
        storage.save_performance(
            {
                "qwen-plus": _mature_record("qwen-plus", 20),      # 0.20
                "deepseek-flash": _mature_record("deepseek-flash", 45),  # 0.45 > 0.20+0.20
            },
            "玄幻",
        )

        assert storage.evaluate_elimination("玄幻") == ["deepseek-flash"]

    def test_elimination_boundary_not_exceeded(self, tmp_path):
        # 恰好等于门槛（20+20=40）不淘汰，守住「超过」而非「达到」
        storage = ModelConfigStorage(str(tmp_path))
        storage.save_performance(
            {
                "qwen-plus": _mature_record("qwen-plus", 20),
                "deepseek-flash": _mature_record("deepseek-flash", 40),
            },
            "玄幻",
        )

        assert storage.evaluate_elimination("玄幻") == []

    def test_elimination_dormant_when_all_ai_ratio_default(self, tmp_path):
        # 全部为默认 avg_ai_ratio=1.0（无检测数据）时不得误淘汰
        storage = ModelConfigStorage(str(tmp_path))
        storage.save_performance(
            {
                "qwen-plus": ModelPerformanceRecord(
                    model_id="qwen-plus", model_name="Q", provider="p",
                    total_evaluations=5, total_success=5,
                ),
                "deepseek-flash": ModelPerformanceRecord(
                    model_id="deepseek-flash", model_name="D", provider="p",
                    total_evaluations=5, total_success=5,
                ),
            },
            "玄幻",
        )

        assert storage.evaluate_elimination("玄幻") == []


def test_challenge_selects_only_one_eliminated_model(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    storage.save_config({
        "eliminated_models": {
            "玄幻": ["qwen-plus", "deepseek-flash"]
        }
    })

    assert len(storage.get_challenge_candidates("玄幻")) == 1


def test_evolving_model_has_fast_non_thinking_evaluation_policy():
    service = MultiModelEvaluationService
    policy = service.get_model_evaluation_policy("doubao-seed-evolving")

    assert policy["timeout"] == 90
    assert policy["max_tokens"] == 4096
    assert policy["extra_body"] == {"thinking": {"type": "disabled"}}
    assert service.get_model_evaluation_policy("qwen-plus")["timeout"] == service.SINGLE_MODEL_TIMEOUT


def test_repeated_model_failures_quarantine_only_that_genre(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    failed = SingleModelResult(
        "doubao-seed-evolving", "Doubao", "volcengine", "", 100, 90,
        success=False, error="超时",
    )

    for _ in range(2):
        storage.update_availability_status(failed, "玄幻")
    assert "doubao-seed-evolving" not in storage.get_eliminated_models("玄幻")

    storage.update_availability_status(failed, "玄幻")
    assert "doubao-seed-evolving" in storage.get_eliminated_models("玄幻")
    assert "doubao-seed-evolving" not in storage.get_eliminated_models("都市")


def test_success_clears_model_failure_streak(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    failed = SingleModelResult(
        "doubao-seed-evolving", "Doubao", "volcengine", "", 100, 90,
        success=False, error="超时",
    )
    success = SingleModelResult(
        "doubao-seed-evolving", "Doubao", "volcengine", "文本", 20, 10,
        success=True, ai_ratio=0.30, original_ai_ratio=0.80,
    )
    storage.update_availability_status(failed, "玄幻")
    storage.update_availability_status(success, "玄幻")

    assert storage.load_config().get("availability_failures", {}).get("玄幻", {}).get("doubao-seed-evolving", 0) == 0


def test_challenger_revives_only_when_ranked_in_top_three(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    storage.save_config({"eliminated_models": {"玄幻": ["qwen-plus"]}})
    # 🔧 2026-10-08：排位主键由 ai_score 改为 ai_ratio，名次由 ai_ratio 决定
    third = SingleModelResult(
        "qwen-plus", "Qwen", "p", "文本", 30, 1, improvement=20, ai_ratio=0.30,
        original_ai_ratio=0.80,
    )
    results = [
        SingleModelResult("m1", "M1", "p", "文本", 10, 1, improvement=40, ai_ratio=0.10,
                          original_ai_ratio=0.60),
        SingleModelResult("m2", "M2", "p", "文本", 20, 1, improvement=30, ai_ratio=0.20,
                          original_ai_ratio=0.70),
        third,
        SingleModelResult("m3", "M3", "p", "文本", 40, 1, improvement=10, ai_ratio=0.40,
                          original_ai_ratio=0.90),
    ]
    assert storage.process_challenge_results("玄幻", [third], results) == ["qwen-plus"]

    storage.save_config({"eliminated_models": {"玄幻": ["qwen-plus"]}})
    fourth = SingleModelResult(
        "qwen-plus", "Qwen", "p", "文本", 35, 1, improvement=15, ai_ratio=0.35,
        original_ai_ratio=0.85,
    )
    results = [
        SingleModelResult("m1", "M1", "p", "文本", 10, 1, improvement=40, ai_ratio=0.10,
                          original_ai_ratio=0.60),
        SingleModelResult("m2", "M2", "p", "文本", 20, 1, improvement=30, ai_ratio=0.20,
                          original_ai_ratio=0.70),
        SingleModelResult("m3", "M3", "p", "文本", 30, 1, improvement=20, ai_ratio=0.30,
                          original_ai_ratio=0.80),
        fourth,
    ]
    assert storage.process_challenge_results("玄幻", [fourth], results) == []


def _semantic_review() -> dict:
    return {
        "available": True,
        "hard_fail": False,
        "over_rewrite_risk": "low",
        "confidence": 0.95,
        "semantic_fidelity": {"score": 95},
        "fact_consistency": {"score": 100},
        "information_completeness": {"score": 90},
    }


@pytest.mark.asyncio
async def test_challenge_preserves_semantic_review_for_regular_baseline(tmp_path, monkeypatch):
    storage = ModelConfigStorage(str(tmp_path))
    storage.save_config({
        "eliminated_models": {"玄幻": ["qwen-plus"]},
        "evaluation_rounds_by_genre": {"玄幻": 5},
    })
    service = MultiModelEvaluationService.__new__(MultiModelEvaluationService)
    service.config_storage = storage

    async def evaluate(*args, **kwargs):
        return SingleModelResult(
            "qwen-plus", "Qwen", "p", "文本", 35, 1,
            fidelity_similarity=40, semantic_review=_semantic_review(),
            ai_ratio=0.30, original_ai_ratio=0.80,
        )

    monkeypatch.setattr(service, "_evaluate_single_model", evaluate)
    # 🔧 2026-10-17：准入守门改用确定AI占比降幅后，baseline 字典也必须带
    # ai_ratio / original_ai_ratio —— 否则 baseline 会被判不合格，
    # 挑战者自动「进入前三」而复活，本用例要守的语义（挑战者不该复活）就失真了。
    # 取真实量级：baseline 三个模型 ratio 0.30/0.20/0.10，原文均为 0.80。
    baseline = [
        {
            "model_id": f"m{index}", "model_name": f"M{index}", "provider": "p",
            "ai_score": score, "latency_seconds": 1, "fidelity_similarity": 40,
            "semantic_review": _semantic_review(), "hybrid_score": score,
            "ai_ratio": ratio, "original_ai_ratio": 0.80,
        }
        for index, (score, ratio) in enumerate(
            zip((10, 20, 30), (0.30, 0.20, 0.10)), start=1
        )
    ]

    result = await service.run_challenge_round(
        "原文", "提示词", genre="玄幻", baseline_results=baseline,
        original_ai_score=50,
    )

    assert result["revived"] == []
    assert storage.get_eliminated_models("玄幻") == ["qwen-plus"]


@pytest.mark.asyncio
async def test_failed_challenge_does_not_consume_challenge_cycle(tmp_path, monkeypatch):
    storage = ModelConfigStorage(str(tmp_path))
    storage.save_config({
        "eliminated_models": {"玄幻": ["qwen-plus"]},
        "evaluation_rounds_by_genre": {"玄幻": 5},
    })
    service = MultiModelEvaluationService.__new__(MultiModelEvaluationService)
    service.config_storage = storage

    async def fail(*args, **kwargs):
        return SingleModelResult(
            "qwen-plus", "Qwen", "p", "", 100, 1,
            success=False, error="timeout",
        )

    monkeypatch.setattr(service, "_evaluate_single_model", fail)
    await service.run_challenge_round(
        "原文", "提示词", genre="玄幻", original_ai_score=50,
    )

    assert storage.should_run_challenge("玄幻") is True


def test_combination_performance_is_isolated_by_genre_prompt_and_model(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    fantasy = SingleModelResult(
        "qwen-plus", "Qwen", "alibaba", "文本", 18, 1.2,
        improvement=42, fidelity_similarity=86,
        ai_ratio=0.30, original_ai_ratio=0.80,
    )
    urban = SingleModelResult(
        "qwen-plus", "Qwen", "alibaba", "文本", 35, 1.0,
        improvement=25, fidelity_similarity=92,
        ai_ratio=0.30, original_ai_ratio=0.80,
    )

    storage.update_combination_performance(fantasy, "玄幻", "prompt-v1", "玄幻提示词")
    storage.update_combination_performance(urban, "都市", "prompt-v1", "都市提示词")

    fantasy_record = storage.load_combination_performance("玄幻")["prompt-v1"]["qwen-plus"]
    urban_record = storage.load_combination_performance("都市")["prompt-v1"]["qwen-plus"]
    assert isinstance(fantasy_record, CombinationPerformanceRecord)
    assert fantasy_record.avg_ai_score == 18
    assert fantasy_record.avg_fidelity_similarity == 86
    assert fantasy_record.prompt_text == "玄幻提示词"
    assert urban_record.avg_ai_score == 35


def test_best_combination_excludes_results_below_fidelity_gate(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    low_ai_but_unfaithful = SingleModelResult(
        "qwen-plus", "Qwen", "alibaba", "文本", 5, 1,
        fidelity_similarity=40,
        ai_ratio=0.05, original_ai_ratio=0.80,
    )
    faithful = SingleModelResult(
        "deepseek-flash", "DeepSeek", "deepseek", "文本", 20, 1,
        fidelity_similarity=85, improvement=30,
        ai_ratio=0.30, original_ai_ratio=0.80,
    )
    storage.update_combination_performance(low_ai_but_unfaithful, "玄幻", "bad", "失真提示词")
    storage.update_combination_performance(faithful, "玄幻", "good", "保真提示词")

    best = storage.get_best_combination("玄幻", min_success=1, min_fidelity_similarity=70)

    assert best is not None
    assert best.prompt_version_id == "good"
    assert best.model_id == "deepseek-flash"


def test_model_result_with_failed_semantic_review_is_not_eligible():
    result = SingleModelResult(
        "m1", "M1", "p", "文本", 0, 1,
        fidelity_similarity=95,
        ai_ratio=0.30, original_ai_ratio=0.80,
        semantic_review={"available": True, "hard_fail": True},
    )

    assert ModelConfigStorage.is_eligible_result(result) is False


def test_semantic_review_allows_lower_lexical_fidelity_but_requires_low_risk():
    review = {
        "available": True,
        "hard_fail": False,
        "over_rewrite_risk": "low",
        "confidence": 0.95,
        "semantic_fidelity": {"score": 95},
        "fact_consistency": {"score": 100},
        "information_completeness": {"score": 92},
    }
    accepted = SingleModelResult(
        "m1", "M1", "p", "文本", 0, 1,
        fidelity_similarity=33, improvement=50,
        ai_ratio=0.30, original_ai_ratio=0.80,
        semantic_review=review,
    )
    medium_risk = SingleModelResult(
        "m2", "M2", "p", "文本", 0, 1,
        fidelity_similarity=45, improvement=50,
        ai_ratio=0.30, original_ai_ratio=0.80,
        semantic_review={**review, "over_rewrite_risk": "medium"},
    )
    no_review = SingleModelResult(
        "m3", "M3", "p", "文本", 0, 1,
        fidelity_similarity=45, improvement=50,
        ai_ratio=0.30, original_ai_ratio=0.80,
        semantic_review={"available": False},
    )

    assert ModelConfigStorage.is_eligible_result(accepted) is True
    assert ModelConfigStorage.is_eligible_result(medium_risk) is False
    assert ModelConfigStorage.is_eligible_result(no_review) is False


def test_unfaithful_result_does_not_enter_model_success_statistics(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    result = SingleModelResult(
        "qwen-plus", "Qwen", "alibaba", "文本", 3, 1,
        improvement=50, fidelity_similarity=45,
        ai_ratio=0.30, original_ai_ratio=0.80,
    )

    storage.update_performance(result, "玄幻")

    record = storage.load_performance("玄幻")["qwen-plus"]
    assert record.total_evaluations == 1
    assert record.total_success == 0
    assert record.avg_ai_score == 100


def test_best_model_for_selected_prompt_never_uses_another_prompt_version(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    for index in range(3):
        storage.update_combination_performance(
            SingleModelResult(
                "qwen-plus", "Qwen", "alibaba", "文本", 30, 1,
                fidelity_similarity=90, improvement=30,
                ai_ratio=0.30, original_ai_ratio=0.80,
            ),
            "玄幻", "approved", "已批准提示词", sample_hash=f"approved-{index}",
        )
        storage.update_combination_performance(
            SingleModelResult(
                "deepseek-flash", "DeepSeek", "deepseek", "文本", 5, 1,
                fidelity_similarity=90, improvement=55,
                ai_ratio=0.05, original_ai_ratio=0.80,
            ),
            "玄幻", "other", "其他提示词", sample_hash=f"other-{index}",
        )

    best = storage.get_best_model_for_prompt("玄幻", "已批准提示词")

    assert best is not None
    assert best.model_id == "qwen-plus"


def test_repeated_same_sample_does_not_mature_combination(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    result = SingleModelResult(
        "qwen-plus", "Qwen", "alibaba", "文本", 20, 1,
        fidelity_similarity=90, improvement=40,
        ai_ratio=0.30, original_ai_ratio=0.80,
    )
    for _ in range(5):
        storage.update_combination_performance(
            result, "玄幻", "prompt", "提示词", sample_hash="same-sample"
        )

    assert storage.get_best_model_for_prompt("玄幻", "提示词") is None


def test_prompt_selection_returns_stable_version_id_and_source(tmp_path):
    storage = EvolutionStorage(str(tmp_path))
    (tmp_path / "approved_prompts.json").write_text(
        json.dumps([
            {"version_id": "v-approved", "prompt_text": "批准提示词", "genre": "玄幻"}
        ], ensure_ascii=False), encoding="utf-8"
    )

    selection = storage.get_prompt_selection("玄幻")

    assert selection == {
        "version_id": "v-approved",
        "prompt_text": "批准提示词",
        "genre": "玄幻",
        "source": "genre_approved",
    }


def test_old_approved_prompt_genre_is_backfilled_from_evolution_history(tmp_path):
    storage = EvolutionStorage(str(tmp_path))
    (tmp_path / "approved_prompts.json").write_text(
        json.dumps([{
            "version_id": "old", "evolution_id": "e1", "prompt_text": "旧提示词"
        }], ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "evolution_history.json").write_text(
        json.dumps([{"evolution_id": "e1", "genre": "武侠"}], ensure_ascii=False),
        encoding="utf-8",
    )

    assert storage.get_prompt_selection("武侠")["version_id"] == "old"
    migrated = json.loads((tmp_path / "approved_prompts.json").read_text(encoding="utf-8"))
    assert migrated[0]["genre"] == "武侠"


def test_combination_tracks_variance_and_penalizes_uncertainty(tmp_path):
    """方差惩罚跟踪的是「确定AI段落占比」（排序主项）。

    2026-10-08 起排序主项由 avg_ai_score 改为 avg_ai_ratio：
    ai_score ≈ (确定AI + 疑似AI) × 100 在 LLM 改写区间恒为 100，
    对 10/30/50 这类取值现实中根本不会出现，用它算方差等于在噪声上做统计。
    """
    storage = ModelConfigStorage(str(tmp_path))
    for index, ratio in enumerate((0.1, 0.3, 0.5)):
        storage.update_combination_performance(
            SingleModelResult(
                "qwen-plus", "Qwen", "alibaba", "文本", 100, 1,
                fidelity_similarity=90, improvement=10, ai_ratio=ratio,
                original_ai_ratio=min(1.0, ratio + 0.5),
            ),
            "玄幻", "p1", "提示词", sample_hash=f"s{index}",
        )

    record = storage.load_combination_performance("玄幻")["p1"]["qwen-plus"]
    assert record.avg_ai_ratio == pytest.approx(0.3)
    assert record.ai_ratio_stddev > 0
    assert record.confidence_score > record.composite_score


def test_composite_score_is_driven_by_ai_ratio_not_ai_score(tmp_path):
    """回归防线：排序主项必须是 ai_ratio。

    历史事故：composite_score = avg_ai_score + 保真项，而 avg_ai_score 在改写区间
    恒为 100，导致 1005 条记录的排序等价于按常数排序，选不出真正有效的模型。
    """
    storage = ModelConfigStorage(str(tmp_path))
    # 两个模型 ai_score 完全相同（现实中的常态），只有 ai_ratio 有区别
    for model_id, ratio in (("model-good", 0.05), ("model-bad", 0.80)):
        storage.update_combination_performance(
            SingleModelResult(
                model_id, model_id, "p", "文本", 100, 1,
                fidelity_similarity=90, improvement=10, ai_ratio=ratio,
                original_ai_ratio=min(1.0, ratio + 0.5),
            ),
            "玄幻", "p1", "提示词", sample_hash="s1",
        )

    records = storage.load_combination_performance("玄幻")["p1"]
    good, bad = records["model-good"], records["model-bad"]
    assert good.avg_ai_score == bad.avg_ai_score == 100
    assert good.composite_score < bad.composite_score


def test_missing_ai_ratio_counts_as_worst(tmp_path):
    """检测未返回 ai_ratio 时按最差 1.0 计，避免检测异常被当成「降得很干净」而占便宜。"""
    storage = ModelConfigStorage(str(tmp_path))
    storage.update_combination_performance(
        SingleModelResult("m1", "M1", "p", "文本", 100, 1,
                          fidelity_similarity=90, improvement=10, ai_ratio=None,
                          original_ai_ratio=0.80),
        "玄幻", "p1", "提示词", sample_hash="s1",
    )
    record = storage.load_combination_performance("玄幻")["p1"]["m1"]
    assert record.avg_ai_ratio == pytest.approx(1.0)


def test_old_evaluation_policy_is_not_used_for_production_routing(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    result = SingleModelResult(
        "qwen-plus", "Qwen", "alibaba", "文本", 10, 1,
        fidelity_similarity=90, improvement=50,
        ai_ratio=0.30, original_ai_ratio=0.80,
    )
    for index in range(3):
        storage.update_combination_performance(
            result, "玄幻", "p1", "提示词", sample_hash=f"s{index}"
        )
    records = storage.load_combination_performance("玄幻")
    records["p1"]["qwen-plus"].evaluation_policy_version = "legacy-v1"
    storage.save_combination_performance(records, "玄幻")

    assert storage.get_best_model_for_prompt_version("玄幻", "p1") is None


# 模型池共 9 个；以下测试验证淘汰后至少保留 MIN_ALIVE_MODELS=4 个存活模型
_POOL = [
    "qwen-plus", "deepseek-flash", "doubao-seed-character", "kimi-preview",
    "glm", "minimax-m", "mimo-flash", "doubao-seed-evolving", "step-preview",
]


def test_elimination_keeps_at_least_six_alive_models(tmp_path):
    # 已淘汰 2 个（alive=7），两个模型超门槛，只允许淘汰最差的一个保留到 6（地板已放宽到 6）
    storage = ModelConfigStorage(str(tmp_path))
    storage.save_config({"eliminated_models": {"玄幻": _POOL[1:3]}})
    storage.save_performance(
        {
            "qwen-plus": _mature_record("qwen-plus", 10),
            "mimo-flash": _mature_record("mimo-flash", 50),
            "step-preview": _mature_record("step-preview", 60),
        },
        "玄幻",
    )

    assert storage.evaluate_elimination("玄幻") == ["step-preview"]
    assert len(storage.get_active_models("玄幻")) == 6


def test_elimination_blocked_when_alive_already_at_floor(tmp_path):
    # 已淘汰 5 个（alive=4 到底），即使有模型超门槛也不再淘汰
    storage = ModelConfigStorage(str(tmp_path))
    storage.save_config({"eliminated_models": {"玄幻": _POOL[1:6]}})
    storage.save_performance(
        {
            "qwen-plus": _mature_record("qwen-plus", 10),
            "step-preview": _mature_record("step-preview", 60),
        },
        "玄幻",
    )

    assert storage.evaluate_elimination("玄幻") == []
    assert len(storage.get_active_models("玄幻")) == 4


def _failed_result(model_id: str) -> SingleModelResult:
    return SingleModelResult(
        model_id, model_id, "test", "", 0, 0.0, success=False, error="timeout"
    )


def test_availability_circuit_breaker_respects_alive_floor(tmp_path):
    # 存活只剩 4 个时，连续失败熔断不得再淘汰（避免可用模型池见底）
    floor_storage = ModelConfigStorage(str(tmp_path / "floor"))
    floor_storage.save_config({"eliminated_models": {"玄幻": _POOL[1:6]}})
    for _ in range(3):
        floor_storage.update_availability_status(_failed_result("qwen-plus"), "玄幻")
    assert "qwen-plus" not in floor_storage.get_eliminated_models("玄幻")

    # 存活 7 个（高于地板 6）时熔断照常生效
    ok_storage = ModelConfigStorage(str(tmp_path / "ok"))
    ok_storage.save_config({"eliminated_models": {"玄幻": _POOL[1:3]}})
    for _ in range(3):
        ok_storage.update_availability_status(_failed_result("qwen-plus"), "玄幻")
    assert "qwen-plus" in ok_storage.get_eliminated_models("玄幻")
