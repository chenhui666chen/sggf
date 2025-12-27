"""
模型优化器 - 根据任务类型智能选择最优模型
实现方案6：模型优化
"""
from enum import Enum
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """任务类型"""
    # 阶段一：概念开发
    CONCEPT_WORLD = "concept_world"           # 世界观设定
    CONCEPT_CHARACTER = "concept_character"   # 人物设定
    CONCEPT_STORY = "concept_story"           # 故事概念
    
    # 阶段二：结构设计
    STRUCTURE_PLOT = "structure_plot"         # 情节架构
    STRUCTURE_EVENTS = "structure_events"     # 事件验证
    
    # 阶段三：内容创作
    CONTENT_DRAFT = "content_draft"           # 章节初稿
    CONTENT_STYLE = "content_style"           # 文风优化
    
    # 阶段四：质量评审
    REVIEW_CHECK = "review_check"             # 质量评审
    
    # 阶段五：迭代优化
    ITERATION_OPTIMIZE = "iteration_optimize" # 迭代优化
    
    # 🆕 提示词进化专用
    REWRITE = "rewrite"                       # 文本改写（降低AI痕迹）
    
    # 🆕 拆书分析专用（信息提取，不需要深度推理）
    BOOK_ANALYSIS = "book_analysis"           # 书籍内容分析（单章）
    BOOK_SYNTHESIS = "book_synthesis"         # 书籍汇总分析（全书，用long）
    
    # 🎙️ 有声小说专用（6个专业Agent）
    AUDIOBOOK_DIRECTOR = "audiobook_director"           # 有声导演：策略制定
    AUDIOBOOK_SCRIPT = "audiobook_script"               # 剧本编剧：剧本改编
    AUDIOBOOK_VOICE = "audiobook_voice"                 # 音色设计：角色音色
    AUDIOBOOK_SOUND = "audiobook_sound"                 # 音效设计：场景音效
    AUDIOBOOK_MUSIC = "audiobook_music"                 # 音乐设计：背景音乐
    AUDIOBOOK_REVIEW = "audiobook_review"               # 质量评审：多维度评审


class ComplexityLevel(str, Enum):
    """复杂度级别"""
    SIMPLE = "simple"      # 简单任务
    MEDIUM = "medium"      # 中等复杂度
    COMPLEX = "complex"    # 复杂任务


