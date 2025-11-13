"""
创意总监协调器 - 协调多个Agent的五阶段工作流程
"""
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
from langchain_community.chat_models import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from .config import Config
from .knowledge_base import NovelKnowledgeBase
from .memory_manager import NovelMemoryManager
from .agents import (
    WorldArchitectAgent, CharacterDesignerAgent, PlotArchitectAgent,
    ContentCreatorAgent, QualityReviewerAgent, CreativeDirectorAgent, create_deepseek_llm
)
from .agent_communication import AgentCommunicationHub

# 🆕 模型优化：导入优化的LLM客户端
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.llm_client import get_llm_client  # type: ignore
    from app.services.model_optimizer import TaskType  # type: ignore

try:
    from app.services.llm_client import get_llm_client  # type: ignore
    from app.services.model_optimizer import TaskType  # type: ignore
    OPTIMIZER_AVAILABLE = True
    print("✅ 模型优化器已加载（保守策略）")
except ImportError as e:
    OPTIMIZER_AVAILABLE = False
    get_llm_client = None  # type: ignore
    TaskType = None  # type: ignore
    print(f"⚠️  模型优化器未加载，使用默认模式: {e}")


class CreativeDirectorCoordinator:
    """创意总监协调器 - 协调多个Agent的五阶段工作流程"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None,
                 enable_communication: bool = False,
                 enable_conflict_detection: bool = False,
                 enable_detailed_logging: bool = False):
        """初始化创意总监协调器
        
        Args:
            knowledge_base: 知识库实例
            memory_manager: 记忆管理器实例
            enable_communication: 是否启用Agent通信中心（默认False，保持向后兼容）
            enable_conflict_detection: 是否启用冲突检测（需要enable_communication=True）
            enable_detailed_logging: 是否启用详细执行日志
        """
        Config.validate()

        self.name = "创意总监"
        self.knowledge_base = knowledge_base or NovelKnowledgeBase()
        self.memory_manager = memory_manager or NovelMemoryManager()

        # 初始化各个专业Agent
        self.creative_director = CreativeDirectorAgent(self.knowledge_base, self.memory_manager)
        self.world_architect = WorldArchitectAgent(self.knowledge_base, self.memory_manager)
        self.character_designer = CharacterDesignerAgent(self.knowledge_base, self.memory_manager)
        self.plot_architect = PlotArchitectAgent(self.knowledge_base, self.memory_manager)
        self.content_creator = ContentCreatorAgent(self.knowledge_base, self.memory_manager)
        self.quality_reviewer = QualityReviewerAgent(self.knowledge_base, self.memory_manager)

        self.llm = create_deepseek_llm()
        
        # 🆕 模型优化：初始化优化的LLM客户端
        if OPTIMIZER_AVAILABLE and get_llm_client is not None:
            try:
                strategy = os.getenv('MODEL_OPTIMIZATION_STRATEGY', 'conservative')
                self.optimized_llm = get_llm_client(strategy)
                print(f"✅ 优化的LLM客户端已启用，策略: {strategy}")
            except Exception as e:
                self.optimized_llm = None
                print(f"⚠️  优化的LLM客户端启动失败: {e}")
        else:
            self.optimized_llm = None

        self.project_context = {
            "title": None,
            "genre": None,
            "concept": None,
            "world_setting": None,
            "characters": [],
            "plot_outline": None,
            "chapters": [],
            "current_stage": None
        }

        self.workflow_log = []
        self.iteration_count = 0
        self.max_iterations = 3
        
        # 🎯 新增：项目上下文管理
        self.current_project_id: Optional[int] = None
        
        # 🆕 WebSocket进度回调相关属性
        self.progress_callback = None  # 进度回调函数
        self.current_task_id: Optional[str] = None  # 当前任务ID
        
        # 🚀 优化：智能缓存机制
        self._kb_cache: Dict[str, tuple[List, float]] = {}  # 缓存：{查询键: (结果, 时间戳)}
        self._cache_ttl = 300  # 缓存生存时间：5分钟
        self._cache_max_size = 100  # 最大缓存条目数
        
        # 🚀 优化：相关性评分配置
        self._relevance_threshold = 0.5  # 相关性阈值（0-1），低于此值的结果会被过滤
        
        # 🚀 优化：动态k值配置
        self._enable_dynamic_k = True  # 是否启用动态k值
        self._min_k = 1  # 最小返回结果数
        self._max_k = 5  # 最大返回结果数
        
        # 🆕 方案A新增：可选的Agent通信中心
        self.enable_communication = enable_communication
        self.enable_conflict_detection = enable_conflict_detection
        self.enable_detailed_logging = enable_detailed_logging
        self.communication_hub: Optional[AgentCommunicationHub] = None
        self.execution_log: List[Dict[str, Any]] = []  # 详细执行日志
        
        if self.enable_communication:
            self.communication_hub = AgentCommunicationHub()
            self._register_all_agents()
            print(f"✓ Agent通信中心已启用")
        
        if self.enable_conflict_detection and not self.enable_communication:
            print(f"⚠️ 冲突检测需要启用通信中心，已自动启用通信中心")
            self.enable_communication = True
            self.communication_hub = AgentCommunicationHub()
            self._register_all_agents()
        
        if self.enable_detailed_logging:
            print(f"✓ 详细执行日志已启用")
    
    def set_project_context(self, project_id: int):
        """🎯 设置当前项目上下文"""
        self.current_project_id = project_id
        print(f"🎯 已设置项目上下文: project_id={project_id}")
        
        # 同步更新 project_context
        if "project_id" not in self.project_context:
            self.project_context["project_id"] = project_id
        
        # 🎯 为所有Agent设置项目上下文
        for agent in [self.creative_director, self.world_architect, 
                     self.character_designer, self.plot_architect,
                     self.content_creator, self.quality_reviewer]:
            agent.set_project_context(project_id)
    
    def set_progress_callback(self, callback, task_id: str, project_id: int):
        """🆕 设置进度回调函数（用于WebSocket实时推送）
        
        Args:
            callback: 异步回调函数，接收 (project_id, task_id, progress, message) 参数
            task_id: 当前任务ID
            project_id: 当前项目ID
        """
        self.progress_callback = callback
        self.current_task_id = task_id
        if not self.current_project_id:
            self.current_project_id = project_id
        print(f"✅ 已设置进度回调: task_id={task_id}, project_id={project_id}")
    
    def _send_progress_update(self, progress: int, message: str):
        """🆕 发送进度更新（如果设置了回调）
        
        Args:
            progress: 进度百分比 (0-100)
            message: 进度消息
        """
        if self.progress_callback and self.current_task_id and self.current_project_id:
            import asyncio
            try:
                # 如果在异步上下文中，直接await
                # 否则创建任务
                if asyncio.iscoroutinefunction(self.progress_callback):
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # 在运行的事件循环中创建任务
                        asyncio.create_task(
                            self.progress_callback(
                                self.current_project_id,
                                self.current_task_id,
                                progress,
                                message
                            )
                        )
                    else:
                        # 没有运行的事件循环，使用run_until_complete
                        loop.run_until_complete(
                            self.progress_callback(
                                self.current_project_id,
                                self.current_task_id,
                                progress,
                                message
                            )
                        )
                else:
                    # 同步回调
                    self.progress_callback(
                        self.current_project_id,
                        self.current_task_id,
                        progress,
                        message
                    )
                print(f"📊 进度更新: {progress}% - {message}")
            except Exception as e:
                print(f"⚠️ 进度回调失败: {e}")
        else:
            # 没有设置回调，仅打印日志
            print(f"📊 进度: {progress}% - {message}")
    
    def _search_knowledge(self, query: str, filter_type: Optional[str] = None, k: int = 5) -> List:
        """🚀 增强版知识库搜索，自动带上项目ID，支持缓存、相关性过滤、动态k值
        
        Args:
            query: 搜索查询
            filter_type: 类型过滤
            k: 返回结果数量
            
        Returns:
            搜索结果列表
        """
        import time
        
        # 🚀 优化1：智能缓存机制
        cache_key = f"{self.current_project_id}:{filter_type}:{query}:{k}"
        current_time = time.time()
        
        # 检查缓存
        if cache_key in self._kb_cache:
            cached_results, cached_time = self._kb_cache[cache_key]
            if current_time - cached_time < self._cache_ttl:
                print(f"⚡ 从缓存读取知识库结果（{len(cached_results)}条）")
                return cached_results
            else:
                # 缓存过期，删除
                del self._kb_cache[cache_key]
        
        # 🚀 优化3：动态k值
        if self._enable_dynamic_k:
            # 根据知识库中的内容数量动态调整k值
            # 这里简化处理：根据过滤类型调整
            if filter_type == "world_setting":
                k = min(k, 3)  # 世界观设定通常不多，限制为3
            elif filter_type == "character":
                k = min(k, 4)  # 人物设定可能较多，限制为4
            k = max(k, self._min_k)  # 确保不低于最小值
        
        # 执行搜索
        results = self.knowledge_base.search(
            query=query,
            k=k * 2,  # 搜索更多结果，然后过滤
            filter_type=filter_type,
            project_id=self.current_project_id  # 🎯 自动注入项目ID
        )
        
        # 🚀 优化2：相关性评分过滤
        # 注：chromadb返回的document对象可能包含metadata中的相似度分数
        filtered_results = []
        for doc in results:
            # 检查是否有相似度分数
            if hasattr(doc, 'metadata') and 'score' in doc.metadata:
                score = doc.metadata.get('score', 1.0)
                if score >= self._relevance_threshold:
                    filtered_results.append(doc)
            else:
                # 如果没有分数，则保留（向后兼容）
                filtered_results.append(doc)
        
        # 限制最终结果数量
        filtered_results = filtered_results[:k]
        
        # 存入缓存
        self._kb_cache[cache_key] = (filtered_results, current_time)
        
        # 缓存大小控制：LRU策略
        if len(self._kb_cache) > self._cache_max_size:
            # 删除最旧的缓存条目
            oldest_key = min(self._kb_cache.keys(), key=lambda k: self._kb_cache[k][1])
            del self._kb_cache[oldest_key]
        
        return filtered_results
    
    def _register_all_agents(self):
        """🆕 注册所有Agent到通信中心"""
        if not self.communication_hub:
            return
        
        self.communication_hub.register_agent("创意总监", self.creative_director)
        self.communication_hub.register_agent("世界观架构师", self.world_architect)
        self.communication_hub.register_agent("人物设计师", self.character_designer)
        self.communication_hub.register_agent("情节架构师", self.plot_architect)
        self.communication_hub.register_agent("内容创作师", self.content_creator)
        self.communication_hub.register_agent("质量评审官", self.quality_reviewer)
    
    def _log_agent_execution(self, agent_name: str, stage: str, input_data: str, output: str, duration: float = 0.0):
        """🆕 记录Agent执行详情"""
        if not self.enable_detailed_logging:
            return
        
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "stage": stage,
            "agent": agent_name,
            "input": input_data[:200] + "..." if len(input_data) > 200 else input_data,
            "output": output[:200] + "..." if len(output) > 200 else output,
            "duration": f"{duration:.2f}s" if duration > 0 else "N/A"
        }
        self.execution_log.append(log_entry)
        
        print(f"📝 [{log_entry['timestamp']}] {agent_name} - {stage}")
        print(f"   输入: {log_entry['input']}")
        print(f"   输出: {log_entry['output']}")
        if duration > 0:
            print(f"   耗时: {log_entry['duration']}")
    
    def _detect_and_resolve_conflicts(self, outputs: Dict[str, str], stage_name: str) -> Optional[Dict[str, str]]:
        """🆕 检测并解决Agent输出之间的冲突
        
        Args:
            outputs: Agent输出字典，key为Agent名称，value为输出内容
            stage_name: 阶段名称
            
        Returns:
            如果有冲突并成功调解，返回调解结果；否则返回None
        """
        if not self.enable_conflict_detection or not self.communication_hub:
            return None
        
        # 检测冲突
        conflicts = self.communication_hub.detect_conflicts(outputs)
        
        if conflicts:
            print(f"\n⚠️ 在{stage_name}阶段检测到 {len(conflicts)} 个冲突")
            for conflict in conflicts:
                print(f"   - {conflict['agent1']} vs {conflict['agent2']}: {conflict['pattern']}")
            
            # 调解冲突
            print(f"\n🔧 启动创意总监进行冲突调解...")
            resolutions = self.communication_hub.resolve_conflicts(conflicts, mediator="创意总监")
            
            print(f"✓ 冲突调解完成")
            return resolutions
        
        return None
    
    def print_execution_log(self):
        """🆕 打印详细执行日志"""
        if not self.execution_log:
            print("\n暂无执行日志")
            return
        
        print(f"\n{'='*70}")
        print("【执行日志】")
        print(f"{'='*70}\n")
        
        for log in self.execution_log:
            print(f"[{log['timestamp']}] {log['stage']} - {log['agent']}")
            print(f"  输入: {log['input']}")
            print(f"  输出: {log['output']}")
            print(f"  耗时: {log['duration']}")
            print()
        
        print(f"{'='*70}\n")
    
    def get_communication_log(self) -> Optional[List]:
        """🆕 获取通信日志"""
        if not self.communication_hub:
            return None
        return self.communication_hub.get_message_history()
    
    def print_communication_log(self):
        """🆕 打印通信日志"""
        if not self.communication_hub:
            print("\n通信中心未启用")
            return
        self.communication_hub.print_communication_log()
    
    def process_user_request(self, user_input: str) -> str:
        """处理用户请求的主工作流程 - 五阶段工作流程"""
        print(f"\n{'='*70}")
        print(f"【{self.name}】收到用户指令: {user_input}")
        print(f"{'='*70}\n")

        self.memory_manager.add_user_message(user_input)

        # 阶段一：概念开发
        print(f"\n【{self.name}】启动阶段一：概念开发阶段")
        concept_result = self._stage_one_concept_development(user_input)

        # 阶段二：结构设计
        print(f"\n【{self.name}】启动阶段二：结构设计阶段")
        structure_result = self._stage_two_structure_design(concept_result)

        # 阶段三：内容创作
        print(f"\n【{self.name}】启动阶段三：内容创作阶段")
        content_result = self._stage_three_content_creation(structure_result)

        # 阶段四：质量评审
        print(f"\n【{self.name}】启动阶段四：质量评审阶段")
        review_result = self._stage_four_quality_review(content_result)

        # 阶段五：迭代优化（如果需要）
        final_result = review_result
        if review_result.get("needs_revision", False) and self.iteration_count < self.max_iterations:
            print(f"\n【{self.name}】启动阶段五：迭代优化循环")
            self.iteration_count += 1
            final_result = self._stage_five_iteration_optimization(review_result)

        self.memory_manager.add_ai_message(str(final_result))
        self.workflow_log.append({
            "user_input": user_input,
            "concept": concept_result,
            "structure": structure_result,
            "content": content_result,
            "review": review_result,
            "final_result": final_result
        })

        print(f"\n{'='*70}")
        print(f"【{self.name}】任务完成")
        print(f"{'='*70}\n")

        return str(final_result)
    
    def _stage_one_concept_development(self, user_input: str) -> Dict[str, Any]:
        """阶段1：概念开发阶段
        创意总监接收用户输入，并行调用世界观架构师和人物设计师
        🔧 修复：禁用知识库搜索，100%基于用户需求创作
        🆕 优化：任务分块执行，实时推送进度保持WebSocket活跃
        """
        import time
        start_time = time.time()
        
        print(f"【{self.name}】分析创作需求...")
        print(f"💡 概念开发阶段：完全基于用户需求创作，不参考知识库")
        print(f"📝 用户需求: {user_input[:100]}...")

        # 🔧 修复策略：新项目概念开发阶段完全禁用知识库搜索
        kb_reference = ""  # 不再搜索知识库

        # 🆕 子任务1：创意总监分析需求（10%）
        self._send_progress_update(10, "💡 正在分析用户创作需求...")
        
        # 创意总监分析需求 - 100%基于用户输入
        concept_prompt = f"""你是一位资深创意总监。请严格基于用户的实际创作需求进行创作。

