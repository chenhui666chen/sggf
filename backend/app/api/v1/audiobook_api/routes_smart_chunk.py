from __future__ import annotations

from typing import List

from fastapi import Body, Depends

from app.core.security import get_current_user
from app.models.user import User
from app.schemas.audiobook import (
    VoiceTypeRecommendationRequest,
)
from app.services.audiobook.smart_chunker import SmartChunker
from app.services.audiobook.voice_types import (
    get_all_voice_types,
    recommend_voice_type,
)

from app.api.v1.audiobook_api import router

@router.post("/smart-chunk/preview")
async def preview_smart_chunking(
    segments: List[dict],
    max_tokens: int = 1800,
    min_tokens: int = 50,
    current_user: User = Depends(get_current_user),
):
    """预览智能分块结果（不实际执行）

    Args:
        segments: 原始剧本片段列表
        max_tokens: 单个分块最大 token 数
        min_tokens: 最小分块 token 数
    """
    chunker = SmartChunker(max_tokens=max_tokens, min_tokens=min_tokens)

    # 对片段列表进行分块
    chunked_segments = chunker.chunk_segments(segments)

    # 计算统计信息
    total_tokens = sum(chunker.estimate_tokens(s.get("text", "")) for s in chunked_segments)
    token_list = [chunker.estimate_tokens(s.get("text", "")) for s in chunked_segments]

    stats = {
        "total_chunks": len(chunked_segments),
        "total_tokens": total_tokens,
        "avg_tokens_per_chunk": total_tokens / len(chunked_segments) if chunked_segments else 0,
        "max_tokens_in_chunk": max(token_list) if token_list else 0,
        "min_tokens_in_chunk": min(token_list) if token_list else 0,
    }

    return {
        "original_segments": len(segments),
        "chunked_segments": len(chunked_segments),
        "total_tokens": total_tokens,
        "chunks": chunked_segments,
        "stats": stats,
    }


@router.post("/smart-chunk/estimate")
async def estimate_text_tokens(
    text: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
):
    """估算文本的 token 数量"""
    chunker = SmartChunker()
    estimated = chunker.estimate_tokens(text)
    needs_chunking = chunker.needs_chunking(text)

    return {
        "text_length": len(text),
        "estimated_tokens": estimated,
        "needs_chunking": needs_chunking,
        "max_tokens": chunker.max_tokens,
    }


@router.get("/voice-types")
async def list_voice_types(
    current_user: User = Depends(get_current_user),
):
    """获取所有声音类型预设列表"""
    return get_all_voice_types()


@router.post("/voice-types/recommend")
async def recommend_voice_types(
    request: VoiceTypeRecommendationRequest,
    current_user: User = Depends(get_current_user),
):
    """根据角色属性推荐声音类型"""
    recommended = recommend_voice_type(
        personality=request.personality,
        gender=request.gender,
        age_range=request.age_range,
    )
    return {
        "recommended_types": recommended,
        "character_name": None,
    }


