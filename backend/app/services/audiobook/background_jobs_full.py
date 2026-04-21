from __future__ import annotations

import json
import logging
from typing import List, Optional

from app.db.base import SessionLocal
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.character import Character
from app.models.project import Chapter, Project
from app.services.audiobook.background_jobs_shared import (
    create_background_engine,
    parse_duration_seconds,
    parse_estimated_cost,
)
from app.services.audiobook.task_support import (
    StageTracker,
    serialize_dataclass_to_dict,
    update_chapter_run_state as _update_chapter_run_state,
)
from app.services.user_center_points_events import (
    record_audiobook_billing_release,
    record_audiobook_billing_settle,
)

logger = logging.getLogger(__name__)


def _apply_project_audio_effects(*, engine, audiobook_project: AudiobookProject, project: Optional[Project]) -> None:
    if project and project.audio_config:
        try:
            from app.services.audiobook.project_audio_config import get_audio_fx
            from app.services.audiobook.project_audio_config import parse_project_audio_config

            config_data = parse_project_audio_config(project.audio_config or "")
            audio_fx = get_audio_fx(config_data)
        except Exception as parse_err:
            logger.warning("⚠️ 解析项目级音频配置失败: %s", parse_err)
            audio_fx = None

        if audio_fx:
            try:
                engine.apply_audio_fx_config(audio_fx)
                logger.info("🎚 已加载项目级音效/BGM 配置")
            except Exception as exc:
                logger.warning("⚠️ 应用项目级音效/BGM 配置失败: %s", exc)

    if audiobook_project.voice_mapping:
        try:
            engine.voice_manager.apply_project_voice_mapping(audiobook_project.voice_mapping)
            logger.info(
                "🎛 已加载项目级角色音配置: %s 个角色",
                len(audiobook_project.voice_mapping),
            )
        except Exception as exc:
            logger.warning("⚠️ 应用项目级角色音配置失败: %s", exc)


