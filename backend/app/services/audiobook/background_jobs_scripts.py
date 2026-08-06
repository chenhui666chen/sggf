from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.db.base import SessionLocal
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.character import Character
from app.models.project import Project
from app.services.audiobook.background_jobs_prefetch import prefetch_chapter_generation_records
from app.services.audiobook.background_jobs_shared import (
    create_background_engine,
    is_audiobook_project_active,
    is_chapter_generation_target_active,
    parse_duration_seconds,
    release_audiobook_project_billing,
)
from app.services.audiobook.chapter_character_scope import select_chapter_characters
from app.services.audiobook.job_tracker import handle_pause_checkpoint
from app.services.audiobook.repository import ChapterAudioRunRepository
from app.services.audiobook.tts_pause import AudiobookPauseRequested
from app.services.audiobook.project_audio_runtime import (
    apply_scene_audio_runtime_to_engine,
    resolve_project_audio_runtime_config,
)
from app.services.audiobook.task_support import (
    StageTracker,
    serialize_dataclass_to_dict,
    update_chapter_run_state as _update_chapter_run_state,
)

logger = logging.getLogger(__name__)


def _build_character_profiles(characters: List[Character]) -> List[Dict[str, Any]]:
    character_profiles: List[Dict[str, Any]] = []
    for character in characters:
        if not character.name:
            continue

        profile = {
            "name": character.name,
            "gender": character.gender,
            "age": character.age,
            "role": character.role,
            "role_position": character.role_position,
            "importance_level": character.importance_level,
            "faction": character.faction,
            "summary": character.summary,
            "tags": None,
            "relations": None,
        }
        if character.tags:
            try:
                profile["tags"] = (
                    json.loads(character.tags)
                    if isinstance(character.tags, str)
                    else character.tags
                )
            except (json.JSONDecodeError, TypeError):
                profile["tags"] = []
        if character.relations:
            try:
                from app.services.character_runtime_context import (
                    build_character_relations_payload,
                )

                relations_data = build_character_relations_payload(character.relations)
                profile["relations"] = (
                    relations_data.get("current_summary") if relations_data else None
                )
            except Exception:
                profile["relations"] = None
        character_profiles.append(profile)
    return character_profiles


def _load_existing_voice_mapping(engine, audiobook_project: AudiobookProject) -> None:
    if not audiobook_project.voice_mapping:
        return

    existing_voice_mapping = audiobook_project.voice_mapping
    if isinstance(existing_voice_mapping, str):
        try:
            existing_voice_mapping = json.loads(existing_voice_mapping)
        except (json.JSONDecodeError, TypeError) as load_err:
            logger.warning("⚠️ 从数据库加载音色分配失败: %s", load_err)
            return

    if not isinstance(existing_voice_mapping, dict) or not existing_voice_mapping:
        return

    try:
        engine.voice_manager.load_from_db(existing_voice_mapping)
    except Exception as load_err:
        logger.warning("⚠️ 从数据库加载音色分配失败: %s", load_err)
        return

    logger.info(
        "💾 已从数据库加载音色分配: %s 个角色",
        len(existing_voice_mapping),
    )


def _apply_script_stage_project_audio_config(
    *,
    engine,
    project: Optional[Project],
    tts_model: str,
    character_profiles: List[Dict[str, Any]],
) -> None:
    runtime_config = resolve_project_audio_runtime_config(
        project,
        tts_model=tts_model,
    )
    apply_scene_audio_runtime_to_engine(
        engine=engine,
        runtime_config=runtime_config,
    )
    effective_voice_mapping = runtime_config.voice_mapping

    for item in runtime_config.character_items:
        name = item.get("name")
        if not name:
            continue
        logger.info(
            "✅ [剧本阶段] 加载角色音配置: %s -> %s",
            name,
            item.get("voice_id"),
        )

    if effective_voice_mapping:
        try:
            engine.voice_manager.apply_project_voice_mapping(
                effective_voice_mapping,
                character_profiles=character_profiles,
            )
            logger.info(
                "🎛 [剧本阶段] 已加载角色音配置: %s 个角色",
                len(effective_voice_mapping),
            )
        except Exception as exc:
            logger.warning("⚠️ [剧本阶段] 应用角色音配置失败: %s", exc)

    if not runtime_config.audio_fx:
        return

    try:
        engine.apply_audio_fx_config(runtime_config.audio_fx)
        logger.info("🎚 [剧本阶段] 已加载项目级音效/BGM 配置")
    except Exception as exc:
        logger.warning("⚠️ [剧本阶段] 应用项目级音效/BGM 配置失败: %s", exc)


