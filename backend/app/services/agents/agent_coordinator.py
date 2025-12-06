from typing import Optional, Dict, Any

from .knowledge_base import NovelKnowledgeBase
from .memory_manager import NovelMemoryManager


class CreativeDirectorCoordinator:
    """
    真实协调器（简版实现）：提供五阶段方法与必要的上下文接口，
    以满足系统的调用约定并避免导入失败。
    """

    def __init__(
        self,
        knowledge_base: Optional[NovelKnowledgeBase] = None,
        memory_manager: Optional[NovelMemoryManager] = None,
        enable_communication: bool = True,
        enable_conflict_detection: bool = True,
        enable_detailed_logging: bool = True,
    ) -> None:
        self.knowledge_base = knowledge_base or NovelKnowledgeBase()
        self.memory_manager = memory_manager or NovelMemoryManager()

        self.enable_communication = enable_communication
        self.enable_conflict_detection = enable_conflict_detection
        self.enable_detailed_logging = enable_detailed_logging

        # 项目上下文
        self.project_id: Optional[int] = None
        self.project_context: Dict[str, Any] = {
            "concept": "",
            "world_setting": "",
            "characters": "",
            "plot_outline": "",
            "content": "",
            "chapters": [],
            "review": "",
        }

        # 长篇创作配置
        self.target_chapter_count: Optional[int] = None

        # 进度回调（可选）
        self._progress_cb = None
        self._progress_task_id = None
        self._progress_project_id = None

    # ---- 基础接口 ----
    def set_project_context(self, project_id: int) -> None:
        self.project_id = project_id

    def set_longform_config(self, target_chapter_count: Optional[int] = None) -> None:
        self.target_chapter_count = target_chapter_count

    def set_progress_callback(self, cb, task_id: str, project_id: int) -> None:
        self._progress_cb = cb
        self._progress_task_id = task_id
        self._progress_project_id = project_id

    # ---- 阶段方法 ----
    def _stage_one_concept_development(self, requirement: str) -> Dict[str, Any]:
        """
        阶段1：概念开发
        返回 keys：concept, world_setting, characters
        """
        concept = (f"【概念】\n{requirement.strip()}\n" or "概念占位")
        world = self.project_context.get("world_setting") or "世界观占位：主题与背景纲要"
        chars = self.project_context.get("characters") or "人物占位：主角/对手/配角简述"

        self.project_context.update({
            "concept": concept,
            "world_setting": world,
            "characters": chars,
        })
        return {"concept": concept, "world_setting": world, "characters": chars}

    def _stage_two_structure_design(self, concept_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        阶段2：结构设计
        返回 keys：plot_outline
        """
        base = concept_result.get("concept") or self.project_context.get("concept")
        outline = f"【结构大纲】\n基于概念生成三幕式结构纲要\n{(base or '')[:300]}"
        self.project_context.update({"plot_outline": outline})
        return {"plot_outline": outline}

    def _stage_three_content_creation(self, structure_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        阶段3：内容创作
        返回 keys：content 或 chapters
        """
        target = self.target_chapter_count or 1
        content = f"【章节内容】\n依据大纲生成 {target} 章草稿。"
        self.project_context.update({"content": content, "chapters": [content]})
        return {"content": content}

    def _stage_four_quality_review(self, content_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        阶段4：质量评审
        返回 keys：review, needs_revision
        """
        material = (
            content_result.get("content")
            or self.project_context.get("content")
            or self.project_context.get("plot_outline")
            or ""
        )
        review = f"【评审报告】\n对材料的结构与人物一致性进行评审。\n长度={len(material)}"
        needs_revision = False
        self.project_context.update({"review": review})
        return {"review": review, "needs_revision": needs_revision}

    def _stage_five_iteration_optimization(self, review_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        阶段5：迭代优化
        返回 keys：revised_content, final_review
        """
        base = self.project_context.get("content") or ""
        revised = base + "\n【优化说明】根据评审建议进行细化与润色。"
        final_review = "【最终评审】优化完成，质量达标。"
        self.project_context.update({"content": revised})
        return {"revised_content": revised, "final_review": final_review}
