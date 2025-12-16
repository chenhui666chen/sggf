"""
耳畔星河 - 有声书生成API

功能：
1. 创建有声书项目
2. 生成章节音频
3. 查询生成进度
4. 下载音频文件
"""
import asyncio
import logging
import os
from urllib.parse import quote
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.models.project import Project, Chapter
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.services.audiobook import AudiobookEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/audiobook", tags=["audiobook"])


# ==================== Pydantic Schemas ====================

class AudiobookProjectCreate(BaseModel):
    """创建有声书项目请求"""
    project_id: int
    chapter_ids: List[int]
    tts_provider: str = "aliyun"
    enable_cache: bool = True


class AudiobookProjectResponse(BaseModel):
    """有声书项目响应"""
    id: int
    project_id: int
    status: str
    total_chapters: int
    completed_chapters: int
    failed_chapters: int
    total_duration: float
    total_cost: float
    created_at: str

    class Config:
        from_attributes = True


class ChapterAudioResponse(BaseModel):
    """章节音频响应"""
    id: int
    chapter_id: int
    audio_path: Optional[str]
    duration: float
    file_size: int
    tts_cost: float
    
    class Config:
        from_attributes = True


# ==================== API Endpoints ====================

@router.post("/projects", response_model=dict)
async def create_audiobook_project(
    request: AudiobookProjectCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    创建有声书项目并启动生成任务
    
    工作流：
    1. 验证项目和章节
    2. 创建有声书项目记录
    3. 后台异步生成音频
    """
    logger.info(f"🎙️ 用户 {current_user.id} 创建有声书项目: project_id={request.project_id}")
    
    # 1. 验证项目权限
    project = db.query(Project).filter(
        Project.id == request.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="项目不存在或无权限"
        )
    
    # 2. 验证章节
    chapters = db.query(Chapter).filter(
        Chapter.project_id == request.project_id,
        Chapter.id.in_(request.chapter_ids)
    ).all()
    
    if len(chapters) != len(request.chapter_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="部分章节不存在"
        )
    
    # 3. 创建有声书项目
    audiobook_project = AudiobookProject(
        project_id=request.project_id,
        status="pending",
        tts_provider=request.tts_provider,
        enable_cache=request.enable_cache,
        total_chapters=len(request.chapter_ids),
        completed_chapters=0,
        failed_chapters=0,
        total_duration=0.0,
        total_cost=0.0
    )
    
    db.add(audiobook_project)
    db.commit()
    db.refresh(audiobook_project)
    
    logger.info(f"✅ 有声书项目创建成功: audiobook_project_id={audiobook_project.id}")
    
    # 4. 后台启动生成任务
    background_tasks.add_task(
        generate_audiobook_background,
        audiobook_project_id=audiobook_project.id,
        chapter_ids=request.chapter_ids
    )
    
    return {
        "success": True,
        "audiobook_project_id": audiobook_project.id,
        "message": "有声书生成任务已启动",
        "total_chapters": len(request.chapter_ids)
    }


@router.get("/projects/{audiobook_project_id}", response_model=dict)
async def get_audiobook_project(
    audiobook_project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取有声书项目详情"""
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在"
        )
    
    # 验证权限
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问"
        )
    
    # 获取章节音频列表
    chapter_audios = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id
    ).all()
    
    return {
        "id": audiobook_project.id,
        "project_id": audiobook_project.project_id,
        "status": audiobook_project.status,
        "total_chapters": audiobook_project.total_chapters,
        "completed_chapters": audiobook_project.completed_chapters,
        "failed_chapters": audiobook_project.failed_chapters,
        "total_duration": audiobook_project.total_duration,
        "total_cost": audiobook_project.total_cost,
        "created_at": audiobook_project.created_at.isoformat() if audiobook_project.created_at else None,
        "chapter_audios": [
            {
                "id": ca.id,
                "chapter_id": ca.chapter_id,
                "task_id": ca.task_id,  # 新增：返回task_id
                "audio_path": ca.audio_path,
                "duration": ca.duration,
                "file_size": ca.file_size,
            }
            for ca in chapter_audios
        ]
    }


