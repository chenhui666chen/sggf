"""
监控 API - 提供指标查询接口

端点：
- GET /api/v1/monitoring/metrics - 获取所有指标摘要
- GET /api/v1/monitoring/health - 健康检查（带详细信息）
- GET /api/v1/monitoring/dashboard - 前端仪表板数据
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Dict, Any
import psutil
import os
from datetime import datetime

from app.db.base import get_db
from app.services.monitoring import metrics_collector
from app.api.v1.auth import get_current_user

router = APIRouter(prefix="/api/v1/monitoring", tags=["Monitoring"])


@router.get("/metrics")
async def get_metrics(
    current_user = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    获取所有指标摘要
    
    返回示例：
    {
        "counters": {
            "tts.requests": {
                "{'provider': 'aliyun'}": 42.0
            }
        },
        "gauges": {...},
        "histograms": {...},
        "timestamp": "2025-12-17T03:20:00"
    }
    """
    return metrics_collector.get_all_metrics()


@router.get("/health")
async def health_check(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    健康检查（带详细系统信息）
    
    返回系统资源使用情况、数据库连接状态等
    """
    # 系统资源监控
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    # 进程信息
    process = psutil.Process(os.getpid())
    process_memory = process.memory_info()
    
    # 数据库连接测试
    db_ok = False
    try:
        db.execute("SELECT 1")
        db_ok = True
    except Exception as e:
        db_ok = False
    
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "system": {
            "cpu_percent": cpu_percent,
            "memory_used_mb": memory.used / 1024 / 1024,
            "memory_total_mb": memory.total / 1024 / 1024,
            "memory_percent": memory.percent,
            "disk_used_gb": disk.used / 1024 / 1024 / 1024,
            "disk_total_gb": disk.total / 1024 / 1024 / 1024,
            "disk_percent": disk.percent,
        },
        "process": {
            "memory_mb": process_memory.rss / 1024 / 1024,
            "pid": process.pid,
            "threads": process.num_threads(),
        },
        "database": {
            "connected": db_ok,
        }
    }


@router.get("/dashboard")
async def get_dashboard_data(
    current_user = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    获取前端仪表板数据（格式化后的指标）
    
    包含：
    - TTS 合成统计
    - 音频生成统计
    - 章节生成统计
    - 错误率统计
    """
    all_metrics = metrics_collector.get_all_metrics()
    
    # TTS 指标
    tts_metrics = {
        "total_requests": metrics_collector.get_counter("tts.requests"),
        "aliyun_requests": metrics_collector.get_counter("tts.requests", {"provider": "aliyun"}),
        "success_count": metrics_collector.get_counter("tts.synthesis.count", {"result": "success"}),
        "failure_count": metrics_collector.get_counter("tts.synthesis.count", {"result": "failure"}),
        "retry_count": metrics_collector.get_counter("tts.retries"),
        "provider_switch_count": metrics_collector.get_counter("tts.provider_switch"),
        "avg_duration": None,
    }
    
    # 获取 TTS 平均耗时
    tts_duration_stats = metrics_collector.get_histogram_stats("tts.synthesis.duration")
    if tts_duration_stats:
        tts_metrics["avg_duration"] = tts_duration_stats["avg"]
        tts_metrics["p95_duration"] = tts_duration_stats["p95"]
    
    # 音频生成指标
    audio_metrics = {
        "mureka_requests": metrics_collector.get_counter("audio.mureka.requests"),
        "cache_hits": metrics_collector.get_counter("audio.cache.hits"),
        "cache_misses": metrics_collector.get_counter("audio.cache.misses"),
        "avg_generation_duration": None,
    }
    
    audio_duration_stats = metrics_collector.get_histogram_stats("audio.generation.duration")
    if audio_duration_stats:
        audio_metrics["avg_generation_duration"] = audio_duration_stats["avg"]
    
    # 章节生成指标
    chapter_metrics = {
        "total_generated": metrics_collector.get_counter("chapter.generated"),
        "success_count": metrics_collector.get_counter("chapter.generation.count", {"result": "success"}),
        "failure_count": metrics_collector.get_counter("chapter.generation.count", {"result": "failure"}),
    }
    
    # 错误指标
    error_metrics = {
        "total_errors": metrics_collector.get_counter("errors.total"),
        "tts_errors": metrics_collector.get_counter("errors", {"category": "tts"}),
        "audio_errors": metrics_collector.get_counter("errors", {"category": "audio"}),
    }
    
    # 计算成功率
    def calculate_success_rate(success: float, total: float) -> float:
        if total == 0:
            return 0.0
        return (success / total) * 100
    
    tts_total = tts_metrics["success_count"] + tts_metrics["failure_count"]
    chapter_total = chapter_metrics["success_count"] + chapter_metrics["failure_count"]
    
    return {
        "timestamp": all_metrics["timestamp"],
        "tts": {
            **tts_metrics,
            "success_rate": calculate_success_rate(tts_metrics["success_count"], tts_total),
        },
        "audio": audio_metrics,
        "chapter": {
            **chapter_metrics,
            "success_rate": calculate_success_rate(chapter_metrics["success_count"], chapter_total),
        },
        "errors": error_metrics,
    }
