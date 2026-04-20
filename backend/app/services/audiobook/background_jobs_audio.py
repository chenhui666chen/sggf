from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from app.db.base import SessionLocal
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.project import Chapter, Project
from app.services.audiobook.background_jobs_shared import (
    create_background_engine,
    parse_duration_seconds,
    parse_estimated_cost,
)
from app.services.audiobook.task_support import (
    StageTracker,
    update_chapter_run_state as _update_chapter_run_state,
)
from app.services.user_center_points_events import (
    record_audiobook_billing_release,
    record_audiobook_billing_settle,
)

logger = logging.getLogger(__name__)


def _build_effective_voice_mapping(
    *,
    audiobook_project: AudiobookProject,
    project: Optional[Project],
    tts_model: str,
) -> Dict[str, dict]:
    effective_voice_mapping = dict(audiobook_project.voice_mapping or {})
    if not project or not project.audio_config:
        return effective_voice_mapping

    try:
        from app.services.audiobook.project_audio_config import get_characters_for_model
        from app.services.audiobook.project_audio_config import parse_project_audio_config

        config_data = parse_project_audio_config(project.audio_config or "")
        characters = get_characters_for_model(config_data, tts_model)
        for item in characters:
            name = item.get("name")
            if not name:
                logger.warning("⚠️ 跳过无名称的角色音配置项")
                continue
            effective_voice_mapping[name] = {
                "voice_id": item.get("voice_id"),
                "volume": item.get("volume", 50),
                "speed": item.get("speed"),
                "pitch": item.get("pitch"),
                "tts_model": item.get("tts_model", tts_model),
            }
    except Exception as exc:
        logger.warning(
            "⚠️ 合并项目级角色音配置失败，将继续使用已有 voice_mapping: %s",
            exc,
        )
    return effective_voice_mapping


