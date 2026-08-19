"""Workflow API module."""
import logging
import asyncio
from fastapi import APIRouter, Depends, HTTPException, status, Body, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional, Tuple, List, Sequence
from pydantic import BaseModel, ConfigDict
from datetime import datetime
import json
import re
import uuid
from sqlalchemy import inspect, text

from app.db.base import get_db, SessionLocal
from app.services.agent_coordinator import coordinator, StageType, AgentStatus
from app.core.security import get_current_user
from app.models.project import Project, Chapter
from app.models.setting import SettingCollection
from app.websocket.manager import ws_manager
from app.services.character_runtime_context import build_character_prompt_context_from_text
from app.services.workflow_context_builder import WorkflowContextBuilder
from app.services.story_expansion_duration_estimator import (
    apply_story_expansion_duration_history_calibration,
)
from app.utils.datetime_utils import parse_datetime_utc, utc_now
from core.model_resolution import normalize_model_id
from core.model_runtime import ensure_model_hub_initialized, resolve_model_for_task
from app.services.prompts.stages.world_building import CharacterDesignPrompts, get_genre_character_fields
from app.services.auto_system_detector import auto_create_system_collections
from app.services.points_usage_pricing import (
    build_points_billing_precheck,
    build_points_billing_precheck_error_detail,
    build_points_usage_charge_estimate,
    estimate_story_expansion_request_basis_yuan,
    estimate_story_expansion_result_basis_yuan,
    supports_points_billing_session,
)
from app.services.user_center_points_events import (
    POINTS_BILLING_MODULE_NOVEL,
    build_points_billing_key,
    record_points_billing_freeze,
    record_points_billing_release,
    record_points_billing_settle,
)

logger = logging.getLogger(__name__)

from app.api.v1.workflow import router
from app.api.v1.workflow.schemas import *
from app.api.v1.workflow.helpers import *
from app.api.v1.workflow.story_helpers import *
from app.api.v1.workflow.story_resolve import *
from app.api.v1.workflow.story_helpers import (
    _build_task_start_response,
    _create_story_expansion_history_record,
    _enqueue_story_expansion_task,
    _ensure_project_owned,
    _normalize_story_request_text_fields,
)
from app.api.v1.workflow.story_resolve import (
    _build_story_expansion_analysis,
    _build_story_written_chapter_preview,
    _estimate_character_count_from_text,
    _estimate_chapter_count_from_text,
    _normalize_story_character_sync_result,
    _normalize_story_result_outline_ops,
    _prepare_story_execution_request,
    _resolve_story_epic_config,
    _resolve_story_result_count,
    _select_story_character_sync_source,
    _update_story_expansion_history_record,
    _validate_expand_story_request,
    _validate_story_framework_mode_switch,
)

from app.schemas.story_expansion import (
    StoryExpansionAnalysisPayload,
    StoryExpansionAnalysisRouteResponse,
    StoryExpansionRepairRequest,
    StoryExpansionRepairResponse,
    StoryExpansionStartResponse,
    StoryExpansionTaskResultResponse,
)


def _load_structural_debt_from_history(db: Session, project_id: int) -> str:
    """读取最近一次协同扩展遗留的情节级结构债（跨轮修复输入）。

    扫描最近若干条已完成记录，取最新的非空 alignment_structural_debt；
    验证器不可用的轮次不写该字段，向前回溯保证债务不被误清。
    """
    try:
        rows = db.execute(
            text(
                """
                SELECT result
                FROM generation_history
                WHERE project_id = :project_id
                  AND task_type = 'expand_story'
                  AND status = 'completed'
                ORDER BY id DESC
                LIMIT 5
                """
            ),
            {"project_id": project_id},
        ).fetchall()
        for row in rows:
            raw_result = row[0] if row else None
            if not raw_result:
                continue
            payload = raw_result if isinstance(raw_result, dict) else json.loads(raw_result)
            if "alignment_structural_debt" not in payload:
                continue
            debt = str(payload.get("alignment_structural_debt") or "").strip()
            if debt:
                logger.info(
                    "加载上轮结构债（%s 字符）注入本轮扩展",
                    len(debt),
                )
            return debt
        return ""
    except Exception as exc:
        logger.warning("读取上轮结构债失败（忽略，按无债处理）: %s", exc)
        return ""


