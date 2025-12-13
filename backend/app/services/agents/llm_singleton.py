"""
LLM实例单例管理器 - 避免重复创建，提升性能

性能优化：
- 减少初始化耗时约8秒
- 避免重复网络连接
- 内存占用更优
"""
from typing import Dict, Optional
from langchain_openai import ChatOpenAI
from .config import Config
import os
import logging


class LLMSingletonManager:
    """LLM实例单例管理器"""
    
    _instances: Dict[str, ChatOpenAI] = {}
    
    @classmethod
    def get_llm(cls, task_type: str = "default") -> ChatOpenAI:
        """获取LLM实例（单例模式）
        
        Args:
            task_type: 任务类型
            
        Returns:
            ChatOpenAI实例
        """
        # 任务类型到模型的映射
        task_model_mapping = {
            "concept": "qwen-max",
            "worldview": "deepseek-reasoner",
            "character": "deepseek-reasoner",
            "outline": "qwen-long",
            "outline_expand": "qwen-long",
            "volume_detail_expand": "deepseek-reasoner",  # 🎆 单卷详细扩展使用R1深度推理
            "character_expand": "deepseek-reasoner",
            "chapter": "qwen-max",
            "dialogue": "qwen-max",
            "entity_extract": "qwen-turbo",
            "ai_trace": "qwen-max",
            "review": "deepseek-reasoner",
            "final_review": "deepseek-reasoner",
            "quality_review": "deepseek-reasoner",
            "summarize": "qwen-turbo",  # 新增: AI摘要任务
        }
        
        selected_model = task_model_mapping.get(task_type, Config.MODEL_NAME)
        
        # 检查是否已存在实例
        if selected_model in cls._instances:
            logging.debug(f"⚡ 复用LLM实例: {selected_model}")
            return cls._instances[selected_model]
        
        # 创建新实例
        if selected_model.startswith("qwen"):
            api_key = os.getenv("DASHSCOPE_API_KEY", Config.DEEPSEEK_API_KEY)
            api_base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        elif selected_model.startswith("deepseek"):
            api_key = Config.DEEPSEEK_API_KEY
            api_base = Config.DEEPSEEK_API_BASE
        else:
            api_key = Config.DEEPSEEK_API_KEY
            api_base = Config.DEEPSEEK_API_BASE
        
        logging.info(f"🤖 [模型选择] 任务类型={task_type} → 模型={selected_model}")
        
        llm = ChatOpenAI(
            model=selected_model,
            temperature=Config.TEMPERATURE,
            api_key=api_key,
            base_url=api_base
        )
        
        # 缓存实例
        cls._instances[selected_model] = llm
        logging.info(f"✅ 创建并缓存LLM实例: {selected_model}")
        
        return llm
    
    @classmethod
    def clear_cache(cls):
        """清空缓存（用于重置）"""
        cls._instances.clear()
        logging.info("🔄 LLM实例缓存已清空")


# 兼容旧接口
def create_deepseek_llm(task_type: str = "default") -> ChatOpenAI:
    """创建LLM实例（使用单例模式）"""
    return LLMSingletonManager.get_llm(task_type)


def get_model_for_task(task_type: str = "default") -> ChatOpenAI:
    """获取指定任务类型的LLM实例
    
    Args:
        task_type: 任务类型
        
    Returns:
        ChatOpenAI实例
    """
    return LLMSingletonManager.get_llm(task_type)
