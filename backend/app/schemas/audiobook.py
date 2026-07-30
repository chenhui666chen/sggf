"""
有声书相关的请求/响应 Schema 定义
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AudiobookProjectCreate(BaseModel):
    """创建有声书项目请求"""
    project_id: int
    chapter_ids: List[int]
    tts_provider: str = "aliyun"
    enable_cache: bool = True
    voice_config: Optional[List["CharacterVoiceConfig"]] = None
    tts_model: Optional[str] = "qwen3-tts-instruct-flash"  # TTS 模型（qwen3-tts-instruct-flash / cosyvoice-v3.5-plus）
    generation_mode: str = "script_only"  # full: 直接生成音频; script_only: 仅生成剧本+评审
    force_regenerate_script: bool = True  # 是否强制重新生成剧本（覆盖已有剧本）
    narration_style: Optional[str] = "professional"  # 叙事风格: professional/dramatic/relaxing/expressive/custom
    narration_style_prompt: Optional[str] = None  # 自定义叙事风格prompt
    output_format: Optional[str] = "mp3"  # mp3/wav/m4b
    generate_subtitle: Optional[bool] = True  # 是否生成字幕文件


class GenerateAudioFromScriptsRequest(BaseModel):
    """基于已生成剧本的音频生成请求（两阶段流程第2阶段）"""
    chapter_ids: Optional[List[int]] = None
    tts_model: Optional[str] = "qwen3-tts-instruct-flash"  # TTS 模型（qwen3-tts-instruct-flash / cosyvoice-v3.5-plus）
    narration_style: Optional[str] = "professional"  # 叙事风格
    narration_style_prompt: Optional[str] = None  # 自定义叙事风格prompt
    output_format: Optional[str] = "mp3"  # mp3/wav/m4b
    generate_subtitle: Optional[bool] = True  # 是否生成字幕文件
    resume_from_checkpoint: Optional[bool] = True  # 是否从断点续传
    timeline_edits: Optional[Dict[str, Dict[str, float]]] = None  # 前端音频时间线调整（单章节生成时使用）


class ChapterScriptUpdateRequest(BaseModel):
    """更新章节剧本请求"""
    script_segments: List[dict]
    script_status: Optional[str] = None  # pending/reviewed/approved


class AudiobookDeleteRequest(BaseModel):
    """有声书项目删除请求。"""

    delete_reason: Optional[str] = None
    delete_files: bool = False

    @field_validator("delete_reason")
    @classmethod
    def normalize_delete_reason(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        reason = str(value).strip()
        return reason or None


class ChapterAudioDeleteRequest(AudiobookDeleteRequest):
    """章节音频删除请求。

    `delete_file` 为旧字段，仅用于兼容旧客户端；新调用统一使用 `delete_files`。
    """

    delete_file: Optional[bool] = Field(
        default=None,
        description="Deprecated: use delete_files.",
        json_schema_extra={"deprecated": True},
    )

    @model_validator(mode="after")
    def apply_deprecated_delete_file(self) -> "ChapterAudioDeleteRequest":
        if self.delete_file is not None:
            self.delete_files = bool(self.delete_file)
        return self


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
    tts_model: Optional[str] = None
    reference_source: Optional[str] = None
    reference_audio_url: Optional[str] = None
    voice_reference_asset_id: Optional[str] = None
    voice_pool_publication_id: Optional[str] = None


class TTSPreviewRequest(BaseModel):
    """TTS试听请求"""
    text: str
    voice_id: str = "male_young_energetic"
    volume: int = 50
    speed: Optional[float] = None
    pitch: Optional[int] = None
    model: Optional[str] = "qwen3-tts-instruct-flash"  # TTS 模型（默认 qwen3-tts-instruct-flash）
    voice_type: Optional[str] = None  # 声音类型（majestic/gentle/lively 等）
    instruction: Optional[str] = None


    voice_clone_data_url: Optional[str] = None
    voice_design_prompt: Optional[str] = None
    mimo_voice_asset_id: Optional[str] = None
    stepaudio_voice_asset_id: Optional[str] = None


class TTSPreviewWithTimestampsRequest(TTSPreviewRequest):
    """带时间戳的 TTS 试听请求"""
    word_timestamp_enabled: bool = True
    phoneme_timestamp_enabled: bool = False


class TTSPromptTestPreviewRequest(BaseModel):
    """独立 TTS 提示词测试试听请求。"""

    model: str
    case_id: str
    voice_id: str = ""
    voice_clone_data_url: Optional[str] = None
    voice_design_prompt: Optional[str] = None
    mimo_voice_asset_id: Optional[str] = None
    stepaudio_voice_asset_id: Optional[str] = None


class TTSPromptTestPreviewResponse(BaseModel):
    """独立 TTS 提示词测试试听响应。"""

    model: str
    case_id: str
    text: str
    voice_id: str
    style_control_mode: str
    provider_prompt_snapshot: Dict[str, Any]
    audio_data_base64: str
    audio_format: str
    audio_mime_type: str
    audio_size_bytes: int
    provider: Optional[str] = None
    provider_model: Optional[str] = None
    transport: Optional[str] = None


class SeedSceneTestReferenceRequest(BaseModel):
    """One existing TTS preview assigned to a Seed Audio test reference slot."""

    slot_id: str
    source_model: str
    source_voice_id: str
    audio_data_base64: Optional[str] = None
    audio_url: Optional[str] = None
    audio_mime_type: str = "audio/mpeg"

    @model_validator(mode="after")
    def validate_preview_source(self) -> "SeedSceneTestReferenceRequest":
        if self.audio_data_base64 and self.audio_url:
            raise ValueError("reference 的 audio_data_base64 和 audio_url 只能提供一种")
        return self


class SeedSceneTestPreviewRequest(BaseModel):
    """Independent Seed Audio scene test request."""

    case_id: str
    variant: str
    sample_index: int = Field(default=1, ge=1, le=3)
    references: List[SeedSceneTestReferenceRequest] = Field(default_factory=list)
    force_regenerate: bool = False


class SeedSceneTestPreviewResponse(BaseModel):
    """Reviewable Seed Audio scene test result."""

    model: str
    case_id: str
    variant: str
    sample_index: int
    sample_id: str
    blind_label: str
    prompt: str
    expected_texts: List[str]
    audio_data_base64: str
    audio_format: str
    audio_mime_type: str
    audio_size_bytes: int
    duration: Optional[float] = None
    subtitle: Any = None
    request_id: Optional[str] = None
    generation_latency_s: Optional[float] = None
    billing: Dict[str, Any]
    generation_status: str
    fallback_reason: Optional[str] = None
    quality_report: Dict[str, Any]
    references: List[Dict[str, Any]] = Field(default_factory=list)
    cached: bool = False


class SeedSceneBlindBatchSampleRequest(BaseModel):
    case_id: str = Field(min_length=1)
    variant: str = Field(min_length=1)
    sample_index: int = Field(ge=1, le=3)


class SeedSceneBlindBatchCreateRequest(BaseModel):
    samples: List[SeedSceneBlindBatchSampleRequest] = Field(min_length=1)


class SeedSceneBlindSample(BaseModel):
    anonymous_id: str
    blind_label: str


class SeedSceneBlindBatchResponse(BaseModel):
    schema_version: str
    batch_id: str
    locked: bool
    samples: List[SeedSceneBlindSample]


class SeedSceneBlindAudioResponse(BaseModel):
    anonymous_id: str
    blind_label: str
    audio_mime_type: str
    audio_data_base64: str


class SeedSceneBlindReviewFlags(BaseModel):
    dialogueComplete: bool
    plotUnderstandable: bool
    voicesDistinct: bool
    voiceConsistent: bool
    emotionNatural: bool
    effectsTimed: bool
    musicAppropriate: bool
    mixClear: bool
    usable: bool


class SeedSceneBlindReviewSubmitRequest(BaseModel):
    score: float = Field(ge=1, le=5)
    flags: SeedSceneBlindReviewFlags
    notes: str = Field(default="", max_length=2000)


class SeedSceneBlindReviewRecordResponse(BaseModel):
    schema_version: str
    batch_id: str
    anonymous_id: str
    reviewer_user_id: int
    score: float
    flags: Dict[str, bool]
    notes: str
    submitted_at: str
    locked: bool


class SeedSceneBlindReviewSummarySample(BaseModel):
    anonymous_id: str
    blind_label: str
    review_count: int
    average_score: Optional[float] = None
    flag_pass_rates: Dict[str, float]
    case_id: Optional[str] = None
    variant: Optional[str] = None
    sample_index: Optional[int] = None
    sample_id: Optional[str] = None


class SeedSceneBlindReviewSummaryResponse(BaseModel):
    schema_version: str
    batch_id: str
    sample_count: int
    completed_sample_count: int
    review_count: int
    reviewer_count: int
    identity_revealed: bool
    samples: List[SeedSceneBlindReviewSummarySample]


class TTSWordTimestamp(BaseModel):
    """词级时间戳"""
    text: str
    begin_index: int
    end_index: int
    begin_time: int
    end_time: int
    sentence_index: Optional[int] = None


class TTSPhonemeTimestamp(BaseModel):
    """音素级时间戳"""
    phoneme: str
    begin_time: int
    end_time: int
    sentence_index: Optional[int] = None
    word_text: Optional[str] = None
    word_begin_index: Optional[int] = None
    word_end_index: Optional[int] = None


class TTSSentenceTimestamp(BaseModel):
    """句级时间戳聚合"""
    index: Optional[int] = None
    type: Optional[str] = None
    original_text: Optional[str] = None
    words: List[TTSWordTimestamp] = Field(default_factory=list)


class TTSPreviewWithTimestampsResponse(BaseModel):
    """带时间戳的 TTS 试听响应"""
    model: str
    voice_id: str
    audio_data_base64: str
    audio_format: str
    audio_mime_type: str
    audio_size_bytes: int
    provider: Optional[str] = None
    provider_model: Optional[str] = None
    transport: Optional[str] = None
    word_timestamp_enabled: bool = False
    phoneme_timestamp_enabled: bool = False
    word_timestamps_available: bool = False
    phoneme_timestamps_available: bool = False
    tts_timestamps: List[TTSWordTimestamp] = Field(default_factory=list)
    tts_timestamp_sentences: List[TTSSentenceTimestamp] = Field(default_factory=list)
    phoneme_timestamps: List[TTSPhonemeTimestamp] = Field(default_factory=list)


class ScriptSegmentPreviewRequest(BaseModel):
    """剧本片段单段音频试听请求"""
    segment: Dict[str, Any]
    tts_model: Optional[str] = "qwen3-tts-instruct-flash"
    preview_type: Optional[str] = "voice"  # voice/sfx/bgm/mix


class SegmentRegenerateRequest(BaseModel):
    """单个片段重新生成请求"""
    segment_index: Optional[int] = None  # 片段在章节中的索引；路径参数已携带时可省略
    reason: Optional[str] = None  # 重新生成原因（可选，用于记录）
    tts_model: Optional[str] = None  # 可选：指定使用不同的 TTS 模型
    segment: Optional[Dict[str, Any]] = None
    preview_type: Optional[str] = "voice"
    voice_id: Optional[str] = None  # 可选：使用不同的音色
    emotion: Optional[str] = None  # 可选：调整情感


class SegmentRegenerationCandidateApplyRequest(BaseModel):
    """Apply a generated segment-audio candidate to script_json."""
    candidate_audio_path: str
    reason: Optional[str] = None
    segment: Optional[Dict[str, Any]] = None
    preview_type: Optional[str] = "voice"


class SegmentReviewRequest(BaseModel):
    """片段审查/评分请求"""
    segment_index: Optional[int] = None
    quality_score: Optional[float] = None  # 质量评分 1-5
    notes: Optional[str] = None  # 审查备注
    needs_regenerate: Optional[bool] = False  # 是否需要重新生成


class PromptAudioManualReviewRequest(BaseModel):
    """Prompt 与音频一致性人工验收请求"""

    model: str
    tag_parse_success: Optional[bool] = None
    text_contamination: Optional[bool] = None
    score: Optional[float] = Field(default=None, ge=0, le=5)
    notes: Optional[str] = None
    asr_transcript: Optional[str] = None

    @field_validator("model")
    @classmethod
    def normalize_model(cls, value: str) -> str:
        model = str(value or "").strip()
        if not model:
            raise ValueError("model 不能为空")
        return model

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        notes = str(value).strip()
        return notes or None

    @field_validator("asr_transcript")
    @classmethod
    def normalize_asr_transcript(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        transcript = str(value).strip()
        return transcript or None


class PromptAudioTranscriptQueueRequest(BaseModel):
    """手动 ASR 转写排队请求。"""

    model: Optional[str] = None
    provider: Optional[str] = None
    confirm_cost: bool = False

    @field_validator("model")
    @classmethod
    def normalize_transcript_model(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        model = str(value).strip()
        return model or None

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        provider = str(value).strip().lower()
        return provider or None


class ChapterReviewStatus(BaseModel):
    """章节整体审查状态"""
    chapter_id: int
    total_segments: int
    reviewed_segments: int
    avg_quality_score: Optional[float] = None
    flagged_segments: List[int] = []  # 标记需要重新生成的片段索引


class CosyVoiceCloneCreateRequest(BaseModel):
    """CosyVoice v3.5-plus 声音复刻请求（支持 http/https 或 oss:// 临时 URL）。"""

    # 用户希望显示的命名（可包含中文）。服务端会基于该名称自动生成合法 prefix。
    name: str
    url: str
    # 向后兼容：允许老版本前端直接传 prefix
    prefix: Optional[str] = None


