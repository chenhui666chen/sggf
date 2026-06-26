"""
多Agent框架 - 各个专业化Agent的定义
"""
import json
import logging
from typing import Dict, Any, List, Optional, Union
from abc import ABC, abstractmethod
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
from .config import Config
from .knowledge_base import NovelKnowledgeBase
from .memory_manager import NovelMemoryManager
from .quality_assessment import (
    QualityAssessmentFramework, QualityAssessmentReport, QualityMetric,
    create_story_metrics, create_character_metrics, create_language_metrics,
    create_structure_metrics, create_innovation_metrics
)
from .context_aware_optimizer import ContextAwareOptimizer

logger = logging.getLogger(__name__)


from core.langchain_bridge import create_task_llm, create_model_llm

def _is_dashscope_llm(llm: Any) -> bool:
    model = getattr(llm, "model_name", None) or getattr(llm, "model", None) or ""
    if isinstance(model, str) and model.startswith("qwen"):
        return True
    base = getattr(llm, "openai_api_base", None) or getattr(llm, "base_url", None)
    if not base:
        client = getattr(llm, "client", None)
        base = getattr(client, "base_url", None) if client else None
    return bool(base and "dashscope.aliyuncs.com" in str(base))


def _collect_streaming_content(stream: Any) -> str:
    parts: List[str] = []
    for chunk in stream:
        if chunk is None:
            continue
        if isinstance(chunk, str):
            parts.append(chunk)
            continue
        content = getattr(chunk, "content", None)
        if content:
            parts.append(content)
            continue
        message = getattr(chunk, "message", None)
        if message is not None:
            message_content = getattr(message, "content", None)
            if message_content:
                parts.append(message_content)
                continue
        text_value = getattr(chunk, "text", None)
        if text_value:
            parts.append(text_value)
    return "".join(parts)


def _invoke_llm_with_optional_streaming(llm: Any, messages: List[BaseMessage]) -> str:
    if _is_dashscope_llm(llm):
        try:
            return _collect_streaming_content(llm.stream(messages))
        except Exception as e:
            err = str(e)
            if "use sse protocol" in err or "non-stream call timed out" in err:
                raise
    try:
        response = llm.invoke(messages)
        return response.content
    except Exception as e:
        err = str(e)
        if "use sse protocol" in err or "non-stream call timed out" in err:
            return _collect_streaming_content(llm.stream(messages))
        raise