@router.get("/projects/by-project/{project_id}")
async def list_audiobook_projects(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取项目的所有有声书项目"""
    # 验证权限
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="项目不存在或无权限"
        )
    
    audiobook_projects = db.query(AudiobookProject).filter(
        AudiobookProject.project_id == project_id
    ).order_by(AudiobookProject.created_at.desc()).all()
    
    return [
        {
            "id": ap.id,
            "status": ap.status,
            "total_chapters": ap.total_chapters,
            "completed_chapters": ap.completed_chapters,
            "total_duration": ap.total_duration,
            "created_at": ap.created_at.isoformat() if ap.created_at else None,
        }
        for ap in audiobook_projects
    ]


@router.delete("/projects/{audiobook_project_id}")
async def delete_audiobook_project(
    audiobook_project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除有声书项目及其所有音频文件
    
    工作流：
    1. 验证权限
    2. 获取所有章节音频文件路径
    3. 删除物理文件
    4. 删除数据库记录（级联删除）
    """
    logger.info(f"🗑️ 用户 {current_user.id} 请求删除有声书项目: audiobook_project_id={audiobook_project_id}")
    
    # 1. 验证有声书项目是否存在
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在"
        )
    
    # 2. 验证原始项目权限
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限删除此项目"
        )
    
    # 3. 获取所有章节音频并删除文件
    chapter_audios = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id
    ).all()
    
    deleted_files = 0
    failed_files = []
    
    for chapter_audio in chapter_audios:
        if chapter_audio.audio_path and os.path.exists(chapter_audio.audio_path):
            try:
                os.remove(chapter_audio.audio_path)
                deleted_files += 1
                logger.info(f"✅ 删除文件: {chapter_audio.audio_path}")
            except Exception as e:
                logger.error(f"❌ 删除文件失败: {chapter_audio.audio_path}, 错误: {e}")
                failed_files.append(chapter_audio.audio_path)
    
    # 4. 删除数据库记录（级联删除会自动删除 ChapterAudio）
    db.delete(audiobook_project)
    db.commit()
    
    logger.info(f"✅ 有声书项目删除成功: audiobook_project_id={audiobook_project_id}, 删除文件数: {deleted_files}")
    
    return {
        "success": True,
        "message": "有声书项目已删除",
        "deleted_files": deleted_files,
        "failed_files": failed_files,
        "total_chapters": len(chapter_audios)
    }


@router.get("/tasks/{task_id}/status")
async def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    获取有声书生成任务状态
    
    返回各阶段的详细进度：
    - strategy: 策略制定
    - script_adaptation: 剧本改编
    - voice_design: 音色设计
    - sound_design: 音效设计
    - music_composition: 音乐编曲
    - tts_synthesis: TTS合成
    - audio_mixing: 音频混合
    - quality_review: 质量评审
    """
    # 获取全局Engine实例（或从缓存中获取）
    from app.services.audiobook import get_engine_instance
    
    engine = get_engine_instance()
    if not engine:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="有声书引擎未初始化"
        )
    
    task_status = engine.get_task_status(task_id)
    
    if not task_status:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务不存在: {task_id}"
        )
    
    return task_status


@router.get("/tasks")
async def list_all_tasks(
    current_user: User = Depends(get_current_user)
):
    """
    获取所有任务状态列表
    
    用于监控页面或调试
    """
    from app.services.audiobook import get_engine_instance
    
    engine = get_engine_instance()
    if not engine:
        return []
    
    return engine.get_all_tasks()


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
    
    # 1. 验证有声书项目权限
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在"
        )
    
    # 验证原始项目权限
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问"
        )
    
    # 2. 获取章节音频记录
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id
    ).first()
    
    if not chapter_audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节音频不存在"
        )
    
    # 3. 检查文件是否存在
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
    
    # 4. 获取章节标题作为文件名
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    filename = f"第{chapter.chapter_number}章-{chapter.title}.mp3" if chapter else f"chapter_{chapter_id}.mp3"
    
    # URL编码文件名（支持中文）
    encoded_filename = quote(filename)
    
    logger.info(f"✅ 返回音频文件: {file_path}")
    
    # 5. 返回文件
    return FileResponse(
        path=file_path,
        media_type="audio/mpeg",
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    流式播放章节音频（用于在线播放）
    
    返回：音频文件流（支持Range请求）
    """
    logger.info(f"🎵 用户 {current_user.id} 在线播放: audiobook_project_id={audiobook_project_id}, chapter_id={chapter_id}")
    
    # 1. 验证权限（同下载接口）
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在"
        )
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问"
        )
    
    # 2. 获取音频文件路径
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id
    ).first()
    
    if not chapter_audio or not chapter_audio.audio_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节音频不存在"
        )
    
    file_path = chapter_audio.audio_path
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"音频文件不存在: {file_path}"
        )
    
    logger.info(f"✅ 流式播放文件: {file_path}")
    
    # 3. 返回文件流（inline模式，浏览器直接播放）
    return FileResponse(
        path=file_path,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "inline",
            "Accept-Ranges": "bytes",
            "Access-Control-Expose-Headers": "Content-Length, Content-Range"
        }
    )


# ==================== Background Tasks ====================

