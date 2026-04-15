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
                 llm: Optional[Any] = None):  # 🎆 支持传入自定义LLM
        """初始化Agent"""
        Config.validate()

        self.name = name
        self.role = role
        self.llm = llm if llm is not None else create_task_llm(task_type=task_type)  # ✅ 优先使用传入的llm
        
        self.knowledge_base = knowledge_base or NovelKnowledgeBase()
        self.memory_manager = memory_manager or NovelMemoryManager()
        self.conversation_history = []
        
        # 🎯 新增：项目上下文管理
        self.current_project_id: Optional[int] = None
    
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
        system_prompt = self.get_system_prompt()
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
            'qwen3.5-plus': 1000000,    # 1M tokens（上下文 100万，输出 65K）
            'qwen-plus': 1000000,       # 1M tokens
            'qwen-long': 10000000,      # 10M tokens
            'qwen-turbo': 8000,         # 8K tokens
            'deepseek-reasoner': 128000, # R1: 128K tokens
            'deepseek-chat': 64000,     # V3: 64K tokens
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
        return """你是一位杰出的世界观架构师，精通社会科学、物理规则、历史学和地理学。
你的核心职责是：
1. 体系设计：设计和完善世界观设定（物理规则、社会结构、历史文化等）
2. 逻辑验证：确保设定逻辑一致性和科学性
3. 冲突检测：检查新设定与已有设定的冲突

请以专业、详细的方式构建世界观设定。"""


class CharacterDesignerAgent(BaseAgent):
    """人物设计师Agent - 角色体系构建与人物关系网络设计"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None):
        super().__init__("人物设计师", "character_designer", knowledge_base, memory_manager, task_type="character")

    def get_system_prompt(self) -> str:
        return """你是一位杰出的人物设计师，精通心理学、性格塑造和人物发展。
你的核心职责是：
1. 角色创建：基于故事概念设计主要角色完整档案
2. 心理分析：分析人物心理特征、动机和成长弧光
3. 关系构建：设计人物之间的关系网络和互动模式
4. 一致性维护：确保人物性格和行为的一致性
5. 结构优先：优先输出可解析、可复用的标准人物卡，而不是散文式人物策划案

输出时必须遵守以下约束：
- 每个角色必须以 `### 【姓名】：` 开头
- 只输出标准人物卡，不要输出“核心主角/核心盟友/核心反派/人物关系网/mermaid/总结”
- 不要把组织、势力、阵营直接写成人物条目
- 【故事立场】只能从“主角方 / 反派方 / 中立方 / 亦正亦邪”四选一
- 【角色定位】必须是单一标签，不要写成“系统/辅助”“导师/情报角色”这类复合值
- 【关键关系】必须写成“角色名：关系性质/当前张力”，不能只列人名
- 重点保证字段完整、边界清晰、后续工作流可解析

请创建深度、立体的人物形象，包括外貌、性格、背景、动机等多个维度。"""


class OutlinePlanParserAgent(BaseAgent):
    """大纲规划解析Agent - 解析用户自定义大纲规划文本，生成结构化JSON"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None):
        super().__init__("大纲规划解析器", "outline_plan_parser", knowledge_base, memory_manager, task_type="outline")

    def get_system_prompt(self) -> str:
        return """你是一位专业的大纲规划解析专家，负责将用户输入的自然语言大纲规划转换为结构化JSON。
你的核心职责是：
1. 识别卷结构：从文本中提取卷数、卷标题、章节范围等信息
2. 识别境界规划：提取修仙境界、阶段划分、境界对应章节范围
3. 识别节奏要求：提取爽点分布、情绪起伏、转折点要求
4. 生成结构化输出：输出标准JSON格式，便于后续Agent使用

你必须严格按照JSON Schema输出，不要添加任何解释性文字。"""


