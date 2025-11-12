"""
多Agent框架 - 协调多个专业化Agent完成小说创作
"""
from typing import Dict, Any, List, Optional
from .agent_coordinator import CreativeDirectorCoordinator
from .knowledge_base import NovelKnowledgeBase
from .memory_manager import NovelMemoryManager


class MultiAgentNovelWritingFramework:
    """多Agent小说写作框架 - 基于五阶段工作流程"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None):
        """初始化多Agent框架"""
        self.knowledge_base = knowledge_base or NovelKnowledgeBase()
        self.memory_manager = memory_manager or NovelMemoryManager()
        self.coordinator = CreativeDirectorCoordinator(self.knowledge_base, self.memory_manager)
        
        self.project_state = {
            "stage": "initialization",  # initialization, world_building, character_creation, plot_design, writing, review
            "completed_tasks": [],
            "current_task": None
        }
    
    def start_project(self, project_title: str, genre: str, initial_concept: str) -> str:
        """启动新的小说创作项目"""
        print(f"\n{'='*70}")
        print(f"【框架】启动新项目: {project_title}")
        print(f"{'='*70}\n")

        self.coordinator.update_project_context(
            title=project_title,
            genre=genre
        )

        self.project_state["stage"] = "concept_development"
        self.project_state["current_task"] = "concept_development"

        # 让创意总监处理初始概念，启动五阶段工作流程
        response = self.coordinator.process_user_request(
            f"我想创作一部{genre}小说，题目是《{project_title}》。初始概念是：{initial_concept}"
        )

        self.project_state["completed_tasks"].append("concept_development")
        return response
    
    def build_world(self, world_description: str) -> str:
        """构建世界观"""
        print(f"\n【框架】进入世界观构建阶段\n")

        self.project_state["stage"] = "world_building"
        self.project_state["current_task"] = "world_building"

        response = self.coordinator.process_user_request(
            f"请为我的小说设计世界观。要求：{world_description}"
        )

        self.coordinator.update_project_context(world_setting=response)
        self.project_state["completed_tasks"].append("world_building")

        return response

    def create_characters(self, character_requirements: str) -> str:
        """创建人物"""
        print(f"\n【框架】进入人物创建阶段\n")

        self.project_state["stage"] = "character_creation"
        self.project_state["current_task"] = "character_creation"

        response = self.coordinator.process_user_request(
            f"请为我的小说创建人物。要求：{character_requirements}"
        )

        self.coordinator.update_project_context(characters=[response])
        self.project_state["completed_tasks"].append("character_creation")

        return response

    def design_plot(self, plot_requirements: str) -> str:
        """设计情节"""
        print(f"\n【框架】进入情节设计阶段\n")

        self.project_state["stage"] = "plot_design"
        self.project_state["current_task"] = "plot_design"

        response = self.coordinator.process_user_request(
            f"请为我的小说设计情节大纲。要求：{plot_requirements}"
        )

        self.coordinator.update_project_context(plot_outline=response)
        self.project_state["completed_tasks"].append("plot_design")

        return response

    def write_chapter(self, chapter_num: int, chapter_requirements: str) -> str:
        """撰写章节"""
        print(f"\n【框架】进入写作阶段 - 第{chapter_num}章\n")

        self.project_state["stage"] = "writing"
        self.project_state["current_task"] = f"writing_chapter_{chapter_num}"

        response = self.coordinator.process_user_request(
            f"请为我的小说撰写第{chapter_num}章。要求：{chapter_requirements}"
        )

        self.project_state["completed_tasks"].append(f"chapter_{chapter_num}")

        return response

    def review_content(self, content_to_review: str) -> str:
        """审阅内容"""
        print(f"\n【框架】进入审阅阶段\n")

        self.project_state["stage"] = "review"
        self.project_state["current_task"] = "review"

        response = self.coordinator.process_user_request(
            f"请审阅以下内容，指出问题并提出改进建议：\n\n{content_to_review}"
        )

        self.project_state["completed_tasks"].append("review")

        return response

    def revise_content(self, original_content: str, feedback: str) -> str:
        """根据反馈修改内容"""
        print(f"\n【框架】进入修改阶段\n")

        response = self.coordinator.process_user_request(
            f"请根据以下反馈修改内容：\n\n原始内容：\n{original_content}\n\n反馈：\n{feedback}"
        )

        return response

    def interactive_session(self) -> None:
        """交互式会话"""
        print(f"\n{'='*70}")
        print("【框架】进入交互式会话模式")
        print("输入 'quit' 退出，'status' 查看项目状态")
        print(f"{'='*70}\n")

        while True:
            user_input = input("你: ").strip()

            if user_input.lower() == "quit":
                print("【框架】会话结束")
                break
            elif user_input.lower() == "status":
                self._print_project_status()
                continue
            elif not user_input:
                continue

            response = self.coordinator.process_user_request(user_input)
            print(f"\n【创意总监】: {response}\n")

    def _print_project_status(self) -> None:
        """打印项目状态"""
        print(f"\n{'='*70}")
        print("【项目状态】")
        print(f"{'='*70}")
        context = self.coordinator.get_project_context()
        print(f"项目名称: {context.get('title', '未设置')}")
        print(f"类型: {context.get('genre', '未设置')}")
        print(f"当前阶段: {self.project_state['stage']}")
        print(f"已完成任务: {', '.join(self.project_state['completed_tasks']) or '无'}")
        print(f"{'='*70}\n")

    def get_project_summary(self) -> Dict[str, Any]:
        """获取项目摘要"""
        return {
            "context": self.coordinator.get_project_context(),
            "state": self.project_state,
            "workflow_log": self.coordinator.get_workflow_log()
        }

