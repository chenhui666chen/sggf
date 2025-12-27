"""
记忆管理器 - 管理对话上下文和短期记忆
增加持久化功能
"""
from typing import List, Dict, Any
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from typing import Optional
from .llm_singleton import create_deepseek_llm


# 简化Memory实现（替代LangChain已移除的Memory模块）
class SimpleChatMemory:
    """简化的聊天记忆实现"""
    
    def __init__(self):
        self.messages: List[BaseMessage] = []
    
    def add_user_message(self, message: str):
        self.messages.append(HumanMessage(content=message))
    
    def add_ai_message(self, message: str):
        self.messages.append(AIMessage(content=message))
    
    def clear(self):
        self.messages = []
import pickle
import json
import os
from pathlib import Path


class NovelMemoryManager:
    """小说写作记忆管理器"""
    
    def __init__(self, memory_type: str = "buffer", persist_directory: str = "memory_data"):
        """初始化记忆管理器
        
        Args:
            memory_type: 记忆类型 ("buffer" 或 "summary")
            persist_directory: 持久化目录
        """
        self.llm = create_deepseek_llm()
        self.persist_directory = persist_directory
        self.memory_file = None
        self.memory_type = memory_type
        
        # 创建持久化目录
        Path(persist_directory).mkdir(parents=True, exist_ok=True)
        
        # 使用简化的内存实现
        self.chat_memory = SimpleChatMemory()
        
        self.current_context = {
            "current_chapter": None,
            "current_scene": None,
            "active_characters": [],
            "writing_goal": None
        }
    
    def add_user_message(self, message: str):
        """添加用户消息"""
        self.chat_memory.add_user_message(message)
    
    def add_ai_message(self, message: str):
        """添加AI消息"""
        self.chat_memory.add_ai_message(message)
    
    def get_chat_history(self) -> List[BaseMessage]:
        """获取聊天历史"""
        return self.chat_memory.messages
    
    def get_chat_history_string(self) -> str:
        """获取聊天历史的字符串表示"""
        messages = self.get_chat_history()
        history_str = ""
        for msg in messages:
            if isinstance(msg, HumanMessage):
                history_str += f"用户: {msg.content}\n"
            elif isinstance(msg, AIMessage):
                history_str += f"助手: {msg.content}\n"
        return history_str
    
    def update_context(self, **kwargs):
        """更新当前写作上下文"""
        self.current_context.update(kwargs)
        print(f" 上下文已更新: {kwargs}")
    
    def get_context(self) -> Dict[str, Any]:
        """获取当前写作上下文"""
        return self.current_context
    
    def get_context_string(self) -> str:
        """获取上下文的字符串表示"""
        ctx = self.current_context
        context_str = "当前写作上下文:\n"
        if ctx["current_chapter"]:
            context_str += f"- 当前章节: {ctx['current_chapter']}\n"
        if ctx["current_scene"]:
            context_str += f"- 当前场景: {ctx['current_scene']}\n"
        if ctx["active_characters"]:
            context_str += f"- 活跃人物: {', '.join(ctx['active_characters'])}\n"
        if ctx["writing_goal"]:
            context_str += f"- 写作目标: {ctx['writing_goal']}\n"
        return context_str
    
    def clear_history(self):
        """清空对话历史"""
        self.chat_memory.clear()
        print(" 对话历史已清空")
    
    def clear_context(self):
        """清空写作上下文"""
        self.current_context = {
            "current_chapter": None,
            "current_scene": None,
            "active_characters": [],
            "writing_goal": None
        }
        print("✅ 写作上下文已清空")

    # 🆕 持久化功能
    
    def save_to_disk(self, project_id: str | int) -> bool:
        """保存记忆到磁盘
        
        Args:
            project_id: 项目 ID
            
        Returns:
            是否保存成功
        """
        try:
            memory_file = os.path.join(self.persist_directory, f"memory_{project_id}.pkl")
            context_file = os.path.join(self.persist_directory, f"context_{project_id}.json")
            
            # 保存对话记忆
            with open(memory_file, 'wb') as f:
                pickle.dump(self.chat_memory.messages, f)
            
            # 保存上下文
            with open(context_file, 'w', encoding='utf-8') as f:
                json.dump(self.current_context, f, ensure_ascii=False, indent=2)
            
            self.memory_file = memory_file
            print(f"✅ 记忆已保存到: {memory_file}")
            return True
            
        except Exception as e:
            print(f"❌ 保存记忆失败: {e}")
            return False
    
    def load_from_disk(self, project_id: str | int) -> bool:
        """从磁盘加载记忆
        
        Args:
            project_id: 项目 ID
            
        Returns:
            是否加载成功
        """
        try:
            memory_file = os.path.join(self.persist_directory, f"memory_{project_id}.pkl")
            context_file = os.path.join(self.persist_directory, f"context_{project_id}.json")
            
            # 检查文件是否存在
            if not os.path.exists(memory_file):
                print(f"⚠️ 记忆文件不存在: {memory_file}")
                return False
            
            # 加载对话记忆
            with open(memory_file, 'rb') as f:
                messages = pickle.load(f)
                self.chat_memory.messages = messages
            
            # 加载上下文
            if os.path.exists(context_file):
                with open(context_file, 'r', encoding='utf-8') as f:
                    self.current_context = json.load(f)
            
            self.memory_file = memory_file
            print(f"✅ 记忆已加载从: {memory_file}")
            print(f"✅ 加载了 {len(messages)} 条对话记录")
            return True
            
        except Exception as e:
            print(f"❌ 加载记忆失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def delete_from_disk(self, project_id: str | int) -> bool:
        """删除磁盘上的记忆
        
        Args:
            project_id: 项目 ID
            
        Returns:
            是否删除成功
        """
        try:
            memory_file = os.path.join(self.persist_directory, f"memory_{project_id}.pkl")
            context_file = os.path.join(self.persist_directory, f"context_{project_id}.json")
            
            deleted = False
            
            if os.path.exists(memory_file):
                os.remove(memory_file)
                deleted = True
            
            if os.path.exists(context_file):
                os.remove(context_file)
                deleted = True
            
            if deleted:
                print(f"✅ 记忆文件已删除: memory_{project_id}.*")
                return True
            else:
                print(f"⚠️ 没有找到记忆文件: memory_{project_id}.*")
                return False
                
        except Exception as e:
            print(f"❌ 删除记忆失败: {e}")
            return False
    
    def list_saved_memories(self) -> List[str]:
        """列出所有已保存的记忆文件
        
        Returns:
            项目 ID 列表
        """
        try:
            memory_files = []
            for filename in os.listdir(self.persist_directory):
                if filename.startswith("memory_") and filename.endswith(".pkl"):
                    # 提取项目 ID
                    project_id = filename[7:-4]  # 移除 "memory_" 和 ".pkl"
                    memory_files.append(project_id)
            return memory_files
        except Exception as e:
            print(f"❌ 列出记忆文件失败: {e}")
            return []

