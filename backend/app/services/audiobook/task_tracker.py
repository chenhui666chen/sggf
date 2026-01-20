"""
任务状态追踪器

追踪多Agent协作任务的执行状态
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
from enum import Enum
import uuid
import logging

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"  # 待执行
    RUNNING = "running"  # 执行中
    PAUSED = "paused"  # 暂停
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败
    CANCELLED = "cancelled"  # 已取消


class StageType(Enum):
    """处理阶段"""
    STRATEGY = "strategy"  # 策略制定
    SCRIPT_ADAPTATION = "script_adaptation"  # 剧本改编
    VOICE_DESIGN = "voice_design"  # 音色设计
    SOUND_DESIGN = "sound_design"  # 音效设计
    MUSIC_COMPOSITION = "music_composition"  # 音乐编曲
    QUALITY_REVIEW = "quality_review"  # 剧本质量评审
    AUDIO_PROMPT_REVIEW = "audio_prompt_review"  # 音频提示词审阅
    TTS_SYNTHESIS = "tts_synthesis"  # TTS合成
    AUDIO_MIXING = "audio_mixing"  # 音频混合
    FINAL_AUDIO_REVIEW = "final_audio_review"  # 最终音频评审


@dataclass
class StageProgress:
    """阶段进度"""
    stage: StageType
    status: TaskStatus
    progress: float = 0.0  # 0.0-1.0
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    error_message: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    
    def start(self):
        """开始阶段"""
        self.status = TaskStatus.RUNNING
        self.start_time = datetime.now().isoformat()
    
    def complete(self, metrics: Optional[Dict[str, Any]] = None):
        """完成阶段"""
        self.status = TaskStatus.COMPLETED
        self.progress = 1.0
        self.end_time = datetime.now().isoformat()
        if metrics:
            self.metrics.update(metrics)
    
    def fail(self, error: str):
        """标记失败"""
        self.status = TaskStatus.FAILED
        self.end_time = datetime.now().isoformat()
        self.error_message = error


@dataclass
class TaskInfo:
    """任务信息"""
    task_id: str
    chapter_id: int
    novel_genre: str
    novel_theme: str
    status: TaskStatus = TaskStatus.PENDING
    stages: Dict[StageType, StageProgress] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    current_stage: Optional[StageType] = None
    
    def update_stage(self, stage: StageType, progress: float):
        """更新阶段进度"""
        if stage in self.stages:
            self.stages[stage].progress = progress
            self.updated_at = datetime.now().isoformat()
    
    def get_overall_progress(self) -> float:
        """获取总体进度"""
        if not self.stages:
            return 0.0
        total = sum(s.progress for s in self.stages.values())
        return total / len(self.stages)


class TaskTracker:
    """任务追踪器"""
    
    def __init__(self):
        self.tasks: Dict[str, TaskInfo] = {}
        self._observers: List[Callable[[Dict[str, Any]], None]] = []
    
    def create_task(
        self,
        chapter_id: int,
        novel_genre: str,
        novel_theme: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """创建新任务"""
        task_id = str(uuid.uuid4())
        
        # 初始化所有阶段
        stages = {
            stage: StageProgress(stage=stage, status=TaskStatus.PENDING)
            for stage in StageType
        }
        
        task = TaskInfo(
            task_id=task_id,
            chapter_id=chapter_id,
            novel_genre=novel_genre,
            novel_theme=novel_theme,
            stages=stages,
            metadata=metadata or {}
        )
        
        self.tasks[task_id] = task
        self._notify(task_id)
        return task_id

    def add_observer(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """添加进度监听"""
        if callback not in self._observers:
            self._observers.append(callback)

    def remove_observer(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """移除进度监听"""
        if callback in self._observers:
            self._observers.remove(callback)

    def _notify(self, task_id: str) -> None:
        snapshot = self.get_task_status(task_id)
        if not snapshot:
            return
        for callback in list(self._observers):
            try:
                callback(snapshot)
            except Exception as exc:  # pragma: no cover
                logger.warning("TaskTracker observer failed: %s", exc)
    
    def start_stage(self, task_id: str, stage: StageType):
        """开始某个阶段"""
        if task_id in self.tasks:
            self.tasks[task_id].stages[stage].start()
            self.tasks[task_id].status = TaskStatus.RUNNING
            self.tasks[task_id].current_stage = stage
            self.tasks[task_id].updated_at = datetime.now().isoformat()
            self._notify(task_id)

    def update_stage_progress(
        self,
        task_id: str,
        stage: StageType,
        progress: float,
        metrics: Optional[Dict[str, Any]] = None,
    ):
        task = self.tasks.get(task_id)
        if not task:
            return

        stage_info = task.stages.get(stage)
        if not stage_info:
            return

        if stage_info.status == TaskStatus.PENDING:
            stage_info.start()
        if stage_info.status == TaskStatus.COMPLETED:
            return

        try:
            progress_value = float(progress)
        except (TypeError, ValueError):
            progress_value = stage_info.progress

        progress_value = max(0.0, min(1.0, progress_value))
        if progress_value < stage_info.progress:
            progress_value = stage_info.progress
        stage_info.progress = progress_value

        if metrics:
            stage_info.metrics.update(metrics)

        task.status = TaskStatus.RUNNING
        task.current_stage = stage
        task.updated_at = datetime.now().isoformat()
        self._notify(task_id)
    
    def complete_stage(
        self,
        task_id: str,
        stage: StageType,
        metrics: Optional[Dict[str, Any]] = None
    ):
        """完成某个阶段"""
        if task_id in self.tasks:
            self.tasks[task_id].stages[stage].complete(metrics)
            self.tasks[task_id].current_stage = stage
            self.tasks[task_id].updated_at = datetime.now().isoformat()
            self._notify(task_id)
    
    def fail_stage(self, task_id: str, stage: StageType, error: str):
        """标记阶段失败"""
        if task_id in self.tasks:
            self.tasks[task_id].stages[stage].fail(error)
            self.tasks[task_id].status = TaskStatus.FAILED
            self.tasks[task_id].current_stage = stage
            self.tasks[task_id].updated_at = datetime.now().isoformat()
            self._notify(task_id)
    
    def complete_task(self, task_id: str):
        """完成任务"""
        if task_id in self.tasks:
            self.tasks[task_id].status = TaskStatus.COMPLETED
            self.tasks[task_id].updated_at = datetime.now().isoformat()
            self._notify(task_id)
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        if task_id not in self.tasks:
            return None
        
        task = self.tasks[task_id]
        return {
            "task_id": task.task_id,
            "chapter_id": task.chapter_id,
            "status": task.status.value,
            "overall_progress": task.get_overall_progress(),
            "current_stage": task.current_stage.value if task.current_stage else None,
            "stages": {
                stage.value: {
                    "status": progress.status.value,
                    "progress": progress.progress,
                    "start_time": progress.start_time,
                    "end_time": progress.end_time,
                    "error": progress.error_message,
                    "metrics": progress.metrics
                }
                for stage, progress in task.stages.items()
            },
            "created_at": task.created_at,
            "updated_at": task.updated_at
        }
    
    def get_all_tasks(self) -> List[Dict[str, Any]]:
        """获取所有任务状态"""
        return [self.get_task_status(task_id) for task_id in self.tasks.keys()]
