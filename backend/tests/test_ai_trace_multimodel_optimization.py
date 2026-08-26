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
    storage.save_config({"eliminated_models": {"玄幻": ["qwen3.7-plus"]}})

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
    storage.save_config({"eliminated_models": {"玄幻": ["qwen3.7-plus"]}})
    storage.save_performance(
        {
            "qwen3.7-plus": ModelPerformanceRecord(
                model_id="qwen3.7-plus",
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
        model_id="qwen3.7-plus",
        model_name="Qwen",
        provider="alibaba",
        reduced_text="文本",
        ai_score=20,
        latency_seconds=1.5,
        improvement=40,
    )
    competitors = [
        challenge,
        SingleModelResult("m1", "M1", "p", "文本", 10, 1, improvement=40),
        SingleModelResult("m2", "M2", "p", "文本", 30, 1, improvement=20),
        SingleModelResult("m3", "M3", "p", "文本", 40, 1, improvement=10),
    ]

    revived = storage.process_challenge_results("玄幻", [challenge], competitors)

    record = storage.load_performance("玄幻")["qwen3.7-plus"]
    assert revived == ["qwen3.7-plus"]
    assert record.total_evaluations == 1
    assert record.total_success == 1
    assert record.avg_ai_score == 20
    assert record.avg_improvement == 40


def _mature_record(model_id: str, score: float) -> ModelPerformanceRecord:
    return ModelPerformanceRecord(
        model_id=model_id,
        model_name=model_id,
        provider="test",
        total_evaluations=5,
        total_success=5,
        avg_ai_score=score,
    )


def test_elimination_starts_when_two_models_are_mature_and_uses_strict_gap(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    storage.save_performance(
        {
            "qwen3.7-plus": _mature_record("qwen3.7-plus", 10),
            "deepseek-v4-flash": _mature_record("deepseek-v4-flash", 31),
        },
        "玄幻",
    )

    assert storage.evaluate_elimination("玄幻") == ["deepseek-v4-flash"]

    boundary_storage = ModelConfigStorage(str(tmp_path / "boundary"))
    boundary_storage.save_performance(
        {
            "qwen3.7-plus": _mature_record("qwen3.7-plus", 10),
            "deepseek-v4-flash": _mature_record("deepseek-v4-flash", 30),
        },
        "玄幻",
    )
    assert boundary_storage.evaluate_elimination("玄幻") == []


def test_challenge_selects_only_one_eliminated_model(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    storage.save_config({
        "eliminated_models": {
            "玄幻": ["qwen3.7-plus", "deepseek-v4-flash"]
        }
    })

    assert len(storage.get_challenge_candidates("玄幻")) == 1


def test_evolving_model_has_fast_non_thinking_evaluation_policy():
    service = MultiModelEvaluationService
    policy = service.get_model_evaluation_policy("doubao-seed-evolving")

    assert policy["timeout"] == 90
    assert policy["max_tokens"] == 4096
    assert policy["extra_body"] == {"thinking": {"type": "disabled"}}
    assert service.get_model_evaluation_policy("qwen3.7-plus")["timeout"] == service.SINGLE_MODEL_TIMEOUT


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
        success=True,
    )
    storage.update_availability_status(failed, "玄幻")
    storage.update_availability_status(success, "玄幻")

    assert storage.load_config().get("availability_failures", {}).get("玄幻", {}).get("doubao-seed-evolving", 0) == 0


def test_challenger_revives_only_when_ranked_in_top_three(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    storage.save_config({"eliminated_models": {"玄幻": ["qwen3.7-plus"]}})
    third = SingleModelResult("qwen3.7-plus", "Qwen", "p", "文本", 30, 1, improvement=20)
    results = [
        SingleModelResult("m1", "M1", "p", "文本", 10, 1, improvement=40),
        SingleModelResult("m2", "M2", "p", "文本", 20, 1, improvement=30),
        third,
        SingleModelResult("m3", "M3", "p", "文本", 40, 1, improvement=10),
    ]
    assert storage.process_challenge_results("玄幻", [third], results) == ["qwen3.7-plus"]

    storage.save_config({"eliminated_models": {"玄幻": ["qwen3.7-plus"]}})
    fourth = SingleModelResult("qwen3.7-plus", "Qwen", "p", "文本", 35, 1, improvement=15)
    results = [
        SingleModelResult("m1", "M1", "p", "文本", 10, 1, improvement=40),
        SingleModelResult("m2", "M2", "p", "文本", 20, 1, improvement=30),
        SingleModelResult("m3", "M3", "p", "文本", 30, 1, improvement=20),
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
        "eliminated_models": {"玄幻": ["qwen3.7-plus"]},
        "evaluation_rounds_by_genre": {"玄幻": 5},
    })
    service = MultiModelEvaluationService.__new__(MultiModelEvaluationService)
    service.config_storage = storage

    async def evaluate(*args, **kwargs):
        return SingleModelResult(
            "qwen3.7-plus", "Qwen", "p", "文本", 35, 1,
            fidelity_similarity=40, semantic_review=_semantic_review(),
        )

    monkeypatch.setattr(service, "_evaluate_single_model", evaluate)
    baseline = [
        {
            "model_id": f"m{index}", "model_name": f"M{index}", "provider": "p",
            "ai_score": score, "latency_seconds": 1, "fidelity_similarity": 40,
            "semantic_review": _semantic_review(), "hybrid_score": score,
        }
        for index, score in enumerate((10, 20, 30), start=1)
    ]

    result = await service.run_challenge_round(
        "原文", "提示词", genre="玄幻", baseline_results=baseline,
        original_ai_score=50,
    )

    assert result["revived"] == []
    assert storage.get_eliminated_models("玄幻") == ["qwen3.7-plus"]


@pytest.mark.asyncio
async def test_failed_challenge_does_not_consume_challenge_cycle(tmp_path, monkeypatch):
    storage = ModelConfigStorage(str(tmp_path))
    storage.save_config({
        "eliminated_models": {"玄幻": ["qwen3.7-plus"]},
        "evaluation_rounds_by_genre": {"玄幻": 5},
    })
    service = MultiModelEvaluationService.__new__(MultiModelEvaluationService)
    service.config_storage = storage

    async def fail(*args, **kwargs):
        return SingleModelResult(
            "qwen3.7-plus", "Qwen", "p", "", 100, 1,
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
        "qwen3.7-plus", "Qwen", "alibaba", "文本", 18, 1.2,
        improvement=42, fidelity_similarity=86,
    )
    urban = SingleModelResult(
        "qwen3.7-plus", "Qwen", "alibaba", "文本", 35, 1.0,
        improvement=25, fidelity_similarity=92,
    )

    storage.update_combination_performance(fantasy, "玄幻", "prompt-v1", "玄幻提示词")
    storage.update_combination_performance(urban, "都市", "prompt-v1", "都市提示词")

    fantasy_record = storage.load_combination_performance("玄幻")["prompt-v1"]["qwen3.7-plus"]
    urban_record = storage.load_combination_performance("都市")["prompt-v1"]["qwen3.7-plus"]
    assert isinstance(fantasy_record, CombinationPerformanceRecord)
    assert fantasy_record.avg_ai_score == 18
    assert fantasy_record.avg_fidelity_similarity == 86
    assert fantasy_record.prompt_text == "玄幻提示词"
    assert urban_record.avg_ai_score == 35


def test_best_combination_excludes_results_below_fidelity_gate(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    low_ai_but_unfaithful = SingleModelResult(
        "qwen3.7-plus", "Qwen", "alibaba", "文本", 5, 1,
        fidelity_similarity=40,
    )
    faithful = SingleModelResult(
        "deepseek-v4-flash", "DeepSeek", "deepseek", "文本", 20, 1,
        fidelity_similarity=85, improvement=30,
    )
    storage.update_combination_performance(low_ai_but_unfaithful, "玄幻", "bad", "失真提示词")
    storage.update_combination_performance(faithful, "玄幻", "good", "保真提示词")

    best = storage.get_best_combination("玄幻", min_success=1, min_fidelity_similarity=70)

    assert best is not None
    assert best.prompt_version_id == "good"
    assert best.model_id == "deepseek-v4-flash"


def test_model_result_with_failed_semantic_review_is_not_eligible():
    result = SingleModelResult(
        "m1", "M1", "p", "文本", 0, 1,
        fidelity_similarity=95,
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
        semantic_review=review,
    )
    medium_risk = SingleModelResult(
        "m2", "M2", "p", "文本", 0, 1,
        fidelity_similarity=45, improvement=50,
        semantic_review={**review, "over_rewrite_risk": "medium"},
    )
    no_review = SingleModelResult(
        "m3", "M3", "p", "文本", 0, 1,
        fidelity_similarity=45, improvement=50,
        semantic_review={"available": False},
    )

    assert ModelConfigStorage.is_eligible_result(accepted) is True
    assert ModelConfigStorage.is_eligible_result(medium_risk) is False
    assert ModelConfigStorage.is_eligible_result(no_review) is False


def test_unfaithful_result_does_not_enter_model_success_statistics(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    result = SingleModelResult(
        "qwen3.7-plus", "Qwen", "alibaba", "文本", 3, 1,
        improvement=50, fidelity_similarity=45,
    )

    storage.update_performance(result, "玄幻")

    record = storage.load_performance("玄幻")["qwen3.7-plus"]
    assert record.total_evaluations == 1
    assert record.total_success == 0
    assert record.avg_ai_score == 100


def test_best_model_for_selected_prompt_never_uses_another_prompt_version(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    for index in range(3):
        storage.update_combination_performance(
            SingleModelResult(
                "qwen3.7-plus", "Qwen", "alibaba", "文本", 30, 1,
                fidelity_similarity=90, improvement=30,
            ),
            "玄幻", "approved", "已批准提示词", sample_hash=f"approved-{index}",
        )
        storage.update_combination_performance(
            SingleModelResult(
                "deepseek-v4-flash", "DeepSeek", "deepseek", "文本", 5, 1,
                fidelity_similarity=90, improvement=55,
            ),
            "玄幻", "other", "其他提示词", sample_hash=f"other-{index}",
        )

    best = storage.get_best_model_for_prompt("玄幻", "已批准提示词")

    assert best is not None
    assert best.model_id == "qwen3.7-plus"


def test_repeated_same_sample_does_not_mature_combination(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    result = SingleModelResult(
        "qwen3.7-plus", "Qwen", "alibaba", "文本", 20, 1,
        fidelity_similarity=90, improvement=40,
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
    storage = ModelConfigStorage(str(tmp_path))
    for index, score in enumerate((10, 30, 50)):
        storage.update_combination_performance(
            SingleModelResult(
                "qwen3.7-plus", "Qwen", "alibaba", "文本", score, 1,
                fidelity_similarity=90, improvement=60 - score,
            ),
            "玄幻", "p1", "提示词", sample_hash=f"s{index}",
        )

    record = storage.load_combination_performance("玄幻")["p1"]["qwen3.7-plus"]
    assert record.ai_score_stddev > 0
    assert record.confidence_score > record.composite_score


def test_old_evaluation_policy_is_not_used_for_production_routing(tmp_path):
    storage = ModelConfigStorage(str(tmp_path))
    result = SingleModelResult(
        "qwen3.7-plus", "Qwen", "alibaba", "文本", 10, 1,
        fidelity_similarity=90, improvement=50,
    )
    for index in range(3):
        storage.update_combination_performance(
            result, "玄幻", "p1", "提示词", sample_hash=f"s{index}"
        )
    records = storage.load_combination_performance("玄幻")
    records["p1"]["qwen3.7-plus"].evaluation_policy_version = "legacy-v1"
    storage.save_combination_performance(records, "玄幻")

    assert storage.get_best_model_for_prompt_version("玄幻", "p1") is None


# 模型池共 9 个；以下测试验证淘汰后至少保留 MIN_ALIVE_MODELS=4 个存活模型
_POOL = [
    "qwen3.7-plus", "deepseek-v4-flash", "doubao-seed-character", "kimi/kimi-k2.6",
    "glm-5.2", "MiniMax/MiniMax-M3", "mimo-v2.5", "doubao-seed-evolving", "step-3.7-flash",
]


def test_elimination_keeps_at_least_six_alive_models(tmp_path):
    # 已淘汰 2 个（alive=7），两个模型超门槛，只允许淘汰最差的一个保留到 6（地板已放宽到 6）
    storage = ModelConfigStorage(str(tmp_path))
    storage.save_config({"eliminated_models": {"玄幻": _POOL[1:3]}})
    storage.save_performance(
        {
            "qwen3.7-plus": _mature_record("qwen3.7-plus", 10),
            "mimo-v2.5": _mature_record("mimo-v2.5", 50),
            "step-3.7-flash": _mature_record("step-3.7-flash", 60),
        },
        "玄幻",
    )

    assert storage.evaluate_elimination("玄幻") == ["step-3.7-flash"]
    assert len(storage.get_active_models("玄幻")) == 6


def test_elimination_blocked_when_alive_already_at_floor(tmp_path):
    # 已淘汰 5 个（alive=4 到底），即使有模型超门槛也不再淘汰
    storage = ModelConfigStorage(str(tmp_path))
    storage.save_config({"eliminated_models": {"玄幻": _POOL[1:6]}})
    storage.save_performance(
        {
            "qwen3.7-plus": _mature_record("qwen3.7-plus", 10),
            "step-3.7-flash": _mature_record("step-3.7-flash", 60),
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
        floor_storage.update_availability_status(_failed_result("qwen3.7-plus"), "玄幻")
    assert "qwen3.7-plus" not in floor_storage.get_eliminated_models("玄幻")

    # 存活 7 个（高于地板 6）时熔断照常生效
    ok_storage = ModelConfigStorage(str(tmp_path / "ok"))
    ok_storage.save_config({"eliminated_models": {"玄幻": _POOL[1:3]}})
    for _ in range(3):
        ok_storage.update_availability_status(_failed_result("qwen3.7-plus"), "玄幻")
    assert "qwen3.7-plus" in ok_storage.get_eliminated_models("玄幻")
