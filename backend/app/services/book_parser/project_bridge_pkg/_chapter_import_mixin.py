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

class ChapterImportMixin:
    def _import_chapters(
        self,
        project: Project,
        book_id: int,
        start_from: Optional[int] = None
    ):
        """
        导入章节内容
        
        保留原书的章节号和标题格式，如 "第1章：灵草复苏之谜"
        """
        query = self.db.query(BookChapter).filter(BookChapter.book_id == book_id)
        
        if start_from:
            query = query.filter(BookChapter.chapter_number >= start_from)
        
        book_chapters = query.order_by(BookChapter.chapter_number).all()
        
        for i, bch in enumerate(book_chapters):
            # 构建完整的章节标题，保留原书章节号
            formatted_title = self._format_chapter_title(bch.chapter_number, bch.title, bch.chapter_type)
            
            chapter = Chapter(
                project_id=project.id,
                chapter_number=i + 1,
                title=formatted_title,
                content=bch.content,
                summary=bch.summary,
                summary_data=self._build_imported_chapter_summary_data(bch),
                word_count=bch.word_count,
                status='draft',
            )
            self.db.add(chapter)
        
        project.word_count = sum(ch.word_count for ch in book_chapters)
        
        logger.info(f"  → 导入 {len(book_chapters)} 个章节")

    @staticmethod
    def _decode_json_field(raw_value: Any, default: Any) -> Any:
        """
        解析 JSON 字段，失败时回退到默认值。
        """
        if raw_value is None or raw_value == "":
            return default

        if isinstance(raw_value, str):
            try:
                return json.loads(raw_value)
            except json.JSONDecodeError:
                return default

        return raw_value

    @staticmethod
    def _try_parse_json_text(raw_text: Any) -> Optional[Any]:
        """尽量从原始文本中解析出 JSON。"""
        if not isinstance(raw_text, str):
            return None

        text = raw_text.strip()
        if not text:
            return None

        candidates = [text]

        code_block_match = re.search(r"```json\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if code_block_match:
            candidates.append(code_block_match.group(1).strip())

        brace_match = re.search(r"\{[\s\S]*\}", text)
        if brace_match:
            candidates.append(brace_match.group(0).strip())

        for candidate in candidates:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

        return None

    @staticmethod
    def _extract_json_string_field(raw_text: str, field_name: str) -> str:
        """从近似 JSON 文本中提取字符串字段。"""
        if not raw_text:
            return ""

        match = re.search(
            rf'"{re.escape(field_name)}"\s*:\s*"((?:\\.|[^"\\])*)"',
            raw_text,
        )
        if not match:
            return ""

        try:
            return json.loads(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            return match.group(1).strip()

    @classmethod
    def _extract_json_objects_from_array_field(cls, raw_text: str, field_name: str) -> List[Dict[str, Any]]:
        """从截断的 JSON 数组中提取已经完整闭合的对象。"""
        if not raw_text:
            return []

        field_match = re.search(rf'"{re.escape(field_name)}"\s*:\s*\[', raw_text)
        if not field_match:
            return []

        array_text = raw_text[field_match.end():]
        objects: List[Dict[str, Any]] = []
        depth = 0
        start_index: Optional[int] = None
        in_string = False
        escape = False

        for index, char in enumerate(array_text):
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue

            if char == "{":
                if depth == 0:
                    start_index = index
                depth += 1
                continue

            if char == "}":
                if depth == 0:
                    continue
                depth -= 1
                if depth == 0 and start_index is not None:
                    candidate = array_text[start_index:index + 1]
                    parsed = cls._try_parse_json_text(candidate)
                    if isinstance(parsed, dict):
                        objects.append(parsed)
                    start_index = None
                continue

            if char == "]" and depth == 0:
                break

        return objects

    def _recover_plot_content_from_analysis(self, analysis: Optional[BookAnalysis]) -> Dict[str, Any]:
        """在 plot 解析失败时，尽量从原始响应预览中恢复关键结构。"""
        if not analysis:
            return {}

        content = self._decode_json_field(getattr(analysis, "content", None), {})
        if isinstance(content, dict) and content and not content.get("parse_error"):
            return content

        extra_data = self._decode_json_field(getattr(analysis, "extra_data", None), {})
        raw_candidates: List[str] = []

        if isinstance(content, dict):
            raw_response = content.get("raw_response")
            if isinstance(raw_response, str) and raw_response.strip():
                raw_candidates.append(raw_response)

        if isinstance(extra_data, dict):
            for key in ("raw_response", "raw_response_preview"):
                raw_text = extra_data.get(key)
                if isinstance(raw_text, str) and raw_text.strip():
                    raw_candidates.append(raw_text)

        for raw_text in raw_candidates:
            parsed = self._try_parse_json_text(raw_text)
            if isinstance(parsed, dict) and parsed:
                logger.warning("plot分析包含 parse_error 标记，已从原始响应中恢复完整 JSON")
                return parsed

        recovered: Dict[str, Any] = {}
        for raw_text in raw_candidates:
            main_plot = self._extract_json_string_field(raw_text, "main_plot")
            if main_plot and not self._normalize_memory_text(recovered.get("main_plot")):
                recovered["main_plot"] = main_plot

            for field_name in ("plot_arcs", "turning_points"):
                if recovered.get(field_name):
                    continue
                items = self._extract_json_objects_from_array_field(raw_text, field_name)
                if items:
                    recovered[field_name] = items

        if recovered:
            logger.warning("plot分析包含 parse_error 标记，已从原始响应预览中恢复部分结构")

        return recovered

    def _build_plot_fallback_content_from_chapters(self, book_id: int) -> Dict[str, Any]:
        """基于章节摘要生成最小可用的大纲结构。"""
        book_chapters = self.db.query(BookChapter).filter(
            BookChapter.book_id == book_id
        ).order_by(BookChapter.chapter_number).all()

        chapter_snapshots: List[Dict[str, Any]] = []
        for chapter in book_chapters:
            summary = str(chapter.summary or "").strip()

            if not summary:
                outline_data = self._decode_json_field(chapter.outline_data, {})
                if isinstance(outline_data, dict):
                    summary = self._normalize_memory_text(
                        outline_data.get("core_summary") or outline_data.get("scene_goal")
                    )
                    if not summary:
                        ending_hook = outline_data.get("ending_hook")
                        if isinstance(ending_hook, dict):
                            summary = self._normalize_memory_text(
                                ending_hook.get("content")
                                or ending_hook.get("summary")
                                or ending_hook.get("hook")
                            )

            if not summary:
                summary = str(chapter.title or "").strip()

            if not summary:
                continue

            chapter_snapshots.append(
                {
                    "chapter": chapter.chapter_number,
                    "summary": summary,
                }
            )

        if not chapter_snapshots:
            main_plot = "拆书情节分析解析失败，当前已回退为最小可用大纲，建议重新提取以获得更完整的情节脉络。"
            return {
                "main_plot": main_plot,
                "concept": {"summary": main_plot},
                "plot_arcs": [
                    {
                        "name": "主线推进",
                        "description": "当前仅保留兜底大纲，后续可重新执行情节分析补全主线、转折与结局设计。",
                        "type": "兜底",
                    }
                ],
                "turning_points": [],
                "chapter_summaries": [],
            }

        first_snapshot = chapter_snapshots[0]
        last_snapshot = chapter_snapshots[-1]

        if first_snapshot["chapter"] == last_snapshot["chapter"]:
            main_plot = f"故事围绕第{first_snapshot['chapter']}章展开：{first_snapshot['summary']}"
        else:
            main_plot = (
                f"故事从第{first_snapshot['chapter']}章的“{first_snapshot['summary']}”展开，"
                f"并逐步推进至第{last_snapshot['chapter']}章的“{last_snapshot['summary']}”。"
            )

        plot_arcs: List[Dict[str, Any]] = [
            {
                "name": "开篇引子",
                "description": first_snapshot["summary"],
                "chapters": [first_snapshot["chapter"], first_snapshot["chapter"]],
                "type": "开端",
            }
        ]

        if len(chapter_snapshots) >= 3:
            middle_snapshot = chapter_snapshots[len(chapter_snapshots) // 2]
            if middle_snapshot["chapter"] not in {first_snapshot["chapter"], last_snapshot["chapter"]}:
                plot_arcs.append(
                    {
                        "name": "中段升级",
                        "description": middle_snapshot["summary"],
                        "chapters": [middle_snapshot["chapter"], middle_snapshot["chapter"]],
                        "type": "发展",
                    }
                )

        if last_snapshot["chapter"] != first_snapshot["chapter"]:
            plot_arcs.append(
                {
                    "name": "结局收束",
                    "description": last_snapshot["summary"],
                    "chapters": [last_snapshot["chapter"], last_snapshot["chapter"]],
                    "type": "结局",
                }
            )
        else:
            plot_arcs[0]["name"] = "主线推进"
            plot_arcs[0]["type"] = "主线"

        candidate_indices = [0]
        if len(chapter_snapshots) >= 4:
            candidate_indices.extend([len(chapter_snapshots) // 3, (len(chapter_snapshots) * 2) // 3])
        elif len(chapter_snapshots) >= 3:
            candidate_indices.append(len(chapter_snapshots) // 2)
        if len(chapter_snapshots) >= 2:
            candidate_indices.append(len(chapter_snapshots) - 1)

        turning_points: List[Dict[str, Any]] = []
        labels = ["故事开端", "局势升级", "关键转折", "结局收束"]
        unique_indices: List[int] = []
        seen_indices = set()
        for index in candidate_indices:
            normalized_index = max(0, min(index, len(chapter_snapshots) - 1))
            if normalized_index in seen_indices:
                continue
            seen_indices.add(normalized_index)
            unique_indices.append(normalized_index)

        for label, index in zip(labels, unique_indices):
            snapshot = chapter_snapshots[index]
            turning_points.append(
                {
                    "chapter": snapshot["chapter"],
                    "event": snapshot["summary"],
                    "significance": label,
                }
            )

        chapter_summaries = [
            f"第{snapshot['chapter']}章：{snapshot['summary']}"
            for snapshot in chapter_snapshots[:12]
        ]

        return {
            "main_plot": main_plot,
            "concept": {"summary": main_plot},
            "plot_arcs": plot_arcs,
            "turning_points": turning_points,
            "chapter_summaries": chapter_summaries,
        }

    def _merge_plot_content(self, primary: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
        """用章节级兜底补齐 plot 核心字段，确保大纲可生成。"""
        merged = dict(primary or {})

        if not self._normalize_memory_text(merged.get("main_plot")):
            merged["main_plot"] = fallback.get("main_plot", "")

        for field_name in ("plot_arcs", "turning_points", "chapter_summaries"):
            current_value = merged.get(field_name)
            if isinstance(current_value, list) and current_value:
                continue
            fallback_value = fallback.get(field_name) or []
            if fallback_value:
                merged[field_name] = fallback_value

        concept = merged.get("concept")
        fallback_concept = fallback.get("concept")
        if not isinstance(concept, dict):
            if isinstance(fallback_concept, dict) and fallback_concept:
                merged["concept"] = dict(fallback_concept)
        elif isinstance(fallback_concept, dict):
            summary = self._normalize_memory_text(concept.get("summary"))
            if not summary:
                fallback_summary = self._normalize_memory_text(fallback_concept.get("summary"))
                if fallback_summary:
                    concept["summary"] = fallback_summary

        return merged

    def _load_plot_content_with_fallback(
        self,
        analysis_map: Dict[str, BookAnalysis],
        book_id: int,
    ) -> Dict[str, Any]:
        """为 plot 提供恢复与兜底后的可用结构。"""
        analysis = analysis_map.get("plot")
        if not analysis:
            return {}

        fallback = self._build_plot_fallback_content_from_chapters(book_id)
        content = self._load_analysis_content(analysis_map, "plot")
        if isinstance(content, dict) and content:
            return self._merge_plot_content(content, fallback)

        recovered = self._recover_plot_content_from_analysis(analysis)
        if recovered:
            logger.warning("plot分析解析失败，已使用原始响应恢复并补齐大纲内容")
        else:
            logger.warning("plot分析解析失败，已使用章节摘要生成最小可用大纲")

        return self._merge_plot_content(recovered, fallback)

    def _build_imported_chapter_summary_data(self, book_chapter: BookChapter) -> Optional[str]:
        """
        将拆书章节的摘要/细纲信息转换为项目章节可直接复用的结构化摘要。
        """
        summary_data: Dict[str, Any] = {}

        outline_data = self._decode_json_field(book_chapter.outline_data, {})
        if isinstance(outline_data, dict):
            summary_data.update(outline_data)

        key_events = self._decode_json_field(book_chapter.key_events, [])
        if isinstance(key_events, list) and key_events:
            summary_data["key_events"] = key_events

        appearing_characters = self._decode_json_field(book_chapter.appearing_characters, [])
        if isinstance(appearing_characters, list) and appearing_characters:
            summary_data["appearing_characters"] = appearing_characters

        if book_chapter.summary:
            summary_data.setdefault("core_summary", book_chapter.summary)

        summary_data["source"] = "book_parser"
        summary_data["original_chapter_number"] = book_chapter.chapter_number
        summary_data["original_title"] = book_chapter.title

        if book_chapter.chapter_type and book_chapter.chapter_type != "normal":
            summary_data["original_chapter_type"] = book_chapter.chapter_type
        if book_chapter.volume_number is not None:
            summary_data["original_volume_number"] = book_chapter.volume_number
        if book_chapter.volume_title:
            summary_data["original_volume_title"] = book_chapter.volume_title

        summary_data = attach_cross_media_adaptation_hints(
            summary_data,
            chapter_title=book_chapter.title or "",
            chapter_summary=book_chapter.summary or "",
        )

        return json.dumps(summary_data, ensure_ascii=False) if summary_data else None
    
    def _format_chapter_title(self, chapter_number: int, title: str, chapter_type: str = 'normal') -> str:
        """
        格式化章节标题，保留原书章节号
        
        Args:
            chapter_number: 原书章节号
            title: 原书章节标题
            chapter_type: 章节类型 (normal/prologue/epilogue/extra/interlude)
            
        Returns:
            格式化后的标题，如 "第1章：灵草复苏之谜"
        """
        # 处理特殊章节类型
        if chapter_type == 'prologue':
            prefix = '序章'
        elif chapter_type == 'epilogue':
            prefix = '尾声'
        elif chapter_type == 'extra':
            prefix = f'番外{chapter_number}'
        elif chapter_type == 'interlude':
            prefix = f'幕间{chapter_number}'
        else:
            prefix = f'第{chapter_number}章'
        
        # 如果标题已经包含章节前缀，提取纯标题部分
        clean_title = self._extract_pure_title(title)
        
        # 组合标题
        if clean_title:
            return f"{prefix}：{clean_title}"
        else:
            return prefix
    
    def _extract_pure_title(self, title: str) -> str:
        """
        从标题中提取纯标题部分，去除章节号前缀
        
        如 "第一章 灵草复苏之谜" -> "灵草复苏之谜"
        """
        import re
        
        # 匹配并移除常见的章节前缀
        patterns = [
            r'^第[一二三四五六七八九十百千万\d]+[章节回][：:\s]*',  # 第X章：
            r'^[Cc]hapter\s*\d+[：:\s.]*',  # Chapter 1:
            r'^\d+[.、][\s]*',  # 1. 或 1、
            r'^序章[：:\s]*',
            r'^尾声[：:\s]*',
            r'^番外\d*[：:\s]*',
            r'^幕间\d*[：:\s]*',
        ]
        
        result = title.strip()
        for pattern in patterns:
            result = re.sub(pattern, '', result, flags=re.IGNORECASE)
        
        return result.strip()
