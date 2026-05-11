"""应用层服务：有声书相关用例的业务编排。

职责：
- 校验项目归属与章节有效性
- 基于项目配置 / 请求参数 / 角色信息构建 voice_mapping
- 创建 AudiobookProject 记录
"""
import json
import logging
from dataclasses import dataclass
from typing import Dict, List

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.project import Chapter, Project
from app.models.user import User
from app.schemas.audiobook import AudiobookProjectCreate, CharacterVoiceConfig
from app.services.audiobook.repository import (
    AudiobookProjectRepository,
    ChapterRepository,
    CharacterRepository,
    ProjectRepository,
)
from app.services.audiobook.project_audio_runtime import resolve_project_audio_runtime_config
from app.services.audiobook.voice_auto_assignment import AutoVoiceAssignmentPool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedAudiobookProjectCreation:
    project: Project
    chapters: List[Chapter]


class AudiobookAppService:
    """有声书应用服务。

    注意：
    - 本层承担用例级业务编排，不负责 HTTP 细节与后台任务调度。
    - 当前直接依赖 SQLAlchemy Session 与 FastAPI HTTPException；如需更强解耦，可进一步抽象为领域服务 + Repository。
    """
    def __init__(self, db: Session, current_user: User) -> None:
        self.db = db
        self.current_user = current_user
        self.project_repo = ProjectRepository
        self.chapter_repo = ChapterRepository
        self.character_repo = CharacterRepository
        self.audiobook_repo = AudiobookProjectRepository

    # -------- 项目与章节校验 --------
    def _get_user_project(self, project_id: int) -> Project:
        project = self.project_repo.get_user_project(
            self.db, user_id=self.current_user.id, project_id=project_id
        )
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="项目不存在或无权限",
            )
        return project

    def _validate_chapters(self, project_id: int, chapter_ids: List[int]) -> List[Chapter]:
        if not chapter_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="章节列表不能为空",
            )

        chapters = self.chapter_repo.get_project_chapters_by_ids(
            self.db, project_id=project_id, chapter_ids=chapter_ids
        )

        if len(chapters) != len(chapter_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="部分章节不存在",
            )

        return chapters

    # -------- voice_mapping 构建逻辑 ---------
    def prepare_audiobook_project_creation(
        self,
        request: AudiobookProjectCreate,
    ) -> PreparedAudiobookProjectCreation:
        validated_project = self._get_user_project(request.project_id)
        chapters = self._validate_chapters(validated_project.id, request.chapter_ids)
        return PreparedAudiobookProjectCreation(project=validated_project, chapters=chapters)

    def _load_project_voice_mapping(self, project: Project, tts_model: str) -> Dict[str, Dict]:
        return resolve_project_audio_runtime_config(
            project,
            tts_model=tts_model,
        ).voice_mapping

    def _apply_request_voice_config(
        self,
        voice_mapping: Dict[str, Dict],
        voice_config: List[CharacterVoiceConfig] | None,
    ) -> None:
        """将本次请求中的角色音频配置合并到 voice_mapping（优先覆盖）。"""
        if not voice_config:
            return

        for item in voice_config:
            voice_mapping[item.character_name] = {
                "voice_id": item.voice_id,
                "volume": item.volume,
                "speed": item.speed,
                "pitch": item.pitch,
                "tts_model": item.tts_model,
                "voice_type": item.voice_type,
                "personality": item.personality,
                "emotion_tendency": item.emotion_tendency,
            }

    def _auto_assign_voices(
        self,
        project_id: int,
        voice_mapping: Dict[str, Dict],
        tts_model: str,
    ) -> None:
        """为缺少配置的角色自动分配音色（基于结构化人物信息）。"""
        try:
            characters = self.character_repo.list_by_project(self.db, project_id=project_id)

            auto_voice_pool = AutoVoiceAssignmentPool(
                preferred_model=tts_model,
                existing_assignments=voice_mapping.values(),
            )

            def _build_traits_from_character(char) -> Dict:
                traits: Dict = {}
                gender = (char.gender or "").strip().lower()
                if gender in ("男", "男性", "male", "m", "man", "boy"):
                    traits["gender"] = "male"
                elif gender in ("女", "女性", "female", "f", "woman", "girl"):
                    traits["gender"] = "female"

                if char.age is not None:
                    age = char.age
                    if age < 12:
                        traits["age_group"] = "child"
                    elif age < 18:
                        traits["age_group"] = "teen"
                    elif age < 30:
                        traits["age_group"] = "young"
                    elif age < 60:
                        traits["age_group"] = "adult"
                    else:
                        traits["age_group"] = "elder"

                # 简单用重要程度影响性格倾向
                importance = (char.importance_level or "").strip()
                if importance:
                    if "主角" in importance or "重要" in importance:
                        traits.setdefault("personality", "energetic")
                    elif "龙套" in importance or "群众" in importance:
                        traits.setdefault("personality", "calm")

                return traits

            for char in characters:
                # 已有配置（项目级或本次请求）优先，不自动覆盖
                existing = voice_mapping.get(char.name)
                if existing and existing.get("voice_id"):
                    continue

                traits = _build_traits_from_character(char)
                assignment = auto_voice_pool.assign(char.name, traits or None)
                profile = assignment.profile

                voice_mapping[char.name] = {
                    "voice_id": profile.voice_id,
                    "volume": profile.volume_base,
                    "speed": profile.speed_base,
                    "pitch": profile.pitch_base,
                    "tts_model": assignment.model,
                }

        except Exception as e:  # noqa: BLE001
            logger.warning("自动分配角色音色失败，将回退到默认规则: %s", e)

    def _clone_existing_scripts(
        self,
        audiobook_project: AudiobookProject,
        chapter_ids: List[int],
    ) -> int:
        """为新建的 audiobook_project 复用最近一次生成的剧本，直到用户主动重生成。"""
        reused = 0
        if not chapter_ids:
            return reused

        for chapter_id in chapter_ids:
            existing = (
                self.db.query(ChapterAudio)
                .join(AudiobookProject, ChapterAudio.audiobook_project_id == AudiobookProject.id)
                .filter(
                    AudiobookProject.project_id == audiobook_project.project_id,
                    ChapterAudio.chapter_id == chapter_id,
                    ChapterAudio.script_json.isnot(None),
                )
                .order_by(ChapterAudio.updated_at.desc())
                .first()
            )
            if not existing:
                continue

            clone = ChapterAudio(
                audiobook_project_id=audiobook_project.id,
                chapter_id=chapter_id,
                script_json=existing.script_json,
                script_review_json=existing.script_review_json,
                script_status=existing.script_status or "pending",
                segment_count=existing.segment_count,
                dialogue_count=existing.dialogue_count,
                narration_count=existing.narration_count,
                character_count=existing.character_count,
            )
            self.db.add(clone)
            reused += 1

        if reused:
            self.db.commit()
            logger.info("♻️ 复用 %s 个章节的已有剧本供新项目 %s 使用", reused, audiobook_project.id)
        return reused

    # -------- 对外用例方法 ---------
    def create_audiobook_project(
        self,
        request: AudiobookProjectCreate,
        *,
        prepared: PreparedAudiobookProjectCreation | None = None,
    ) -> AudiobookProject:
        logger.info(
            "创建有声书项目 user_id=%s project_id=%s",
            self.current_user.id,
            request.project_id,
        )

        # 1. 验证项目权限
        prepared_request = prepared or self.prepare_audiobook_project_creation(request)
        project = prepared_request.project

        # 2. 验证章节

        # 3. 构建 voice_mapping
        tts_model = (request.tts_model or "qwen3-tts-instruct-flash").strip()
        voice_mapping_data = self._load_project_voice_mapping(project, tts_model)
        self._apply_request_voice_config(voice_mapping_data, request.voice_config)
        self._auto_assign_voices(project.id, voice_mapping_data, tts_model)

        # 4. 创建 AudiobookProject
        audiobook_project = AudiobookProject(
            project_id=request.project_id,
            status="pending",
            tts_provider=request.tts_provider,
            voice_mapping=voice_mapping_data,
            enable_cache=request.enable_cache,
            total_chapters=len(request.chapter_ids),
            completed_chapters=0,
            failed_chapters=0,
            total_duration=0.0,
            total_cost=0.0,
        )

        self.db.add(audiobook_project)
        self.db.commit()
        self.db.refresh(audiobook_project)

        logger.info("有声书项目创建成功 audiobook_project_id=%s", audiobook_project.id)

        # 5. 复用最近一次的剧本，除非用户要求强制重新生成剧本
        if request.force_regenerate_script:
            logger.info(
                "跳过复用已有剧本: audiobook_project_id=%s force_regenerate_script=true",
                audiobook_project.id,
            )
        else:
            try:
                self._clone_existing_scripts(audiobook_project, request.chapter_ids)
            except Exception as exc:  # noqa: BLE001
                logger.warning("复用已有剧本失败：%s", exc)

        return audiobook_project
