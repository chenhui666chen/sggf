from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import Body, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.services.audiobook import AudiobookEngine
from app.services.audiobook.sse_progress import sse_tracker
from app.services.audiobook.smart_retrier import RetryConfig, default_retrier
from app.services.audiobook.preview_generator import default_preview_generator
from app.services.audiobook.repository import (
    AudiobookTaskRepository,
)
from app.services.audiobook.tts_model_ids import normalize_audiobook_tts_model

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)

@router.get("/tasks/{task_id}/stream")
async def stream_task_progress(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """SSE 实时进度推送端点

    客户端连接后将持续接收任务进度事件
    """
    from fastapi.responses import StreamingResponse

    task = AudiobookTaskRepository.get_task_for_user(db, task_id, current_user.id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务不存在: {task_id}",
        )
    # StreamingResponse 可能长时间保持连接，权限校验后不再占用数据库会话。
    db.close()

    async def event_generator():
        async for event in sse_tracker.stream_events(task_id):
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/previews/generate")
async def generate_preview(
    text: str = Body(..., embed=True),
    voice_id: str = Body(..., embed=True),
    tts_model: str = Body("qwen3-tts-instruct-flash", embed=True),
    emotion: Optional[str] = Body(None, embed=True),
    speed: Optional[float] = Body(None, embed=True),
    current_user: User = Depends(get_current_user),
):
    """快速生成试听片段（前 2 句）

    Args:
        text: 完整文本
        voice_id: 音色 ID
        tts_model: TTS 模型
        emotion: 情感参数
        speed: 语速参数
    """
    try:
        tts_model = normalize_audiobook_tts_model(tts_model)
        # 初始化 TTS 引擎
        from core.unified_llm_client import get_llm_client

        llm_client = get_llm_client(strategy="conservative")
        engine = AudiobookEngine(
            enable_cache=False,
            max_concurrent=1,
            llm_client=llm_client,
            tts_model=tts_model,
        )

        # 生成预览
        preview = default_preview_generator.generate_preview(
            text=text,
            voice_id=voice_id,
            tts_engine=engine,
            emotion=emotion,
            speed=speed,
        )

        return {
            "success": True,
            "preview": preview,
        }

    except Exception as e:
        logger.error(f"❌ 预览生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"预览生成失败: {str(e)}")


@router.get("/previews/{preview_id}")
async def get_generated_preview(
    preview_id: str,
    current_user: User = Depends(get_current_user),
):
    """读取快速试听片段文件。"""
    normalized_id = str(preview_id or "").strip()
    if not normalized_id or not normalized_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="无效的预览ID")

    preview_dir = Path(default_preview_generator.output_dir).resolve()
    file_path = (preview_dir / f"preview_{normalized_id}.mp3").resolve()
    if preview_dir not in file_path.parents and file_path.parent != preview_dir:
        raise HTTPException(status_code=400, detail="无效的预览路径")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="预览音频不存在")

    return FileResponse(
        path=str(file_path),
        media_type="audio/mpeg",
        filename=file_path.name,
        headers={"Content-Disposition": "inline"},
    )


@router.post("/retries/config")
async def configure_retry(
    max_retries: int = Body(3, embed=True),
    initial_delay: float = Body(1.0, embed=True),
    backoff_factor: float = Body(2.0, embed=True),
    enable_degraded: bool = Body(True, embed=True),
    current_user: User = Depends(get_current_user),
):
    """配置重试策略

    Args:
        max_retries: 最大重试次数
        initial_delay: 初始延迟（秒）
        backoff_factor: 退避因子
        enable_degraded: 是否启用降级
    """
    config = RetryConfig(
        max_retries=max_retries,
        initial_delay=initial_delay,
        backoff_factor=backoff_factor,
        enable_degraded=enable_degraded,
    )
    default_retrier.config = config
    return {
        "message": "默认重试配置已更新",
        "config": {
            "max_retries": config.max_retries,
            "initial_delay": config.initial_delay,
            "backoff_factor": config.backoff_factor,
            "enable_degraded": config.enable_degraded,
        },
    }
