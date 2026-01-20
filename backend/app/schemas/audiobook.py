"""
有声书相关的请求/响应 Schema 定义
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class AudiobookProjectCreate(BaseModel):
    """创建有声书项目请求"""
    project_id: int
    chapter_ids: List[int]
    tts_provider: str = "aliyun"
    enable_cache: bool = True
    voice_config: Optional[List["CharacterVoiceConfig"]] = None
    tts_model: Optional[str] = "qwen3-tts-flash"  # TTS 模型（qwen3-tts-flash / cosyvoice-v3-plus）
    generation_mode: str = "full"  # full: 直接生成音频; script_only: 仅生成剧本+评审
    force_regenerate_script: bool = False  # 🆕 是否强制重新生成剧本（覆盖已有剧本）


class GenerateAudioFromScriptsRequest(BaseModel):
    """基于已生成剧本的音频生成请求（两阶段流程第2阶段）"""
    chapter_ids: Optional[List[int]] = None
    tts_model: Optional[str] = "qwen3-tts-flash"  # TTS 模型（qwen3-tts-flash / cosyvoice-v3-plus）


class ChapterScriptUpdateRequest(BaseModel):
    """更新章节剧本请求"""
    script_segments: List[dict]
    script_status: Optional[str] = None  # pending/reviewed/approved


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
    chapter_number: Optional[int] = None
    audio_path: Optional[str]
    duration: float
    file_size: int
    tts_cost: float

    class Config:
        from_attributes = True


class CharacterVoiceConfig(BaseModel):
    """角色音频配置（用户可选）"""
    character_name: str
    voice_id: str
    volume: int = 50
    speed: Optional[float] = None
    pitch: Optional[int] = None


class TTSPreviewRequest(BaseModel):
    """TTS试听请求"""
    text: str
    voice_id: str = "male_young_energetic"
    volume: int = 50
    speed: Optional[float] = None
    pitch: Optional[int] = None
    model: Optional[str] = "qwen3-tts-flash"  # TTS 模型（默认 qwen3-tts-flash）


class ScriptSegmentPreviewRequest(BaseModel):
    """剧本片段单段音频试听请求"""
    segment: Dict[str, Any]
    tts_model: Optional[str] = "qwen3-tts-flash"
    preview_type: Optional[str] = "voice"  # voice/sfx/bgm/mix


class CosyVoiceCloneCreateRequest(BaseModel):
    """CosyVoice v3-plus 声音复刻请求（支持 http/https 或 oss:// 临时 URL）。"""

    # 用户希望显示的命名（可包含中文）。服务端会基于该名称自动生成合法 prefix。
    name: str
    url: str
    # 向后兼容：允许老版本前端直接传 prefix
    prefix: Optional[str] = None


class AudiobookTaskStatus(BaseModel):
    """Celery 任务状态响应"""
    celery_task_id: Optional[str]
    audiobook_project_id: int
    chapter_id: Optional[int]
    task_type: str
    status: str
    current_stage: Optional[str] = None
    progress: float = 0.0
    completed_units: int = 0
    total_units: int = 0
    detail: Optional[dict] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    class Config:
        from_attributes = True