class ModelOptimizer:
    """
    模型优化器
    
    根据任务类型和复杂度智能选择最优模型，在速度和质量间取得平衡
    """
    
    # 🎯 有声小说专用混合优化策略（平衡质量与速度）⭐⭐⭐⭐⭐
    AUDIOBOOK_BALANCED_STRATEGY = {
        # 阶段一：全部使用 chat（创意发散，不需要深度推理）
        TaskType.CONCEPT_WORLD: "qwen3-max",
        TaskType.CONCEPT_CHARACTER: "qwen3-max",
        TaskType.CONCEPT_STORY: "qwen3-max",
        
        # 阶段二：保持 reasoner（需要逻辑推理）
        TaskType.STRUCTURE_PLOT: "deepseek-reasoner",
        TaskType.STRUCTURE_EVENTS: "deepseek-reasoner",
        
        # 阶段三：保持 reasoner（内容质量关键）
        TaskType.CONTENT_DRAFT: "deepseek-reasoner",
        TaskType.CONTENT_STYLE: "deepseek-reasoner",
        
        # 阶段四：使用 chat（评审不需要深度推理）
        TaskType.REVIEW_CHECK: "qwen3-max",
        
        # 阶段五：使用 chat（修改润色）
        TaskType.ITERATION_OPTIMIZE: "qwen3-max",
        
        # 🆕 提示词进化：使用 chat（文风改写不需要推理，追求速度）
        TaskType.REWRITE: "deepseek-chat",
        
        # 🆕 拆书分析：使用 chat（信息提取不需要深度推理，且输入可能较长）
        TaskType.BOOK_ANALYSIS: "qwen3-max",
        
        # 🆕 拆书汇总：使用 qwen-long（全书摘要汇总，输入量大）
        TaskType.BOOK_SYNTHESIS: "qwen-long",
        
        # 🎙️ 有声小说混合优化：核心用R1，辅助用qwen3-max（速度提升60%，质量损失<10%）
        TaskType.AUDIOBOOK_DIRECTOR: "qwen3-max",       # 导演策略：升级到 qwen3-max
        TaskType.AUDIOBOOK_SCRIPT: "deepseek-reasoner",  # 🔥 剧本改编：保持R1（核心任务，质量优先！）
        TaskType.AUDIOBOOK_VOICE: "qwen3-max",          # 音色设计：升级到 qwen3-max
        TaskType.AUDIOBOOK_SOUND: "qwen3-max",          # 音效设计：升级到 qwen3-max
        TaskType.AUDIOBOOK_MUSIC: "qwen3-max",          # 音乐设计：升级到 qwen3-max
        TaskType.AUDIOBOOK_REVIEW: "qwen3-max",         # 质量评审：升级到 qwen3-max
    }
    # 保守优化策略（小说生成通用）
    CONSERVATIVE_STRATEGY = AUDIOBOOK_BALANCED_STRATEGY.copy()  # 使用混合策略作为默认
    AGGRESSIVE_STRATEGY = {
        # 阶段一：全部 chat
        TaskType.CONCEPT_WORLD: "qwen3-max",
        TaskType.CONCEPT_CHARACTER: "qwen3-max",
        TaskType.CONCEPT_STORY: "qwen3-max",
        
        # 阶段二：全部 chat
        TaskType.STRUCTURE_PLOT: "qwen3-max",
        TaskType.STRUCTURE_EVENTS: "qwen3-max",
        
        # 阶段三：初稿用 reasoner，优化用 chat
        TaskType.CONTENT_DRAFT: "deepseek-reasoner",
        TaskType.CONTENT_STYLE: "qwen3-max",
        
        # 阶段四：chat
        TaskType.REVIEW_CHECK: "qwen3-max",
        
        # 阶段五：chat
        TaskType.ITERATION_OPTIMIZE: "qwen3-max",
        
        # 🆕 提示词进化：chat
        TaskType.REWRITE: "deepseek-chat",
        
        # 🆕 拆书分析：chat
        TaskType.BOOK_ANALYSIS: "qwen3-max",
        
        # 🆕 拆书汇总：qwen-long
        TaskType.BOOK_SYNTHESIS: "qwen-long",
        
        # 🎙️ 有声小说：最大化速度，全部用快速模型
        TaskType.AUDIOBOOK_DIRECTOR: "qwen-turbo",       # 导演策略：用turbo加速
        TaskType.AUDIOBOOK_SCRIPT: "qwen3-max",         # 剧本改编：升级到 qwen3-max（保证质量）
        TaskType.AUDIOBOOK_VOICE: "qwen-turbo",         # 音色设计：turbo
        TaskType.AUDIOBOOK_SOUND: "qwen-turbo",         # 音效设计：turbo
        TaskType.AUDIOBOOK_MUSIC: "qwen-turbo",         # 音乐设计：turbo
        TaskType.AUDIOBOOK_REVIEW: "qwen3-max",          # 质量评审：升级到 qwen3-max
    }
    
    # 默认策略（不优化，全部使用 reasoner）
    DEFAULT_STRATEGY = {
        task: "deepseek-reasoner" for task in TaskType
    }
    DEFAULT_STRATEGY[TaskType.BOOK_ANALYSIS] = "qwen3-max"  # 拆书始终用 qwen3-max
    DEFAULT_STRATEGY[TaskType.BOOK_SYNTHESIS] = "qwen-long"      # 汇总始终用long
    # 有声小说使用默认模型（不优化时用reasoner）
    DEFAULT_STRATEGY[TaskType.AUDIOBOOK_DIRECTOR] = "deepseek-reasoner"
    DEFAULT_STRATEGY[TaskType.AUDIOBOOK_SCRIPT] = "deepseek-reasoner"
    DEFAULT_STRATEGY[TaskType.AUDIOBOOK_VOICE] = "deepseek-reasoner"
    DEFAULT_STRATEGY[TaskType.AUDIOBOOK_SOUND] = "deepseek-reasoner"
    DEFAULT_STRATEGY[TaskType.AUDIOBOOK_MUSIC] = "deepseek-reasoner"
    DEFAULT_STRATEGY[TaskType.AUDIOBOOK_REVIEW] = "deepseek-reasoner"
    
    def __init__(self, strategy: str = "conservative"):
        """
        初始化模型优化器
        
        Args:
            strategy: 优化策略
                - "conservative": 保守优化（推荐，质量无影响）
                - "aggressive": 激进优化（最大化速度）
                - "dynamic": 动态选择（根据复杂度）
                - "default": 不优化（全部 reasoner）
        """
        self.strategy = strategy
        logger.info(f"🚀 模型优化器已启用，策略: {strategy}")
        
        # 选择策略
        if strategy == "conservative":
            self.model_map = self.CONSERVATIVE_STRATEGY
        elif strategy == "aggressive":
            self.model_map = self.AGGRESSIVE_STRATEGY
        elif strategy == "default":
            self.model_map = self.DEFAULT_STRATEGY
        else:
            self.model_map = self.CONSERVATIVE_STRATEGY
    
    def select_model(
        self, 
        task_type: TaskType, 
        complexity: Optional[ComplexityLevel] = None,
        requirement: Optional[str] = None
    ) -> str:
        """
        选择最优模型
        
        Args:
            task_type: 任务类型
            complexity: 复杂度级别（可选）
            requirement: 用户需求文本（用于分析复杂度）
        
        Returns:
            模型名称
        """
        # 动态策略：根据复杂度选择
        if self.strategy == "dynamic":
            if complexity is None and requirement:
                complexity = self._analyze_complexity(requirement)
            
            return self._dynamic_select(task_type, complexity)
        
        # 其他策略：使用预定义映射
        model = self.model_map.get(task_type, "deepseek-reasoner")
        
        logger.info(f"📌 任务: {task_type.value} → 模型: {model}")
        return model
    
    def _dynamic_select(
        self, 
        task_type: TaskType, 
        complexity: Optional[ComplexityLevel]
    ) -> str:
        """
        动态选择模型（根据复杂度）
        
        策略：
        - 简单任务：全部用 chat
        - 复杂任务：核心阶段用 reasoner
        - 中等复杂度：大部分用 chat
        """
        # 降 AI 痕迹改写：固定使用 deepseek-chat（对降低 AI 率更友好）
        if task_type == TaskType.REWRITE:
            return "deepseek-chat"

        # 简单任务：全部用 chat
        if complexity == ComplexityLevel.SIMPLE:
            return "qwen3-max"
        
        # 复杂任务：核心阶段用 reasoner
        if complexity == ComplexityLevel.COMPLEX:
            if task_type in [
                TaskType.CONTENT_DRAFT,      # 章节创作
                TaskType.STRUCTURE_EVENTS,   # 事件验证
            ]:
                return "deepseek-reasoner"
            else:
                return "qwen3-max"
        
        # 中等复杂度：大部分用 chat（除了最关键的内容创作）
        if task_type == TaskType.CONTENT_DRAFT:
            return "deepseek-reasoner"
        else:
            return "qwen3-max"
    
    def _analyze_complexity(self, requirement: str) -> ComplexityLevel:
        """
        分析需求复杂度
        
        规则：
        - 包含复杂关键词 → complex
        - 超过500字 → medium
        - 其他 → simple
        """
        # 复杂度关键词
        complex_keywords = [
            "复杂", "深度", "逻辑", "推理", "多线索", "悬疑",
            "科幻", "奇幻", "史诗", "系列", "连载"
        ]
        
        # 检查关键词
        if any(kw in requirement for kw in complex_keywords):
            return ComplexityLevel.COMPLEX
        
        # 检查长度
        if len(requirement) > 500:
            return ComplexityLevel.MEDIUM
        
        return ComplexityLevel.SIMPLE
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """
        获取性能指标预测
        
        Returns:
            性能指标字典
        """
        # 统计每种模型的使用次数
        chat_count = sum(
            1 for model in self.model_map.values()
            if model in {"qwen3-max", "deepseek-chat"}
        )
        reasoner_count = sum(
            1 for model in self.model_map.values() 
            if model == "deepseek-reasoner"
        )
        
        total = len(self.model_map)
        chat_ratio = chat_count / total if total > 0 else 0
        
        # 性能提升估算
        # chat 比 reasoner 快 2.5倍，便宜 6倍
        speed_improvement = 1 + (chat_ratio * 1.5)  # 最多提升2.5倍
        cost_reduction = chat_ratio * 0.6  # 最多降低60%
        
        return {
            "strategy": self.strategy,
            "total_tasks": total,
            "chat_count": chat_count,
            "reasoner_count": reasoner_count,
            "chat_ratio": f"{chat_ratio:.1%}",
            "expected_speed_improvement": f"{(speed_improvement - 1) * 100:.0f}%",
            "expected_cost_reduction": f"{cost_reduction * 100:.0f}%",
            "quality_impact": "minimal" if self.strategy == "conservative" else "slight"
        }


