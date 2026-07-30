from __future__ import annotations

import json
import logging
from typing import List, Optional

from app.db.base import SessionLocal
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.character import Character
from app.models.project import Project
from app.services.audiobook.background_jobs_prefetch import prefetch_chapter_generation_records
from app.services.audiobook.background_jobs_shared import (
    apply_chapter_audio_generation_result,
    build_checkpoint_patch_from_generation_result,
    create_background_engine,
    generate_and_apply_subtitle_artifacts,
    mark_chapter_generation_failed,
    mark_chapter_preflight_failed,
    prepare_chapter_generation_output_context,
    prune_and_log_completed_run_temp_assets,
    refresh_audiobook_project_audio_totals,
    release_audiobook_project_billing,
    settle_audiobook_project_billing,
)
from app.services.audiobook.chapter_character_scope import select_chapter_characters
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


def _apply_project_audio_effects(
    *,
    engine,
    audiobook_project: AudiobookProject,
    project: Optional[Project],
    tts_model: str,
) -> None:
    runtime_config = resolve_project_audio_runtime_config(
        project,
        tts_model=tts_model,
        base_voice_mapping=audiobook_project.voice_mapping or {},
    )
    apply_scene_audio_runtime_to_engine(
        engine=engine,
        runtime_config=runtime_config,
    )

    if runtime_config.audio_fx:
        try:
            engine.apply_audio_fx_config(runtime_config.audio_fx)
            logger.info("🎚 已加载项目级音效/BGM 配置")
        except Exception as exc:
            logger.warning("⚠️ 应用项目级音效/BGM 配置失败: %s", exc)

    if runtime_config.voice_mapping:
        try:
            engine.voice_manager.apply_project_voice_mapping(runtime_config.voice_mapping)
            logger.info(
                "🎛 已加载项目级角色音配置: %s 个角色",
                len(runtime_config.voice_mapping),
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
    db.expire_on_commit = False
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
                tts_model=tts_model,
            )
        except Exception as exc:
            logger.warning("⚠️ 加载项目级音频配置失败: %s", exc)

        characters = db.query(Character).filter(
            Character.project_id == audiobook_project.project_id
        ).all()
        generation_records = prefetch_chapter_generation_records(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_ids=chapter_ids,
        )
        chapter_by_id = generation_records.chapter_by_id
        chapter_audio_by_chapter_id = generation_records.chapter_audio_by_chapter_id

        current_run_failed_chapters = 0
        refresh_audiobook_project_audio_totals(
            db,
            audiobook_project=audiobook_project,
            failed_chapters=current_run_failed_chapters,
        )
        db.commit()

        for index, chapter_id in enumerate(chapter_ids, 1):
            chapter = None
            resume_checkpoint = {}
            task_id = None
            result = None
            try:
                logger.info(
                    "📖 处理章节 %s/%s: chapter_id=%s",
                    index,
                    len(chapter_ids),
                    chapter_id,
                )

                chapter = chapter_by_id.get(chapter_id)
                if not chapter:
                    logger.warning("⚠️ 章节不存在: %s", chapter_id)
                    current_run_failed_chapters = mark_chapter_preflight_failed(
                        db,
                        audiobook_project=audiobook_project,
                        chapter_id=chapter_id,
                        run_type="full",
                        error_message="chapter_not_found",
                        failed_chapters=current_run_failed_chapters,
                    )
                    db.commit()
                    continue

                output_context = prepare_chapter_generation_output_context(
                    db,
                    engine=engine,
                    audiobook_project=audiobook_project,
                    chapter_id=chapter_id,
                    chapter_number=chapter.chapter_number,
                    run_type="full",
                )
                resume_checkpoint = output_context.resume_checkpoint
                output_format = output_context.output_format
                generate_subtitle = output_context.generate_subtitle
                output_path = output_context.output_path

                chapter_characters, _ = select_chapter_characters(
                    chapters=[chapter],
                    characters=characters,
                )
                character_list = [
                    character.name
                    for character in chapter_characters
                    if character.name
                ]
                logger.info("📝 章节 %s 人物范围: %s", chapter_id, character_list)

                result = await engine.generate_chapter_audio(
                    chapter_content=chapter.content or "",
                    chapter_id=chapter_id,
                    character_list=character_list,
                    output_path=output_path,
                    output_format=output_format,
                    chapter_title=chapter.title or "",
                    chapter_summary=chapter.summary or "",
                    summary_data=chapter.summary_data,
                    resume_checkpoint=resume_checkpoint,
                    tts_progress_callback=output_context.tts_progress_callback,
                )

                task_id = result.get("task_id")
                logger.info("🎯 TaskID: %s", task_id)

                if result["success"]:
                    chapter_audio = chapter_audio_by_chapter_id.get(chapter_id)

                    if not chapter_audio:
                        chapter_audio = ChapterAudio(
                            audiobook_project_id=audiobook_project_id,
                            chapter_id=chapter_id,
                        )
                        db.add(chapter_audio)
                        chapter_audio_by_chapter_id[chapter_id] = chapter_audio
                        logger.info("🆕 创建新的章节音频记录: chapter_id=%s", chapter_id)
                    else:
                        logger.info("♻️ 更新已有章节音频记录: chapter_id=%s", chapter_id)
                        if chapter_audio.script_json:
                            logger.info(
                                "✅ 保留已有剧本（status=%s）",
                                chapter_audio.script_status,
                            )

                    result_metadata = apply_chapter_audio_generation_result(
                        chapter_audio=chapter_audio,
                        result=result,
                        output_path=output_path,
                        require_audio_metrics=True,
                    )
                    parse_stats = result_metadata["parse_stats"]

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

                    generate_and_apply_subtitle_artifacts(
                        chapter_audio=chapter_audio,
                        result=result,
                        fallback_script_segments=script_payload,
                        output_path=output_path,
                        title=chapter.title or f"Chapter {chapter.chapter_number}",
                        generate_subtitle=generate_subtitle,
                    )

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
                        checkpoint_patch=build_checkpoint_patch_from_generation_result(
                            result=result,
                            task_id=task_id,
                            output_path=output_path,
                        ),
                    )
                    prune_and_log_completed_run_temp_assets(
                        logger,
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="full",
                    )
                    logger.info("✅ 章节 %s 生成成功", chapter_id)
                else:
                    current_run_failed_chapters += 1
                    logger.error("❌ 章节 %s 生成失败: %s", chapter_id, result.get("error"))
                    failure_script_segments = result.get("script_segments_payload")
                    mark_chapter_generation_failed(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="full",
                        stage="full",
                        chapter=chapter,
                        script_segments=failure_script_segments if isinstance(failure_script_segments, list) else [],
                        result=result,
                        resume_checkpoint=resume_checkpoint,
                        task_id=task_id,
                        default_error_message="full_generation_failed",
                    )

                refresh_audiobook_project_audio_totals(
                    db,
                    audiobook_project=audiobook_project,
                    failed_chapters=current_run_failed_chapters,
                )
                db.commit()

            except Exception as exc:
                logger.error("❌ 章节 %s 处理异常: %s", chapter_id, exc)
                current_run_failed_chapters += 1
                mark_chapter_generation_failed(
                    db,
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    run_type="full",
                    stage="full",
                    chapter=chapter,
                    script_segments=[],
                    result=result if isinstance(result, dict) else None,
                    exception=exc,
                    resume_checkpoint=resume_checkpoint if isinstance(resume_checkpoint, dict) else {},
                    task_id=task_id,
                    default_error_message="full_generation_failed",
                )
                refresh_audiobook_project_audio_totals(
                    db,
                    audiobook_project=audiobook_project,
                    failed_chapters=current_run_failed_chapters,
                )
                db.commit()
                import traceback

                traceback.print_exc()

        audiobook_project.status = "completed"
        final_totals = refresh_audiobook_project_audio_totals(
            db,
            audiobook_project=audiobook_project,
            failed_chapters=current_run_failed_chapters,
        )
        db.commit()

        settle_audiobook_project_billing(
            logger,
            db,
            audiobook_project_id=audiobook_project_id,
        )

        logger.info("🎉 有声书生成完成!")
        logger.info(
            "   - 成功: %s/%s",
            audiobook_project.completed_chapters,
            audiobook_project.total_chapters,
        )
        logger.info("   - 总时长: %.1f秒", final_totals.total_duration)
        logger.info("   - 总成本: ¥%.2f", final_totals.total_cost)
    except Exception as exc:
        logger.error("❌ 后台生成任务失败: %s", exc)
        import traceback

        traceback.print_exc()

        if audiobook_project:
            audiobook_project.status = "failed"
            db.commit()
            release_audiobook_project_billing(
                logger,
                db,
                audiobook_project_id=audiobook_project_id,
                reason="有声书生成失败，已释放冻结积分。",
            )
    finally:
        db.close()


__all__ = ["generate_audiobook_background"]
