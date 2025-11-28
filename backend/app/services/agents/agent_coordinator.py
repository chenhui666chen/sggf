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

        # 🆕 长篇创作配置：默认目标章节数
        self.target_chapter_count: int = 100
        self.project_context["target_chapter_count"] = self.target_chapter_count

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

    def set_longform_config(self, target_chapter_count: Optional[int] = None):
        """🆕 设置长篇创作相关配置（例如目标章节数）"""
        if target_chapter_count is None:
            return
        try:
            value = int(target_chapter_count)
        except (TypeError, ValueError):
            return
        if value <= 0:
            return
        self.target_chapter_count = value
        self.project_context["target_chapter_count"] = value
        print(f"🎯 已设置长篇目标章节数: {value}")


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
        concept_prompt = f"""你是一位资深网络小说创意总监。请严格基于用户的实际创作需求进行创作。

【核心原则】用户需求是唯一标准，必须100%遵循！

用户需求: {user_input}

请基于用户需求提供：
1. 故事核心冲突与一句话卖点
2. 题材类型与流派定位
3. 爽点设计（金手指、升级体系、打脸节奏）
4. 目标读者与阅读体验
5. 故事背景和设定方向

【网文题材分类参考】
请根据用户需求选择最匹配的题材流派：
- 玄幻：东方玄幻/异世大陆/王朝争霸/高武世界
- 仙侠：修真文明/幻想修仙/现代修真/神话修真
- 都市：都市异能/都市生活/职场商战/娱乐明星
- 科幻：星际文明/时空穿梭/进化变异/末世危机
- 历史：架空历史/秦汉三国/两晋隋唐/明清
- 游戏：虚拟网游/游戏异界/电子竞技
- 悬疑：推理侦探/恐怖惊悚/灵异神怪
- 特殊流派：系统流/无限流/穿越/重生/种田/宫斗

【关键要求】
- 题材类型：严格按照用户指定的题材
- 故事风格：必须符合用户描述的风格和氛围
- 爽点设计：明确金手指类型和升级节奏
- 独立创作：不参考任何已有作品设定

⚠️ 警告：绝对不允许改变用户指定的题材类型！

【输出格式要求】
请使用以下Markdown格式输出：

## 一句话卖点
（用一句话概括本书最大的吸引力，如："废材逆袭成为最强修仙者"）

## 题材与流派
- **主题材**：（如：玄幻-东方玄幻）
- **子流派**：（如：系统流/升级流/无敌流）
- **核心标签**：（3-5个关键词，如：逆袭、打脸、无敌、爽文）

## 爽点设计

### 金手指设定
- **类型**：（系统/空间/重生记忆/特殊血脉/神秘传承...）
- **核心能力**：（金手指提供的主要优势）
- **成长性**：（金手指如何随主角成长而升级）
- **限制条件**：（使用金手指的代价或限制，增加合理性）

### 升级体系
- **境界划分**：（列出3-5个主要境界层次）
- **升级节奏**：（预计每多少章突破一次）
- **升级爽点**：（突破时的爽感来源，如：实力碾压、打脸嘲讽者）

### 打脸节奏规划
| 阶段 | 打脸对象类型 | 打脸方式 | 预计章节 |
|------|-------------|---------|---------|
| 开局 | 欺凌者/小人 | 实力反杀 | 第3-5章 |
| 初期 | 家族敌对势力 | 比武碾压 | 第15-20章 |
| 中期 | 天才/高手 | 越级挑战 | 第40-50章 |

## 故事核心冲突
（描述核心冲突，2-3段）

## 目标读者
- **年龄段**：
- **阅读偏好**：
- **期待的爽感**：

## 故事背景和设定方向
（描述背景设定，3-5段）

## 差异化卖点
- **与同类作品的区别**：（本书的独特之处）
- **创新点**：（在套路中的创新）

**格式规范**：
- 使用Markdown标题层级（##、###）
- 表格格式清晰
- 重要信息使用**加粗**标记"""

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
        character_prompt = f"""基于以下故事概念，设计完整的人物体系。

【故事概念】
{concept}

【任务说明】
1. 结合故事概念，设计主角、对手、支持角色和中立角色，构成一个适合长篇小说的完整人物阵容，总人数不少于 15-20 人。
2. 每个角色需包含：姓名、年龄/性别、角色定位、性格特点、在情节中的作用、与主要角色的关系；鼓励补充背景故事、核心动机和弱点/缺陷等信息，以便后续深入刻画。
3. 按阵营分类输出人物列表，并合理分配：主角阵营 3-5 人，对手阵营 2-4 人，支持角色和中立角色合计 8-12 人。

【输出格式要求】
请严格使用以下 Markdown 结构化格式输出，确保与后续“人物扩展”功能兼容：

## 主角阵营

### 【姓名】：林墨
【年龄/性别】：28岁/男
【角色定位】：主角
【性格特点】：...
【在情节中的作用】：...
【与主要角色的关系】：...

## 对手阵营

### 【姓名】：陈朔
【年龄/性别】：35岁/男
【角色定位】：主要对手
【性格特点】：...
【在情节中的作用】：...
【与主要角色的关系】：...

## 支持角色

### 【姓名】：老周
【年龄/性别】：50岁/男
【角色定位】：支持角色
【性格特点】：...
【在情节中的作用】：...
【与主要角色的关系】：...

## 中立角色

### 【姓名】：张伟
【年龄/性别】：32岁/男
【角色定位】：中立角色
【性格特点】：...
【在情节中的作用】：...
【与主要角色的关系】：...

请只输出以上结构化人物设定内容，不要添加额外的解释性文字。"""
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

        # 🆕 确定长篇目标章节数（默认100章，可通过 set_longform_config 动态调整）
        target_chapters = getattr(self, "target_chapter_count", 100)
        try:
            target_chapters = int(target_chapters)
        except (TypeError, ValueError):
            target_chapters = 100
        if target_chapters <= 0:
            target_chapters = 100
        # 保持成员属性与上下文一致
        self.target_chapter_count = target_chapters
        self.project_context["target_chapter_count"] = target_chapters

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

        # 🆕 计算卷数和每卷章节数（网文通常每卷20-30章）
        chapters_per_volume = 25  # 每卷约25章
        volume_count = max(2, (target_chapters + chapters_per_volume - 1) // chapters_per_volume)

        plot_prompt = f"""基于以下故事设定，设计**适合约{target_chapters}章长篇网络小说**的完整情节结构：

【世界观设定】
{concept_result['world_setting']}

【人物设定】
{concept_result['characters']}

{structure_reference}

【网文结构设计原则】
⚠️ 网络小说不同于传统文学，需要特别注意：
1. **卷结构**：按"卷"划分，每卷有独立的小高潮和阶段性目标
2. **爽点密度**：每3-5章必须有一个爽点（打脸/升级/获得/反转）
3. **钩子设计**：每章结尾必须有悬念，让读者想点下一章
4. **节奏控制**：紧张-舒缓交替，避免长时间铺垫
5. **金手指展示**：定期展示主角的优势，给读者爽感

【长篇篇幅硬性要求】
- 本书规划为**约{target_chapters}章**，分为**{volume_count}卷**
- 每卷约{chapters_per_volume}章，有独立的阶段性高潮
- 各卷章节数可灵活调整，但总数应接近{target_chapters}章

请按以下格式输出：

## 一、卷结构规划（共{volume_count}卷）

按以下模板为每一卷填写：

### 第一卷：（卷名，如"初入江湖"）
**章节范围**：第1-{chapters_per_volume}章
**阶段目标**：（本卷主角的核心目标）
**核心冲突**：（本卷的主要矛盾）
**卷末高潮**：（本卷结尾的高潮事件）
**爽点设计**：
- 第X章：（爽点1，如"首次展示金手指"）
- 第Y章：（爽点2，如"打脸嘲讽者"）
- 第Z章：（爽点3，如"阶段性突破"）

### 第二卷：（卷名）
...（同上格式，继续规划后续各卷）

---

## 二、章节钩子规划表

为关键章节设计结尾钩子，确保读者追更：

| 章节 | 章节概要 | 结尾钩子类型 | 钩子内容 |
|------|----------|-------------|----------|
| 第1章 | （概要） | 悬念式 | （如：神秘人物出现） |
| 第3章 | （概要） | 危机式 | （如：主角陷入危机） |
| 第5章 | （概要） | 反转式 | （如：敌人竟是亲人） |
| ...  | ... | ... | ... |

钩子类型：悬念式/危机式/反转式/升级式/对决式

---

## 三、爽点节奏表

| 章节 | 爽点类型 | 爽点描述 | 爽感强度 |
|------|----------|----------|----------|
| 第3章 | 首秀 | 主角首次展示能力 | ⭐⭐ |
| 第8章 | 打脸 | 回击嘲讽者 | ⭐⭐⭐ |
| 第15章 | 升级 | 第一次境界突破 | ⭐⭐⭐⭐ |
| 第{chapters_per_volume}章 | 卷末大爽 | 击败本卷Boss | ⭐⭐⭐⭐⭐ |

爽点类型：打脸/升级/获得宝物/装逼成功/反转翻盘/美人倾心/万众瞩目

---

## 四、情节线索总览

| 情节线 | 类型 | 章节跨度 | 核心冲突 | 悬念/伏笔 |
|--------|------|----------|----------|-----------|
| 主线 | 主线 | 第1-{target_chapters}章 | （终极目标） | （贯穿悬念） |
| 支线1 | 支线 | 第X-Y章 | （冲突） | （伏笔） |
| 支线2 | 支线 | 第X-Y章 | （冲突） | （伏笔） |

---

## 五、关键转折点

| 转折点 | 章节 | 类型 | 描述 | 对主角的影响 |
|--------|------|------|------|-------------|
| 转折1 | 第X章 | 剧情反转 | （描述） | （影响） |
| 转折2 | 第Y章 | 身份揭秘 | （描述） | （影响） |
| 转折3 | 第Z章 | 关系转变 | （描述） | （影响） |

---

**格式规范**：
- 使用Markdown标题层级（##、###）
- 章节之间使用分隔线 `---`
- 表格格式清晰对齐
- 重要信息使用**加粗**标记"""

        plot_result = self.plot_architect.process(plot_prompt, self.project_context)
        self.project_context["plot_outline"] = plot_result

        # 📝 注意：自动大纲扩展已移除
        # 大纲扩展功能仍然可用，但需要用户通过前端按钮或 API 手动触发
        # 调用端点：POST /api/v1/workflow/expand-outline
        # 这样可以显著加快项目创建速度，提升用户体验
        print(f"ℹ️ 项目创建完成。如需扩展大纲至更多章节，请手动调用大纲扩展功能。")

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

        # 🆕 章节开头/结尾方式定义
        opening_styles = {
            "对话开头": ("对话开头", "直接进入冲突或紧张场景", ""站住！"身后传来一声厉喝。"),
            "动作开头": ("动作开头", "正在发生的动态事件", "刀光闪过，血珠在空中划出一道弧线。"),
            "悬念开头": ("悬念开头", "抛出问题，引发好奇", "三天后回想起这个决定时，她依然后悔不已。"),
            "场景开头": ("场景开头", "氛围渲染，快速建立情境", "暴雨倾盆，整个长安城笼罩在一片灰蒙蒙的水雾中。"),
            "反转开头": ("反转开头", "与上章结尾形成对比或反差", "然而他睁开眼时，发现自己躺在一张软榻上。"),
        }
        ending_styles = {
            "悬念式": ("悬念式", "关键信息揭露一半", "信封里只有一张纸，上面写着三个字——"),
            "转折式": ("转折式", "意外事件发生", "就在她以为一切结束时，门外响起了敲门声。来人是——"),
            "动作中断式": ("动作中断式", "危机时刻戛然而止", "刀锋距离她的咽喉只有一寸。她闭上眼睛——"),
            "信息炸弹式": ("信息炸弹式", "惊人真相揭露", ""你以为我是谁？"他摘下面具，露出一张与她父亲一模一样的脸。"),
            "选择困境式": ("选择困境式", "主角面临艰难抉择", "救左边的师父，还是右边的爱人？她只有三秒钟做出决定。"),
        }

        # 🆕 情节类型 → 推荐的开头/结尾方式（关键词规则匹配）
        scene_style_rules = {
            # 战斗/打斗场景
            "战斗": {"keywords": ["战斗", "打斗", "厮杀", "对决", "交手", "出招", "攻击", "防御", "刀剑", "拳脚"],
                    "opening": "动作开头", "ending": "动作中断式"},
            # 悬疑/推理场景
            "悬疑": {"keywords": ["悬疑", "推理", "谜团", "线索", "真相", "秘密", "调查", "疑点", "隐情", "身世"],
                    "opening": "悬念开头", "ending": "悬念式"},
            # 重大转折/揭秘
            "转折": {"keywords": ["转折", "揭秘", "真相大白", "身份", "背叛", "反转", "意外", "惊人", "原来", "竟然"],
                    "opening": "反转开头", "ending": "信息炸弹式"},
            # 情感/告别场景
            "情感": {"keywords": ["告别", "离别", "重逢", "表白", "感情", "思念", "回忆", "温情", "感动", "眼泪"],
                    "opening": "场景开头", "ending": "选择困境式"},
            # 危机/紧张场景
            "危机": {"keywords": ["危机", "危险", "生死", "逃亡", "追杀", "困境", "绝境", "险境", "紧急", "千钧一发"],
                    "opening": "动作开头", "ending": "动作中断式"},
            # 对话/谈判场景
            "对话": {"keywords": ["谈判", "对话", "交涉", "质问", "争执", "辩论", "说服", "威胁", "警告", "摊牌"],
                    "opening": "对话开头", "ending": "转折式"},
            # 日常/过渡场景
            "日常": {"keywords": ["日常", "休息", "准备", "旅途", "修炼", "学习", "训练", "恢复", "整顿", "计划"],
                    "opening": "场景开头", "ending": "悬念式"},
            # 升级/获得场景（网文爽点）
            "升级": {"keywords": ["突破", "升级", "进阶", "觉醒", "获得", "传承", "机缘", "宝物", "功法", "神通"],
                    "opening": "悬念开头", "ending": "信息炸弹式"},
        }

        # 🆕 分析章节大纲，匹配情节类型
        plot_outline = structure_result.get('plot_outline', '')
        matched_scene_type = None
        max_keyword_count = 0

        for scene_type, rule in scene_style_rules.items():
            keyword_count = sum(1 for kw in rule["keywords"] if kw in plot_outline)
            if keyword_count > max_keyword_count:
                max_keyword_count = keyword_count
                matched_scene_type = scene_type

        # 🆕 根据匹配结果选择开头/结尾方式
        if matched_scene_type and max_keyword_count >= 1:
            rule = scene_style_rules[matched_scene_type]
            selected_opening = opening_styles[rule["opening"]]
            selected_ending = ending_styles[rule["ending"]]
            match_method = f"关键词匹配({matched_scene_type}场景, 命中{max_keyword_count}个关键词)"
        else:
            # 回退到章节编号轮换
            opening_list = list(opening_styles.values())
            ending_list = list(ending_styles.values())
            opening_index = (current_chapter_number - 1) % len(opening_list)
            ending_index = (current_chapter_number + 2) % len(ending_list)
            selected_opening = opening_list[opening_index]
            selected_ending = ending_list[ending_index]
            match_method = "章节编号轮换(未匹配到关键词)"

        print(f"📝 第{current_chapter_number}章 - 开头: {selected_opening[0]}, 结尾: {selected_ending[0]} [{match_method}]")

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

【本章开头方式 - 强制要求】
⚠️ 本章必须使用【{selected_opening[0]}】方式开头！
- 技巧说明：{selected_opening[1]}
- 参考示例：{selected_opening[2]}

❌ 禁止使用：每章都用"XXX醒来/睁开眼睛/阳光照进房间"开头

【本章结尾方式 - 强制要求】
⚠️ 本章必须使用【{selected_ending[0]}】结尾！
- 技巧说明：{selected_ending[1]}
- 参考示例：{selected_ending[2]}

❌ 禁止使用：总结式内心独白 + 对未来的展望（如"她知道，从这一刻起..."）
✅ 结尾要制造钩子，让读者想点下一章

【创作风格要求 - 去除AI痕迹】
在创作时请特别注意以下几点，使文本更加自然、真实：

1. 语言表达：
   - 避免程式化、模板化的表达
   - 增加语言多样性，减少重复句式
   - 用具体细节替代抽象概括

2. 人物对话：
   - 对话要符合人物性格，有人情味
   - 添加停顿、犹豫等真实对话特征
   - 通过对话展现人物的矛盾和复杂性

3. 情节节奏：
   - 每章应有1-2个小高潮点
   - 紧张-舒缓-紧张的节奏波动
   - 对话与叙述穿插，对话占比建议30-50%

4. 场景描写：
   - 运用五感描写增强沉浸感
   - 避免陈词滥调和套路化表述

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
        🆕 增加内容一致性检查：确保长篇小说前后内容不矛盾
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

        # 🆕 获取一致性检查所需的参考信息
        consistency_reference = ""
        chapters_list = self.project_context.get("chapters", [])
        current_chapter_num = len(chapters_list)

        if current_chapter_num > 0:
            # 提取世界观和人物设定的关键信息
            world_setting = self.project_context.get('world_setting', '')
            characters = self.project_context.get('characters', '')

            # 获取最近3章的摘要（用于检查连贯性）
            recent_chapters_summary = ""
            recent_count = min(3, len(chapters_list) - 1)  # 不包括当前章
            if recent_count > 0:
                recent_chapters_summary = "\n【最近章节摘要】\n"
                for i in range(recent_count):
                    idx = len(chapters_list) - 1 - recent_count + i
                    if idx >= 0:
                        chapter_content = chapters_list[idx] if isinstance(chapters_list[idx], str) else str(chapters_list[idx])
                        # 提取前200字作为摘要
                        summary = chapter_content[:200].replace('\n', ' ')
                        recent_chapters_summary += f"第{idx + 1}章摘要：{summary}...\n"

            consistency_reference = f"""
【一致性检查参考信息】

【核心设定摘要】
- 世界观关键词：{world_setting[:300] if isinstance(world_setting, str) else str(world_setting)[:300]}...
- 人物设定关键词：{characters[:300] if isinstance(characters, str) else str(characters)[:300]}...
{recent_chapters_summary}

⚠️ 请特别注意检查本章是否与以上设定和前文存在矛盾！
"""
            print(f"📋 已加载一致性检查参考（当前第{current_chapter_num}章）")

        review_prompt = f"""你是一位资深网络小说编辑。请对以下章节内容进行专业评审。

【待评审内容】
{content_result.get('content', content_result.get('chapters', content_result))}

{quality_reference}
{consistency_reference}

【网文评审维度】
请从以下6个维度进行评审，前5个是网文核心要素，第6个是长篇小说必须检查的一致性：

## 1. 爽点效果（权重25%）
- 本章是否有明确的爽点（打脸、升级、获得、反转等）？
- 爽点设计是否有足够的铺垫和释放？
- 读者情绪曲线是否有高潮？
- 爽感是否足够强烈？

## 2. 节奏把控（权重20%）
- 是否有拖沓、注水、废话连篇？
- 紧张与舒缓是否平衡？
- 信息密度是否适中（不过载也不空洞）？
- 场景转换是否流畅？

## 3. 钩子效果（权重15%）
- 章节开头是否吸引人？
- 章节结尾是否有悬念/钩子？
- 读者是否有"想点下一章"的冲动？
- 伏笔铺设是否自然？

## 4. 代入感（权重15%）
- 主角视角是否清晰？
- 读者能否代入主角的处境和情感？
- 配角是否有存在感而不抢戏？
- 情感共鸣是否充分？

## 5. 文笔流畅度（权重10%）
- 是否有明显的AI痕迹或机械感？
- 对话是否自然、符合人物性格？
- 是否有病句、重复、啰嗦？
- 描写是否生动有画面感？

## 6. 内容一致性（权重15%）⚠️ 长篇必查
- 人物设定是否与前文一致（性格、能力、外貌、背景）？
- 世界观规则是否与前文一致（修炼体系、社会规则等）？
- 时间线是否合理（事件发生顺序、时间间隔）？
- 道具/物品是否与前文一致（已获得/已使用的物品）？
- 人物关系是否与前文一致（敌友关系、称呼方式）？
- 如发现矛盾，必须明确指出具体位置和修正建议！

【输出格式】
请使用以下简洁格式输出评审报告：

## 📊 网文质量评审报告

**综合评分**：X/10分

---

### 分项评分

| 维度 | 评分 | 一句话点评 |
|------|------|-----------|
| 爽点效果 | X/10 | （点评） |
| 节奏把控 | X/10 | （点评） |
| 钩子效果 | X/10 | （点评） |
| 代入感 | X/10 | （点评） |
| 文笔流畅度 | X/10 | （点评） |
| 内容一致性 | X/10 | （点评，如有矛盾必须说明） |

---

### ⚠️ 一致性问题（如有）

如发现与前文/设定矛盾的内容，请在此列出：
1. **矛盾点**：（具体描述矛盾内容）
   **前文/设定**：（前文怎么写的）
   **本章内容**：（本章怎么写的）
   **修正建议**：（如何修改）

（如无一致性问题，可写"未发现明显矛盾"）

---

### 🔧 必须修改（影响阅读体验的硬伤）

1. **问题**：（具体描述）
   **修改建议**：（可操作的具体建议）
   **位置**：（指出问题所在的段落或对话）

2. ...

---

### 💡 建议优化（锦上添花）

1. （建议内容）
2. ...

---

### 最终结论

**是否需要修改**：是 / 否
**修改优先级**：高 / 中 / 低
**一句话总结**：（对本章的整体评价）"""

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

        # 原始文本副本，用于安全回退
        original_text = content or ""

        # 1. 精准移除常见的额外标题/说明块
        patterns_to_remove = [
            r'【迭代优化完成】.*?\n*',
            r'【优化要点说明】.*',
            r'【最终版本.*?】.*?\n*',
            r'【修改说明】.*',
            r'\*\*优化要点说明?\*\*.*',
            r'\n---\n+\*\*优化.*',
            r'\n\*\*\*\n+\*\*优化.*',
        ]

        cleaned = original_text
        for pattern in patterns_to_remove:
            cleaned = re.sub(pattern, '', cleaned, flags=re.DOTALL | re.MULTILINE)

        # 2. 清理多余的空行（保留最多2个连续换行）
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

        # 3. 移除开头和结尾的空白
        cleaned = cleaned.strip()

        # 4. 安全保护：如果清理后内容明显变短，则回退到原始内容，避免误删正文
        try:
            original_len = len(original_text)
            cleaned_len = len(cleaned)
        except Exception:
            return cleaned

        if original_len > 0 and cleaned_len > 0 and cleaned_len < original_len * 0.6:
            print(
                f"⚠️ _clean_final_output 清理后长度({cleaned_len}) 远小于原始长度({original_len})，疑似误删正文，已回退为原始内容"
            )
            return original_text.strip()

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
            print("⚠️  警告：未找到原始章节内容，返回空的 revised_content")
            # 🔥 关键修复：即使没有原始内容，也要返回正确的字典结构
            return {
                "revised_content": "",
                "final_review": review_result.get("review", "无法获取原始内容进行优化"),
                "iteration": self.iteration_count
            }

        print(f"📝 原始章节字数: {len(original_content)}")

        # 获取评审意见
        review_text = review_result.get('review', '') if isinstance(review_result, dict) else str(review_result)

        # 🔥 关键修复：根据原始内容长度决定优化策略
        original_length = len(original_content)
        is_short_outline = original_length < 500  # 少于500字视为简短大纲

        if is_short_outline:
            # 简短大纲模式：鼓励创造性扩展
            print(f"📝 检测到简短大纲（{original_length}字），启用创造性扩展模式")
            expansion_instruction = f"""
【创作模式】创造性扩展
由于原始内容是一个简短的大纲/提纲，请基于这个框架进行创造性发挥：

1. **大幅扩展内容**：将大纲扩展为完整的章节，目标字数 2000-3000 字
2. **丰富细节描写**：添加场景、环境、人物外貌、动作、表情等细节
3. **创造对话内容**：根据情节需要创造生动的人物对话
4. **发挥想象力**：在保持核心情节的前提下，自由发挥创意
5. **每次生成不同版本**：即使是相同的大纲，也请用不同的细节、对话、描写来呈现
6. **避免重复模式**：不要使用固定的开头套路，每次尝试新的切入角度

⚠️ 重要：这是一个需要你发挥创意的任务！请大胆创作，不要拘泥于原始大纲的字数。
"""
        else:
            # 正常优化模式：保持原有内容结构
            print(f"📝 检测到完整章节（{original_length}字），启用优化润色模式")
            expansion_instruction = """
【创作模式】优化润色
请在保持原有内容框架的前提下，根据评审意见进行优化修改：

1. 保持原有的故事情节和结构
2. 优化语言表达，使文笔更加流畅
3. 增强细节描写，但不改变主要情节
4. 修正评审中指出的问题
"""

        revision_prompt = f"""你是一位专业的编辑和创作者。请根据以下评审意见优化章节内容。

【原始章节内容】
{original_content}

【评审意见】
{review_text}

{expansion_instruction}

【输出格式要求】
1. 第一行：**第X章：章节标题**（Markdown加粗格式）
2. 标题后空两行，然后是正文内容
3. 段落之间空一行
4. 对话使用引号："对话内容"
5. 场景转换处空两行
6. 只输出章节标题和正文，不要包含任何说明文字

【文风要求】
- 语言自然流畅，避免机械化表达
- 人物对话符合性格特点
- 细节描写生动，有画面感
- 叙事节奏张弛有度

请开始创作："""

        # 🔥 关键修复：根据内容长度使用不同的 temperature
        # 简短大纲需要更高的创造性（temperature=0.9）
        # 完整章节只需要优化润色（temperature=0.7）
        creative_temperature = 0.9 if is_short_outline else 0.7

        revised_content = self.content_creator.process(
            revision_prompt,
            self.project_context,
            temperature=creative_temperature
        )

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

    def _analyze_previous_chapters(self, chapters: List[Any]) -> str:
        """🆕 分析已完成章节，提取关键信息用于新章节创作

        Args:
            chapters: 已完成的章节列表，可以是纯正文字符串，
                      或包含 chapter_number/title/content/summary 的字典

        Returns:
            格式化的章节分析文本（以高层摘要为主，避免复制整段开头原文）
        """
        if not chapters:
            return ""

        # 仅分析最近 3 章，避免 prompt 过长
        recent_chapters = chapters[-3:] if len(chapters) > 3 else chapters

        analysis_parts: List[str] = []
        analysis_parts.append("【已完成章节分析（高层摘要）】")

        for i, chapter_item in enumerate(recent_chapters, 1):
            # 计算实际章节编号
            actual_chapter_num = len(chapters) - len(recent_chapters) + i

            # 兼容不同输入形式：字符串 or 字典
            chapter_number = actual_chapter_num
            title = ""
            content = ""
            summary_text = ""

            if isinstance(chapter_item, dict):
                chapter_number = chapter_item.get("chapter_number", actual_chapter_num)
                title = (chapter_item.get("title") or "").strip()
                content = (chapter_item.get("content") or "").strip()
                summary_text = (chapter_item.get("summary") or "").strip()
            else:
                content = str(chapter_item or "").strip()

            # 若没有显式摘要，则退化为从正文中提取一段“概要式片段”
            # 注意这里不再强调“开篇内容”，而是作为事件概括使用，降低开头模板化风险
            if summary_text:
                core_summary = summary_text
            else:
                if not content:
                    core_summary = ""
                elif len(content) <= 300:
                    core_summary = content
                else:
                    # 取中间偏后的片段，避免总是重复章节首句
                    start_idx = len(content) // 4
                    end_idx = min(start_idx + 300, len(content))
                    core_summary = content[start_idx:end_idx]

            # 提取章节结尾（最后 200 字，用于衔接）
            ending = ""
            if content:
                ending = content[-200:] if len(content) > 200 else content

            header = f"\n第{chapter_number}章分析："
            if title:
                header += f"《{title}》"
            analysis_parts.append(header)

            if core_summary:
                analysis_parts.append(f"- 核心摘要：{core_summary}...")

            if ending:
                analysis_parts.append(f"- 结尾关键场景：{ending}")

            # 简单的内容特征分析（对话 / 场景 / 心理描写）
            if any(mark in content for mark in ["“", "”", "\""]):
                analysis_parts.append("- 特点：包含人物对话")
            if any(word in content for word in ["场景", "环境", "街道", "房间", "天空"]):
                analysis_parts.append("- 特点：包含场景描写")
            if any(word in content for word in ["心理", "想到", "觉得", "心里", "内心"]):
                analysis_parts.append("- 特点：包含心理描写")

        # 添加连贯性提示
        analysis_parts.append("\n【内容连贯性要求】")
        analysis_parts.append("⚠️ 请确保新章节内容：")
        analysis_parts.append("1. 情节上与前面章节自然衔接，不出现跳跃或矛盾")
        analysis_parts.append("2. 人物性格、言行举止与前面章节保持一致")
        analysis_parts.append("3. 已提及的设定、规则、背景不能自相矛盾")
        analysis_parts.append("4. 叙事风格、文笔特点延续前面章节的特色，但开头段落的具体句式应有所变化")
        analysis_parts.append("5. 时间线、地点转换逻辑清晰合理")

        return "\n".join(analysis_parts)

    # 🆕 开头防重复相关工具方法
    def _get_opening_prefix(self, text: str, length: int = 80) -> str:
        """提取用于比较的开头片段，去掉换行和多余空白。"""
        if not text:
            return ""
        prefix = text.strip().replace("\r", "").replace("\n", "")
        return prefix[:length]

    def _rewrite_opening_to_avoid_repetition(
        self,
        chapter_number: int,
        chapter_content: str,
        similar_openings: List[str],
    ) -> str:
        """当开头与前几章过于相似时，请求模型只重写开头 1–2 段。"""
        if not chapter_content or not similar_openings:
            return chapter_content

        examples = "\n".join(
            f"示例{i}：{opening[:120]}" for i, opening in enumerate(similar_openings, 1)
        )

        prompt = f"""你是一位专业小说作者。下面是第{chapter_number}章当前的完整内容，
以及前几章的开头片段。当前章节的开头和前几章过于相似，请在保持
时间线、地点和剧情连续性的前提下，只改写本章的开头 1-2 个自然段，
让开场方式更有变化，避免与前几章在句式和用语上高度重复。

【前几章开头示例】
{examples}

【当前第{chapter_number}章全文】
{chapter_content}

【改写要求】
1. 只改写开头 1-2 个自然段，其余内容尽量保持不变；
2. 可以更换时间切入点、视角、动作描写方式等，但不要改变已经发生的事件与信息；
3. 不要直接重复前几章的首句或明显相同的比喻/意象；
4. 输出完整修改后的第{chapter_number}章（标题 + 正文），不要输出任何说明文字。

请给出修改后的完整章节内容：
"""
        revised = self.content_creator.process(prompt, self.project_context)
        revised = self._clean_final_output(revised)
        return revised or chapter_content


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
                               previous_chapters: Optional[List[Any]] = None) -> str:
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

        # 🆕 防重复：检查开头是否与最近章节过于相似
        if previous_chapters and len(previous_chapters) > 0 and chapter_content:
            current_prefix = self._get_opening_prefix(chapter_content, length=80)
            recent_chapters = previous_chapters[-3:] if len(previous_chapters) > 3 else previous_chapters

            # 兼容 previous_chapters 既可能是正文字符串列表，也可能是包含 content 的字典列表
            previous_prefixes: List[str] = []
            for item in recent_chapters:
                if not item:
                    continue
                if isinstance(item, dict):
                    prev_text = (item.get("content") or "").strip()
                else:
                    prev_text = str(item or "").strip()
                if prev_text:
                    previous_prefixes.append(self._get_opening_prefix(prev_text, length=80))

            similar_openings = []
            for prev_prefix in previous_prefixes:
                if not prev_prefix:
                    continue
                max_len = min(len(current_prefix), len(prev_prefix))
                common_len = 0
                for i in range(max_len):
                    if current_prefix[i] == prev_prefix[i]:
                        common_len += 1
                    else:
                        break
                if common_len >= 25:  # 至少 25 个字符完全相同，视为开头高度重复
                    similar_openings.append(prev_prefix)

            if similar_openings:
                print(
                    f"⚠️ 第{chapter_number}章开头与前几章过于相似，匹配到 {len(similar_openings)} 个相似开头，尝试改写开头。"
                )
                chapter_content = self._rewrite_opening_to_avoid_repetition(
                    chapter_number, chapter_content, similar_openings
                )

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