【核心原则】用户需求是唯一标准，必须100%遵循！

用户需求: {user_input}

请基于用户需求提供：
1. 故事核心冲突
2. 主题思想
3. 目标读者
4. 故事背景和设定方向

【关键要求】
- 题材类型：严格按照用户指定的题材（武侠/科幻/玄幻/现代等）
- 故事风格：必须符合用户描述的风格和氛围
- 创新性：在用户框架内创新，不改变用户意图
- 独立创作：不参考任何已有设定，完全基于用户需求

⚠️ 警告：绝对不允许改变用户指定的题材类型！

【输出格式要求】
请使用以下Markdown格式输出，确保结构清晰、易于阅读：

## 故事核心冲突
（描述核心冲突，2-3段）

## 主题思想
（阐述主题思想，2-3段）

## 目标读者
- 年龄段：
- 阅读偏好：
- 期待体验：

## 故事背景和设定方向
（描述背景设定，3-5段）

**格式规范**：
- 使用Markdown标题层级（##、###）
- 段落之间空一行
- 列表项使用 `-` 或 `1.` 格式
- 重要信息使用**加粗**标记
- 避免连续空行（最多2行）"""

        # 🆕 子任务2：生成核心概念（30%）
        self._send_progress_update(30, "🎨 正在生成故事核心概念...")
        
        concept = self.creative_director.process(concept_prompt, self.project_context)
        self.project_context["concept"] = concept
        
        # 🆕 记录创意总监执行
        self._log_agent_execution("创意总监", "阶段1-概念开发", concept_prompt, concept, time.time() - start_time)

        # 🆕 子任务3：启动并行Agent（50%）
        self._send_progress_update(50, "🚀 并行启动世界观架构师和人物设计师...")
        print(f"【{self.name}】并行启动世界观架构师和人物设计师...")
        
        # 并行调用世界观架构师
        world_start = time.time()
        world_prompt = f"""基于以下故事概念，设计世界观设定：
{concept}
{kb_reference}"""
        world_result = self.world_architect.process(world_prompt, self.project_context)
        self.project_context["world_setting"] = world_result
        
        self._log_agent_execution("世界观架构师", "阶段1-概念开发", world_prompt, world_result, time.time() - world_start)

        # 🆕 子任务4：人物设计师工作（70%）
        self._send_progress_update(70, "👥 正在设计主要人物...")
        
        # 并行调用人物设计师
        character_start = time.time()
        character_prompt = f"基于以下故事概念，设计主要人物：\n{concept}"
        character_result = self.character_designer.process(character_prompt, self.project_context)
        self.project_context["characters"] = character_result
        
        self._log_agent_execution("人物设计师", "阶段1-概念开发", character_prompt, character_result, time.time() - character_start)

        # 🆕 子任务5：冲突检测与解决（90%）
        self._send_progress_update(90, "🔍 正在检测并解决潜在冲突...")
        
        # 🆕 冲突检测与解决
        conflict_resolutions = self._detect_and_resolve_conflicts(
            {
                "世界观架构师": world_result,
                "人物设计师": character_result
            },
            "阶段1-概念开发"
        )

        # 🆕 子任务6：完成整合（100%）
        self._send_progress_update(100, "✅ 概念开发阶段完成！")
        print(f"【{self.name}】阶段1完成：概念开发完成")

        result: Dict[str, Any] = {
            "concept": concept,
            "world_setting": world_result,
            "characters": character_result
        }
        
        # 如果有冲突调解结果，添加到返回值
        if conflict_resolutions:
            result["conflict_resolutions"] = conflict_resolutions
        
        return result

    def _stage_two_structure_design(self, concept_result: Dict[str, Any]) -> Dict[str, Any]:
        """阶段二：结构设计阶段
        情节架构师生成事件序列和情节大纲
        🆕 集成知识库：搜索经典情节结构和叙事模式参考
        """
        print(f"【{self.name}】启动情节架构师生成事件序列...")

        # 🆕 知识库增强：搜索经典情节结构参考
        structure_reference = ""
        if self.current_project_id:
            print(f"🔍 正在搜索知识库中的情节结构参考...")
            # 搜索已有的情节大纲作为参考
            similar_plots = self._search_knowledge(
                query="三幕剧结构 情节转折 高潮",
                filter_type="chapter",
                k=2
            )
            
            if similar_plots:
                structure_reference = "\n\n【知识库参考 - 经典情节结构】\n"
                for i, doc in enumerate(similar_plots, 1):
                    structure_reference += f"{i}. 参考结构：{doc.page_content[:150]}...\n"
                structure_reference += "\n💡 可以参考以上结构的叙事节奏，但要根据本故事特点调整。\n"
                print(f"✓ 找到 {len(similar_plots)} 个情节结构参考")

        plot_prompt = f"""基于以下故事设定，设计完整的情节结构：

