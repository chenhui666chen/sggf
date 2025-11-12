"""
增强版协调器 - 默认启用所有方案A功能

使用方式：
    from enhanced_coordinator import create_enhanced_coordinator
    
    # 自动启用所有功能
    coordinator = create_enhanced_coordinator()
    
    # 或者自定义配置
    coordinator = create_enhanced_coordinator(
        enable_conflict_detection=False  # 禁用某个功能
    )
"""
from typing import Optional
from agent_coordinator import CreativeDirectorCoordinator
from knowledge_base import NovelKnowledgeBase
from memory_manager import NovelMemoryManager


def create_enhanced_coordinator(
    knowledge_base: Optional[NovelKnowledgeBase] = None,
    memory_manager: Optional[NovelMemoryManager] = None,
    enable_communication: bool = True,      # 默认启用
    enable_conflict_detection: bool = True,  # 默认启用
    enable_detailed_logging: bool = True     # 默认启用
) -> CreativeDirectorCoordinator:
    """
    创建增强版协调器，默认启用所有方案A功能
    
    Args:
        knowledge_base: 知识库实例（可选）
        memory_manager: 记忆管理器实例（可选）
        enable_communication: 启用Agent通信中心（默认True）
        enable_conflict_detection: 启用冲突检测（默认True）
        enable_detailed_logging: 启用详细日志（默认True）
    
    Returns:
        配置好的CreativeDirectorCoordinator实例
    
    Examples:
        >>> # 最简单的方式：启用所有功能
        >>> coordinator = create_enhanced_coordinator()
        >>> result = coordinator.process_user_request("创作需求")
        
        >>> # 自定义配置
        >>> coordinator = create_enhanced_coordinator(
        ...     enable_detailed_logging=False  # 禁用详细日志
        ... )
    """
    return CreativeDirectorCoordinator(
        knowledge_base=knowledge_base,
        memory_manager=memory_manager,
        enable_communication=enable_communication,
        enable_conflict_detection=enable_conflict_detection,
        enable_detailed_logging=enable_detailed_logging
    )


def create_default_coordinator(
    knowledge_base: Optional[NovelKnowledgeBase] = None,
    memory_manager: Optional[NovelMemoryManager] = None
) -> CreativeDirectorCoordinator:
    """
    创建默认协调器，不启用新功能（向后兼容）
    
    Args:
        knowledge_base: 知识库实例（可选）
        memory_manager: 记忆管理器实例（可选）
    
    Returns:
        默认配置的CreativeDirectorCoordinator实例
    """
    return CreativeDirectorCoordinator(
        knowledge_base=knowledge_base,
        memory_manager=memory_manager,
        enable_communication=False,
        enable_conflict_detection=False,
        enable_detailed_logging=False
    )


# 为了方便，提供一个别名
EnhancedCoordinator = create_enhanced_coordinator
DefaultCoordinator = create_default_coordinator
