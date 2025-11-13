"""
Agent协调系统 - 管理多个Agent的协调和通信
集成真实的CreativeDirectorCoordinator
"""
import asyncio
from typing import Dict, List, Any, Optional
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime


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

        # 🆕 集成真实的Agent协调器
        self._real_coordinator = None
        self._coordinator_initialized = False

        # 🎯 新增：项目上下文管理
        self.current_project_id: Optional[int] = None

        # 🆕 进度回调相关属性
        self.progress_callback = None
        self.current_task_id: Optional[str] = None

    async def initialize_agents(self) -> None:
        """初始化所有Agent"""
        if not self._coordinator_initialized:
            try:
                # 🆕 导入并初始化真实的协调器
                print("🔍 开始初始化真实协调器...")
                print("   步骤1: 导入 enhanced_coordinator 模块...")
                from .agents.enhanced_coordinator import create_enhanced_coordinator
                print("   ✅ 步骤1完成: enhanced_coordinator 模块导入成功")
                
                print("   步骤2: 创建协调器实例...")
                self._real_coordinator = create_enhanced_coordinator()
                print("   ✅ 步骤2完成: 协调器实例创建成功")
                
                print("   步骤3: 测试协调器方法...")
                # 测试协调器是否有必要的方法
                if not hasattr(self._real_coordinator, '_stage_one_concept_development'):
                    raise RuntimeError("协调器缺少 _stage_one_concept_development 方法")
                print("   ✅ 步骤3完成: 协调器方法验证通过")
                
                self._coordinator_initialized = True
                print("✅ 真实Agent协调器初始化成功（已启用通信系统）")
            except ImportError as e:
                error_msg = f"❌ 导入模块失败: {e}"
                print(error_msg)
                print("\n⚠️  详细错误追踪:")
                import traceback
                traceback.print_exc()
                print("\n⚠️  请检查:")
                print("   1. enhanced_coordinator.py 是否存在于 backend/app/services/agents/")
                print("   2. agent_coordinator.py 是否存在于 backend/app/services/agents/")
                print("   3. 依赖模块是否都存在：")
                print("      - config.py")
                print("      - knowledge_base.py")
                print("      - memory_manager.py")
                print("      - agents.py")
                print("      - agent_communication.py")
                print("   4. Python包是否已安装：")
                print("      - langchain")
                print("      - openai")
                print("      - chromadb")
                print("\n💡 建议: 运行 pip install -r requirements.txt 安装所有依赖")
                # ⛔ 不再静默失败，而是抛出错误
                self._coordinator_initialized = False
                raise RuntimeError(error_msg) from e
            except Exception as e:
                error_msg = f"❌ 初始化真实协调器失败: {e}"
                print(error_msg)
                print("\n⚠️  详细错误追踪:")
                import traceback
                traceback.print_exc()
                # ⛔ 抛出错误
                self._coordinator_initialized = False
                raise RuntimeError(error_msg) from e
        
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
                "role": "协调迭代优化",
                "stage": StageType.ITERATION,
            },
        }

        for agent_type, config in agents_config.items():
            self.agents[agent_type.value] = {
                "id": agent_type.value,
                "name": config["name"],
                "role": config["role"],
                "stage": config["stage"],
                "status": AgentStatus.IDLE,
                "progress": 0,
                "message": "",
            }

    def set_progress_callback(self, callback, task_id: str, project_id: int):
        """设置进度回调函数

        Args:
            callback: 进度回调函数 (async function)
            task_id: 任务ID
            project_id: 项目ID
        """
        import asyncio
        self.progress_callback = callback
        self.current_task_id = task_id
        self.current_project_id = project_id

        # 🔥 关键修复：保存主线程的事件循环引用
        try:
            self.main_event_loop = asyncio.get_running_loop()
            print(f"✅ 已保存主线程事件循环引用")
        except RuntimeError:
            # 如果当前没有运行的事件循环，尝试获取当前线程的事件循环
            try:
                self.main_event_loop = asyncio.get_event_loop()
                print(f"✅ 已保存事件循环引用")
            except Exception as e:
                print(f"⚠️ 无法获取事件循环: {e}")
                self.main_event_loop = None

        print(f"✅ 已设置进度回调: task_id={task_id}, project_id={project_id}")

    async def execute_stage(
        self, stage: StageType, input_data: Dict[str, Any]
    ) -> StageOutput:
        """执行阶段"""
        # 🎯 提取项目 ID
        project_id = input_data.get("project_id")
        if project_id:
            self.current_project_id = project_id
            print(f"🎯 设置当前项目上下文: project_id={project_id}")
            
            # 🔥 关键修复：从数据库加载项目上下文
            await self._load_project_context_from_db(project_id)
        
        # 获取该阶段的Agent
        stage_agents = [
            agent_id
            for agent_id, agent in self.agents.items()
            if agent["stage"] == stage
        ]

        # 更新Agent状态
        for agent_id in stage_agents:
            self.agents[agent_id]["status"] = AgentStatus.WORKING
            self.agents[agent_id]["progress"] = 0

        # 🆕 必须使用真实的协调器执行（不再降级）
        if not self._coordinator_initialized or not self._real_coordinator:
            error_msg = f"⛔ 真实协调器未初始化，无法执行阶段 {stage.value}"
            print(error_msg)
            print("⚠️  请检查:")
            print("   1. enhanced_coordinator.py 是否存在")
            print("   2. agent_coordinator.py 是否存在")
            print("   3. 依赖是否正确安装")
            raise RuntimeError(error_msg)
        
        # 执行真实协调器
        output = await self._execute_with_real_coordinator(stage, input_data)

        # 更新Agent状态
        for agent_id in stage_agents:
            self.agents[agent_id]["status"] = AgentStatus.COMPLETED
            self.agents[agent_id]["progress"] = 100

        # 保存阶段输出
        stage_output = StageOutput(
            stage=stage,
            agents_involved=stage_agents,
            output=output,
            status="completed",
        )
        self.stage_outputs[stage] = stage_output

        return stage_output
    
    async def _load_project_context_from_db(self, project_id: int):
        """🔥 从数据库加载项目上下文（关键修复！）

        根据记忆知识：异步工作流上下文加载规范
        在触发异步工作流执行前，必须从数据库加载完整的项目上下文数据
        """
        from sqlalchemy import text
        from app.db.base import get_db
        import json
        
        try:
            db = next(get_db())
            
            # 查询 project_settings 表
            query = text("""
                SELECT concept, world_setting, characters, plot_outline, 
                       chapter_draft, review_report, final_version
                FROM project_settings
                WHERE project_id = :project_id
            """)
            
            result = db.execute(query, {"project_id": project_id}).fetchone()
            
            if result:
                # 更新 real_coordinator 的 project_context
                if self._real_coordinator:
                    # 🔧 修复JSON解析错误：智能处理各种格式
                    def safe_parse_json(value):
                        """安全解析JSON，兼容多种格式"""
                        if not value:
                            return ""
                        
                        # 如果已经是字符串且不以JSON特征开头，直接返回
                        if isinstance(value, str) and not value.strip().startswith(('{', '[', '"')):
                            return value
                        
                        try:
                            parsed = json.loads(value)
                            # 如果解析结果是字符串，直接返回
                            if isinstance(parsed, str):
                                return parsed
                            # 否则转回字符串
                            return json.dumps(parsed, ensure_ascii=False)
                        except (json.JSONDecodeError, TypeError):
                            # 解析失败，直接返回原值
                            return str(value) if value else ""
                    
                    # 使用安全解析方法
                    concept = safe_parse_json(result[0])
                    world_setting = safe_parse_json(result[1])
                    characters = safe_parse_json(result[2])
                    plot_outline = safe_parse_json(result[3])
                    chapter_draft = safe_parse_json(result[4])
                    review_report = safe_parse_json(result[5])
                    final_version = safe_parse_json(result[6])
                    
                    # 更新 project_context
                    self._real_coordinator.project_context.update({
                        "concept": concept,
                        "world_setting": world_setting,
                        "characters": characters,
                        "plot_outline": plot_outline,
                        "content": chapter_draft,  # ← 关键！
                        "chapter_draft": chapter_draft,
                        "review_report": review_report,
                        "review": review_report,  # 兼容两种字段名
                        "final_version": final_version,
                    })
                    
                    print(f"✅ 已从数据库加载项目上下文:")
                    print(f"   - 概念: {len(concept)} 字")
                    print(f"   - 世界观: {len(world_setting)} 字")
                    print(f"   - 人物: {len(characters)} 字")
                    print(f"   - 情节大纲: {len(plot_outline)} 字")
                    print(f"   - 章节初稿: {len(chapter_draft)} 字")  # ← 这里应该不为0！
                    print(f"   - 评审报告: {len(review_report)} 字")
                    print(f"   - 最终版本: {len(final_version)} 字")
            else:
                print(f"⚠️  数据库中未找到项目 {project_id} 的设置")
        
        except Exception as e:
            print(f"⚠️  加载项目上下文失败: {e}")
            import traceback
            traceback.print_exc()

    async def _execute_with_real_coordinator(
        self, stage: StageType, input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """🆕 使用真实的协调器执行阶段"""
        # 类型检查
        if not self._real_coordinator:
            error_msg = "⚠️ 真实协调器未初始化，请检查 enhanced_coordinator 是否正确安装"
            print(error_msg)
            # ⛔ 不再静默降级，而是抛出错误
            raise RuntimeError(error_msg)
        
        try:
            requirement = input_data.get("requirement", "根据项目设定进行创作")
            project_id = input_data.get("project_id")
            
            # 🎯 设置项目上下文（关键！）
            if project_id and hasattr(self._real_coordinator, 'set_project_context'):
                self._real_coordinator.set_project_context(project_id)
                print(f"✅ 已为真实协调器设置项目上下文: {project_id}")

            # 🔥 关键修复：将进度回调传递给真实协调器
            if hasattr(self._real_coordinator, 'set_progress_callback'):
                self._real_coordinator.set_progress_callback(
                    self.progress_callback,
                    self.current_task_id,
                    self.current_project_id
                )
                # 🔥 同时传递事件循环引用
                if hasattr(self, 'main_event_loop') and self.main_event_loop:
                    self._real_coordinator.main_event_loop = self.main_event_loop
                    print(f"✅ 已为真实协调器设置进度回调和事件循环引用")
                else:
                    print(f"✅ 已为真实协调器设置进度回调")

            # 调用真实的五阶段工作流程
            # 🔧 关键修复：使用 asyncio.to_thread() 在线程池中运行同步函数
            # 这样可以避免阻塞事件循环，同时允许 _send_progress_update() 正常工作
            import asyncio

            if stage == StageType.CONCEPT:
                # 阶段1: 概念开发
                print(f"🔄 在线程池中执行概念开发阶段...")
                result = await asyncio.to_thread(
                    self._real_coordinator._stage_one_concept_development,
                    requirement
                )
                return {
                    "concept": result.get("concept", ""),
                    "worldview": result.get("world_setting", ""),
                    "characters": result.get("characters", ""),
                }

            elif stage == StageType.STRUCTURE:
                # 阶段2: 结构设计
                print(f"🔄 在线程池中执行结构设计阶段...")
                concept_result = self._real_coordinator.project_context
                result = await asyncio.to_thread(
                    self._real_coordinator._stage_two_structure_design,
                    concept_result
                )
                return {
                    "plot_outline": result.get("plot_outline", ""),
                    "structure": str(result),
                }

            elif stage == StageType.CONTENT:
                # 阶段3: 内容创作
                print(f"🔄 在线程池中执行内容创作阶段...")
                structure_result = self._real_coordinator.project_context
                result = await asyncio.to_thread(
                    self._real_coordinator._stage_three_content_creation,
                    structure_result
                )
                return {
                    "content": result.get("content", ""),
                }
            
            elif stage == StageType.REVIEW:
                # 阶段4: 质量评审
                print(f"🔄 在线程池中执行质量评审阶段...")
                # 🔧 修复: 获取前一阶段的输出作为评审内容
                # 优先从 project_context 中获取 chapters 或 content
                content_to_review = (
                    self._real_coordinator.project_context.get('chapters') or
                    self._real_coordinator.project_context.get('content') or
                    self._real_coordinator.project_context.get('plot_outline', '正在生成中...')
                )

                content_result = {
                    'content': content_to_review
                }

                result = await asyncio.to_thread(
                    self._real_coordinator._stage_four_quality_review,
                    content_result
                )
                return {
                    "review": result.get("review", ""),
                    "needs_revision": result.get("needs_revision", False),
                }

            elif stage == StageType.ITERATION:
                # 阶段5: 迭代优化
                print(f"🔄 在线程池中执行迭代优化阶段...")
                # 🔥 关键修复：构造正确的 review_result 结构，确保 content 是嵌套字典
                chapter_draft_content = (
                    self._real_coordinator.project_context.get('content') or
                    self._real_coordinator.project_context.get('chapter_draft') or
                    self._real_coordinator.project_context.get('plot_outline', '')
                )

                # 📝 记录日志，方便调试
                print(f"📝 迭代优化阶段 - 章节初稿字数: {len(chapter_draft_content) if isinstance(chapter_draft_content, str) else 0}")

                review_result = {
                    'review': (
                        self._real_coordinator.project_context.get('review') or
                        self._real_coordinator.project_context.get('review_report') or
                        "质量评审结果待补充"
                    ),
                    'needs_revision': self._real_coordinator.project_context.get('needs_revision', False),
                    # 🔥 关键修复：将 content 包装为嵌套字典结构
                    'content': {
                        'content': chapter_draft_content  # ← 这里是关键！
                    }
                }

                result = await asyncio.to_thread(
                    self._real_coordinator._stage_five_iteration_optimization,
                    review_result
                )
                return {
                    "revised_content": result.get("revised_content", ""),
                    "final_review": result.get("final_review", ""),
                }
            
            return {}
            
        except Exception as e:
            # 📢 详细记录错误信息
            print(f"❌ 真实协调器执行失败 (Stage: {stage.value}): {e}")
            import traceback
            traceback.print_exc()
            
            # ⛔ 不再静默降级，直接抛出错误
            raise RuntimeError(f"执行阶段 {stage.value} 失败: {str(e)}") from e
    
    async def _simulate_stage_execution(
        self, stage: StageType, agents: List[str], input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """模拟阶段执行（降级模式）"""
        print(f"⚠️ 使用模拟模式执行阶段: {stage.value}")
        
        stage_outputs = {
            StageType.CONCEPT: {
                "worldview": "在遥远的未来，人类发现了时空旅行的秘密...",
                "characters": [
                    {"name": "主角", "description": "勇敢的时空旅行者"},
                    {"name": "配角", "description": "神秘的时空守护者"},
                ],
                "concept": "一部关于时空旅行的科幻冒险小说",
            },
            StageType.STRUCTURE: {
                "plot_outline": "第一部分：发现秘密\n第二部分：时空冒险\n第三部分：最终对决",
                "events": [
                    {"event": "发现时空传送门", "chapter": 1},
                    {"event": "进入平行世界", "chapter": 5},
                    {"event": "最终对决", "chapter": 10},
                ],
            },
            StageType.CONTENT: {
                "chapters": [
                    {"chapter": 1, "title": "发现", "content": "第一章内容..."},
                    {"chapter": 2, "title": "冒险", "content": "第二章内容..."},
                ],
                "style": "科幻冒险风格，紧凑的叙事节奏",
            },
            StageType.REVIEW: {
                "quality_score": 8.5,
                "feedback": "内容质量良好，建议加强人物刻画",
                "issues": ["人物刻画需加强", "部分情节过快"],
            },
            StageType.ITERATION: {
                "improvements": ["加强人物刻画", "调整情节节奏"],
                "final_status": "已优化完成",
            },
        }

        return stage_outputs.get(stage, {})

    async def get_agent_status(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """获取Agent状态"""
        return self.agents.get(agent_id)

    async def get_stage_output(self, stage: StageType) -> Optional[StageOutput]:
        """获取阶段输出"""
        return self.stage_outputs.get(stage)

    async def get_workflow_status(self) -> Dict[str, Any]:
        """获取工作流程状态"""
        return {
            "agents": self.agents,
            "stage_outputs": {
                stage.value: output.__dict__
                for stage, output in self.stage_outputs.items()
            },
            "workflow_state": self.workflow_state,
        }

    def add_message(self, message: AgentMessage) -> None:
        """添加消息"""
        self.message_queue.append(message)

    def get_messages(self, limit: int = 100) -> List[AgentMessage]:
        """获取消息"""
        return self.message_queue[-limit:]


# 全局Agent协调器实例
coordinator = AgentCoordinator()