# 全局单例
_optimizer = None


def get_model_optimizer(strategy: str = "conservative") -> ModelOptimizer:
    """
    获取模型优化器单例
    
    Args:
        strategy: 优化策略
    
    Returns:
        ModelOptimizer实例
    """
    global _optimizer
    if _optimizer is None:
        _optimizer = ModelOptimizer(strategy=strategy)
    return _optimizer


def set_optimization_strategy(strategy: str):
    """
    设置优化策略（会重新创建优化器）
    
    Args:
        strategy: 优化策略
    """
    global _optimizer
    _optimizer = ModelOptimizer(strategy=strategy)
    logger.info(f"✅ 优化策略已更新: {strategy}")


# 使用示例
if __name__ == "__main__":
    # 1. 保守优化（推荐）
    optimizer = get_model_optimizer("conservative")
    
    # 测试各阶段模型选择
    print("\n=== 保守优化策略 ===")
    for task in TaskType:
        model = optimizer.select_model(task)
        print(f"{task.value:30} → {model}")
    
    # 性能指标
    print("\n=== 性能预测 ===")
    metrics = optimizer.get_performance_metrics()
    for key, value in metrics.items():
        print(f"{key:30}: {value}")
    
    # 2. 动态优化
    print("\n\n=== 动态优化策略 ===")
    optimizer_dynamic = ModelOptimizer("dynamic")
    
    # 简单需求
    simple_req = "写一个爱情故事"
    print(f"\n需求: {simple_req}")
    for task in [TaskType.CONCEPT_STORY, TaskType.CONTENT_DRAFT]:
        model = optimizer_dynamic.select_model(task, requirement=simple_req)
        print(f"{task.value:30} → {model}")
    
    # 复杂需求
    complex_req = "创作一部逻辑严密的科幻悬疑小说，涉及多重世界观和复杂的时间线"
    print(f"\n需求: {complex_req}")
    for task in [TaskType.CONCEPT_STORY, TaskType.CONTENT_DRAFT]:
        model = optimizer_dynamic.select_model(task, requirement=complex_req)
        print(f"{task.value:30} → {model}")
    for task in [TaskType.CONCEPT_STORY, TaskType.CONTENT_DRAFT]:
        model = optimizer_dynamic.select_model(task, requirement=complex_req)
        print(f"{task.value:30} → {model}")