【世界观设定】
{concept_result['world_setting']}

【人物设定】
{concept_result['characters']}

{structure_reference}

请提供：
1. 三幕剧结构
2. 关键情节点
3. 情节转折
4. 高潮和结局

【输出格式要求】
请使用以下Markdown格式输出，确保结构清晰、层次分明：

## 一、三幕剧结构

### 第一幕：开端（Setup）
**时间跨度**：第1-X章
**核心任务**：
- 建立世界观
- 介绍主要人物
- 引入核心冲突

**主要情节**：
1. （情节点1）
2. （情节点2）
3. （情节点3）

---

### 第二幕：对抗（Confrontation）
**时间跨度**：第X-Y章
**核心任务**：
- 冲突升级
- 人物成长
- 推向高潮

**主要情节**：
1. （情节点1）
2. （情节点2）
3. （情节点3）

---

### 第三幕：结局（Resolution）
**时间跨度**：第Y-Z章
**核心任务**：
- 高潮对决
- 解决冲突
- 收束故事

**主要情节**：
1. （情节点1）
2. （情节点2）
3. （情节点3）

---

## 二、关键情节点

| 章节 | 情节点名称 | 描述 | 作用 |
|------|-----------|------|------|
| 第X章 | （名称） | （描述） | （作用） |
| 第Y章 | （名称） | （描述） | （作用） |

