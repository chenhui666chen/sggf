# -*- coding: utf-8 -*-
"""
Smart Dispatch API - Intent parsing + model routing + execution.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User

router = APIRouter(prefix="/api/v1/smart-dispatch", tags=["smart-dispatch"])


class IntentParseRequest(BaseModel):
    user_input: str = Field(..., min_length=1, max_length=5000, description="用户自然语言请求")
    context: Optional[Dict[str, Any]] = Field(default=None, description="附加上下文")


class IntentParseResponse(BaseModel):
    success: bool
    parsed_json: Dict[str, Any]
    task_spec: Dict[str, Any]
    confidence: float
    parse_errors: List[str]


class SmartDispatchRequest(BaseModel):
    user_input: str = Field(..., min_length=1, max_length=5000, description="用户自然语言请求")
    context: Optional[Dict[str, Any]] = Field(default=None, description="附加上下文")
    strategy: str = Field(default="balanced", description="调度策略: quality/cost/speed/balanced")
    use_fallback: bool = Field(default=True, description="是否启用回退机制")
    dry_run: bool = Field(default=False, description="仅解析+路由，不执行生成")


class SmartDispatchResponse(BaseModel):
    success: bool
    intent: Optional[Dict[str, Any]] = None
    routing: Optional[Dict[str, Any]] = None
    execution: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ModelRecommendRequest(BaseModel):
    user_input: str = Field(..., min_length=1, max_length=5000, description="用户自然语言请求")
    context: Optional[Dict[str, Any]] = Field(default=None, description="附加上下文")
    strategy: str = Field(default="balanced", description="调度策略: quality/cost/speed/balanced")


class ModelRecommendResponse(BaseModel):
    success: bool
    intent: Dict[str, Any]
    candidates: List[Dict[str, Any]]
    recommended: Optional[Dict[str, Any]] = None
    reasons: List[str]


class SemanticMatchRequest(BaseModel):
    user_input: str = Field(..., min_length=1, max_length=5000, description="用户输入/风格描述")
    style_hint: Optional[str] = Field(default=None, description="风格提示")
    scenario_hint: Optional[str] = Field(default=None, description="场景提示")
    top_k: int = Field(default=5, ge=1, le=20, description="返回Top-K匹配结果")


class SemanticMatchResponse(BaseModel):
    success: bool
    matches: List[Dict[str, Any]]
    detected_styles: List[str]
    detected_scenarios: List[str]


class StyleVocabularyResponse(BaseModel):
    success: bool
    styles: Dict[str, List[str]]
    scenarios: Dict[str, List[str]]


@router.post("/parse-intent", response_model=IntentParseResponse)
async def parse_intent(
    request: IntentParseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from core.intent_parser import get_intent_parser

    parser = get_intent_parser()
    result = await parser.parse(request.user_input, request.context, db_session=db)

    return IntentParseResponse(
        success=True,
        parsed_json=result.parsed_json,
        task_spec=result.task_spec.to_dict(),
        confidence=result.confidence,
        parse_errors=result.parse_errors,
    )


@router.post("/dispatch", response_model=SmartDispatchResponse)
async def smart_dispatch(
    request: SmartDispatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from core.intent_parser import get_intent_parser
    from core.router import router as smart_router

    parser = get_intent_parser()
    intent_result = await parser.parse(request.user_input, request.context, db_session=db)

    if intent_result.confidence < 0.3 and intent_result.parse_errors:
        return SmartDispatchResponse(
            success=False,
            intent=intent_result.to_dict(),
            error=f"意图解析置信度过低({intent_result.confidence:.2f}): {'; '.join(intent_result.parse_errors)}",
        )

    task = intent_result.task_spec

    try:
        routing_result = smart_router.route_with_fallback_by_strategy(
            task,
            request.strategy,
        )
    except ValueError as e:
        return SmartDispatchResponse(
            success=False,
            intent=intent_result.to_dict(),
            error=f"模型路由失败: {str(e)}",
        )

    routing_info = routing_result.to_dict()

    if request.dry_run:
        return SmartDispatchResponse(
            success=True,
            intent=intent_result.to_dict(),
            routing=routing_info,
        )

    from core.execution_engine import engine

    exec_result = engine.execute(
        task=task,
        strategy=request.strategy,
        use_fallback=request.use_fallback,
        routing_result=routing_result,
    )

    execution_info = exec_result.to_dict()

    return SmartDispatchResponse(
        success=exec_result.success,
        intent=intent_result.to_dict(),
        routing=routing_info,
        execution=execution_info,
        error=exec_result.error if not exec_result.success else None,
    )


@router.post("/recommend-models", response_model=ModelRecommendResponse)
async def recommend_models(
    request: ModelRecommendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from core.intent_parser import get_intent_parser
    from core.router import router as smart_router

    parser = get_intent_parser()
    intent_result = await parser.parse(request.user_input, request.context, db_session=db)

    task = intent_result.task_spec

    try:
        routing_result = smart_router.route_with_fallback_by_strategy(
            task,
            request.strategy,
            max_fallbacks=3,
        )
    except ValueError as e:
        return ModelRecommendResponse(
            success=False,
            intent=intent_result.parsed_json,
            candidates=[],
            recommended=None,
            reasons=[f"模型路由失败: {str(e)}"],
        )

    candidates = []
    all_models = [routing_result.selected_model] + routing_result.fallback_models
    for model in all_models:
        candidates.append({
            "model_id": model.id,
            "name": model.name,
            "provider": model.provider,
            "score": routing_result.score if model == routing_result.selected_model else 0.0,
            "modality": model.modality,
            "quality_score": model.quality_metrics.overall_score,
            "avg_latency": model.avg_latency_seconds,
            "cost": model.cost_profile.price,
            "recommended_scenarios": model.recommended_scenarios,
            "tags": model.tags,
        })

    recommended = candidates[0] if candidates else None

    return ModelRecommendResponse(
        success=True,
        intent=intent_result.parsed_json,
        candidates=candidates,
        recommended=recommended,
        reasons=routing_result.reasons,
    )


@router.post("/semantic-match", response_model=SemanticMatchResponse)
async def semantic_match(
    request: SemanticMatchRequest,
    current_user: User = Depends(get_current_user),
):
    from core.semantic_matcher import get_semantic_matcher

    matcher = get_semantic_matcher()

    try:
        results = matcher.match(
            request.user_input,
            style_hint=request.style_hint,
            scenario_hint=request.scenario_hint,
            top_k=request.top_k,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Semantic match failed: {str(e)}",
        )

    import numpy as np
    from core.semantic_matcher import _hash_embed, STYLE_VOCABULARY, SCENARIO_VOCABULARY

    query_emb = _hash_embed(request.user_input)
    detected_styles = []
    for style_name, keywords in STYLE_VOCABULARY.items():
        style_emb = _hash_embed(" ".join(keywords) + " " + style_name)
        from core.semantic_matcher import _cosine_similarity
        if _cosine_similarity(query_emb, style_emb) >= 0.3:
            detected_styles.append(style_name)

    detected_scenarios = []
    for scenario_name, keywords in SCENARIO_VOCABULARY.items():
        scenario_emb = _hash_embed(" ".join(keywords) + " " + scenario_name)
        if _cosine_similarity(query_emb, scenario_emb) >= 0.3:
            detected_scenarios.append(scenario_name)

    return SemanticMatchResponse(
        success=True,
        matches=[r.to_dict() for r in results],
        detected_styles=detected_styles,
        detected_scenarios=detected_scenarios,
    )


@router.get("/style-vocabulary", response_model=StyleVocabularyResponse)
async def get_style_vocabulary(
    current_user: User = Depends(get_current_user),
):
    from core.semantic_matcher import get_semantic_matcher

    matcher = get_semantic_matcher()
    return StyleVocabularyResponse(
        success=True,
        styles=matcher.get_all_styles(),
        scenarios=matcher.get_all_scenarios(),
    )
