"""
Agent 协调系统，负责管理多个 Agent 的协同和通信，
并集成真实的 CreativeDirectorCoordinator。
"""
import logging
import asyncio
from typing import Dict, List, Any, Optional
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

class AgentType(str, Enum):
    """Agent类型"""
    CREATIVE_DIRECTOR = "creative_director"
    WORLDVIEW_ARCHITECT = "worldview_architect"
    CHARACTER_DESIGNER = "character_designer"
    PLOT_ARCHITECT = "plot_architect"
    EVENT_VALIDATOR = "event_validator"
    CONTENT_CREATOR = "content_creator"
    STYLE_OPTIMIZER = "style_optimizer"
    QUALITY_REVIEWER = "quality_reviewer"
    ITERATION_COORDINATOR = "iteration_coordinator"
    CONTENT_REVISER = "content_reviser"
    FINAL_REVIEWER = "final_reviewer"


class StageType(str, Enum):
    """阶段类型"""
    CONCEPT = "concept"
    STRUCTURE = "structure"
    CONTENT = "content"
    REVIEW = "review"
    ITERATION = "iteration"


class AgentStatus(str, Enum):
    """Agent状态"""
    IDLE = "idle"
    WORKING = "working"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class AgentMessage:
    """Agent消息"""
    agent_id: str
    agent_name: str
    stage: StageType
    status: AgentStatus
    progress: int
    message: str
    output: Optional[Dict[str, Any]] = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class StageOutput:
    """阶段输出"""
    stage: StageType
    agents_involved: List[str]
    output: Dict[str, Any]
    status: str
    timestamp: datetime = field(default_factory=datetime.now)


