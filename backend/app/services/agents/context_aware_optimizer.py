"""
上下文感知优化器 - 基于记忆管理器优化提示词，准确捕捉作者创作意图
"""
from typing import Dict, Any, List, Optional
from langchain_core.messages import SystemMessage, HumanMessage
from .config import Config
from .llm_singleton import create_deepseek_llm
from .memory_manager import NovelMemoryManager
from .knowledge_base import NovelKnowledgeBase


class ContextAwareOptimizer:
    """上下文感知优化器 - 基于上下文优化提示词"""
    
    def __init__(self, memory_manager: Optional[NovelMemoryManager] = None,
                 knowledge_base: Optional[NovelKnowledgeBase] = None):
        """初始化上下文感知优化器"""
        self.memory_manager = memory_manager or NovelMemoryManager()
        self.knowledge_base = knowledge_base or NovelKnowledgeBase()
        self.llm = create_deepseek_llm()
        
        # 存储优化历史
        self.optimization_history = []
    
    def extract_writing_intent(self, user_input: str) -> Dict[str, Any]:
        """从用户输入中提取创作意图"""
        intent_prompt = f"""分析以下用户输入，提取创作意图和关键信息。

用户输入：
{user_input}

请提取以下信息（以JSON格式返回）：
1. 主要创作意图（intent）
2. 情感基调（tone）
3. 场景类型（scene_type）
4. 关键人物（key_characters）
5. 故事节奏（pacing）
6. 特殊要求（special_requirements）

返回格式：
{{
    "intent": "...",
    "tone": "...",
    "scene_type": "...",
    "key_characters": [...],
    "pacing": "...",
    "special_requirements": "..."
}}"""

        messages = [HumanMessage(content=intent_prompt)]
        response = self.llm.invoke(messages)
        
        # 解析响应
        try:
            import json
            # 提取JSON部分
            response_text = response.content
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}') + 1
            if start_idx != -1 and end_idx > start_idx:
                json_str = response_text[start_idx:end_idx]
                intent_data = json.loads(json_str)
                return intent_data
        except:
            pass
        
        return {
            "intent": "创作新章节",
            "tone": "中性",
            "scene_type": "未指定",
            "key_characters": [],
            "pacing": "正常",
            "special_requirements": ""
        }
    
    def get_context_summary(self) -> str:
        """获取上下文摘要"""
        context = self.memory_manager.get_context()
        chat_history = self.memory_manager.get_chat_history_string()
        
        summary = "【当前创作上下文】\n"
        
        if context.get("current_chapter"):
            summary += f"当前章节: {context['current_chapter']}\n"
        
        if context.get("current_scene"):
            summary += f"当前场景: {context['current_scene']}\n"
        
        if context.get("active_characters"):
            summary += f"活跃人物: {', '.join(context['active_characters'])}\n"
        
        if context.get("writing_goal"):
            summary += f"写作目标: {context['writing_goal']}\n"
        
        # 添加最近的对话历史摘要
        if chat_history:
            summary += "\n【最近对话摘要】\n"
            lines = chat_history.split('\n')
            # 只保留最后5条对话
            recent_lines = lines[-5:] if len(lines) > 5 else lines
            summary += '\n'.join(recent_lines)
        
        return summary
    
    def retrieve_relevant_knowledge(self, query: str, top_k: int = 3) -> List[str]:
        """从知识库检索相关信息"""
        try:
            results = self.knowledge_base.search(query, k=top_k)
            return [result.page_content for result in results]
        except:
            return []
    
    def optimize_prompt(self, base_prompt: str, user_input: Optional[str] = None) -> str:
        """基于上下文优化提示词"""
        
        # 1. 提取创作意图
        intent = self.extract_writing_intent(user_input or base_prompt)
        
        # 2. 获取上下文摘要
        context_summary = self.get_context_summary()
        
        # 3. 检索相关知识
        relevant_knowledge = self.retrieve_relevant_knowledge(user_input or base_prompt)
        
        # 4. 构建优化后的提示词
        optimized_prompt = f"""{base_prompt}

【创作意图分析】
- 主要意图: {intent.get('intent', '未指定')}
- 情感基调: {intent.get('tone', '中性')}
- 场景类型: {intent.get('scene_type', '未指定')}
- 关键人物: {', '.join(intent.get('key_characters', [])) or '未指定'}
- 故事节奏: {intent.get('pacing', '正常')}
- 特殊要求: {intent.get('special_requirements', '无')}

【上下文信息】
{context_summary}

【相关背景知识】
"""
        
        if relevant_knowledge:
            for i, knowledge in enumerate(relevant_knowledge, 1):
                optimized_prompt += f"{i}. {knowledge}\n"
        else:
            optimized_prompt += "暂无相关背景知识\n"
        
        optimized_prompt += "\n请根据以上信息进行创作，确保与上下文保持一致。"
        
        # 记录优化历史
        self.optimization_history.append({
            "original_prompt": base_prompt,
            "optimized_prompt": optimized_prompt,
            "intent": intent,
            "context": context_summary
        })
        
        return optimized_prompt
    
    def generate_chapter_prompt(self, chapter_info: Dict[str, Any]) -> str:
        """生成优化的章节创作提示词"""
        
        base_prompt = f"""请创作第 {chapter_info.get('chapter_number', '?')} 章的内容。

【章节信息】
- 章节标题: {chapter_info.get('title', '未指定')}
- 章节大纲: {chapter_info.get('outline', '未指定')}
- 字数要求: {chapter_info.get('word_count', '2000-3000')} 字
- 主要人物: {', '.join(chapter_info.get('main_characters', [])) or '未指定'}
- 场景设置: {chapter_info.get('setting', '未指定')}
- 情节要点: {chapter_info.get('plot_points', '未指定')}

请创作高质量的文学作品，注重细节描写、对话、心理活动和场景营造。"""
        
        # 使用优化器优化提示词
        optimized_prompt = self.optimize_prompt(base_prompt, chapter_info.get('title'))
        
        return optimized_prompt
    
    def update_memory_context(self, **kwargs):
        """更新记忆管理器的上下文"""
        self.memory_manager.update_context(**kwargs)
    
    def get_optimization_history(self) -> List[Dict[str, Any]]:
        """获取优化历史"""
        return self.optimization_history
    
    def clear_optimization_history(self):
        """清空优化历史"""
        self.optimization_history = []
    
    def generate_context_aware_system_prompt(self, base_system_prompt: str) -> str:
        """生成上下文感知的系统提示词"""
        
        context_summary = self.get_context_summary()
        
        context_aware_prompt = f"""{base_system_prompt}

【当前创作上下文】
{context_summary}

请根据上述上下文信息调整你的创作风格和内容，确保与已有内容保持一致性和连贯性。"""
        
        return context_aware_prompt
    
    def analyze_writing_consistency(self, new_content: str) -> Dict[str, Any]:
        """分析新内容与上下文的一致性"""
        
        context_summary = self.get_context_summary()
        
        consistency_prompt = f"""分析以下新创作的内容与上下文的一致性。

【上下文信息】
{context_summary}

【新创作内容】
{new_content}

请分析：
1. 人物性格是否一致
2. 故事逻辑是否连贯
3. 语言风格是否统一
4. 场景设置是否合理
5. 时间线是否正确

返回格式：
{{
    "consistency_score": 0-10,
    "character_consistency": "...",
    "plot_consistency": "...",
    "style_consistency": "...",
    "setting_consistency": "...",
    "timeline_consistency": "...",
    "suggestions": ["...", "..."]
}}"""

        messages = [HumanMessage(content=consistency_prompt)]
        response = self.llm.invoke(messages)
        
        try:
            import json
            response_text = response.content
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}') + 1
            if start_idx != -1 and end_idx > start_idx:
                json_str = response_text[start_idx:end_idx]
                analysis = json.loads(json_str)
                return analysis
        except:
            pass
        
        return {
            "consistency_score": 5,
            "character_consistency": "未能分析",
            "plot_consistency": "未能分析",
            "style_consistency": "未能分析",
            "setting_consistency": "未能分析",
            "timeline_consistency": "未能分析",
            "suggestions": []
        }
