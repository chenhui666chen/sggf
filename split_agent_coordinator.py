"""Split agent_coordinator.py into a package using Mixin pattern."""
import os
import re

SRC = r"c:\Users\cuigu\novel_writing_agent\backend\app\services\agents\agent_coordinator.py"
OUT_DIR = r"c:\Users\cuigu\novel_writing_agent\backend\app\services\agents\agent_coordinator_pkg"

def read_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.readlines()

def slice_raw(lines, start, end):
    """1-indexed, inclusive start, exclusive end"""
    return ''.join(lines[start-1:end-1])

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

lines = read_file(SRC)
total = len(lines)
print(f"Source file: {total} lines")

# _constants.py (44-213)
constants_content = slice_raw(lines, 44, 213)
constants_header = '''"""
Agent协调器常量定义
"""
import re
import random
from typing import Any, Optional


'''
constants_content = constants_header + constants_content

# _utils.py (59-131) - 辅助函数
utils_content = '''"""
Agent协调器工具函数
"""
import re
from typing import Any, Optional, Tuple


def _normalize_role_position_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    compact = text.splitlines()[0].strip().strip(""\"'"'")
    for canonical, keywords in _SINGLE_ROLE_POSITION_RULES:
        if any(keyword in compact for keyword in keywords):
            return canonical

    first_segment = re.split(r"[/|;,", compact, maxsplit=1)[0].strip()
    return first_segment[:12]


def _infer_story_stance_from_role_position_label(role_position: str) -> Optional[str]:
    mapping = {
        "主角": "主角方",
        "盟友": "主角方",
        "导师": "主角方",
        "守护者": "主角方",
        "情报角色": "主角方",
        "对手": "反派方",
        "初期对手": "反派方",
        "高位反派": "反派方",
        "中立角色": "中立方",
        "危险盟友": "亦正亦邪",
    }
    return mapping.get(str(role_position or "").strip())


def _replace_single_line_card_field(block: str, label: str, value: str) -> Tuple[str, bool]:
    if not value:
        return block, False

    field_pattern = re.compile(
        rf"(?m)^(?P<prefix>\\s*(?:###\\s*)?(?:\\*\\*)?【{re.escape(label)}】(?:\\*\\*)?[：:]\\s*).*$"
    )
    if field_pattern.search(block):
        updated = field_pattern.sub(lambda match: f"{match.group('prefix')}{value}", block, count=1)
        return updated, updated != block
    return block, False


def _insert_single_line_card_field(
    block: str,
    label: str,
    value: str,
    *,
    after_labels: Tuple[str, ...],
) -> Tuple[str, bool]:
    if not value:
        return block, False

    lines = block.splitlines()
    insert_at = 1 if lines else 0

    for index, line in enumerate(lines):
        if any(f"【{after_label}】" in line for after_label in after_labels):
            insert_at = index + 1

    lines.insert(insert_at, f"【{label}】：{value}")
    return "\\n".join(lines), True


LEGACY_CHARACTER_SECTION_PATTERNS = (
    re.compile(
        r"(?im)^\\s*(?:#+\\s*)?[一二三四五六七八九十]+[、.．:：]\\s*(?:主角|核心盟友|关键配角|核心反派|人物关系网(?:与动态)?|人物关系网络与动态)"
    ),
    re.compile(
        r"(?im)^\\s*(?:#+\\s*)?(?:核心主角|核心盟友|关键配角|核心反派|人物关系网|动态演变|关系动态要点)\\s*$"
    ),
)


from ._constants import _SINGLE_ROLE_POSITION_RULES
'''

# _base.py - 基类
base_content = '''"""
CreativeDirectorCoordinator 基类

包含初始化和基础接口
"""
import logging
from typing import Any, Dict, Optional

from .knowledge_base import NovelKnowledgeBase
from .memory_manager import NovelMemoryManager
from .agents import (
    CreativeDirectorAgent,
    WorldArchitectAgent,
    CharacterDesignerAgent,
    ContentCreatorAgent,
    QualityReviewerAgent,
    OutlinePlanParserAgent,
)

logger = logging.getLogger(__name__)


class CreativeDirectorCoordinatorBase:
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
        
        self.creative_director = CreativeDirectorAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)
        self.world_architect = WorldArchitectAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)
        self.character_designer = CharacterDesignerAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)
        self.content_creator = ContentCreatorAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)
        self.quality_reviewer = QualityReviewerAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)
        self.outline_plan_parser = OutlinePlanParserAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)

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

        self.target_chapter_count: Optional[int] = None

        self._progress_cb = None
        self._progress_task_id = None
        self._progress_project_id = None

    def set_project_context(self, project_id: int) -> None:
        if self.project_id != project_id:
            logger.info(f"切换项目上下文：{self.project_id} -> {project_id}")
            self.project_context = {
                "concept": "",
                "world_setting": "",
                "characters": "",
                "plot_outline": "",
                "content": "",
                "chapters": [],
                "review": "",
                "genre": None,
                "sub_genre": None,
                "planned_length_type": None,
                "planned_chapters_min": None,
                "planned_chapters_max": None,
                "parsed_outline_plan": {},
                "regenerate": False,
                "regenerate_targets": [],
                "title": None,
                "project_title": None,
                "project_genre": None,
            }

            self.memory_manager.clear_history()
            self.memory_manager.clear_context()
            self.memory_manager.load_from_disk(project_id)
            self.memory_manager.update_context(project_id=project_id)
        
        self.project_id = project_id
        for agent in (
            self.creative_director,
            self.world_architect,
            self.character_designer,
            self.content_creator,
            self.quality_reviewer,
            self.outline_plan_parser,
        ):
            agent.set_project_context(project_id)
        logger.info(f"项目上下文已设置：project_id={project_id}")

    def set_longform_config(self, target_chapter_count: Optional[int] = None) -> None:
        self.target_chapter_count = target_chapter_count

    def set_progress_callback(self, cb, task_id: str, project_id: int) -> None:
        self._progress_cb = cb
        self._progress_task_id = task_id
        self._progress_project_id = project_id
'''