---

## 三、情节转折

1. **第一次转折**（第X章）
   - 触发事件：
   - 影响：
   - 后续发展：

2. **第二次转折**（第Y章）
   - 触发事件：
   - 影响：
   - 后续发展：

---

## 四、高潮和结局

### 高潮部分（第X章）
（描述高潮场景，3-5段）

### 结局部分（第Y章）
（描述结局，2-3段）

**格式规范**：
- 使用Markdown标题层级（##、###）
- 章节之间使用分隔线 `---`
- 重要信息使用**加粗**标记
- 表格格式清晰对齐
- 段落之间空一行"""

        plot_result = self.plot_architect.process(plot_prompt, self.project_context)
        self.project_context["plot_outline"] = plot_result

        print(f"【{self.name}】阶段二完成：情节结构设计完成")

        return {
            "plot_outline": plot_result,
            "concept": concept_result
        }

    def _stage_three_content_creation(self, structure_result: Dict[str, Any]) -> Dict[str, Any]:
        """阶段三：增强版内容创作阶段
        内容创作师根据情节大纲创作章节内容，包含已生成章节的分析
        🆕 集成知识库：搜索相关设定和细节，确保内容一致性
        """
        print(f"【{self.name}】启动内容创作师创作章节...")

        # 🆕 确定当前要创作的章节编号
        current_chapter_number = len(self.project_context.get("chapters", [])) + 1
        print(f"📖 准备创作第{current_chapter_number}章")

        # 🆕 知识库增强：搜索相关世界观和人物设定
        kb_settings = ""
        if self.current_project_id:
            print(f"🔍 正在搜索知识库中的相关设定...")
            
            # 搜索世界观设定
            world_setting_text = self.project_context.get('world_setting', '')
            # 🔥 确保 query 是字符串类型
            if isinstance(world_setting_text, (list, dict)):
                world_setting_text = str(world_setting_text)
            
            world_docs = self._search_knowledge(
                query=world_setting_text,
                filter_type="world_setting",
                k=2
            )
            
            # 搜索人物设定
            characters_text = self.project_context.get('characters', '')
            # 🔥 确保 query 是字符串类型
            if isinstance(characters_text, (list, dict)):
                characters_text = str(characters_text)
            
            character_docs = self._search_knowledge(
                query=characters_text,
                filter_type="character",
                k=2
            )
            
            if world_docs or character_docs:
                kb_settings = "\n\n【知识库参考 - 已存储的设定】\n"
                
                if world_docs:
                    kb_settings += "世界观设定：\n"
                    for doc in world_docs:
                        kb_settings += f"- {doc.page_content[:150]}...\n"
                
                if character_docs:
                    kb_settings += "\n人物设定：\n"
                    for doc in character_docs:
                        kb_settings += f"- {doc.page_content[:150]}...\n"
                
                kb_settings += "\n⚠️ 请严格遵守以上设定，确保内容一致性。\n"
                print(f"✓ 找到 {len(world_docs) + len(character_docs)} 条相关设定")

        # 🆕 分析已完成的章节（如果有）
        previous_chapters_analysis = ""
        chapters_list = self.project_context.get("chapters", [])
        if chapters_list and len(chapters_list) > 0:
            previous_chapters_analysis = self._analyze_previous_chapters(chapters_list)
            print(f"✅ 已分析 {len(chapters_list)} 个已完成章节")

        # 🆕 获取前一章结尾（用于衔接）
        previous_ending = ""
        if current_chapter_number > 1 and chapters_list:
            last_chapter = chapters_list[-1]
            previous_ending = last_chapter[-200:] if len(last_chapter) > 200 else last_chapter

        # 🆕 构建动态的创作要求（根据章节编号调整）
        if current_chapter_number == 1:
            creation_requirements = """【创作要求】