async def generate_audiobook_background(
    audiobook_project_id: int,
    chapter_ids: List[int],
    tts_model: str = "qwen3-tts-instruct-flash",
    tracker: Optional[StageTracker] = None,
) -> None:
    """后台生成有声书任务。"""
    db = SessionLocal()
    audiobook_project: Optional[AudiobookProject] = None

    try:
        logger.info("🎙️ 开始后台生成有声书: audiobook_project_id=%s", audiobook_project_id)

        audiobook_project = db.query(AudiobookProject).filter(
            AudiobookProject.id == audiobook_project_id
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
        try:
            _apply_project_audio_effects(
                engine=engine,
                audiobook_project=audiobook_project,
                project=project,
            )
        except Exception as exc:
            logger.warning("⚠️ 加载项目级音频配置失败: %s", exc)

        characters = db.query(Character).filter(
            Character.project_id == audiobook_project.project_id
        ).all()
        character_list = [character.name for character in characters if character.name]
        logger.info("📝 角色列表: %s", character_list)

        total_duration = 0.0
        total_cost = 0.0

        for index, chapter_id in enumerate(chapter_ids, 1):
            try:
                logger.info(
                    "📖 处理章节 %s/%s: chapter_id=%s",
                    index,
                    len(chapter_ids),
                    chapter_id,
                )

                chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
                if not chapter:
                    logger.warning("⚠️ 章节不存在: %s", chapter_id)
                    audiobook_project.failed_chapters += 1
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="full",
                        status="failed",
                        current_stage="failed",
                        progress=0.0,
                        error_message="chapter_not_found",
                    )
                    continue

                output_path = (
                    f"audiobooks/project_{audiobook_project.project_id}"
                    f"/chapter_{chapter.chapter_number:03d}.mp3"
                )
                result = await engine.generate_chapter_audio(
                    chapter_content=chapter.content or "",
                    chapter_id=chapter_id,
                    character_list=character_list,
                    output_path=output_path,
                    chapter_title=chapter.title or "",
                    chapter_summary=chapter.summary or "",
                    summary_data=chapter.summary_data,
                )

                task_id = result.get("task_id")
                logger.info("🎯 TaskID: %s", task_id)

                if result["success"]:
                    chapter_audio = db.query(ChapterAudio).filter(
                        ChapterAudio.audiobook_project_id == audiobook_project_id,
                        ChapterAudio.chapter_id == chapter_id,
                    ).first()

                    if not chapter_audio:
                        chapter_audio = ChapterAudio(
                            audiobook_project_id=audiobook_project_id,
                            chapter_id=chapter_id,
                        )
                        db.add(chapter_audio)
                        logger.info("🆕 创建新的章节音频记录: chapter_id=%s", chapter_id)
                    else:
                        logger.info("♻️ 更新已有章节音频记录: chapter_id=%s", chapter_id)
                        if chapter_audio.script_json:
                            logger.info(
                                "✅ 保留已有剧本（status=%s）",
                                chapter_audio.script_status,
                            )

                    chapter_audio.task_id = task_id
                    chapter_audio.audio_path = output_path
                    chapter_audio.duration = result["duration"]
                    chapter_audio.file_size = result["file_size"]

                    stats = result.get("stats", {})
                    parse_stats = stats.get("parse_stats", {})
                    tts_stats = stats.get("tts_stats", {})

                    script_payload = result.get("script_segments_payload") or []
                    if script_payload:
                        chapter_audio.script_json = json.dumps(
                            serialize_dataclass_to_dict(script_payload),
                            ensure_ascii=False,
                        )
                        chapter_audio.script_status = "pending"
                        quality_detail = result.get("quality_report_detail")
                        if quality_detail:
                            chapter_audio.script_review_json = json.dumps(
                                serialize_dataclass_to_dict(quality_detail),
                                ensure_ascii=False,
                            )

                    chapter_audio.segment_count = parse_stats.get("total_segments", 0)
                    chapter_audio.dialogue_count = parse_stats.get("dialogue_count", 0)
                    chapter_audio.narration_count = parse_stats.get("narration_count", 0)

                    generation_time = parse_duration_seconds(
                        stats.get("generation_time", "0秒")
                    )
                    if generation_time is not None:
                        chapter_audio.generation_time = generation_time

                    cost = parse_estimated_cost(tts_stats.get("estimated_cost", "¥0.00"))
                    if cost is not None:
                        chapter_audio.tts_cost = cost

                    total_duration += result["duration"]
                    if cost is not None:
                        total_cost += cost

                    audiobook_project.completed_chapters += 1
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="full",
                        status="completed",
                        current_stage="completed",
                        progress=1.0,
                        total_segment_count=parse_stats.get("total_segments", 0),
                        completed_segment_count=parse_stats.get("total_segments", 0),
                        checkpoint_patch={
                            "engine_task_id": task_id,
                            "output_path": output_path,
                        },
                    )
                    logger.info("✅ 章节 %s 生成成功", chapter_id)
                else:
                    audiobook_project.failed_chapters += 1
                    logger.error("❌ 章节 %s 生成失败: %s", chapter_id, result.get("error"))
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="full",
                        status="failed",
                        current_stage="failed",
                        progress=0.0,
                        error_message=str(result.get("error") or "full_generation_failed"),
                    )

                audiobook_project.total_duration = total_duration
                audiobook_project.total_cost = total_cost
                db.commit()

            except Exception as exc:
                logger.error("❌ 章节 %s 处理异常: %s", chapter_id, exc)
                audiobook_project.failed_chapters += 1
                _update_chapter_run_state(
                    db,
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    run_type="full",
                    status="failed",
                    current_stage="failed",
                    progress=0.0,
                    error_message=str(exc),
                )
                db.commit()
                import traceback

                traceback.print_exc()

        audiobook_project.status = "completed"
        audiobook_project.total_duration = total_duration
        audiobook_project.total_cost = total_cost
        db.commit()

        try:
            record_audiobook_billing_settle(db=db, audiobook_project_id=audiobook_project_id)
        except Exception as exc:
            logger.warning(
                "记录有声书积分结算失败 audiobook_project_id=%s: %s",
                audiobook_project_id,
                exc,
            )

        logger.info("🎉 有声书生成完成!")
        logger.info(
            "   - 成功: %s/%s",
            audiobook_project.completed_chapters,
            audiobook_project.total_chapters,
        )
        logger.info("   - 总时长: %.1f秒", total_duration)
        logger.info("   - 总成本: ¥%.2f", total_cost)
    except Exception as exc:
        logger.error("❌ 后台生成任务失败: %s", exc)
        import traceback

        traceback.print_exc()

        if audiobook_project:
            audiobook_project.status = "failed"
            db.commit()
            try:
                record_audiobook_billing_release(
                    db=db,
                    audiobook_project_id=audiobook_project_id,
                    reason="有声书生成失败，已释放冻结积分。",
                )
            except Exception as release_exc:
                logger.warning(
                    "释放有声书冻结积分失败 audiobook_project_id=%s: %s",
                    audiobook_project_id,
                    release_exc,
                )
    finally:
        db.close()


__all__ = ["generate_audiobook_background"]
