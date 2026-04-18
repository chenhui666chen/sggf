"""
有声书相关的请求/响应 Schema 定义
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


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
    narration_style: Optional[str] = "professional"  # 叙事风格: professional/dramatic/relaxing/expressive/custom
    narration_style_prompt: Optional[str] = None  # 自定义叙事风格prompt
    output_format: Optional[str] = "mp3"  # mp3/wav/m4b
    generate_subtitle: Optional[bool] = True  # 是否生成字幕文件


class GenerateAudioFromScriptsRequest(BaseModel):
    """基于已生成剧本的音频生成请求（两阶段流程第2阶段）"""
    chapter_ids: Optional[List[int]] = None
    tts_model: Optional[str] = "qwen3-tts-flash"  # TTS 模型（qwen3-tts-flash / cosyvoice-v3-plus）
    narration_style: Optional[str] = "professional"  # 叙事风格
    narration_style_prompt: Optional[str] = None  # 自定义叙事风格prompt
    output_format: Optional[str] = "mp3"  # mp3/wav/m4b
    generate_subtitle: Optional[bool] = True  # 是否生成字幕文件
    resume_from_checkpoint: Optional[bool] = True  # 是否从断点续传


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

    model_config = ConfigDict(from_attributes=True)


class ChapterAudioResponse(BaseModel):
    """章节音频响应"""
    id: int
    chapter_id: int
    chapter_number: Optional[int] = None
    audio_path: Optional[str]
    duration: float
    file_size: int
    tts_cost: float

    model_config = ConfigDict(from_attributes=True)


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


class SegmentRegenerateRequest(BaseModel):
    """单个片段重新生成请求"""
    segment_index: int  # 片段在章节中的索引
    reason: Optional[str] = None  # 重新生成原因（可选，用于记录）
    tts_model: Optional[str] = None  # 可选：指定使用不同的 TTS 模型
    voice_id: Optional[str] = None  # 可选：使用不同的音色
    emotion: Optional[str] = None  # 可选：调整情感


class SegmentReviewRequest(BaseModel):
    """片段审查/评分请求"""
    segment_index: int
    quality_score: Optional[float] = None  # 质量评分 1-5
    notes: Optional[str] = None  # 审查备注
    needs_regenerate: Optional[bool] = False  # 是否需要重新生成


class ChapterReviewStatus(BaseModel):
    """章节整体审查状态"""
    chapter_id: int
    total_segments: int
    reviewed_segments: int
    avg_quality_score: Optional[float] = None
    flagged_segments: List[int] = []  # 标记需要重新生成的片段索引


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

    model_config = ConfigDict(from_attributes=True)


class NarrationStylePreset(BaseModel):
    """叙事风格预设"""
    id: str
    name: str
    description: str
    emotion_profile: dict  # 情感参数配置
    speed_range: dict  # 语速范围
    pitch_range: dict  # 音调范围
    pause_multiplier: float  # 停顿倍数
    supported_models: List[str]  # 支持的模型列表


class SubtitleDownloadResponse(BaseModel):
    """字幕下载响应"""
    chapter_id: int
    subtitle_format: str
    subtitle_url: str
    subtitle_content: Optional[str] = None  # 直接返回字幕内容（用于预览）


class GenerationCheckpointResponse(BaseModel):
    """生成断点信息"""
    chapter_id: int
    total_segments: int
    completed_segments: int
    completed_segment_indices: List[int] = []
    cached_audio_paths: Dict[int, str] = {}  # segment_index -> audio_path
    can_resume: bool = True
    estimated_remaining_time: Optional[float] = None  # 预估剩余时间（秒）


class SmartChunkConfig(BaseModel):
    """智能分块配置"""
    enable_smart_chunk: bool = True  # 是否启用智能分块
    max_tokens: int = 1800  # 单个分块最大 token 数
    min_tokens: int = 50  # 最小分块 token 数
    chunking_strategy: str = "semantic"  # semantic/paragraph/sentence


class ChunkStats(BaseModel):
    """分块统计信息"""
    total_chunks: int
    total_tokens: int
    avg_tokens_per_chunk: float
    max_tokens_in_chunk: int
    min_tokens_in_chunk: int


class ChunkPreviewResponse(BaseModel):
    """分块预览响应"""
    original_segments: int
    chunked_segments: int
    total_tokens: int
    chunks: List[dict]  # 分块后的片段列表
    stats: ChunkStats