1. 开场场景：设计引人入胜的开场，建立故事基调
2. 人物介绍：自然地引入主要人物，展现其性格特点
3. 故事背景：巧妙地交代世界观和背景设定
4. 初始冲突：设置核心矛盾或悬念，吸引读者继续阅读
5. 叙事节奏：保持适当的节奏，避免信息过载
6. 场景描写：运用生动的描写手法营造画面感
7. 对话设计：通过对话展现人物性格和推进情节"""
            chapter_instruction = f"请开始创作第{current_chapter_number}章内容（开篇章节）："
        else:
            creation_requirements = f"""【前一章结尾】
{previous_ending if previous_ending else '（无）'}

【创作要求】
1. 自然衔接：从上一章的结尾自然过渡，避免突兀
2. 情节推进：完成本章应推进的情节，不能原地踏步
3. 人物发展：展现人物成长或关系变化
4. 节奏把控：保持适当的叙事节奏，张弛有度
5. 悬念设置：为下一章埋下伏笔或设置悬念
6. 场景描写：运用生动的描写手法营造画面感
7. 对话设计：通过对话推进情节和展现人物性格"""
            chapter_instruction = f"请开始创作第{current_chapter_number}章内容："

        # 🆕 构建增强版提示词（内置AI痕迹去除指导）
        content_prompt = f"""你是一位经验丰富的小说作家。请基于以下信息创作第{current_chapter_number}章内容：

【情节大纲】
{structure_result['plot_outline']}

【世界观设定】
{self.project_context.get('world_setting', '')}

【人物设定】
{self.project_context['characters']}
{kb_settings}
{previous_chapters_analysis}

{creation_requirements}

【质量标准】
- 逻辑连贯：确保情节发展符合逻辑
- 人物一致：人物言行符合其性格设定
- 世界观一致：遵循已设定的世界观规则
- 文风统一：保持连贯的叙事风格
- 细节丰富：注重细节描写，增强真实感
{f'- 承接自然：与第{current_chapter_number-1}章无缝衔接' if current_chapter_number > 1 else ''}

【创作风格要求 - 去除AI痕迹】
在创作时请特别注意以下几点，使文本更加自然、真实：

1. 语言表达：
   - 避免使用过于程式化、模板化的表达方式
   - 减少重复的句式结构，增加语言的多样性
   - 使用自然、口语化的语言，而非书面化的正式表达
   - 避免过度使用形容词和副词堆砌
   - 用具体的细节替代抽象的概括

2. 人物对话：
   - 让对话更加真实、有人情味，符合人物性格
   - 添加适当的停顿、犹豫、重复等真实对话特征
   - 避免对话过于完美、信息密度过高
   - 通过对话展现人物的矛盾和复杂性

3. 情节推进：
   - 避免情节过于完美、顺利
   - 适当加入意外、阻碍、误会等真实生活元素
   - 让转折点更加自然，而非生硬
   - 保持叙事节奏的张弛有度

4. 场景描写：
   - 运用五感描写（视觉、听觉、嗅觉、触觉、味觉）
   - 添加具体的细节，而非笼统的描述
   - 让场景描写更有画面感和沉浸感
   - 避免陈词滥调和套路化的表述

【输出格式要求 - 章节内容排版】
请严格遵循以下排版规范，确保内容易于阅读：

**1. 章节标题格式**：
**第X章：章节标题**

（标题后空两行）

**2. 段落格式**：
- 每个段落之间空一行
- 每段3-5句话为宜，避免单段过长
- 段落首行不缩进（或缩进两个全角空格，保持一致）

**3. 对话格式**：
- 对话前后各空一行
- 对话内容使用引号："对话内容"
- 对话标签简洁自然

示例：
林墨抬起头，看着眼前的陌生人。

"你是谁？"他警惕地问道。

陌生人微微一笑，没有回答。

**4. 场景转换**：
- 场景转换处空两行
- 可使用简短的过渡句

示例：
（前一场景结束）


（新场景开始）

**5. 避免的问题**：
- ❌ 不要出现大段文字堆砌（超过10行不换段）
- ❌ 不要连续空行超过2行
- ❌ 不要在正文中添加说明性文字
- ❌ 不要使用 `\n\n` 等转义字符（直接换行）

{chapter_instruction}

**请确保输出内容格式规范、结构清晰、易于阅读！**"""

        content_result = self.content_creator.process(content_prompt, self.project_context)

        # ✅ 安全地添加章节，确保 chapters 列表存在
        if "chapters" not in self.project_context:
            self.project_context["chapters"] = []
        self.project_context["chapters"].append(content_result)

        print(f"【{self.name}】阶段三完成：第{current_chapter_number}章内容创作完成，字数：{len(content_result)}")

        return {
            "content": content_result,
            "structure": structure_result
        }

    def _stage_four_quality_review(self, content_result: Dict[str, Any]) -> Dict[str, Any]:
        """阶段四：质量评审阶段
        质量评审官对内容进行全面评审
        🆕 集成知识库：搜索质量标准和优秀章节范例
        """
        print(f"【{self.name}】启动质量评审官进行全面评审...")

        # 🆕 知识库增强：搜索质量标准和优秀章节范例
        quality_reference = ""
        if self.current_project_id:
            print(f"🔍 正在搜索知识库中的质量标准和范例...")
            # 搜索以前评审过的高质量章节
            quality_chapters = self._search_knowledge(
                query="高质量 评审 优秀",
                filter_type="chapter",
                k=1
            )
            
            if quality_chapters:
                quality_reference = "\n\n【知识库参考 - 优秀章节范例】\n"
                quality_reference += f"参考章节：{quality_chapters[0].page_content[:200]}...\n"
                quality_reference += "\n📊 请参照以上优秀章节的标准进行评审。\n"
                print(f"✓ 找到 1 个优秀章节范例")

        review_prompt = f"""请对以下内容进行全面质量评审：

【待评审内容】
{content_result.get('content', content_result.get('chapters', content_result))}

{quality_reference}

请从以下维度进行评审：
1. 逻辑一致性
2. 人物塑造
3. 文笔质量
4. 故事吸引力
5. 作者腔调一致性（如有定义）

并给出：
- 具体问题
- 改进建议
- 质量评分（1-10分）
- 是否需要修改

【输出格式要求 - 评审报告排版】
请使用以下Markdown格式输出，确保评审报告结构清晰：

## 📊 质量评审报告

### 一、总体评分
**综合评分**：X/10分

**评分说明**：（简要说明评分理由）

---

### 二、分项评估

#### 1. 逻辑一致性 ⭐⭐⭐⭐⭐
**评分**：X/10分

**优点**：
- （优点1）
- （优点2）

**问题**：
- （问题1）
- （问题2）

---

#### 2. 人物塑造 ⭐⭐⭐⭐⭐
**评分**：X/10分

**优点**：
- （优点1）
- （优点2）

**问题**：
- （问题1）
- （问题2）

---