class BaseAgent(ABC):
    """所有Agent的基类"""
    
    def __init__(self, name: str, role: str, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None, task_type: str = "default",
                 llm: Optional[Any] = None, tts_strategy: Optional[str] = None):
        """初始化Agent"""
        Config.validate()

        self.name = name
        self.role = role
        self.llm = llm if llm is not None else create_task_llm(task_type=task_type)
        
        self.knowledge_base = knowledge_base or NovelKnowledgeBase()
        self.memory_manager = memory_manager or NovelMemoryManager()
        self.conversation_history = []
        
        self.current_project_id: Optional[int] = None

        self._tts_dispatch_client = None
        self._tts_strategy = tts_strategy
    
    @property
    def tts_dispatch_client(self):
        if self._tts_dispatch_client is None:
            try:
                from app.services.audiobook.agent_dispatch_client import client as tts_client
                self._tts_dispatch_client = tts_client
            except ImportError:
                logger.warning("智能调度客户端未加载，TTS 功能不可用")
        return self._tts_dispatch_client
    
    def synthesize_with_dispatch(
        self,
        text: str,
        strategy: Optional[str] = None,
        voice_id: Optional[str] = None,
        **kwargs,
    ) -> Any:
        """使用智能调度系统合成语音

        Args:
            text: 要合成的文本
            strategy: 调度策略 (quality/fast/balanced/cost_saving)
            voice_id: 指定音色 ID
            **kwargs: 其他 TTS 参数

        Returns:
            TTSDispatchResult: 合成结果
        """
        if self.tts_dispatch_client is None:
            logger.error("智能调度客户端不可用")
            return None

        effective_strategy = strategy or self._tts_strategy
        agent_type = getattr(self, "agent_type", None) or self.name.lower().replace("agent", "").replace(" ", "_")

        return self.tts_dispatch_client.synthesize(
            text=text,
            strategy=effective_strategy,
            voice_id=voice_id,
            agent_type=agent_type,
            **kwargs,
        )
    
    def synthesize_batch_with_dispatch(
        self,
        texts: List[str],
        strategy: Optional[str] = None,
        voice_ids: Optional[List[str]] = None,
        **kwargs,
    ) -> List[Any]:
        """使用智能调度系统批量合成语音

        Args:
            texts: 要合成的文本列表
            strategy: 调度策略
            voice_ids: 音色 ID 列表
            **kwargs: 其他 TTS 参数

        Returns:
            List[TTSDispatchResult]: 合成结果列表
        """
        if self.tts_dispatch_client is None:
            logger.error("智能调度客户端不可用")
            return []

        effective_strategy = strategy or self._tts_strategy
        agent_type = getattr(self, "agent_type", None) or self.name.lower().replace("agent", "").replace(" ", "_")

        return self.tts_dispatch_client.synthesize_batch(
            texts=texts,
            strategy=effective_strategy,
            voice_ids=voice_ids,
            agent_type=agent_type,
            **kwargs,
        )
    
    def set_project_context(self, project_id: int):
        """🎯 设置当前项目上下文
        
        Args:
            project_id: 项目 ID
        """
        self.current_project_id = project_id
    
    def _search_knowledge(self, query: str, filter_type: Optional[str] = None, k: int = 5) -> List:
        """🎯 封装知识库搜索，自动带上项目ID
        
        Args:
            query: 搜索查询
            filter_type: 类型过滤
            k: 返回结果数量
            
        Returns:
            搜索结果列表
        """
        return self.knowledge_base.search(
            query=query,
            k=k,
            filter_type=filter_type,
            project_id=self.current_project_id  # 🎯 自动注入项目ID
        )
    
    @abstractmethod
    def get_system_prompt(self) -> str:
        """获取Agent的系统提示词"""
        pass
    
    def process(self, user_input: str, context: Optional[Dict[str, Any]] = None,
                temperature: Optional[float] = None) -> str:
        """使用Agent默认系统提示词处理输入。"""
        return self._process_with_system_prompt(
            user_input,
            system_prompt=self.get_system_prompt(),
            context=context,
            temperature=temperature,
        )

    def _process_with_system_prompt(
        self,
        user_input: str,
        *,
        system_prompt: str,
        context: Optional[Dict[str, Any]] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """处理输入并生成响应

        Args:
            user_input: 用户输入
            context: 上下文信息
            temperature: 可选的温度参数，用于控制创造性（0.0-1.0）
                        None: 使用默认值（0.7）
                        高值（0.8-1.0）: 更有创造性，适合扩展创作
                        低值（0.1-0.5）: 更确定性，适合优化润色
        """
        self.memory_manager.add_user_message(user_input)

        # 🔥 合并 system_prompt 和 context 为单个 SystemMessage,避免阿里云 API 报错
        system_prompt = system_prompt or self.get_system_prompt()
        if context:
            context_str = self._format_context(context)
            system_prompt = f"{system_prompt}\n\n{context_str}"
        
        messages: List[BaseMessage] = [SystemMessage(content=system_prompt)]

        # 添加对话历史（🛡️ 验证消息格式）
        history = self.memory_manager.get_chat_history()
        if len(history) > 10:
            history = history[-10:]
        
        # 🔧 过滤无效消息，避免 API 错误
        valid_history = []
        for msg in history[:-1]:  # 排除最后一条（已经被添加到 user_input）
            # 验证消息类型和内容
            if isinstance(msg, (HumanMessage, AIMessage, SystemMessage)):
                # 检查 content 属性是否存在且为字符串
                if hasattr(msg, 'content') and msg.content and isinstance(msg.content, str) and msg.content.strip():
                    valid_history.append(msg)
                else:
                    logger.debug(f"⚠️ 过滤空消息: {type(msg).__name__}")
            else:
                logger.debug(f"⚠️ 过滤无效消息类型: {type(msg)}")
        
        messages.extend(valid_history)

        messages.append(HumanMessage(content=user_input))
        
        # 🔥 关键修复：支持动态设置 temperature
        if temperature is not None:
            # 创建一个临时的 LLM 实例，使用指定的 temperature
            model_name = (
                getattr(self.llm, 'model_name', None)
                or getattr(self.llm, 'model', None)
                or Config.MODEL_NAME
                or "qwen3-max"
            )
            temp_llm = create_model_llm(model=model_name, temperature=temperature)
            logger.debug(f"🎲 使用自定义 temperature={temperature}")
            try:
                response_content = _invoke_llm_with_optional_streaming(temp_llm, messages)
            except Exception as e:
                # 捕获并详细记录错误
                import traceback
                error_details = traceback.format_exc()
                logger.debug(f"❌ LLM调用失败: {str(e)}")
                logger.debug(f"📋 完整错误信息:\n{error_details}")
                # 如果是JSON解析错误,记录更多信息
                if "JSON" in str(e) or "Expecting value" in str(e):
                    logger.debug("⚠️ 检测到JSON解析错误,可能是API返回格式异常")
                raise
        else:
            response_content = _invoke_llm_with_optional_streaming(self.llm, messages)

        self.memory_manager.add_ai_message(response_content)
        self.conversation_history.append({"input": user_input, "output": response_content})

        return response_content
    
    def _format_context(self, context: Dict[str, Any]) -> str:
        """格式化上下文信息（智能超限保护）"""
        from .intelligent_truncator import truncate_with_ai_assist
        
        # 💡 智能检测当前模型的tokens限制
        model_name = getattr(self.llm, 'model_name', None) or getattr(self.llm, 'model', 'qwen3-max')
        
        # 模型限制映射 (tokens)
        MODEL_LIMITS = {
            'qwen-max': 30720,          # 30K tokens
            'qwen3-max': 256000,        # 256K tokens（上下文 256K）
            'qwen3.7-plus': 1000000,    # 1M tokens（上下文 100万，输出 65K）
            'qwen-plus': 1000000,       # 1M tokens
            'qwen-long': 10000000,      # 10M tokens
            'qwen-turbo': 8000,         # 8K tokens
            'deepseek-v4-pro': 1000000, # V4 Pro: 1M tokens
            'deepseek-v4-flash': 1000000, # V4 Flash: 1M tokens
        }
        
        # 默认限制(如果模型未知)
        token_limit = MODEL_LIMITS.get(model_name, 30720)
        
        # 🛡️ 安全系数: 使用85%空间,留余15%给system_prompt和prompt模板
        safe_token_limit = int(token_limit * 0.85)
        
        # 📊 按中文估算: 1 token ≈ 0.67 中文字符
        safe_char_limit = int(safe_token_limit * 0.67)
        
        context_str = "当前上下文信息:\n"
        
        for key, value in context.items():
            try:
                # 转换为字符串
                s = value if isinstance(value, str) else str(value)
            except Exception:
                s = ""
            
            if s is None or not s:
                continue
            
            # 根据键名判断内容类型
            if 'outline' in key.lower() or 'plot' in key.lower():
                content_type = "outline"
            elif 'character' in key.lower():
                content_type = "character"
            elif 'world' in key.lower() or 'setting' in key.lower():
                content_type = "worldview"
            else:
                content_type = "outline"  # 默认
            
            # 🔥 智能截断：只在真正超限时才启用AI辅助
            if len(s) > safe_char_limit:
                # 🎯 目标长度 = 安全限制 * 95% (略留余地)
                target_length = int(safe_char_limit * 0.95)
                s = truncate_with_ai_assist(
                    content=s,
                    target_length=target_length,
                    content_type=content_type
                )
            
            context_str += f"- {key}: {s}\n"
        
        return context_str
    
    def clear_history(self):
        """清空对话历史"""
        self.conversation_history = []
        self.memory_manager.clear_history()


# ============================================================================
# 新的 Agent 结构（6个Agent）
# ============================================================================

class WorldArchitectAgent(BaseAgent):
    """世界观架构师Agent - 世界观体系构建与逻辑一致性维护"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None):
        super().__init__("世界观架构师", "world_architect", knowledge_base, memory_manager, task_type="worldview")

    def get_system_prompt(self) -> str:
        from app.services.prompts.manager import prompt_manager
        return prompt_manager.get_agent_prompt("world_architect")


class CharacterDesignerAgent(BaseAgent):
    """人物设计师Agent - 角色体系构建与人物关系网络设计"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None):
        super().__init__("人物设计师", "character_designer", knowledge_base, memory_manager, task_type="character")

    def get_system_prompt(self) -> str:
        from app.services.prompts.manager import prompt_manager
        return prompt_manager.get_agent_prompt("character_designer")


class OutlinePlanParserAgent(BaseAgent):
    """大纲规划解析Agent - 解析用户自定义大纲规划文本，生成结构化JSON"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None):
        super().__init__("大纲规划解析器", "outline_plan_parser", knowledge_base, memory_manager, task_type="outline")

    def get_system_prompt(self) -> str:
        from app.services.prompts.manager import prompt_manager
        return prompt_manager.get_agent_prompt("outline_plan_parser")


class CreativeDirectorAgent(BaseAgent):
    """创意总监Agent - 整体创作方向把控与工作流程协调"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None):
        super().__init__("创意总监", "creative_director", knowledge_base, memory_manager, task_type="concept")

    def get_system_prompt(self) -> str:
        from app.services.prompts.manager import prompt_manager
        return prompt_manager.get_agent_prompt("creative_director")


class PlotArchitectAgent(BaseAgent):
    """情节架构师Agent - 故事结构设计与情节质量把控"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None,
                 llm: Optional[Any] = None):  # 🎆 支持传入自定义LLM
        super().__init__("情节架构师", "plot_architect", knowledge_base, memory_manager, 
                        task_type="outline", llm=llm)  # ✅ 传递llm参数

    def get_system_prompt(self) -> str:
        from app.services.prompts.manager import prompt_manager
        return prompt_manager.get_agent_prompt("plot_architect")


class ContentCreatorAgent(BaseAgent):
    """内容创作师Agent - 具体内容创作与语言风格优化"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None):
        super().__init__("内容创作师", "content_creator", knowledge_base, memory_manager, task_type="chapter")
        # 初始化上下文感知优化器 - 确保传递实际的实例而非None
        self.context_optimizer = ContextAwareOptimizer(
            self.memory_manager,  # 使用已初始化的实例
            self.knowledge_base   # 使用已初始化的实例
        )

    def get_system_prompt(self) -> str:
        from app.services.prompts.manager import prompt_manager
        return prompt_manager.get_agent_prompt("content_creator")

    def create_chapter_from_prompts(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        context: Optional[Dict[str, Any]] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """使用显式双 Prompt 生成章节内容。"""
        return self._process_with_system_prompt(
            user_prompt,
            system_prompt=system_prompt,
            context=context,
            temperature=temperature,
        )

    def create_chapter(self, chapter_info: Dict[str, Any]) -> Dict[str, Any]:
        """创建新章节 - 使用上下文感知优化"""

        # 1. 更新记忆管理器的上下文
        self.context_optimizer.update_memory_context(
            current_chapter=chapter_info.get('chapter_number'),
            current_scene=chapter_info.get('setting'),
            active_characters=chapter_info.get('main_characters', []),
            writing_goal=chapter_info.get('outline')
        )

        # 2. 生成优化的提示词
        optimized_prompt = self.context_optimizer.generate_chapter_prompt(chapter_info)

        # 3. 获取上下文感知的系统提示词
        context_aware_system_prompt = self.context_optimizer.generate_context_aware_system_prompt(
            self.get_system_prompt()
        )

        # 4. 构建消息
        messages: List[BaseMessage] = [SystemMessage(content=context_aware_system_prompt)]
        messages.append(HumanMessage(content=optimized_prompt))

        # 5. 调用LLM生成内容
        response = self.llm.invoke(messages)
        chapter_content = response.content

        # 6. 记录到记忆管理器
        self.memory_manager.add_user_message(optimized_prompt)
        self.memory_manager.add_ai_message(chapter_content)

        # 7. 分析一致性
        consistency_analysis = self.context_optimizer.analyze_writing_consistency(chapter_content)

        return {
            "content": chapter_content,
            "consistency_analysis": consistency_analysis,
            "optimization_info": {
                "chapter_number": chapter_info.get('chapter_number'),
                "title": chapter_info.get('title'),
                "consistency_score": consistency_analysis.get('consistency_score', 0)
            }
        }

    def create_scene(self, scene_info: Dict[str, Any]) -> str:
        """创建新场景 - 使用上下文感知优化"""

        self.context_optimizer.update_memory_context(
            current_scene=scene_info.get('scene_name'),
            active_characters=scene_info.get('characters', []),
            writing_goal=scene_info.get('description')
        )

        from app.services.prompts.manager import prompt_manager
        base_prompt = prompt_manager.get_user_prompt(
            "content_creator_scene",
            variables={
                "scene_name": scene_info.get('scene_name', '未指定'),
                "scene_description": scene_info.get('description', '未指定'),
                "characters": ', '.join(scene_info.get('characters', [])) or '未指定',
                "scene_type": scene_info.get('scene_type', '未指定'),
                "tone": scene_info.get('tone', '中性'),
                "word_count": scene_info.get('word_count', '500-1000'),
            },
        )

        optimized_prompt = self.context_optimizer.optimize_prompt(base_prompt, scene_info.get('scene_name', ''))

        # 3. 获取上下文感知的系统提示词
        context_aware_system_prompt = self.context_optimizer.generate_context_aware_system_prompt(
            self.get_system_prompt()
        )

        # 4. 构建消息
        messages: List[BaseMessage] = [SystemMessage(content=context_aware_system_prompt)]
        messages.append(HumanMessage(content=optimized_prompt))

        # 5. 调用LLM生成内容
        response = self.llm.invoke(messages)
        scene_content = response.content

        # 6. 记录到记忆管理器
        self.memory_manager.add_user_message(optimized_prompt)
        self.memory_manager.add_ai_message(scene_content)

        return scene_content


class QualityReviewerAgent(BaseAgent):
    """质量评审官Agent - 作品质量审核与改进建议"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None):
        super().__init__("质量评审官", "quality_reviewer", knowledge_base, memory_manager, task_type="review")
        self.assessment_framework = QualityAssessmentFramework()

    def get_system_prompt(self) -> str:
        from app.services.prompts.manager import prompt_manager
        return prompt_manager.get_agent_prompt("quality_reviewer")

    def create_assessment_report(self, content_id: str, content_type: str = "chapter") -> QualityAssessmentReport:
        """创建评估报告"""
        report = self.assessment_framework.create_assessment_report(content_id, content_type)

        # 添加所有指标
        for metric in create_story_metrics():
            self.assessment_framework.add_metric_to_report(report, metric)

        for metric in create_character_metrics():
            self.assessment_framework.add_metric_to_report(report, metric)

        for metric in create_language_metrics():
            self.assessment_framework.add_metric_to_report(report, metric)

        for metric in create_structure_metrics():
            self.assessment_framework.add_metric_to_report(report, metric)

        for metric in create_innovation_metrics():
            self.assessment_framework.add_metric_to_report(report, metric)

        return report

    def assess_content(self, content: str, content_id: str = "chapter_1") -> QualityAssessmentReport:
        """评估内容质量"""
        report = self.create_assessment_report(content_id)

        from app.services.prompts.manager import prompt_manager
        assessment_prompt = prompt_manager.get_user_prompt(
            "quality_reviewer_assessment", variables={"content": content}
        )

        assessment_result = self.process(assessment_prompt)

        # 解析评估结果并填充报告
        self._parse_assessment_result(report, assessment_result)

        return report

    def _parse_assessment_result(self, report: QualityAssessmentReport, result: str):
        """解析评估结果"""
        # 这里可以使用更复杂的解析逻辑
        # 为了演示，我们设置一些默认值

        # 设置评审官名称和日期
        report.reviewer_name = self.name
        from datetime import datetime
        report.assessment_date = datetime.now().isoformat()

        # 计算评分
        self.assessment_framework.calculate_report_scores(report)

    def generate_assessment_summary(self, report: QualityAssessmentReport) -> str:
        """生成评估总结"""
        summary = f"""
{'='*70}
【质量评估报告】
{'='*70}

内容ID: {report.content_id}
评审官: {report.reviewer_name}
评估日期: {report.assessment_date}

【各维度评分】
"""

        for dimension, dim_score in report.dimension_scores.items():
            summary += f"\n{dimension.value.upper()}（权重{dim_score.weight*100:.0f}%）: {dim_score.dimension_score:.1f}/10\n"
            for metric in dim_score.metrics:
                summary += f"  - {metric.name}: {metric.score:.1f}/10\n"
                if metric.feedback:
                    summary += f"    反馈: {metric.feedback}\n"

        summary += f"\n【综合评分】\n"
        summary += f"综合评分: {report.overall_score:.1f}/10\n"
        summary += f"评级: {'优秀 ⭐' if report.is_excellent else '良好'}\n"

        if report.strengths:
            summary += f"\n【主要优点】\n"
            for strength in report.strengths:
                summary += f"✓ {strength}\n"

        if report.weaknesses:
            summary += f"\n【主要缺点】\n"
            for weakness in report.weaknesses:
                summary += f"✗ {weakness}\n"

        if report.suggestions:
            summary += f"\n【改进建议】\n"
            for i, suggestion in enumerate(report.suggestions, 1):
                summary += f"{i}. {suggestion}\n"

        summary += f"\n{'='*70}\n"

        return summary


class ContentReviserAgent(BaseAgent):
    """内容修订师Agent - 根据评审反馈修订章节内容"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None):
        super().__init__("内容修订师", "content_reviser", knowledge_base, memory_manager, task_type="chapter")

    def get_system_prompt(self) -> str:
        from app.services.prompts.manager import prompt_manager
        return prompt_manager.get_agent_prompt("content_reviser")

    def revise_content(
        self,
        original_content: str,
        review_feedback: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """根据评审意见修订内容。"""
        from app.services.prompts.workflow_runtime import (
            build_iteration_revision_user_prompt,
            get_iteration_revision_system_prompt,
        )

        runtime_context = context or {}
        revision_prompt = build_iteration_revision_user_prompt(
            chapter_number=int(runtime_context.get("chapter_number") or 1),
            chapter_content=original_content,
            review_text=review_feedback,
            iteration_plan=runtime_context.get("iteration_plan", ""),
            recent_chapter_assets_summary=runtime_context.get("recent_chapter_assets_summary", ""),
            include_history_hint=bool(runtime_context.get("include_history_hint", False)),
        )
        return self._process_with_system_prompt(
            revision_prompt,
            system_prompt=get_iteration_revision_system_prompt(),
            context=context,
        )


class FinalReviewerAgent(BaseAgent):
    """最终审核官Agent - 对修订后的章节进行最终审核"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None):
        super().__init__("最终审核官", "final_reviewer", knowledge_base, memory_manager, task_type="review")

    def get_system_prompt(self) -> str:
        from app.services.prompts.manager import prompt_manager
        return prompt_manager.get_agent_prompt("final_reviewer")

    def review_final_content(
        self,
        content: str,
        chapter_number: int = 1,
        chapter_plan: str = "",
        recent_chapter_assets_summary: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """对修订后的内容执行最终审核。"""
        from app.services.prompts.workflow_runtime import (
            build_iteration_loop_review_user_prompt,
            get_iteration_loop_review_system_prompt,
        )

        runtime_context = context or {}
        review_prompt = build_iteration_loop_review_user_prompt(
            chapter_number=int(runtime_context.get("chapter_number") or chapter_number or 1),
            chapter_content=content,
            chapter_plan=runtime_context.get("chapter_plan", chapter_plan),
            recent_chapter_assets_summary=runtime_context.get(
                "recent_chapter_assets_summary",
                recent_chapter_assets_summary,
            ),
        )
        return self._process_with_system_prompt(
            review_prompt,
            system_prompt=get_iteration_loop_review_system_prompt(),
            context=context,
        )


# ============================================================================
# 新增的辅助 Agent 实现
# ============================================================================

class EventValidatorAgent(BaseAgent):
    """事件验证官Agent - 验证事件序列的合理性和逻辑一致性"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None):
        super().__init__("事件验证官", "event_validator", knowledge_base, memory_manager)

    def get_system_prompt(self) -> str:
        from app.services.prompts.manager import prompt_manager
        return prompt_manager.get_agent_prompt("event_validator")

    def validate_events(self, events: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """验证事件序列"""
        from app.services.prompts.manager import prompt_manager
        validation_prompt = prompt_manager.get_user_prompt(
            "event_validator_validate", variables={"events": events}
        )

        result = self.process(validation_prompt, context)

        return {
            "validation_result": result,
            "status": "completed"
        }


class StyleOptimizerAgent(BaseAgent):
    """文风优化师Agent - 优化文风和语言表达"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None):
        super().__init__("文风优化师", "style_optimizer", knowledge_base, memory_manager)

    def get_system_prompt(self) -> str:
        from app.services.prompts.manager import prompt_manager
        return prompt_manager.get_agent_prompt("style_optimizer")

    def optimize_style(self, content: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """优化文风"""
        from app.services.prompts.manager import prompt_manager
        optimization_prompt = prompt_manager.get_user_prompt(
            "style_optimizer_optimize", variables={"content": content}
        )

        result = self.process(optimization_prompt, context)

        return {
            "optimized_content": result,
            "status": "completed"
        }


class IterationCoordinatorAgent(BaseAgent):
    """迭代协调官Agent - 协调迭代优化过程"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None):
        super().__init__("迭代协调官", "iteration_coordinator", knowledge_base, memory_manager)

    def get_system_prompt(self) -> str:
        from app.services.prompts.manager import prompt_manager
        return prompt_manager.get_agent_prompt("iteration_coordinator")

    def coordinate_iteration(self, feedback: str, content: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """协调迭代优化"""
        from app.services.prompts.workflow_runtime import (
            build_iteration_coordination_user_prompt,
            get_iteration_coordination_system_prompt,
        )

        runtime_context = context or {}
        coordination_prompt = build_iteration_coordination_user_prompt(
            chapter_number=int(runtime_context.get("chapter_number") or 1),
            chapter_content=content,
            review_text=feedback,
            recent_chapter_assets_summary=runtime_context.get("recent_chapter_assets_summary", ""),
            include_history_hint=bool(runtime_context.get("include_history_hint", False)),
        )

        result = self._process_with_system_prompt(
            coordination_prompt,
            system_prompt=get_iteration_coordination_system_prompt(),
            context=context,
        )

        return {
            "iteration_plan": result,
            "status": "completed"
        }


class ChapterLogicChecker(BaseAgent):
    """章节逻辑检查官Agent - 检查角色功法使用的合理性与境界要求"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None):
        super().__init__("章节逻辑检查官", "chapter_logic_checker", knowledge_base, memory_manager)

    def get_system_prompt(self) -> str:
        from app.services.prompts.manager import prompt_manager
        return prompt_manager.get_agent_prompt("chapter_logic_checker")

    def check_chapter_logic(self, chapter_content: str, character_techniques_map: Dict[str, List[str]],
                           character_realms: Dict[str, str], technique_requirements: Dict[str, str],
                           context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """检查章节逻辑"""
        techniques_summary = "## 角色功法与境界约束\n"
        for char_name, techniques in character_techniques_map.items():
            realm = character_realms.get(char_name, "未知")
            techniques_summary += f"- {char_name}（当前境界：{realm}）：已掌握功法：{', '.join(techniques) if techniques else '无'}\n"

        requirements_summary = "## 功法需求境界\n"
        for tech_name, req_realm in technique_requirements.items():
            requirements_summary += f"- {tech_name}：需求境界 {req_realm}\n"

        from app.services.prompts.manager import prompt_manager
        check_prompt = prompt_manager.get_user_prompt(
            "chapter_logic_checker_check",
            variables={
                "chapter_content": chapter_content,
                "techniques_summary": techniques_summary,
                "requirements_summary": requirements_summary,
            },
        )

        result = self.process(check_prompt, context)

        try:
            json_start = result.find('{')
            json_end = result.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = result[json_start:json_end]
                parsed_result = json.loads(json_str)
                return parsed_result
        except (json.JSONDecodeError, ValueError):
            pass

        return {
            "has_issues": "问题" in result or "错误" in result,
            "issues": [],
            "summary": result,
            "raw_result": result
        }


