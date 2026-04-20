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

class MemoryMixin:
    def _build_import_structured_memory_payload(
        self,
        analysis_map: Dict[str, BookAnalysis],
        book: BookSource,
    ) -> Optional[Dict[str, Any]]:
        """基于拆书结果构建可直接用于工作流的结构化记忆。"""
        plot_content = self._load_plot_content_with_fallback(analysis_map, book.id)
        character_content = self._load_analysis_content(analysis_map, 'characters')
        worldview_content = self._load_analysis_content(analysis_map, 'worldview')
        concepts_content = self._load_analysis_content(analysis_map, 'concepts')

        book_chapters = self.db.query(BookChapter).filter(
            BookChapter.book_id == book.id
        ).order_by(BookChapter.chapter_number).all()

        global_story_arcs: List[str] = []
        main_plot = self._normalize_memory_text(plot_content.get('main_plot'))
        if main_plot:
            global_story_arcs.append(f"主线：{main_plot}")

        for arc in (plot_content.get('plot_arcs') or [])[:6]:
            if not isinstance(arc, dict):
                continue
            name = self._normalize_memory_text(arc.get('name')) or "未命名剧情弧"
            arc_desc = self._normalize_memory_text(arc.get('description'))
            chapters = arc.get('chapters') or []
            meta_parts = []
            if isinstance(chapters, list) and len(chapters) >= 2:
                meta_parts.append(f"第{chapters[0]}-{chapters[1]}章")
            arc_type = self._normalize_memory_text(arc.get('type'))
            if arc_type:
                meta_parts.append(arc_type)
            meta_text = f"（{' / '.join(meta_parts)}）" if meta_parts else ""
            global_story_arcs.append(f"{name}{meta_text}：{arc_desc}" if arc_desc else f"{name}{meta_text}")

        for tp in (plot_content.get('turning_points') or [])[:4]:
            if not isinstance(tp, dict):
                continue
            chapter = self._normalize_memory_text(tp.get('chapter'))
            event = self._normalize_memory_text(tp.get('event'))
            significance = self._normalize_memory_text(tp.get('significance'))
            title = f"第{chapter}章转折" if chapter else "关键转折"
            detail = "；".join([item for item in [event, significance] if item])
            if detail:
                global_story_arcs.append(f"{title}：{detail}")

        if not global_story_arcs:
            for chapter in (book_chapters[:2] + book_chapters[-2:]):
                if chapter.summary:
                    global_story_arcs.append(f"第{chapter.chapter_number}章：{chapter.summary}")

        character_states: List[str] = []
        for char in self._get_character_entries(character_content):
            if not isinstance(char, dict):
                continue
            name = self._normalize_memory_text(char.get('name'))
            if not name:
                continue
            fragments = [name]
            relation_to_main = self._normalize_memory_text(char.get('relationship_to_main'))
            role_position = self._normalize_role_position_value(
                char.get('role_position'),
                relationship_to_main=relation_to_main,
            )
            if role_position:
                fragments.append(f"定位={role_position}")
            stance = self._infer_story_stance(
                explicit_stance=char.get('story_stance'),
                role_position=role_position,
                relationship_to_main=relation_to_main,
                additional_texts=[
                    char.get('description'),
                    char.get('background_status'),
                    char.get('mainline_role'),
                    char.get('growth_direction'),
                ],
            )
            if stance:
                fragments.append(f"立场={stance}")
            faction = self._normalize_memory_text(char.get('faction'))
            if faction and faction != '未提及':
                fragments.append(f"势力={faction}")
            description = self._normalize_memory_text(
                char.get('description') or char.get('relationship_to_main')
            )
            if description:
                fragments.append(description)
            character_states.append("；".join(fragments))

        relationship_edges: List[str] = []
        for rel in (character_content.get('character_relationships') or [])[:12]:
            if not isinstance(rel, dict):
                continue
            char_a = self._normalize_memory_text(rel.get('character1'))
            char_b = self._normalize_memory_text(rel.get('character2'))
            if not char_a or not char_b:
                continue
            relation = self._normalize_memory_text(rel.get('relationship'))
            description = self._normalize_memory_text(rel.get('description'))
            detail_parts = [item for item in [relation, description] if item]
            detail = "；".join(detail_parts)
            relationship_edges.append(f"{char_a} <-> {char_b}：{detail}" if detail else f"{char_a} <-> {char_b}")

        pending_foreshadowings: List[str] = []
        for chapter in book_chapters:
            outline_data = self._decode_json_field(chapter.outline_data, {})
            if not isinstance(outline_data, dict):
                continue

            for item in (outline_data.get('foreshadowing') or []):
                text = self._normalize_memory_text(item)
                if text:
                    pending_foreshadowings.append(f"第{chapter.chapter_number}章伏笔：{text}")

            ending_hook = outline_data.get('ending_hook')
            if isinstance(ending_hook, dict):
                hook_text = self._normalize_memory_text(
                    ending_hook.get('content') or ending_hook.get('hook') or ending_hook.get('summary')
                )
                if hook_text:
                    pending_foreshadowings.append(f"第{chapter.chapter_number}章钩子：{hook_text}")
            else:
                hook_text = self._normalize_memory_text(ending_hook)
                if hook_text:
                    pending_foreshadowings.append(f"第{chapter.chapter_number}章钩子：{hook_text}")

        for conflict in (plot_content.get('conflicts') or [])[:6]:
            if not isinstance(conflict, dict):
                continue
            status = self._normalize_memory_text(conflict.get('status'))
            if status and status != '已解决':
                description = self._normalize_memory_text(conflict.get('description'))
                if description:
                    pending_foreshadowings.append(f"未解决冲突：{description}")

        world_rules_hard_constraints: List[str] = []
        world_type = self._normalize_memory_text(worldview_content.get('world_type'))
        if world_type:
            world_rules_hard_constraints.append(f"世界类型：{world_type}")

        time_period = self._normalize_memory_text(worldview_content.get('time_period'))
        if time_period:
            world_rules_hard_constraints.append(f"时代背景：{time_period}")

        for system in (worldview_content.get('power_systems') or [])[:5]:
            if not isinstance(system, dict):
                continue
            name = self._normalize_memory_text(system.get('name')) or "未命名体系"
            description = self._normalize_memory_text(system.get('description'))
            levels = system.get('levels') or []
            levels_text = " -> ".join([str(level).strip() for level in levels if str(level).strip()])
            detail_parts = []
            if description:
                detail_parts.append(description)
            if levels_text:
                detail_parts.append(f"等级：{levels_text}")
            detail = "；".join(detail_parts)
            world_rules_hard_constraints.append(f"力量体系：{name}；{detail}" if detail else f"力量体系：{name}")

        for term in (concepts_content.get('terms') or [])[:4]:
            if not isinstance(term, dict):
                continue
            term_name = self._normalize_memory_text(term.get('term'))
            definition = self._normalize_memory_text(term.get('definition'))
            if term_name and definition:
                world_rules_hard_constraints.append(f"术语：{term_name}；{definition}")

        structured_memory: Dict[str, List[str]] = {}
        raw_memory_map = {
            "global_story_arcs": global_story_arcs,
            "character_states": character_states,
            "relationship_edges": relationship_edges,
            "pending_foreshadowings": pending_foreshadowings,
            "world_rules_hard_constraints": world_rules_hard_constraints,
        }

        for key, values in raw_memory_map.items():
            deduplicated = self._deduplicate_memory_items(
                values,
                self.STRUCTURED_MEMORY_LIMITS.get(key, 12),
            )
            if deduplicated:
                structured_memory[key] = deduplicated

        if not structured_memory:
            return None

        now_iso = utc_now().isoformat()
        return {
            "structured_memory": structured_memory,
            "memory_text": self._render_structured_memory_text(structured_memory),
            "metadata": {
                "source": "book_parser_import",
                "book_id": book.id,
                "book_title": book.title,
                "analysis_types": sorted(analysis_map.keys()),
            },
            "updated_at": now_iso,
        }

    def _project_settings_supports_structured_memory(self) -> bool:
        """检查当前数据库是否已经具备结构化记忆字段。"""
        try:
            inspector = inspect(self.db.get_bind())
            columns = {column["name"] for column in inspector.get_columns("project_settings")}
        except Exception as exc:
            logger.warning(f"  ⚠️ 检查 structured_memory 字段失败: {exc}")
            return False

        return {"structured_memory", "structured_memory_updated_at"}.issubset(columns)

    def _save_import_structured_memory(
        self,
        project_id: int,
        payload: Optional[Dict[str, Any]],
        updated_at: str,
    ) -> None:
        """将拆书生成的结构化记忆写入 project_settings。"""
        if not payload:
            return

        if not self._project_settings_supports_structured_memory():
            logger.info("  ℹ️ 当前数据库未启用 structured_memory 字段，跳过初始化")
            return

        from sqlalchemy import text

        self.db.execute(
            text(
                """
                UPDATE project_settings
                SET structured_memory = :structured_memory,
                    structured_memory_updated_at = :structured_memory_updated_at,
                    updated_at = :updated_at
                WHERE project_id = :project_id
                """
            ),
            {
                "project_id": project_id,
                "structured_memory": json.dumps(payload, ensure_ascii=False),
                "structured_memory_updated_at": updated_at,
                "updated_at": updated_at,
            },
        )
        logger.info("  → 已初始化结构化记忆 (structured_memory)")
    
    def _init_project_settings(self, project: Project, analysis_map: Dict[str, BookAnalysis], book: BookSource):
        """
        初始化 project_settings 表，填充工作流阶段内容
        
        将拆书分析结果转换为工作流可用的格式：
        - concept: 故事概念（基于情节分析生成）
        - world_setting: 世界观设定
        - characters: 人物设定
        - plot_outline: 情节大纲
        """
        from sqlalchemy import text
        
        # 构建各阶段内容
        concept_text = self._build_concept_text(analysis_map, book)
        world_setting_text = self._build_world_setting_text(analysis_map)
        characters_text = self._build_characters_text(analysis_map)
        plot_outline_text = self._build_plot_outline_text(analysis_map, book.id)
        structured_memory_payload = self._build_import_structured_memory_payload(analysis_map, book)
        
        # 插入 project_settings 记录
        now_iso = utc_now().isoformat()
        insert_sql = text("""
            INSERT INTO project_settings (
                project_id, concept, world_setting, characters, plot_outline, created_at, updated_at
            )
            VALUES (
                :project_id, :concept, :world_setting, :characters, :plot_outline, :created_at, :updated_at
            )
            ON CONFLICT(project_id) DO UPDATE SET
                concept = :concept,
                world_setting = :world_setting,
                characters = :characters,
                plot_outline = :plot_outline,
                updated_at = :updated_at
        """)
        
        self.db.execute(insert_sql, {
            'project_id': project.id,
            'concept': concept_text,
            'world_setting': world_setting_text,
            'characters': characters_text,
            'plot_outline': plot_outline_text,
            'created_at': now_iso,
            'updated_at': now_iso,
        })

        self._save_import_structured_memory(
            project_id=project.id,
            payload=structured_memory_payload,
            updated_at=now_iso,
        )
        
        logger.info(f"  → 已初始化工作流阶段内容 (project_settings)")

