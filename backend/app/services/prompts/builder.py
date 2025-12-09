"""
提示词统一组装器

负责将基础模块、阶段模块、题材模块组装成完整的提示词。
支持：
1. 模块化组装
2. 版本追踪
3. 动态注入
4. 优先级合并
5. 统计追踪（为提示词自动进化做准备）
"""

import logging
from typing import Dict, Optional, List, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
import hashlib

from .base.role import get_role
from .base.quality import get_quality_standard
from .base.format import get_output_format

logger = logging.getLogger(__name__)


@dataclass
class PromptModule:
    """提示词模块"""
    name: str                    # 模块名称
    content: str                 # 模块内容
    priority: int = 50           # 优先级（0-100，越高越靠前）
    enabled: bool = True         # 是否启用
    version: str = "1.0.0"       # 版本号
    category: str = "base"       # 分类: base/stage/genre


@dataclass
class PromptConfig:
    """提示词配置"""
    stage: str                           # 阶段名称
    genre: str = ""                      # 题材
    modules_enabled: Dict[str, bool] = field(default_factory=dict)  # 模块开关
    extra_context: Dict[str, str] = field(default_factory=dict)     # 额外上下文


class PromptBuilder:
    """
    提示词统一组装器
    
    使用方式:
        builder = PromptBuilder(stage="content_creation", genre="修仙")
        system_prompt = builder.build_system_prompt()
        user_prompt = builder.build_user_prompt(context={...})
    """
    
    def __init__(
        self,
        stage: str,
        genre: str = "",
        modules_enabled: Optional[Dict[str, bool]] = None
    ):
        """
        初始化组装器
        
        Args:
            stage: 阶段名称 (chapter_planning/content_creation/outline_expansion/etc.)
            genre: 题材名称 (修仙/玄幻/都市/etc.)
            modules_enabled: 模块开关配置
        """
        self.stage = stage
        self.genre = genre
        self.modules_enabled = modules_enabled or {}
        self._modules: List[PromptModule] = []
        self._build_time: Optional[datetime] = None
        
    def add_module(self, module: PromptModule) -> 'PromptBuilder':
        """添加模块"""
        if module.enabled and self.modules_enabled.get(module.name, True):
            self._modules.append(module)
        return self
    
    def add_text(
        self,
        name: str,
        content: str,
        priority: int = 50,
        category: str = "custom"
    ) -> 'PromptBuilder':
        """添加文本片段"""
        if content and content.strip():
            self._modules.append(PromptModule(
                name=name,
                content=content,
                priority=priority,
                category=category
            ))
        return self
    
    def with_role(self) -> 'PromptBuilder':
        """添加角色定义"""
        role_content = get_role(self.stage, self.genre)
        if role_content:
            self.add_text("role", role_content, priority=90, category="base")
        return self
    
    def with_quality_standard(self) -> 'PromptBuilder':
        """添加质量标准"""
        quality_content = get_quality_standard(self.stage)
        if quality_content:
            self.add_text("quality", quality_content, priority=30, category="base")
        return self
    
    def with_output_format(self, format_key: Optional[str] = None) -> 'PromptBuilder':
        """添加输出格式"""
        key = format_key or self.stage
        format_content = get_output_format(key)
        if format_content:
            self.add_text("format", format_content, priority=10, category="base")
        return self
    
    def with_genre_extension(self, genre_module: Dict[str, str], field: str) -> 'PromptBuilder':
        """添加题材扩展"""
        content = genre_module.get(field, "")
        if content and content.strip():
            self.add_text(
                name=f"genre_{field}",
                content=f"\n【题材专属细化】（以下为通用要求的具体落地方式，请结合使用）\n{content}",
                priority=40,
                category="genre"
            )
        return self
    
    def build(self) -> str:
        """
        组装最终提示词
        
        Returns:
            组装后的完整提示词
        """
        self._build_time = datetime.now()
        
        # 按优先级排序（高优先级在前）
        sorted_modules = sorted(self._modules, key=lambda m: -m.priority)
        
        # 组装内容
        parts = []
        for module in sorted_modules:
            if module.content and module.content.strip():
                parts.append(module.content.strip())
        
        return "\n\n".join(parts)
    
    def build_system_prompt(self) -> str:
        """构建 system prompt"""
        return self.build()
    
    def get_build_info(self) -> Dict[str, Any]:
        """获取构建信息（用于日志和追踪）"""
        return {
            "stage": self.stage,
            "genre": self.genre,
            "build_time": self._build_time.isoformat() if self._build_time else None,
            "modules": [
                {
                    "name": m.name,
                    "category": m.category,
                    "priority": m.priority,
                    "version": m.version,
                    "content_length": len(m.content)
                }
                for m in self._modules
            ]
        }
    
    def clear(self) -> 'PromptBuilder':
        """清空已添加的模块"""
        self._modules = []
        return self


    def with_stage_prompt(
        self,
        prompt_class: Any,
        method_name: str,
        **kwargs
    ) -> 'PromptBuilder':
        """
        添加阶段专属提示词
        
        Args:
            prompt_class: 阶段提示词类（如 ChapterPlanningPrompts）
            method_name: 方法名（如 'get_system_prompt'）
            **kwargs: 传递给方法的参数
        """
        method = getattr(prompt_class, method_name, None)
        if method:
            content = method(**kwargs)
            if content:
                self.add_text(
                    name=f"stage_{method_name}",
                    content=content,
                    priority=70,
                    category="stage"
                )
        return self
    
    def with_custom(
        self,
        name: str,
        content: str,
        priority: int = 50
    ) -> 'PromptBuilder':
        """
        添加自定义内容
        
        Args:
            name: 内容名称
            content: 内容文本
            priority: 优先级
        """
        if content and content.strip():
            self.add_text(name, content, priority=priority, category="custom")
        return self
    
    def get_content_hash(self) -> str:
        """获取内容哈希（用于缓存和去重）"""
        content = self.build()
        return hashlib.md5(content.encode()).hexdigest()[:16]
    
    def log_build_info(self):
        """记录构建信息到日志"""
        info = self.get_build_info()
        logger.info(f"PromptBuilder 构建完成: stage={info['stage']}, genre={info['genre']}")
        logger.debug(f"模块详情: {info['modules']}")


