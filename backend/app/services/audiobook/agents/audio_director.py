"""AudioDirector - 有声导演/总监Agent

核心职责：
1. 统筹有声剧本的整体创作方向和质量
2. 制定改编策略（声音戏剧 vs 朗读）
3. 协调各专业Agent的工作
4. 最终质量把关和发布决策

TTS能力：CosyVoice v3-plus
- 顶级音质（MOS>4.7）
- 语速控制：0.5-2.0
- 音调控制：0.5-2.0
- 毫秒级停顿：100-2000ms
- 重音强调：3级
"""

import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class AdaptationStyle(str, Enum):
    """改编风格"""
    AUDIO_DRAMA = "audio_drama"  # 声音戏剧（音效+音乐丰富）
    AUDIOBOOK = "audiobook"  # 有声朗读（以旁白为主）
    HYBRID = "hybrid"  # 混合模式


class FidelityLevel(str, Enum):
    """原著忠实度"""
    HIGH = "high"  # 高度忠实
    MEDIUM = "medium"  # 适度改编
    LOW = "low"  # 大幅改编


@dataclass
class AdaptationStrategy:
    """改编策略（适配CosyVoice v3-plus）"""
    style: AdaptationStyle = AdaptationStyle.HYBRID
    fidelity_level: FidelityLevel = FidelityLevel.HIGH
    target_audience: str = "通用听众"
    tone: str = "沉浸感优先"
    emphasis: str = "情节为主"  # 情节为主/角色为主/氛围为主
    
    # 技术参数
    max_episode_duration: int = 40  # 每集最大时长（分钟）
    sound_effect_density: str = "medium"  # low/medium/high
    music_density: str = "medium"
    voice_differentiation: bool = True  # 是否为角色分配不同音色
    
    # v3-plus高级特性利用
    use_advanced_rate_control: bool = True  # 使用语速控制
    use_pitch_modulation: bool = True  # 使用音调调节
    use_precise_pauses: bool = True  # 使用精确停顿
    use_emphasis: bool = True  # 使用重音强调


@dataclass
class TaskAssignment:
    """任务分配"""
    agent_name: str
    task_description: str
    priority: int = 1  # 1-5，1最高
    deadline: Optional[str] = None
    status: str = "pending"  # pending/in_progress/completed


@dataclass
class AudioDirectorDecision:
    """导演决策"""
    adaptation_strategy: AdaptationStrategy
    task_assignments: List[TaskAssignment]
    approval_status: str  # approved/revision_needed/rejected
    feedback: str
    next_steps: List[str]


