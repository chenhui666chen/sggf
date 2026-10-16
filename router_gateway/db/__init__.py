# -*- coding: utf-8 -*-
"""SQLAlchemy 模型与仓储。独立库 router_gateway，与小说业务库物理隔离。

财务相关的 attempt / event 为追加型记录，不做覆盖删除。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    create_engine,
    or_,
    and_,
    exists,
    func,
    inspect,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from ..stats import RouteStats

# 本机 docker novel_postgres 中的独立库 router_gateway（与小说业务库物理隔离）
DEFAULT_DATABASE_URL = (
    "postgresql://novel_user:NovelPostgres0t649OyRUaI@127.0.0.1:5432/router_gateway")


class ClientConcurrencyLimitExceeded(ValueError):
    """调用方活动任务数已达到配置上限。"""

    def __init__(self, current: int, limit: int):
        self.current = current
        self.limit = limit
        super().__init__(f"client active job limit exceeded: {current}/{limit}")


class IdempotencyKeyConflict(ValueError):
    """同一调用方复用幂等键但请求内容不一致。"""


class ClientTaskLimitExceeded(ValueError):
    def __init__(self, current: int, limit: int):
        self.current = current
        self.limit = limit
        super().__init__(f"client task limit exceeded: {current}/{limit}")


class JobLeaseLost(RuntimeError):
    pass

# PG 上仍建为 JSONB（能力与现状一致）；sqlite 变体供一次性建表/全链路测试使用
_Json = JSON().with_variant(JSONB(), "postgresql")
# PG 上为 bigint 自增主键；sqlite 仅 INTEGER PRIMARY KEY 可自动自增
_BigIntPK = BigInteger().with_variant(Integer(), "sqlite")


def _now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Client(Base):
    __tablename__ = "clients"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    # 旧版本的 api_key 列保留用于兼容历史明文记录；新发卡只写不可逆占位值和 hash。
    api_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    api_key_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0)
    rate_limit_per_second: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1")
    burst_capacity: Mapped[int] = mapped_column(
        Integer, default=5, server_default="5")
    max_active_jobs: Mapped[int] = mapped_column(
        Integer, default=5, server_default="5")
    max_parallel_attempts: Mapped[int] = mapped_column(
        Integer, default=2, server_default="2")
    lifetime_task_limit: Mapped[int] = mapped_column(
        Integer, default=100, server_default="100")
    daily_task_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_task_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    monthly_budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # 幂等键去重仅在同一 client 维度生效：不同 client 可复用同一幂等键
        UniqueConstraint("client_key", "idempotency_key",
                         name="uq_jobs_client_idempotency"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    client_key: Mapped[str] = mapped_column(String(128), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    spec: Mapped[dict] = mapped_column(_Json)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    # unsupported_capability / all_candidates_failed / running
    semantic_error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quality_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error: Mapped[dict | None] = mapped_column(_Json, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    claim_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    attempts: Mapped[list["Attempt"]] = relationship(back_populates="job")


class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[int] = mapped_column(_BigIntPK, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(32), ForeignKey("jobs.id"), index=True)
    seq: Mapped[int]
    route_id: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    upstream_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="created")
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_hedge: Mapped[bool] = mapped_column(Boolean, default=False)
    quote_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    billing_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    refunded: Mapped[bool] = mapped_column(Boolean, default=False)
    content_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    delivery_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error: Mapped[dict | None] = mapped_column(_Json, nullable=True)
    raw: Mapped[dict | None] = mapped_column(_Json, nullable=True)
    submit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    running_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    job: Mapped[Job] = relationship(back_populates="attempts")


class RouteEvent(Base):
    __tablename__ = "route_events"
    id: Mapped[int] = mapped_column(_BigIntPK, primary_key=True, autoincrement=True)
    route_id: Mapped[str] = mapped_column(String(64), index=True)
    bucket: Mapped[str] = mapped_column(String(64), index=True)
    job_id: Mapped[str] = mapped_column(String(32))
    attempt_id: Mapped[int] = mapped_column(BigInteger)
    success: Mapped[bool]
    elapsed_seconds: Mapped[float]
    quality_pass: Mapped[bool] = mapped_column(Boolean, default=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class QualityReview(Base):
    __tablename__ = "quality_reviews"
    __table_args__ = (UniqueConstraint("attempt_id", name="uq_quality_reviews_attempt"),)

    id: Mapped[int] = mapped_column(_BigIntPK, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(32), index=True)
    attempt_id: Mapped[int] = mapped_column(BigInteger, index=True)
    route_id: Mapped[str] = mapped_column(String(64), index=True)
    model_key: Mapped[str] = mapped_column(String(128), index=True)
    sample_index: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 3), nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    result: Mapped[dict | None] = mapped_column(_Json, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    claim_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class QualitySampleCounter(Base):
    __tablename__ = "quality_sample_counters"
    model_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    success_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class DecisionSnapshot(Base):
    __tablename__ = "decision_snapshots"
    id: Mapped[int] = mapped_column(_BigIntPK, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(32), ForeignKey("jobs.id"), index=True)
    data: Mapped[dict] = mapped_column(_Json)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


def get_engine(url: str):
    return create_engine(url, pool_pre_ping=True, future=True)


def make_session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False, future=True)


class JobRepository:
    def __init__(self, session_factory, *, quality_sample_every: int = 10,
                 quality_model_keys: dict[str, str] | None = None):
        self._sf = session_factory
        self._quality_schema_available = None
        self.quality_sample_every = max(1, int(quality_sample_every))
        self.quality_model_keys = quality_model_keys or {}
        self._claim_context = ContextVar(f"job_claim_{id(self)}", default=None)

    @contextmanager
    def claimed_job(self, job_id: str, *, claim_token: str):
        token = self._claim_context.set((job_id, claim_token))
        try:
            yield
        finally:
            self._claim_context.reset(token)

    def _guard_claim(self, session, job_id: str) -> None:
        claim = self._claim_context.get()
        if claim is None:
            return
        if claim[0] != job_id:
            raise JobLeaseLost("job lease context mismatch")
        owned = (session.query(Job.id)
                 .filter(Job.id == job_id, Job.claimed_by == claim[1],
                         Job.claim_until > _now())
                 .with_for_update().one_or_none())
        if owned is None:
            raise JobLeaseLost("job lease expired or replaced")

    # ---------- 调用方 clients（W2 鉴权/CLI 发卡吊销） ----------

    def create_client(self, name: str, api_key: str, **limits) -> Client:
        """登记新调用方；enabled 默认 True，balance 本期不接线（D3）。"""
        with self._sf() as s:
            key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
            client = Client(
                id=str(uuid.uuid4()), name=name,
                api_key=f"keyhash:{key_hash}", api_key_hash=key_hash,
                **limits)
            s.add(client)
            s.commit()
            s.refresh(client)
            client.issued_api_key = api_key
            return client

    def rotate_client_key(self, client_id: str, api_key: str) -> Client | None:
        with self._sf() as s:
            client = s.get(Client, client_id)
            if client is None:
                return None
            key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
            client.api_key = f"keyhash:{key_hash}"
            client.api_key_hash = key_hash
            s.commit()
            s.refresh(client)
            client.issued_api_key = api_key
            return client

    def set_client_enabled(self, client_id: str, enabled: bool) -> Client | None:
        with self._sf() as s:
            client = s.get(Client, client_id)
            if client is None:
                return None
            client.enabled = bool(enabled)
            s.commit()
            s.refresh(client)
            return client

    def update_client_limits(self, client_id: str, **limits) -> Client | None:
        allowed = {
            "rate_limit_per_second", "burst_capacity", "max_active_jobs",
            "max_parallel_attempts", "daily_task_limit", "monthly_task_limit",
            "daily_budget", "monthly_budget",
            "lifetime_task_limit",
        }
        unknown = set(limits) - allowed
        if unknown:
            raise ValueError(f"unsupported client limits: {sorted(unknown)}")
        with self._sf() as s:
            client = s.get(Client, client_id)
            if client is None:
                return None
            for key, value in limits.items():
                if value is not None:
                    setattr(client, key, value)
            s.commit()
            s.refresh(client)
            return client

    def get_client_by_api_key(self, api_key: str) -> Client | None:
        """按 api_key 查调用方；不存在返回 None，enabled=false 同样返回由鉴权层判禁用。"""
        with self._sf() as s:
            key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
            client = (s.query(Client)
                      .filter_by(api_key_hash=key_hash)
                      .one_or_none())
            if client is not None:
                return client
            # 兼容迁移前的历史明文 key；新发卡不会再走此分支。
            return (s.query(Client)
                    .filter(Client.api_key == api_key, Client.api_key_hash.is_(None))
                    .one_or_none())

    def disable_client(self, client_id: str) -> bool:
        """吊销调用方；返回是否命中并更新（不存在返回 False）。"""
        with self._sf() as s:
            client = s.get(Client, client_id)
            if client is None:
                return False
            client.enabled = False
            s.commit()
            return True

    def create_job(self, client_key: str, idempotency_key: str | None, spec: dict) -> Job:
        with self._sf() as s:
            client = s.get(Client, client_key, with_for_update=True)
            if idempotency_key:
                existing = (s.query(Job)
                            .filter_by(client_key=client_key,
                                       idempotency_key=idempotency_key)
                            .one_or_none())
                if existing:
                    if self._request_spec(existing.spec) != self._request_spec(spec):
                        raise IdempotencyKeyConflict(
                            "idempotency key reused with different request")
                    return existing
            if client is not None:
                total = s.query(Job).filter(Job.client_key == client_key).count()
                if total >= client.lifetime_task_limit:
                    raise ClientTaskLimitExceeded(total, client.lifetime_task_limit)
            if client is not None and client.max_active_jobs is not None:
                active_attempt = exists().where(
                    and_(Attempt.job_id == Job.id,
                         Attempt.status.in_([
                             "created", "submitted", "queued", "running",
                             "review", "delivery_pending"])))
                current = (s.query(Job)
                           .filter(Job.client_key == client_key)
                           .filter(or_(
                               ~Job.status.in_(["succeeded", "failed"]),
                               active_attempt))
                           .count())
                if current >= max(0, int(client.max_active_jobs)):
                    raise ClientConcurrencyLimitExceeded(
                        current=current, limit=int(client.max_active_jobs))
            job = Job(id=uuid.uuid4().hex, client_key=client_key,
                      idempotency_key=idempotency_key, spec=spec)
            s.add(job)
            try:
                s.commit()
            except IntegrityError:
                s.rollback()
                if not idempotency_key:
                    raise
                existing = (s.query(Job)
                            .filter_by(client_key=client_key,
                                       idempotency_key=idempotency_key)
                            .one_or_none())
                if existing is None:
                    raise
                if self._request_spec(existing.spec) != self._request_spec(spec):
                    raise IdempotencyKeyConflict(
                        "idempotency key reused with different request")
                return existing
            s.refresh(job)
            return job

    @staticmethod
    def _request_spec(spec: dict) -> dict:
        return json.loads(json.dumps({key: value for key, value in spec.items()
                                      if key != "max_parallel_attempts"}))

    def get_job(self, job_id: str) -> Job | None:
        with self._sf() as s:
            return s.get(Job, job_id)

    def get_job_for_client(self, job_id: str, client_key: str) -> Job | None:
        """归属隔离查询：仅返回属于该 client 的任务；他人任务与不存在同样返回 None。"""
        with self._sf() as s:
            return (s.query(Job)
                    .filter_by(id=job_id, client_key=client_key)
                    .one_or_none())

    def list_active_job_ids(self, limit: int = 20) -> list[str]:
        """后台 worker 拉取活动任务：pending（含提交中断遗留）与 running，先进先出。"""
        with self._sf() as s:
            rows = (s.query(Job.id)
                    .filter(Job.status.in_(["pending", "running"]))
                    .order_by(Job.created_at, Job.id)
                    .limit(limit).all())
            return [row[0] for row in rows]

    def claim_active_job_ids(self, *, worker_id: str, lease_seconds: int = 30,
                             limit: int = 20, poll_interval_seconds: int = 5) -> list[str]:
        """在事务内领取任务，避免多个 worker 同时处理同一任务。"""
        now = _now()
        lease_until = now + timedelta(seconds=max(1, int(lease_seconds)))
        active_attempt = exists().where(
            and_(Attempt.job_id == Job.id,
                 Attempt.status.in_(["created", "submitted", "queued", "running",
                                     "review", "delivery_pending"])))
        with self._sf() as s:
            query = (s.query(Job)
                     .filter(or_(Job.status.in_(["pending", "running"]), active_attempt))
                     .filter(or_(Job.claim_until.is_(None),
                                 Job.claim_until < now))
                     .filter(or_(Job.next_poll_at.is_(None), Job.next_poll_at <= now))
                     .order_by(Job.next_poll_at.asc().nullsfirst(), Job.created_at, Job.id)
                     .with_for_update(skip_locked=True)
                     .limit(limit))
            jobs = query.all()
            ids = []
            for job in jobs:
                job.claimed_by = worker_id
                job.claim_until = lease_until
                job.next_poll_at = now + timedelta(seconds=max(1, poll_interval_seconds))
                ids.append(job.id)
            s.commit()
            return ids

    def claim_submission(self, job_id: str, *, worker_id: str,
                         lease_seconds: int = 30) -> bool:
        """原子领取待提交任务，避免并发 API 请求重复触达供应商。"""
        now = _now()
        lease_until = now + timedelta(seconds=max(1, int(lease_seconds)))
        with self._sf() as s:
            has_attempt = exists().where(Attempt.job_id == Job.id)
            affected = (s.query(Job)
                        .filter(Job.id == job_id, Job.status == "pending", ~has_attempt)
                        .filter(or_(Job.claim_until.is_(None), Job.claim_until < now))
                        .update({Job.claimed_by: worker_id, Job.claim_until: lease_until},
                                synchronize_session=False))
            s.commit()
            return affected == 1

    def release_job_claim(self, job_id: str, *, worker_id: str) -> None:
        """轮询tick结束时释放租约，但保留 next_poll_at 退避。

        claim 时把 next_poll_at 推到 now+poll_interval；常规轮询释放必须保留
        它，否则下一tick立刻重领同一批任务造成轮询风暴（见
        test_polling_due_time_prevents_oldest_jobs_starving_new_jobs）。
        """
        with self._sf() as s:
            (s.query(Job).filter_by(id=job_id, claimed_by=worker_id)
             .update({Job.claimed_by: None, Job.claim_until: None},
                     synchronize_session=False))
            s.commit()

    def handover_job_claim(self, job_id: str, *, worker_id: str) -> None:
        """实例让位/停机时移交：释放租约并清空轮询退避，让其他实例立即接管。"""
        with self._sf() as s:
            (s.query(Job).filter_by(id=job_id, claimed_by=worker_id)
             .update({Job.claimed_by: None, Job.claim_until: None,
                      Job.next_poll_at: None}, synchronize_session=False))
            s.commit()

    def renew_job_claim(self, job_id: str, *, worker_id: str,
                        lease_seconds: int = 30) -> bool:
        now = _now()
        with self._sf() as s:
            affected = (s.query(Job)
                        .filter(Job.id == job_id, Job.claimed_by == worker_id,
                                Job.claim_until > now)
                        .update({Job.claim_until: now + timedelta(seconds=max(1, lease_seconds))},
                                synchronize_session=False))
            s.commit()
            return affected == 1

    def update_job(self, job_id: str, **fields) -> None:
        with self._sf() as s:
            self._guard_claim(s, job_id)
            obj = s.get(Job, job_id)
            for k, v in fields.items():
                setattr(obj, k, v)
            s.commit()

    def add_attempt(self, job_id: str, seq: int, route_id: str, provider: str,
                    quote_amount: str, reason: str, is_hedge: bool) -> Attempt:
        with self._sf() as s:
            self._guard_claim(s, job_id)
            a = Attempt(job_id=job_id, seq=seq, route_id=route_id, provider=provider,
                        quote_amount=Decimal(quote_amount), reason=reason, is_hedge=is_hedge)
            s.add(a)
            s.commit()
            s.refresh(a)
            return a

    def mark_attempt(self, attempt_id: int, status: str, **fields) -> None:
        with self._sf() as s:
            a = s.get(Attempt, attempt_id)
            self._guard_claim(s, a.job_id)
            a.status = status
            if status == "submitted" and a.submit_at is None:
                a.submit_at = _now()
            if status == "queued" and a.queued_at is None:
                a.queued_at = _now()
            if status == "running" and a.running_at is None:
                a.running_at = _now()
            for k, v in fields.items():
                setattr(a, k, v)
            s.commit()

    def settle_attempt(self, attempt_id: int, status: str, billing_status: str | None,
                       content_url: str | None, cost: str | None,
                       error: dict | None = None, raw: dict | None = None,
                       ended_at: datetime | None = None) -> None:
        with self._sf() as s:
            a = s.get(Attempt, attempt_id)
            self._guard_claim(s, a.job_id)
            a.status = status
            a.ended_at = ended_at or _now()
            a.billing_status = billing_status
            a.content_url = content_url
            a.cost = Decimal(cost) if cost is not None else None
            if error is not None:
                a.error = error
            if raw is not None:
                a.raw = raw
            s.commit()

    def get_attempt(self, attempt_id: int) -> Attempt:
        with self._sf() as s:
            return s.get(Attempt, attempt_id)

    def list_attempts(self, job_id: str) -> list[Attempt]:
        with self._sf() as s:
            return (s.query(Attempt).filter_by(job_id=job_id).order_by(Attempt.seq).all())

    def active_attempt(self, job_id: str) -> Attempt | None:
        with self._sf() as s:
            return (s.query(Attempt)
                    .filter(Attempt.job_id == job_id,
                            Attempt.status.in_(["submitted", "queued", "running"]))
                    .order_by(Attempt.seq.desc()).first())

    def record_event(self, route_id: str, bucket: str, job_id: str, attempt_id: int,
                     success: bool, elapsed_seconds: float, quality_pass: bool = True,
                     cost: str | None = None) -> None:
        with self._sf() as s:
            self._guard_claim(s, job_id)
            s.add(RouteEvent(route_id=route_id, bucket=bucket, job_id=job_id, attempt_id=attempt_id,
                             success=success, elapsed_seconds=elapsed_seconds,
                             quality_pass=quality_pass,
                             cost=Decimal(cost) if cost is not None else None))
            s.commit()

    def rolling_stats(self, route_id: str, bucket: str, window: int = 100) -> RouteStats:
        with self._sf() as s:
            rows = (s.query(RouteEvent.success, RouteEvent.elapsed_seconds,
                            RouteEvent.quality_pass)
                    .filter_by(route_id=route_id, bucket=bucket)
                    .order_by(RouteEvent.id.desc()).limit(window).all())
            if self._quality_schema_available is None:
                self._quality_schema_available = inspect(s.get_bind()).has_table("quality_reviews")
            matching_event = exists().where(and_(
                RouteEvent.attempt_id == QualityReview.attempt_id,
                RouteEvent.route_id == route_id, RouteEvent.bucket == bucket))
            quality_rows = (s.query(QualityReview.passed)
                            .filter(matching_event,
                                    QualityReview.status == "completed",
                                    QualityReview.passed.isnot(None))
                            .order_by(QualityReview.id.desc()).limit(window).all()
                            if self._quality_schema_available else [])
        if not rows:
            return RouteStats(0, 0.95, 0.0, 0.0, 1.0, len(quality_rows))
        n = len(rows)
        ok = sum(1 for r in rows if r[0])
        durations = sorted(r[1] for r in rows if r[0])
        q = sum(1 for r in quality_rows if r[0])
        p50 = durations[len(durations) // 2] if durations else 0.0
        p95 = durations[min(len(durations) - 1, int(round(n * 0.95)) - 1)] if durations else 0.0
        return RouteStats(n, ok / n, p50, p95,
                          q / len(quality_rows) if quality_rows else 1.0,
                          len(quality_rows))

    def claim_quality_review(self, *, worker_id: str, lease_seconds: int = 300) -> QualityReview | None:
        for _ in range(100):
            review = self._claim_next_quality_sample(lease_seconds=lease_seconds)
            if review is None:
                return None
            if review.status == "running":
                return review
        return None

    def _claim_next_quality_sample(self, *, lease_seconds: int) -> QualityReview | None:
        now = _now()
        lease_until = now + timedelta(seconds=max(1, int(lease_seconds)))
        token = uuid.uuid4().hex
        with self._sf() as s:
            (s.query(QualityReview)
             .filter(QualityReview.status == "running", QualityReview.claim_until < now)
             .update({QualityReview.status: "failed", QualityReview.error_code: "worker_lost",
                      QualityReview.claim_token: None, QualityReview.claim_until: None},
                     synchronize_session=False))
            candidate = (s.query(Attempt)
                         .join(Job, Job.id == Attempt.job_id)
                         .outerjoin(QualityReview, QualityReview.attempt_id == Attempt.id)
                         .filter(Attempt.status == "succeeded",
                                 Attempt.content_url.isnot(None),
                                 Job.status == "succeeded",
                                 QualityReview.id.is_(None))
                         .filter(exists().where(and_(RouteEvent.attempt_id == Attempt.id,
                                                     RouteEvent.success.is_(True))))
                         .order_by(Attempt.ended_at, Attempt.id)
                         .with_for_update(of=Attempt, skip_locked=True).first())
            if candidate is None:
                s.commit()
                return None
            model_key = self.quality_model_keys.get(candidate.route_id, candidate.route_id)
            dialect = s.get_bind().dialect.name
            if dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert
            elif dialect == "sqlite":
                from sqlalchemy.dialects.sqlite import insert
            else:
                raise RuntimeError("quality sampling requires PostgreSQL or SQLite")
            s.execute(insert(QualitySampleCounter).values(model_key=model_key, success_count=0)
                      .on_conflict_do_nothing(index_elements=["model_key"]))
            counter = (s.query(QualitySampleCounter).filter_by(model_key=model_key)
                       .with_for_update().one())
            counter.success_count += 1
            sampled = counter.success_count % self.quality_sample_every == 0
            review = QualityReview(job_id=candidate.job_id, attempt_id=candidate.id,
                                   route_id=candidate.route_id, model_key=model_key,
                                   sample_index=counter.success_count,
                                   status="running" if sampled else "skipped",
                                   claim_token=token if sampled else None,
                                   claim_until=lease_until if sampled else None,
                                   attempts=1 if sampled else 0)
            s.add(review)
            try:
                s.commit()
            except IntegrityError:
                s.rollback()
                return None
            s.refresh(review)
            return review

    def finish_quality_review(self, review_id: int, *, worker_id: str,
                              result: dict | None = None, score: float | None = None,
                              passed: bool | None = None, model: str | None = None,
                              error_code: str | None = None) -> bool:
        """仅当前租约 token 可收尾；评价写入失败也不修改任务或成败事件。"""
        with self._sf() as s:
            fields = {QualityReview.claim_token: None, QualityReview.claim_until: None,
                      QualityReview.model: model}
            if error_code:
                fields.update({QualityReview.status: "failed", QualityReview.error_code: error_code})
            else:
                fields.update({QualityReview.status: "completed", QualityReview.result: result,
                               QualityReview.score: Decimal(str(score)) if score is not None else None,
                               QualityReview.passed: passed})
            affected = (s.query(QualityReview)
                        .filter(QualityReview.id == review_id, QualityReview.status == "running",
                                QualityReview.claim_token == worker_id, QualityReview.claim_until >= _now())
                        .update(fields, synchronize_session=False))
            s.commit()
            return affected == 1

    def gateway_metrics(self, *, window_hours: int = 24) -> dict:
        """返回管理面板所需的聚合指标，不读取任务 prompt 或供应商凭据。"""
        window_hours = max(1, min(int(window_hours), 168))
        cutoff = _now() - timedelta(hours=window_hours)
        with self._sf() as s:
            events = (s.query(RouteEvent.route_id, RouteEvent.success,
                               RouteEvent.elapsed_seconds, RouteEvent.cost)
                      .filter(RouteEvent.created_at >= cutoff)
                      .order_by(RouteEvent.id.desc()).limit(10000)
                      .all())
            jobs = (s.query(Job.client_key, Job.status, func.count(Job.id))
                    .filter(Job.created_at >= cutoff)
                    .group_by(Job.client_key, Job.status).all())
            outstanding = exists().where(and_(
                Attempt.job_id == Job.id,
                Attempt.status.in_(["created", "submitted", "queued", "running", "review", "delivery_pending"])))
            active_jobs = (s.query(func.count(Job.id))
                           .filter(or_(Job.status.in_(["pending", "running"]), outstanding))
                           .scalar() or 0)
            recorded_cost, cost_count = (s.query(func.sum(Attempt.cost), func.count(Attempt.cost))
                               .filter(Attempt.created_at >= cutoff).one())
            unknown_cost = (s.query(func.count(Attempt.id))
                            .filter(Attempt.created_at >= cutoff, Attempt.cost.is_(None)).scalar() or 0)
            pending_jobs = (s.query(func.count(Job.id)).filter(Job.status == "pending").scalar() or 0)
            event_count = (s.query(func.count(RouteEvent.id))
                           .filter(RouteEvent.created_at >= cutoff).scalar() or 0)
            active_counts = dict(s.query(Job.client_key, func.count(Job.id))
                                 .filter(or_(Job.status.in_(["pending", "running"]), outstanding))
                                 .group_by(Job.client_key).all())
            if self._quality_schema_available is None:
                self._quality_schema_available = inspect(s.get_bind()).has_table("quality_reviews")
            quality_rows = (s.query(QualityReview.route_id, QualityReview.status,
                                    QualityReview.score, QualityReview.passed)
                            .filter(QualityReview.created_at >= cutoff)
                            .order_by(QualityReview.id.desc()).limit(10000).all()
                            if self._quality_schema_available else [])

        def percentile(values: list[float], ratio: float) -> float:
            if not values:
                return 0.0
            ordered = sorted(values)
            index = min(len(ordered) - 1,
                        int((len(ordered) - 1) * ratio))
            return round(float(ordered[index]), 4)

        grouped: dict[str, list] = {}
        quality_grouped: dict[str, list] = {}
        quality_counts = {"completed": 0, "failed": 0, "running": 0, "pending": 0, "skipped": 0}
        for route_id, status, score, passed in quality_rows:
            if status in quality_counts:
                quality_counts[status] += 1
            if status == "completed" and score is not None and passed is not None:
                quality_grouped.setdefault(route_id, []).append((float(score), bool(passed)))
        for route_id, success, elapsed, cost in events:
            grouped.setdefault(route_id, []).append(
                (bool(success), float(elapsed or 0), float(cost or 0)))
        routes = []
        for route_id, rows in sorted(grouped.items()):
            durations = [row[1] for row in rows]
            quality = quality_grouped.get(route_id, [])
            routes.append({
                "route_id": route_id,
                "samples": len(rows),
                "success_rate": round(sum(row[0] for row in rows) / len(rows), 4),
                "p50_latency_seconds": percentile(durations, 0.50),
                "p95_latency_seconds": percentile(durations, 0.95),
                "total_cost": None,
                "quality_samples": len(quality),
                "quality_pass_rate": round(sum(item[1] for item in quality) / len(quality), 4) if quality else None,
                "quality_average_score": round(sum(item[0] for item in quality) / len(quality), 3) if quality else None,
            })

        client_rows: dict[str, dict] = {}
        for client_key, status, count in jobs:
            item = client_rows.setdefault(client_key, {
                "client_id": client_key, "total_jobs": 0,
                "active_jobs": 0, "succeeded_jobs": 0, "failed_jobs": 0})
            item["total_jobs"] += count
            if status in ("pending", "running"):
                item["active_jobs"] += count
            elif status == "succeeded":
                item["succeeded_jobs"] += count
            elif status == "failed":
                item["failed_jobs"] += count

        success_count = sum(1 for row in events if row[1])
        for client_id, count in active_counts.items():
            item = client_rows.setdefault(client_id, {
                "client_id": client_id, "total_jobs": 0,
                "active_jobs": 0, "succeeded_jobs": 0, "failed_jobs": 0})
            item["active_jobs"] = count
        return {
            "window_hours": window_hours,
            "route_event_count": event_count,
            "sampled_event_count": len(events),
            "success_rate": round(success_count / len(events), 4) if events else 0.0,
            "p50_latency_seconds": percentile([float(row[2] or 0) for row in events], 0.50),
            "p95_latency_seconds": percentile([float(row[2] or 0) for row in events], 0.95),
            "active_jobs": int(active_jobs),
            "total_cost": str(recorded_cost) if cost_count else None,
            "unknown_cost_attempts": int(unknown_cost),
            "pending_jobs": int(pending_jobs),
            "quality": {**quality_counts, "sampled_review_count": len(quality_rows)},
            "routes": routes,
            "clients": sorted(client_rows.values(), key=lambda item: item["client_id"]),
        }

    def save_decision(self, job_id: str, data: dict) -> None:
        with self._sf() as s:
            self._guard_claim(s, job_id)
            s.add(DecisionSnapshot(job_id=job_id, data=data))
            s.commit()

    def list_decisions(self, job_id: str) -> list[DecisionSnapshot]:
        with self._sf() as s:
            return (s.query(DecisionSnapshot).filter_by(job_id=job_id)
                    .order_by(DecisionSnapshot.id).all())
