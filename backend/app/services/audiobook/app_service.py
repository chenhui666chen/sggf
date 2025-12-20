"""应用层服务：有声书相关用例的业务编排

当前主要负责：
- 校验项目归属与章节有效性
- 基于项目配置 / 请求参数 / 角色信息构建 voice_mapping
- 创建 AudiobookProject 记录

后续可以在此基础上逐步引入 Repository 层，进一步解耦 ORM 访问。
"""
import json
import logging
from typing import Dict, List

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.audiobook import AudiobookProject
from app.models.project import Project
from app.models.user import User
from app.schemas.audiobook import AudiobookProjectCreate, CharacterVoiceConfig
from app.services.audiobook.repository import (
    AudiobookProjectRepository,
    ChapterRepository,
    CharacterRepository,
    ProjectRepository,
)
from app.services.audiobook.voice_manager import VoiceManager

logger = logging.getLogger(__name__)


class AudiobookAppService:
    """有声书应用服务

    注意：
    - 该层承担用例级业务编排职责，不负责 HTTP 细节和后台任务调度。
    - 当前直接依赖 SQLAlchemy Session 和 FastAPI 的 HTTPException，
      后续如果需要可进一步抽象为领域服务 + Repository。
    """

    def __init__(self, db: Session, current_user: User) -> None:
        self.db = db
        self.current_user = current_user
        self.project_repo = ProjectRepository
        self.chapter_repo = ChapterRepository
        self.character_repo = CharacterRepository
        self.audiobook_repo = AudiobookProjectRepository

    # -------- 项目与章节校验 ---------
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

    def _validate_chapters(self, project_id: int, chapter_ids: List[int]) -> List[Project]:
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
    def _load_project_voice_mapping(self, project: Project) -> Dict[str, Dict]:
        """从项目级 audio_config 中加载默认角色音频配置。"""
        voice_mapping: Dict[str, Dict] = {}
        if not project.audio_config:
            return voice_mapping

        try:
            config = json.loads(project.audio_config)
        except Exception as e:  # noqa: BLE001
            logger.warning("⚠️ 解析项目级音频配置失败: %s", e)
            return voice_mapping

        for item in (config.get("characters") or []):
            name = item.get("name")
            if not name:
                continue
            voice_mapping[name] = {
                "voice_id": item.get("voice_id"),
                "volume": item.get("volume", 50),
                "speed": item.get("speed"),
                "pitch": item.get("pitch"),
            }

        return voice_mapping

    def _apply_request_voice_config(
        self,
        voice_mapping: Dict[str, Dict],
        voice_config: List[CharacterVoiceConfig] | None,
    ) -> None:
        """将本次请求中的角色音频配置合入 voice_mapping。"""
        if not voice_config:
            return

        for item in voice_config:
            voice_mapping[item.character_name] = {
                "voice_id": item.voice_id,
                "volume": item.volume,
                "speed": item.speed,
                "pitch": item.pitch,
            }

    def _auto_assign_voices(
        self,
        project_id: int,
        voice_mapping: Dict[str, Dict],
    ) -> None:
        """为缺少配置的角色自动分配音色（基于结构化人物卡）。"""
        try:
            characters = self.character_repo.list_by_project(self.db, project_id=project_id)

            vm = VoiceManager()

            def _build_traits_from_character(char) -> Dict:
                traits: Dict = {}
                gender = (char.gender or "").strip().lower()
                if gender in ("男", "male", "m", "man", "boy"):
                    traits["gender"] = "male"
                elif gender in ("女", "female", "f", "woman", "girl"):
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
                profile = vm.assign_voice(char.name, character_info=traits or None)

                voice_mapping[char.name] = {
                    "voice_id": profile.voice_id,
                    "volume": profile.volume_base,
                    "speed": profile.speed_base,
                    "pitch": profile.pitch_base,
                }

        except Exception as e:  # noqa: BLE001
            logger.warning("⚠️ 自动分配角色音色失败，将使用默认规则分配: %s", e)

    # -------- 对外用例方法 ---------
    def create_audiobook_project(self, request: AudiobookProjectCreate) -> AudiobookProject:
        """创建有声书项目（不包含后台任务调度）。"""
        logger.info(
            "🎙️ 用户 %s 创建有声书项目: project_id=%s",
            self.current_user.id,
            request.project_id,
        )

        # 1. 验证项目权限
        project = self._get_user_project(request.project_id)

        # 2. 验证章节
        self._validate_chapters(project.id, request.chapter_ids)

        # 3. 构建 voice_mapping
        voice_mapping_data = self._load_project_voice_mapping(project)
        self._apply_request_voice_config(voice_mapping_data, request.voice_config)
        self._auto_assign_voices(project.id, voice_mapping_data)

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

        logger.info("✅ 有声书项目创建成功: audiobook_project_id=%s", audiobook_project.id)

        return audiobook_project