class CreativeDirectorAgent(BaseAgent):
    """创意总监Agent - 整体创作方向把控与工作流程协调"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None):
        super().__init__("创意总监", "creative_director", knowledge_base, memory_manager, task_type="concept")

    def get_system_prompt(self) -> str:
        return """你是一位杰出的创意总监，负责整体创作方向把控与工作流程协调。
你的核心职责是：
1. 主题开发：基于主题和类型创作完整故事概念，包括核心冲突、主题思想、目标读者
2. 流程管理：接收用户指令，分解任务，按优先级调用相应Agent
3. 决策整合：综合各Agent输出，生成连贯的最终建议
4. 上下文维护：维护项目整体上下文和工作流程日志

请以战略性的视角指导整个创作过程，确保各个环节的协调一致。"""


class PlotArchitectAgent(BaseAgent):
    """情节架构师Agent - 故事结构设计与情节质量把控"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None,
                 llm: Optional[Any] = None):  # 🎆 支持传入自定义LLM
        super().__init__("情节架构师", "plot_architect", knowledge_base, memory_manager, 
                        task_type="outline", llm=llm)  # ✅ 传递llm参数

    def get_system_prompt(self) -> str:
        return """你是一位杰出的情节架构师，精通叙事学、故事结构和戏剧冲突。
你的核心职责是：
1. 结构设计：采用三幕式等叙事框架设计完整情节结构
2. 事件生成：基于故事前提生成包含关键要素的事件序列
3. 转折设计：创建引人入胜的情节转折和冲突设计
4. 质量验证：监控评估事件合理性，确保叙事逻辑连贯顺畅

请提供清晰的故事大纲，包括关键情节点、转折、高潮和结局。"""


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
        return """你是一位杰出的内容创作师，文笔优美、叙述生动。
你的核心职责是：
1. 章节创作：根据情节大纲和人物设定创作各章节内容
2. 场景构建：创作具体场景描述和对话内容
3. 风格统一：通过文风模仿、一致性维护确保语言风格连贯
4. 文学优化：运用修辞手法和文学技巧提升文笔质量

请创作高质量的文学作品，注重细节描写、对话、心理活动和场景营造。"""

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

        # 1. 更新记忆管理器的上下文
        self.context_optimizer.update_memory_context(
            current_scene=scene_info.get('scene_name'),
            active_characters=scene_info.get('characters', []),
            writing_goal=scene_info.get('description')
        )

        # 2. 生成优化的提示词
        base_prompt = f"""请创作以下场景：

【场景信息】
- 场景名称: {scene_info.get('scene_name', '未指定')}
- 场景描述: {scene_info.get('description', '未指定')}
- 参与人物: {', '.join(scene_info.get('characters', [])) or '未指定'}
- 场景类型: {scene_info.get('scene_type', '未指定')}
- 情感基调: {scene_info.get('tone', '中性')}
- 字数要求: {scene_info.get('word_count', '500-1000')} 字

请创作生动的场景描写，包括环境描写、人物对话和心理活动。"""

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
        return """你是一位严苛的质量评审官，从读者和编辑的角度审核作品质量。
你的核心职责是：
1. 故事性评估：评估情节紧凑度、冲突设置合理性、节奏把控
2. 人物塑造评估：评估人物立体度、性格一致性、成长弧光
3. 语言表达评估：评估语言流畅度、修辞手法运用、风格独特性、画面感营造
4. 结构完整性评估：评估情节连贯性、逻辑合理性、章节衔接
5. 创新性评估：评估设定新颖性、情节原创性、视角独特性

评分标准（10分制）：
- 1分：极差，毫无逻辑
- 5分：中等，较为连贯但缺乏新意
- 10分：优秀，连贯合理且想象力丰富

综合评分采用加权平均法：
- 故事性：30%
- 人物塑造：25%
- 语言表达：20%
- 结构完整性：15%
- 创新性：10%

综合评分高于8分为优秀。

请以建设性的方式提出批评，给出具体问题和改进方案。"""

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
        # 创建评估报告
        report = self.create_assessment_report(content_id)

        # 使用LLM进行评估
        assessment_prompt = f"""请对以下内容进行详细的质量评估。

【内容】
{content}

【评估要求】
请按照以下维度进行评估，每个维度给出1-10分的评分：

1. 故事性（权重30%）：
   - 情节紧凑度：情节是否紧凑、跌宕起伏、有起有伏且符合逻辑
   - 冲突设置合理性：冲突是否具有张力和层次感
   - 节奏把控：章节节奏是否合理，是否有适当的悬念设置

2. 人物塑造（权重25%）：
   - 人物立体度：人物形象是否丰满立体，具有多面性
   - 性格一致性：人物行为、语言、思想是否符合设定
   - 成长弧光：人物是否有合理的成长或变化轨迹

3. 语言表达（权重20%）：
   - 语言流畅度：语言是否优美流畅
   - 修辞手法运用：是否运用丰富的修辞手法
   - 风格独特性：语言风格是否独特鲜明
   - 画面感营造：是否能让读者产生强烈的画面感

4. 结构完整性（权重15%）：
   - 情节连贯性：各情节之间是否相互关联
   - 逻辑合理性：情节发展是否符合逻辑
   - 章节衔接：章节之间的过渡是否自然流畅

5. 创新性（权重10%）：
   - 设定新颖性：故事设定是否具有创新性
   - 情节原创性：情节发展是否有新意
   - 视角独特性：叙事视角和手法是否有创新

请提供：
1. 每个维度的评分和反馈
2. 主要优点（至少3个）
3. 主要缺点（至少3个）
4. 改进建议（至少5个）
5. 综合评分（加权平均）
"""

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