# ========== 便捷工厂函数 ==========

def create_prompt_builder(
    stage: str,
    genre: str = "",
    auto_add_base: bool = True
) -> PromptBuilder:
    """
    创建提示词组装器
    
    Args:
        stage: 阶段名称
        genre: 题材名称
        auto_add_base: 是否自动添加基础模块（角色、质量标准）
    
    Returns:
        配置好的 PromptBuilder 实例
    """
    builder = PromptBuilder(stage=stage, genre=genre)
    
    if auto_add_base:
        builder.with_role().with_quality_standard()
    
    return builder


# ========== 阶段专属快捷构建器 ==========

def build_chapter_planning_prompt(
    genre: str = "",
    genre_module: Optional[Dict[str, str]] = None
) -> str:
    """
    构建章节规划提示词
    
    Args:
        genre: 题材
        genre_module: 题材专属模块（来自 GENRE_PROMPT_MODULES）
    """
    from .stages.chapter_planning import ChapterPlanningPrompts
    
    builder = PromptBuilder(stage="chapter_planning", genre=genre)
    builder.add_text(
        "system",
        ChapterPlanningPrompts.get_system_prompt(genre),
        priority=90,
        category="stage"
    )
    
    if genre_module and genre_module.get("chapter_plan_guide"):
        builder.with_genre_extension(genre_module, "chapter_plan_guide")
    
    return builder.build()


def build_content_creation_prompt(
    genre: str = "",
    genre_module: Optional[Dict[str, str]] = None
) -> str:
    """
    构建内容创作提示词
    
    Args:
        genre: 题材
        genre_module: 题材专属模块
    """
    from .stages.content_creation import ContentCreationPrompts
    
    builder = PromptBuilder(stage="content_creation", genre=genre)
    builder.add_text(
        "system",
        ContentCreationPrompts.get_system_prompt(genre),
        priority=90,
        category="stage"
    )
    
    if genre_module:
        for field in ["opening_styles", "ending_styles", "rhythm_control"]:
            if genre_module.get(field):
                builder.with_genre_extension(genre_module, field)
    
    return builder.build()