#### 3. 文笔质量 ⭐⭐⭐⭐⭐
**评分**：X/10分

**优点**：
- （优点1）
- （优点2）

**问题**：
- （问题1）
- （问题2）

---

#### 4. 故事吸引力 ⭐⭐⭐⭐⭐
**评分**：X/10分

**优点**：
- （优点1）
- （优点2）

**问题**：
- （问题1）
- （问题2）

---

#### 5. 作者腔调一致性 ⭐⭐⭐⭐⭐
**评分**：X/10分

**评估**：（评估腔调一致性）

---

### 三、改进建议

#### 🔧 必须修改的问题
1. **问题描述**：（具体问题）
   - **建议**：（改进建议）
   - **优先级**：高

2. **问题描述**：（具体问题）
   - **建议**：（改进建议）
   - **优先级**：高

#### 💡 可选优化的建议
1. （建议1）
2. （建议2）

---

### 四、最终结论

**是否需要修改**：是 / 否

**修改重点**：
1. （重点1）
2. （重点2）

**预期效果**：（修改后的预期效果）

---

**格式规范**：
- 使用清晰的标题结构（##、###）
- 问题和建议使用编号列表
- 评分使用星级（⭐）或数字
- 重要信息使用**加粗**标记
- 各部分之间使用分隔线 `---`"""

        review_result = self.quality_reviewer.process(review_prompt, self.project_context)

        # 简单的评分判断
        needs_revision = "需要修改" in review_result or "问题" in review_result

        print(f"【{self.name}】阶段四完成：质量评审完成")

        return {
            "review": review_result,
            "needs_revision": needs_revision,
            "content": content_result
        }

    def _clean_final_output(self, content: str) -> str:
        """清理最终输出，移除额外的评审话语和说明文字
        
        Args:
            content: 原始输出内容
            
        Returns:
            清理后的章节内容（仅包含标题+正文）
        """
        import re
        
        # 移除常见的额外标题
        patterns_to_remove = [
            r'【迭代优化完成】.*?\n*',
            r'【优化要点说明】.*',
            r'【最终版本.*?】.*?\n*',
            r'【修改说明】.*',
            r'\*\*优化要点说明?\*\*.*',
            r'\n---\n+\*\*优化.*',
            r'\n\*\*\*\n+\*\*优化.*',
        ]
        
        cleaned = content
        for pattern in patterns_to_remove:
            cleaned = re.sub(pattern, '', cleaned, flags=re.DOTALL | re.MULTILINE)
        
        # 移除分隔线后的所有内容（通常是说明文字）
        # 匹配 --- 或 *** 后的内容
        if '---' in cleaned:
            parts = cleaned.split('---')
            # 只保留第一部分（章节正文）
            cleaned = parts[0]
        
        if '***' in cleaned and '优化' in cleaned:
            parts = cleaned.split('***')
            cleaned = parts[0]
        
        # 清理多余的空行（保留最多2个连续换行）
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        
        # 移除开头和结尾的空白
        cleaned = cleaned.strip()
        
        return cleaned

    def _stage_five_iteration_optimization(self, review_result: Dict[str, Any]) -> Dict[str, Any]:
        """阶段五：迭代优化循环
        根据评审反馈进行修改和优化
        """
        print(f"【{self.name}】启动迭代优化循环（第{self.iteration_count}次）...")

        # 🔥 关键修复：处理 review_result 可能是字典或字符串的情况
        if isinstance(review_result, str):
            # 如果是字符串，转换为字典格式
            print("⚠️  警告：review_result 是字符串类型，转换为字典")
            review_result = {
                "review": review_result,
                "needs_revision": True,
                "content": {}
            }
        
        # 获取原始章节内容
        original_content = ""
        if isinstance(review_result.get('content'), dict):
            original_content = review_result.get('content', {}).get('content', '')
        elif isinstance(review_result.get('content'), str):
            original_content = review_result.get('content', '')
        
        # 如果还是没有原始内容，尝试从 project_context 中获取
        if not original_content:
            # 尝试从 chapters 列表中获取最后一章
            if "chapters" in self.project_context and self.project_context["chapters"]:
                original_content = self.project_context["chapters"][-1]
                print(f"📝 从 project_context.chapters 获取原始内容")
        
        if not original_content:
            print("⚠️  警告：未找到原始章节内容，直接返回评审结果")
            return review_result
        
        print(f"📝 原始章节字数: {len(original_content)}")

        # 获取评审意见
        review_text = review_result.get('review', '') if isinstance(review_result, dict) else str(review_result)

        revision_prompt = f"""你是一位专业的编辑。请根据以下评审意见修改和优化章节内容：

【原始章节内容】
{original_content}

【评审意见】
{review_text}

请在保持原有内容和字数的前提下，根据评审意见进行优化修改。

【重要要求 - 格式规范】
请严格按照以下格式输出优化后的章节：

**第X章：章节标题**

章节正文内容...

格式要求：
1. 第一行必须是 Markdown 加粗格式的标题：**第X章：标题名称**
2. 章节编号使用阿拉伯数字（如1、2、3）
3. 标题后使用中文冒号：（不是英文冒号:）
4. 标题后空两行，然后是正文内容
5. 不要包含任何额外的说明文字、评审话语、优化要点说明等内容
6. 只输出：章节标题 + 章节正文内容
7. ❗ 特别注意：保持原有章节的字数长度，不要大幅缩减内容

【输出格式要求 - 章节内容排版】
请严格遵循以下排版规范，确保内容易于阅读：

**1. 段落格式**：
- 每个段落之间空一行
- 每段3-5句话为宜，避免单段过长
- 段落首行不缩进（或缩进两个全角空格，保持一致）

**2. 对话格式**：
- 对话前后各空一行
- 对话内容使用引号："对话内容"
- 对话标签简洁自然

示例：
林墨抬起头，看着眼前的陌生人。

"你是谁？"他警惕地问道。

陌生人微微一笑，没有回答。

**3. 场景转换**：
- 场景转换处空两行
- 可使用简短的过渡句

**4. 避免的问题**：
- ❌ 不要出现大段文字堆砌（超过10行不换段）
- ❌ 不要连续空行超过2行
- ❌ 不要在正文中添加说明性文字
- ❌ 不要使用 `\n\n` 等转义字符（直接换行）

【优化风格要求 - 去除AI痕迹】
在优化时请重点关注以下几点，使文本更加自然、真实：

1. 语言自然度：
   - 检查并修改过于机械化、程式化的表达
   - 增加语言的多样性和自然度
   - 删除冗余的描述和说明
   - 让文本更具人性化和真实感

