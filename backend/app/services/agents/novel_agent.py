"""
小说写作Agent - 整合知识库和记忆管理的智能写作助手
"""
from typing import Dict, Any, List, Optional
from langchain_community.chat_models import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage
from .config import Config
from .knowledge_base import NovelKnowledgeBase
from .memory_manager import NovelMemoryManager


from .llm_singleton import create_deepseek_llm


class NovelWritingAgent:
    """小说写作Agent - 核心工作流程"""
    
    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None, memory_manager: Optional[NovelMemoryManager] = None):
        """初始化Agent"""
        Config.validate()

        self.llm = create_deepseek_llm()
        
        self.knowledge_base = knowledge_base or NovelKnowledgeBase()
        self.memory_manager = memory_manager or NovelMemoryManager()
        
        self.system_prompt = """你是一个专业的小说写作助手。你的任务是帮助作者创作高质量的小说内容。

你拥有以下能力:
1. 访问小说的世界观设定、人物档案和已写章节
2. 理解当前的写作上下文和对话历史
3. 根据检索到的信息生成连贯、符合设定的内容

请遵循以下原则:
- 严格遵守已有的世界观设定和人物性格
- 保持故事的连贯性和一致性
- 根据上下文理解用户的真实意图
- 生成富有创意但符合逻辑的内容
"""
    
    def process_request(self, user_input: str) -> str:
        """处理用户请求的核心工作流程"""
        print(f"\n{'='*60}")
        print(f"用户请求: {user_input}")
        print(f"{'='*60}\n")
        
        self.memory_manager.add_user_message(user_input)
        
        print(" 正在检索相关知识...")
        retrieved_docs = self.knowledge_base.search(user_input, k=5)
        retrieved_context = self._format_retrieved_docs(retrieved_docs)
        print(f" 检索到 {len(retrieved_docs)} 条相关信息\n")
        
        current_context = self.memory_manager.get_context_string()
        chat_history = self.memory_manager.get_chat_history_string()
        
        enhanced_prompt = self._build_enhanced_prompt(
            user_input=user_input,
            retrieved_context=retrieved_context,
            current_context=current_context,
            chat_history=chat_history
        )
        
        print("  正在生成内容...\n")
        response = self._generate_response(enhanced_prompt)
        
        self.memory_manager.add_ai_message(response)
        
        print(f"\n{'='*60}")
        print(" 生成完成")
        print(f"{'='*60}\n")
        
        return response
    
    def _format_retrieved_docs(self, docs: List) -> str:
        """格式化检索到的文档"""
        if not docs:
            return "未找到相关信息"
        
        formatted = "检索到的相关信息:\n\n"
        for i, doc in enumerate(docs, 1):
            metadata = doc.metadata
            doc_type = metadata.get('type', '未知')
            
            if doc_type == 'character':
                formatted += f"[人物档案] {metadata.get('name', '未知')}\n"
            elif doc_type == 'world_setting':
                formatted += f"[世界观] {metadata.get('title', '未知')}\n"
            elif doc_type == 'chapter':
                formatted += f"[章节] 第{metadata.get('chapter_num', '?')}章 - {metadata.get('title', '未知')}\n"
            
            formatted += f"{doc.page_content}\n\n"
        
        return formatted
    
    def _build_enhanced_prompt(self, user_input: str, retrieved_context: str, 
                               current_context: str, chat_history: str) -> List[BaseMessage]:
        """构建增强的Prompt"""
        messages: List[BaseMessage] = [SystemMessage(content=self.system_prompt)]
        
        if retrieved_context and retrieved_context != "未找到相关信息":
            messages.append(SystemMessage(content=f"\n{retrieved_context}"))
        
        if current_context:
            messages.append(SystemMessage(content=f"\n{current_context}"))
        
        history_messages = self.memory_manager.get_chat_history()
        if len(history_messages) > 10:
            history_messages = history_messages[-10:]
        messages.extend(history_messages[:-1])
        
        messages.append(HumanMessage(content=user_input))
        
        return messages
    
    def _generate_response(self, messages: List[BaseMessage]) -> str:
        """调用LLM生成响应"""
        response = self.llm.invoke(messages)  # type: ignore
        return response.content
    
    def set_context(self, **kwargs):
        """设置写作上下文"""
        self.memory_manager.update_context(**kwargs)
    
    def add_knowledge(self, knowledge_type: str, **kwargs):
        """添加知识到知识库"""
        if knowledge_type == "world_setting":
            title = kwargs.get('title')
            content = kwargs.get('content')
            if title and content:
                self.knowledge_base.add_world_setting(
                    title=title,
                    content=content,
                    metadata=kwargs.get('metadata')
                )
        elif knowledge_type == "character":
            name = kwargs.get('name')
            profile = kwargs.get('profile')
            if name and profile:
                self.knowledge_base.add_character(
                    name=name,
                    profile=profile,
                    metadata=kwargs.get('metadata')
                )
        elif knowledge_type == "chapter":
            chapter_num = kwargs.get('chapter_num')
            title = kwargs.get('title')
            content = kwargs.get('content')
            if chapter_num is not None and title and content:
                self.knowledge_base.add_chapter(
                    chapter_num=chapter_num,
                    title=title,
                    content=content,
                    metadata=kwargs.get('metadata')
                )