# ============================================================================
# 新增的 Agent 实现（3个缺失的Agent）
# ============================================================================

class EventValidatorAgent(BaseAgent):
    """事件验证官Agent - 验证事件序列的合理性和逻辑一致性"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None):
        super().__init__("事件验证官", "event_validator", knowledge_base, memory_manager)

    def get_system_prompt(self) -> str:
        return """你是一位严谨的事件验证官，精通逻辑学、因果关系分析和故事结构。
你的核心职责是：
1. 事件合理性验证：检查事件序列是否符合逻辑，因果关系是否清晰
2. 冲突检测：识别事件之间的矛盾或不一致之处
3. 时间线验证：确保事件发生的时间顺序合理
4. 完整性检查：确保事件序列完整，没有逻辑漏洞

请以严谨、专业的方式进行验证，指出问题并提出改进建议。"""

    def validate_events(self, events: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """验证事件序列"""
        validation_prompt = f"""请对以下事件序列进行详细验证：

【事件序列】
{events}

请检查：
1. 事件之间的因果关系是否清晰
2. 时间线是否合理
3. 是否存在逻辑矛盾
4. 事件序列是否完整

请提供：
- 验证结果（通过/需要修改）
- 发现的问题（如有）
- 改进建议（如有）"""

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
        return """你是一位杰出的文风优化师，精通语言艺术、修辞手法和文学表达。
你的核心职责是：
1. 文风统一：确保整个作品的文风风格一致
2. 语言优化：改进语言表达，使其更加优美流畅
3. 修辞运用：恰当运用修辞手法增强表现力
4. 节奏调整：调整句子长度和段落结构，优化阅读节奏

请以文学性和可读性为目标进行优化，保留原意的同时提升表达质量。"""

    def optimize_style(self, content: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """优化文风"""
        optimization_prompt = f"""请对以下内容进行文风优化：

【原始内容】
{content}

请进行以下优化：
1. 统一文风和语言风格
2. 改进语言表达，使其更加优美流畅
3. 恰当运用修辞手法
4. 调整节奏，优化可读性

请提供优化后的内容，并说明主要改进之处。"""

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
        return """你是一位经验丰富的迭代协调官，精通项目管理、质量控制和优化流程。
