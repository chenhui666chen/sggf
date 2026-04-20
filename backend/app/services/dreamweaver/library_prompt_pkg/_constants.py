from __future__ import annotations

import os
import re
from typing import Any, Dict, Literal, Optional, Tuple

from agents.llm_client import chat_completions, env_flag, extract_json_object, pick_model
from pipeline.media_presets import normalize_frame_ratio
from pipeline.style_presets import (
    normalize_style_preset,
    style_negative_prompt_for_preset,
    style_prompt_for_preset,
)

from app.services.dreamweaver.library import build_library_prompt


LibraryPromptMode = Literal["template", "ai"]

_STYLE_PREFIXES = ("风格：", "风格:", "style:")
_RATIO_PREFIXES = ("画幅：", "画幅:", "比例：", "比例:", "ratio:")
_CHARACTER_BG_REQUIREMENT = "背景要求：纯灰色背景板，背景完全干净，无场景元素、无杂物、无文字、无多余人物。"
_CHARACTER_BACKGROUND_LINE = "背景：纯灰色背景板，背景完全干净，无场景元素、无杂物、无文字、无多余人物。"
_CHARACTER_CONSTRAINT_LINE = "约束：无文字，无水印，无logo，无边框，无拼贴。"
_CHARACTER_ROLE_PREFIXES = {
    "lib_character_portrait",
    "lib_character_portrait_side",
    "lib_character_portrait_back",
    "lib_character_portrait_bust",
    "lib_character_portrait_bust_three_quarter",
    "lib_character_portrait_bust_side",
}


