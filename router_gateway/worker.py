# -*- coding: utf-8 -*-
"""DB 状态驱动的轮询 worker：无内存调度表，可安全多实例部署。

每个 tick 都以数据库为唯一事实源：重新查活动任务 → 逐个对账推进。
实例随时被杀、任意时刻水平扩容都不会丢任务或重复派发
（去重/并发边界由幂等提交与适配器状态对账保证，见 docs 路由指南 §12.3）。
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from threading import Event, Thread
from typing import Callable

from .assembly import build_gateway

logger = logging.getLogger("router_gateway.worker")


def run_once(orchestrator, repo, *, limit: int = 20,
             worker_id: str = "test", lease_seconds: int = 30) -> int:
    """处理一批活动任务；单个任务失败只记录日志，不影响同批其余任务。"""
    claim = getattr(repo, "claim_active_job_ids", None)
    if claim is not None and hasattr(repo, "renew_job_claim"):
        processed = 0
        for _ in range(limit):
            claim_token = f"{worker_id[:90]}:{uuid.uuid4().hex}"
            job_ids = claim(worker_id=claim_token, lease_seconds=lease_seconds, limit=1)
            if not job_ids:
                break
            job_id = job_ids[0]
            stopped = Event()

            def heartbeat():
                while not stopped.wait(max(0.1, lease_seconds / 3)):
                    try:
                        if not repo.renew_job_claim(job_id, worker_id=claim_token,
                                                    lease_seconds=lease_seconds):
                            logger.warning("任务租约已失效：job_id=%s", job_id)
                            return
                    except Exception:
                        logger.exception("任务续租失败：job_id=%s", job_id)
                        return

            renewer = Thread(target=heartbeat, daemon=True)
            renewer.start()
            try:
                with repo.claimed_job(job_id, claim_token=claim_token):
                    orchestrator.poll_job(job_id)
            except Exception:
                logger.exception("poll_job 失败：job_id=%s", job_id)
            finally:
                stopped.set()
                renewer.join()
                repo.release_job_claim(job_id, worker_id=claim_token)
            processed += 1
        return processed
    if claim is None:
        job_ids = repo.list_active_job_ids(limit=limit)
    else:
        job_ids = claim(worker_id=worker_id, lease_seconds=lease_seconds,
                        limit=limit)
    for job_id in job_ids:
        try:
            orchestrator.poll_job(job_id)
        except Exception:
            # 轮询是持续循环，任何单任务异常都不能炸掉 worker
            logger.exception("poll_job 失败：job_id=%s", job_id)
        finally:
            release = getattr(repo, "release_job_claim", None)
            if release is not None:
                release(job_id, worker_id=worker_id)
    return len(job_ids)


def run_forever(orchestrator, repo, *,
                sleep: Callable[[float], None] = time.sleep,
                should_continue: Callable[[], bool] = lambda: True,
                idle_seconds: float = 5.0,
                busy_seconds: float = 1.0,
                batch_limit: int = 20,
                worker_id: str = "test",
                lease_seconds: int = 30) -> None:
    """无限轮询：空批长退避，有任务短退避；每轮都重新查库。"""
    while should_continue():
        processed = run_once(orchestrator, repo, limit=batch_limit,
                             worker_id=worker_id, lease_seconds=lease_seconds)
        sleep(busy_seconds if processed else idle_seconds)


def main() -> None:
    """进程入口：python -m router_gateway.worker"""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    gateway = build_gateway()
    try:
        worker_id = os.getenv("ROUTER_GATEWAY_WORKER_ID") or uuid.uuid4().hex
        run_forever(gateway.orchestrator, gateway.repo, worker_id=worker_id)
    finally:
        gateway.engine.dispose()


if __name__ == "__main__":
    main()
