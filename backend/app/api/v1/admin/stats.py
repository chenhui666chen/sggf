"""
数据统计仪表盘 API
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.permissions import require_admin, require_permission
from app.db.base import get_db
from app.models.user import User
from app.models.project import Project
from app.models.audiobook_task import AudiobookTask
from app.models.admin_log import AdminOperationLog
from app.models.role import Role
from app.schemas.admin import StatsOverview

router = APIRouter()


@router.get("/overview", response_model=StatsOverview)
async def get_stats_overview(
    current_user: User = Depends(require_permission("stats:read")),
    db: Session = Depends(get_db),
):
    """关键指标汇总"""
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    thirty_days_ago = now - timedelta(days=30)
    
    total_users = db.query(User).count()
    
    new_users_today = db.query(User).filter(
        User.created_at >= today_start
    ).count()
    
    active_users_30d = db.query(User).filter(
        User.updated_at >= thirty_days_ago
    ).count()
    
    total_projects = db.query(Project).count()
    
    active_projects = db.query(Project).filter(
        Project.status == "active"
    ).count()
    
    total_audiobook_tasks = db.query(AudiobookTask).count()
    
    admin_operations_today = db.query(AdminOperationLog).filter(
        AdminOperationLog.created_at >= today_start
    ).count()
    
    return StatsOverview(
        total_users=total_users,
        new_users_today=new_users_today,
        active_users_30d=active_users_30d,
        total_projects=total_projects,
        active_projects=active_projects,
        total_audiobook_tasks=total_audiobook_tasks,
        admin_operations_today=admin_operations_today,
    )


@router.get("/users/growth")
async def get_user_growth(
    days: int = 30,
    current_user: User = Depends(require_permission("stats:read")),
    db: Session = Depends(get_db),
):
    """用户增长趋势"""
    now = datetime.now()
    start_date = now - timedelta(days=days)
    
    daily_stats = db.query(
        func.date(User.created_at).label('date'),
        func.count(User.id).label('count')
    ).filter(
        User.created_at >= start_date
    ).group_by(
        func.date(User.created_at)
    ).all()
    
    return {
        "period": f"{days} days",
        "data": [
            {"date": str(stat.date), "count": stat.count}
            for stat in daily_stats
        ]
    }


@router.get("/projects/distribution")
async def get_project_distribution(
    current_user: User = Depends(require_permission("stats:read")),
    db: Session = Depends(get_db),
):
    """项目分布统计"""
    status_distribution = db.query(
        Project.status,
        func.count(Project.id).label('count')
    ).group_by(
        Project.status
    ).all()
    
    return {
        "by_status": [
            {"status": stat.status, "count": stat.count}
            for stat in status_distribution
        ]
    }


@router.get("/system/health")
async def get_system_health(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """系统运行状态"""
    try:
        db.execute("SELECT 1")
        db_status = "healthy"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    return {
        "database": db_status,
        "timestamp": datetime.now().isoformat(),
    }
