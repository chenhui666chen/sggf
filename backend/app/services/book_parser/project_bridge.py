"""
项目桥接服务

将拆书分析结果转换为工作流项目
"""
import json
import logging
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from app.models.book_parser import BookSource, BookChapter, BookAnalysis
from app.models.project import Project, Chapter
from app.models.setting import SettingCollection, SettingItem
from app.models.character import Character
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)


class ProjectBridge:
    """
    项目桥接器
    
    将拆书分析结果转换为工作流项目，包括：
    - 创建项目
    - 导入设定（人物、世界观）
    - 导入章节（可选）
    """
    
    # 设定类型映射
    ANALYSIS_TO_COLLECTION = {
        'characters': '人物设定',
        'worldview': '世界观设定',
        'plot': '情节脉络',
        'concepts': '关键概念',
    }
    
    def __init__(self, db: Session):
        self.db = db
    
    def import_to_project(
        self,
        book_id: int,
        user_id: int,
        project_title: Optional[str] = None,
        import_settings: bool = True,
        import_characters: bool = True,
        import_chapters: bool = False,
        start_from_chapter: Optional[int] = None,
    ) -> Project:
        """
        将书籍导入为工作流项目
        
        Args:
            book_id: 书籍ID
            user_id: 用户ID
            project_title: 项目标题（默认使用书名）
            import_settings: 是否导入设定
            import_characters: 是否导入人物
            import_chapters: 是否导入章节内容
            start_from_chapter: 从第几章开始导入
            
        Returns:
            创建的项目
        """
        # 获取书籍
        book = self.db.query(BookSource).filter(BookSource.id == book_id).first()
        if not book:
            raise ValueError(f"书籍不存在: {book_id}")
        
        # 创建项目
        project = Project(
            user_id=user_id,
            title=project_title or f"{book.title}（续写）",
            description=f"基于《{book.title}》的创作项目",
            genre=book.genre,
            status="draft",
        )
        self.db.add(project)
        self.db.flush()  # 获取project.id
        
        logger.info(f"✅ 创建项目: {project.title} (ID: {project.id})")
        
        # 获取分析结果
        analyses = self.db.query(BookAnalysis).filter(
            BookAnalysis.book_id == book_id
        ).all()
        
        analysis_map = {a.analysis_type: a for a in analyses}
        
        # 导入人物设定
        if import_characters and 'characters' in analysis_map:
            self._import_characters(project, analysis_map['characters'])
        
        # 导入设定
        if import_settings:
            self._import_settings(project, analysis_map)
        
        # 导入章节
        if import_chapters:
            self._import_chapters(project, book_id, start_from_chapter)
        
        # 更新书籍关联
        book.imported_project_id = project.id
        
        # 🆕 初始化 project_settings 记录，填充工作流阶段内容
        self._init_project_settings(project, analysis_map, book)
        
        self.db.commit()
        
        logger.info(f"✅ 项目导入完成: {project.title}")
        
        return project
    
    def _import_characters(self, project: Project, analysis: BookAnalysis):
        """
        导入人物设定
        """
        try:
            content = json.loads(analysis.content) if isinstance(analysis.content, str) else analysis.content
        except json.JSONDecodeError:
            logger.warning("人物分析结果解析失败")
            return
        
        # 导入主要人物
        main_characters = content.get('main_characters', [])
        for char_data in main_characters:
            # 构建人物档案内容
            profile_parts = []
            if char_data.get('description'):
                profile_parts.append(f"简介: {char_data['description']}")
            if char_data.get('personality'):
                profile_parts.append(f"性格: {', '.join(char_data['personality']) if isinstance(char_data['personality'], list) else char_data['personality']}")
            if char_data.get('abilities'):
                profile_parts.append(f"能力: {', '.join(char_data['abilities']) if isinstance(char_data['abilities'], list) else char_data['abilities']}")
            
            character = Character(
                project_id=project.id,
                name=char_data.get('name', '未知'),
                role=self._map_role(char_data.get('role', '')),
                summary=char_data.get('description', ''),  # 简短介绍
                profile='\n'.join(profile_parts),  # 完整档案
                importance_level='主角' if char_data.get('role') == 'protagonist' else '重要角色',
                tags=json.dumps(char_data.get('personality', []), ensure_ascii=False),
            )
            self.db.add(character)
        
        # 导入配角（作为次要角色）
        supporting_characters = content.get('supporting_characters', [])
        for char_data in supporting_characters[:10]:  # 限制数量
            character = Character(
                project_id=project.id,
                name=char_data.get('name', '未知'),
                role='supporting',
                summary=char_data.get('description', ''),
                profile=char_data.get('relationship_to_main', ''),
                importance_level='次要角色',
                tags='[]',
            )
            self.db.add(character)
        
        logger.info(f"  → 导入 {len(main_characters)} 个主要人物, {min(len(supporting_characters), 10)} 个配角")
    
    def _map_role(self, role: str) -> str:
        """映射角色类型"""
        role_map = {
            'protagonist': 'protagonist',
            'antagonist': 'antagonist',
            'deuteragonist': 'supporting',
            'supporting': 'supporting',
        }
        return role_map.get(role.lower(), 'supporting')
    
    def _import_settings(self, project: Project, analysis_map: Dict[str, BookAnalysis]):
        """
        导入设定集合
        """
        order = 0
        
        # 世界观设定
        if 'worldview' in analysis_map:
            self._create_worldview_collection(project, analysis_map['worldview'], order)
            order += 1
        
        # 情节脉络
        if 'plot' in analysis_map:
            self._create_plot_collection(project, analysis_map['plot'], order)
            order += 1
        
        # 关键概念
        if 'concepts' in analysis_map:
            self._create_concepts_collection(project, analysis_map['concepts'], order)
            order += 1
    
    def _create_worldview_collection(self, project: Project, analysis: BookAnalysis, order: int):
        """
        创建世界观设定集合
        """
        try:
            content = json.loads(analysis.content) if isinstance(analysis.content, str) else analysis.content
        except json.JSONDecodeError:
            return
        
        collection = SettingCollection(
            project_id=project.id,
            name='世界观设定',
            category='worldview',
            description=f"从原著提取的世界观设定（置信度: {int(analysis.confidence * 100)}%）",
            max_depth=3,
            order=order,
        )
        self.db.add(collection)
        self.db.flush()
        
        item_order = 0
        
        # 世界类型
        if content.get('world_type'):
            self._add_setting_item(collection.id, '世界类型', content['world_type'], item_order)
            item_order += 1
        
        # 世界描述
        if content.get('world_description'):
            self._add_setting_item(collection.id, '世界概述', content['world_description'], item_order)
            item_order += 1
        
        # 力量体系
        power_systems = content.get('power_systems', [])
        for sys in power_systems:
            sys_content = f"{sys.get('description', '')}"
            if sys.get('levels'):
                sys_content += f"\n等级: {' → '.join(sys['levels'])}"
            self._add_setting_item(collection.id, sys.get('name', '力量体系'), sys_content, item_order)
            item_order += 1
        
        # 重要地点
        locations = content.get('locations', [])[:10]
        for loc in locations:
            loc_content = f"类型: {loc.get('type', '未知')}\n{loc.get('description', '')}"
            self._add_setting_item(collection.id, loc.get('name', '地点'), loc_content, item_order)
            item_order += 1
        
        # 势力
        factions = content.get('factions', [])[:10]
        for faction in factions:
            faction_content = f"类型: {faction.get('type', '未知')}\n{faction.get('description', '')}"
            self._add_setting_item(collection.id, faction.get('name', '势力'), faction_content, item_order)
            item_order += 1
        
        logger.info(f"  → 导入世界观设定 ({item_order} 项)")
    
    def _create_plot_collection(self, project: Project, analysis: BookAnalysis, order: int):
        """
        创建情节脉络集合
        """
        try:
            content = json.loads(analysis.content) if isinstance(analysis.content, str) else analysis.content
        except json.JSONDecodeError:
            return
        
        collection = SettingCollection(
            project_id=project.id,
            name='情节脉络',
            category='plot',
            description='从原著提取的情节结构',
            max_depth=2,
            order=order,
        )
        self.db.add(collection)
        self.db.flush()
        
        item_order = 0
        
        # 主线剧情
        if content.get('main_plot'):
            self._add_setting_item(collection.id, '主线剧情', content['main_plot'], item_order)
            item_order += 1
        
        # 剧情弧
        plot_arcs = content.get('plot_arcs', [])
        for arc in plot_arcs:
            chapters = arc.get('chapters', [])
            chapter_range = f"第{chapters[0]}-{chapters[1]}章" if len(chapters) >= 2 else ""
            arc_content = f"{chapter_range}\n{arc.get('description', '')}"
            self._add_setting_item(collection.id, arc.get('name', '剧情弧'), arc_content, item_order)
            item_order += 1
        
        # 转折点
        turning_points = content.get('turning_points', [])[:5]
        for tp in turning_points:
            tp_content = f"第{tp.get('chapter', '?')}章\n{tp.get('event', '')}\n重要性: {tp.get('significance', '')}"
            self._add_setting_item(collection.id, '转折点', tp_content, item_order)
            item_order += 1
        
        logger.info(f"  → 导入情节脉络 ({item_order} 项)")
    
    def _create_concepts_collection(self, project: Project, analysis: BookAnalysis, order: int):
        """
        创建关键概念集合
        """
        try:
            content = json.loads(analysis.content) if isinstance(analysis.content, str) else analysis.content
        except json.JSONDecodeError:
            return
        
        collection = SettingCollection(
            project_id=project.id,
            name='关键概念',
            category='concepts',
            description='从原著提取的专有名词和概念',
            max_depth=2,
            order=order,
        )
        self.db.add(collection)
        self.db.flush()
        
        item_order = 0
        terms = content.get('terms', [])
        for term in terms[:20]:
            self._add_setting_item(
                collection.id,
                term.get('term', '概念'),
                term.get('definition', ''),
                item_order
            )
            item_order += 1
        
        logger.info(f"  → 导入关键概念 ({item_order} 项)")
    
    def _add_setting_item(self, collection_id: int, name: str, content: str, order: int):
        """
        添加设定项
        """
        item = SettingItem(
            collection_id=collection_id,
            name=name,
            content=content,
            depth=1,
            is_leaf=True,
            order=order,
        )
        self.db.add(item)
    
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
                word_count=bch.word_count,
                status='draft',
            )
            self.db.add(chapter)
        
        project.word_count = sum(ch.word_count for ch in book_chapters)
        
        logger.info(f"  → 导入 {len(book_chapters)} 个章节")
    
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
            try:
                content = json.loads(a.content) if isinstance(a.content, str) else a.content
                item_count = self._count_items(a.analysis_type, content)
            except:
                item_count = 0
            
            preview["analyses"].append({
                "type": a.analysis_type,
                "type_name": self.ANALYSIS_TO_COLLECTION.get(a.analysis_type, a.analysis_type),
                "confidence": a.confidence,
                "item_count": item_count,
            })
            
            if a.analysis_type in preview["import_options"]:
                preview["import_options"][a.analysis_type] = True
        
        return preview
    
    def _count_items(self, analysis_type: str, content: Dict) -> int:
        """统计分析结果中的项目数量"""
        if analysis_type == 'characters':
            return len(content.get('main_characters', [])) + len(content.get('supporting_characters', []))
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
        
        logger.info(f"  → 已初始化工作流阶段内容 (project_settings)")
    
    def _build_concept_text(self, analysis_map: Dict[str, BookAnalysis], book: BookSource) -> str:
        """构建故事概念文本（六部分标准格式 - 与创作模式一致）"""
        parts = []
        
        # 从情节分析提取概念信息
        concept_data = {}
        if 'plot' in analysis_map:
            try:
                content = json.loads(analysis_map['plot'].content) if isinstance(analysis_map['plot'].content, str) else analysis_map['plot'].content
                concept_data = content.get('concept', {})
            except:
                pass
        
        # 1. 一句话卖点（Logline）
        parts.append("**一句话卖点（Logline）**")
        logline = concept_data.get('logline', '')
        if not logline and 'plot' in analysis_map:
            # 回退：从主线剧情提取
            try:
                content = json.loads(analysis_map['plot'].content) if isinstance(analysis_map['plot'].content, str) else analysis_map['plot'].content
                main_plot = content.get('main_plot', '')
                logline = main_plot[:60] + '...' if len(main_plot) > 60 else main_plot
            except:
                logline = f"《{book.title}》的故事"
        parts.append(logline or f"《{book.title}》的故事")
        parts.append("")
        
        # 2. 日志标题（短标题）
        parts.append("**日志标题（短标题）**")
        short_title = concept_data.get('short_title', '') or book.title[:10]
        parts.append(short_title)
        parts.append("")
        
        # 3. 概念摘要（80–150字）
        parts.append("**概念摘要**")
        summary = concept_data.get('summary', '')
        if not summary and 'plot' in analysis_map:
            try:
                content = json.loads(analysis_map['plot'].content) if isinstance(analysis_map['plot'].content, str) else analysis_map['plot'].content
                summary = content.get('main_plot', '')[:150]
            except:
                pass
        parts.append(summary or f"基于《{book.title}》的创作项目")
        parts.append("")
        
        # 4. 题材与流派
        parts.append("**题材与流派**")
        genre = concept_data.get('genre', '') or book.genre or '通用题材'
        sub_genre = concept_data.get('sub_genre', '')
        genre_text = f"{genre} / {sub_genre}" if sub_genre else genre
        parts.append(genre_text)
        parts.append("")
        
        # 5. 核心标签
        parts.append("**核心标签**")
        core_tags = concept_data.get('core_tags', [])
        if core_tags:
            parts.append("、".join(core_tags))
        else:
            parts.append("待补充")
        parts.append("")
        
        # 6. 核心冲突与情感基调
        parts.append("**核心冲突与情感基调**")
        core_conflict = concept_data.get('core_conflict', '')
        emotional_tone = concept_data.get('emotional_tone', '')
        
        if core_conflict:
            parts.append(f"核心冲突：{core_conflict}")
        if emotional_tone:
            parts.append(f"情感基调：{emotional_tone}")
        if not core_conflict and not emotional_tone:
            # 回退：从冲突列表提取
            if 'plot' in analysis_map:
                try:
                    content = json.loads(analysis_map['plot'].content) if isinstance(analysis_map['plot'].content, str) else analysis_map['plot'].content
                    conflicts = content.get('conflicts', [])
                    if conflicts:
                        parts.append(f"核心冲突：{conflicts[0].get('description', '待分析')}")
                except:
                    pass
        parts.append("")
        
        # 7. 世界观高概摘要（可简略）
        if 'worldview' in analysis_map:
            try:
                content = json.loads(analysis_map['worldview'].content) if isinstance(analysis_map['worldview'].content, str) else analysis_map['worldview'].content
                if content.get('world_description'):
                    parts.append("**世界观高概摘要**")
                    parts.append(content['world_description'][:200])
                    parts.append("")
            except:
                pass
        
        return '\n'.join(parts) if parts else f"# {book.title}\n\n基于《{book.title}》的创作项目"
    
    def _build_world_setting_text(self, analysis_map: Dict[str, BookAnalysis]) -> str:
        """构建世界观设定文本"""
        if 'worldview' not in analysis_map:
            return ""
        
        try:
            content = json.loads(analysis_map['worldview'].content) if isinstance(analysis_map['worldview'].content, str) else analysis_map['worldview'].content
        except:
            return ""
        
        parts = ["# 世界观设定", ""]
        
        # 世界类型
        if content.get('world_type'):
            parts.append(f"## 世界类型")
            parts.append(content['world_type'])
            parts.append("")
        
        # 世界描述
        if content.get('world_description'):
            parts.append(f"## 世界概述")
            parts.append(content['world_description'])
            parts.append("")
        
        # 力量体系
        power_systems = content.get('power_systems', [])
        if power_systems:
            parts.append("## 力量体系")
            for sys in power_systems:
                parts.append(f"### {sys.get('name', '未命名体系')}")
                if sys.get('description'):
                    parts.append(sys['description'])
                if sys.get('levels'):
                    parts.append(f"等级：{' → '.join(sys['levels'])}")
                parts.append("")
        
        # 重要地点
        locations = content.get('locations', [])[:10]
        if locations:
            parts.append("## 重要地点")
            for loc in locations:
                parts.append(f"### {loc.get('name', '未命名')}")
                if loc.get('type'):
                    parts.append(f"类型：{loc['type']}")
                if loc.get('description'):
                    parts.append(loc['description'])
                parts.append("")
        
        # 势力
        factions = content.get('factions', [])[:10]
        if factions:
            parts.append("## 主要势力")
            for faction in factions:
                parts.append(f"### {faction.get('name', '未命名')}")
                if faction.get('type'):
                    parts.append(f"类型：{faction['type']}")
                if faction.get('description'):
                    parts.append(faction['description'])
                parts.append("")
        
        return '\n'.join(parts)
    
    def _build_characters_text(self, analysis_map: Dict[str, BookAnalysis]) -> str:
        """生成与人物扩展一致的人物档案文本。"""
        if 'characters' not in analysis_map:
            return ""

        try:
            content = json.loads(analysis_map['characters'].content) if isinstance(analysis_map['characters'].content, str) else analysis_map['characters'].content
        except Exception:
            return ""

        def normalize_text(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, list):
                items = [str(v).strip() for v in value if str(v).strip()]
                return "、".join(items)
            return str(value).strip()

        def pick_first(*values: Any) -> str:
            for value in values:
                text_value = normalize_text(value)
                if text_value:
                    return text_value
            return ""

        def build_role_text(role_value: str, fallback: str) -> str:
            role_map = {
                'protagonist': '主角',
                'antagonist': '反派',
                'deuteragonist': '核心配角',
                'supporting': '支持角色',
            }
            if role_value:
                normalized = str(role_value).strip().lower()
                if normalized:
                    return role_map.get(normalized, role_value)
            return fallback

        relationship_map: Dict[str, List[str]] = {}
        for rel in (content.get('character_relationships', []) or []):
            char_a = normalize_text(rel.get('character1'))
            char_b = normalize_text(rel.get('character2'))
            if not char_a or not char_b:
                continue
            relation = normalize_text(rel.get('relationship'))
            description = normalize_text(rel.get('description'))
            detail_parts = []
            if relation:
                detail_parts.append(relation)
            if description and description != relation:
                detail_parts.append(description)
            detail = "，".join(detail_parts)
            line_a = f"{char_b}：{detail}" if detail else char_b
            line_b = f"{char_a}：{detail}" if detail else char_a
            relationship_map.setdefault(char_a, []).append(line_a)
            relationship_map.setdefault(char_b, []).append(line_b)

        def value_or_default(value: str) -> str:
            return value if value else "待补充"

        def append_character_card(target: List[str], char_data: Dict[str, Any], role_text: str) -> None:
            name = normalize_text(char_data.get('name')) or "待补充"
            age_gender = pick_first(char_data.get('age_gender'), char_data.get('age'), char_data.get('gender'))
            appearance = pick_first(char_data.get('appearance'), char_data.get('looks'), char_data.get('appearance_feature'))
            personality = pick_first(char_data.get('personality'), char_data.get('traits'))
            background = pick_first(char_data.get('background'), char_data.get('backstory'))
            worldview = pick_first(char_data.get('worldview'), char_data.get('values'), char_data.get('worldview_position'))
            motivation = pick_first(char_data.get('motivation'), char_data.get('goal'))
            abilities = pick_first(char_data.get('abilities'), char_data.get('skills'), char_data.get('strengths'))
            weakness = pick_first(char_data.get('weakness'), char_data.get('weaknesses'), char_data.get('flaws'))
            plot_role = pick_first(char_data.get('plot_role'), char_data.get('role_in_plot'), char_data.get('description'))
            growth_arc = pick_first(char_data.get('arc'), char_data.get('development'), char_data.get('growth'))
            related_clues = pick_first(char_data.get('clues'), char_data.get('related_clues'))

            relationship_lines: List[str] = []
            relation_to_main = normalize_text(char_data.get('relationship_to_main'))
            if relation_to_main:
                relationship_lines.append(f"与主角：{relation_to_main}")
            relationship_lines.extend(relationship_map.get(name, []))
            relationship_text = "；".join(list(dict.fromkeys([line for line in relationship_lines if line]))) or "待补充"

            target.append(f"### 【姓名】：{name}")
            target.append("")
            target.append(f"【年龄/性别】：{value_or_default(age_gender)}")
            target.append("")
            target.append(f"【角色定位】：{value_or_default(role_text)}")
            target.append("")
            target.append(f"【外貌特征】：{value_or_default(appearance)}")
            target.append("")
            target.append(f"【性格特点】：{value_or_default(personality)}")
            target.append("")
            target.append(f"【背景故事】：{value_or_default(background)}")
            target.append("")
            target.append(f"【世界观/价值观立场】：{value_or_default(worldview)}")
            target.append("")
            target.append(f"【核心动机】：{value_or_default(motivation)}")
            target.append("")
            target.append(f"【能力/特长】：{value_or_default(abilities)}")
            target.append("")
            target.append(f"【弱点/缺陷】：{value_or_default(weakness)}")
            target.append("")
            target.append(f"【在情节中的作用】：{value_or_default(plot_role)}")
            target.append("")
            target.append(f"【人物成长线】：{value_or_default(growth_arc)}")
            target.append("")
            target.append(f"【关键关系】：{value_or_default(relationship_text)}")
            target.append("")
            target.append(f"【关联线索】：{value_or_default(related_clues)}")
            target.append("")
            target.append("---")
            target.append("")

        parts: List[str] = []
        main_characters = content.get('main_characters', []) or []
        supporting_characters = content.get('supporting_characters', []) or []

        main_names = {normalize_text(c.get('name')) for c in main_characters if normalize_text(c.get('name'))}
        supporting_characters = [c for c in supporting_characters if normalize_text(c.get('name')) not in main_names]

        groups: Dict[str, List[Any]] = {
            "主角阵营": [],
            "对手阵营": [],
            "支持角色": [],
            "中立角色": [],
        }

        for char in main_characters:
            role = str(char.get('role') or '').lower()
            if role == 'protagonist':
                groups["主角阵营"].append((char, build_role_text(role, "主角")))
            elif role == 'antagonist':
                groups["对手阵营"].append((char, build_role_text(role, "反派")))
            elif role in {'deuteragonist', 'supporting'}:
                groups["支持角色"].append((char, build_role_text(role, "支持角色")))
            else:
                groups["中立角色"].append((char, build_role_text(role, "中立角色")))

        for char in supporting_characters:
            role = str(char.get('role') or '').lower()
            groups["支持角色"].append((char, build_role_text(role, "支持角色")))

        for group_name, entries in groups.items():
            if not entries:
                continue
            parts.append(f"## {group_name}")
            parts.append("")
            for char_data, role_text in entries:
                append_character_card(parts, char_data, role_text)

        return "\n".join(parts).strip()

    def _build_plot_outline_text(self, analysis_map: Dict[str, BookAnalysis], book_id: int) -> str:
        """生成与大纲扩展一致的情节大纲文本。"""
        if 'plot' not in analysis_map:
            return ""

        try:
            content = json.loads(analysis_map['plot'].content) if isinstance(analysis_map['plot'].content, str) else analysis_map['plot'].content
        except Exception:
            return ""

        def normalize_text(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, list):
                items = [str(v).strip() for v in value if str(v).strip()]
                return "、".join(items)
            return str(value).strip()

        def format_arc_brief(arc: Any) -> str:
            if not isinstance(arc, dict):
                return normalize_text(arc) or "待补充"
            name = normalize_text(arc.get('name')) or "待补充"
            desc = normalize_text(arc.get('description'))
            chapters = arc.get('chapters') or []
            meta_parts = []
            if isinstance(chapters, list) and len(chapters) >= 2:
                meta_parts.append(f"第{chapters[0]}-{chapters[1]}章")
            arc_type = normalize_text(arc.get('type'))
            if arc_type:
                meta_parts.append(arc_type)
            if meta_parts:
                name = f"{name}（{' / '.join(meta_parts)}）"
            if desc:
                return f"{name}：{desc}"
            return name

        parts: List[str] = []

        main_plot = normalize_text(content.get('main_plot'))
        if not main_plot:
            main_plot = normalize_text(content.get('concept', {}).get('summary')) or normalize_text(content.get('concept', {}).get('logline'))
        parts.append("1. 故事概述")
        parts.append(main_plot if main_plot else "待补充")
        parts.append("")

        plot_arcs = content.get('plot_arcs', []) or []
        parts.append("2. 情节发展")
        if plot_arcs:
            for arc in plot_arcs:
                parts.append(f"- {format_arc_brief(arc)}")
        else:
            parts.append("待补充")
        parts.append("")

        turning_points = content.get('turning_points', []) or []
        parts.append("3. 重要转折点")
        if turning_points:
            for tp in turning_points[:8]:
                chapter = normalize_text(tp.get('chapter')) if isinstance(tp, dict) else ""
                event = normalize_text(tp.get('event')) if isinstance(tp, dict) else ""
                significance = normalize_text(tp.get('significance')) if isinstance(tp, dict) else ""
                title = f"第{chapter}章" if chapter else "关键节点"
                detail_parts = [item for item in [event, significance] if item]
                detail = "，".join(detail_parts)
                parts.append(f"- {title}：{detail}" if detail else f"- {title}")
        else:
            parts.append("待补充")
        parts.append("")

        parts.append("4. 高潮设计")
        climax_lines = []
        for arc in plot_arcs:
            if not isinstance(arc, dict):
                continue
            arc_type = normalize_text(arc.get('type'))
            arc_name = normalize_text(arc.get('name'))
            if "高潮" in arc_type or "高潮" in arc_name or "决战" in arc_name:
                climax_lines.append(f"- {format_arc_brief(arc)}")
        if not climax_lines and turning_points:
            for tp in turning_points[-2:]:
                chapter = normalize_text(tp.get('chapter')) if isinstance(tp, dict) else ""
                event = normalize_text(tp.get('event')) if isinstance(tp, dict) else ""
                title = f"第{chapter}章" if chapter else "关键节点"
                detail = event or (normalize_text(tp.get('significance')) if isinstance(tp, dict) else "")
                climax_lines.append(f"- {title}：{detail}" if detail else f"- {title}")
        if climax_lines:
            parts.extend(climax_lines)
        else:
            parts.append("待补充")
        parts.append("")

        parts.append("5. 结局规划")
        ending_lines = []
        for arc in plot_arcs:
            if not isinstance(arc, dict):
                continue
            arc_type = normalize_text(arc.get('type'))
            arc_name = normalize_text(arc.get('name'))
            if any(keyword in arc_type for keyword in ["结局", "收尾", "终局", "尾声"]) or any(keyword in arc_name for keyword in ["结局", "收尾", "终局", "尾声"]):
                ending_lines.append(f"- {format_arc_brief(arc)}")
        if not ending_lines:
            chapter_summaries = content.get('chapter_summaries') or []
            if chapter_summaries:
                last_summary = normalize_text(chapter_summaries[-1])
                if last_summary:
                    ending_lines.append(f"- {last_summary}")
        if ending_lines:
            parts.extend(ending_lines)
        else:
            parts.append("待补充")

        return "\n".join(parts).strip()
