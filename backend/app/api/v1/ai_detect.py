"""
AI 生成检测 API
调用朱雀 AIGC 检测（EdgeOne AI 网关 zhuque-text）检测文本的 AI 生成率
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Chapter
from app.services.zhuque_ai_detect import zhuque_ai_detect_service

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

    logger.info(f"开始 AI 检测，文本长度: {len(text)} 字符")

    # 调用朱雀网关（支持长文本，按千字计费，不截断）
    result = await zhuque_ai_detect_service.detect_ai_content(text)
    
    # 构建响应（朱雀无 label/suggestion 字段，保留 schema 兼容，置 None）
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
    检查朱雀网关配置状态
    """
    from app.core.config import settings

    gateway_configured = bool(getattr(settings, 'ZHUQUE_GATEWAY_URL', ''))
    api_key_configured = bool(getattr(settings, 'ZHUQUE_API_KEY', ''))

    return {
        "configured": gateway_configured and api_key_configured,
        "secret_id_set": gateway_configured,
        "secret_key_set": api_key_configured,
        "region": "",
        "biztype": f"provider=zhuque-text, is_merge={getattr(settings, 'ZHUQUE_IS_MERGE', False)}"
    }