class CosyVoiceDesignCreateRequest(BaseModel):
    """CosyVoice v3.5-plus 澹伴煶璁捐璇锋眰銆?"""

    name: str
    voice_prompt: str
    preview_text: str
    prefix: Optional[str] = None
    sample_rate: Optional[int] = 24000
    response_format: Optional[str] = "wav"


class MiMoVoiceCloneAssetCreateRequest(BaseModel):
    """MiMo Voice Clone 本地音色资产创建请求。"""

    name: str
    audio_data_url: str
    description: Optional[str] = None


class MiMoVoiceDesignAssetCreateRequest(BaseModel):
    """MiMo Voice Design 本地音色资产创建请求。"""

    name: str
    voice_design_prompt: str
    description: Optional[str] = None


class StepAudioVoiceCloneAssetCreateRequest(BaseModel):
    """StepAudio Voice Clone 本地参考样本资产创建请求。"""

    name: str
    sample_text: Optional[str] = None
    file_id: Optional[str] = None
    description: Optional[str] = None


class VoiceReferenceMaterializeRequest(BaseModel):
    """为用户设计音色生成可供 Seed Audio 引用的标准试听。"""

    source_asset_id: str = Field(min_length=1, max_length=160)
    confirm_cost: bool = False


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


class ChapterAudioRunResponse(BaseModel):
    """绔犺妭闊抽杩愯鎬佸搷搴斻€?"""

    id: int
    audiobook_project_id: int
    chapter_id: int
    run_type: str
    celery_task_id: Optional[str] = None
    status: str
    current_stage: Optional[str] = None
    progress: float = 0.0
    completed_segment_count: int = 0
    total_segment_count: int = 0
    tts_model: Optional[str] = None
    output_format: Optional[str] = None
    narration_style: Optional[str] = None
    narration_style_prompt: Optional[str] = None
    resumable: bool = True
    checkpoint_json: Dict[str, Any] = Field(default_factory=dict)
    temp_asset_prefix: Optional[str] = None
    expires_at: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
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
    completed_segment_indices: List[int] = Field(default_factory=list)
    cached_audio_paths: Dict[int, str] = Field(default_factory=dict)  # segment_index -> audio_path
    can_resume: bool = True
    run_id: Optional[int] = None
    run_status: Optional[str] = None
    current_stage: Optional[str] = None
    celery_task_id: Optional[str] = None
    generate_subtitle: bool = True
    checkpoint_source: Optional[str] = None
    checkpoint_schema_version: Optional[int] = None
    checkpoint_updated_at: Optional[str] = None
    checkpoint_expires_at: Optional[str] = None
    resume_validation_mode: Optional[str] = None
    resume_blockers: List[str] = Field(default_factory=list)
    resume_validation: Dict[str, Any] = Field(default_factory=dict)
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


class VoiceTypePresetResponse(BaseModel):
    """声音类型预设响应"""
    voice_type: str
    name: str
    description: str
    speed_modifier: float
    pitch_modifier: int
    volume_modifier: int
    emotion_tendency: str
    default_emotion: str
    compatible_personalities: List[str] = []
    suitable_scenarios: List[str] = []


class VoiceTypeRecommendationRequest(BaseModel):
    """声音类型推荐请求"""
    personality: Optional[str] = None
    gender: Optional[str] = None
    age_range: Optional[str] = None


class VoiceTypeRecommendationResponse(BaseModel):
    """声音类型推荐响应"""
    recommended_types: List[str]
    character_name: Optional[str] = None