def build_world_building_prompt(
    concept: str,
    genre: str = "",
    requirement: str = "",
    genre_module: Optional[Dict[str, str]] = None,
    genre_constraint: str = ""
) -> str:
    """
    构建世界观生成提示词
    
    Args:
        concept: 故事概念
        genre: 题材
        requirement: 用户要求
        genre_module: 题材专属模块
        genre_constraint: 题材约束
    """
    from .stages.world_building import WorldBuildingPrompts, get_genre_world_extension
    
    genre_extra = genre_module.get("world_extra_sections", "") if genre_module else ""
    if not genre_extra:
        genre_extra = get_genre_world_extension(genre)
    
    return WorldBuildingPrompts.get_world_prompt(
        concept=concept,
        genre=genre,
        requirement=requirement,
        genre_constraint=genre_constraint,
        genre_extra_sections=genre_extra
    )


def build_character_design_prompt(
    concept: str,
    world_setting: str,
    requirement: str = "",
    genre_module: Optional[Dict[str, str]] = None
) -> str:
    """
    构建人物设计提示词
    
    Args:
        concept: 故事概念
        world_setting: 世界观设定
        requirement: 用户要求
        genre_module: 题材专属模块
    """
    from .stages.world_building import CharacterDesignPrompts, get_genre_character_fields
    
    genre_extra = genre_module.get("character_extra_fields", "") if genre_module else ""
    if not genre_extra:
        # 尝试从题材获取
        pass
    
    return CharacterDesignPrompts.get_character_prompt(
        concept=concept,
        world_setting=world_setting,
        requirement=requirement,
        genre_extra_fields=genre_extra
    )


# ========== 进化追踪支持 ==========

@dataclass
class PromptUsageRecord:
    """
    提示词使用记录（为未来自动进化准备）
    
    可用于记录：
    - 哪些提示词组合生成了高质量内容
    - 哪些题材模块表现更好
    - AI率与提示词的关联
    """
    prompt_hash: str               # 提示词哈希
    stage: str                     # 阶段
    genre: str                     # 题材
    modules_used: List[str]        # 使用的模块列表
    timestamp: datetime            # 使用时间
    # 以下字段在生成完成后回填
    quality_score: Optional[float] = None   # 质量评分
    ai_rate: Optional[float] = None         # AI率
    user_feedback: Optional[str] = None     # 用户反馈


class PromptEvolutionTracker:
    """
    提示词进化追踪器（预留接口）
    
    未来可实现：
    1. 收集使用记录
    2. 分析效果数据
    3. 自动优化模块权重
    4. A/B测试不同模块组合
    """
    
    _instance: Optional['PromptEvolutionTracker'] = None
    
    def __init__(self):
        self._records: List[PromptUsageRecord] = []
    
    @classmethod
    def get_instance(cls) -> 'PromptEvolutionTracker':
        """获取单例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def record_usage(
        self,
        builder: PromptBuilder
    ) -> str:
        """
        记录提示词使用
        
        Returns:
            记录ID（prompt_hash）
        """
        info = builder.get_build_info()
        record = PromptUsageRecord(
            prompt_hash=builder.get_content_hash(),
            stage=builder.stage,
            genre=builder.genre,
            modules_used=[m['name'] for m in info['modules']],
            timestamp=datetime.now()
        )
        self._records.append(record)
        return record.prompt_hash
    
    def update_feedback(
        self,
        prompt_hash: str,
        quality_score: Optional[float] = None,
        ai_rate: Optional[float] = None,
        user_feedback: Optional[str] = None
    ):
        """
        更新反馈数据
        
        Args:
            prompt_hash: 提示词哈希
            quality_score: 质量评分 (0-100)
            ai_rate: AI率 (0-100)
            user_feedback: 用户反馈
        """
        for record in self._records:
            if record.prompt_hash == prompt_hash:
                if quality_score is not None:
                    record.quality_score = quality_score
                if ai_rate is not None:
                    record.ai_rate = ai_rate
                if user_feedback is not None:
                    record.user_feedback = user_feedback
                break
    
    def get_stats_by_genre(self, genre: str) -> Dict[str, Any]:
        """获取题材统计（预留接口）"""
        genre_records = [r for r in self._records if r.genre == genre]
        if not genre_records:
            return {"count": 0}
        
        quality_scores = [r.quality_score for r in genre_records if r.quality_score is not None]
        ai_rates = [r.ai_rate for r in genre_records if r.ai_rate is not None]
        
        return {
            "count": len(genre_records),
            "avg_quality": sum(quality_scores) / len(quality_scores) if quality_scores else None,
            "avg_ai_rate": sum(ai_rates) / len(ai_rates) if ai_rates else None
        }
