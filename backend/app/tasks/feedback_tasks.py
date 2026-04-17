# -*- coding: utf-8 -*-
"""
Feedback loop Celery tasks - Periodic model profile updates from generation feedback.
"""

from __future__ import annotations

import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="feedback_loop.apply_feedback_to_profiles",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def apply_feedback_to_profiles_task(
    self,
    min_samples: int = 5,
    days: int = 30,
    user_rating_weight: float = 0.3,
    qc_weight: float = 0.7,
) -> dict:
    from app.db.base import SessionLocal
    from app.services.feedback_loop import get_feedback_loop_service

    db = SessionLocal()
    try:
        service = get_feedback_loop_service()
        result = service.apply_feedback_to_model_profiles(
            db,
            min_samples=min_samples,
            days=days,
            user_rating_weight=user_rating_weight,
            qc_weight=qc_weight,
        )
        logger.info(
            "Feedback loop task completed: updated %d models from %d records",
            result.get("updated_models", 0),
            result.get("total_feedback_processed", 0),
        )
        return result
    except Exception as exc:
        logger.error("Feedback loop task failed: %s", exc)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {"updated_models": 0, "total_feedback_processed": 0, "error": str(exc)}
    finally:
        db.close()


@celery_app.task(
    name="feedback_loop.collect_qc_feedback",
    bind=True,
    max_retries=1,
    default_retry_delay=60,
)
def collect_qc_feedback_task(
    self,
    model_id: str,
    task_type: str,
    qc_passed: bool,
    qc_score: float,
    qc_details: dict | None = None,
    style_match_score: float | None = None,
    prompt_adherence_score: float | None = None,
    visual_quality_score: float | None = None,
    character_consistency_score: float | None = None,
    motion_stability_score: float | None = None,
    generation_latency: float | None = None,
    generation_cost: float | None = None,
    prompt_text: str | None = None,
    output_urls: list | None = None,
) -> dict:
    from app.db.base import SessionLocal
    from app.services.feedback_loop import get_feedback_loop_service

    db = SessionLocal()
    try:
        service = get_feedback_loop_service()
        feedback = service.submit_qc_result(
            db,
            model_id=model_id,
            task_type=task_type,
            qc_passed=qc_passed,
            qc_score=qc_score,
            qc_details=qc_details,
            style_match_score=style_match_score,
            prompt_adherence_score=prompt_adherence_score,
            visual_quality_score=visual_quality_score,
            character_consistency_score=character_consistency_score,
            motion_stability_score=motion_stability_score,
            generation_latency=generation_latency,
            generation_cost=generation_cost,
            prompt_text=prompt_text,
            output_urls=output_urls,
        )
        return {"success": True, "feedback_id": feedback.id}
    except Exception as exc:
        logger.error("QC feedback collection task failed: %s", exc)
        return {"success": False, "error": str(exc)}
    finally:
        db.close()