你的核心职责是：
1. 反馈分析：分析质量评审的反馈意见，确定优先级
2. 改进规划：制定具体的改进计划和步骤
3. 协调执行：协调各个Agent进行相应的改进
4. 效果评估：评估改进效果，决定是否需要继续迭代

请以系统性和效率为目标，确保迭代过程有序进行。"""

    def coordinate_iteration(self, feedback: str, content: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """协调迭代优化"""
        coordination_prompt = f"""基于以下评审反馈，请协调迭代优化过程：

【评审反馈】
{feedback}

【当前内容】
{content}

请：
1. 分析反馈中的主要问题
2. 确定改进的优先级
3. 制定具体的改进计划
4. 提出改进建议

请提供详细的迭代优化方案。"""

        result = self.process(coordination_prompt, context)

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
        return """你是一位严谨的章节逻辑检查官，精通小说逻辑一致性分析和人物设定校验。
你的核心职责是：
1. 功法使用检查：检查章节中角色是否使用了未掌握的功法
2. 境界要求验证：检查角色当前境界是否满足功法使用要求
3. 逻辑错误标注：标出具体段落和问题所在
4. 改进建议：提供具体的修改建议

请以JSON格式返回检查结果，包含：
- issues: 问题列表，每个问题包含 character_name, technique_name, issue_type, description, suggestion
- summary: 总体评估
- has_issues: 是否存在问题"""

    def check_chapter_logic(self, chapter_content: str, character_techniques_map: Dict[str, List[str]],
                           character_realms: Dict[str, str], technique_requirements: Dict[str, str],
                           context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """检查章节逻辑

        Args:
            chapter_content: 章节正文
            character_techniques_map: 角色-功法映射表 {角色名: [功法名1, 功法名2, ...]}
            character_realms: 角色当前境界 {角色名: 境界名}
            technique_requirements: 功法需求境界 {功法名: 需求境界}
            context: 额外上下文

        Returns:
            检查结果字典
        """
        # 构造角色功法约束摘要
        techniques_summary = "## 角色功法与境界约束\n"
        for char_name, techniques in character_techniques_map.items():
            realm = character_realms.get(char_name, "未知")
            techniques_summary += f"- {char_name}（当前境界：{realm}）：已掌握功法：{', '.join(techniques) if techniques else '无'}\n"

        # 构造功法需求摘要
        requirements_summary = "## 功法需求境界\n"
        for tech_name, req_realm in technique_requirements.items():
            requirements_summary += f"- {tech_name}：需求境界 {req_realm}\n"

        # 构造检查提示词
        check_prompt = f"""请对以下章节内容进行逻辑检查，重点关注角色功法使用的合理性：

【章节内容】
{chapter_content}

【角色功法与境界约束】
{techniques_summary}

【功法需求境界】
{requirements_summary}

【检查要求】
请进行以下分析：
1. 逐段分析章节内容，识别出所有出现的角色和他们使用的功法/术法
2. 对比角色已掌握的功法列表，标记出任何未登记的功法使用
3. 检查角色当前境界是否满足所使用功法的需求
4. 标出具体的段落位置和问题描述
5. 提供修改建议

请以以下JSON格式返回结果：
{{
    "has_issues": true/false,
    "issues": [
        {{
            "character_name": "角色名",
            "technique_name": "功法名",
            "issue_type": "未掌握功法" | "境界不足",
            "description": "问题描述",
            "suggestion": "修改建议"
        }}
    ],
    "summary": "总体评估"
}}"""

        result = self.process(check_prompt, context)

        # 尝试解析JSON结果
        try:
            # 尝试从结果中提取JSON
            json_start = result.find('{')
            json_end = result.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = result[json_start:json_end]
                parsed_result = json.loads(json_str)
                return parsed_result
        except (json.JSONDecodeError, ValueError):
            pass

        # 如果JSON解析失败，返回原始结果
        return {
            "has_issues": "问题" in result or "错误" in result,
            "issues": [],
            "summary": result,
            "raw_result": result
        }