async def generate_audiobook_scripts_background(
    audiobook_project_id: int,
    chapter_ids: List[int],
    tts_model: str = "qwen3-tts-instruct-flash",
    force_regenerate: bool = False,
    tracker: Optional[StageTracker] = None,
    celery_task_id: Optional[str] = None,
) -> None:
    """后台生成有声书【剧本+评审】任务（不执行 TTS 和混音）。"""
    db = SessionLocal()
    db.expire_on_commit = False
    audiobook_project: Optional[AudiobookProject] = None

    try:
        logger.info("📝 开始后台生成有声书剧本: audiobook_project_id=%s", audiobook_project_id)

        audiobook_project = db.query(AudiobookProject).filter(
            AudiobookProject.id == audiobook_project_id,
            AudiobookProject.deleted_at.is_(None),
        ).first()
        if not audiobook_project:
            logger.error("❌ 有声书项目不存在: %s", audiobook_project_id)
            return

        audiobook_project.status = "processing"
        db.commit()

        engine = create_background_engine(
            audiobook_project=audiobook_project,
            chapter_ids=chapter_ids,
            tts_model=tts_model,
            tracker=tracker,
        )

        project = db.query(Project).filter(Project.id == audiobook_project.project_id).first()
        characters = db.query(Character).filter(
            Character.project_id == audiobook_project.project_id
        ).all()
        character_profiles = _build_character_profiles(characters)

        logger.info("📋 项目角色档案数量: %s", len(character_profiles))

        # 注入资产归属用户，使后台任务能解析项目所有者的私有音色资产
        # （mimo 声音设计/克隆），避免归属校验拒绝导致自定义音色静默失效。
        if project is not None and getattr(project, "user_id", None) is not None:
            engine.voice_manager.owner_user_id = int(project.user_id)

        _load_existing_voice_mapping(engine, audiobook_project)
        try:
            _apply_script_stage_project_audio_config(
                engine=engine,
                project=project,
                tts_model=tts_model,
                character_profiles=character_profiles,
            )
        except Exception as exc:
            logger.warning("⚠️ [剧本阶段] 加载项目级音频配置失败: %s", exc)

        generation_records = prefetch_chapter_generation_records(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_ids=chapter_ids,
        )
        chapter_by_id = generation_records.chapter_by_id
        chapter_audio_by_chapter_id = generation_records.chapter_audio_by_chapter_id

        failed_in_run = 0

        pause_check_fn = getattr(tracker, "is_pause_requested", None) if tracker else None

        for index, chapter_id in enumerate(chapter_ids, 1):
            if handle_pause_checkpoint(
                tracker,
                chapter_ids=chapter_ids,
                current_index=index,
            ):
                audiobook_project.status = "paused"
                db.commit()
                release_audiobook_project_billing(
                    logger,
                    db,
                    audiobook_project_id=audiobook_project_id,
                    reason="有声书剧本生成任务已暂停，已释放冻结积分。",
                )
                return
            try:
                logger.info(
                    "📖 [脚本阶段] 处理章节 %s/%s: chapter_id=%s",
                    index,
                    len(chapter_ids),
                    chapter_id,
                )

                run_id: Optional[int] = None
                if celery_task_id:
                    dispatch_run = ChapterAudioRunRepository.get_run_by_celery_task_id(
                        db,
                        celery_task_id=celery_task_id,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="script_only",
                    )
                    run_id = dispatch_run.id if dispatch_run else None

                # 章节可能在排队或上一次 LLM 调用期间被删除；先挡住本轮所有写入。
                if not is_chapter_generation_target_active(
                    db,
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    run_id=run_id,
                ):
                    logger.info(
                        "章节产物已删除，跳过剧本生成: audiobook_project_id=%s chapter_id=%s",
                        audiobook_project_id,
                        chapter_id,
                    )
                    continue

                chapter = chapter_by_id.get(chapter_id)
                if not chapter:
                    logger.warning("⚠️ 章节不存在: %s", chapter_id)
                    audiobook_project.failed_chapters += 1
                    failed_in_run += 1
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="script_only",
                        status="failed",
                        current_stage="failed",
                        progress=0.0,
                        error_message="chapter_not_found",
                        run_id=run_id,
                    )
                    continue

                chapter_audio = chapter_audio_by_chapter_id.get(chapter_id)

                if chapter_audio and chapter_audio.script_json and not force_regenerate:
                    if chapter_audio.script_status in ["reviewed", "approved"]:
                        logger.info(
                            "✅ [跳过] 章节 %s 已有%s剧本，保持不变",
                            chapter_id,
                            chapter_audio.script_status,
                        )
                        audiobook_project.completed_chapters += 1
                        _update_chapter_run_state(
                            db,
                            audiobook_project_id=audiobook_project_id,
                            chapter_id=chapter_id,
                            run_type="script_only",
                            status="completed",
                            current_stage="completed",
                            progress=1.0,
                            total_segment_count=chapter_audio.segment_count or 0,
                            completed_segment_count=chapter_audio.segment_count or 0,
                            checkpoint_patch={
                                "reuse_existing_script": True,
                                "script_status": chapter_audio.script_status,
                            },
                            run_id=run_id,
                        )
                        db.commit()
                        continue

                    logger.info(
                        "🔄 [覆盖] 章节 %s 剧本状态为%s，将重新生成",
                        chapter_id,
                        chapter_audio.script_status,
                    )
                elif force_regenerate and chapter_audio and chapter_audio.script_json:
                    logger.info("🔄 [强制重生成] 章节 %s 将覆盖现有剧本", chapter_id)

                chapter_characters, _ = select_chapter_characters(
                    chapters=[chapter],
                    characters=characters,
                )
                character_list = [
                    character.name for character in chapter_characters if character.name
                ]
                chapter_character_profiles = _build_character_profiles(chapter_characters)
                logger.info(
                    "📝 章节 %s 剧本人物范围: %s",
                    chapter_id,
                    character_list,
                )

                result = await engine.prepare_chapter_script(
                    chapter_content=chapter.content or "",
                    chapter_id=chapter_id,
                    character_list=character_list,
                    character_profiles=chapter_character_profiles,
                    novel_genre=str(getattr(project, "genre", "") or "").strip() or "通用",
                    audiobook_project_id=audiobook_project_id,
                    chapter_title=chapter.title or "",
                    chapter_summary=chapter.summary or "",
                    summary_data=chapter.summary_data,
                    pause_check=pause_check_fn,
                )

                if not result.get("success"):
                    raise RuntimeError(
                        f"剧本生成失败: {result.get('error') or '未知错误'}"
                    )

                original_chapter_audio_id = getattr(chapter_audio, "id", None)
                if not is_chapter_generation_target_active(
                    db,
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    chapter_audio_id=original_chapter_audio_id,
                    run_id=run_id,
                ):
                    logger.info(
                        "章节在剧本生成期间被删除，放弃写回 script_json: "
                        "audiobook_project_id=%s chapter_id=%s",
                        audiobook_project_id,
                        chapter_id,
                    )
                    db.rollback()
                    continue

                if original_chapter_audio_id is not None:
                    # 使用刚刚确认过的活动记录，避免把已删除的旧 ORM 对象重新挂回会话。
                    chapter_audio = (
                        db.query(ChapterAudio)
                        .filter(
                            ChapterAudio.id == original_chapter_audio_id,
                            ChapterAudio.audiobook_project_id == audiobook_project_id,
                            ChapterAudio.chapter_id == chapter_id,
                            ChapterAudio.deleted_at.is_(None),
                        )
                        .populate_existing()
                        .first()
                    )
                    if chapter_audio is None:
                        db.rollback()
                        continue

                if not chapter_audio:
                    chapter_audio = ChapterAudio(
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                    )
                    db.add(chapter_audio)
                    db.flush()
                    chapter_audio_by_chapter_id[chapter_id] = chapter_audio

                # 新建记录 flush 后再次确认父项目/章节仍有效；删除竞态下回滚本轮对象，
                # 避免提交一个孤立的 ChapterAudio。
                if not is_chapter_generation_target_active(
                    db,
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    chapter_audio_id=chapter_audio.id,
                    run_id=run_id,
                ):
                    logger.info(
                        "章节在剧本写回前被删除，放弃提交 ChapterAudio: "
                        "audiobook_project_id=%s chapter_id=%s",
                        audiobook_project_id,
                        chapter_id,
                    )
                    db.rollback()
                    chapter_audio_by_chapter_id.pop(chapter_id, None)
                    continue

                stats = result.get("stats", {})
                parse_stats = stats.get("parse_stats", {})

                chapter_audio.segment_count = parse_stats.get("total_segments", 0)
                chapter_audio.dialogue_count = parse_stats.get("dialogue_count", 0)
                chapter_audio.narration_count = parse_stats.get("narration_count", 0)
                chapter_audio.character_count = stats.get("characters", 0)

                generation_time = parse_duration_seconds(stats.get("generation_time", "0秒"))
                if generation_time is not None:
                    chapter_audio.generation_time = generation_time

                chapter_audio.script_json = json.dumps(
                    serialize_dataclass_to_dict(result.get("script_segments") or []),
                    ensure_ascii=False,
                )
                chapter_audio.script_review_json = json.dumps(
                    serialize_dataclass_to_dict(result.get("quality_report") or {}),
                    ensure_ascii=False,
                )
                if not chapter_audio.script_status or force_regenerate:
                    chapter_audio.script_status = "pending"
                else:
                    logger.info(
                        "✅ 保留章节 %s 剧本状态: %s",
                        chapter_id,
                        chapter_audio.script_status,
                    )

                if not is_chapter_generation_target_active(
                    db,
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    chapter_audio_id=chapter_audio.id,
                    run_id=run_id,
                ):
                    logger.info(
                        "章节在 script_json 提交前已删除，回滚本轮写入: "
                        "audiobook_project_id=%s chapter_id=%s",
                        audiobook_project_id,
                        chapter_id,
                    )
                    db.rollback()
                    if original_chapter_audio_id is None:
                        chapter_audio_by_chapter_id.pop(chapter_id, None)
                    continue

                _update_chapter_run_state(
                    db,
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    run_type="script_only",
                    status="completed",
                    current_stage="completed",
                    progress=1.0,
                    total_segment_count=parse_stats.get("total_segments", 0),
                    completed_segment_count=parse_stats.get("total_segments", 0),
                    checkpoint_patch={
                        "engine_task_id": result.get("task_id"),
                        "script_status": chapter_audio.script_status,
                    },
                    run_id=run_id,
                )
                audiobook_project.completed_chapters += 1

                try:
                    voice_mapping_to_save = engine.voice_manager.export_to_db()
                    if voice_mapping_to_save:
                        existing_mapping = audiobook_project.voice_mapping or {}
                        if isinstance(existing_mapping, str):
                            try:
                                existing_mapping = json.loads(existing_mapping)
                            except (json.JSONDecodeError, TypeError):
                                existing_mapping = {}
                        if not isinstance(existing_mapping, dict):
                            existing_mapping = {}

                        audiobook_project.voice_mapping = {
                            **existing_mapping,
                            **voice_mapping_to_save,
                        }
                        logger.info(
                            "💾 已保存音色分配到数据库: %s 个角色",
                            len(voice_mapping_to_save),
                        )
                except Exception as save_err:
                    logger.warning("⚠️ 保存音色分配到数据库失败: %s", save_err)

                db.commit()

            except AudiobookPauseRequested:
                # 章节剧本生成过程中收到暂停请求：落库为 paused（包含当前章节），
                # 恢复时重新生成该章节剧本，不当作失败处理
                logger.info("⏸️ [脚本阶段] 章节 %s 生成中被暂停请求中断", chapter_id)
                handle_pause_checkpoint(
                    tracker,
                    chapter_ids=chapter_ids,
                    current_index=index,
                    stage="script_adaptation",
                )
                audiobook_project.status = "paused"
                db.commit()
                release_audiobook_project_billing(
                    logger,
                    db,
                    audiobook_project_id=audiobook_project_id,
                    reason="有声书剧本生成任务已暂停，已释放冻结积分。",
                )
                return
            except Exception as exc:
                logger.error("❌ [脚本阶段] 章节 %s 处理异常: %s", chapter_id, exc)
                audiobook_project.failed_chapters += 1
                failed_in_run += 1
                _update_chapter_run_state(
                    db,
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    run_type="script_only",
                    status="failed",
                    current_stage="failed",
                    progress=0.0,
                    error_message=str(exc),
                    run_id=run_id,
                )
                db.commit()
                import traceback

                traceback.print_exc()

        # 本次运行有失败章节时置为 failed，避免掩盖局部失败
        if not is_audiobook_project_active(
            db,
            audiobook_project_id=audiobook_project_id,
        ):
            logger.info(
                "有声书项目已删除，跳过 script_only 任务最终状态写回: audiobook_project_id=%s",
                audiobook_project_id,
            )
            return

        audiobook_project.status = "completed" if failed_in_run == 0 else "failed"
        db.commit()

        if failed_in_run:
            logger.warning("⚠️ 有声书剧本生成结束，但本次运行有 %s 个章节失败", failed_in_run)
        else:
            logger.info("🎉 有声书剧本生成完成!")
        logger.info(
            "   - 成功: %s/%s",
            audiobook_project.completed_chapters,
            audiobook_project.total_chapters,
        )
    finally:
        db.close()


__all__ = ["generate_audiobook_scripts_background"]
