# -*- coding: utf-8 -*-
"""
Feedback Loop Service - Collects generation feedback and updates model profiles.

Closes the loop between generation results (user ratings + AutoQC) and
model capability profiles, enabling the system to improve over time.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func as sql_func
from sqlalchemy.orm import Session

from app.models.generation_feedback import GenerationFeedback

logger = logging.getLogger(__name__)


class FeedbackLoopService:
    """Service for collecting feedback and updating model profiles."""

    def submit_user_rating(
        self,
        db: Session,
        *,
        model_id: str,
        task_type: str,
        user_rating: float,
        user_id: Optional[int] = None,
        project_id: Optional[int] = None,
        user_comment: Optional[str] = None,
        prompt_text: Optional[str] = None,
        output_urls: Optional[List[str]] = None,
    ) -> GenerationFeedback:
        user_rating = max(1.0, min(5.0, float(user_rating)))

        feedback = GenerationFeedback(
            user_id=user_id,
            project_id=project_id,
            model_id=model_id,
            task_type=task_type,
            user_rating=user_rating,
            user_comment=user_comment,
            prompt_text=prompt_text,
            output_urls=output_urls or [],
            source="user",
        )
        db.add(feedback)
        db.commit()
        db.refresh(feedback)

        logger.info(
            "User rating submitted: model=%s rating=%.1f user=%s",
            model_id, user_rating, user_id,
        )
        return feedback

    def submit_qc_result(
        self,
        db: Session,
        *,
        model_id: str,
        task_type: str,
        qc_passed: bool,
        qc_score: float,
        qc_details: Optional[Dict[str, Any]] = None,
        style_match_score: Optional[float] = None,
        prompt_adherence_score: Optional[float] = None,
        visual_quality_score: Optional[float] = None,
        character_consistency_score: Optional[float] = None,
        motion_stability_score: Optional[float] = None,
        generation_latency: Optional[float] = None,
        generation_cost: Optional[float] = None,
        prompt_text: Optional[str] = None,
        output_urls: Optional[List[str]] = None,
        user_id: Optional[int] = None,
        project_id: Optional[int] = None,
    ) -> GenerationFeedback:
        feedback = GenerationFeedback(
            user_id=user_id,
            project_id=project_id,
            model_id=model_id,
            task_type=task_type,
            qc_passed=qc_passed,
            qc_score=max(0.0, min(1.0, float(qc_score))),
            qc_details=qc_details or {},
            style_match_score=style_match_score,
            prompt_adherence_score=prompt_adherence_score,
            visual_quality_score=visual_quality_score,
            character_consistency_score=character_consistency_score,
            motion_stability_score=motion_stability_score,
            generation_latency=generation_latency,
            generation_cost=generation_cost,
            prompt_text=prompt_text,
            output_urls=output_urls or [],
            source="auto_qc",
        )
        db.add(feedback)
        db.commit()
        db.refresh(feedback)

        logger.info(
            "QC result submitted: model=%s passed=%s score=%.2f",
            model_id, qc_passed, qc_score,
        )
        return feedback

    def get_model_feedback_stats(
        self,
        db: Session,
        model_id: str,
        task_type: Optional[str] = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        query = db.query(GenerationFeedback).filter(
            GenerationFeedback.model_id == model_id,
            GenerationFeedback.created_at >= cutoff,
        )

        if task_type:
            query = query.filter(GenerationFeedback.task_type == task_type)

        feedbacks = query.all()

        if not feedbacks:
            return {
                "model_id": model_id,
                "task_type": task_type,
                "sample_count": 0,
                "avg_user_rating": None,
                "avg_qc_score": None,
                "qc_pass_rate": None,
                "avg_style_match": None,
                "avg_prompt_adherence": None,
                "avg_visual_quality": None,
                "avg_character_consistency": None,
                "avg_motion_stability": None,
                "avg_latency": None,
                "avg_cost": None,
            }

        user_ratings = [f.user_rating for f in feedbacks if f.user_rating is not None]
        qc_scores = [f.qc_score for f in feedbacks if f.qc_score is not None]
        qc_passes = [f.qc_passed for f in feedbacks if f.qc_passed is not None]
        style_matches = [f.style_match_score for f in feedbacks if f.style_match_score is not None]
        prompt_adherences = [f.prompt_adherence_score for f in feedbacks if f.prompt_adherence_score is not None]
        visual_qualities = [f.visual_quality_score for f in feedbacks if f.visual_quality_score is not None]
        char_consistencies = [f.character_consistency_score for f in feedbacks if f.character_consistency_score is not None]
        motion_stabilities = [f.motion_stability_score for f in feedbacks if f.motion_stability_score is not None]
        latencies = [f.generation_latency for f in feedbacks if f.generation_latency is not None]
        costs = [f.generation_cost for f in feedbacks if f.generation_cost is not None]

        def _avg(values: List[float]) -> Optional[float]:
            return round(sum(values) / len(values), 4) if values else None

        return {
            "model_id": model_id,
            "task_type": task_type,
            "sample_count": len(feedbacks),
            "days": days,
            "avg_user_rating": _avg(user_ratings),
            "avg_qc_score": _avg(qc_scores),
            "qc_pass_rate": round(sum(qc_passes) / len(qc_passes), 4) if qc_passes else None,
            "avg_style_match": _avg(style_matches),
            "avg_prompt_adherence": _avg(prompt_adherences),
            "avg_visual_quality": _avg(visual_qualities),
            "avg_character_consistency": _avg(char_consistencies),
            "avg_motion_stability": _avg(motion_stabilities),
            "avg_latency": _avg(latencies),
            "avg_cost": _avg(costs),
        }
    
    def get_scene_recommendation_stats(
        self,
        db: Session,
        scene_keywords: List[str],
        field: str = "lighting_time",
        days: int = 30,
        min_samples: int = 3,
    ) -> List[Dict[str, Any]]:
        """Get statistical recommendations for scene based on historical feedback.
        
        Args:
            db: Database session
            scene_keywords: Keywords to match in prompt_text
            field: Field to analyze (lighting_time, camera_movement, shot_type, etc.)
            days: Days of feedback to consider
            min_samples: Minimum samples required
        
        Returns:
            List of recommendations sorted by weighted score
        """
        from datetime import timedelta
        from sqlalchemy import func as sql_func
        
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        query = db.query(
            sql_func.json_extract_text(GenerationFeedback.qc_details, f"$.{field}").label(field),
            sql_func.avg(GenerationFeedback.user_rating).label("avg_rating"),
            sql_func.avg(GenerationFeedback.qc_score).label("avg_qc"),
            sql_func.count(GenerationFeedback.id).label("count"),
            sql_func.avg(GenerationFeedback.visual_quality_score).label("avg_visual"),
        ).filter(
            GenerationFeedback.created_at >= cutoff,
        )
        
        for keyword in scene_keywords:
            query = query.filter(GenerationFeedback.prompt_text.ilike(f"%{keyword}%"))
        
        query = query.group_by(field)
        
        results = []
        for row in query.all():
            value = getattr(row, field)
            if value is None:
                continue
            
            count = row.count
            if count < min_samples:
                continue
            
            avg_rating = row.avg_rating or 0.0
            avg_qc = row.avg_qc or 0.0
            avg_visual = row.avg_visual or 0.0
            
            weighted_score = (avg_rating * 0.4 + avg_qc * 0.4 + avg_visual * 0.2) * (1 + 0.1 * count)
            
            results.append({
                "value": value,
                "avg_rating": round(avg_rating, 2),
                "avg_qc": round(avg_qc, 2),
                "avg_visual": round(avg_visual, 2),
                "count": count,
                "weighted_score": round(weighted_score, 3),
            })
        
        results.sort(key=lambda x: x["weighted_score"], reverse=True)
        return results[:5]
    
    def get_image_edit_stats(
        self,
        db: Session,
        scene_keywords: List[str],
        field: str = "edit_strength",
        days: int = 30,
        min_samples: int = 3,
    ) -> List[Dict[str, Any]]:
        """Get statistical recommendations for image editing based on historical feedback.
        
        Args:
            db: Database session
            scene_keywords: Keywords to match in prompt_text
            field: Field to analyze (edit_strength, skin_smoothing, saturation_boost, etc.)
            days: Days of feedback to consider
            min_samples: Minimum samples required
        
        Returns:
            List of recommendations sorted by weighted score
        """
        from datetime import timedelta
        from sqlalchemy import func as sql_func
        
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        query = db.query(
            sql_func.json_extract_text(GenerationFeedback.qc_details, f"$.qc_scores.overall").label("qc_overall"),
            sql_func.avg(GenerationFeedback.user_rating).label("avg_rating"),
            sql_func.avg(GenerationFeedback.qc_score).label("avg_qc"),
            sql_func.count(GenerationFeedback.id).label("count"),
            sql_func.avg(GenerationFeedback.visual_quality_score).label("avg_visual"),
        ).filter(
            GenerationFeedback.created_at >= cutoff,
        )
        
        for keyword in scene_keywords:
            query = query.filter(GenerationFeedback.prompt_text.ilike(f"%{keyword}%"))
        
        # Group by the field value from qc_details
        query = query.group_by(
            sql_func.json_extract_text(GenerationFeedback.qc_details, f"$.qc_scores.overall")
        )
        
        results = []
        for row in query.all():
            qc_overall = getattr(row, "qc_overall")
            if qc_overall is None:
                continue
            
            count = row.count
            if count < min_samples:
                continue
            
            avg_rating = row.avg_rating or 0.0
            avg_qc = float(qc_overall) if isinstance(qc_overall, (int, float)) else 0.0
            avg_visual = row.avg_visual or 0.0
            
            weighted_score = (avg_rating * 0.4 + avg_qc * 0.4 + avg_visual * 0.2) * (1 + 0.1 * count)
            
            results.append({
                "field_value": field,  # The field name itself
                "avg_rating": round(avg_rating, 2),
                "avg_qc": round(avg_qc, 2),
                "avg_visual": round(avg_visual, 2),
                "count": count,
                "weighted_score": round(weighted_score, 3),
            })
        
        results.sort(key=lambda x: x["weighted_score"], reverse=True)
        return results[:5]

    def apply_feedback_to_model_profiles(
        self,
        db: Session,
        min_samples: int = 5,
        days: int = 30,
        user_rating_weight: float = 0.3,
        qc_weight: float = 0.7,
    ) -> Dict[str, Any]:
        from adapters.registry import registry as model_registry

        unapplied = (
            db.query(GenerationFeedback)
            .filter(GenerationFeedback.applied_to_profile == False)  # noqa: E712
            .all()
        )

        if not unapplied:
            return {"updated_models": 0, "message": "No unapplied feedback found"}

        model_ids = list({f.model_id for f in unapplied})
        updated_count = 0
        update_details = {}

        for model_id in model_ids:
            stats = self.get_model_feedback_stats(db, model_id, days=days)

            if stats["sample_count"] < min_samples:
                continue

            spec = model_registry.get_spec(model_id)
            if spec is None:
                continue

            updated_fields = self._update_spec_from_stats(spec, stats, user_rating_weight, qc_weight)

            if updated_fields:
                updated_count += 1
                update_details[model_id] = updated_fields

        model_feedbacks_for_model = {f.model_id: f for f in unapplied}
        for feedback in unapplied:
            feedback.applied_to_profile = True

        db.commit()

        logger.info(
            "Feedback applied: updated %d models from %d feedback records",
            updated_count, len(unapplied),
        )

        return {
            "updated_models": updated_count,
            "total_feedback_processed": len(unapplied),
            "details": update_details,
        }

    def _update_spec_from_stats(
        self,
        spec: Any,
        stats: Dict[str, Any],
        user_rating_weight: float,
        qc_weight: float,
    ) -> Dict[str, Any]:
        updated = {}

        if stats["avg_user_rating"] is not None or stats["avg_qc_score"] is not None:
            new_overall = self._blend_quality_score(
                spec.quality_metrics.overall_score,
                stats,
                user_rating_weight,
                qc_weight,
            )
            if abs(new_overall - spec.quality_metrics.overall_score) > 0.01:
                updated["overall_score"] = {
                    "old": spec.quality_metrics.overall_score,
                    "new": round(new_overall, 2),
                }
                spec.quality_metrics.overall_score = round(new_overall, 2)

        if stats["avg_style_match"] is not None:
            new_val = self._blend_metric(spec.quality_metrics.style_accuracy, stats["avg_style_match"])
            if abs(new_val - spec.quality_metrics.style_accuracy) > 0.01:
                updated["style_accuracy"] = {"old": spec.quality_metrics.style_accuracy, "new": round(new_val, 4)}
                spec.quality_metrics.style_accuracy = round(new_val, 4)

        if stats["avg_prompt_adherence"] is not None:
            new_val = self._blend_metric(spec.quality_metrics.prompt_adherence, stats["avg_prompt_adherence"])
            if abs(new_val - spec.quality_metrics.prompt_adherence) > 0.01:
                updated["prompt_adherence"] = {"old": spec.quality_metrics.prompt_adherence, "new": round(new_val, 4)}
                spec.quality_metrics.prompt_adherence = round(new_val, 4)

        if stats["avg_visual_quality"] is not None:
            new_val = self._blend_metric(spec.quality_metrics.visual_quality, stats["avg_visual_quality"])
            if abs(new_val - spec.quality_metrics.visual_quality) > 0.01:
                updated["visual_quality"] = {"old": spec.quality_metrics.visual_quality, "new": round(new_val, 4)}
                spec.quality_metrics.visual_quality = round(new_val, 4)

        if stats["avg_character_consistency"] is not None:
            new_val = self._blend_metric(spec.quality_metrics.character_consistency, stats["avg_character_consistency"])
            if abs(new_val - spec.quality_metrics.character_consistency) > 0.01:
                updated["character_consistency"] = {"old": spec.quality_metrics.character_consistency, "new": round(new_val, 4)}
                spec.quality_metrics.character_consistency = round(new_val, 4)

        if stats["avg_motion_stability"] is not None:
            new_val = self._blend_metric(spec.quality_metrics.motion_stability, stats["avg_motion_stability"])
            if abs(new_val - spec.quality_metrics.motion_stability) > 0.01:
                updated["motion_stability"] = {"old": spec.quality_metrics.motion_stability, "new": round(new_val, 4)}
                spec.quality_metrics.motion_stability = round(new_val, 4)

        if stats["avg_latency"] is not None and stats["avg_latency"] > 0:
            old_latency = spec.avg_latency_seconds
            new_latency = old_latency * 0.7 + stats["avg_latency"] * 0.3
            if abs(new_latency - old_latency) > 1.0:
                updated["avg_latency_seconds"] = {"old": old_latency, "new": round(new_latency, 2)}
                spec.avg_latency_seconds = round(new_latency, 2)

        return updated

    def _blend_quality_score(
        self,
        current_score: float,
        stats: Dict[str, Any],
        user_weight: float,
        qc_weight: float,
    ) -> float:
        observed_score = 0.0
        total_weight = 0.0

        if stats["avg_user_rating"] is not None:
            normalized_user = (stats["avg_user_rating"] / 5.0) * 10.0
            observed_score += normalized_user * user_weight
            total_weight += user_weight

        if stats["avg_qc_score"] is not None:
            normalized_qc = stats["avg_qc_score"] * 10.0
            observed_score += normalized_qc * qc_weight
            total_weight += qc_weight

        if total_weight == 0:
            return current_score

        observed_score /= total_weight

        return current_score * 0.6 + observed_score * 0.4

    def _blend_metric(self, current: float, observed: float) -> float:
        return current * 0.6 + observed * 0.4


_feedback_loop_service: Optional[FeedbackLoopService] = None


def get_feedback_loop_service() -> FeedbackLoopService:
    global _feedback_loop_service
    if _feedback_loop_service is None:
        _feedback_loop_service = FeedbackLoopService()
    return _feedback_loop_service
