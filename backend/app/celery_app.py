"""
Celery application instance for background audiobook jobs.
"""
import os
import sys

from celery import Celery
from celery.schedules import crontab
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
    # beat 调度任务的定义分散在 services 模块与未被 app.tasks.__init__ 导入的
    # experiment_tasks 中，autodiscover 覆盖不到；显式 include 保证 worker 注册
    include=[
        "app.services.audiobook.dispatch_service",
        "app.services.audiobook.billing_finalizer_service",
        "app.tasks.experiment_tasks",
        "app.tasks.account_anonymization_tasks",
    ],
)

# 确保 worker 侧也具备最新表结构：**仅开发环境** create_all 兜底；
# 非开发环境强制走 Alembic，避免导入 celery 时自动建表与版本链脱节
# （P2 批次 D 教训：audit_logs/consent_records 曾被自动先建出，迁移时 DuplicateTable）
try:
    from app.db.base import Base, engine  # noqa: WPS433
    from app.db.schema_compat import ensure_runtime_schema_compatibility  # noqa: WPS433
    import app.models  # noqa: F401,WPS433

    if settings.APP_ENV == "development":
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
    beat_schedule={
        # 可靠派发：每 2 分钟认领 stale pending run + 接管过期 worker 租约
        "audiobook-dispatch-stale-pending": {
            "task": "audiobook.dispatch_stale_pending",
            "schedule": crontab(minute="*/2"),
            "args": (20,),
        },
        # 计费 finalizer：每 3 分钟扫描可结算 run
        "audiobook-billing-finalizer-scan": {
            "task": "audiobook.billing_finalizer_scan",
            "schedule": crontab(minute="*/3"),
            "args": (20,),
        },
        "audiobook-cleanup-expired-temp-assets-hourly": {
            "task": "audiobook.cleanup_expired_temp_assets",
            "schedule": crontab(minute=17),
            "args": (100,),
        },
        # shadow 实验批处理：每 5 分钟认领并执行 pending 实验（EXPERIMENT_ENABLED 未开启时任务体空转）
        "prompt-experiment-run-shadow-batch": {
            "task": "prompt_experiment.run_shadow_batch",
            "schedule": crontab(minute="*/5"),
            "args": (5, 600),
        },
        # 四层校准：每 30 分钟重算并把四层全过的 shadow 挑战者推进到 eligible（EXPERIMENT_ENABLED 未开启时空转）
        "prompt-experiment-run-calibration": {
            "task": "prompt_experiment.run_calibration",
            "schedule": crontab(minute="*/30"),
        },
        # 进化启停调度：每 60 分钟逐题材采集信号并按三态决策转移（EXPERIMENT_ENABLED 未开启时空转）
        "prompt-experiment-run-scheduler-tick": {
            "task": "prompt_experiment.run_scheduler_tick",
            "schedule": crontab(minute=0),
        },
        # holdout 过拟合探针：每日低频对冠军做训练/留出新鲜复评并写缓存，供 tick 只读消费
        # （外部评分 API 有成本，冠军未变时任务体内部跳过重算；EXPERIMENT_ENABLED 未开启时空转）
        "prompt-experiment-run-holdout-eval": {
            "task": "prompt_experiment.run_holdout_eval",
            "schedule": crontab(hour=3, minute=40),
        },
        # 哨兵巡检探针：每 12 小时对 sleeping 题材用固定哨兵语料做冠军新鲜检测并写缓存，
        # 供 tick 只读消费唤醒（非 sleeping 题材跳过不调外部评分；EXPERIMENT_ENABLED 未开启时空转）
        "prompt-experiment-run-sentinel-probe": {
            "task": "prompt_experiment.run_sentinel_probe",
            "schedule": crontab(hour="4,16", minute=10),
        },
        # P2-5.3：每日低频匿名化超过冷却期的已注销账号（幂等，落库非 dry-run）
        "account-anonymize-expired-daily": {
            "task": "account.anonymize_expired",
            "schedule": crontab(hour=3, minute=30),
        },
    },
)

# Windows 下 Celery 无法使用 prefork 池，会触发 WinError 5。
# 自动强制使用 solo 池，避免用户忘记在命令行添加 `-P solo`。
if os.name == "nt":
    celery_app.conf.worker_pool = "solo"
    celery_app.conf.worker_concurrency = 1

# 任务发现：强制在 import 时完成加载，避免 worker 未 finalize 前任务未注册。
celery_app.autodiscover_tasks(["app"], force=True)
