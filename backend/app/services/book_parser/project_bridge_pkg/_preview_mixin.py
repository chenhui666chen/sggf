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

from app.services.book_parser.project_bridge_pkg._constants import (
    ANALYSIS_TO_COLLECTION,
    STRUCTURED_MEMORY_LIMITS,
    CANONICAL_STORY_STANCES,
    CANONICAL_ROLE_POSITIONS,
    GENERIC_ROLE_POSITIONS,
)

class PreviewMixin:
    def get_import_preview(self, book_id: int) -> Dict[str, Any]:
        """
        获取导入预览信息
        """
        book = self.db.query(BookSource).filter(BookSource.id == book_id).first()
        if not book:
            return {"error": "书籍不存在"}
        
        analyses = self.db.query(BookAnalysis).filter(
            BookAnalysis.book_id == book_id
        ).all()
        
        chapters_count = self.db.query(BookChapter).filter(
            BookChapter.book_id == book_id
        ).count()
        
        preview = {
            "book": {
                "id": book.id,
                "title": book.title,
                "author": book.author,
                "total_words": book.total_words,
                "total_chapters": chapters_count,
            },
            "analyses": [],
            "import_options": {
                "characters": False,
                "worldview": False,
                "plot": False,
                "concepts": False,
            }
        }
        
        for a in analyses:
            content = self._load_analysis_payload(
                a,
                log_context=f"{self.ANALYSIS_TO_COLLECTION.get(a.analysis_type, a.analysis_type)}预览",
            )
            item_count = self._count_items(a.analysis_type, content) if content else 0
            extra_data = self._decode_json_field(getattr(a, "extra_data", None), {})
             
            preview["analyses"].append({
                "type": a.analysis_type,
                "type_name": self.ANALYSIS_TO_COLLECTION.get(a.analysis_type, a.analysis_type),
                "confidence": a.confidence,
                "item_count": item_count,
                "quality_warning": extra_data.get("quality_warning") if isinstance(extra_data, dict) else None,
            })
             
            if a.analysis_type in preview["import_options"] and item_count > 0:
                preview["import_options"][a.analysis_type] = True
        
        return preview
    
    def _count_items(self, analysis_type: str, content: Dict) -> int:
        """统计分析结果中的项目数量"""
        if analysis_type == 'characters':
            return len(self._get_character_entries(content))
        elif analysis_type == 'worldview':
            return (
                len(content.get('locations', [])) +
                len(content.get('power_systems', [])) +
                len(content.get('factions', []))
            )
        elif analysis_type == 'plot':
            return len(content.get('plot_arcs', [])) + len(content.get('turning_points', []))
        elif analysis_type == 'concepts':
            return len(content.get('terms', []))
        return 0

    def _load_analysis_payload(self, analysis: Optional[BookAnalysis], log_context: str = "分析结果") -> Dict[str, Any]:
        """安全加载单个分析结果，跳过低质量或解析失败的内容。"""
        if not analysis:
            return {}

        try:
            content = json.loads(analysis.content) if isinstance(analysis.content, str) else analysis.content
        except Exception:
            logger.warning(f"{log_context}解析失败，已跳过")
            return {}

        if not isinstance(content, dict):
            return {}

        extra_data = self._decode_json_field(getattr(analysis, "extra_data", None), {})
        parse_error = bool(content.get("parse_error")) or (
            isinstance(extra_data, dict) and bool(extra_data.get("parse_error"))
        )
        if parse_error:
            logger.warning(f"{log_context}包含 parse_error 标记，已跳过导入")
            return {}

        return content

    def _load_analysis_content(self, analysis_map: Dict[str, BookAnalysis], analysis_type: str) -> Dict[str, Any]:
        """安全加载分析结果 JSON。"""
        analysis = analysis_map.get(analysis_type)
        return self._load_analysis_payload(analysis, log_context=analysis_type)

    @staticmethod
    def _normalize_memory_text(value: Any) -> str:
        """将任意值规范为单行记忆文本。"""
        if value is None:
            return ""
        if isinstance(value, list):
            parts = [str(item).strip() for item in value if str(item).strip()]
            return "；".join(parts)
        return str(value).strip()

    @classmethod
    def _clean_memory_line(cls, text: str, max_length: int = 120) -> str:
        """清理并裁剪结构化记忆行。"""
        cleaned = " ".join(str(text or "").split()).strip(" -")
        if not cleaned:
            return ""
        if len(cleaned) > max_length:
            return cleaned[: max_length - 3].rstrip() + "..."
        return cleaned

    @classmethod
    def _deduplicate_memory_items(cls, items: List[str], limit: int) -> List[str]:
        """保持顺序去重，并按类别上限裁剪。"""
        result: List[str] = []
        seen = set()

        for item in items:
            normalized = cls._clean_memory_line(item)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
            if len(result) >= limit:
                break

        return result

    def _render_structured_memory_text(self, structured_memory: Dict[str, List[str]]) -> str:
        """渲染与工作流兼容的结构化记忆文本。"""
        category_labels = [
            ("global_story_arcs", "主线弧线"),
            ("character_states", "人物状态"),
            ("relationship_edges", "关系边"),
            ("pending_foreshadowings", "待回收伏笔"),
            ("world_rules_hard_constraints", "世界规则硬约束"),
        ]

        parts: List[str] = ["【结构化记忆】"]
        for key, label in category_labels:
            values = structured_memory.get(key) or []
            if not values:
                continue
            parts.append(f"- {label}:")
            for value in values:
                parts.append(f"  - {value}")

        return "\n".join(parts).strip()

    @staticmethod
    def _parse_plot_outline_chapter_number(value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            chapter_number = int(value)
            return chapter_number if chapter_number > 0 else None

        match = re.search(r"\d+", str(value))
        if not match:
            return None

        chapter_number = int(match.group(0))
        return chapter_number if chapter_number > 0 else None

    @classmethod
    def _normalize_plot_outline_title(cls, value: Any, *, default: str) -> str:
        title = str(value or "").strip()
        title = re.sub(
            r"^第\s*[0-9一二三四五六七八九十百千两零〇]+\s*章[：:\-\s]*",
            "",
            title,
        ).strip()
        title = title.strip("《》【】[]()（）-:： ")
        title = re.split(r"[。！？!?；;\n]", title)[0].strip()
        title = cls._clean_memory_line(title, max_length=24)
        return title or default

    @classmethod
    def _normalize_plot_outline_item_list(cls, value: Any, *, limit: int = 6) -> List[str]:
        raw_items = value if isinstance(value, list) else [value]
        items: List[str] = []

        for raw_item in raw_items:
            if isinstance(raw_item, dict):
                text_parts = [
                    cls._normalize_memory_text(raw_item.get(key))
                    for key in ("content", "description", "summary", "event", "name")
                ]
                text = "；".join(part for part in text_parts if part)
            else:
                text = cls._normalize_memory_text(raw_item)

            if not text:
                continue

            for line in str(text).splitlines():
                normalized = re.sub(r"^\d+\s*[.、]\s*", "", line.strip())
                if normalized:
                    items.append(normalized)

        return cls._deduplicate_memory_items(items, limit=limit)

    @classmethod
    def _format_book_parser_conflict_design(cls, conflict_arc: Any, fallback: Any = "") -> str:
        fallback_text = cls._normalize_memory_text(fallback)
        if fallback_text:
            return fallback_text

        if not isinstance(conflict_arc, dict):
            return cls._normalize_memory_text(conflict_arc)

        pieces: List[str] = []
        for key, label in (
            ("type", "冲突类型"),
            ("trigger", "起因"),
            ("escalation", "升级"),
            ("resolution", "结果"),
            ("result", "结果"),
            ("description", "说明"),
            ("stakes", "代价"),
            ("obstacle", "阻碍"),
        ):
            text = cls._normalize_memory_text(conflict_arc.get(key))
            if text:
                pieces.append(f"{label}：{text}")

        return "；".join(dict.fromkeys(pieces))

    @classmethod
    def _format_book_parser_highlight(cls, highlight: Any) -> str:
        if not isinstance(highlight, dict):
            return cls._normalize_memory_text(highlight)

        type_text = cls._normalize_memory_text(highlight.get("type"))
        description = cls._normalize_memory_text(
            highlight.get("description") or highlight.get("content")
        )
        intensity = cls._normalize_memory_text(highlight.get("intensity"))

        parts: List[str] = []
        if type_text and type_text != "无":
            parts.append(type_text)
        if description:
            parts.append(f"内容：{description}")
        if intensity and intensity not in {"0", "无"}:
            parts.append(f"强度：{intensity}")

        if parts:
            return "；".join(parts)
        return type_text

    @classmethod
    def _format_book_parser_ending_hook(cls, ending_hook: Any) -> str:
        if not isinstance(ending_hook, dict):
            return cls._normalize_memory_text(ending_hook)

        hook_type = cls._normalize_memory_text(ending_hook.get("type"))
        hook_content = cls._normalize_memory_text(
            ending_hook.get("content")
            or ending_hook.get("summary")
            or ending_hook.get("hook")
        )

        if hook_type and hook_type != "无" and hook_content:
            return f"{hook_type} / {hook_content}"
        return hook_content or hook_type

    @classmethod
    def _format_book_parser_gains(cls, gains: Any, *, prefer: str) -> str:
        if not isinstance(gains, dict):
            return cls._normalize_memory_text(gains)

        character_gains = cls._normalize_memory_text(
            gains.get("character_gains")
            or gains.get("character_growth")
            or gains.get("relationship_change")
            or gains.get("status_change")
        )
        plot_progress = cls._normalize_memory_text(
            gains.get("plot_progress")
            or gains.get("information_gain")
            or gains.get("clue_progress")
        )

        if prefer == "character":
            return character_gains or plot_progress
        if prefer == "information":
            parts: List[str] = []
            if character_gains:
                parts.append(f"角色收获：{character_gains}")
            if plot_progress:
                parts.append(f"主线推进：{plot_progress}")
            if parts:
                return "；".join(parts)

        fallback_parts = [
            cls._normalize_memory_text(value)
            for value in gains.values()
        ]
        fallback_parts = [part for part in fallback_parts if part]
        return "；".join(dict.fromkeys(fallback_parts))

    @classmethod
    def _infer_plot_outline_function(
        cls,
        chapter_index: int,
        total_chapters: int,
        *,
        has_hook: bool,
        has_foreshadowing: bool,
    ) -> str:
        if total_chapters <= 1:
            return "概括当前章节的核心推进，并为后续延展保留空间。"
        if chapter_index == 0:
            return "开篇立题，建立基础局势与核心矛盾。"
        if chapter_index == total_chapters - 1:
            return "阶段收束并抛出后续升级钩子。" if has_hook else "阶段收束，完成当前阶段结果交代。"
        if has_hook or has_foreshadowing:
            return "承接前文并推进主线，同时埋设后续升级点。"
        return "承接前文并推进当前主线。"

    def _build_plot_outline_blocks_from_book_chapters(self, book_id: int) -> List[Dict[str, Any]]:
        book_chapters = self.db.query(BookChapter).filter(
            BookChapter.book_id == book_id
        ).order_by(BookChapter.chapter_number).all()

        total_chapters = len(book_chapters)
        blocks: List[Dict[str, Any]] = []

        for index, chapter in enumerate(book_chapters):
            outline_data = self._decode_json_field(chapter.outline_data, {})
            outline_data = outline_data if isinstance(outline_data, dict) else {}

            summary = self._normalize_memory_text(chapter.summary)
            key_events = self._normalize_plot_outline_item_list(
                self._decode_json_field(chapter.key_events, [])
            )
            appearing_characters = self._normalize_plot_outline_item_list(
                self._decode_json_field(chapter.appearing_characters, [])
            )

            scene_goal = self._normalize_memory_text(outline_data.get("scene_goal")) or summary
            if not scene_goal:
                scene_goal = f"围绕第{chapter.chapter_number}章核心事件推进当前主线。"

            conflict_design = self._format_book_parser_conflict_design(
                outline_data.get("conflict_arc"),
                fallback=outline_data.get("conflict"),
            )
            highlight_type = self._format_book_parser_highlight(outline_data.get("highlight")) or "待补充"
            involved_characters = "、".join(appearing_characters) or "待补充"
            character_progress = self._format_book_parser_gains(
                outline_data.get("gains"),
                prefer="character",
            )
            plot_progress_hint = self._format_book_parser_gains(
                outline_data.get("gains"),
                prefer="information",
            )
            ending_hook = self._format_book_parser_ending_hook(outline_data.get("ending_hook")) or "无"
            foreshadowing_item = "；".join(
                self._normalize_plot_outline_item_list(outline_data.get("foreshadowing"))
            ) or "无"

            if not key_events and summary:
                key_events = [summary]

            if not conflict_design:
                conflict_design = summary or scene_goal
            if not character_progress:
                if involved_characters != "待补充":
                    character_progress = f"{involved_characters}在本章的状态或关系出现推进。"
                else:
                    character_progress = "主角与关键角色的状态出现阶段性变化。"
            plot_function = self._normalize_memory_text(outline_data.get("plot_function"))
            if not plot_function:
                plot_function = plot_progress_hint or self._infer_plot_outline_function(
                    index,
                    total_chapters,
                    has_hook=ending_hook != "无",
                    has_foreshadowing=foreshadowing_item != "无",
                )

            blocks.append(
                {
                    "chapter_number": int(chapter.chapter_number or index + 1),
                    "title": self._normalize_plot_outline_title(
                        chapter.title,
                        default=f"章节推进{chapter.chapter_number or index + 1}",
                    ),
                    "scene_goal": scene_goal,
                    "conflict_design": conflict_design,
                    "highlight_type": highlight_type,
                    "involved_characters": involved_characters,
                    "character_progress": character_progress,
                    "plot_function": plot_function,
                    "ending_hook": ending_hook,
                    "foreshadowing_item": foreshadowing_item,
                    "key_events": key_events,
                }
            )

        return blocks

    def _build_plot_outline_blocks_from_plot_content(self, content: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(content, dict) or not content:
            return []

        main_plot = self._normalize_memory_text(content.get("main_plot"))
        if not main_plot:
            concept = content.get("concept") or {}
            if isinstance(concept, dict):
                main_plot = self._normalize_memory_text(
                    concept.get("summary") or concept.get("logline")
                )

        blocks_by_chapter: Dict[int, Dict[str, Any]] = {}

        def ensure_block(chapter_number: int, default_title: str) -> Dict[str, Any]:
            block = blocks_by_chapter.setdefault(
                chapter_number,
                {
                    "chapter_number": chapter_number,
                    "title": "",
                    "scene_goal": "",
                    "conflict_design": "",
                    "highlight_type": "",
                    "involved_characters": "",
                    "character_progress": "",
                    "plot_function": "",
                    "ending_hook": "",
                    "foreshadowing_item": "",
                    "key_events": [],
                },
            )
            if default_title and not block["title"]:
                block["title"] = default_title
            return block

        chapter_summaries = content.get("chapter_summaries") or []
        for index, raw_item in enumerate(chapter_summaries, start=1):
            if isinstance(raw_item, dict):
                chapter_number = (
                    self._parse_plot_outline_chapter_number(
                        raw_item.get("chapter") or raw_item.get("chapter_number")
                    )
                    or index
                )
                summary_text = self._normalize_memory_text(
                    raw_item.get("summary")
                    or raw_item.get("content")
                    or raw_item.get("title")
                )
                title_source = raw_item.get("title") or summary_text
            else:
                summary_text = self._normalize_memory_text(raw_item)
                if not summary_text:
                    continue
                match = re.match(r"^第\s*(\d+)\s*章[：:]\s*(.+)$", summary_text)
                if match:
                    chapter_number = int(match.group(1))
                    summary_text = match.group(2).strip()
                else:
                    chapter_number = index
                title_source = summary_text

            if not summary_text:
                continue

            block = ensure_block(
                chapter_number,
                self._normalize_plot_outline_title(
                    title_source,
                    default=f"章节推进{chapter_number}",
                ),
            )
            if not block["scene_goal"]:
                block["scene_goal"] = summary_text
            if not block["plot_function"]:
                block["plot_function"] = summary_text or "概括该章节的阶段推进与结果。"
            if not block["key_events"]:
                block["key_events"].append(summary_text)

        normalized_turning_points: List[Dict[str, Any]] = []
        for index, raw_turning_point in enumerate(content.get("turning_points") or [], start=1):
            turning_point = raw_turning_point if isinstance(raw_turning_point, dict) else {"event": raw_turning_point}
            event_text = self._normalize_memory_text(turning_point.get("event"))
            significance = self._normalize_memory_text(turning_point.get("significance"))
            if not event_text and not significance:
                continue

            chapter_number = self._parse_plot_outline_chapter_number(turning_point.get("chapter")) or index
            block = ensure_block(
                chapter_number,
                self._normalize_plot_outline_title(
                    event_text or significance,
                    default=f"关键转折{index}",
                ),
            )
            if not block["scene_goal"]:
                block["scene_goal"] = event_text or significance or main_plot
            if not block["conflict_design"]:
                block["conflict_design"] = significance or event_text or main_plot
            if not block["highlight_type"]:
                block["highlight_type"] = "关键转折 / 局势升级"
            if not block["plot_function"]:
                block["plot_function"] = significance or "推动主线进入下一阶段。"
            if event_text:
                block["key_events"].append(event_text)

            normalized_turning_points.append(
                {
                    "chapter_number": chapter_number,
                    "event": event_text,
                    "significance": significance,
                }
            )

        for index, item in enumerate(normalized_turning_points):
            block = blocks_by_chapter.get(item["chapter_number"])
            if not block or block["ending_hook"]:
                continue
            next_event = ""
            if index + 1 < len(normalized_turning_points):
                next_event = normalized_turning_points[index + 1]["event"]
            block["ending_hook"] = next_event or item["significance"] or main_plot

        for index, raw_arc in enumerate(content.get("plot_arcs") or [], start=1):
            arc = raw_arc if isinstance(raw_arc, dict) else {"name": raw_arc}
            arc_name = self._normalize_memory_text(arc.get("name"))
            arc_description = self._normalize_memory_text(arc.get("description"))
            arc_type = self._normalize_memory_text(arc.get("type"))
            chapters = arc.get("chapters") or []
            start_chapter = (
                self._parse_plot_outline_chapter_number(chapters[0])
                if isinstance(chapters, list) and chapters
                else None
            ) or index
            end_chapter = (
                self._parse_plot_outline_chapter_number(chapters[1])
                if isinstance(chapters, list) and len(chapters) >= 2
                else None
            ) or start_chapter

            block = ensure_block(
                start_chapter,
                self._normalize_plot_outline_title(
                    arc_name or arc_description,
                    default=f"主线推进{start_chapter}",
                ),
            )
            if not block["scene_goal"]:
                block["scene_goal"] = arc_description or arc_name or main_plot
            if not block["conflict_design"]:
                block["conflict_design"] = arc_description or arc_type or main_plot
            if not block["highlight_type"]:
                block["highlight_type"] = arc_type or arc_name or "主线推进"
            if not block["plot_function"]:
                plot_function_parts = [part for part in (arc_name, arc_type) if part]
                if end_chapter != start_chapter:
                    plot_function_parts.append(f"覆盖第{start_chapter}-{end_chapter}章")
                block["plot_function"] = " / ".join(plot_function_parts) or "承接前文并推进主线。"
            if not block["ending_hook"] and end_chapter != start_chapter:
                block["ending_hook"] = f"该段剧情将推进至第{end_chapter}章。"

        if not blocks_by_chapter and main_plot:
            block = ensure_block(
                1,
                self._normalize_plot_outline_title(main_plot, default="主线开启"),
            )
            block["scene_goal"] = main_plot
            block["conflict_design"] = main_plot
            block["plot_function"] = main_plot
            block["key_events"].append(main_plot)

        chapter_numbers = sorted(blocks_by_chapter.keys())
        rendered_blocks: List[Dict[str, Any]] = []

        for index, chapter_number in enumerate(chapter_numbers):
            raw_block = blocks_by_chapter[chapter_number]
            next_block = blocks_by_chapter.get(chapter_numbers[index + 1]) if index + 1 < len(chapter_numbers) else None
            scene_goal = raw_block["scene_goal"] or main_plot or f"推进第{chapter_number}章主线。"
            conflict_design = raw_block["conflict_design"] or scene_goal
            ending_hook = raw_block["ending_hook"]
            if not ending_hook and next_block:
                ending_hook = f"下一节点：{next_block['title']}"
            if not ending_hook:
                ending_hook = main_plot or "无"

            rendered_blocks.append(
                {
                    "chapter_number": chapter_number,
                    "title": self._normalize_plot_outline_title(
                        raw_block["title"],
                        default=f"章节推进{chapter_number}",
                    ),
                    "scene_goal": scene_goal,
                    "conflict_design": conflict_design,
                    "highlight_type": raw_block["highlight_type"] or "待补充",
                    "involved_characters": raw_block["involved_characters"] or "待补充",
                    "character_progress": raw_block["character_progress"] or "待补充",
                    "plot_function": raw_block["plot_function"] or self._infer_plot_outline_function(
                        index,
                        len(chapter_numbers),
                        has_hook=bool(ending_hook and ending_hook != "无"),
                        has_foreshadowing=False,
                    ),
                    "ending_hook": ending_hook,
                    "foreshadowing_item": raw_block["foreshadowing_item"] or "无",
                    "key_events": self._deduplicate_memory_items(
                        raw_block["key_events"] or [scene_goal],
                        limit=5,
                    ),
                }
            )

        return rendered_blocks

    def _build_plot_outline_text(self, analysis_map: Dict[str, BookAnalysis], book_id: int) -> str:
        """生成与大纲扩展一致的章节细纲文本。"""
        content = self._load_plot_content_with_fallback(analysis_map, book_id)
        if not isinstance(content, dict) or not content:
            return ""

        main_plot = self._normalize_memory_text(content.get("main_plot"))
        if not main_plot:
            concept = content.get("concept") or {}
            if isinstance(concept, dict):
                main_plot = self._normalize_memory_text(
                    concept.get("summary") or concept.get("logline")
                )

        blocks = self._build_plot_outline_blocks_from_book_chapters(book_id)
        if not blocks:
            blocks = self._build_plot_outline_blocks_from_plot_content(content)

        if not blocks:
            return f"故事总纲：{main_plot}" if main_plot else ""

        parts: List[str] = []
        if main_plot:
            parts.append(f"故事总纲：{main_plot}")
            parts.append("")

        for block in blocks:
            chapter_number = int(block.get("chapter_number") or 0) or 1
            title = self._normalize_plot_outline_title(
                block.get("title"),
                default=f"章节推进{chapter_number}",
            )
            key_events = self._normalize_plot_outline_item_list(
                block.get("key_events"),
                limit=5,
            ) or ["待补充"]
            parts.append(f"第{chapter_number}章：{title}")
            parts.append(f"- 场景目标：{self._normalize_memory_text(block.get('scene_goal')) or '待补充'}")
            parts.append(f"- 冲突设计：{self._normalize_memory_text(block.get('conflict_design')) or '待补充'}")
            parts.append("- 关键事件：")
            for event_index, event in enumerate(key_events, start=1):
                parts.append(f"  {event_index}. {event}")
            parts.append(f"- 涉及人物：{self._normalize_memory_text(block.get('involved_characters')) or '待补充'}")
            parts.append(f"- 人物推进：{self._normalize_memory_text(block.get('character_progress')) or '待补充'}")
            parts.append(f"- 情节作用：{self._normalize_memory_text(block.get('plot_function')) or '待补充'}")
            parts.append(f"- 结尾钩子：{self._normalize_memory_text(block.get('ending_hook')) or '无'}")
            highlight_type = self._normalize_memory_text(block.get('highlight_type'))
            if highlight_type:
                parts.append(f"- 爽点类型：{highlight_type}")
            foreshadowing_item = self._normalize_memory_text(block.get('foreshadowing_item'))
            if foreshadowing_item:
                parts.append(f"- 伏笔事项：{foreshadowing_item}")
            parts.append("")

        return "\n".join(parts).strip()
