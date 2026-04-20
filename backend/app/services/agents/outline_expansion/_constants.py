"""
情节大纲和人物扩展器 - 自动扩展简短大纲和增加人物数量
"""
import json
import logging
import os
import re
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

VOLUME_DETAIL_CHAPTER_HEADING_PATTERN = re.compile(
    r"(?m)^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*第\s*(\d+)\s*章(?:\*\*)?(?:[：:《\s]|$)"
)
VOLUME_DETAIL_RANGE_SHORTCUT_PATTERN = re.compile(
    r"(?:第\s*)?(?P<start>\d+)\s*(?:章)?\s*(?:-|~|～|—|－|至|到)\s*(?:第\s*)?(?P<end>\d+)\s*章"
)
VOLUME_DETAIL_GROUP_RANGE_PATTERN = re.compile(
    r"(?:章节|章节范围)\s*[：:]\s*(?P<start>\d+)\s*(?:-|~|～|—|－|至|到)\s*(?P<end>\d+)(?:\s*章)?"
)
VOLUME_DETAIL_MODEL_SWITCH_THRESHOLD = 80
VOLUME_DETAIL_MAX_CHAPTERS = 100
CHARACTER_CONTEXT_SUMMARY_LIMIT = 1800
CHARACTER_EXPANSION_OUTLINE_CONTEXT_LIMIT = 6000
CHARACTER_EXPANSION_CARD_CONTEXT_LIMIT = 6000
CHARACTER_EXPANSION_NEW_CARD_CONTEXT_LIMIT = 4200
CHARACTER_EXPANSION_MERGED_CONTEXT_LIMIT = 7200
EPIC_FRAMEWORK_CHARACTER_CONTEXT_LIMIT = 4200
VOLUME_DETAIL_CHARACTER_CONTEXT_LIMIT = 4200


CANONICAL_OUTLINE_CHAPTER_TEMPLATE = """- **场景目标**：（本章核心任务，30-40字）
  格式：[地点/局面] + [主要人物] + [要达成什么]

- **冲突设计**：（写清主要阻碍、升级过程与破局方向，40-80字）

- **关键事件**：
  1. ...
  2. ...

- **涉及人物**：...

- **人物推进**：（人物关系、立场、心理或能力的关键变化）

- **情节作用**：（承接/升级/转折/爆点前置/伏笔回收等）

- **结尾钩子**：（20-30字，说明下一章驱动力）

- **爽点类型**：（可选；如无明显爽点可写“无”）

- **伏笔事项**：（可选；如无则写“无”）"""


CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT = """- **场景目标**：...
- **冲突设计**：...
- **关键事件**：
  1. ...
  2. ...
- **涉及人物**：...
- **人物推进**：...
- **情节作用**：...
- **结尾钩子**：...
- **爽点类型**：...
- **伏笔事项**：..."""
