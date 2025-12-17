"""
监控指标收集器 - 统一管理系统指标埋点

核心功能：
1. 性能指标收集（API 响应时间、TTS 合成时长、音频生成时长）
2. 业务指标收集（章节生成成功率、重试次数、提供商切换）
3. 错误监控（异常追踪、错误率统计）
4. 资源监控（内存使用、缓存命中率、并发数）
"""
import time
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict
import threading
import asyncio

logger = logging.getLogger(__name__)


class MetricType(str, Enum):
    """指标类型"""
    COUNTER = "counter"        # 计数器（累加）
    GAUGE = "gauge"           # 仪表盘（瞬时值）
    HISTOGRAM = "histogram"   # 直方图（分布统计）
    TIMER = "timer"           # 计时器


class MetricCategory(str, Enum):
    """指标分类"""
    PERFORMANCE = "performance"   # 性能指标
    BUSINESS = "business"         # 业务指标
    ERROR = "error"               # 错误指标
    RESOURCE = "resource"         # 资源指标


@dataclass
class Metric:
    """单个指标"""
    name: str
    type: MetricType
    category: MetricCategory
    value: float
    timestamp: datetime = field(default_factory=datetime.now)
    labels: Dict[str, str] = field(default_factory=dict)
    description: str = ""


@dataclass
class TimerContext:
    """计时器上下文"""
    metric_name: str
    labels: Dict[str, str]
    start_time: float
    collector: 'MetricsCollector'
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        self.collector.record_timer(
            self.metric_name,
            duration,
            labels=self.labels,
            success=(exc_type is None)
        )
        return False