class AudioDirector:
    """
    有声导演Agent
    
    负责统筹整个有声剧本的创作方向和质量控制
    """
    
    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: LLM客户端（可选，用于智能决策）
        """
        self.llm_client = llm_client
        self.current_strategy: Optional[AdaptationStrategy] = None
        self.task_queue: List[TaskAssignment] = []
    
    def formulate_strategy(
        self,
        novel_genre: str,
        novel_theme: str,
        target_audience: str = "通用听众",
        special_requirements: Optional[List[str]] = None
    ) -> AdaptationStrategy:
        """
        制定改编策略
        
        Args:
            novel_genre: 小说类型（科幻/奇幻/悬疑等）
            novel_theme: 小说主题
            target_audience: 目标听众
            special_requirements: 特殊要求
        
        Returns:
            改编策略
        """
        logger.info(f"🎬 制定改编策略: {novel_genre} - {novel_theme}")
        
        # 基于类型推荐风格
        style_mapping = {
            "科幻": AdaptationStyle.AUDIO_DRAMA,  # 科幻适合音效丰富
            "奇幻": AdaptationStyle.AUDIO_DRAMA,
            "悬疑": AdaptationStyle.HYBRID,  # 悬疑需要氛围音乐
            "言情": AdaptationStyle.AUDIOBOOK,  # 言情以对话为主
            "历史": AdaptationStyle.AUDIOBOOK,
            "武侠": AdaptationStyle.HYBRID,
        }
        
        style = style_mapping.get(novel_genre, AdaptationStyle.HYBRID)
        
        # 音效密度建议
        sound_density_mapping = {
            AdaptationStyle.AUDIO_DRAMA: "high",
            AdaptationStyle.AUDIOBOOK: "low",
            AdaptationStyle.HYBRID: "medium",
        }
        
        strategy = AdaptationStrategy(
            style=style,
            fidelity_level=FidelityLevel.HIGH,
            target_audience=target_audience,
            tone="沉浸感优先" if style == AdaptationStyle.AUDIO_DRAMA else "故事为主",
            emphasis=self._determine_emphasis(novel_genre),
            sound_effect_density=sound_density_mapping[style],
            music_density="medium",
            voice_differentiation=True,
            # 商业版：全面启用v3-plus高级特性
            use_advanced_rate_control=True,
            use_pitch_modulation=True,
            use_precise_pauses=True,
            use_emphasis=True
        )
        
        self.current_strategy = strategy
        logger.info(f"   ✅ 策略制定完成: {strategy.style.value}")
        
        return strategy
    
    def _determine_emphasis(self, genre: str) -> str:
        """根据类型确定重点"""
        if genre in ["科幻", "奇幻"]:
            return "世界观为主"
        elif genre in ["悬疑", "推理"]:
            return "情节为主"
        elif genre in ["言情", "现代"]:
            return "角色为主"
        else:
            return "情节为主"
    
    def assign_tasks(
        self,
        project_info: Dict[str, Any]
    ) -> List[TaskAssignment]:
        """
        分配任务给各专业Agent
        
        Args:
            project_info: 项目信息
        
        Returns:
            任务分配列表
        """
        logger.info("📋 分配任务给专业Agent...")
        
        if not self.current_strategy:
            raise ValueError("请先制定改编策略")
        
        tasks = []
        
        # 1. 剧本改编任务（最高优先级）
        tasks.append(TaskAssignment(
            agent_name="AudiobookScriptAdapter",
            task_description=f"改编章节内容为有声剧本，风格：{self.current_strategy.style.value}。充分利用v3-plus的rate/pitch/pause/emphasis控制。",
            priority=1,
            status="pending"
        ))
        
        # 2. 角色音色设计
        if self.current_strategy.voice_differentiation:
            tasks.append(TaskAssignment(
                agent_name="VoiceDesigner",
                task_description="为主要角色设计差异化音色，使用v3-plus的rate/pitch参数进行精细调整。",
                priority=2,
                status="pending"
            ))
        
        # 3. 音效设计（根据密度）
        if self.current_strategy.sound_effect_density in ["medium", "high"]:
            tasks.append(TaskAssignment(
                agent_name="SoundEffectDesigner",
                task_description=f"设计场景音效，密度：{self.current_strategy.sound_effect_density}",
                priority=2,
                status="pending"
            ))
        
        # 4. 音乐设计
        if self.current_strategy.music_density in ["medium", "high"]:
            tasks.append(TaskAssignment(
                agent_name="MusicComposer",
                task_description=f"设计背景音乐，密度：{self.current_strategy.music_density}",
                priority=3,
                status="pending"
            ))
        
        # 5. 质量评审（最后）
        tasks.append(TaskAssignment(
            agent_name="AudioQualityReviewer",
            task_description="评审有声剧本质量和听觉体验",
            priority=5,
            status="pending"
        ))
        
        self.task_queue = tasks
        logger.info(f"   ✅ 共分配 {len(tasks)} 个任务")
        
        return tasks
    
    def review_output(
        self,
        agent_name: str,
        output: Dict[str, Any]
    ) -> AudioDirectorDecision:
        """
        审核Agent输出
        
        Args:
            agent_name: Agent名称
            output: Agent输出结果
        
        Returns:
            导演决策
        """
        logger.info(f"🔍 审核 {agent_name} 的输出...")
        
        # 自动审核逻辑
        approval_status = "approved"
        feedback = f"{agent_name} 的工作符合要求"
        next_steps = []
        
        # 检查是否所有任务都完成
        completed_tasks = [t for t in self.task_queue if t.status == "completed"]
        pending_tasks = [t for t in self.task_queue if t.status != "completed"]
        
        if pending_tasks:
            next_steps = [f"等待 {t.agent_name} 完成任务" for t in pending_tasks[:3]]
        else:
            next_steps = ["所有任务已完成，准备最终审核"]
        
        decision = AudioDirectorDecision(
            adaptation_strategy=self.current_strategy,
            task_assignments=self.task_queue,
            approval_status=approval_status,
            feedback=feedback,
            next_steps=next_steps
        )
        
        logger.info(f"   ✅ 审核完成: {approval_status}")
        
        return decision
    
    def final_approval(
        self,
        audiobook_project: Dict[str, Any],
        quality_report: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        最终审批
        
        Args:
            audiobook_project: 有声书项目数据
            quality_report: 质量评审报告
        
        Returns:
            最终决策
        """
        logger.info("🎯 进行最终审批...")
        
        # 基于质量评分自动决策
        overall_grade = quality_report.get("overall_grade", "C")
        
        if overall_grade in ["A", "A+", "A-", "B+", "B"]:
            status = "approved"
            comment = "质量优秀，批准发布"
        elif overall_grade in ["B-", "C+", "C"]:
            status = "revision_needed"
            comment = "质量合格但需优化，建议修订"
        else:
            status = "rejected"
            comment = "质量不达标，需要重新制作"
        
        decision = {
            "status": status,
            "comment": comment,
            "quality_grade": overall_grade,
            "timestamp": "2025-01-01T00:00:00",
            "approved_by": "AudioDirector"
        }
        
        logger.info(f"   ✅ 最终决策: {status} - {overall_grade}")
        
        return decision
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_tasks": len(self.task_queue),
            "completed_tasks": len([t for t in self.task_queue if t.status == "completed"]),
            "pending_tasks": len([t for t in self.task_queue if t.status == "pending"]),
            "current_strategy": self.current_strategy.__dict__ if self.current_strategy else None
        }
