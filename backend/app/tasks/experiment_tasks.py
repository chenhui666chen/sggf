# -*- coding: utf-8 -*-
"""
shadow 实验 Celery 薄壳（设计文档 §5.2 / §14 第 6 步子块 B-2）

职责仅限「装配真实供应商依赖 + 提供 beat 轮询入口」，全部编排逻辑在
services/prompt_evolution/shadow_executor.py（sqlite + 假函数已充分测试）。

- rewrite_fn：PromptEvaluator._rewrite_text（按实验行冻结契约的 resolved_model_id 改写）；
- detect_fn：腾讯 AI 检测（返回 ai_score，失败/不可用返回 None → infrastructure_failure）；
- review_fn：SemanticJudge 语义评审，输出展平为 review_verdict 期望的扁平键。

Celery solo 池为同步执行，异步调用统一经 asyncio.run 桥接（同 audiobook_tasks._run_async）。
EXPERIMENT_ENABLED 未开启时直接空转返回，不认领、不建会话开销最小。
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """从同步 Celery 任务体执行协程。"""
    return asyncio.run(coro)


def _flatten_review(review: Mapping[str, Any]) -> dict:
    """
    SemanticJudge 嵌套维度输出 → review_verdict 期望的扁平键。
    不可用评审原样透传 available=False，由 review_verdict 判为 infrastructure_failure。
    """
    if not review.get("available", False):
        return {"available": False}

    def _score(name: str) -> float:
        dim = review.get(name)
        if isinstance(dim, Mapping):
            return float(dim.get("score", 0.0))
        return 0.0

    return {
        "available": True,
        "hard_fail": bool(review.get("hard_fail", False)),
        "fidelity": _score("semantic_fidelity"),
        "fact": _score("fact_consistency"),
        "completeness": _score("information_completeness"),
        "over_rewrite_risk": str(review.get("over_rewrite_risk", "medium")),
        "confidence": float(review.get("confidence", 0.0)),
    }


def _build_deps():
    """装配执行期真实依赖（延迟导入，避免 worker 启动即加载重模块）。"""
    from app.services.prompt_evolution.returnable_service import (
        parse_ai_threshold,
        parse_max_attempts,
    )

    # 配置校验前置于重模块导入之前 fast-fail（八轮评审① / 九轮评审）：AI 硬门槛与
    # returnable 共用 parse_ai_threshold，杜绝裸解析放行 nan/inf/负值/越界或 max_attempts<1
    ai_threshold = parse_ai_threshold()
    max_attempts = parse_max_attempts()

    from app.services.prompt_evolution.evaluator import PromptEvaluator
    from app.services.prompt_evolution.shadow_dispatch import ShadowDispatchConfig
    from app.services.prompt_evolution.shadow_executor import ShadowExecutionDeps
    from app.services.zhuque_ai_detect import zhuque_ai_detect_service

    evaluator = PromptEvaluator()
    config = ShadowDispatchConfig.from_env()

    def rewrite_fn(prompt_text: str, original_text: str, model_id: Optional[str]) -> str:
        return _run_async(
            evaluator._rewrite_text(prompt_text, original_text, temperature=0.8, model_id=model_id)
        )

    def detect_fn(text: str) -> Optional[float]:
        result = _run_async(zhuque_ai_detect_service.detect_ai_content(text))
        if not result.get("success"):
            return None
        return float(result.get("ai_score", 0.0))

    def review_fn(original: str, rewritten: str, genre: str) -> dict:
        review = _run_async(evaluator.semantic_judge.evaluate(original, rewritten, genre))
        return _flatten_review(review)

    return ShadowExecutionDeps(
        rewrite_fn=rewrite_fn,
        detect_fn=detect_fn,
        review_fn=review_fn,
        vault=None,  # 实际 vault 在任务体内按 EXPERIMENT_PAYLOAD_KEY 构造并注入
        estimated_cost=config.estimated_cost,
        ai_threshold=ai_threshold,
        max_attempts=max_attempts,
    ), config


@celery_app.task(
    name="prompt_experiment.run_shadow_batch",
    bind=True,
    max_retries=0,
)
def run_shadow_batch_task(self, limit: int = 5, lease_seconds: int = 600) -> dict:
    """
    beat 轮询入口：认领并执行至多 limit 个 pending shadow 实验。
    单次批处理故障不重试（下一轮 beat 自然重扫，租约到期任务自动可再认领）。
    """
    if os.getenv("EXPERIMENT_ENABLED", "false").lower() != "true":
        return {"skipped": "disabled"}

    import dataclasses

    from app.db.base import SessionLocal
    from app.services.prompt_evolution.experiment_privacy import PayloadVault
    from app.services.prompt_evolution.shadow_executor import run_shadow_batch

    deps, config = _build_deps()
    if not config.payload_key:
        return {"skipped": "missing_payload_key"}
    deps = dataclasses.replace(deps, vault=PayloadVault(config.payload_key))

    db = SessionLocal()
    try:
        stats = run_shadow_batch(
            db, deps, now=datetime.now(timezone.utc), limit=limit, lease_seconds=lease_seconds
        )
        logger.info("shadow 批处理任务完成: %s", stats)
        return stats
    except Exception as exc:  # noqa: BLE001 —— 批处理级兜底，下一轮 beat 重扫
        logger.error("shadow 批处理任务异常: %s", type(exc).__name__)
        return {"error": type(exc).__name__}
    finally:
        db.close()


@celery_app.task(
    name="prompt_experiment.run_calibration",
    bind=True,
    max_retries=0,
)
def run_calibration_task(self) -> dict:
    """
    beat 轮询入口（§14 第 7 步）：按当前评审策略版本窗口重算四层校准，
    把四层全过且仍处 shadow 的挑战者推进到 eligible（待人工批准）。
    纯 DB 计算，不调外部供应商；EXPERIMENT_ENABLED 未开启时空转。
    """
    if os.getenv("EXPERIMENT_ENABLED", "false").lower() != "true":
        return {"skipped": "disabled"}

    from app.db.base import SessionLocal
    from app.services.prompt_evolution.experiment_contract import (
        EXPERIMENT_EVALUATION_POLICY_VERSION,
    )
    from app.services.prompt_evolution.layered_calibration import (
        CalibrationThresholds,
        promote_calibrated_challengers,
    )

    db = SessionLocal()
    try:
        result = promote_calibrated_challengers(
            db,
            thresholds=CalibrationThresholds.from_env(),
            evaluation_policy_version=EXPERIMENT_EVALUATION_POLICY_VERSION,
        )
        logger.info("四层校准任务完成: %s", result)
        return result
    except Exception as exc:  # noqa: BLE001 —— 批处理级兜底，下一轮 beat 重扫
        logger.error("四层校准任务异常: %s", type(exc).__name__)
        return {"error": type(exc).__name__}
    finally:
        db.close()


# 进化启停调度覆盖的题材：契约模块单一来源（与 API 面板共用，新增题材只改契约模块）
from app.services.prompt_evolution.experiment_contract import (
    EVOLUTION_GENRES as _SCHEDULER_GENRES,
)


@celery_app.task(
    name="prompt_experiment.run_holdout_eval",
    bind=True,
    max_retries=0,
)
def run_holdout_eval_task(self) -> dict:
    """
    beat 低频入口（§11.1 信号 2 holdout 分差）：逐题材对当前冠军做训练/留出新鲜复评，
    分差写入 holdout_scores.json 缓存供调度 tick 只读消费。

    纯 JSON + 外部评分 API，不碰 DB 不建会话；冠军与 policy 均未变时逐题材跳过重算
    （成本控制）；EXPERIMENT_ENABLED 未开启时空转。单题材失败不中断其余题材。
    """
    if os.getenv("EXPERIMENT_ENABLED", "false").lower() != "true":
        return {"skipped": "disabled"}

    from app.services.prompt_evolution.evaluator import PromptEvaluator
    from app.services.prompt_evolution.experiment_contract import (
        EXPERIMENT_EVALUATION_POLICY_VERSION,
    )
    from app.services.prompt_evolution.holdout_probe import (
        HoldoutScoreStore,
        evaluate_holdout_gap,
    )
    from app.services.prompt_evolution.storage import get_evolution_storage
    from app.services.prompt_evolution.test_samples import get_sample_manager

    evaluator = PromptEvaluator()
    sample_manager = get_sample_manager()
    sample_manager.apply_holdout_split()
    store = HoldoutScoreStore()
    storage = get_evolution_storage()

    results: dict = {}
    for genre in _SCHEDULER_GENRES:
        try:
            results[genre] = _run_async(
                evaluate_holdout_gap(
                    genre,
                    evaluator=evaluator,
                    sample_manager=sample_manager,
                    storage=storage,
                    store=store,
                    policy=EXPERIMENT_EVALUATION_POLICY_VERSION,
                )
            )
        except Exception as exc:  # noqa: BLE001 —— 单题材兜底，下一轮 beat 重试
            logger.error("holdout 复评异常: genre=%s %s", genre, type(exc).__name__)
            results[genre] = {"status": "error", "error": type(exc).__name__}
    logger.info("holdout 复评任务完成: %s", results)
    return results


@celery_app.task(
    name="prompt_experiment.run_sentinel_probe",
    bind=True,
    max_retries=0,
)
def run_sentinel_probe_task(self) -> dict:
    """
    beat 低频入口（§11.2 信号 5 哨兵巡检）：对处于 sleeping 状态的题材用固定哨兵语料
    （holdout 留出子集）对当前冠军做新鲜 AI 检测，退化标志写入 sentinel_state.json
    缓存供调度 tick 只读消费唤醒。

    成本控制：唤醒信号只在 sleeping 期被消费，非 sleeping 题材直接跳过不调外部评分。
    纯 JSON + 外部评分 API，不碰 DB 不建会话；EXPERIMENT_ENABLED 未开启时空转；
    单题材失败不中断其余题材。退化判定复用 SchedulerThresholds.wake_ai_score_rise
    现有唤醒阈值口径，不新增阈值。
    """
    if os.getenv("EXPERIMENT_ENABLED", "false").lower() != "true":
        return {"skipped": "disabled"}

    from app.services.prompt_evolution.evaluator import PromptEvaluator
    from app.services.prompt_evolution.evolution_scheduler import (
        STATE_SLEEPING,
        SchedulerThresholds,
    )
    from app.services.prompt_evolution.experiment_contract import (
        EXPERIMENT_EVALUATION_POLICY_VERSION,
    )
    from app.services.prompt_evolution.scheduler_state import SchedulerStateStore
    from app.services.prompt_evolution.sentinel_probe import (
        SentinelStateStore,
        run_sentinel_probe_for_genre,
    )
    from app.services.prompt_evolution.storage import get_evolution_storage
    from app.services.prompt_evolution.test_samples import get_sample_manager

    evaluator = PromptEvaluator()
    sample_manager = get_sample_manager()
    sample_manager.apply_holdout_split()
    store = SentinelStateStore()
    storage = get_evolution_storage()
    state_store = SchedulerStateStore()
    wake_ai_score_rise = SchedulerThresholds.from_env().wake_ai_score_rise

    results: dict = {}
    for genre in _SCHEDULER_GENRES:
        if state_store.get(genre).state != STATE_SLEEPING:
            results[genre] = {"status": "skipped_not_sleeping"}
            continue
        try:
            results[genre] = _run_async(
                run_sentinel_probe_for_genre(
                    genre,
                    evaluator=evaluator,
                    sample_manager=sample_manager,
                    storage=storage,
                    store=store,
                    policy=EXPERIMENT_EVALUATION_POLICY_VERSION,
                    wake_ai_score_rise=wake_ai_score_rise,
                )
            )
        except Exception as exc:  # noqa: BLE001 —— 单题材兜底，下一轮 beat 重试
            logger.error("哨兵探测异常: genre=%s %s", genre, type(exc).__name__)
            results[genre] = {"status": "error", "error": type(exc).__name__}
    logger.info("哨兵巡检任务完成: %s", results)
    return results


@celery_app.task(
    name="prompt_experiment.run_scheduler_tick",
    bind=True,
    max_retries=0,
)
def run_scheduler_tick_task(self) -> dict:
    """
    beat 轮询入口（§14 第 10 步 · 子块 B）：逐题材采集启停信号，按三态决策转移并落盘。

    纯 DB + 本地状态账本计算，不调外部供应商；EXPERIMENT_ENABLED 未开启时空转。
    全部启停信号均已接入数据源：预算触顶 / 跨批次提升 / 综合分达标 / 冠军保真下降 /
    冠军 AI 率回升 / 挑战者反超 / 环境变更〔入眠指纹快照对比〕/ holdout 分差〔读
    run_holdout_eval 低频缓存〕/ 哨兵巡检〔读 run_sentinel_probe 低频缓存〕。
    """
    if os.getenv("EXPERIMENT_ENABLED", "false").lower() != "true":
        return {"skipped": "disabled"}

    from app.db.base import SessionLocal
    from app.services.prompt_evolution.budget_ledger import BudgetLedger
    from app.services.prompt_evolution.experiment_contract import (
        EXPERIMENT_EVALUATION_POLICY_VERSION,
        LIGHT_JUDGE_VERSION,
    )
    from app.services.prompt_evolution.holdout_probe import HoldoutScoreStore
    from app.services.prompt_evolution.scheduler_orchestration import (
        SchedulerTickDeps,
        run_scheduler_tick,
    )
    from app.services.prompt_evolution.scheduler_state import SchedulerStateStore
    from app.services.prompt_evolution.sentinel_probe import SentinelStateStore
    from app.services.prompt_evolution.storage import get_evolution_storage

    now = datetime.now(timezone.utc)
    budget_date = now.strftime("%Y-%m-%d")

    # 环境版本指纹（§11.2 信号 4）：仅纳入任务层稳定可得、实质变化即使达标结论失效的
    # 版本常量（评审策略版本 / 轻判器版本）。无稳定模块级来源的 model_catalog_version
    # 不纳入（宁缺毋臆造）。逐题材共用同一指纹（当前版本体系不按题材分化）。
    env_fingerprint = {
        "evaluation_policy_version": EXPERIMENT_EVALUATION_POLICY_VERSION,
        "light_judge_version": LIGHT_JUDGE_VERSION,
    }
    # holdout 分差缓存（§11.1 信号 2）：run_holdout_eval 低频写、tick 只读；
    # 无缓存/policy 不一致由 get_gap 内部降级为 0.0 中性。
    holdout_store = HoldoutScoreStore()
    # 哨兵退化缓存（§11.2 信号 5）：run_sentinel_probe 低频写、tick 只读；
    # 无缓存/policy 不一致由 is_degraded 内部降级为 False（不误唤醒）。
    sentinel_store = SentinelStateStore()

    db = SessionLocal()
    try:
        ledger = BudgetLedger(db)

        deps = SchedulerTickDeps(
            list_history_summaries=lambda: get_evolution_storage().list_evolution_histories(),
            # 周期进化费用按 (日期 × 题材) 维度查触顶；无账本行视为未设限（不误休眠）
            is_budget_exhausted=lambda genre: ledger.is_exhausted(
                budget_date, "evolution_genre", genre
            ),
            env_fingerprint=lambda genre: dict(env_fingerprint),
            holdout_score_gap=lambda genre: holdout_store.get_gap(
                genre, policy=EXPERIMENT_EVALUATION_POLICY_VERSION
            ),
            sentinel_degraded=lambda genre: sentinel_store.is_degraded(
                genre, policy=EXPERIMENT_EVALUATION_POLICY_VERSION
            ),
        )

        result = run_scheduler_tick(
            db,
            _SCHEDULER_GENRES,
            deps=deps,
            state_store=SchedulerStateStore(),
            policy=EXPERIMENT_EVALUATION_POLICY_VERSION,
            now=now.isoformat(),
        )
        logger.info("进化启停调度 tick 完成: %s", result)
        return result
    except Exception as exc:  # noqa: BLE001 —— 批处理级兜底，下一轮 beat 重扫
        logger.error("进化启停调度 tick 异常: %s", type(exc).__name__)
        return {"error": type(exc).__name__}
    finally:
        db.close()