def _apply_project_audio_effects(*, engine, project: Optional[Project]) -> None:
    if not project or not project.audio_config:
        return

    try:
        from app.services.audiobook.project_audio_config import get_audio_fx
        from app.services.audiobook.project_audio_config import parse_project_audio_config

        config_data = parse_project_audio_config(project.audio_config or "")
        audio_fx = get_audio_fx(config_data)
    except Exception as parse_err:
        logger.warning("⚠️ 解析项目级音频配置失败: %s", parse_err)
        return

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
    tts_model: str = "qwen3-tts-flash",
    tracker: Optional[StageTracker] = None,
) -> None:
    """后台生成有声书音频任务（基于已生成或人工审核后的剧本）。"""
    db = SessionLocal()
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
        audiobook_project.completed_chapters = 0
        audiobook_project.failed_chapters = 0
        audiobook_project.total_duration = 0.0
        audiobook_project.total_cost = 0.0
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

        effective_voice_mapping = _build_effective_voice_mapping(
            audiobook_project=audiobook_project,
            project=project,
            tts_model=tts_model,
        )
        if effective_voice_mapping:
            try:
                engine.voice_manager.apply_project_voice_mapping(effective_voice_mapping)
                logger.info("🎛 已加载角色音配置: %s 个角色", len(effective_voice_mapping))
            except Exception as exc:
                logger.warning("⚠️ 应用角色音配置失败: %s", exc)

        _apply_project_audio_effects(engine=engine, project=project)

        total_duration = 0.0
        total_cost = 0.0

        for index, chapter_id in enumerate(chapter_ids, 1):
            try:
                logger.info(
                    "📖 [音频阶段] 处理章节 %s/%s: chapter_id=%s",
                    index,
                    len(chapter_ids),
                    chapter_id,
                )

                chapter_audio = db.query(ChapterAudio).filter(
                    ChapterAudio.audiobook_project_id == audiobook_project_id,
                    ChapterAudio.chapter_id == chapter_id,
                ).first()
                if not chapter_audio or not chapter_audio.script_json:
                    logger.warning(
                        "⚠️ 章节 %s 缺少剧本数据(script_json为空)，跳过该章节",
                        chapter_id,
                    )
                    audiobook_project.failed_chapters += 1
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        status="failed",
                        current_stage="failed",
                        progress=0.0,
                        error_message="script_missing",
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
                    audiobook_project.failed_chapters += 1
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        status="failed",
                        current_stage="failed",
                        progress=0.0,
                        error_message=f"script_not_approved:{chapter_audio.script_status}",
                    )
                    db.commit()
                    continue

                chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
                if not chapter:
                    logger.warning("⚠️ 章节不存在: %s", chapter_id)
                    audiobook_project.failed_chapters += 1
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        status="failed",
                        current_stage="failed",
                        progress=0.0,
                        error_message="chapter_not_found",
                    )
                    db.commit()
                    continue

                try:
                    script_segments_data = json.loads(chapter_audio.script_json)
                except Exception as parse_err:
                    logger.error(
                        "❌ 解析章节剧本JSON失败 chapter_id=%s: %s",
                        chapter_id,
                        parse_err,
                    )
                    audiobook_project.failed_chapters += 1
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        status="failed",
                        current_stage="failed",
                        progress=0.0,
                        error_message=f"invalid_script_json:{parse_err}",
                    )
                    db.commit()
                    continue

                if not isinstance(script_segments_data, list):
                    logger.warning(
                        "⚠️ 章节 %s 剧本数据格式异常，期望为列表，实际为 %s",
                        chapter_id,
                        type(script_segments_data),
                    )
                    audiobook_project.failed_chapters += 1
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        status="failed",
                        current_stage="failed",
                        progress=0.0,
                        error_message=f"invalid_script_payload:{type(script_segments_data)}",
                    )
                    db.commit()
                    continue

                output_path = (
                    f"audiobooks/project_{audiobook_project.project_id}"
                    f"/chapter_{chapter.chapter_number:03d}.mp3"
                )
                result = await engine.generate_chapter_audio_from_script(
                    script_segments_data=script_segments_data,
                    chapter_id=chapter_id,
                    output_path=output_path,
                    novel_genre=novel_genre,
                    novel_theme=novel_theme,
                    enable_quality_review=True,
                    audiobook_project_id=audiobook_project_id,
                )

                task_id = result.get("task_id")
                logger.info("🎯 [音频阶段] Chapter %s TaskID: %s", chapter_id, task_id)

                if result.get("success"):
                    stats = result.get("stats") or {}
                    parse_stats = stats.get("parse_stats") or {}
                    tts_stats = stats.get("tts_stats") or {}

                    chapter_audio.task_id = task_id
                    chapter_audio.audio_path = output_path
                    chapter_audio.duration = result.get("duration") or 0.0
                    chapter_audio.file_size = result.get("file_size") or 0
                    chapter_audio.segment_count = parse_stats.get(
                        "total_segments",
                        chapter_audio.segment_count,
                    )
                    chapter_audio.dialogue_count = parse_stats.get(
                        "dialogue_count",
                        chapter_audio.dialogue_count,
                    )
                    chapter_audio.narration_count = parse_stats.get(
                        "narration_count",
                        chapter_audio.narration_count,
                    )

                    generation_time = parse_duration_seconds(
                        stats.get("generation_time", "0秒")
                    )
                    if generation_time is not None:
                        chapter_audio.generation_time = generation_time

                    cost = parse_estimated_cost(tts_stats.get("estimated_cost", "¥0.00"))
                    if cost is not None:
                        chapter_audio.tts_cost = cost

                    final_audio_review = stats.get("final_audio_review")
                    if final_audio_review is not None:
                        try:
                            chapter_audio.final_audio_review_json = json.dumps(
                                final_audio_review,
                                ensure_ascii=False,
                            )
                        except Exception as dump_err:
                            logger.warning(
                                "⚠️ 序列化最终音频评审结果失败 chapter_id=%s: %s",
                                chapter_id,
                                dump_err,
                            )

                    audiobook_project.completed_chapters += 1
                    total_duration += result.get("duration") or 0.0
                    if cost is not None:
                        total_cost += cost

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
                        checkpoint_patch={
                            "engine_task_id": task_id,
                            "output_path": output_path,
                        },
                    )
                    logger.info("✅ 章节 %s 音频生成成功", chapter_id)
                else:
                    audiobook_project.failed_chapters += 1
                    logger.error("❌ 章节 %s 音频生成失败: %s", chapter_id, result.get("error"))
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        status="failed",
                        current_stage="failed",
                        progress=0.0,
                        error_message=str(result.get("error") or "audio_generation_failed"),
                    )

                audiobook_project.total_duration = total_duration
                audiobook_project.total_cost = total_cost
                db.commit()

            except Exception as exc:
                logger.error("❌ 章节 %s 音频阶段处理异常: %s", chapter_id, exc)
                audiobook_project.failed_chapters += 1
                _update_chapter_run_state(
                    db,
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    run_type="audio_from_scripts",
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

        logger.info("🎉 基于剧本的有声书音频生成完成!")
        logger.info(
            "   - 成功: %s/%s",
            audiobook_project.completed_chapters,
            audiobook_project.total_chapters,
        )
        logger.info("   - 总时长: %.1f秒", total_duration)
        logger.info("   - 总成本: ¥%.2f", total_cost)
    except Exception as exc:
        logger.error("❌ 基于剧本的后台生成任务失败: %s", exc)
        import traceback

        traceback.print_exc()

        if audiobook_project:
            audiobook_project.status = "failed"
            db.commit()
            try:
                record_audiobook_billing_release(
                    db=db,
                    audiobook_project_id=audiobook_project_id,
                    reason="有声书音频生成失败，已释放冻结积分。",
                )
            except Exception as release_exc:
                logger.warning(
                    "释放有声书冻结积分失败 audiobook_project_id=%s: %s",
                    audiobook_project_id,
                    release_exc,
                )
    finally:
        db.close()


__all__ = ["generate_audiobook_audio_from_scripts_background"]
