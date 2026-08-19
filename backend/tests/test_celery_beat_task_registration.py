# -*- coding: utf-8 -*-
"""Celery beat 计划任务注册完整性测试。

背景：beat 按计划发送 dispatch_stale_pending / billing_finalizer_scan /
run_shadow_batch，但任务定义分散在 services 模块与未被 app.tasks.__init__
导入的 experiment_tasks 中，autodiscover 覆盖不到，worker 以
"unregistered task" 丢弃消息，stale run 与计费结算永不自愈。
约束：beat_schedule 中的每个任务必须在 worker finalize（导入 include 与
autodiscover）后可用。
"""

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")


def test_beat_scheduled_tasks_are_registered_after_worker_finalize():
    from app.celery_app import celery_app

    # 模拟 worker 启动 finalize：导入 include 列表并执行 autodiscover
    celery_app.loader.import_default_modules()

    registered = set(celery_app.tasks.keys())
    scheduled = {
        str(entry["task"]) for entry in celery_app.conf.beat_schedule.values()
    }
    assert scheduled, "beat_schedule 不得为空"
    missing = scheduled - registered
    assert not missing, f"beat 计划任务未被 worker 注册: {sorted(missing)}"


def test_include_covers_beat_tasks_defined_outside_app_tasks_package():
    """定义在 services 模块的 beat 任务必须出现在 include 列表。"""
    from app.celery_app import celery_app

    include = set(celery_app.conf.include or [])
    assert "app.services.audiobook.dispatch_service" in include
    assert "app.services.audiobook.billing_finalizer_service" in include
    assert "app.tasks.experiment_tasks" in include
