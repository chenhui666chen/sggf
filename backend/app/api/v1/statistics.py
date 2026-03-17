"""
统计API - 提供工作流阶段耗时统计
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Dict, List
from datetime import datetime

from app.db.base import get_db
from app.models.user import User
from app.models.project import Project
from app.api.v1.auth import get_current_user

router = APIRouter(prefix="/api/v1/statistics", tags=["statistics"])


@router.get("/workflow/stage-durations")
async def get_stage_durations(
    project_id: int | None = None,
    recent_count: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, float]:
    """
    获取工作流各阶段的平均耗时（秒）

    Args:
        project_id: 可选，指定项目ID则只统计该项目的数据
        recent_count: 可选，只统计最近N次任务（默认为None，统计所有任务）
                     如果设置为3，则优先使用最近3次任务的平均耗时（自适应学习）
        current_user: 当前用户
        db: 数据库会话

    Returns:
        Dict[str, float]: 各阶段的平均耗时（秒）
        {
            "concept": 120.5,
            "structure": 90.3,
            "content": 180.7,
            "review": 60.2,
            "iteration": 75.8
        }
    """
    try:
        # ✅ 如果指定了 project_id，验证项目所有权
        if project_id:
            project = db.query(Project).filter(
                Project.id == project_id,
                Project.user_id == current_user.id
            ).first()

            if not project:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Project not found or access denied"
                )

        # 🆕 如果指定了 recent_count，使用子查询获取每个阶段最近N次任务
        if recent_count:
            if project_id:
                # 只统计指定项目的最近N次任务
                query = text("""
                    SELECT
                        task_type,
                        AVG(duration_seconds) as avg_duration_seconds
                    FROM (
                        SELECT
                            task_type,
                            EXTRACT(EPOCH FROM (completed_at - created_at)) as duration_seconds,
                            ROW_NUMBER() OVER (PARTITION BY task_type ORDER BY completed_at DESC) as rn
                        FROM generation_history
                        WHERE
                            project_id = :project_id
                            AND status = 'completed'
                            AND completed_at IS NOT NULL
                            AND created_at IS NOT NULL
                            AND task_type LIKE 'workflow_stage_%'
                    ) ranked
                    WHERE rn <= :recent_count
                    GROUP BY task_type
                """)
                result = db.execute(query, {"project_id": project_id, "recent_count": recent_count}).fetchall()
            else:
                # 统计当前用户所有项目的最近N次任务
                query = text("""
                    SELECT
                        task_type,
                        AVG(duration_seconds) as avg_duration_seconds
                    FROM (
                        SELECT
                            gh.task_type,
                            EXTRACT(EPOCH FROM (gh.completed_at - gh.created_at)) as duration_seconds,
                            ROW_NUMBER() OVER (PARTITION BY gh.task_type ORDER BY gh.completed_at DESC) as rn
                        FROM generation_history gh
                        INNER JOIN projects p ON gh.project_id = p.id
                        WHERE
                            p.user_id = :user_id
                            AND gh.status = 'completed'
                            AND gh.completed_at IS NOT NULL
                            AND gh.created_at IS NOT NULL
                            AND gh.task_type LIKE 'workflow_stage_%'
                    ) ranked
                    WHERE rn <= :recent_count
                    GROUP BY task_type
                """)
                result = db.execute(query, {"user_id": current_user.id, "recent_count": recent_count}).fetchall()
        else:
            # 原有逻辑：统计所有历史数据
            if project_id:
                # 只统计指定项目的数据
                query = text("""
                    SELECT
                        task_type,
                        AVG(
                            EXTRACT(EPOCH FROM (completed_at - created_at))
                        ) as avg_duration_seconds
                    FROM generation_history
                    WHERE
                        project_id = :project_id
                        AND status = 'completed'
                        AND completed_at IS NOT NULL
                        AND created_at IS NOT NULL
                        AND task_type LIKE 'workflow_stage_%'
                    GROUP BY task_type
                """)
                result = db.execute(query, {"project_id": project_id}).fetchall()
            else:
                # 统计当前用户所有项目的数据
                query = text("""
                    SELECT
                        gh.task_type,
                        AVG(
                            EXTRACT(EPOCH FROM (gh.completed_at - gh.created_at))
                        ) as avg_duration_seconds
                    FROM generation_history gh
                    INNER JOIN projects p ON gh.project_id = p.id
                    WHERE
                        p.user_id = :user_id
                        AND gh.status = 'completed'
                        AND gh.completed_at IS NOT NULL
                        AND gh.created_at IS NOT NULL
                        AND gh.task_type LIKE 'workflow_stage_%'
                    GROUP BY gh.task_type
                """)
                result = db.execute(query, {"user_id": current_user.id}).fetchall()
        
        # 解析结果
        stage_durations = {}
        for row in result:
            task_type = row[0]  # 例如: "workflow_stage_concept"
            avg_duration = row[1]
            
            # 提取阶段名称
            if task_type.startswith("workflow_stage_"):
                stage_name = task_type.replace("workflow_stage_", "")
                stage_durations[stage_name] = round(avg_duration, 2)
        
        # 如果没有历史数据，返回默认值（基于经验估算）
        default_durations = {
            "concept": 120.0,    # 2分钟
            "structure": 90.0,   # 1.5分钟
            "content": 180.0,    # 3分钟
            "review": 60.0,      # 1分钟
            "iteration": 75.0    # 1.25分钟
        }
        
        # 合并默认值和实际统计值
        for stage in default_durations:
            if stage not in stage_durations:
                stage_durations[stage] = default_durations[stage]
        
        return stage_durations
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get stage durations: {str(e)}"
        )


@router.get("/workflow/stage-durations/detailed")
async def get_stage_durations_detailed(
    project_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Dict[str, float]]:
    """
    获取工作流各阶段的详细统计信息
    
    Returns:
        Dict[str, Dict[str, float]]: 各阶段的详细统计
        {
            "concept": {
                "avg": 120.5,
                "min": 80.0,
                "max": 200.0,
                "count": 10
            },
            ...
        }
    """
    try:
        # ✅ 如果指定了 project_id，验证项目所有权
        if project_id:
            project = db.query(Project).filter(
                Project.id == project_id,
                Project.user_id == current_user.id
            ).first()

            if not project:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Project not found or access denied"
                )

        # 构建查询
        if project_id:
            query = text("""
                SELECT
                    task_type,
                    AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) as avg_duration,
                    MIN(EXTRACT(EPOCH FROM (completed_at - created_at))) as min_duration,
                    MAX(EXTRACT(EPOCH FROM (completed_at - created_at))) as max_duration,
                    COUNT(*) as count
                FROM generation_history
                WHERE
                    project_id = :project_id
                    AND status = 'completed'
                    AND completed_at IS NOT NULL
                    AND created_at IS NOT NULL
                    AND task_type LIKE 'workflow_stage_%'
                GROUP BY task_type
            """)
            result = db.execute(query, {"project_id": project_id}).fetchall()
        else:
            query = text("""
                SELECT
                    gh.task_type,
                    AVG(EXTRACT(EPOCH FROM (gh.completed_at - gh.created_at))) as avg_duration,
                    MIN(EXTRACT(EPOCH FROM (gh.completed_at - gh.created_at))) as min_duration,
                    MAX(EXTRACT(EPOCH FROM (gh.completed_at - gh.created_at))) as max_duration,
                    COUNT(*) as count
                FROM generation_history gh
                INNER JOIN projects p ON gh.project_id = p.id
                WHERE
                    p.user_id = :user_id
                    AND gh.status = 'completed'
                    AND gh.completed_at IS NOT NULL
                    AND gh.created_at IS NOT NULL
                    AND gh.task_type LIKE 'workflow_stage_%'
                GROUP BY gh.task_type
            """)
            result = db.execute(query, {"user_id": current_user.id}).fetchall()

        # 解析结果
        stage_stats = {}
        for row in result:
            task_type = row[0]
            avg_duration = row[1]
            min_duration = row[2]
            max_duration = row[3]
            count = row[4]

            # 提取阶段名称
            if task_type.startswith("workflow_stage_"):
                stage_name = task_type.replace("workflow_stage_", "")
                stage_stats[stage_name] = {
                    "avg": round(avg_duration, 2),
                    "min": round(min_duration, 2),
                    "max": round(max_duration, 2),
                    "count": count
                }

        return stage_stats

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get detailed stage durations: {str(e)}"
        )