async def generate_audiobook_background(
    audiobook_project_id: int,
    chapter_ids: List[int]
):
    """
    后台生成有声书任务
    
    流程：
    1. 初始化AudiobookEngine
    2. 逐章生成音频
    3. 更新进度和状态
    4. 保存音频文件
    """
    from app.db.base import SessionLocal
    db = SessionLocal()
    
    try:
        logger.info(f"🎙️ 开始后台生成有声书: audiobook_project_id={audiobook_project_id}")
        
        # 更新状态为处理中
        audiobook_project = db.query(AudiobookProject).filter(
            AudiobookProject.id == audiobook_project_id
        ).first()
        
        if not audiobook_project:
            logger.error(f"❌ 有声书项目不存在: {audiobook_project_id}")
            return
        
        audiobook_project.status = "processing"
        db.commit()
        
        # 初始化引擎（使用全局实例）
        from app.services.audiobook import get_engine_instance, set_engine_instance
        from app.services.llm_client import get_llm_client
        
        # 创建LLM客户端（必需）
        llm_client = get_llm_client(strategy="conservative")
        
        engine = AudiobookEngine(
            enable_cache=audiobook_project.enable_cache,
            max_concurrent=1,  # 降低并发避免限流
            llm_client=llm_client  # 必须传入LLM客户端
        )
        # 设置为全局实例，供状态查询使用
        set_engine_instance(engine)
        
        # 获取项目角色列表
        from app.models.character import Character
        characters = db.query(Character).filter(
            Character.project_id == audiobook_project.project_id
        ).all()
        character_list = [c.name for c in characters if c.name]
        
        logger.info(f"📝 角色列表: {character_list}")
        
        # 逐章生成
        total_duration = 0.0
        total_cost = 0.0
        
        for i, chapter_id in enumerate(chapter_ids, 1):
            try:
                logger.info(f"📖 处理章节 {i}/{len(chapter_ids)}: chapter_id={chapter_id}")
                
                # 获取章节内容
                chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
                if not chapter:
                    logger.warning(f"⚠️ 章节不存在: {chapter_id}")
                    audiobook_project.failed_chapters += 1
                    continue
                
                # 生成音频
                result = await engine.generate_chapter_audio(
                    chapter_content=chapter.content or "",
                    chapter_id=chapter_id,
                    character_list=character_list,
                    output_path=f"audiobooks/project_{audiobook_project.project_id}/chapter_{chapter.chapter_number:03d}.mp3"
                )
                
                # 记录task_id到数据库（可选）
                task_id = result.get('task_id')
                logger.info(f"🎯 TaskID: {task_id}")
                
                if result["success"]:
                    # 保存章节音频记录
                    chapter_audio = ChapterAudio(
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        task_id=task_id,  # 新增：保存task_id
                        audio_path=f"audiobooks/project_{audiobook_project.project_id}/chapter_{chapter.chapter_number:03d}.mp3",
                        duration=result["duration"],
                        file_size=result["file_size"],
                        segment_count=result["stats"]["parse_stats"]["total_segments"],
                        dialogue_count=result["stats"]["parse_stats"]["dialogue_count"],
                        narration_count=result["stats"]["parse_stats"]["narration_count"],
                        generation_time=float(result["stats"]["generation_time"].replace("秒", "")),
                        tts_cost=float(result["stats"]["tts_stats"]["estimated_cost"].replace("¥", "")),
                    )
                    db.add(chapter_audio)
                    
                    total_duration += result["duration"]
                    total_cost += float(result["stats"]["tts_stats"]["estimated_cost"].replace("¥", ""))
                    
                    audiobook_project.completed_chapters += 1
                    logger.info(f"✅ 章节 {chapter_id} 生成成功")
                else:
                    audiobook_project.failed_chapters += 1
                    logger.error(f"❌ 章节 {chapter_id} 生成失败: {result.get('error')}")
                
                # 更新进度
                audiobook_project.total_duration = total_duration
                audiobook_project.total_cost = total_cost
                db.commit()
                
            except Exception as e:
                logger.error(f"❌ 章节 {chapter_id} 处理异常: {e}")
                audiobook_project.failed_chapters += 1
                db.commit()
                import traceback
                traceback.print_exc()
        
        # 更新最终状态
        audiobook_project.status = "completed"
        audiobook_project.total_duration = total_duration
        audiobook_project.total_cost = total_cost
        db.commit()
        
        logger.info(f"🎉 有声书生成完成!")
        logger.info(f"   - 成功: {audiobook_project.completed_chapters}/{audiobook_project.total_chapters}")
        logger.info(f"   - 总时长: {total_duration:.1f}秒")
        logger.info(f"   - 总成本: ¥{total_cost:.2f}")
        
    except Exception as e:
        logger.error(f"❌ 后台生成任务失败: {e}")
        import traceback
        traceback.print_exc()
        
        # 更新状态为失败
        if audiobook_project:
            audiobook_project.status = "failed"
            db.commit()
    
    finally:
        db.close()
