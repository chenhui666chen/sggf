from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from app.db.base import SessionLocal
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.project import Project
from app.services.audiobook.background_jobs_prefetch import prefetch_chapter_generation_records
from app.services.audiobook.background_jobs_shared import (
    apply_chapter_audio_generation_result,
    build_checkpoint_patch_from_generation_result,
    cleanup_aborted_chapter_generation_artifacts,
    create_background_engine,
    generate_and_apply_subtitle_artifacts,
    is_audiobook_project_active,
    is_chapter_generation_target_active,
    mark_chapter_generation_failed,
    mark_chapter_preflight_failed,
    merge_workbench_segment_audio_into_checkpoint,
    prepare_chapter_generation_output_context,
    prune_and_log_completed_run_temp_assets,
    refresh_audiobook_project_audio_totals,
    release_audiobook_project_billing,
    settle_audiobook_project_billing,
)
from app.services.audiobook.atomic_files import write_bytes_atomic
from app.services.audiobook.chapter_output_publish import (
    publish_seed_scene_chapter_output,
    register_scene_audio_artifacts,
    upsert_staged_chapter_output,
)
from app.services.audiobook.chapter_segment_assets import (
    collect_chapter_segment_asset_refs,
    delete_replaced_segment_asset_refs,
    persist_generated_chapter_segment_audio,
)
from app.services.audiobook.job_tracker import handle_pause_checkpoint
from app.services.audiobook.repository import ChapterAudioRunRepository
from app.services.audiobook.tts_pause import TTSPauseRequested
from app.services.audiobook.project_audio_config import parse_engine_config_snapshot
from app.services.audiobook.project_audio_runtime import (
    apply_scene_audio_runtime_to_engine,
    resolve_from_snapshot,
    resolve_project_audio_runtime_config,
    validate_project_voice_references,
)
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
    celery_task_id: Optional[str] = None,
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
            AudiobookProject.id == audiobook_project_id,
            AudiobookProject.deleted_at.is_(None),
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

        # 注入资产归属用户，使后台任务能解析项目所有者的私有音色资产
        # （mimo 声音设计/克隆），避免归属校验拒绝导致自定义音色静默失效。
        if project is not None and getattr(project, "user_id", None) is not None:
            engine.voice_manager.owner_user_id = int(project.user_id)

        # Phase 1.5：优先从 engine_config_snapshot 解析，回退实时配置
        snapshot = parse_engine_config_snapshot(
            str(audiobook_project.engine_config_snapshot or "") if audiobook_project else None
        )
        if snapshot:
            runtime_config = resolve_from_snapshot(snapshot, tts_model=tts_model)
        else:
            runtime_config = resolve_project_audio_runtime_config(
                project=project,
                tts_model=tts_model,
                base_voice_mapping=audiobook_project.voice_mapping or {},
            )
        if project is not None:
            validate_project_voice_references(
                db,
                owner_user_id=int(project.user_id),
                voice_mapping=runtime_config.voice_mapping,
            )
        apply_scene_audio_runtime_to_engine(
            engine=engine,
            runtime_config=runtime_config,
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
                    reason="有声书音频生成任务已暂停，已释放冻结积分。",
                )
                return
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

                # 通过 celery_task_id 精确定位本次派发创建的 run 记录，
                # 避免并发任务按“同类型最新 run”回退定位时互相串写状态
                run_id: Optional[int] = None
                if celery_task_id:
                    dispatch_run = ChapterAudioRunRepository.get_run_by_celery_task_id(
                        db,
                        celery_task_id=celery_task_id,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                    )
                    run_id = dispatch_run.id if dispatch_run else None

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
                        run_id=run_id,
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
                        run_id=run_id,
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
                        run_id=run_id,
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
                        run_id=run_id,
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
                        run_id=run_id,
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
                    run_id=run_id,
                )
                resume_checkpoint = merge_workbench_segment_audio_into_checkpoint(
                    script_segments=script_segments_data,
                    resume_checkpoint=output_context.resume_checkpoint,
                    default_tts_model=getattr(engine, "tts_model", None),
                )
                output_format = output_context.output_format
                generate_subtitle = output_context.generate_subtitle
                output_path = output_context.output_path
                chapter_timeline_edits = (
                    (timeline_edits_by_chapter or {}).get(chapter_id)
                    or resume_checkpoint.get("timeline_edits")
                )

                # Phase 2: replace_voice_missing 选择性音色覆盖
                raw_segment_overrides = resume_checkpoint.get("segment_voice_overrides")
                segment_voice_overrides = None
                if isinstance(raw_segment_overrides, dict) and raw_segment_overrides:
                    segment_voice_overrides = {
                        int(k): v for k, v in raw_segment_overrides.items()
                        if isinstance(v, dict)
                    }

                result = await engine.generate_chapter_audio_from_script(
                    script_segments_data=script_segments_data,
                    chapter_id=chapter_id,
                    output_path=None,
                    output_format=output_format,
                    novel_genre=novel_genre,
                    novel_theme=novel_theme,
                    enable_quality_review=True,
                    audiobook_project_id=audiobook_project_id,
                    resume_checkpoint=resume_checkpoint,
                    timeline_edits=chapter_timeline_edits if isinstance(chapter_timeline_edits, dict) else None,
                    tts_progress_callback=output_context.tts_progress_callback,
                    segment_voice_overrides=segment_voice_overrides,
                    pause_check=pause_check_fn,
                )

                task_id = result.get("task_id")
                logger.info("🎯 [音频阶段] Chapter %s TaskID: %s", chapter_id, task_id)

                # 生成耗时较长，写入前复核章节/章节音频是否在生成期间被删除，
                # 避免与删除流程竞争导致已删记录被复活或孤儿文件写入
                if not is_chapter_generation_target_active(
                    db,
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    chapter_audio_id=chapter_audio.id,
                    run_id=run_id,
                ):
                    logger.warning(
                        "⚠️ 章节 %s 在生成期间已被删除，放弃写入生成结果",
                        chapter_id,
                    )
                    cleanup_aborted_chapter_generation_artifacts(
                        output_path=output_path,
                        result=result,
                    )
                    db.rollback()
                    continue

                if result.get("success"):
                    active_chapter_audio = (
                        db.query(ChapterAudio)
                        .filter(
                            ChapterAudio.id == chapter_audio.id,
                            ChapterAudio.audiobook_project_id == audiobook_project_id,
                            ChapterAudio.chapter_id == chapter_id,
                            ChapterAudio.deleted_at.is_(None),
                        )
                        .populate_existing()
                        .first()
                    )
                    if active_chapter_audio is None:
                        logger.info(
                            "章节在 audio_from_scripts 结果写回前已删除，放弃写入: "
                            "audiobook_project_id=%s chapter_id=%s",
                            audiobook_project_id,
                            chapter_id,
                        )
                        db.rollback()
                        continue
                    chapter_audio = active_chapter_audio
                    existing_persistent_asset_refs = collect_chapter_segment_asset_refs(
                        chapter_audio
                    )
                    audio_data = result.get("audio_data")
                    if not isinstance(audio_data, (bytes, bytearray)) or not audio_data:
                        raise RuntimeError("generated_audio_missing")
                    write_bytes_atomic(output_path, bytes(audio_data))
                    # §2.5：识别 seed_scene 渲染结果（stats.mode），走发布协议链路；
                    # run_id 缺失（非 celery 派发路径）时降级旧直写行为
                    is_seed_scene_result = (
                        (result.get("stats") or {}).get("mode") == "seed_scene"
                    )
                    use_publish_protocol = is_seed_scene_result and run_id is not None
                    if not is_chapter_generation_target_active(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        chapter_audio_id=chapter_audio.id,
                        run_id=run_id,
                    ):
                        cleanup_aborted_chapter_generation_artifacts(
                            output_path=output_path,
                            result=result,
                        )
                        db.rollback()
                        continue

                    result_metadata = apply_chapter_audio_generation_result(
                        chapter_audio=chapter_audio,
                        result=result,
                        output_path=output_path,
                        preserve_existing_counts=True,
                        logger=logger,
                        chapter_id=chapter_id,
                        skip_mirror_columns=use_publish_protocol,
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

                    # §2.5：seed_scene 引擎登记 run 级输出（staged），整章可导出
                    # 镜像列改由发布事务 CAS 写入（§2.4 规则 3/4）
                    if use_publish_protocol:
                        subtitle_artifacts = result.get("subtitle_artifacts")
                        subtitle_artifacts = (
                            subtitle_artifacts
                            if isinstance(subtitle_artifacts, dict)
                            else {}
                        )
                        upsert_staged_chapter_output(
                            db,
                            run_id=run_id,
                            chapter_audio_id=chapter_audio.id,
                            audiobook_project_id=audiobook_project_id,
                            chapter_id=chapter_id,
                            audio_path=output_path,
                            duration=result.get("duration"),
                            file_size=result.get("file_size"),
                            subtitle_path=subtitle_artifacts.get("subtitle_path"),
                            subtitle_format=(
                                subtitle_artifacts.get("subtitle_format") or "srt"
                            ),
                        )
                        # §3.4：装配段产物就绪 → 登记场景音频 artifact（staged）
                        register_scene_audio_artifacts(
                            db,
                            run_id=run_id,
                            chapter_audio_id=chapter_audio.id,
                            audiobook_project_id=audiobook_project_id,
                            chapter_id=chapter_id,
                            scene_artifacts=result.get("scene_artifacts"),
                        )

                    # 在 run 临时资产清理前固化片段音频并写回 script_json，
                    # 供工作台分段试听与整章重新混音使用
                    if not is_chapter_generation_target_active(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        chapter_audio_id=chapter_audio.id,
                        run_id=run_id,
                    ):
                        cleanup_aborted_chapter_generation_artifacts(
                            output_path=output_path,
                            result=result,
                        )
                        db.rollback()
                        continue

                    persist_generated_chapter_segment_audio(
                        chapter_audio=chapter_audio,
                        result=result,
                        tts_model=getattr(engine, "tts_model", None),
                    )
                    new_persistent_asset_refs = collect_chapter_segment_asset_refs(
                        chapter_audio
                    )

                    if not is_chapter_generation_target_active(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        chapter_audio_id=chapter_audio.id,
                        run_id=run_id,
                    ):
                        cleanup_aborted_chapter_generation_artifacts(
                            output_path=output_path,
                            result=result,
                            persistent_asset_refs=(
                                new_persistent_asset_refs
                                - existing_persistent_asset_refs
                            ),
                        )
                        db.rollback()
                        continue

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
                        run_id=run_id,
                        result_render_status=(
                            result.get("render_status") if is_seed_scene_result else None
                        ),
                        result_render_detail=(
                            result.get("render_status_detail")
                            if is_seed_scene_result
                            else None
                        ),
                    )
                    # §2.5：整章装配完成 → 先写 run 投影（上方）→ 幂等完整发布协议
                    if use_publish_protocol:
                        publish_seed_scene_chapter_output(
                            db,
                            run_id=run_id,
                            chapter_audio_id=chapter_audio.id,
                            render_status=result.get("render_status"),
                            render_status_detail=result.get("render_status_detail"),
                        )
                    prune_and_log_completed_run_temp_assets(
                        logger,
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        run_id=run_id,
                    )
                    logger.info("✅ 章节 %s 音频生成成功", chapter_id)
                else:
                    current_run_failed_chapters += 1
                    logger.error("❌ 章节 %s 音频生成失败: %s", chapter_id, result.get("error"))
                    is_seed_scene_failure = (
                        isinstance(result, dict)
                        and (result.get("stats") or {}).get("mode") == "seed_scene"
                    )
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
                        run_id=run_id,
                        result_render_status=(
                            result.get("render_status") or "failed"
                            if is_seed_scene_failure
                            else None
                        ),
                        result_render_detail=(
                            result.get("render_status_detail")
                            if is_seed_scene_failure
                            else None
                        ),
                    )

                refresh_audiobook_project_audio_totals(
                    db,
                    audiobook_project=audiobook_project,
                    failed_chapters=current_run_failed_chapters,
                )
                db.commit()
                if result.get("success"):
                    try:
                        delete_replaced_segment_asset_refs(
                            existing_persistent_asset_refs,
                            new_persistent_asset_refs,
                        )
                    except Exception as cleanup_exc:
                        logger.warning(
                            "回收管线已替换片段资产失败: chapter_id=%s error=%s",
                            chapter_id,
                            cleanup_exc,
                        )

            except TTSPauseRequested:
                # 章节合成过程中收到暂停请求：落库为 paused（包含当前章节，
                # 恢复时可复用已合成片段），不当作失败处理
                logger.info("⏸️ [音频阶段] 章节 %s 合成中被暂停请求中断", chapter_id)
                handle_pause_checkpoint(
                    tracker,
                    chapter_ids=chapter_ids,
                    current_index=index,
                    stage="tts_synthesis",
                )
                audiobook_project.status = "paused"
                db.commit()
                release_audiobook_project_billing(
                    logger,
                    db,
                    audiobook_project_id=audiobook_project_id,
                    reason="有声书音频生成任务已暂停，已释放冻结积分。",
                )
                return
            except Exception as exc:
                logger.error("❌ 章节 %s 音频阶段处理异常: %s", chapter_id, exc)
                current_run_failed_chapters += 1
                is_seed_scene_failure = (
                    isinstance(result, dict)
                    and (result.get("stats") or {}).get("mode") == "seed_scene"
                )
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
                    run_id=run_id,
                    result_render_status=(
                        "failed" if is_seed_scene_failure else None
                    ),
                    result_render_detail=(
                        result.get("render_status_detail")
                        if is_seed_scene_failure
                        else None
                    ),
                )
                refresh_audiobook_project_audio_totals(
                    db,
                    audiobook_project=audiobook_project,
                    failed_chapters=current_run_failed_chapters,
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
                "有声书项目已删除，跳过 audio_from_scripts 任务最终状态写回: audiobook_project_id=%s",
                audiobook_project_id,
            )
            return

        audiobook_project.status = "completed" if current_run_failed_chapters == 0 else "failed"
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

        if audiobook_project and is_audiobook_project_active(
            db,
            audiobook_project_id=audiobook_project_id,
        ):
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
