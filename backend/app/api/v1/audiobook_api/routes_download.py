from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_current_user, get_current_user_optional
from app.db.base import get_db
from app.models.user import User
from app.models.audiobook import ChapterAudio
from app.services.audiobook.repository import ChapterRepository, UserRepository
from app.services.audiobook.safe_filename import build_safe_filename

from app.api.v1.audiobook_api import router
from app.api.v1.audiobook_api.dependencies import (
    get_active_chapter_audio_for_project,
    resolve_owned_audiobook_project,
)

logger = logging.getLogger(__name__)

STREAM_TOKEN_PURPOSE = "audiobook_stream"
STREAM_TOKEN_TTL_SECONDS = 2 * 60 * 60


def _get_audio_media_type(file_path: str) -> str:
    extension = Path(file_path).suffix.lstrip(".").lower() or "mp3"
    return {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "m4b": "audio/mp4",
        "m4a": "audio/mp4",
    }.get(extension, "application/octet-stream")


def _create_stream_access_token(
    *,
    user_id: int,
    audiobook_project_id: int,
    chapter_id: int,
) -> tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=STREAM_TOKEN_TTL_SECONDS)
    payload = {
        "sub": str(user_id),
        "purpose": STREAM_TOKEN_PURPOSE,
        "audiobook_project_id": audiobook_project_id,
        "chapter_id": chapter_id,
        "exp": expires_at,
    }
    token = jwt.encode(
        payload,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return token, expires_at


def _resolve_stream_token_user(
    *,
    db: Session,
    token: str,
    audiobook_project_id: int,
    chapter_id: int,
) -> User:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid stream token",
        ) from exc

    try:
        token_project_id = int(payload.get("audiobook_project_id") or 0)
        token_chapter_id = int(payload.get("chapter_id") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid stream token",
        ) from exc

    if (
        payload.get("purpose") != STREAM_TOKEN_PURPOSE
        or token_project_id != audiobook_project_id
        or token_chapter_id != chapter_id
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid stream token",
        )

    try:
        user_id = int(payload.get("sub") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid stream token",
        ) from exc

    if user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid stream token",
        )

    user = UserRepository.get_active_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid stream token",
        )
    return user


def _resolve_owned_chapter_audio_file(
    *,
    db: Session,
    current_user: User,
    audiobook_project_id: int,
    chapter_id: int,
) -> tuple[ChapterAudio, Any | None, str, str]:
    resolve_owned_audiobook_project(
        db=db,
        current_user=current_user,
        audiobook_project_id=audiobook_project_id,
    )
    try:
        chapter_audio = get_active_chapter_audio_for_project(
            db=db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="章节音频不存在",
            ) from exc
        raise

    if not chapter_audio.audio_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="音频文件路径不存在"
        )

    file_path = chapter_audio.audio_path
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"音频文件不存在: {file_path}"
        )

    chapter = ChapterRepository.get_active_by_id(db, chapter_id)
    return chapter_audio, chapter, file_path, _get_audio_media_type(file_path)


@router.get("/stream-url/{audiobook_project_id}/{chapter_id}")
async def create_chapter_audio_stream_url(
    audiobook_project_id: int,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    创建短期签名播放 URL。

    原生 audio 标签无法携带 Bearer header，因此播放器需要一个短期 token URL。
    """
    _, _, _, _ = _resolve_owned_chapter_audio_file(
        db=db,
        current_user=current_user,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )
    token, expires_at = _create_stream_access_token(
        user_id=current_user.id,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )
    encoded_token = quote(token, safe="")
    return {
        "stream_url": (
            f"/api/v1/audiobook/stream/{audiobook_project_id}/{chapter_id}"
            f"?play_token={encoded_token}"
        ),
        "expires_at": expires_at.isoformat(),
        "expires_in_seconds": STREAM_TOKEN_TTL_SECONDS,
    }


@router.get("/download/{audiobook_project_id}/{chapter_id}")
async def download_chapter_audio(
    audiobook_project_id: int,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    下载章节音频文件
    
    返回：MP3音频文件流
    """
    logger.info(f"🎧 用户 {current_user.id} 下载音频: audiobook_project_id={audiobook_project_id}, chapter_id={chapter_id}")
    
    _, chapter, file_path, media_type = _resolve_owned_chapter_audio_file(
        db=db,
        current_user=current_user,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )

    # 获取章节标题作为文件名
    extension = Path(file_path).suffix.lstrip(".").lower() or "mp3"
    if chapter:
        filename = build_safe_filename(
            f"第{chapter.chapter_number}章-{chapter.title}",
            extension,
            fallback=f"chapter_{chapter_id}",
        )
    else:
        filename = build_safe_filename(f"chapter_{chapter_id}", extension, fallback="chapter")
    
    # URL编码文件名（支持中文）
    encoded_filename = quote(filename)
    
    logger.info(f"✅ 返回音频文件: {file_path}")
    
    # 5. 返回文件
    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=filename,  # 保留原始文件名（供浏览器显示）
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )


@router.get("/stream/{audiobook_project_id}/{chapter_id}")
async def stream_chapter_audio(
    audiobook_project_id: int,
    chapter_id: int,
    play_token: str | None = Query(default=None),
    current_user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """
    流式播放章节音频（用于在线播放）
    
    返回：音频文件流（支持Range请求）
    """
    if play_token:
        resolved_user = _resolve_stream_token_user(
            db=db,
            token=play_token,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
        )
    elif current_user:
        resolved_user = current_user
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing stream credentials",
        )

    logger.info(f"🎵 用户 {resolved_user.id} 在线播放: audiobook_project_id={audiobook_project_id}, chapter_id={chapter_id}")
    
    _, _, file_path, media_type = _resolve_owned_chapter_audio_file(
        db=db,
        current_user=resolved_user,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )
    
    logger.info(f"✅ 流式播放文件: {file_path}")

    # 返回文件流（inline模式，浏览器直接播放；Bearer 鉴权场景下前端仍需要 fetch Blob）
    return FileResponse(
        path=file_path,
        media_type=media_type,
        headers={
            "Content-Disposition": "inline",
            "Accept-Ranges": "bytes",
            "Access-Control-Expose-Headers": "Content-Length, Content-Range"
        }
    )


# ==================== 剧本编辑与音频生成（两阶段相关） ====================
