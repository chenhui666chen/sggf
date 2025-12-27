"""
AI 生成检测 API
调用腾讯云文本内容安全 API 检测文本的 AI 生成率
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Chapter
from app.services.tencent_ai_detect import tencent_ai_detect_service

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai-detect", tags=["AI Detect"])


class AIDetectRequest(BaseModel):
    """AI 检测请求"""
    text: Optional[str] = None
    chapter_id: Optional[int] = None


class AIDetectResponse(BaseModel):
    """AI 检测响应"""
    success: bool
    ai_score: Optional[int] = None
    label: Optional[str] = None
    suggestion: Optional[str] = None
    error: Optional[str] = None
    text_length: Optional[int] = None
    text_preview: Optional[str] = None


@router.post("", response_model=AIDetectResponse)
async def detect_ai_content(
    request: AIDetectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    检测文本的 AI 生成率
    
    可以通过以下两种方式之一提供待检测文本：
    1. 直接提供 text 参数
    2. 提供 chapter_id，自动获取章节内容
    """
    text = request.text
    
    # 如果提供了 chapter_id，获取章节内容
    if request.chapter_id and not text:
        chapter = db.query(Chapter).filter(Chapter.id == request.chapter_id).first()
        if not chapter:
            raise HTTPException(status_code=404, detail="章节不存在")
        text = chapter.content
    
    if not text:
        raise HTTPException(status_code=400, detail="请提供待检测的文本内容或章节 ID")
    
    # 文本长度限制（腾讯云 API 限制 10000 个字符）
    if len(text) > 10000:
        logger.warning(f"文本过长 ({len(text)} 字符)，截取前 10000 字符进行检测")
        text = text[:10000]
    
    logger.info(f"开始 AI 检测，文本长度: {len(text)} 字符")
    
    # 调用腾讯云 API
    result = await tencent_ai_detect_service.detect_ai_content(text)
    
    # 构建响应
    response = AIDetectResponse(
        success=result.get("success", False),
        ai_score=result.get("ai_score"),
        label=result.get("label"),
        suggestion=result.get("suggestion"),
        error=result.get("error"),
        text_length=len(text),
        text_preview=text[:100] + "..." if len(text) > 100 else text
    )
    
    logger.info(f"AI 检测完成: success={response.success}, ai_score={response.ai_score}")
    
    return response


@router.get("/config-status")
async def get_config_status(
    current_user: User = Depends(get_current_user)
):
    """
    检查腾讯云 API 配置状态
    """
    from app.core.config import settings
    
    secret_id_configured = bool(getattr(settings, 'TENCENT_SECRET_ID', ''))
    secret_key_configured = bool(getattr(settings, 'TENCENT_SECRET_KEY', ''))
    
    return {
        "configured": secret_id_configured and secret_key_configured,
        "secret_id_set": secret_id_configured,
        "secret_key_set": secret_key_configured,
        "region": getattr(settings, 'TENCENT_REGION', 'ap-guangzhou'),
        "biztype": getattr(settings, 'TENCENT_BIZTYPE', '') or "未设置（使用默认策略）"
    }
