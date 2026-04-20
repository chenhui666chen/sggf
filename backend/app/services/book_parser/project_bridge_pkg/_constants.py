from __future__ import annotations

import json
import logging
import re
from typing import Dict, Any, List, Optional
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.models.book_parser import BookSource, BookChapter, BookAnalysis
from app.models.project import Project, Chapter
from app.models.setting import SettingCollection, SettingItem
from app.models.character import Character
from app.models.user import User
from app.services.chapter_adaptation_assets import attach_cross_media_adaptation_hints
from app.services.character_parser import (
    _build_ability_and_limit_text,
    _build_mainline_binding_text,
    _build_personality_anchor_text,
    infer_story_stance_from_text_evidence,
)
from app.services.setting_templates import get_hierarchy_config_json
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

# 设定类型映射
ANALYSIS_TO_COLLECTION = {
    'characters': '人物设定',
    'worldview': '世界观设定',
    'plot': '情节脉络',
    'concepts': '关键概念',
    'style': '写作风格参考',
}
STRUCTURED_MEMORY_LIMITS = {
    "global_story_arcs": 10,
    "character_states": 14,
    "relationship_edges": 12,
    "pending_foreshadowings": 12,
    "world_rules_hard_constraints": 10,
}
CANONICAL_STORY_STANCES = frozenset({"主角方", "反派方", "中立方", "亦正亦邪"})
CANONICAL_ROLE_POSITIONS = frozenset({
    "主角",
    "盟友",
    "导师",
    "对手",
    "守护者",
    "情报角色",
    "中立角色",
    "摇摆角色",
    "治疗者",
    "首领",
    "受害者",
    "主线角色",
    "功能角色",
})
GENERIC_ROLE_POSITIONS = frozenset({"盟友", "对手", "中立角色", "摇摆角色", "主线角色", "功能角色"})
