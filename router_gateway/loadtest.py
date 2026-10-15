"""本地视频网关容量探测器。

只使用自动创建的本地临时 PostgreSQL、Redis 和模拟供应商，不读取
供应商凭据、不访问现有数据库或生产入口。两个 HTTP API 实例共享
仓储与限流存储，使用真实编排器和 worker。结果不代表供应商容量。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import platform
import secrets
import socket
import subprocess
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable

import httpx
import redis
import uvicorn
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from .api import create_app
from .db import Base, Job, Attempt, JobRepository
from .orchestrator.service import Orchestrator
from .adapters.base import NormalizedResult, SubmitRequest, SubmitResult
from .catalog import Route, RouteCapability, DurationRange, Mode
from .quota import RedisTokenBucket
from .worker import run_once


class SimulatedProvider:
    """没有网络副作用的供应商替身，按虚拟时钟返回任务阶段。"""

    provider = "loadtest"
    supports_idempotent_submit = True

    def __init__(self, *, task_seconds: float = 2.0,
                 latency_seconds: float = 0.0,
                 clock: Callable[[], float] = time.monotonic):
        self.task_seconds = max(0.0, float(task_seconds))
        self.latency_seconds = max(0.0, float(latency_seconds))
        self.clock = clock
        self.hold = False
        self.unavailable = False
        self.submissions: Counter[str] = Counter()
        self._tasks: dict[str, tuple[float, str, str]] = {}
        self._lock = threading.Lock()

    def submit(self, request: SubmitRequest) -> SubmitResult:
        if self.latency_seconds:
            time.sleep(self.latency_seconds)
        with self._lock:
            self.submissions[request.idempotency_key] += 1
            existing = self._tasks.get(request.idempotency_key)
            if existing is None:
                task_id = f"loadtest-{len(self._tasks) + 1}"
                self._tasks[request.idempotency_key] = (self.clock(), task_id, request.prompt)
            else:
                _, task_id, _ = existing
        return SubmitResult(upstream_task_id=task_id, phase="queued", raw={})

    def poll(self, upstream_task_id: str) -> NormalizedResult:
        if self.latency_seconds:
            time.sleep(self.latency_seconds)
        if self.unavailable:
            from .adapters.base import RetriableTransportError
            raise RetriableTransportError("simulated outage")
        with self._lock:
            task = next(((start, prompt) for start, task_id, prompt in self._tasks.values()
                         if task_id == upstream_task_id), None)
        if task is None:
            return NormalizedResult(phase="failed", error={"type": "not_found"})
        started, prompt = task
        elapsed = self.clock() - started
        if self.hold or elapsed < self.task_seconds / 2:
            return NormalizedResult(phase="queued")
        if elapsed < self.task_seconds:
            return NormalizedResult(phase="running")
        if prompt == "fail":
            return NormalizedResult(phase="failed", error={"type": "simulated_failure"})
        return NormalizedResult(
            phase="succeeded",
            content_url=f"https://loadtest.invalid/{upstream_task_id}.mp4",
        )


def _percentile(values: list[float], ratio: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, math.ceil(len(ordered) * ratio))
    return int(round(ordered[rank - 1] * 1000))


def summarize(results: list[tuple[int, float, str | None]], *, elapsed: float) -> dict:
    status_counts = Counter(str(status) for status, _, _ in results)
    error_counts = Counter(code for _, _, code in results if code)
    latencies = [duration for _, duration, _ in results]
    elapsed = max(float(elapsed), 0.000001)
    return {
        "requests": len(results),
        "status_counts": dict(sorted(status_counts.items())),
        "error_counts": dict(sorted(error_counts.items())),
        "requests_per_second": round(len(results) / elapsed, 2),
        "p50_ms": _percentile(latencies, 0.50),
        "p95_ms": _percentile(latencies, 0.95),
        "p99_ms": _percentile(latencies, 0.99),
        "successful_requests_per_second": round(sum(200 <= status < 300 for status, _, _ in results) / elapsed, 2),
        "success_p95_ms": _percentile([duration for status, duration, _ in results if 200 <= status < 300], 0.95),
    }


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行隔离的视频网关模拟容量测试（需要 Docker）")
    parser.add_argument("--requests", type=int, default=400)
    parser.add_argument("--concurrency", type=int, default=64)
    parser.add_argument("--rate", type=int, default=10000)
    parser.add_argument("--burst", type=int, default=10000)
    parser.add_argument("--active-limit", type=int, default=100)
    parser.add_argument("--output", type=str, default=None,
                        help="可选：将 JSON 结果写入本地文件")
    return parser


def report_failures(report: dict) -> list[str]:
    failures = []
    checks = report["checks"]
    for name in ("active_limit_not_exceeded", "outage_preserves_running_jobs", "redis_fail_closed"):
        if not checks.get(name):
            failures.append(name)
    if checks.get("idempotency") != {"jobs": 1, "attempts": 1, "submit_calls": 1}:
        failures.append("duplicate_idempotent_dispatch")
    for name, phase in report["phases"].items():
        counts = phase.get("status_counts", {})
        if any(counts.get(status, 0) for status in ("0", "500", "502", "504")):
            failures.append(f"unexpected_http_error_{name}")
        if any(counts.get(status, 0) for status in ("pending", "running")):
            failures.append(f"unfinished_{name}")
        if phase.get("errors"):
            failures.append(f"worker_errors_{name}")
    return failures


def _validate_args(args: argparse.Namespace) -> None:
    if not 1 <= args.requests <= 100_000:
        raise SystemExit("--requests 必须在 1 到 100000 之间")
    if not 1 <= args.concurrency <= 512:
        raise SystemExit("--concurrency 必须在 1 到 512 之间")
    if not 1 <= args.rate <= 1_000_000 or not 1 <= args.burst <= 1_000_000:
        raise SystemExit("--rate/--burst 必须在 1 到 1000000 之间")
    if not 1 <= args.active_limit <= 100_000:
        raise SystemExit("--active-limit 必须在 1 到 100000 之间")


def _docker(*arguments: str) -> str:
    completed = subprocess.run(["docker", *arguments], capture_output=True, text=True,
                               encoding="utf-8", timeout=60)
    if completed.returncode:
        raise RuntimeError(f"Docker {arguments[0]} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _mapped_port(name: str, port: int) -> int:
    info = json.loads(_docker("inspect", "--format", "{{json .NetworkSettings.Ports}}", name))
    return int(info[f"{port}/tcp"][0]["HostPort"])


@contextmanager
def isolated_services():
    names: list[str] = []
    task_id = uuid.uuid4().hex[:12]
    password = secrets.token_hex(16)
    engine = None
    cache = None
    try:
        pg_name = f"video-loadtest-pg-{task_id}"
        _docker("run", "--rm", "-d", "--name", pg_name, "--pull=never",
                "--label", "video-loadtest=temporary", "--tmpfs", "/var/lib/postgresql/data",
                "-p", "127.0.0.1::5432", "-e", "POSTGRES_USER=loadtest",
                "-e", f"POSTGRES_PASSWORD={password}", "-e", "POSTGRES_DB=loadtest",
                "postgres:15-alpine")
        names.append(pg_name)
        redis_name = f"video-loadtest-redis-{task_id}"
        _docker("run", "--rm", "-d", "--name", redis_name, "--pull=never",
                "--label", "video-loadtest=temporary", "-p", "127.0.0.1::6379",
                "redis:7-alpine", "redis-server", "--save", "", "--appendonly", "no")
        names.append(redis_name)
        engine = create_engine(
            f"postgresql://loadtest:{password}@127.0.0.1:{_mapped_port(pg_name, 5432)}/loadtest",
            pool_size=20, max_overflow=80, pool_timeout=10, pool_pre_ping=True)
        cache = redis.Redis(host="127.0.0.1", port=_mapped_port(redis_name, 6379),
                            socket_timeout=2, socket_connect_timeout=2)
        deadline = time.monotonic() + 30
        while True:
            try:
                with engine.connect():
                    cache.ping()
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise RuntimeError("temporary database/Redis did not become ready") from None
                time.sleep(0.2)
        Base.metadata.create_all(engine)
        yield engine, cache
    finally:
        if engine is not None:
            engine.dispose()
        if cache is not None:
            cache.close()
        for name in reversed(names):
            _docker("stop", "--time", "5", name)


@contextmanager
def http_servers(repo, provider, cache):
    capability = RouteCapability("per_second", DurationRange(1, 30),
                                 ("720p",), ("16:9",), frozenset({Mode.TEXT}))
    route = Route("simulated", "loadtest", "simulated", "simulated",
                  capability, {"720p": "0.00"})
    servers, threads, sockets, urls, orchestrators = [], [], [], [], []
    try:
        for _ in range(2):
            orchestrator = Orchestrator(repo=repo, routes=[route], adapters={"loadtest": provider})
            app = create_app(orchestrator, resolve_client=repo.get_client_by_api_key,
                             rate_limiter=RedisTokenBucket(cache), admin_repo=repo,
                             internal_token="loadtest-internal")
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(512)
            sockets.append(listener)
            server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
            thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
            servers.append(server)
            threads.append(thread)
            urls.append(f"http://127.0.0.1:{listener.getsockname()[1]}")
            orchestrators.append(orchestrator)
            thread.start()
        deadline = time.monotonic() + 15
        while not all(server.started for server in servers):
            if time.monotonic() >= deadline:
                raise RuntimeError("loadtest HTTP servers did not become ready")
            time.sleep(0.05)
        yield urls, orchestrators
    finally:
        for server in servers:
            server.should_exit = True
        for thread in threads:
            thread.join(timeout=15)
        for listener in sockets:
            listener.close()


async def burst(urls, *, key, count, concurrency, method="POST", path="/v1/videos",
                shared_idempotency=False, prompt="success"):
    semaphore = asyncio.Semaphore(concurrency)
    phase_id = uuid.uuid4().hex[:12]
    results, bodies = [], []
    async with httpx.AsyncClient(trust_env=False, timeout=30,
                                limits=httpx.Limits(max_connections=concurrency)) as http:
        async def send(index):
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await http.request(method, urls[index % len(urls)] + path,
                        headers={"Authorization": f"Bearer {key}",
                                 "Idempotency-Key": f"{phase_id}-{0 if shared_idempotency else index}"},
                        **({"json": {"model": "simulated", "prompt": prompt,
                            "duration_seconds": 5, "resolution": "720p", "aspect_ratio": "16:9",
                            "allow_switch": False, "allow_hedge": False}} if method == "POST" else {}))
                    body = response.json()
                    results.append((response.status_code, time.perf_counter() - started,
                                    (body.get("error") or {}).get("code")))
                    bodies.append(body)
                except httpx.HTTPError as exc:
                    results.append((0, time.perf_counter() - started, type(exc).__name__))
        started = time.perf_counter()
        await asyncio.gather(*(send(index) for index in range(count)))
    return summarize(results, elapsed=time.perf_counter() - started), bodies


def drain(repo, orchestrators, *, client_id, worker_count, timeout=60):
    started = time.perf_counter()
    cycles = Counter()
    errors = []
    def worker(index):
        try:
            while time.perf_counter() - started < timeout:
                with repo._sf() as session:
                    active = session.query(func.count(Job.id)).filter(
                        Job.client_key == client_id, Job.status.in_(["pending", "running"])).scalar()
                if not active:
                    return
                cycles[index] += run_once(orchestrators[index % 2], repo, limit=20,
                                          worker_id=f"loadtest-{index}", lease_seconds=30)
                time.sleep(0.01)
        except Exception as exc:
            errors.append(type(exc).__name__)
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        list(pool.map(worker, range(worker_count)))
    with repo._sf() as session:
        counts = dict(session.query(Job.status, func.count(Job.id)).filter(
            Job.client_key == client_id).group_by(Job.status).all())
    return {"workers": worker_count, "elapsed_seconds": round(time.perf_counter() - started, 3),
            "status_counts": counts, "polls": sum(cycles.values()), "errors": errors}


def run_benchmark(args):
    _validate_args(args)
    report = {"mode": "isolated_postgres_redis_http", "supplier_requests": 0,
              "environment": {"python": platform.python_version(), "platform": platform.platform(),
                  "redis_client": redis.__version__, "httpx": httpx.__version__,
                  "uvicorn": uvicorn.__version__, "api_instances": 2,
                  "api_processes": 1, "db_pool_size": 20, "db_max_overflow": 80,
                  "simulated_provider_latency_ms": 50, "simulated_task_seconds": 1,
                  "nginx_included": False},
              "config": vars(args), "phases": {}, "checks": {}}
    with isolated_services() as (engine, cache):
        repo = JobRepository(sessionmaker(engine, expire_on_commit=False))
        provider = SimulatedProvider(task_seconds=1, latency_seconds=0.05)
        provider.hold = True
        with http_servers(repo, provider, cache) as (urls, orchestrators):
            def issue(name, rate=args.rate, capacity=args.burst, active=args.active_limit):
                key = f"loadtest-{name}-{uuid.uuid4().hex}"
                return key, repo.create_client(name, key, rate_limit_per_second=rate,
                    burst_capacity=capacity, max_active_jobs=active, max_parallel_attempts=1)
            def phase(name, **kwargs):
                concurrency = kwargs.pop("concurrency", args.concurrency)
                summary, bodies = asyncio.run(burst(urls, concurrency=concurrency, **kwargs))
                summary["concurrency"] = concurrency
                report["phases"][name] = summary
                print(f"phase {name}: {json.dumps(summary)}", flush=True)
                return summary, bodies
            key, client = issue("active")
            summary, bodies = phase("active_limit", key=key, count=args.requests)
            with repo._sf() as session:
                active_count = session.query(func.count(Job.id)).filter(Job.client_key == client.id).scalar()
            report["checks"]["active_limit_not_exceeded"] = active_count <= args.active_limit
            report["checks"]["active_jobs_created"] = active_count
            job_id = next((body["id"] for body in bodies if "id" in body), None)
            if job_id:
                phase("query_while_full", key=key, count=args.requests * 2,
                      method="GET", path=f"/v1/tasks/{job_id}")
                for concurrency in (8, 16, 32, 64, 128):
                    phase(f"query_concurrency_{concurrency}", key=key, count=400,
                          method="GET", path=f"/v1/tasks/{job_id}", concurrency=concurrency)
            rate_key, _ = issue("rate", rate=1, capacity=5, active=1000)
            phase("shared_rate_limit", key=rate_key, count=100)
            retry_key, retry_client = issue("retry")
            before = sum(provider.submissions.values())
            phase("concurrent_idempotency", key=retry_key, count=32, shared_idempotency=True)
            with repo._sf() as session:
                retry_jobs = session.query(func.count(Job.id)).filter(Job.client_key == retry_client.id).scalar()
                retry_attempts = session.query(func.count(Attempt.id)).join(Job).filter(Job.client_key == retry_client.id).scalar()
            report["checks"]["idempotency"] = {"jobs": retry_jobs, "attempts": retry_attempts,
                "submit_calls": sum(provider.submissions.values()) - before}
            provider.hold = False
            report["phases"]["worker_1"] = drain(repo, orchestrators, client_id=client.id, worker_count=1)
            parallel_key, parallel_client = issue("parallel")
            provider.hold = True
            phase("worker_4_seed", key=parallel_key, count=args.active_limit)
            provider.hold = False
            report["phases"]["worker_4"] = drain(repo, orchestrators, client_id=parallel_client.id, worker_count=4)
            mixed_key, mixed_client = issue("mixed")
            provider.hold = True
            _, mixed_bodies = phase("mixed_seed", key=mixed_key, count=args.active_limit)
            mixed_job_id = next((body["id"] for body in mixed_bodies if "id" in body), None)
            provider.hold = False
            if mixed_job_id:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    processing = pool.submit(drain, repo, orchestrators, client_id=mixed_client.id, worker_count=4)
                    phase("query_with_workers", key=mixed_key, count=800, method="GET",
                          path=f"/v1/tasks/{mixed_job_id}", concurrency=32)
                    report["phases"]["worker_with_queries"] = processing.result()
            failure_key, failure_client = issue("failure")
            phase("simulated_failure_seed", key=failure_key, count=10, prompt="fail")
            report["phases"]["simulated_failure_drain"] = drain(
                repo, orchestrators, client_id=failure_client.id, worker_count=2)
            outage_key, outage_client = issue("outage")
            phase("outage_seed", key=outage_key, count=10)
            provider.unavailable = True
            run_once(orchestrators[0], repo, worker_id="outage", limit=1000)
            with repo._sf() as session:
                still_active = session.query(func.count(Job.id)).filter(Job.client_key == outage_client.id,
                    Job.status == "running").scalar()
            report["checks"]["outage_preserves_running_jobs"] = still_active == 10
            provider.unavailable = False
            report["phases"]["outage_recovery"] = drain(repo, orchestrators, client_id=outage_client.id, worker_count=2)
            unavailable_cache = RedisTokenBucket.from_url("redis://127.0.0.1:1/0")._client
            with http_servers(repo, provider, unavailable_cache) as (fault_urls, _):
                fault, _ = asyncio.run(burst(fault_urls, key=key, count=20, concurrency=10))
                report["phases"]["redis_unavailable"] = fault
                report["checks"]["redis_fail_closed"] = fault["status_counts"] == {"503": 20}
            unavailable_cache.close()
            report["provider_submit_calls"] = sum(provider.submissions.values())
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["failures"] = report_failures(report)
    report["passed"] = not report["failures"]
    report["http_requests"] = sum(phase.get("requests", 0) for phase in report["phases"].values())
    return report


def main() -> int:
    args = argument_parser().parse_args()
    _validate_args(args)
    report = run_benchmark(args)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
        print(f"report saved: {args.output}; passed={report['passed']}; failures={report['failures']}")
    else:
        print(encoded)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