2. 人物对话优化：
   - 确保人物对话符合其性格特点
   - 添加真实对话的特征（停顿、犹豫、口语化等）
   - 避免对话过于完美、信息密度过高
   - 通过对话展现人物的复杂性和矛盾

3. 情节真实性：
   - 检查情节是否过于顺利、完美
   - 适当保留或增加意外、阻碍等真实元素
   - 确保转折点自然而非生硬
   - 保持叙事节奏的张弛有度

4. 细节描写：
   - 增强五感描写（视觉、听觉、嗅觉、触觉、味觉）
   - 用具体细节替代抽象概括
   - 避免陈词滥调和套路化表述
   - 让场景更有画面感和沉浸感

示例格式：
**第1章：数据幽灵**


林墨左眼的神经接口泛着淡蓝色的微光，数据流在视网膜上快速滚动。

"又是一个普通的夜晚。"他自言自语道。

窗外的霓虹灯闪烁不定，将房间染成诡异的紫色。


（场景转换）


第二天清晨，林墨被一阵急促的敲门声惊醒。

**请确保输出内容格式规范、结构清晰、易于阅读！**"""

        revised_content = self.content_creator.process(revision_prompt, self.project_context)

        # 🔥 关键修复：清理输出内容，移除额外的评审话语
        revised_content = self._clean_final_output(revised_content)

        # 重新评审修改后的内容
        re_review_prompt = f"""请对修改后的内容进行评审：
修改后的内容: {revised_content}

请评估是否解决了之前的问题，并给出最终评分。"""

        final_review = self.quality_reviewer.process(re_review_prompt, self.project_context)

        print(f"【{self.name}】阶段五完成：迭代优化完成")

        return {
            "revised_content": revised_content,
            "final_review": final_review,
            "iteration": self.iteration_count
        }
    
    def get_project_context(self) -> Dict[str, Any]:
        """获取项目上下文"""
        return self.project_context
    
    def update_project_context(self, **kwargs):
        """更新项目上下文"""
        self.project_context.update(kwargs)
        print(f"【主编】项目上下文已更新")
    
    def get_workflow_log(self) -> List[Dict[str, Any]]:
        """获取工作流程日志"""
        return self.workflow_log
    
    def clear_kb_cache(self):
        """🚀 清除知识库缓存"""
        cache_count = len(self._kb_cache)
        self._kb_cache.clear()
        print(f"✅ 已清除 {cache_count} 条知识库缓存")
    
    def get_kb_cache_stats(self) -> Dict[str, Any]:
        """🚀 获取知识库缓存统计信息"""
        import time
        current_time = time.time()
        
        active_count = 0
        expired_count = 0
        
        for key, (_, cached_time) in self._kb_cache.items():
            if current_time - cached_time < self._cache_ttl:
                active_count += 1
            else:
                expired_count += 1
        
        return {
            "total_entries": len(self._kb_cache),
            "active_entries": active_count,
            "expired_entries": expired_count,
            "cache_ttl_seconds": self._cache_ttl,
            "max_cache_size": self._cache_max_size
        }
    
    def set_relevance_threshold(self, threshold: float):
        """🚀 设置相关性阈值
        
        Args:
            threshold: 相关性阈值（0.0-1.0），低于此值的结果会被过滤
        """
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("相关性阈值必须在 0.0-1.0 之间")
        
        old_threshold = self._relevance_threshold
        self._relevance_threshold = threshold
        print(f"✅ 相关性阈值已从 {old_threshold} 调整为 {threshold}")
        # 清除缓存以应用新阈值
        self.clear_kb_cache()
    
    def set_cache_ttl(self, ttl_seconds: int):
        """🚀 设置缓存生存时间
        
        Args:
            ttl_seconds: 缓存生存时间（秒）
        """
        if ttl_seconds <= 0:
            raise ValueError("缓存生存时间必须大于0")
        
        old_ttl = self._cache_ttl
        self._cache_ttl = ttl_seconds
        print(f"✅ 缓存生存时间已从 {old_ttl}秒 调整为 {ttl_seconds}秒")
    
    def enable_dynamic_k(self, enabled: bool = True):
        """🚀 启用/禁用动态k值
        
        Args:
            enabled: 是否启用动态k值
        """
        self._enable_dynamic_k = enabled
        status = "已启用" if enabled else "已禁用"
        print(f"✅ 动态k值 {status}")
    
    def _analyze_previous_chapters(self, chapters: List[str]) -> str:
        """🆕 分析已完成章节，提取关键信息用于新章节创作
        
        Args:
            chapters: 已完成的章节列表
            
        Returns:
            格式化的章节分析文本
        """
        if not chapters or len(chapters) == 0:
            return ""
        
        # 提取最近3章的摘要（避免prompt过长）
        recent_chapters = chapters[-3:] if len(chapters) > 3 else chapters
        
        analysis_parts = []
        analysis_parts.append("【已完成章节分析】")
        
        for i, chapter_content in enumerate(recent_chapters, 1):
            # 计算实际章节编号
            actual_chapter_num = len(chapters) - len(recent_chapters) + i
            
            # 提取章节摘要（前300字）
            summary = chapter_content[:300] if len(chapter_content) > 300 else chapter_content
            
            # 提取章节结尾（最后200字，用于衔接）
            ending = chapter_content[-200:] if len(chapter_content) > 200 else chapter_content
            
            analysis_parts.append(f"\n第{actual_chapter_num}章分析：")
            analysis_parts.append(f"- 开篇内容：{summary}...")
            analysis_parts.append(f"- 结尾内容：{ending}")
            
            # 简单的内容分析
            if "对话" in chapter_content or """ in chapter_content or """ in chapter_content:
                analysis_parts.append(f"- 特点：包含人物对话")
            if "场景" in chapter_content or "环境" in chapter_content:
                analysis_parts.append(f"- 特点：包含场景描写")
            if "心理" in chapter_content or "想到" in chapter_content or "觉得" in chapter_content:
                analysis_parts.append(f"- 特点：包含心理描写")
        
        # 添加连贯性提示
        analysis_parts.append("\n【内容连贯性要求】")
        analysis_parts.append("⚠️ 请确保新章节内容：")
        analysis_parts.append("1. 情节上与前面章节自然衔接，不出现跳跃或矛盾")
        analysis_parts.append("2. 人物性格、言行举止与前面章节保持一致")
        analysis_parts.append("3. 已提及的设定、规则、背景不能自相矛盾")
        analysis_parts.append("4. 叙事风格、文笔特点延续前面章节的特色")
        analysis_parts.append("5. 时间线、地点转换逻辑清晰合理")
        
        return "\n".join(analysis_parts)
    
    # ========== 🆕 章节生成专用方法 ==========
    
    def generate_chapter_plan(self, chapter_number: int, project_concept: str, 
                            plot_outline: str, world_setting: str, characters: str,
                            previous_chapters_summary: str, previous_ending: str) -> str:
        """生成章节规划
        
        Args:
            chapter_number: 章节编号
            project_concept: 整本书的故事概念
            plot_outline: 整本书的情节大纲
            world_setting: 世界观设定
            characters: 人物设定
            previous_chapters_summary: 已完成章节的摘要
            previous_ending: 前一章的结尾内容（用于衔接）
            
        Returns:
            章节规划内容
        """
        print(f"【{self.name}】为第{chapter_number}章制定创作计划...")
        
        # 构建章节规划提示词
        chapter_plan_prompt = f"""你是一位资深小说情节规划师。请为第{chapter_number}章制定创作计划。

