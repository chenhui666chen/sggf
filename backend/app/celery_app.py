"""
Celery application instance for background audiobook jobs.
"""
import os
import sys

from celery import Celery
from app.core.env_loader import get_project_root, load_project_env

# 允许 Celery worker 直接 import 项目根目录下的轻量模块（如：pipeline/agents/adapters）
PROJECT_ROOT = get_project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

# ⚠️ 重要：先加载环境变量（必须在导入 settings 之前）
load_project_env(override=False)

from app.core.config import settings

celery_app = Celery(
    "novel_writing_agent",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

# 确保 worker 侧也具备最新表结构（开发环境 create_all 兜底；生产建议用 Alembic）
try:
    from app.db.base import Base, engine  # noqa: WPS433
    from app.db.schema_compat import ensure_runtime_schema_compatibility  # noqa: WPS433
    import app.models  # noqa: F401,WPS433

    Base.metadata.create_all(bind=engine)
    ensure_runtime_schema_compatibility()
except Exception:
    # 避免 Celery 启动因建表失败而直接退出，错误可在后续任务中暴露
    pass

celery_app.conf.update(
    task_default_queue="audiobook",
    task_default_exchange_type="direct",
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)

# Windows 下 Celery 无法使用 prefork 池，会触发 WinError 5。
# 自动强制使用 solo 池，避免用户忘记在命令行添加 `-P solo`。
if os.name == "nt":
    celery_app.conf.worker_pool = "solo"
    celery_app.conf.worker_concurrency = 1

# 任务发现：强制在 import 时完成加载，避免 worker 未 finalize 前任务未注册。
celery_app.autodiscover_tasks(["app"], force=True)