def _apply_story_expansion_duration_calibration_safely(
    db: Session,
    *,
    user_id: int,
    project_id: int,
    analysis: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        return apply_story_expansion_duration_history_calibration(
            db,
            user_id=user_id,
            project_id=project_id,
            analysis=analysis,
        )
    except Exception as estimate_error:
        logger.warning(
            "协同扩展历史耗时校准失败，回退静态估时：project_id=%s, error=%s",
            project_id,
            estimate_error,
        )
        return analysis


def _build_story_expansion_billing_key(task_id: str) -> str:
    return build_points_billing_key(POINTS_BILLING_MODULE_NOVEL, f"expand-story:{task_id}")


def _safe_user_name(user: object) -> str:
    return str(getattr(user, "username", None) or getattr(user, "email", None) or "system").strip() or "system"


def _release_story_expansion_billing_safely(
    *,
    db: Session,
    user_id: int,
    username: str,
    task_id: str,
    reason: str,
    project_id: int,
) -> None:
    if not supports_points_billing_session(db):
        return
    try:
        try:
            db.rollback()
        except Exception:
            pass
        record_points_billing_release(
            db=db,
            actor_user_id=user_id,
            actor_username=username,
            target_user_id=user_id,
            billing_key=_build_story_expansion_billing_key(task_id),
            module_key=POINTS_BILLING_MODULE_NOVEL,
            reason=reason,
            default_request_path=f"/internal/workflow/expand-story/{task_id}/billing-release",
            extra_payload={
                "project_id": int(project_id or 0),
                "task_id": task_id,
            },
        )
    except Exception as billing_error:
        logger.warning("小说协同扩展积分释放失败: task_id=%s, error=%s", task_id, billing_error)


def _settle_story_expansion_billing_safely(
    *,
    db: Session,
    user_id: int,
    username: str,
    task_id: str,
    project_id: int,
    project_title: str | None,
    initial_chapter_count: int,
    final_chapter_count: int,
    initial_character_count: int,
    final_character_count: int,
    execution_mode: str | None,
    execution_rounds: Sequence[object] | None,
    epic_total_volumes: int | None,
) -> None:
    if not supports_points_billing_session(db):
        return
    try:
        basis_yuan = estimate_story_expansion_result_basis_yuan(
            initial_chapter_count=initial_chapter_count,
            final_chapter_count=final_chapter_count,
            initial_character_count=initial_character_count,
            final_character_count=final_character_count,
            execution_mode=execution_mode,
            execution_rounds=execution_rounds,
            epic_total_volumes=epic_total_volumes,
        )
        estimate = build_points_usage_charge_estimate(
            db=db,
            module_key=POINTS_BILLING_MODULE_NOVEL,
            basis_yuan=basis_yuan,
            include_freeze_buffer=False,
        )
        record_points_billing_settle(
            db=db,
            actor_user_id=user_id,
            actor_username=username,
            target_user_id=user_id,
            billing_key=_build_story_expansion_billing_key(task_id),
            module_key=POINTS_BILLING_MODULE_NOVEL,
            amount_points=estimate.estimated_points,
            amount_yuan=estimate.basis_yuan,
            title=f"小说协同扩展：{project_title or project_id}",
            summary=(
                f"协同扩展已完成，章节 {initial_chapter_count} → {final_chapter_count}，"
                f"人物 {initial_character_count} → {final_character_count}。"
            ),
            action_path=f"/workflow?project_id={int(project_id or 0)}",
            action_label="查看小说项目",
            default_request_path=f"/internal/workflow/expand-story/{task_id}/billing-settle",
            extra_payload={
                "project_id": int(project_id or 0),
                "task_id": task_id,
                "execution_mode": execution_mode,
                "initial_chapter_count": int(initial_chapter_count or 0),
                "final_chapter_count": int(final_chapter_count or 0),
                "initial_character_count": int(initial_character_count or 0),
                "final_character_count": int(final_character_count or 0),
                "execution_round_count": len(list(execution_rounds or [])),
            },
            require_active_freeze=True,
        )
    except Exception as billing_error:
        logger.warning("小说协同扩展积分结算失败: task_id=%s, error=%s", task_id, billing_error)

@router.get("/epic-framework-state/{project_id}")
async def get_epic_framework_state(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    🔍 检测长篇框架状态
    
    返回:
    {
        "has_framework": true/false,
        "total_volumes": 17,
        "expanded_volumes": [1, 3, 5],
        "framework_generated_at": "2025-12-12T10:00:00"
    }
    """
    import logging
    from app.services.outline_merger import detect_framework_state
    from sqlalchemy import text
    
    logger = logging.getLogger("uvicorn.error")
    
    try:
        logger.info(f"🔍 检测长篇框架状态，项目ID: {project_id}")
        
        # 验证项目所有权
        project = db.query(Project).filter(
            (Project.id == project_id) & (Project.user_id == current_user.id)
        ).first()
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )
        
        # 读取框架数据
        epic_framework_state = WorkflowContextBuilder(db).load_epic_framework_state(project_id)
        
        if not (
            epic_framework_state.epic_framework
            or epic_framework_state.framework_generated_at
            or epic_framework_state.plot_outline
            or epic_framework_state.epic_volumes_detail
        ):
            logger.info(f"   ✅ 未找到项目设置，返回空状态")
            return {
                "has_framework": False,
                "total_volumes": 0,
                "expanded_volumes": [],
                "framework_generated_at": None
            }
        
        epic_framework = epic_framework_state.epic_framework
        framework_generated_at = epic_framework_state.framework_generated_at
        plot_outline = epic_framework_state.plot_outline or ""
        epic_volumes_detail_json = epic_framework_state.epic_volumes_detail or ""
        
        # 🌟 新架构：使用 parse_epic_volumes_json 和 get_volume_state
        from app.services.outline_merger import parse_epic_volumes_json, get_volume_state
        
        # 解析卷数据
        volumes_data = parse_epic_volumes_json(epic_volumes_detail_json)
        
        # 如果新架构有数据，直接使用
        if volumes_data.get("volumes"):
            state = get_volume_state(volumes_data)
            logger.info(f"   ✅ 新架构状态: has_framework={state['hasFramework']}, total_volumes={state['totalVolumes']}, expanded_volumes={state['expandedVolumes']}")
            return {
                "has_framework": state["hasFramework"],
                "total_volumes": state["totalVolumes"],
                "expanded_volumes": state["expandedVolumes"],
                "framework_generated_at": state["frameworkGeneratedAt"] or framework_generated_at
            }
        
        # 🔄 回退：老结构或空数据，使用原有逻辑
        import re
        has_framework = bool(framework_generated_at) or bool(epic_framework and len(epic_framework) > 100)
        
        total_volumes = 0
        yaml_match = re.search(r'总卷数:\s*(\d+)', plot_outline)
        if yaml_match:
            total_volumes = int(yaml_match.group(1))
        else:
            vol_matches = re.findall(r'第\s*(\d+)\s*卷', plot_outline or epic_framework or '')
            if vol_matches:
                total_volumes = max(int(v) for v in vol_matches)
        
        # 老格式兼容：从旧JSON读取已扩展卷
        from app.services.outline_merger import parse_volumes_detail_json
        expanded_volumes = []
        if epic_volumes_detail_json:
            try:
                volumes_dict = parse_volumes_detail_json(epic_volumes_detail_json)
                expanded_volumes = sorted(volumes_dict.keys())
            except Exception as e:
                logger.warning(f"   ⚠️  解析 epic_volumes_detail 失败: {e}")
        
        logger.info(f"   ✅ 框架状态(回退): has_framework={has_framework}, total_volumes={total_volumes}, expanded_volumes={expanded_volumes}")
        
        return {
            "has_framework": has_framework,
            "total_volumes": total_volumes,
            "expanded_volumes": expanded_volumes,
            "framework_generated_at": framework_generated_at
        }
        
    except Exception as e:
        logger.error(f"❌ 检测框架状态失败: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


def _build_story_score_repair_messages(repairs: List[Dict[str, Any]]) -> List[str]:
    messages: List[str] = []
    for item in repairs:
        name = str(item.get("character_name") or "").strip()
        chapter_number = int(item.get("chapter_number") or 0)
        if not name:
            continue

        chapter_label = f"第{chapter_number}章" if chapter_number > 0 else "当前章节"
        messages.append(f"{chapter_label}已补入人物 {name} 的章节承接。")

    return list(dict.fromkeys(messages))


def _sync_story_repaired_outline_to_vector(project_id: int, plot_outline: str) -> None:
    if not plot_outline or not plot_outline.strip():
        return

    try:
        from app.services.vector_sync import sync_to_vector_db

        sync_to_vector_db(
            kb_type="plot",
            name=f"project_{project_id}_plot_outline",
            content=plot_outline,
            metadata={
                "project_id": str(project_id),
                "type": "plot_outline",
            },
        )
    except Exception as vector_error:
        logger.warning(f"⚠️ 评分修复后同步向量库失败: {vector_error}")


@router.post("/expand-story/analysis", response_model=StoryExpansionAnalysisRouteResponse)
async def analyze_expand_story(
    request: ExpandStoryRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """分析协同扩展请求，返回推荐方向、模式和模型适配信息。"""
    try:
        _validate_expand_story_request(request, allow_empty_targets_for_analysis=True)

        _ensure_project_owned(request.project_id, current_user.id, db)
        _validate_story_framework_mode_switch(request, db)

        request = _normalize_story_request_text_fields(request)
        preview = _build_story_written_chapter_preview(request, db)
        analysis_request = request.model_copy(
            update={
                "current_outline": preview["effective_outline"],
                "current_chapter_count": preview["effective_current_chapter_count"],
            }
        )
        analysis_bundle = _build_story_expansion_analysis(
            request=analysis_request,
            db=db,
        )
        analysis = dict(analysis_bundle["analysis"])
        warnings = list(analysis.get("warnings") or [])
        warnings.extend(preview.get("warnings") or [])
        analysis["warnings"] = list(dict.fromkeys(item for item in warnings if item))
        analysis["written_chapter_context"] = {
            "applied": bool(preview.get("applied")),
            "written_chapter_count": int(preview.get("written_chapter_count") or 0),
            "preserve_written_mode": request.preserve_written_mode,
        }
        analysis = _apply_story_expansion_duration_calibration_safely(
            db,
            user_id=int(current_user.id),
            project_id=request.project_id,
            analysis=analysis,
        )

        response_payload = StoryExpansionAnalysisRouteResponse.model_validate(
            {
                "success": True,
                "analysis": StoryExpansionAnalysisPayload.model_validate(analysis).model_dump(
                    mode="python",
                    exclude_none=True,
                ),
            }
        )
        return response_payload.model_dump(mode="python", exclude_none=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 协同扩展预检分析失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/expand-story/repair-score", response_model=StoryExpansionRepairResponse)
async def repair_expand_story_score(
    request: StoryExpansionRepairRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修复当前协同结果里导致评分下降的人物承接缺口，不启动新一轮协同扩展。"""
    try:
        _ensure_project_owned(request.project_id, current_user.id, db)

        from app.services.story_expansion_coordinator import (
            StoryExpansionCoordinator,
            evaluate_story_coordination,
        )

        context_builder = WorkflowContextBuilder(db)
        stage_context = context_builder.load_stage_text_context(request.project_id)
        epic_framework_state = context_builder.load_epic_framework_state(request.project_id)

        characters_text = (stage_context.characters or "").strip()
        current_plot_outline = (
            stage_context.plot_outline
            or epic_framework_state.plot_outline
            or epic_framework_state.epic_framework
            or ""
        ).strip()
        if not current_plot_outline:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="当前项目缺少可修复的大纲内容",
            )
        if not characters_text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="当前项目缺少人物设定，无法执行评分修复",
            )

        validation_before = evaluate_story_coordination(current_plot_outline, characters_text)
        target_character_names = list(validation_before.get("unreferenced_characters") or [])

        repaired_outline = current_plot_outline
        repaired_outline_delta = ""
        repair_records: List[Dict[str, Any]] = []
        update_fields: Dict[str, Any] = {}
        repair_scope = str(request.story_expansion_mode or "total").strip() or "total"
        epic_total_volumes: Optional[int] = None

        if repair_scope == "volume_detail" and request.volume_index:
            from app.services.outline_merger import (
                get_volume_state,
                merge_volumes_to_outline,
                parse_epic_volumes_json,
                update_volume_detail,
            )

            volumes_data = parse_epic_volumes_json(epic_framework_state.epic_volumes_detail or "")
            volume_entry = (
                (volumes_data.get("volumes") or {}).get(str(request.volume_index))
                if isinstance(volumes_data, dict)
                else None
            )
            detail_content = str((volume_entry or {}).get("detail") or "").strip()
            if not detail_content:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="当前卷缺少可修复的细纲内容",
                )

            repaired_detail, repair_records = StoryExpansionCoordinator._repair_outline_character_references(
                detail_content,
                target_character_names,
                characters_text=characters_text,
            )
            if repair_records:
                chapter_range = list((volume_entry or {}).get("chapters_range") or [0, 0])
                volumes_data = update_volume_detail(
                    volumes_data,
                    int(request.volume_index),
                    repaired_detail,
                    chapter_range,
                )
                repaired_outline = merge_volumes_to_outline(volumes_data)
                repaired_outline_delta = repaired_detail
                update_fields.update(
                    {
                        "plot_outline": repaired_outline,
                        "epic_volumes_detail": json.dumps(volumes_data, ensure_ascii=False),
                    }
                )
                epic_total_volumes = int(get_volume_state(volumes_data).get("totalVolumes") or 0)
        else:
            repair_source_outline = (
                epic_framework_state.epic_framework.strip()
                if repair_scope == "epic_framework" and epic_framework_state.epic_framework
                else current_plot_outline
            )
            repaired_outline, repair_records = StoryExpansionCoordinator._repair_outline_character_references(
                repair_source_outline,
                target_character_names,
                characters_text=characters_text,
            )
            repaired_outline_delta = StoryExpansionCoordinator._extract_outline_delta_text(
                repair_source_outline,
                repaired_outline,
            )
            if repair_records:
                update_fields["plot_outline"] = repaired_outline
                if repair_scope == "epic_framework" and epic_framework_state.epic_framework:
                    update_fields["epic_framework"] = repaired_outline

                # 读取链路会用 epic_volumes_detail 重建 plot_outline（卷细纲是权威源），
                # 必须把人物承接修复同步进卷细纲，否则修复会在下次读取时被静默回滚。
                volumes_detail_raw = (epic_framework_state.epic_volumes_detail or "").strip()
                if volumes_detail_raw:
                    from app.services.outline_merger import (
                        get_volume_state,
                        merge_volumes_to_outline,
                        parse_epic_volumes_json,
                        update_volume_detail,
                    )

                    volumes_data = parse_epic_volumes_json(volumes_detail_raw)
                    volumes_map = (
                        volumes_data.get("volumes") or {} if isinstance(volumes_data, dict) else {}
                    )
                    remaining_names = list(target_character_names)
                    for volume_key in sorted(volumes_map.keys(), key=lambda item: int(item)):
                        if not remaining_names:
                            break
                        volume_entry = volumes_map.get(volume_key) or {}
                        detail_content = str(volume_entry.get("detail") or "").strip()
                        if not detail_content:
                            continue
                        repaired_detail, volume_repairs = StoryExpansionCoordinator._repair_outline_character_references(
                            detail_content,
                            remaining_names,
                            characters_text=characters_text,
                        )
                        if not volume_repairs:
                            continue
                        chapter_range = list(volume_entry.get("chapters_range") or [0, 0])
                        volumes_data = update_volume_detail(
                            volumes_data,
                            int(volume_key),
                            repaired_detail,
                            chapter_range,
                        )
                        volumes_map = (
                            volumes_data.get("volumes") or {} if isinstance(volumes_data, dict) else {}
                        )
                        repaired_volume_names = {
                            str(record.get("character_name") or "") for record in volume_repairs
                        }
                        remaining_names = [
                            name for name in remaining_names if name not in repaired_volume_names
                        ]
                    if not remaining_names:
                        merged_outline = merge_volumes_to_outline(volumes_data)
                        if merged_outline.strip():
                            repaired_outline = merged_outline
                            repaired_outline_delta = StoryExpansionCoordinator._extract_outline_delta_text(
                                repair_source_outline,
                                repaired_outline,
                            )
                            update_fields["plot_outline"] = repaired_outline
                            update_fields["epic_volumes_detail"] = json.dumps(
                                volumes_data,
                                ensure_ascii=False,
                            )
                            epic_total_volumes = int(get_volume_state(volumes_data).get("totalVolumes") or 0)
                            if repair_scope == "epic_framework" and epic_framework_state.epic_framework:
                                update_fields["epic_framework"] = repaired_outline

        if update_fields:
            context_builder.update_project_settings_fields(request.project_id, **update_fields)
            _sync_story_repaired_outline_to_vector(request.project_id, repaired_outline)

        validation_after = evaluate_story_coordination(repaired_outline, characters_text)
        alignment_repairs = _build_story_score_repair_messages(repair_records)
        remaining_unreferenced = list(validation_after.get("unreferenced_characters") or [])
        alignment_warnings = (
            [f"仍有未完成承接的人物：{'、'.join(remaining_unreferenced[:5])}"]
            if remaining_unreferenced
            else []
        )

        if repair_records:
            coordination_summary = (
                f"已针对协同评分下降项补齐 {len(repair_records)} 处人物承接，"
                f"评分 {validation_before.get('score', 0)} → {validation_after.get('score', 0)}。"
            )
            message = "协同评分下降项已完成定向修复"
        elif target_character_names:
            coordination_summary = "已尝试修复评分下降项，但当前大纲中没有可安全补入的章节字段。"
            message = "当前评分下降项暂未产生可落地修复"
        else:
            coordination_summary = "当前结果没有发现可直接修复的人物承接缺口。"
            message = "当前协同结果无需执行评分修复"

        result_payload = StoryExpansionTaskResultResponse.model_validate(
            {
                "expanded_outline": repaired_outline,
                "all_characters": characters_text,
                "outline_delta": repaired_outline_delta or "",
                "character_delta": "",
                "character_relationships": "",
                "outline_ops": [],
                "execution_mode": "repair",
                "execution_mode_reason": "定向修复当前协同结果中的人物承接缺口，不新增章节或人物。",
                "execution_rounds": [],
                "new_characters": [],
                "alignment_repairs": alignment_repairs,
                "story_strategy": "auto",
                "story_intent": "balanced",
                "story_expansion_mode": repair_scope,
                "story_preserve_written_mode": "extract_extend",
                "coordination_summary": coordination_summary,
                "current_chapter_count": validation_after.get("chapter_count"),
                "target_chapter_count": validation_after.get("chapter_count"),
                "current_character_count": validation_after.get("character_count"),
                "target_character_count": validation_after.get("character_count"),
                "validation_before": validation_before,
                "validation_after": validation_after,
                "alignment_warnings": alignment_warnings,
                "epic_total_volumes": epic_total_volumes,
                "message": message,
            }
        )

        return StoryExpansionRepairResponse.model_validate(
            {
                "success": True,
                "result": result_payload,
                "message": message,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 协同评分修复失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/expand-story", response_model=StoryExpansionStartResponse)
async def expand_story(
    request: ExpandStoryRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """协同拓展大纲与人物，采用真正的 delta 策略异步执行。"""
    task_id: str | None = None
    billing_frozen = False
    try:
        _validate_expand_story_request(request)

        project = _ensure_project_owned(request.project_id, current_user.id, db)
        _validate_story_framework_mode_switch(request, db)

        task_id = f"expand-story-{uuid.uuid4()}"
        if supports_points_billing_session(db):
            billing_key = _build_story_expansion_billing_key(task_id)
            basis_yuan = estimate_story_expansion_request_basis_yuan(request)
            module_label = "小说协同"
            precheck = build_points_billing_precheck(
                db=db,
                user_id=current_user.id,
                billing_key=billing_key,
                module_key=POINTS_BILLING_MODULE_NOVEL,
                module_label=module_label,
                basis_yuan=basis_yuan,
            )
            if not precheck.allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=build_points_billing_precheck_error_detail(
                        precheck=precheck,
                        default_message="小说协同扩展积分预检未通过",
                    ),
                )
            record_points_billing_freeze(
                db=db,
                actor_user_id=current_user.id,
                actor_username=_safe_user_name(current_user),
                target_user_id=current_user.id,
                billing_key=billing_key,
                module_key=POINTS_BILLING_MODULE_NOVEL,
                amount_points=precheck.required_frozen_points,
                amount_yuan=precheck.estimated_yuan,
                title=f"小说协同扩展：{getattr(project, 'title', None) or request.project_id}",
                summary="小说协同扩展任务已启动，积分已按预估消耗冻结。",
                action_path=f"/workflow?project_id={int(request.project_id or 0)}",
                action_label="查看小说项目",
                request_context=None,
                default_request_method="POST",
                default_request_path="/api/v1/workflow/expand-story",
                operation_desc=f"小说协同扩展冻结积分 {precheck.required_frozen_points:.2f}",
                extra_payload={
                    "project_id": int(request.project_id or 0),
                    "task_id": task_id,
                    "expansion_mode": request.expansion_mode,
                    "target_total_chapters": request.target_total_chapters,
                    "target_total_characters": request.target_total_characters,
                },
            )
            billing_frozen = True

        _create_story_expansion_history_record(
            db,
            project_id=request.project_id,
            task_id=task_id,
        )

        _enqueue_story_expansion_task(
            task_id=task_id,
            request=request,
            user_id=current_user.id,
        )

        response_payload = StoryExpansionStartResponse.model_validate(
            _build_task_start_response(
                task_id=task_id,
                message="协同拓展任务已启动，正在后台分析人物与大纲的增量缺口...",
            )
        )
        return response_payload.model_dump(mode="python", exclude_none=True)

    except HTTPException:
        if billing_frozen and task_id:
            _release_story_expansion_billing_safely(
                db=db,
                user_id=int(getattr(current_user, "id", 0) or 0),
                username=_safe_user_name(current_user),
                task_id=task_id,
                reason="小说协同扩展启动失败，已释放冻结积分。",
                project_id=request.project_id,
            )
        raise
    except Exception as e:
        if billing_frozen and task_id:
            _release_story_expansion_billing_safely(
                db=db,
                user_id=int(getattr(current_user, "id", 0) or 0),
                username=_safe_user_name(current_user),
                task_id=task_id,
                reason="小说协同扩展启动异常，已释放冻结积分。",
                project_id=request.project_id,
            )
        logger.error(f"❌ 启动协同拓展任务失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


async def execute_expand_story_task(
    task_id: str,
    project_id: int,
    user_id: int,
    current_outline: str,
    world_setting: str,
    characters: str,
    current_chapter_count: int,
    current_character_count: int,
    target_total_chapters: Optional[int],
    target_total_characters: Optional[int],
    strategy: str,
    intent: str,
    enable_auto_supplement: bool,
    expansion_mode: str,
    total_volumes: Optional[int],
    total_chapters_min: Optional[int],
    total_chapters_max: Optional[int],
    target_volume_index: Optional[int],
    volume_chapters_min: Optional[int],
    volume_chapters_max: Optional[int],
    preserve_written_mode: str,
    volume_character_increment: Optional[int] = None,
    reset_epic_framework: bool = False,
):
    """后台执行协同拓展任务。"""
    from app.db.base import SessionLocal

    logger.info(f"🚀 开始执行后台任务: {task_id}, 协同拓展")
    db = SessionLocal()

    try:
        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=0,
            message="🧭 开始分析大纲与人物的协同缺口...",
        )

        prepared_request_bundle = await _prepare_story_execution_request(
            ExpandStoryRequest(
                project_id=project_id,
                current_outline=current_outline,
                world_setting=world_setting,
                characters=characters,
                current_chapter_count=current_chapter_count,
                current_character_count=current_character_count,
                target_total_chapters=target_total_chapters,
                target_total_characters=target_total_characters,
                strategy=strategy,
                intent=intent,
                enable_auto_supplement=enable_auto_supplement,
                expansion_mode=expansion_mode,
                total_volumes=total_volumes,
                total_chapters_min=total_chapters_min,
                total_chapters_max=total_chapters_max,
                target_volume_index=target_volume_index,
                volume_chapters_min=volume_chapters_min,
                volume_chapters_max=volume_chapters_max,
                volume_character_increment=volume_character_increment,
                preserve_written_mode=preserve_written_mode,
                reset_epic_framework=reset_epic_framework,
            ),
            db,
        )
        prepared_request = prepared_request_bundle["request"]
        _validate_story_framework_mode_switch(prepared_request, db)
        execution_context_warnings = list(prepared_request_bundle.get("warnings") or [])
        written_chapter_context = {
            "applied": bool(prepared_request_bundle.get("applied")),
            "written_chapter_count": int(prepared_request_bundle.get("written_chapter_count") or 0),
            "preserve_written_mode": preserve_written_mode,
        }

        analysis_bundle = _build_story_expansion_analysis(
            request=prepared_request,
            db=db,
        )
        coordinator = analysis_bundle["coordinator"]
        combined_world_setting = analysis_bundle["combined_world_setting"]
        analysis = analysis_bundle["analysis"]
        volume_detail_config = analysis_bundle.get("volume_detail_config")
        effective_target_total_chapters = analysis.get("effective_target_chapter_count")
        effective_target_total_characters = analysis.get("effective_target_character_count")
        effective_strategy = analysis.get("effective_strategy") or strategy
        effective_intent = analysis.get("effective_intent") or intent
        effective_expansion_mode = analysis.get("effective_expansion_mode") or expansion_mode
        epic_config = analysis.get("epic_config") or _resolve_story_epic_config(
            ExpandStoryRequest(
                project_id=project_id,
                current_outline=current_outline,
                world_setting=world_setting,
                characters=characters,
                current_chapter_count=current_chapter_count,
                current_character_count=current_character_count,
                target_total_chapters=target_total_chapters,
                target_total_characters=target_total_characters,
                strategy=strategy,
                intent=intent,
                enable_auto_supplement=enable_auto_supplement,
                expansion_mode=expansion_mode,
                total_volumes=total_volumes,
                total_chapters_min=total_chapters_min,
                total_chapters_max=total_chapters_max,
                target_volume_index=target_volume_index,
                volume_chapters_min=volume_chapters_min,
                volume_chapters_max=volume_chapters_max,
                volume_character_increment=volume_character_increment,
                preserve_written_mode=preserve_written_mode,
            )
        )
        warnings = list(analysis.get("warnings") or [])
        warnings.extend(execution_context_warnings)
        analysis["warnings"] = list(dict.fromkeys(item for item in warnings if item))
        analysis["written_chapter_context"] = written_chapter_context
        analysis = _apply_story_expansion_duration_calibration_safely(
            db,
            user_id=user_id,
            project_id=project_id,
            analysis=analysis,
        )
        analysis = StoryExpansionAnalysisPayload.model_validate(analysis).model_dump(
            mode="python",
            exclude_none=True,
        )
        auto_supplement_plan = (
            analysis.get("auto_supplement")
            if enable_auto_supplement and prepared_request.target_total_characters is None
            else None
        )

        mode_info = {
            "mode": analysis.get("execution_mode", "delta"),
            "reason": analysis.get("execution_mode_reason", ""),
        }
        mode_messages = {
            "delta": "🧠 正在生成单轮协同 delta 计划...",
            "iterative": "🧠 正在编排分轮协同扩展计划...",
            "epic": "🧠 正在规划长篇框架优先的协同扩展...",
            "volume_detail": "🧠 正在编排单卷细化协同计划...",
        }

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=18,
            message=mode_messages.get(mode_info.get("mode", "delta"), "🧠 正在生成协同扩展计划..."),
        )

        result = await asyncio.to_thread(
            coordinator.execute,
            current_outline=prepared_request.current_outline,
            characters=characters,
            world_setting=combined_world_setting,
            target_total_chapters=effective_target_total_chapters,
            target_total_characters=effective_target_total_characters,
            strategy=effective_strategy,
            expansion_mode=effective_expansion_mode,
            epic_config=epic_config,
            volume_detail_config=volume_detail_config,
            auto_supplement_plan=auto_supplement_plan,
            structural_debt=_load_structural_debt_from_history(db, project_id),
        )

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=72,
            message="💾 正在保存协同拓展结果...",
        )

        workflow_context_builder = WorkflowContextBuilder(db)
        # 捕获执行前的 epic 框架状态：用于判定本次 epic 是"重建"还是"首次创建"
        _prior_epic_state = workflow_context_builder.load_epic_framework_state(project_id)
        had_epic_framework_before = bool(
            (_prior_epic_state.epic_framework or "").strip()
            or (_prior_epic_state.epic_volumes_detail or "").strip()
        )
        update_fields = {
            "plot_outline": result["plot_outline"],
            "characters": result["characters"],
        }
        if result.get("execution_mode") == "epic" and result.get("epic_framework"):
            update_fields.update(
                {
                    "epic_framework": result.get("epic_framework", result["plot_outline"]),
                    "epic_volumes_detail": result.get("epic_volumes_detail", ""),
                    "epic_framework_generated_at": utc_now().isoformat(),
                }
            )
        elif result.get("execution_mode") == "volume_detail" and result.get("epic_framework"):
            update_fields.update(
                {
                    "epic_framework": result.get("epic_framework", result["plot_outline"]),
                    "epic_volumes_detail": result.get("epic_volumes_detail", ""),
                }
            )
        elif reset_epic_framework:
            update_fields.update(
                {
                    "epic_framework": None,
                    "epic_volumes_detail": None,
                    "epic_framework_generated_at": None,
                }
            )

        workflow_context_builder.update_project_settings_fields(project_id, **update_fields)

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=84,
            message="👥 正在同步人物卡与关系...",
        )

        sync_result = {"parsed": 0, "created": 0, "updated": 0, "skipped": 0}
        relationship_result = {"parsed": 0, "saved": 0, "characters_updated": 0}
        character_archive = {"archived": 0, "names": []}

        try:
            from app.services.character_parser import (
                parse_and_sync_characters,
                parse_and_sync_relationships,
                archive_orphan_expansion_characters,
            )

            character_sync_text, character_sync_source = _select_story_character_sync_source(result)
            if character_sync_text:
                sync_result = parse_and_sync_characters(
                    project_id=project_id,
                    characters_text=character_sync_text,
                    db_session=db,
                )
                logger.info(
                    "✅ 协同拓展人物卡同步完成：project_id=%s, source=%s, parsed=%s, created=%s, updated=%s",
                    project_id,
                    character_sync_source,
                    sync_result.get("parsed", 0),
                    sync_result.get("created", 0),
                    sync_result.get("updated", 0),
                )

                # epic 框架重建：归档旧框架遗留、新框架不再引用的扩展管线人物卡。
                # 仅当本轮成功解析出人物卡时执行（解析失败时不清空整表）；
                # 手动创建/历史卡片（source 为 NULL）不受影响。
                if (
                    result.get("execution_mode") == "epic"
                    and had_epic_framework_before
                    and sync_result.get("parsed", 0) > 0
                ):
                    try:
                        character_archive = archive_orphan_expansion_characters(
                            project_id=project_id,
                            keep_normalized_names=sync_result.get("normalized_names") or [],
                            db_session=db,
                        )
                        if character_archive.get("archived"):
                            logger.info(
                                "🗂️ epic 重建归档孤立人物卡：project_id=%s, archived=%s",
                                project_id,
                                character_archive.get("archived"),
                            )
                    except Exception as archive_error:
                        logger.warning(f"⚠️ epic 重建归档孤立人物卡失败: {archive_error}")
            else:
                logger.info(
                    "ℹ️ 协同拓展未检测到可解析人物卡，跳过同步：project_id=%s",
                    project_id,
                )

            if result.get("character_relationships"):
                relationship_result = parse_and_sync_relationships(
                    project_id=project_id,
                    relationships_text=result["character_relationships"],
                    db_session=db,
                )
                sync_result["relationships"] = relationship_result
        except Exception as sync_error:
            logger.warning(f"⚠️ 协同拓展后同步人物失败: {sync_error}")

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=92,
            message="📚 正在同步向量库...",
        )

        try:
            from app.models.character import Character
            from app.services.vector_sync import sync_to_vector_db, upsert_character_to_vector_db

            if result["plot_outline"]:
                sync_to_vector_db(
                    kb_type="plot",
                    name=f"project_{project_id}_plot_outline",
                    content=result["plot_outline"],
                    metadata={
                        "project_id": str(project_id),
                        "type": "plot_outline",
                    },
                )

            characters_in_db = (
                db.query(Character)
                .filter(
                    Character.project_id == project_id,
                    Character.archived_at.is_(None),
                )
                .all()
            )
            for char in characters_in_db:
                char_content = f"""
人物名称: {char.name}
故事立场: {char.role or '未设定'}
角色定位: {getattr(char, 'role_position', None) or '未设定'}
所属势力: {char.faction or '未设定'}
状态: {char.life_status or '未知'}
简介: {char.summary or ''}
详细信息: {char.profile or ''}
""".strip()
                upsert_character_to_vector_db(
                    character_id=char.id,
                    character_name=char.name,
                    content=char_content,
                    project_id=project_id,
                    metadata={
                        "character_id": str(char.id),
                        "name": char.name,
                        "role": char.role or "",
                        "role_position": getattr(char, "role_position", None) or "",
                    },
                )
        except Exception as vector_error:
            logger.warning(f"⚠️ 协同拓展后同步向量库失败: {vector_error}")

        before_stats = result.get("validation_before") or {}
        after_stats = result.get("validation_after") or {}
        # 起始计数与最终计数保持同一解析口径，避免框架大纲下 validation_before 低估。
        initial_chapter_count = _resolve_story_result_count(
            reported_count=prepared_request.current_chapter_count,
            parsed_count=_estimate_chapter_count_from_text(prepared_request.current_outline or ""),
            validation_count=before_stats.get("chapter_count"),
            fallback_count=current_chapter_count,
        )
        initial_character_count = _resolve_story_result_count(
            reported_count=prepared_request.current_character_count,
            parsed_count=_estimate_character_count_from_text(prepared_request.characters or ""),
            validation_count=before_stats.get("character_count"),
            fallback_count=current_character_count,
        )
        final_chapter_count = _resolve_story_result_count(
            reported_count=result.get("current_chapter_count"),
            parsed_count=_estimate_chapter_count_from_text(result.get("plot_outline", "")),
            validation_count=after_stats.get("chapter_count"),
            fallback_count=prepared_request.current_chapter_count,
        )
        final_character_count = _resolve_story_result_count(
            reported_count=result.get("current_character_count"),
            parsed_count=_estimate_character_count_from_text(result.get("characters", "")),
            validation_count=after_stats.get("character_count"),
            fallback_count=current_character_count,
        )
        normalized_character_sync, character_sync_warnings = _normalize_story_character_sync_result(sync_result)
        alignment_warnings = list(result.get("alignment_warnings", []))
        alignment_warnings.extend(character_sync_warnings)
        alignment_warnings = list(dict.fromkeys(str(item).strip() for item in alignment_warnings if str(item).strip()))
        result_plan = result.get("plan") or {}
        target_chapter_count = (
            result_plan.get("target_chapter_count")
            or effective_target_total_chapters
            or target_total_chapters
            or final_chapter_count
        )
        target_character_count = (
            result_plan.get("target_character_count")
            or effective_target_total_characters
            or target_total_characters
            or final_character_count
        )
        if result.get("execution_mode") == "volume_detail":
            volume_count_range = result.get("volume_chapter_count_range") or result_plan.get("volume_chapter_count_range")
            volume_chapter_count = result.get("volume_chapter_count") or result_plan.get("volume_chapter_count")
            if isinstance(volume_count_range, (list, tuple)) and len(volume_count_range) == 2:
                try:
                    lower = max(1, int(volume_count_range[0] or 1))
                    upper = max(lower, int(volume_count_range[1] or lower))
                    actual = int(volume_chapter_count or 0)
                    if lower <= actual <= upper:
                        target_chapter_count = final_chapter_count
                except Exception:
                    pass
        goal_reached = (
            final_chapter_count >= int(target_chapter_count or 0)
            and final_character_count >= int(target_character_count or 0)
        )
        stop_reasons = list(
            dict.fromkeys(
                str(item).strip()
                for item in (result.get("stop_reasons") or [])
                if str(item).strip()
            )
        )
        pending_parts: list[str] = []
        if final_chapter_count < int(target_chapter_count or 0):
            chapter_gap = int(target_chapter_count or 0) - final_chapter_count
            pending_parts.append(f"章节尚差 {chapter_gap} 章")
            stop_reasons.append(f"章节尚差 {chapter_gap} 章，需继续发起下一次协同。")
        if final_character_count < int(target_character_count or 0):
            character_gap = int(target_character_count or 0) - final_character_count
            pending_parts.append(f"人物尚差 {character_gap} 人")
            stop_reasons.append(f"人物尚差 {character_gap} 人，需继续发起下一次协同。")
        stop_reasons = list(dict.fromkeys(stop_reasons))
        completion_status = "completed" if goal_reached else "partial"
        coordination_summary = str(result.get("coordination_summary") or "").strip()
        if pending_parts:
            partial_summary = f"本次协同已完成当前可确认增量，{'，'.join(pending_parts)}。"
            if not coordination_summary:
                coordination_summary = partial_summary
            elif all(keyword not in coordination_summary for keyword in ("阶段性", "尚差", "继续发起下一次协同")):
                coordination_summary = f"{partial_summary} {coordination_summary}"
        task_message = (
            f"✅ 协同拓展完成！章节 {initial_chapter_count}"
            f" → {final_chapter_count}，人物 {initial_character_count}"
            f" → {final_character_count}"
            if goal_reached
            else (
                f"⚠️ 协同拓展已阶段性完成：章节 {initial_chapter_count}"
                f" → {final_chapter_count}，人物 {initial_character_count}"
                f" → {final_character_count}"
                f"；{'，'.join(pending_parts)}"
            )
        )

        task_result_payload = StoryExpansionTaskResultResponse.model_validate(
            {
                "expanded_outline": result["plot_outline"],
                "all_characters": result["characters"],
                "outline_delta": result.get("outline_delta", ""),
                "character_delta": result.get("character_delta", ""),
                "character_relationships": result.get("character_relationships", ""),
                "outline_ops": _normalize_story_result_outline_ops(result),
                "execution_mode": result.get("execution_mode", mode_info.get("mode", "delta")),
                "execution_mode_reason": result.get("execution_mode_reason", mode_info.get("reason", "")),
                "execution_rounds": result.get("execution_rounds", []),
                "new_characters": result.get("new_characters", []),
                "alignment_repairs": result.get("alignment_repairs", []),
                "alignment_gate_status": result.get("alignment_gate_status"),
                "alignment_gate_retry": result.get("alignment_gate_retry"),
                "alignment_structural_debt": result.get("alignment_structural_debt"),
                "character_plot_alignment": result.get("character_plot_alignment"),
                "story_strategy": result.get("strategy", effective_strategy),
                "story_intent": effective_intent,
                "story_expansion_mode": effective_expansion_mode,
                "story_preserve_written_mode": preserve_written_mode,
                "written_chapter_context": written_chapter_context,
                "volume_index": result.get("volume_index"),
                "volume_chapter_range": result.get("volume_chapter_range"),
                "coordination_summary": coordination_summary,
                "current_chapter_count": final_chapter_count,
                "target_chapter_count": target_chapter_count,
                "current_character_count": final_character_count,
                "target_character_count": target_character_count,
                "validation_before": before_stats,
                "validation_after": after_stats,
                "alignment_warnings": alignment_warnings,
                "character_sync": normalized_character_sync,
                "character_archive": {
                    "archived": int(character_archive.get("archived", 0) or 0),
                    "names": list(character_archive.get("names") or [])[:50],
                },
                "stop_reasons": stop_reasons,
                "expansion_analysis": analysis,
                "epic_total_volumes": result.get("epic_total_volumes"),
                "epic_chapter_range": result.get("epic_chapter_range"),
                "completion_status": completion_status,
                "goal_reached": goal_reached,
                "message": task_message,
            }
        ).model_dump(mode="python", exclude_none=True)

        project_title = None
        if supports_points_billing_session(db):
            try:
                project_row = db.query(Project).filter(Project.id == project_id).first()
                project_title = getattr(project_row, "title", None)
            except Exception:
                project_title = None
        _settle_story_expansion_billing_safely(
            db=db,
            user_id=user_id,
            username=f"user-{user_id}",
            task_id=task_id,
            project_id=project_id,
            project_title=project_title,
            initial_chapter_count=initial_chapter_count,
            final_chapter_count=final_chapter_count,
            initial_character_count=initial_character_count,
            final_character_count=final_character_count,
            execution_mode=task_result_payload.get("execution_mode"),
            execution_rounds=task_result_payload.get("execution_rounds"),
            epic_total_volumes=task_result_payload.get("epic_total_volumes"),
        )

        _update_story_expansion_history_record(
            db,
            task_id=task_id,
            status="completed",
            result=task_result_payload,
        )
        await ws_manager.send_task_complete(
            project_id=project_id,
            task_id=task_id,
            result=task_result_payload,
        )

    except Exception as e:
        logger.error(f"❌ 后台协同拓展失败: {str(e)}")
        _release_story_expansion_billing_safely(
            db=db,
            user_id=user_id,
            username=f"user-{user_id}",
            task_id=task_id,
            reason="小说协同扩展任务失败，已释放冻结积分。",
            project_id=project_id,
        )
        _update_story_expansion_history_record(
            db,
            task_id=task_id,
            status="failed",
            error=str(e),
        )
        await ws_manager.send_task_error(
            project_id=project_id,
            task_id=task_id,
            error=str(e),
        )
    finally:
        db.close()