【整本书信息】
- 故事概念：{project_concept}
- 情节大纲：{plot_outline}
- 世界观：{world_setting}
- 主要人物：{characters}

【已完成章节摘要】
{previous_chapters_summary if previous_chapters_summary else '（这是第一章）'}

【前一章结尾】
{previous_ending if previous_ending else '（这是第一章，没有前一章）'}

请为第{chapter_number}章制定创作计划，包括：
1. 本章核心事件（推进主线情节的关键事件）
2. 人物发展（角色成长或关系变化）
3. 情节承接（如何从上一章自然过渡）
4. 悬念设置（为下一章埋下伏笔）
5. 场景安排（时间、地点、氛围）

要求：
- 确保与整本书的情节大纲保持一致
- 确保与前面章节的剧情连贯
- 推进故事发展，不能原地踏步
- 提供具体、可执行的创作指导
"""
        
        # 使用创意总监生成章节规划
        chapter_plan = self.creative_director.process(chapter_plan_prompt, self.project_context)
        
        print(f"【{self.name}】第{chapter_number}章创作计划已完成")
        return chapter_plan
    
    def generate_chapter_content(self, chapter_number: int, chapter_plan: str, 
                               world_setting: str, characters: str, 
                               previous_ending: str, target_word_count: int = 3000,
                               previous_chapters: Optional[List[str]] = None) -> str:
        """生成章节内容（增强版 - 包含已生成章节分析）
        
        Args:
            chapter_number: 章节编号
            chapter_plan: 章节规划
            world_setting: 世界观设定
            characters: 人物设定
            previous_ending: 前一章的结尾内容（用于衔接）
            target_word_count: 目标字数
            previous_chapters: 已完成的章节列表（用于分析）
            
        Returns:
            章节内容
        """
        print(f"【{self.name}】启动内容创作师创作第{chapter_number}章...")
        
        # 🆕 分析已完成的章节
        chapters_analysis = ""
        if previous_chapters and len(previous_chapters) > 0:
            chapters_analysis = self._analyze_previous_chapters(previous_chapters)
            print(f"✅ 已分析 {len(previous_chapters)} 个已完成章节")
        
        # 🆕 构建增强版内容创作提示词
        content_creation_prompt = f"""你是一位经验丰富的小说作家。请根据以下信息创作第{chapter_number}章内容。

【章节规划】
{chapter_plan}

【整本书设定】
- 世界观：{world_setting}
- 人物：{characters}

【前一章结尾】
{previous_ending if previous_ending else '（这是第一章，请设计一个引人入胜的开场）'}

{chapters_analysis}

【创作要求】
1. 字数：{target_word_count}字左右
2. 承接上一章的剧情，自然过渡
3. 完成本章规划的核心事件
4. 塑造人物，推进关系发展
5. 文风保持一致，生动细腻
6. 设置悬念，吸引读者继续阅读
7. 使用场景描写、对话、心理描写等多种手法

【质量标准】
- ✅ 与前面章节的情节连贯一致
- ✅ 人物性格和行为符合已有描写
- ✅ 遵循已建立的世界观规则和设定
- ✅ 延续已有的叙事风格和文笔特点
- ✅ 推进主线情节，避免原地踏步
- ✅ 注重细节的合理性和真实感

请开始创作第{chapter_number}章内容：
"""
        
        # 使用内容创作者生成章节内容
        chapter_content = self.content_creator.process(content_creation_prompt, self.project_context)
        
        print(f"【{self.name}】第{chapter_number}章内容创作完成，字数：{len(chapter_content)}")
        return chapter_content
    


    def review_chapter(self, chapter_draft: str, chapter_plan: str, plot_outline: str) -> str:
        """评审章节内容

        Args:
            chapter_draft: 章节初稿
            chapter_plan: 章节规划
            plot_outline: 整本书的情节大纲

        Returns:
            评审报告
        """
        print(f"【{self.name}】启动质量评审官进行章节评审...")
        
        review_prompt = f"""请对以下章节内容进行全面质量评审：

【章节规划】
{chapter_plan}

【章节内容】
{chapter_draft}

【整本书情节大纲】
{plot_outline}

请评估：
1. 是否完成了章节规划的核心事件
2. 是否符合整本书的情节大纲
3. 逻辑一致性和连贯性
4. 人物塑造是否生动
5. 文笔质量和叙事节奏
6. 悬念设置是否有效

并给出：
- 优点（做得好的地方）
- 具体问题（需要改进的地方）
- 改进建议（如何修改）
- 质量评分（1-10分）
"""
        
        review_report = self.quality_reviewer.process(review_prompt, self.project_context)
        
        print(f"【{self.name}】章节评审完成")
        return review_report
    
    def optimize_chapter(self, chapter_draft: str, review_report: str) -> str:
        """优化章节内容
        
        Args:
            chapter_draft: 章节初稿
            review_report: 评审报告
            
        Returns:
            优化后的章节内容
        """
        print(f"【{self.name}】启动内容优化...")
        
        optimization_prompt = f"""根据以下评审意见，对章节内容进行优化和改进。

【章节初稿】
{chapter_draft}

【评审意见】
{review_report}

Please根据评审意见：
1. 修正指出的问题
2. 保留做得好的部分
3. 优化文笔和叙事节奏
4. 增强场景描写和人物塑造
5. 确保逻辑连贯性

【重要要求】
请直接输出优化后的章节内容，格式如下：

**第X章 章节标题**

章节正文内容...

不要包含任何额外的说明文字、评审话语、优化要点说明等内容。
只输出：章节标题 + 章节正文内容。
"""
        
        optimized_content = self.content_creator.process(optimization_prompt, self.project_context)
        
        # 🔥 关键修复：清理输出内容，移除额外的评审话语
        optimized_content = self._clean_final_output(optimized_content)
        
        print(f"【{self.name}】章节优化完成")
        return optimized_content

