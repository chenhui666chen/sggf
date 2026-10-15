# -*- coding: utf-8 -*-
"""任务编排服务：幂等提交、故障切换、慢任务对冲、状态一致性。

设计要点（docs/VIDEO_API_SMART_ROUTING_GUIDE.md §5）：
- 提交结果"未知"不等于失败：幂等供应商用同键重放，非幂等供应商记 unknown，
  切换备份时显式记录双扣风险；
- 先通过验收的成片成为唯一交付，晚到的成功/失败如实记账但不覆盖交付物；
- 超过截止时间停止等待，活动中的上游尝试保留以便后台对账，不伪造失败；
- 状态未知（无响应）不进路线成功率滚动窗口，避免少量超时误伤熔断。
"""
from __future__ import annotations

import logging
import math
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional, Protocol

from ..adapters.base import (AssetRef, NormalizedResult, RetriableTransportError,
                             SubmitRequest)
from ..assets import AssetInput, AssetRegistrationError
from ..assets.safe_fetch import SafeFetchError, validate_public_url
from ..catalog import Mode, VideoSpec
from ..catalog.intent import resolve_mode
from ..router import RankedRoute, rank_candidates
from ..stats import RouteStats
from .policy import (
    ACTIVE_ATTEMPT,
    DELIVERY_PENDING_ATTEMPT,
    DISPATCHING_ATTEMPT,
    OCCUPIED_ATTEMPT,
    TERMINAL_JOB,
    deadline_remaining,
    hedge_due,
    select_failover_route,
    select_hedge_route,
)


logger = logging.getLogger("router_gateway.orchestrator")


def _default_content_validator(url: str, raw: dict) -> bool:
    if not url:
        return False
    try:
        validate_public_url(url, resolve_dns=False)
    except SafeFetchError:
        return False
    return True


class OrchestratorError(Exception):
    pass


@dataclass(frozen=True)
class ContentRiskDecision:
    """提交前内容违规风险评分：score 为 0.0-1.0 的违规概率。"""
    score: float
    reason: Optional[str] = None


class ContentRiskScorer(Protocol):
    """提交前内容违规风险评分端口（见 docs 路由指南 §7.3）。

    只允许结构化决策模型接入；生产与预发中不可用时拒绝新任务。
    """

    def score_risk(self, prompt: str) -> ContentRiskDecision:
        ...


_PHASE_MAP = {"queued": "queued", "pending": "queued", "submitted": "submitted",
              "running": "running", "in_progress": "running", "processing": "running"}


def _asset_filename(public_url: str) -> str:
    """从 OSS 公网 URL 路径推导文件名（登记层据此识别扩展名/Content-Type）。"""
    path = urllib.parse.unquote(urllib.parse.urlsplit(public_url).path)
    name = path.rsplit("/", 1)[-1]
    return name or "asset"


@dataclass(frozen=True)
class AttemptView:
    id: int
    seq: int
    route_id: str
    provider: str
    status: str
    reason: Optional[str]
    is_hedge: bool
    upstream_task_id: Optional[str]
    content_url: Optional[str]
    cost: object
    error: Optional[dict]


@dataclass(frozen=True)
class JobView:
    id: str
    status: str
    semantic_error: Optional[str]
    quality_group: Optional[str]
    content_url: Optional[str]
    error: Optional[dict]
    attempts: tuple[AttemptView, ...]


