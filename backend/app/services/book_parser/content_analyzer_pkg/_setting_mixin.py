from __future__ import annotations

import os
import json
import asyncio
import logging
import re
from typing import List, Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass
from enum import Enum

from core.unified_llm_client import get_llm_client, UnifiedLLMClient
from core.model_resolution import TaskType
from ..chapter_splitter import ChapterInfo, ChapterType

logger = logging.getLogger(__name__)

# 🛡️ 全局禁用代理配置 - 确保直连API
for proxy_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    if proxy_var in os.environ:
        del os.environ[proxy_var]


class AnalysisType(str, Enum):
    """分析类型"""
    CHARACTERS = "characters"
    WORLDVIEW = "worldview"
    PLOT = "plot"
    STYLE = "style"
    CONCEPTS = "concepts"
    THEMES = "themes"
    CHAPTER_SUMMARY = "chapter_summary"


@dataclass
class ChapterSummary:
    chapter_index: int
    title: str
    summary: str
    characters: List[str]
    key_events: List[str]


@dataclass
class AnalysisResult:
    analysis_type: AnalysisType
    content: Dict[str, Any]
    confidence: float
    chapter_summaries: Optional[List[ChapterSummary]] = None

class SettingMixin:
    def _extract_setting_hint(self, text: str) -> str:
        """从章节开头粗提场景地点。"""
        if not text:
            return ""

        patterns = [
            r'([^\n，。]{2,20}(?:中心|诊所|街区|城区|实验室|办公室|控制室|大厦|酒吧|基地))',
            r'(?:在|来到|走进|进入|穿过)([^\n，。]{2,18})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text[:600])
            if match:
                return match.group(1).strip()[:20]
        return ""

    def _build_fallback_chapter_summary(
        self,
        chapter: ChapterInfo,
        *,
        reason: str = "",
    ) -> Dict[str, Any]:
        """当模型不可用或解析失败时，生成最低可用章节资产。"""
        text = chapter.content or ""
        sentences = self._split_sentences(text)
        key_events: List[str] = []
        for sentence in sentences:
            cleaned = sentence.strip("“”\"'")
            if not cleaned:
                continue
            event = cleaned[:30] + ("..." if len(cleaned) > 30 else "")
            if event not in key_events:
                key_events.append(event)
            if len(key_events) >= 5:
                break

        summary_candidates = sentences[:3]
        if len(sentences) > 4:
            summary_candidates.append(sentences[-1])
        summary = " ".join(summary_candidates).strip()
        if not summary:
            summary = (text[:240] + "...") if len(text) > 240 else text

        characters = self._extract_character_names_from_text(text)
        setting = self._extract_setting_hint(text)

        logger.warning(
            "章节摘要提取回退到规则模式: 第%s章《%s》%s",
            chapter.number,
            chapter.title,
            f"| 原因: {reason}" if reason else "",
        )

        return {
            "chapter_number": chapter.number,
            "title": chapter.title,
            "summary": summary[:400],
            "characters_appeared": characters,
            "key_events": key_events,
            "setting": setting,
            "character_clues": [],
            "scene_goal": f"{setting or '本章场景'}中推进核心事件"[:40],
            "conflict_arc": {
                "trigger": key_events[0] if key_events else "",
                "escalation": key_events[1] if len(key_events) > 1 else "",
                "resolution": key_events[-1] if key_events else "",
            },
            "emotion_curve": "平静→紧张→悬念" if key_events else "",
            "highlight": {"type": "无", "description": "规则兜底摘要，待模型补全", "intensity": "1"},
            "ending_hook": {
                "type": "悬念" if len(key_events) >= 2 else "无",
                "content": key_events[-1] if key_events else "本章需后续补全钩子",
            },
            "gains": {
                "character_gains": "",
                "plot_progress": key_events[0] if key_events else "",
            },
            "foreshadowing": [],
            "conflict": key_events[1] if len(key_events) > 1 else "",
            "emotion_tone": "紧张" if key_events else "",
        }

    def _build_fallback_character_analysis(
        self,
        character_appearances: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """当人物汇总模型不可用时，按章节出场频次生成最小人物体系。"""
        ranked_characters = sorted(
            [
                (name, info)
                for name, info in character_appearances.items()
                if self._is_likely_character_name(name) and (info.get("count") or 0) > 0
            ],
            key=lambda item: (
                -(item[1].get("count") or 0),
                item[1].get("first_chapter") or 10**9,
                item[0],
            ),
        )

        characters: List[Dict[str, Any]] = []
        relationship_pairs: List[Dict[str, str]] = []

        for idx, (name, info) in enumerate(ranked_characters[:12]):
            payload = {
                "name": name,
            "description": f"基于章节出场频次识别的人物，累计出现 {info.get('count', 0)} 章",
            "story_stance": "未提及",
            "role_position": "功能角色",
            "faction": "未提及",
            "first_appearance_chapter": info.get("first_chapter"),
            "appearance_count": info.get("count", 0),
                "importance_score": 1.0 if idx == 0 else round(max(0.3, 1 - idx * 0.08), 2),
            }

            if idx == 0:
                payload["story_stance"] = "主角方"
                payload["role_position"] = "主角"
                payload["importance_level"] = "主角"
                characters.append(payload)
            elif idx <= 2:
                payload["role_position"] = "盟友"
                payload["importance_level"] = "重要角色"
                characters.append(payload)
            else:
                payload["relationship_to_main"] = "与核心剧情相关"
                payload["importance_level"] = "次要角色"
                characters.append(payload)

        if len(characters) >= 2:
            anchor = characters[0]["name"]
            for char in characters[1:3]:
                relationship_pairs.append({
                    "character1": anchor,
                    "character2": char["name"],
                    "relationship": "核心关联人物",
                    "description": "基于章节共同高频出现的启发式关系",
                })

        logger.warning(
            "人物体系分析回退到规则模式: 生成 %s 个候选人物",
            len(characters),
        )

        for char in characters:
            self._infer_character_defaults(char)

        return {
            "characters": characters,
            "character_relationships": relationship_pairs,
            "character_statistics": character_appearances,
        }
    
    # ==================== 阶段1: 逐章提取摘要 ====================
    
