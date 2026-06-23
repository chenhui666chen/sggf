from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from app.db.base import SessionLocal
from app.models.audiobook import AudiobookProject
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
from app.services.audiobook.project_audio_runtime import resolve_project_audio_runtime_config
from app.services.audiobook.task_support import (
    StageTracker,
    update_chapter_run_state as _update_chapter_run_state,
)

logger = logging.getLogger(__name__)


def _apply_project_audio_effects(*, engine, audio_fx: Dict[str, object]) -> None:
    if not audio_fx:
        return

    try:
        engine.apply_audio_fx_config(audio_fx)
        logger.info("🎚 已加载项目级音效/BGM 配置")
    except Exception as exc:
        logger.warning("⚠️ 应用项目级音效/BGM 配置失败: %s", exc)


async def generate_audiobook_audio_from_scripts_background(
    audiobook_project_id: int,
    chapter_ids: List[int],
    tts_model: str = "qwen3-tts-instruct-flash",
    timeline_edits_by_chapter: Optional[Dict[int, Dict[str, Dict[str, float]]]] = None,
    tracker: Optional[StageTracker] = None,
) -> None:
    """后台生成有声书音频任务（基于已生成或人工审核后的剧本）。"""
    db = SessionLocal()
    db.expire_on_commit = False
    audiobook_project: Optional[AudiobookProject] = None

    try:
        logger.info(
            "🎙️ 开始基于剧本的有声书音频生成: audiobook_project_id=%s, chapters=%s",
            audiobook_project_id,
            chapter_ids,
        )

        audiobook_project = db.query(AudiobookProject).filter(
            AudiobookProject.id == audiobook_project_id
        ).first()
        if not audiobook_project:
            logger.error("❌ 有声书项目不存在: %s", audiobook_project_id)
            return

        audiobook_project.status = "processing"
        current_run_failed_chapters = 0
        refresh_audiobook_project_audio_totals(
            db,
            audiobook_project=audiobook_project,
            failed_chapters=current_run_failed_chapters,
        )
        db.commit()

        engine = create_background_engine(
            audiobook_project=audiobook_project,
            chapter_ids=chapter_ids,
            tts_model=tts_model,
            tracker=tracker,
        )

        project = db.query(Project).filter(Project.id == audiobook_project.project_id).first()
        novel_genre = (project.genre or "科幻") if project else "科幻"
        novel_theme = (project.sub_genre or "未知主题") if project else "未知主题"

        runtime_config = resolve_project_audio_runtime_config(
            project=project,
            tts_model=tts_model,
            base_voice_mapping=audiobook_project.voice_mapping or {},
        )
        effective_voice_mapping = runtime_config.voice_mapping
        if effective_voice_mapping:
            try:
                engine.voice_manager.apply_project_voice_mapping(effective_voice_mapping)
                logger.info("🎛 已加载角色音配置: %s 个角色", len(effective_voice_mapping))
            except Exception as exc:
                logger.warning("⚠️ 应用角色音配置失败: %s", exc)

        _apply_project_audio_effects(engine=engine, audio_fx=runtime_config.audio_fx)

        generation_records = prefetch_chapter_generation_records(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_ids=chapter_ids,
        )
        chapter_by_id = generation_records.chapter_by_id
        chapter_audio_by_chapter_id = generation_records.chapter_audio_by_chapter_id

        for index, chapter_id in enumerate(chapter_ids, 1):
            chapter = None
            resume_checkpoint = {}
            script_segments_data = None
            task_id = None
            result = None
            try:
                logger.info(
                    "📖 [音频阶段] 处理章节 %s/%s: chapter_id=%s",
                    index,
                    len(chapter_ids),
                    chapter_id,
                )

                chapter_audio = chapter_audio_by_chapter_id.get(chapter_id)
                if not chapter_audio or not chapter_audio.script_json:
                    logger.warning(
                        "⚠️ 章节 %s 缺少剧本数据(script_json为空)，跳过该章节",
                        chapter_id,
                    )
                    current_run_failed_chapters = mark_chapter_preflight_failed(
                        db,
                        audiobook_project=audiobook_project,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        error_message="script_missing",
                        failed_chapters=current_run_failed_chapters,
                    )
                    db.commit()
                    continue

                script_status = (chapter_audio.script_status or "").lower()
                if script_status != "approved":
                    logger.warning(
                        "⚠️ 章节 %s 剧本尚未通过评审(script_status=%s)，跳过音频生成",
                        chapter_id,
                        chapter_audio.script_status,
                    )
                    current_run_failed_chapters = mark_chapter_preflight_failed(
                        db,
                        audiobook_project=audiobook_project,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        error_message=f"script_not_approved:{chapter_audio.script_status}",
                        failed_chapters=current_run_failed_chapters,
                    )
                    db.commit()
                    continue

                chapter = chapter_by_id.get(chapter_id)
                if not chapter:
                    logger.warning("⚠️ 章节不存在: %s", chapter_id)
                    current_run_failed_chapters = mark_chapter_preflight_failed(
                        db,
                        audiobook_project=audiobook_project,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        error_message="chapter_not_found",
                        failed_chapters=current_run_failed_chapters,
                    )
                    db.commit()
                    continue

                try:
                    script_segments_data = json.loads(chapter_audio.script_json)
                except (json.JSONDecodeError, TypeError) as parse_err:
                    logger.error(
                        "❌ 解析章节剧本JSON失败 chapter_id=%s: %s",
                        chapter_id,
                        parse_err,
                    )
                    current_run_failed_chapters = mark_chapter_preflight_failed(
                        db,
                        audiobook_project=audiobook_project,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        error_message=f"invalid_script_json:{parse_err}",
                        failed_chapters=current_run_failed_chapters,
                    )
                    db.commit()
                    continue

                if not isinstance(script_segments_data, list):
                    logger.warning(
                        "⚠️ 章节 %s 剧本数据格式异常，期望为列表，实际为 %s",
                        chapter_id,
                        type(script_segments_data),
                    )
                    current_run_failed_chapters = mark_chapter_preflight_failed(
                        db,
                        audiobook_project=audiobook_project,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        error_message=f"invalid_script_payload:{type(script_segments_data)}",
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
                    run_type="audio_from_scripts",
                )
                resume_checkpoint = output_context.resume_checkpoint
                output_format = output_context.output_format
                generate_subtitle = output_context.generate_subtitle
                output_path = output_context.output_path
                chapter_timeline_edits = (
                    (timeline_edits_by_chapter or {}).get(chapter_id)
                    or resume_checkpoint.get("timeline_edits")
                )

                result = await engine.generate_chapter_audio_from_script(
                    script_segments_data=script_segments_data,
                    chapter_id=chapter_id,
                    output_path=output_path,
                    output_format=output_format,
                    novel_genre=novel_genre,
                    novel_theme=novel_theme,
                    enable_quality_review=True,
                    audiobook_project_id=audiobook_project_id,
                    resume_checkpoint=resume_checkpoint,
                    timeline_edits=chapter_timeline_edits if isinstance(chapter_timeline_edits, dict) else None,
                    tts_progress_callback=output_context.tts_progress_callback,
                )

                task_id = result.get("task_id")
                logger.info("🎯 [音频阶段] Chapter %s TaskID: %s", chapter_id, task_id)

                if result.get("success"):
                    result_metadata = apply_chapter_audio_generation_result(
                        chapter_audio=chapter_audio,
                        result=result,
                        output_path=output_path,
                        preserve_existing_counts=True,
                        logger=logger,
                        chapter_id=chapter_id,
                    )
                    parse_stats = result_metadata["parse_stats"]

                    generate_and_apply_subtitle_artifacts(
                        chapter_audio=chapter_audio,
                        result=result,
                        fallback_script_segments=script_segments_data,
                        output_path=output_path,
                        title=chapter.title or f"Chapter {chapter.chapter_number}",
                        generate_subtitle=generate_subtitle,
                    )

                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        status="completed",
                        current_stage="completed",
                        progress=1.0,
                        total_segment_count=parse_stats.get(
                            "total_segments",
                            chapter_audio.segment_count or 0,
                        ),
                        completed_segment_count=parse_stats.get(
                            "total_segments",
                            chapter_audio.segment_count or 0,
                        ),
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
                        run_type="audio_from_scripts",
                    )
                    logger.info("✅ 章节 %s 音频生成成功", chapter_id)
                else:
                    current_run_failed_chapters += 1
                    logger.error("❌ 章节 %s 音频生成失败: %s", chapter_id, result.get("error"))
                    mark_chapter_generation_failed(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        stage="audio_from_scripts",
                        chapter=chapter,
                        script_segments=script_segments_data if isinstance(script_segments_data, list) else [],
                        result=result,
                        resume_checkpoint=resume_checkpoint,
                        task_id=task_id,
                        default_error_message="audio_generation_failed",
                    )

                refresh_audiobook_project_audio_totals(
                    db,
                    audiobook_project=audiobook_project,
                    failed_chapters=current_run_failed_chapters,
                )
                db.commit()

            except Exception as exc:
                logger.error("❌ 章节 %s 音频阶段处理异常: %s", chapter_id, exc)
                current_run_failed_chapters += 1
                mark_chapter_generation_failed(
                    db,
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    run_type="audio_from_scripts",
                    stage="audio_from_scripts",
                    chapter=chapter,
                    script_segments=script_segments_data if isinstance(script_segments_data, list) else [],
                    result=result if isinstance(result, dict) else None,
                    exception=exc,
                    resume_checkpoint=resume_checkpoint if isinstance(resume_checkpoint, dict) else {},
                    task_id=task_id,
                    default_error_message="audio_generation_failed",
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

        logger.info("🎉 基于剧本的有声书音频生成完成!")
        logger.info(
            "   - 成功: %s/%s",
            audiobook_project.completed_chapters,
            audiobook_project.total_chapters,
        )
        logger.info("   - 总时长: %.1f秒", final_totals.total_duration)
        logger.info("   - 总成本: ¥%.2f", final_totals.total_cost)
    except Exception as exc:
        logger.error("❌ 基于剧本的后台生成任务失败: %s", exc)
        import traceback

        traceback.print_exc()

        if audiobook_project:
            audiobook_project.status = "failed"
            db.commit()
            release_audiobook_project_billing(
                logger,
                db,
                audiobook_project_id=audiobook_project_id,
                reason="有声书音频生成失败，已释放冻结积分。",
            )
    finally:
        db.close()


__all__ = ["generate_audiobook_audio_from_scripts_background"]