请根据评审意见：
1. 修正指出的问题
2. 保留做得好的部分
3. 优化文笔和叙事节奏
4. 增强场景描写和人物塑造
5. 确保逻辑连贯性
6. 在不删除重要情节、不丢失关键信息的前提下进行润色，而不是改写成摘要

【重要要求】
- 优化后的章节应完整保留原有情节发展，除非原文存在明显冗余，否则篇幅不应少于章节初稿字数的 80%；
- 不要将长篇内容压缩成简要梗概或概述；
- 这是“编辑”和“润色”任务，而不是“总结”任务。

请直接输出优化后的章节内容，格式如下：

**第X章 章节标题**

章节正文内容...

不要包含任何额外的说明文字、评审话语、优化要点说明等内容。
只输出：章节标题 + 章节正文内容。
"""

        optimized_content = self.content_creator.process(optimization_prompt, self.project_context)

        # 🔥 关键修复：清理输出内容，移除额外的评审话语
        optimized_content = self._clean_final_output(optimized_content)

        # 🔒 安全保护：如果优化后字数远小于原稿，则认为可能被压缩成摘要，回退为原始章节内容
        original_len = len(chapter_draft or "")
        optimized_len = len(optimized_content or "")
        if original_len >= 500 and optimized_len > 0 and optimized_len < original_len * 0.6:
            print(
                f"⚠️ 优化后长度({optimized_len}) 远小于原稿({original_len})，疑似被压缩为摘要，本次将保留原始章节内容"
            )
            optimized_content = chapter_draft

        print(f"【{self.name}】章节优化完成")
        return optimized_content