class Orchestrator:
    def __init__(self, *, repo, routes: list, adapters: dict,
                 clock: Optional[Callable[[], datetime]] = None,
                 fallback_hedge_seconds: int = 300,
                 max_parallel_attempts: int = 2,
                 content_validator: Optional[Callable[[str, dict], bool]] = None,
                 on_job_terminal: Optional[Callable[[object], None]] = None,
                 intent_classifier: Optional[object] = None,
                 intent_confidence_threshold: float = 0.6,
                 content_risk_scorer: Optional[ContentRiskScorer] = None,
                 content_risk_threshold: float = 0.9,
                 content_risk_fail_closed: bool = False,
                 asset_registrar: Optional[object] = None,
                 deliverer: Optional[object] = None,
                 dispatch_grace_seconds: int = 90,
                 max_attempts: int = 3):
        self._repo = repo
        self._routes = routes
        self._adapters = adapters
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._fallback_hedge_seconds = fallback_hedge_seconds
        self._max_parallel = max_parallel_attempts
        self._max_attempts = max(1, int(max_attempts))
        self._content_validator = content_validator or _default_content_validator
        self._on_terminal = on_job_terminal
        # 仅“恰好 2 图”歧义时使用的决策模型；缺失时由 resolve_mode 保守兜底
        self._intent_classifier = intent_classifier
        self._intent_confidence_threshold = intent_confidence_threshold
        self._content_risk_scorer = content_risk_scorer
        self._content_risk_fail_closed = content_risk_fail_closed
        self._content_risk_threshold = content_risk_threshold
        # 供应商素材登记器（贰春上传/三宝裸传/算力转存）；public_url 路线无需注入
        self._asset_registrar = asset_registrar
        # 成片交付转存器：注入后任务在成片落入自有 OSS 后才置 succeeded；
        # 不注入时维持现状，直接以上游地址交付
        self._deliverer = deliverer
        # created 派发占位的宽限：超过该时长仍未完成首次 submit，
        # 判定创建进程中断（提交最坏 2 次 × 30s 超时，默认 90s 留余量）
        self._dispatch_grace_seconds = dispatch_grace_seconds

    # ---------- 对外入口 ----------

    def submit_job(self, client_key: str, idempotency_key: Optional[str],
                   spec: dict) -> JobView:
        # 意图仲裁先于落库：显式模式与素材结构矛盾时抛 IntentError（由 API 层映射 422），
        # 不建任务、不产生费用；解析出的 mode 写入持久化 spec 供过滤与统计桶使用
        spec = self._resolve_spec(spec)
        job = self._repo.create_job(client_key, idempotency_key, spec)
        # 幂等重放：已有任务（含终态）一律返回现状，不再产生尝试
        if job.status != "pending" or self._repo.list_attempts(job.id):
            return self._view(job.id)

        claim_submission = getattr(self._repo, "claim_submission", None)
        submission_owner = f"submit-{uuid.uuid4().hex}"
        if claim_submission is not None and not claim_submission(
                job.id, worker_id=submission_owner,
                lease_seconds=max(90, self._dispatch_grace_seconds * self._max_attempts * 2)):
            return self._view(job.id)

        try:
            now = self._clock()
            ranked = self._rank(spec)
            self._repo.save_decision(job.id, {
                "candidates": [
                    {"route_id": item.route.route_id, "provider": item.route.provider,
                     "quote": str(item.quote), "expected_cost": str(item.expected_cost)}
                    for item in ranked],
                "chosen": ranked[0].route.route_id if ranked else None,
            })
            if not ranked:
                self._terminate(job.id, "failed", "unsupported_capability")
                return self._view(job.id)

            self._repo.update_job(job.id, quality_group=ranked[0].route.quality_group)
            self._run_chain(job.id, spec, ranked, now)
            return self._view(job.id)
        finally:
            release = getattr(self._repo, "release_job_claim", None)
            if release is not None:
                release(job.id, worker_id=submission_owner)

    def get_view(self, job_id: str, client_key: str) -> JobView:
        """只读快照：不查上游、不推进状态机（供 API GET 使用）。

        归属隔离：任务不存在或不属于该 client 同样抛错，
        两者错误不可区分，防止枚举他人任务 ID 探测存在性。
        """
        job = self._repo.get_job_for_client(job_id, client_key)
        if job is None:
            raise OrchestratorError(f"job not found: {job_id}")
        return self._view(job_id)

    def poll_job(self, job_id: str) -> JobView:
        job = self._repo.get_job(job_id)
        if job is None:
            raise OrchestratorError(f"job not found: {job_id}")
        now = self._clock()
        bucket = self._bucket(job.spec)

        # 先对账所有占用中的尝试（活动态 + 审核挂起态；即使任务已终态，晚到的状态仍需如实记录费用）
        for attempt in self._repo.list_attempts(job_id):
            if attempt.status in DISPATCHING_ATTEMPT:
                # created 无 upstream_task_id 不能对账：宽限期内由创建它的
                # submit 调用负责；超宽限视为创建进程中断，按"提交结果未知"
                # 释放占位，交由下方故障切换链处理
                age = (now - attempt.created_at).total_seconds()
                if age <= self._dispatch_grace_seconds:
                    continue
                logger.warning(
                    "提交占位超过 %ss 未完成，按中断释放：job_id=%s attempt_id=%s",
                    self._dispatch_grace_seconds, job_id, attempt.id)
                self._repo.settle_attempt(
                    attempt.id, status="unknown", billing_status=None,
                    content_url=None, cost=None,
                    error={"type": "submit_dispatch_stale",
                           "message": "提交占位超过宽限未完成，创建进程疑似中断"},
                    ended_at=now)
                continue
            if attempt.status in OCCUPIED_ATTEMPT:
                self._reconcile(attempt, now, bucket)

        job = self._repo.get_job(job_id)
        if job.status in TERMINAL_JOB:
            if job.status == "failed" and job.semantic_error == "deadline_exceeded":
                self._reconcile_terminal_delivery(job)
            return self._view(job_id)

        # 交付阶段：已有成片通过验收时，转存自有 OSS 成功后任务才置终态；
        # 转存失败任务保持 running，由后续 tick 补偿（不新增 archiving 状态）
        if self._deliverer is not None:
            source = next((a for a in self._repo.list_attempts(job_id)
                           if a.status == "succeeded"), None)
            if source is not None:
                self._deliver_content(job, source.content_url)
                return self._view(job_id)

        spec = job.spec
        ranked = self._rank(spec)
        attempts = self._repo.list_attempts(job_id)
        active = [a for a in attempts if a.status in OCCUPIED_ATTEMPT]
        dispatching = [a for a in attempts if a.status in DISPATCHING_ATTEMPT]
        remaining = deadline_remaining(job.created_at,
                                       deadline_seconds=spec.get("deadline_seconds"),
                                       now=now)

        if remaining is not None and remaining <= 0:
            # 停止等待；活动尝试保留给后台继续对账，不伪造失败
            self._terminate(job_id, "failed", "deadline_exceeded")
            return self._view(job_id)

        if not active and not dispatching:
            self._run_chain(job_id, spec, ranked, now)
            return self._view(job_id)

        if job.status == "pending":
            # submit 仍在派发窗口内：任务事实已开始，避免继续以 pending 暴露
            self._repo.update_job(job_id, status="running")

        if spec.get("allow_hedge"):
            self._maybe_start_hedge(job_id, spec, ranked, attempts, active,
                                    remaining, now)
        return self._view(job_id)

    # ---------- 提交与故障切换链 ----------

    def _run_chain(self, job_id: str, spec: dict, ranked: list[RankedRoute],
                   now: datetime) -> None:
        if not self._repo.list_attempts(job_id):
            risk_error = self._assess_content_risk(spec)
            if risk_error is not None:
                self._terminate(job_id, "failed", risk_error["type"], error=risk_error)
                return
        allow_switch = bool(spec.get("allow_switch", True))
        while True:
            attempts = self._repo.list_attempts(job_id)
            if any(a.status in (OCCUPIED_ATTEMPT | DISPATCHING_ATTEMPT)
                   for a in attempts):
                # created 占位（并发 worker 撞见 submit 进行中）同样不得新开路线
                self._repo.update_job(job_id, status="running")
                return
            used = {a.route_id for a in attempts}
            if len(attempts) >= self._max_attempts:
                self._terminate(job_id, "failed", "all_candidates_failed")
                return
            choice = select_failover_route(ranked, used)
            if choice is None or (attempts and not allow_switch):
                semantic = ("upstream_unknown"
                            if attempts and attempts[-1].status == "unknown"
                            else "all_candidates_failed")
                self._terminate(job_id, "failed", semantic)
                return

            if not attempts:
                reason = "expected_cost_min"
            else:
                reason = ("failover_after_unknown"
                          if attempts[-1].status == "unknown"
                          else "failover_after_failed")
            attempt = self._start_attempt(job_id, spec, choice,
                                          seq=len(attempts), reason=reason,
                                          is_hedge=False, now=now,
                                          bucket=self._bucket(spec))
            if attempt.status in ACTIVE_ATTEMPT:
                self._repo.update_job(job_id, status="running")
                return

    def _start_attempt(self, job_id: str, spec: dict, choice: RankedRoute,
                       *, seq: int, reason: str, is_hedge: bool,
                       now: datetime, bucket: str):
        route = choice.route
        adapter = self._adapters.get(route.provider)
        if adapter is None:
            raise OrchestratorError(f"未注册供应商适配器: {route.provider}")

        attempt = self._repo.add_attempt(
            job_id=job_id, seq=seq, route_id=route.route_id,
            provider=route.provider, quote_amount=str(choice.quote),
            reason=reason, is_hedge=is_hedge)

        try:
            assets = self._prepare_assets(route, spec)
        except AssetRegistrationError as exc:
            # 尚未触达供应商、不产生费用：记失败并让 _run_chain 同轮切换备份
            self._settle_asset_failed(attempt, exc, now)
            self._record_event(attempt, success=False, now=now, bucket=bucket)
            return self._repo.list_attempts(job_id)[seq]

        req = SubmitRequest(
            model=route.upstream_model,
            prompt=spec["prompt"],
            duration_seconds=int(spec["duration_seconds"]),
            resolution=str(spec["resolution"]).lower(),
            aspect_ratio=spec["aspect_ratio"],
            idempotency_key=f"{job_id}-{seq}",
            reference_assets=assets,
            duration_field=route.capability.duration_field,
        )

        # 无响应=结果未知：幂等供应商同键重放一次；非幂等只发一次
        tries = 2 if adapter.supports_idempotent_submit else 1
        for _ in range(tries):
            try:
                result = adapter.submit(req)
            except RetriableTransportError:
                continue
            except Exception as exc:  # 收到明确 HTTP 响应（含 5xx/429）= 明确提交失败
                self._settle_submit_rejected(attempt, exc, now)
                self._record_event(attempt, success=False, now=now, bucket=bucket)
                return self._repo.list_attempts(job_id)[seq]
            else:
                self._repo.mark_attempt(
                    attempt.id, "submitted",
                    upstream_task_id=result.upstream_task_id, submit_at=now)
                phase = _PHASE_MAP.get(result.phase, "queued")
                if phase in ("queued", "running"):
                    self._repo.mark_attempt(
                        attempt.id, phase,
                        **({"queued_at": now} if phase == "queued"
                           else {"running_at": now}))
                return self._repo.list_attempts(job_id)[seq]

        # 重放仍未知
        risk_reason = None
        if not adapter.supports_idempotent_submit:
            risk_reason = "submit_unknown_double_charge_risk"
        fields = {"reason": risk_reason} if risk_reason else {}
        self._repo.mark_attempt(attempt.id, "unknown", **fields)
        self._repo.settle_attempt(
            attempt.id, status="unknown", billing_status=None,
            content_url=None, cost=None,
            error={"type": "submit_unknown", "message": "提交结果未知，未收到上游响应"},
            ended_at=now)
        return self._repo.list_attempts(job_id)[seq]

    def _settle_submit_rejected(self, attempt, exc: Exception, now: datetime) -> None:
        error = {"type": "submit_rejected",
                 "status": getattr(exc, "status", None),
                 "retriable": bool(getattr(exc, "retriable", False)),
                 "message": str(exc)}
        self._repo.settle_attempt(
            attempt.id, status="failed", billing_status=None,
            content_url=None, cost=None, error=error, ended_at=now)

    def _prepare_assets(self, route, spec: dict) -> tuple[AssetRef, ...]:
        """按路线 asset_access 在提交前完成素材登记，输出统一引用通道。"""
        groups = (("image", spec.get("reference_images")),
                  ("video", spec.get("reference_videos")),
                  ("audio", spec.get("reference_audios")))
        sources = [(kind, url)
                   for kind, urls in groups for url in (urls or ())]
        if not sources:
            return ()
        access = route.capability.asset_access
        if access == "public_url":
            return tuple(AssetRef(kind, url, "public_url")
                         for kind, url in sources)
        if self._asset_registrar is None:
            raise OrchestratorError(
                f"路线 {route.route_id} 需要素材登记（{access}）但未配置登记器")
        inputs = tuple(
            AssetInput(kind=kind, public_url=url,
                       filename=_asset_filename(url))
            for kind, url in sources)
        registered = self._asset_registrar.register_batch(route, inputs)
        return tuple(AssetRef(a.kind, a.ref, a.ref_type) for a in registered)

    def _settle_asset_failed(self, attempt, exc: AssetRegistrationError,
                             now: datetime) -> None:
        error = {"type": "asset_registration",
                 "status": getattr(exc, "status", None),
                 "retriable": bool(getattr(exc, "retriable", False)),
                 "field": getattr(exc, "field", None),
                 "message": str(exc)}
        self._repo.settle_attempt(
            attempt.id, status="failed", billing_status=None,
            content_url=None, cost=None, error=error, ended_at=now)

    # ---------- 轮询对账 ----------

    def _reconcile(self, attempt, now: datetime, bucket: str) -> None:
        adapter = self._adapters.get(attempt.provider)
        if adapter is None:
            raise OrchestratorError(f"未注册供应商适配器: {attempt.provider}")
        try:
            result = adapter.poll(attempt.upstream_task_id)
        except RetriableTransportError:
            return  # 瞬时抖动：保持活动，下个轮询周期再看
        except Exception as exc:
            if getattr(exc, "retriable", False):
                # 供应商明确返回的可重试错误（如 429 限频）：尝试保持活动，
                # 下个轮询周期再对账，不得中断本 tick 同任务其余尝试
                logger.warning("供应商返回可重试错误，稍后再对账："
                               "provider=%s task=%s status=%s",
                               attempt.provider, attempt.upstream_task_id,
                               getattr(exc, "status", None))
                return
            raise

        if result.phase in ("queued", "running"):
            phase = _PHASE_MAP.get(result.phase, "queued")
            stamp = {"queued_at": now} if phase == "queued" else {"running_at": now}
            if (phase == "queued" and attempt.queued_at is None) or \
               (phase == "running" and attempt.running_at is None):
                self._repo.mark_attempt(attempt.id, phase, **stamp)
            else:
                self._repo.mark_attempt(attempt.id, phase)
            return

        if result.phase == "review":
            # 人工核对挂起：不判失败、不结算、不自动退款、不记成败事件、不触发切换/对冲；
            # 尝试保持占用，后续轮询继续对账，转 succeeded/failed 时照常收尾。
            if attempt.status != "review":
                self._repo.mark_attempt(attempt.id, "review")
            return

        if result.phase == "succeeded":
            if self._content_validator(result.content_url or "", result.raw):
                job = self._repo.get_job(attempt.job_id)
                late_result = (
                    job.status in TERMINAL_JOB
                    and job.semantic_error == "deadline_exceeded"
                )
                self._repo.settle_attempt(
                    attempt.id,
                    status=("delivery_pending"
                            if late_result and self._deliverer is not None
                            else "succeeded"),
                    billing_status=result.billing_status,
                    content_url=result.content_url, cost=None,
                    raw=result.raw, ended_at=now)
                self._record_event(attempt, success=True, now=now, bucket=bucket)
                if self._deliverer is None:
                    if job.status not in TERMINAL_JOB:
                        # 第一个通过验收的成片成为唯一交付
                        self._repo.update_job(
                            attempt.job_id, status="succeeded",
                            semantic_error=None, content_url=result.content_url)
                        self._fire_terminal(attempt.job_id)
                # 注入转存器时 job 保持 running：由 poll_job 交付阶段把成片
                # 落入自有 OSS 后才置 succeeded（交付源取 seq 最小的成功尝试）
                return
            result = NormalizedResult(
                phase="failed", billing_status=result.billing_status,
                content_url=None,
                error={"type": "content_unavailable",
                       "message": "成片链接未通过交付校验"},
                raw=result.raw)

        # 明确失败
        self._repo.settle_attempt(
            attempt.id, status="failed", billing_status=result.billing_status,
            content_url=None, cost=None, error=result.error, raw=result.raw,
            ended_at=now)
        self._record_event(attempt, success=False, now=now, bucket=bucket)

    def _reconcile_terminal_delivery(self, job) -> None:
        """处理 deadline 后到账的成片，保持对外失败语义并完成内部归档。"""
        source = next((attempt for attempt in self._repo.list_attempts(job.id)
                       if attempt.status in DELIVERY_PENDING_ATTEMPT
                       and attempt.content_url), None)
        if source is None:
            return
        if self._deliverer is None:
            if source.status == "delivery_pending":
                self._repo.mark_attempt(source.id, "succeeded")
            return
        if source.status != "delivery_pending":
            self._repo.mark_attempt(source.id, "delivery_pending")
        final_url = self._deliver_content(job, source.content_url,
                                          promote_job=False)
        if final_url:
            self._repo.mark_attempt(source.id, "succeeded",
                                    delivery_url=final_url)

    def _deliver_content(self, job, source_url: Optional[str], *,
                         promote_job: bool = True) -> Optional[str]:
        """把已验收成片转存到自有 OSS；任何失败都保持 running 等下轮补偿。

        确定性 key（job_id 命名、按创建月份分目录）使重复补偿天然幂等，
        多实例并发最多多一次同内容 PUT，不会产生两份交付物。
        """
        if not source_url:
            # 理论不可达：成功结算必带 content_url；防御性记录并等待人工对账
            logger.error("成功尝试缺少 content_url，无法转存：job_id=%s", job.id)
            return None
        try:
            final_url = self._deliverer.deliver(job.id, job.created_at, source_url)
        except Exception:
            logger.exception("成片转存失败，下个 tick 补偿：job_id=%s", job.id)
            return None
        if promote_job:
            self._repo.update_job(job.id, status="succeeded",
                                  semantic_error=None, content_url=final_url)
            self._fire_terminal(job.id)
        return final_url

    def _maybe_start_hedge(self, job_id: str, spec: dict,
                           ranked: list[RankedRoute], attempts: list,
                           active: list, remaining: Optional[int],
                           now: datetime) -> None:
        max_parallel = max(
            1, int(spec.get("max_parallel_attempts", self._max_parallel)
                   or self._max_parallel))
        used = {a.route_id for a in attempts}
        if len(attempts) >= self._max_attempts:
            return
        active_providers = {a.provider for a in active}
        for attempt in active:  # 一个轮询周期最多启动一条对冲
            stats = self._repo.rolling_stats(attempt.route_id, self._bucket(spec))
            if not hedge_due(
                    attempt, stats=stats,
                    fallback_seconds=self._fallback_hedge_seconds, now=now,
                    active_attempt_count=len(active),
                    max_parallel=max_parallel, allow_hedge=True,
                    remaining_seconds=remaining):
                continue
            choice = select_hedge_route(ranked, used, active_providers)
            if choice is None:
                continue
            self._start_attempt(job_id, spec, choice, seq=len(attempts),
                                reason="hedge_slow", is_hedge=True, now=now,
                                bucket=self._bucket(spec))
            return

    # ---------- 基础设施 ----------

    def _resolve_spec(self, spec: dict) -> dict:
        """提交入口意图仲裁：返回带确定 mode 的 spec 副本；矛盾请求抛 IntentError。"""
        images = tuple(spec.get("reference_images") or ())
        videos = tuple(spec.get("reference_videos") or ())
        audios = tuple(spec.get("reference_audios") or ())
        intent = resolve_mode(
            prompt=spec["prompt"],
            image_count=len(images),
            video_count=len(videos),
            audio_count=len(audios),
            explicit=spec.get("mode"),
            classifier=self._intent_classifier,
            confidence_threshold=self._intent_confidence_threshold)
        resolved = dict(spec)
        resolved["mode"] = intent.mode.value
        return resolved

    def _assess_content_risk(self, spec: dict) -> Optional[dict]:
        """提交前内容安全闸门；生产中未配置、异常或非法分数均拒绝。"""
        unavailable = {"type": "content_safety_unavailable"}
        scorer = self._content_risk_scorer
        if scorer is None:
            return unavailable if self._content_risk_fail_closed else None
        try:
            decision = scorer.score_risk(spec["prompt"])
            score = float(decision.score)
            if not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError("invalid safety score")
        except Exception:
            return unavailable if self._content_risk_fail_closed else None
        if score >= self._content_risk_threshold:
            return {"type": "content_risk_blocked",
                    "score": score,
                    "threshold": self._content_risk_threshold,
                    "reason": getattr(decision, "reason", None),
                    "message": "提交前内容违规风险评分达到阻断阈值"}
        return None

    def _rank(self, spec: dict) -> list[RankedRoute]:
        req = VideoSpec(
            prompt=spec["prompt"],
            duration_seconds=int(spec["duration_seconds"]),
            resolution=str(spec["resolution"]).lower(),
            aspect_ratio=spec["aspect_ratio"],
            mode=Mode(spec["mode"]),
            quality_group=spec.get("quality_group"),
            reference_images=len(tuple(spec.get("reference_images") or ())),
            reference_videos=len(tuple(spec.get("reference_videos") or ())),
            reference_audios=len(tuple(spec.get("reference_audios") or ())),
        )
        # 第一遍只用硬条件收敛候选，避免为不相关路线查统计；
        # 第二遍带入滚动成功率/熔断状态做最终期望成本排序。
        candidates = rank_candidates(self._routes, req, {})
        stats = {
            item.route.route_id:
            self._repo.rolling_stats(item.route.route_id, self._bucket(spec))
            for item in candidates
        }
        return rank_candidates(self._routes, req, stats)

    @staticmethod
    def _bucket(spec: dict) -> str:
        return f"{spec['mode']}|{str(spec['resolution']).lower()}|{int(spec['duration_seconds'])}s"

    def _record_event(self, attempt, *, success: bool, now: datetime,
                      bucket: str) -> None:
        if attempt.submit_at is None:
            elapsed = 0.0
        else:
            elapsed = (now - attempt.submit_at).total_seconds()
        self._repo.record_event(
            route_id=attempt.route_id, bucket=bucket,
            job_id=attempt.job_id, attempt_id=attempt.id, success=success,
            elapsed_seconds=max(elapsed, 0.0))

    def _terminate(self, job_id: str, status: str, semantic_error: str,
                   error: Optional[dict] = None) -> None:
        self._repo.update_job(job_id, status=status,
                              semantic_error=semantic_error, error=error)
        self._fire_terminal(job_id)

    def _fire_terminal(self, job_id: str) -> None:
        if self._on_terminal is not None:
            self._on_terminal(self._repo.get_job(job_id))

    def _view(self, job_id: str) -> JobView:
        job = self._repo.get_job(job_id)
        attempts = tuple(
            AttemptView(
                id=a.id, seq=a.seq, route_id=a.route_id, provider=a.provider,
                status=a.status, reason=a.reason, is_hedge=a.is_hedge,
                upstream_task_id=a.upstream_task_id, content_url=a.content_url,
                cost=a.cost, error=a.error)
            for a in self._repo.list_attempts(job_id))
        return JobView(
            id=job.id, status=job.status, semantic_error=job.semantic_error,
            quality_group=job.quality_group, content_url=job.content_url,
            error=job.error, attempts=attempts)