class MetricsCollector:
    """
    指标收集器 - 单例模式
    
    使用示例：
    >>> collector = MetricsCollector.get_instance()
    >>> collector.increment_counter("tts.requests", labels={"provider": "aliyun"})
    >>> with collector.timer("tts.synthesis", labels={"model": "v3-plus"}):
    ...     await synthesize_audio()
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __init__(self):
        # 指标存储（最近1小时）
        self.metrics: Dict[str, List[Metric]] = defaultdict(list)
        self._max_age = timedelta(hours=1)
        
        # 聚合统计（内存中）
        self.counters: Dict[str, Dict[tuple, float]] = defaultdict(lambda: defaultdict(float))
        self.gauges: Dict[str, Dict[tuple, float]] = defaultdict(lambda: defaultdict(float))
        self.histograms: Dict[str, Dict[tuple, List[float]]] = defaultdict(lambda: defaultdict(list))
        
        logger.info("✅ 指标收集器初始化成功")
    
    @classmethod
    def get_instance(cls) -> 'MetricsCollector':
        """获取单例实例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def _labels_to_tuple(self, labels: Optional[Dict[str, str]] = None) -> tuple:
        """将标签字典转换为可哈希的元组"""
        if not labels:
            return ()
        return tuple(sorted(labels.items()))
    
    def _cleanup_old_metrics(self):
        """清理过期指标"""
        cutoff_time = datetime.now() - self._max_age
        for metric_name in list(self.metrics.keys()):
            self.metrics[metric_name] = [
                m for m in self.metrics[metric_name]
                if m.timestamp >= cutoff_time
            ]
            if not self.metrics[metric_name]:
                del self.metrics[metric_name]
    
    def increment_counter(
        self,
        name: str,
        value: float = 1.0,
        labels: Optional[Dict[str, str]] = None,
        category: MetricCategory = MetricCategory.BUSINESS
    ):
        """递增计数器"""
        labels_tuple = self._labels_to_tuple(labels)
        self.counters[name][labels_tuple] += value
        
        metric = Metric(
            name=name,
            type=MetricType.COUNTER,
            category=category,
            value=value,
            labels=labels or {},
        )
        self.metrics[name].append(metric)
        self._cleanup_old_metrics()
    
    def set_gauge(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
        category: MetricCategory = MetricCategory.RESOURCE
    ):
        """设置仪表盘值"""
        labels_tuple = self._labels_to_tuple(labels)
        self.gauges[name][labels_tuple] = value
        
        metric = Metric(
            name=name,
            type=MetricType.GAUGE,
            category=category,
            value=value,
            labels=labels or {},
        )
        self.metrics[name].append(metric)
    
    def record_histogram(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
        category: MetricCategory = MetricCategory.PERFORMANCE
    ):
        """记录直方图数据点"""
        labels_tuple = self._labels_to_tuple(labels)
        self.histograms[name][labels_tuple].append(value)
        
        # 只保留最近1000个数据点（避免内存溢出）
        if len(self.histograms[name][labels_tuple]) > 1000:
            self.histograms[name][labels_tuple] = self.histograms[name][labels_tuple][-1000:]
        
        metric = Metric(
            name=name,
            type=MetricType.HISTOGRAM,
            category=category,
            value=value,
            labels=labels or {},
        )
        self.metrics[name].append(metric)
    
    def record_timer(
        self,
        name: str,
        duration: float,
        labels: Optional[Dict[str, str]] = None,
        success: bool = True
    ):
        """记录计时器结果"""
        # 计时器既是直方图（记录分布），也更新成功率计数器
        self.record_histogram(
            f"{name}.duration",
            duration,
            labels=labels,
            category=MetricCategory.PERFORMANCE
        )
        
        # 记录成功/失败次数
        result_labels = {**(labels or {}), "result": "success" if success else "failure"}
        self.increment_counter(
            f"{name}.count",
            value=1.0,
            labels=result_labels,
            category=MetricCategory.BUSINESS
        )
    
    def timer(
        self,
        name: str,
        labels: Optional[Dict[str, str]] = None
    ) -> TimerContext:
        """创建计时器上下文管理器"""
        return TimerContext(
            metric_name=name,
            labels=labels or {},
            start_time=time.time(),
            collector=self
        )
    
    def get_counter(self, name: str, labels: Optional[Dict[str, str]] = None) -> float:
        """获取计数器当前值"""
        labels_tuple = self._labels_to_tuple(labels)
        return self.counters.get(name, {}).get(labels_tuple, 0.0)
    
    def get_gauge(self, name: str, labels: Optional[Dict[str, str]] = None) -> Optional[float]:
        """获取仪表盘当前值"""
        labels_tuple = self._labels_to_tuple(labels)
        return self.gauges.get(name, {}).get(labels_tuple)
    
    def get_histogram_stats(
        self,
        name: str,
        labels: Optional[Dict[str, str]] = None
    ) -> Optional[Dict[str, float]]:
        """获取直方图统计信息（最小值、最大值、平均值、P50、P95、P99）"""
        labels_tuple = self._labels_to_tuple(labels)
        data = self.histograms.get(name, {}).get(labels_tuple, [])
        
        if not data:
            return None
        
        sorted_data = sorted(data)
        n = len(sorted_data)
        
        return {
            "count": n,
            "min": sorted_data[0],
            "max": sorted_data[-1],
            "avg": sum(sorted_data) / n,
            "p50": sorted_data[int(n * 0.5)],
            "p95": sorted_data[int(n * 0.95)],
            "p99": sorted_data[int(n * 0.99)],
        }
    
    def get_all_metrics(self) -> Dict[str, Any]:
        """获取所有指标的摘要"""
        summary = {
            "counters": {},
            "gauges": {},
            "histograms": {},
            "timestamp": datetime.now().isoformat()
        }
        
        # 汇总计数器
        for metric_name, label_values in self.counters.items():
            summary["counters"][metric_name] = {
                str(dict(labels)): value
                for labels, value in label_values.items()
            }
        
        # 汇总仪表盘
        for metric_name, label_values in self.gauges.items():
            summary["gauges"][metric_name] = {
                str(dict(labels)): value
                for labels, value in label_values.items()
            }
        
        # 汇总直方图
        for metric_name, label_values in self.histograms.items():
            summary["histograms"][metric_name] = {}
            for labels, data in label_values.items():
                label_str = str(dict(labels))
                stats = self.get_histogram_stats(metric_name, dict(labels))
                summary["histograms"][metric_name][label_str] = stats
        
        return summary
    
    def reset(self):
        """重置所有指标（仅用于测试）"""
        self.metrics.clear()
        self.counters.clear()
        self.gauges.clear()
        self.histograms.clear()
        logger.warning("⚠️ 所有指标已重置")


# 全局单例实例
metrics_collector = MetricsCollector.get_instance()