# _character_card.py (325-518)
character_card_content = slice_raw(lines, 325, 518)
character_card_header = '''"""
人物卡处理 Mixin

包含人物卡规范化相关方法
"""
import logging
from typing import Any, Dict

from app.services.character_parser import (
    CharacterTextParser,
    convert_legacy_grouped_characters_to_cards,
    has_parseable_character_cards,
    normalize_story_stance_label,
)
from app.services.prompts.base.format import get_output_format

from ._utils import (
    _normalize_role_position_label,
    _infer_story_stance_from_role_position_label,
    _replace_single_line_card_field,
    _insert_single_line_card_field,
    LEGACY_CHARACTER_SECTION_PATTERNS,
)

logger = logging.getLogger(__name__)


'''
character_card_content = character_card_header + character_card_content

# _outline.py (519-678)
outline_content = slice_raw(lines, 519, 678)
outline_header = '''"""
大纲解析 Mixin

包含大纲规划解析方法
"""
import json
import logging
import re
from typing import Any, Dict

logger = logging.getLogger(__name__)


'''
outline_content = outline_header + outline_content

# _stages.py (680-1346)
stages_content = slice_raw(lines, 680, 1346)
stages_header = '''"""
阶段方法 Mixin

包含五阶段创作方法
"""
import logging
from typing import Any, Dict

from core.langchain_bridge import create_model_llm
from app.services.prompts.stages.world_building import (
    WorldBuildingPrompts,
    CharacterDesignPrompts,
    get_genre_world_extension,
    get_genre_character_fields,
)
from app.services.prompts.stages.structure_design import (
    StructureDesignPrompts,
    get_genre_rhythm_guide,
)
from .intelligent_truncator import smart_truncate_for_context
from ._constants import (
    GENRE_PROMPT_MODULES,
    DEFAULT_GENRE_MODULE,
    GENRE_TERMINOLOGY,
    REALM_SPAN_WARNING_THRESHOLD,
    REALM_SPAN_RECOMMEND_SUBDIVISION,
    _build_project_creative_variation_profile,
)

logger = logging.getLogger(__name__)


'''
stages_content = stages_header + stages_content

# __init__.py
init_content = '''"""
agent_coordinator_pkg - 创意总监协调器

协调五阶段创作流程
"""
from ._constants import (
    _SINGLE_ROLE_POSITION_RULES,
    _normalize_role_position_label,
    _infer_story_stance_from_role_position_label,
    _build_project_creative_variation_profile,
    GENRE_TERMINOLOGY,
    GENRE_PROMPT_MODULES,
    DEFAULT_GENRE_MODULE,
    REALM_SPAN_WARNING_THRESHOLD,
    REALM_SPAN_RECOMMEND_SUBDIVISION,
)
from ._utils import (
    _replace_single_line_card_field,
    _insert_single_line_card_field,
    LEGACY_CHARACTER_SECTION_PATTERNS,
)
from ._base import CreativeDirectorCoordinatorBase
from ._character_card import CharacterCardMixin
from ._outline import OutlineMixin
from ._stages import StagesMixin


class CreativeDirectorCoordinator(
    CreativeDirectorCoordinatorBase,
    CharacterCardMixin,
    OutlineMixin,
    StagesMixin,
):
    """
    真实协调器：提供五阶段方法与必要的上下文接口，
    以满足系统的调用约定并避免导入失败。
    """
    pass


__all__ = [
    "CreativeDirectorCoordinator",
    "_SINGLE_ROLE_POSITION_RULES",
    "_normalize_role_position_label",
    "_infer_story_stance_from_role_position_label",
    "_build_project_creative_variation_profile",
    "GENRE_TERMINOLOGY",
    "GENRE_PROMPT_MODULES",
    "DEFAULT_GENRE_MODULE",
    "REALM_SPAN_WARNING_THRESHOLD",
    "REALM_SPAN_RECOMMEND_SUBDIVISION",
]
'''

# Write all files
write_file(os.path.join(OUT_DIR, "_constants.py"), constants_content)
print(f"Wrote _constants.py")

write_file(os.path.join(OUT_DIR, "_utils.py"), utils_content)
print(f"Wrote _utils.py")

write_file(os.path.join(OUT_DIR, "_base.py"), base_content)
print(f"Wrote _base.py")

write_file(os.path.join(OUT_DIR, "_character_card.py"), character_card_content)
print(f"Wrote _character_card.py")

write_file(os.path.join(OUT_DIR, "_outline.py"), outline_content)
print(f"Wrote _outline.py")

write_file(os.path.join(OUT_DIR, "_stages.py"), stages_content)
print(f"Wrote _stages.py")

write_file(os.path.join(OUT_DIR, "__init__.py"), init_content)
print(f"Wrote __init__.py")

print("Done!")
