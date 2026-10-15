# -*- coding: utf-8 -*-
"""独立质量评价 worker：评价失败只记录内部状态，不改变交付结果。"""
from __future__ import annotations

import logging
import os
import time
import uuid

from .db import JobRepository, get_engine, make_session_factory
from .db.init_db import resolve_database_url
from .catalog import load_catalog
from .quality import VideoQualityClient, review_score, validate_review

logger = logging.getLogger("router_gateway.quality_worker")


def run_once(repo, reviewer, *, worker_id="test") -> int:
    review = repo.claim_quality_review(worker_id=worker_id)
    if review is None:
        return 0
    try:
        attempt = repo.get_attempt(review.attempt_id)
        job = repo.get_job(review.job_id)
        first_success = next((item for item in repo.list_attempts(review.job_id)
                              if item.status == "succeeded" and item.content_url), None)
        source_url = attempt.delivery_url or attempt.content_url
        if first_success is not None and first_success.id == attempt.id and job.content_url:
            source_url = job.content_url
        result = validate_review(reviewer.evaluate(source_url))
        score, passed = review_score(result)
        if not repo.finish_quality_review(review.id, worker_id=review.claim_token,
                                          result=result, score=score, passed=passed,
                                          model=getattr(reviewer, "model", None)):
            logger.warning("quality review lease lost: review_id=%s", review.id)
    except Exception as exc:
        logger.warning("quality review failed: review_id=%s error_type=%s", review.id, type(exc).__name__)
        repo.finish_quality_review(review.id, worker_id=review.claim_token,
                                   model=getattr(reviewer, "model", None), error_code="evaluation_failed")
    return 1


def run_forever(repo, reviewer, *, worker_id, sleep=time.sleep, idle_seconds=5,
                busy_seconds=1):
    while True:
        try:
            processed = run_once(repo, reviewer, worker_id=worker_id)
        except Exception as exc:
            logger.warning("quality worker tick failed: error_type=%s", type(exc).__name__)
            processed = 0
        sleep(busy_seconds if processed else idle_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
    if not key:
        logger.error("DASHSCOPE_API_KEY 未配置，质量 worker 不启动评价")
        return
    engine = get_engine(resolve_database_url())
    repo = JobRepository(make_session_factory(engine),
                         quality_sample_every=int(os.getenv("ROUTER_GATEWAY_QUALITY_SAMPLE_EVERY", "10")),
                         quality_model_keys={route.route_id: route.quality_group for route in load_catalog()})
    reviewer = VideoQualityClient(
        api_key=key,
        base_url=os.getenv("ROUTER_GATEWAY_QUALITY_BASE_URL",
                           "https://dashscope.aliyuncs.com/compatible-mode"),
        model=os.getenv("ROUTER_GATEWAY_QUALITY_MODEL", "qwen3.8-omni-flash"),
        timeout=int(os.getenv("ROUTER_GATEWAY_QUALITY_TIMEOUT", "45")))
    try:
        run_forever(repo, reviewer,
                    worker_id=os.getenv("ROUTER_GATEWAY_QUALITY_WORKER_ID") or uuid.uuid4().hex)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