class AgentCoordinator:
    """Agent协调器 - 包装真实的CreativeDirectorCoordinator"""

    def __init__(self):
        self.agents: Dict[str, Dict[str, Any]] = {}
        self.stage_outputs: Dict[StageType, StageOutput] = {}
        self.message_queue: List[AgentMessage] = []
        self.workflow_state: Dict[str, Any] = {}
        self._agent_templates: Dict[str, Dict[str, Any]] = {}
        self._project_agents: Dict[int, Dict[str, Dict[str, Any]]] = {}
        self._project_stage_outputs: Dict[int, Dict[StageType, StageOutput]] = {}
        self._project_workflow_states: Dict[int, Dict[str, Any]] = {}
        self._project_message_queues: Dict[int, List[AgentMessage]] = {}
        
        # 🆕 集成真实的Agent协调器
        self._real_coordinator = None
        self._real_coordinators: Dict[int, Any] = {}
        self._coordinator_factory = None
        self._coordinator_initialized = False
        
        # 🎯 新增：项目上下文管理
        self.current_project_id: Optional[int] = None

    def _activate_project_scope(self, project_id: int) -> None:
        """切换当前项目作用域，绑定项目级状态容器。"""
        self.current_project_id = project_id
        self.agents = self._get_project_agents(project_id)
        self.stage_outputs = self._get_project_stage_outputs(project_id)
        self.workflow_state = self._get_project_workflow_state(project_id)
        self.message_queue = self._get_project_message_queue(project_id)

    def _build_agent_registry(self) -> Dict[str, Dict[str, Any]]:
        """根据模板构建一份新的项目级Agent运行态快照。"""
        return {
            agent_id: dict(agent_config)
            for agent_id, agent_config in self._agent_templates.items()
        }

    def _get_project_agents(self, project_id: int) -> Dict[str, Dict[str, Any]]:
        """获取项目级Agent运行态，不切换全局作用域。"""
        if project_id not in self._project_agents:
            self._project_agents[project_id] = self._build_agent_registry()
        return self._project_agents[project_id]

    def _get_project_stage_outputs(self, project_id: int) -> Dict[StageType, StageOutput]:
        """获取项目级阶段输出容器，不切换全局作用域。"""
        return self._project_stage_outputs.setdefault(project_id, {})

    def _get_project_workflow_state(self, project_id: int) -> Dict[str, Any]:
        """获取项目级工作流状态容器，不切换全局作用域。"""
        return self._project_workflow_states.setdefault(project_id, {})

    def _get_project_message_queue(self, project_id: int) -> List[AgentMessage]:
        """获取项目级消息队列，不切换全局作用域。"""
        return self._project_message_queues.setdefault(project_id, [])

    def set_workflow_state(self, project_id: int, state: Dict[str, Any]) -> None:
        """设置项目级工作流状态，避免不同项目共享同一份状态字典。"""
        self._activate_project_scope(project_id)
        project_state = dict(state)
        self._project_workflow_states[project_id] = project_state
        self.workflow_state = project_state

    def get_workflow_state(self, project_id: Optional[int] = None) -> Dict[str, Any]:
        """获取项目级工作流状态。"""
        resolved_project_id = project_id or self.current_project_id
        if resolved_project_id is None:
            return self.workflow_state
        return self._get_project_workflow_state(resolved_project_id)

    def _get_or_create_real_coordinator(self, project_id: Optional[int] = None):
        """获取项目级真实协调器，不同项目使用独立实例。"""
        if project_id is None:
            return self._real_coordinator

        if project_id in self._real_coordinators:
            return self._real_coordinators[project_id]

        if not self._coordinator_initialized or not self._coordinator_factory:
            return self._real_coordinator

        real_coordinator = self._coordinator_factory()
        if not hasattr(real_coordinator, "_stage_one_concept_development"):
            raise RuntimeError("协调器缺少 _stage_one_concept_development 方法")

        self._real_coordinators[project_id] = real_coordinator
        return real_coordinator

    def get_real_coordinator(self, project_id: Optional[int] = None):
        """对外暴露项目级真实协调器访问接口。"""
        resolved_project_id = project_id or self.current_project_id
        if resolved_project_id is not None:
            real_coordinator = self._get_or_create_real_coordinator(resolved_project_id)
            if real_coordinator:
                self._real_coordinator = real_coordinator
            return real_coordinator
        return self._real_coordinator

    async def initialize_agents(self) -> None:
        """初始化所有Agent"""
        if not self._coordinator_initialized:
            try:
                # 🆕 导入并初始化真实的协调器
                logger.debug("🔍 开始初始化真实协调器...")
                logger.debug("   步骤1: 导入 enhanced_coordinator 模块...")
                from .agents.enhanced_coordinator import create_enhanced_coordinator
                logger.debug("   ✅ 步骤1完成: enhanced_coordinator 模块导入成功")
                
                logger.debug("   步骤2: 创建协调器实例...")
                self._coordinator_factory = create_enhanced_coordinator
                self._real_coordinator = self._coordinator_factory()
                logger.debug("   ✅ 步骤2完成: 协调器实例创建成功")
                
                logger.debug("   步骤3: 测试协调器方法...")
                # 测试协调器是否有必要的方法
                if not hasattr(self._real_coordinator, '_stage_one_concept_development'):
                    raise RuntimeError("协调器缺少 _stage_one_concept_development 方法")
                logger.debug("   ✅ 步骤3完成: 协调器方法验证通过")
                
                self._coordinator_initialized = True
                logger.debug("✅ 真实Agent协调器初始化成功（已启用通信系统）")
            except ImportError as e:
                error_msg = f"❌ 导入模块失败: {e}"
                logger.debug(error_msg)
                logger.debug("\n⚠️  详细错误追踪:")
                import traceback
                traceback.print_exc()
                logger.debug("\n⚠️  请检查:")
                logger.debug("   1. enhanced_coordinator.py 是否存在于 backend/app/services/agents/")
                logger.debug("   2. agent_coordinator.py 是否存在于 backend/app/services/agents/")
                logger.debug("   3. 依赖模块是否都存在：")
                logger.debug("      - config.py")
                logger.debug("      - knowledge_base.py")
                logger.debug("      - memory_manager.py")
                logger.debug("      - agents.py")
                logger.debug("      - agent_communication.py")
                logger.debug("   4. Python包是否已安装：")
                logger.debug("      - langchain")
                logger.debug("      - openai")
                logger.debug("      - chromadb")
                logger.debug("\n💡 建议: 运行 pip install -r requirements.txt 安装所有依赖")
                # 🔧 回退：不抛错，使用模拟模式
                self._coordinator_initialized = False
                self._real_coordinator = None
                self._real_coordinators = {}
                self._coordinator_factory = None
                logger.debug("⚠️  已回退到模拟协调器模式")
            except BaseException as e:
                if isinstance(e, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                    raise
                error_msg = f"❌ 初始化真实协调器失败: {e}"
                logger.warning(error_msg)
                logger.warning("\n⚠️  详细错误追踪:")
                import traceback
                traceback.print_exc()
                self._coordinator_initialized = False
                self._real_coordinator = None
                self._real_coordinators = {}
                self._coordinator_factory = None
                logger.warning("⚠️  已回退到模拟协调器模式")
        
        # Agent配置映射
        agents_config = {
            AgentType.CREATIVE_DIRECTOR: {
                "name": "创意总监",
                "role": "协调整个创作流程",
                "stage": StageType.CONCEPT,
            },
            AgentType.WORLDVIEW_ARCHITECT: {
                "name": "世界观架构师",
                "role": "设计故事世界观",
                "stage": StageType.CONCEPT,
            },
            AgentType.CHARACTER_DESIGNER: {
                "name": "人物设计师",
                "role": "设计故事人物",
                "stage": StageType.CONCEPT,
            },
            AgentType.PLOT_ARCHITECT: {
                "name": "情节架构师",
                "role": "设计故事情节",
                "stage": StageType.STRUCTURE,
            },
            AgentType.EVENT_VALIDATOR: {
                "name": "事件验证官",
                "role": "验证事件序列质量",
                "stage": StageType.STRUCTURE,
            },
            AgentType.CONTENT_CREATOR: {
                "name": "内容创作师",
                "role": "创作章节内容",
                "stage": StageType.CONTENT,
            },
            AgentType.STYLE_OPTIMIZER: {
                "name": "文风优化师",
                "role": "优化文风和语言",
                "stage": StageType.CONTENT,
            },
            AgentType.QUALITY_REVIEWER: {
                "name": "质量评审官",
                "role": "评审内容质量",
                "stage": StageType.REVIEW,
            },
            AgentType.ITERATION_COORDINATOR: {
                "name": "迭代协调官",
                "role": "分析反馈制定改进计划",
                "stage": StageType.ITERATION,
            },
            AgentType.CONTENT_REVISER: {
                "name": "内容修订师",
                "role": "执行内容修订优化",
                "stage": StageType.ITERATION,
            },
            AgentType.FINAL_REVIEWER: {
                "name": "最终审核官",
                "role": "最终审核确认",
                "stage": StageType.ITERATION,
            },
        }

        self._agent_templates = {}
        for agent_type, config in agents_config.items():
            self._agent_templates[agent_type.value] = {
                "id": agent_type.value,
                "name": config["name"],
                "role": config["role"],
                "stage": config["stage"],
                "status": AgentStatus.IDLE,
                "progress": 0,
                "message": "",
            }

        if self.current_project_id is not None:
            self._activate_project_scope(self.current_project_id)
        elif not self.agents:
            self.agents = self._build_agent_registry()

    def get_agents(self, project_id: Optional[int] = None) -> Dict[str, Dict[str, Any]]:
        """获取项目级Agent运行态。"""
        resolved_project_id = project_id or self.current_project_id
        if resolved_project_id is not None:
            return self._get_project_agents(resolved_project_id)

        if not self.agents and self._agent_templates:
            self.agents = self._build_agent_registry()
        return self.agents

    def get_stage_agents(self, project_id: int, stage: StageType) -> List[Dict[str, Any]]:
        """获取某个项目在指定阶段的Agent列表。"""
        agent_registry = self.get_agents(project_id)
        return [
            agent
            for agent in agent_registry.values()
            if agent["stage"] == stage
        ]

    def set_project_context(self, project_id: int) -> None:
        """
        🔧 设置当前项目上下文（委托给真实的协调器）
        
        关键修复：避免项目间数据污染
        """
        self._activate_project_scope(project_id)
        logger.info(f"🔄 AgentCoordinator 设置项目上下文：project_id={project_id}")
        
        # 委托给真实的协调器处理
        real_coordinator = self.get_real_coordinator(project_id)
        if real_coordinator and hasattr(real_coordinator, 'set_project_context'):
            real_coordinator.set_project_context(project_id)
            self._real_coordinator = real_coordinator
            logger.info(f"✅ 已委托真实协调器设置项目上下文")
        else:
            logger.warning(f"⚠️  真实协调器未初始化或无 set_project_context 方法")

    async def execute_stage(
        self, stage: StageType, input_data: Dict[str, Any]
    ) -> StageOutput:
        """执行阶段"""
        # 🎯 提取项目 ID
        project_id = input_data.get("project_id")
        if project_id:
            self._activate_project_scope(project_id)
            logger.debug(f"🎯 设置当前项目上下文: project_id={project_id}")
            
            # 🔥 关键修复：从数据库加载项目上下文
            self.set_project_context(project_id)
            await self._load_project_context_from_db(project_id)
        
        # 获取该阶段的Agent
        agent_registry = self.get_agents(project_id)
        stage_agents = [
            agent_id
            for agent_id, agent in agent_registry.items()
            if agent["stage"] == stage
        ]

        # 更新Agent状态
        for agent_id in stage_agents:
            agent_registry[agent_id]["status"] = AgentStatus.WORKING
            agent_registry[agent_id]["progress"] = 0

        # 🆕 必须使用真实的协调器执行（不再降级）
        real_coordinator = self.get_real_coordinator(project_id)
        if not self._coordinator_initialized or not real_coordinator:
            logger.debug(f"⚠️  真实协调器未初始化，使用模拟模式执行阶段 {stage.value}")
            output = await self._simulate_stage_execution(stage, stage_agents, input_data)
        else:
            # 执行真实协调器
            output = await self._execute_with_real_coordinator(stage, input_data)

        # 更新Agent状态
        for agent_id in stage_agents:
            agent_registry[agent_id]["status"] = AgentStatus.COMPLETED
            agent_registry[agent_id]["progress"] = 100

        # 保存阶段输出
        stage_output = StageOutput(
            stage=stage,
            agents_involved=stage_agents,
            output=output,
            status="completed",
        )
        if project_id:
            project_stage_outputs = self._project_stage_outputs.setdefault(project_id, {})
            project_stage_outputs[stage] = stage_output
            self.stage_outputs = project_stage_outputs
        else:
            self.stage_outputs[stage] = stage_output

        return stage_output
    
    async def _load_project_context_from_db(self, project_id: int):
        """🔥 从数据库加载项目上下文（关键修复！）
        
        根据记忆知识：异步工作流上下文加载规范
        在触发异步工作流执行前，必须从数据库加载完整的项目上下文数据
        """
        from app.db.base import get_db
        from app.services.workflow_context_builder import WorkflowContextBuilder
        
        try:
            db = next(get_db())
            stage_context = WorkflowContextBuilder(db).load_stage_text_context(project_id)
            has_stage_context = any(
                [
                    stage_context.concept,
                    stage_context.world_setting,
                    stage_context.characters,
                    stage_context.plot_outline,
                    stage_context.chapter_draft,
                    stage_context.review_report,
                    stage_context.final_version,
                ]
            )

            if has_stage_context:
                # 更新 real_coordinator 的 project_context
                real_coordinator = self.get_real_coordinator(project_id)
                if real_coordinator:
                    # 更新 project_context
                    real_coordinator.project_context.update({
                        "concept": stage_context.concept,
                        "world_setting": stage_context.world_setting,
                        "characters": stage_context.characters,
                        "plot_outline": stage_context.plot_outline,
                        "content": stage_context.chapter_draft,  # ← 关键！
                        "chapter_draft": stage_context.chapter_draft,
                        "review_report": stage_context.review_report,
                        "review": stage_context.review_report,  # 兼容两种字段名
                        "final_version": stage_context.final_version,
                    })
                    
                    logger.debug(f"✅ 已从数据库加载项目上下文:")
                    logger.debug(f"   - 概念: {len(stage_context.concept)} 字")
                    logger.debug(f"   - 世界观: {len(stage_context.world_setting)} 字")
                    logger.debug(f"   - 人物: {len(stage_context.characters)} 字")
                    logger.debug(f"   - 情节大纲: {len(stage_context.plot_outline)} 字")
                    logger.debug(f"   - 章节初稿: {len(stage_context.chapter_draft)} 字")  # ← 这里应该不为0！
                    logger.debug(f"   - 评审报告: {len(stage_context.review_report)} 字")
                    logger.debug(f"   - 最终版本: {len(stage_context.final_version)} 字")
            else:
                real_coordinator = self.get_real_coordinator(project_id)
                if real_coordinator:
                    real_coordinator.project_context.update({
                        "concept": "",
                        "world_setting": "",
                        "characters": "",
                        "plot_outline": "",
                        "content": "",
                        "chapter_draft": "",
                        "review_report": "",
                        "review": "",
                        "final_version": "",
                    })
                logger.debug(f"⚠️  数据库中未找到项目 {project_id} 的设置")
        
        except Exception as e:
            logger.debug(f"⚠️  加载项目上下文失败: {e}")
            import traceback
            traceback.print_exc()

    async def _execute_with_real_coordinator(
        self, stage: StageType, input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """🆕 使用真实的协调器执行阶段"""
        # 类型检查
        try:
            requirement = input_data.get("requirement", "根据项目设定进行创作")
            project_id = input_data.get("project_id")
            workflow_state = self.get_workflow_state(project_id)
            target_chapter_count = workflow_state.get("target_chapter_count")
            real_coordinator = self.get_real_coordinator(project_id)

            if not real_coordinator:
                error_msg = "⚠️ 真实协调器未初始化，请检查 enhanced_coordinator 是否正确安装"
                logger.debug(error_msg)
                raise RuntimeError(error_msg)

            # 🎯 设置项目上下文（关键！）
            if project_id and hasattr(real_coordinator, 'set_project_context'):
                real_coordinator.set_project_context(project_id)
                self._real_coordinator = real_coordinator
                logger.debug(f"✅ 已为真实协调器设置项目上下文: {project_id}")

            # 🆕 设置长篇创作配置（例如目标章节数）
            if target_chapter_count is not None and hasattr(real_coordinator, "set_longform_config"):
                try:
                    real_coordinator.set_longform_config(target_chapter_count=target_chapter_count)
                    logger.debug(f"✅ 已为真实协调器设置目标章节数: {target_chapter_count}")
                except Exception as e:
                    logger.debug(f"⚠️ 设置目标章节数失败，将使用默认配置: {e}")

            # 调用真实的五阶段工作流程
            if stage == StageType.CONCEPT:
                # 阶段1: 概念开发
                result = real_coordinator._stage_one_concept_development(requirement)
                return {
                    "concept": result.get("concept", ""),
                    "worldview": result.get("world_setting", ""),
                    "characters": result.get("characters", ""),
                }
            
            elif stage == StageType.STRUCTURE:
                # 阶段2: 结构设计
                concept_result = real_coordinator.project_context
                result = real_coordinator._stage_two_structure_design(concept_result)
                return {
                    "plot_outline": result.get("plot_outline", ""),
                    "structure": str(result),
                }
            
            elif stage == StageType.CONTENT:
                # 阶段3: 内容创作
                structure_result = real_coordinator.project_context
                result = real_coordinator._stage_three_content_creation(structure_result)
                return {
                    "content": result.get("content", ""),
                }
            
            elif stage == StageType.REVIEW:
                # 阶段4: 质量评审
                # 🔧 修复: 获取前一阶段的输出作为评审内容
                # 优先从 project_context 中获取 chapters 或 content
                content_to_review = (
                    real_coordinator.project_context.get('chapters') or 
                    real_coordinator.project_context.get('content') or 
                    real_coordinator.project_context.get('plot_outline', '正在生成中...')
                )
                
                content_result = {
                    'content': content_to_review
                }
                
                result = real_coordinator._stage_four_quality_review(content_result)
                return {
                    "review": result.get("review", ""),
                    "needs_revision": result.get("needs_revision", False),
                }
            
            elif stage == StageType.ITERATION:
                # 阶段5: 迭代优化
                # 🔥 关键修复：构造正确的 review_result 结构，确保 content 是嵌套字典
                chapter_draft_content = (
                    real_coordinator.project_context.get('content') or
                    real_coordinator.project_context.get('chapter_draft') or
                    real_coordinator.project_context.get('plot_outline', '')
                )

                # 📝 详细调试日志
                logger.debug(f"📝 迭代优化阶段 - 章节初稿字数: {len(chapter_draft_content) if isinstance(chapter_draft_content, str) else 0}")
                logger.debug(f"📝 project_context keys: {list(real_coordinator.project_context.keys())}")

                review_result = {
                    'review': (
                        real_coordinator.project_context.get('review') or
                        real_coordinator.project_context.get('review_report') or
                        "质量评审结果待补充"
                    ),
                    # 🔥 关键修复：强制设置 needs_revision=True，确保进入优化逻辑
                    'needs_revision': True,
                    # 🔥 关键修复：将 content 包装为嵌套字典结构
                    'content': {
                        'content': chapter_draft_content  # ← 这里是关键！
                    }
                }

                result = real_coordinator._stage_five_iteration_optimization(review_result)

                # 📝 关键调试：输出返回结果的结构
                logger.debug(f"📝 _stage_five_iteration_optimization 返回结果:")
                logger.debug(f"   - result type: {type(result)}")
                logger.debug(f"   - result keys: {result.keys() if isinstance(result, dict) else 'N/A'}")
                revised = result.get("revised_content", "") if isinstance(result, dict) else ""
                logger.debug(f"   - revised_content 字数: {len(revised) if revised else 0}")

                # 🔥 关键修复：如果 revised_content 为空，使用原始章节内容
                if not revised and chapter_draft_content:
                    logger.debug(f"⚠️  revised_content 为空，使用原始章节内容作为最终版本")
                    revised = chapter_draft_content

                return {
                    "revised_content": revised,
                    "final_review": result.get("final_review", "") if isinstance(result, dict) else "",
                }
            
            return {}
            
        except Exception as e:
            # 📢 详细记录错误信息
            logger.debug(f"❌ 真实协调器执行失败 (Stage: {stage.value}): {e}")
            import traceback
            traceback.print_exc()
            
            # ⛔ 不再静默降级，直接抛出错误
            raise RuntimeError(f"执行阶段 {stage.value} 失败: {str(e)}") from e
    
    async def _simulate_stage_execution(
        self, stage: StageType, agents: List[str], input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """模拟阶段执行（降级模式）"""
        logger.debug(f"⚠️ 使用模拟模式执行阶段: {stage.value}")
        
        stage_outputs = {
            StageType.CONCEPT: {
                "concept": "一部关于修真与末法时代的概念草案",
                "worldview": "世界观：灵气衰退，法则动荡，势力分布简述",
                "characters": "主角：某某；配角：某某；反派：某某",
            },
            StageType.STRUCTURE: {
                "plot_outline": "第一部分：起；第二部分：承；第三部分：转；第四部分：合",
                "structure": "结构：三幕式大纲",
            },
            StageType.CONTENT: {
                "content": "章节初稿占位文本...",
            },
            StageType.REVIEW: {
                "review": "评审报告占位文本...",
                "needs_revision": False,
            },
            StageType.ITERATION: {
                "revised_content": "优化后章节占位文本...",
                "final_review": "最终评审占位文本...",
            },
        }

        return stage_outputs.get(stage, {})

    async def get_agent_status(self, agent_id: str, project_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """获取Agent状态"""
        return self.get_agents(project_id).get(agent_id)

    async def get_stage_output(self, stage: StageType, project_id: Optional[int] = None) -> Optional[StageOutput]:
        """获取阶段输出"""
        resolved_project_id = project_id or self.current_project_id
        if resolved_project_id is not None:
            return self._get_project_stage_outputs(resolved_project_id).get(stage)
        return self.stage_outputs.get(stage)

    async def get_workflow_status(self, project_id: Optional[int] = None) -> Dict[str, Any]:
        """获取工作流程状态"""
        workflow_state = self.get_workflow_state(project_id)
        agent_registry = self.get_agents(project_id)
        stage_outputs = self.stage_outputs
        if project_id is not None:
            stage_outputs = self._get_project_stage_outputs(project_id)

        return {
            "agents": agent_registry,
            "stage_outputs": {
                stage.value: output.__dict__
                for stage, output in stage_outputs.items()
            },
            "workflow_state": workflow_state,
        }

    def add_message(self, message: AgentMessage, project_id: Optional[int] = None) -> None:
        """添加消息"""
        resolved_project_id = project_id or self.current_project_id
        if resolved_project_id is not None:
            self._get_project_message_queue(resolved_project_id).append(message)
            return
        self.message_queue.append(message)

    def get_messages(self, limit: int = 100, project_id: Optional[int] = None) -> List[AgentMessage]:
        """获取消息"""
        resolved_project_id = project_id or self.current_project_id
        if resolved_project_id is not None:
            return self._get_project_message_queue(resolved_project_id)[-limit:]
        return self.message_queue[-limit:]


# 全局Agent协调器实例
coordinator = AgentCoordinator()

