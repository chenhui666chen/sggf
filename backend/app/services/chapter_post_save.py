"""
章节保存后的后台处理任务

包含：
1. 统一提取（实体、地点、实体关系、人物关系）
2. 生成章节摘要（仅工作流场景）

摘要生成策略：
- 工作流生成章节：generate_summary=True，需要生成摘要
- 手动创建/编辑章节：generate_summary=False，不生成摘要（避免覆盖人工编辑）
- 自动保存：不调用此服务（频率太高）
"""
import asyncio
import threading
import logging
import json
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from app.db.base import SessionLocal
from app.services.character_runtime_context import (
    build_character_relations_payload,
    extract_character_relation_items,
)

logger = logging.getLogger("uvicorn.error")

# 🆕 存储主事件循环的引用
_main_event_loop: asyncio.AbstractEventLoop | None = None


def set_main_event_loop(loop: asyncio.AbstractEventLoop):
    """🆕 设置主事件循环的引用（在应用启动时调用）"""
    global _main_event_loop
    _main_event_loop = loop


def get_main_event_loop() -> asyncio.AbstractEventLoop | None:
    """🆕 获取主事件循环的引用"""
    return _main_event_loop


async def _broadcast_project_event(
    *,
    project_id: int,
    event: str,
    data: Dict[str, Any],
) -> bool:
    """
    在正确的事件循环中推送项目广播。

    章节后处理运行在线程创建的新事件循环中，而 Socket.IO 服务绑定在主事件循环。
    这里统一切回主事件循环发消息，避免 Future attached to a different loop。
    """
    from app.websocket.manager import ws_manager

    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    main_loop = get_main_event_loop()
    if main_loop and not main_loop.is_closed() and current_loop is not main_loop:
        try:
            future = asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast_to_project(
                    project_id=project_id,
                    event=event,
                    data=data,
                ),
                main_loop,
            )
            return bool(await asyncio.wrap_future(future))
        except Exception as exc:
            logger.warning(f"⚠️ 跨事件循环广播失败（{event}）: {exc}")
            return False

    try:
        return bool(
            await ws_manager.broadcast_to_project(
                project_id=project_id,
                event=event,
                data=data,
            )
        )
    except Exception as exc:
        logger.warning(f"⚠️ 广播失败（{event}）: {exc}")
        return False


async def _save_character_relations(
    db: Session,
    project_id: int,
    character_relations: List[Dict[str, Any]]
) -> int:
    """
    🆕 将提取的人物关系保存到Character表
    
    关系格式：[
        {"source": "人物A", "target": "人物B", "relation_type": "师徒", "description": "..."}
    ]
    
    保存到 Character.relations 字段，格式：
    [{"target": "人物B", "type": "师徒"}]
    
    Returns:
        保存的关系数量
    """
    from app.models.character import Character
    
    if not character_relations:
        return 0
    
    characters = db.query(Character).filter(
        Character.project_id == project_id
    ).all()
    
    name_to_char = {char.name: char for char in characters}
    
    unique_names = set()
    for rel in character_relations:
        if rel.get('source'):
            unique_names.add(rel['source'].strip())
        if rel.get('target'):
            unique_names.add(rel['target'].strip())
    
    new_char_names = unique_names - set(name_to_char.keys())
    if new_char_names:
        logger.info(f"   🆕 自动创建 {len(new_char_names)} 个人物卡：{', '.join(new_char_names)}")
        for name in new_char_names:
            if name:
                new_char = Character(
                    project_id=project_id,
                    name=name,
                    appearance_status="已出场",
                    life_status="存活",
                    importance_level="次要角色",
                )
                db.add(new_char)
        db.commit()
        
        characters = db.query(Character).filter(
            Character.project_id == project_id
        ).all()
        name_to_char = {char.name: char for char in characters}
    
    saved_count = 0
    updated_chars = set()
    
    for rel in character_relations:
        source_name = rel.get('source', '').strip()
        target_name = rel.get('target', '').strip()
        rel_type = rel.get('relation_type', '关联')
        description = rel.get('description', '')
        
        if not source_name or not target_name:
            continue
        
        source_char = name_to_char.get(source_name)
        target_char = name_to_char.get(target_name)
        
        if not source_char:
            continue
        
        # 解析现有关系
        try:
            existing_relations = json.loads(source_char.relations) if source_char.relations else None
        except Exception:
            existing_relations = source_char.relations or None

        existing_relation_items = extract_character_relation_items(existing_relations)
        
        # 检查是否已存在相同关系
        already_exists = any(
            r.get('target') == target_name and r.get('type') == rel_type
            for r in existing_relation_items if isinstance(r, dict)
        )
        
        if not already_exists:
            # 添加新关系
            new_relation = {
                "target": target_name,
                "type": rel_type
            }
            if description and description != rel_type:
                new_relation["description"] = description
            
            source_char.relations = json.dumps(
                build_character_relations_payload(
                    {
                        "text": (
                            existing_relations.get("text")
                            if isinstance(existing_relations, dict)
                            else (existing_relations if isinstance(existing_relations, str) else "")
                        ),
                        "items": [*existing_relation_items, new_relation],
                    }
                ),
                ensure_ascii=False,
            )
            updated_chars.add(source_char.id)
            saved_count += 1
            
            logger.debug(f"      → {source_name} --[{rel_type}]--> {target_name}")
    
    # 提交更改
    if updated_chars:
        db.commit()
        logger.info(f"   👥 已更新 {len(updated_chars)} 个人物的关系数据")
    
    return saved_count


async def process_chapter_post_save(
    chapter_id: int,
    chapter_title: str,
    chapter_content: str,
    chapter_number: int,
    project_id: int,
    generate_summary: bool = False  # 🆕 新增参数：是否生成摘要
):
    """
    章节保存后的后台处理任务
    
    包含：
    1. 统一提取（实体、地点、关系、人物关系）
    2. 生成章节摘要（仅工作流场景）
    
    Args:
        chapter_id: 章节ID
        chapter_title: 章节标题
        chapter_content: 章节内容
        chapter_number: 章节编号
        project_id: 项目ID
        generate_summary: 是否生成摘要（默认False，仅工作流场景为True）
    """
    # 创建独立的数据库会话
    db = SessionLocal()
    
    try:
        logger.info(f"📡 开始后台处理章节 {chapter_id}（第{chapter_number}章）...")
        
        # 🔔 推送任务开始事件
        try:
            pushed = await _broadcast_project_event(
                project_id=project_id,
                event='post_save_task_start',
                data={
                    'chapter_id': chapter_id,
                    'chapter_number': chapter_number,
                    'status': 'processing'
                }
            )
            if pushed:
                logger.info("📡 已推送任务开始事件")
            else:
                logger.warning("⚠️ 任务开始事件未成功推送")
        except Exception as ws_error:
            logger.warning(f"⚠️ WebSocket 推送失败: {ws_error}")
        
        # ==================== 步骤1：统一提取（实体、地点、关系） ====================
        try:
            from app.services.unified_extraction import UnifiedExtractionService
            from app.services.entity_extraction import EntityExtractionService
            from app.services.location_hierarchy_extractor import LocationHierarchyExtractor
            from app.models.graph import KnowledgeGraphEdge
            
            logger.info(f"   🚀 统一提取（1次AI调用）...")
            
            # 🚀 优先使用统一提取（1次AI调用）
            try:
                unified_result = await UnifiedExtractionService.extract_all_from_chapter(
                    chapter_title=chapter_title,
                    chapter_content=chapter_content,
                    project_id=project_id,
                )
                
                entities = unified_result.get("entities", [])
                locations = unified_result.get("locations", [])
                relations = unified_result.get("relations", [])
                character_relations = unified_result.get("character_relations", [])
                
                logger.info(
                    f"   ✅ 统一提取完成：{len(entities)} 个实体，"
                    f"{len(locations)} 个地点，{len(relations)} 个实体关系，"
                    f"{len(character_relations)} 个人物关系"
                )
                
            except Exception as unified_error:
                # ⚠️ 统一提取失败，回退到原方法（3次AI调用）
                logger.warning(f"   ⚠️ 统一提取失败，回退到原方法: {unified_error}")
                logger.info(f"   🔄 使用原方法：分3次调用AI...")
                
                # 提取实体（第1次AI调用）
                entities = await EntityExtractionService.extract_entities_from_chapter(
                    chapter_title=chapter_title,
                    chapter_content=chapter_content,
                    project_id=project_id,
                )
                logger.info(f"   ✅ 抽取到 {len(entities)} 个实体")
                
                # 提取地点层级（第2次AI调用）
                logger.info(f"   🗺️ 开始提取地点层级关系...")
                locations = await LocationHierarchyExtractor.extract_location_hierarchy(
                    chapter_title=chapter_title,
                    chapter_content=chapter_content,
                )
                logger.info(f"   ✅ 提取到 {len(locations)} 个地点")
                
                # 提取关系（第3次AI调用）
                if entities:
                    logger.info(f"   🔗 开始抽取实体间关系...")
                    relations = await EntityExtractionService.extract_relations_from_chapter(
                        chapter_title=chapter_title,
                        chapter_content=chapter_content,
                        entities=entities,
                    )
                    logger.info(f"   ✅ 抽取到 {len(relations)} 个关系")
                else:
                    relations = []
                
                # 回退模式不提取人物关系
                character_relations = []
            
            # 保存地点层级到地图体系
            if locations:
                location_result = LocationHierarchyExtractor.save_location_hierarchy(
                    db=db,
                    project_id=project_id,
                    locations=locations,
                )
                
                logger.info(
                    f"   💾 地点层级保存完成：创建 {location_result['created']} 个，"
                    f"更新 {location_result['updated']} 个，跳过 {location_result['skipped']} 个"
                )
            
            # 归类并保存实体
            if entities:
                result = EntityExtractionService.classify_and_save_entities(
                    db=db,
                    project_id=project_id,
                    entities=entities,
                )
                
                logger.info(
                    f"   💾 实体归类完成：正式集合 {result['saved_to_formal']} 项，"
                    f"候选集合 {result['saved_to_candidate']} 项，"
                    f"跳过 {result['skipped']} 项"
                )
            
            # 保存关系（从统一提取的结果中获取）
            if relations:
                from app.models.setting import SettingItem
                saved_relations = 0
                
                logger.info(f"   🔗 开始保存 {len(relations)} 个关系...")
                
                project_items = db.query(SettingItem).join(
                    SettingItem.collection
                ).filter(
                    SettingItem.collection.has(project_id=project_id)
                ).all()
                items_by_name: dict = {}
                for si in project_items:
                    items_by_name.setdefault(si.name, []).append(si)
                
                for rel in relations:
                    source_name = rel.get('source', '').strip()
                    target_name = rel.get('target', '').strip()
                    relation_type = rel.get('relation_type', '相关')
                    confidence = rel.get('confidence', 0.6)
                    
                    source_item = items_by_name.get(source_name, [None])[0]
                    target_item = items_by_name.get(target_name, [None])[0]
                    
                    if source_item and target_item:
                        existing_edge = db.query(KnowledgeGraphEdge).filter(
                            KnowledgeGraphEdge.source_item_id == source_item.id,
                            KnowledgeGraphEdge.target_item_id == target_item.id,
                            KnowledgeGraphEdge.relation_type == relation_type,
                        ).first()
                        
                        if not existing_edge:
                            edge = KnowledgeGraphEdge(
                                source_item_id=source_item.id,
                                target_item_id=target_item.id,
                                relation_type=relation_type,
                                confidence=confidence,
                                auto_extracted=True,
                            )
                            db.add(edge)
                            saved_relations += 1
                
                if saved_relations > 0:
                    db.commit()
                    logger.info(f"   🔗 已保存 {saved_relations} 个关系边到知识图谱")
                else:
                    logger.info(f"   ℹ️ 没有新实体关系需要保存")
            
            # 🆕 保存人物关系到Character表
            if character_relations:
                saved_char_relations = await _save_character_relations(
                    db=db,
                    project_id=project_id,
                    character_relations=character_relations
                )
                if saved_char_relations > 0:
                    logger.info(f"   👥 已保存 {saved_char_relations} 个人物关系")
                    
        except Exception as e:
            logger.warning(f"   ⚠️ 统一提取失败: {e}")
            import traceback
            traceback.print_exc()
        
        # ==================== 步顲2：生成章节摘要（仅工作流场景） ====================
        if generate_summary:
            try:
                from app.services.agents.chapter_summarizer import create_chapter_summarizer
                
                logger.info(f"   📝 开始生成章节摘要...")
                
                summarizer = create_chapter_summarizer(db_session=db)
                summarizer.get_or_generate_summary(
                    chapter_id=chapter_id,
                    chapter_number=chapter_number,
                    chapter_title=chapter_title,
                    chapter_content=chapter_content,
                    summary_length=300,
                    force_regenerate=True
                )
                
                logger.info(f"   ✅ 章节摘要生成完成")
                
            except Exception as e:
                logger.warning(f"   ⚠️ 生成章节摘要失败: {e}")
                import traceback
                traceback.print_exc()
        else:
            logger.info(f"   ℹ️ 跳过摘要生成（非工作流场景）")
        
        logger.info(f"✅ 后台处理完成：章节 {chapter_id}")
        
        # 🔔 推送任务完成事件
        try:
            pushed = await _broadcast_project_event(
                project_id=project_id,
                event='post_save_task_complete',
                data={
                    'chapter_id': chapter_id,
                    'chapter_number': chapter_number,
                    'status': 'completed'
                }
            )
            if pushed:
                logger.info("📡 已推送任务完成事件")
            else:
                logger.warning("⚠️ 任务完成事件未成功推送")
        except Exception as ws_error:
            logger.warning(f"⚠️ WebSocket 推送失败：{ws_error}")
        
    except Exception as e:
        logger.error(f"❌ 后台处理失败：章节 {chapter_id}, 错误：{e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def start_chapter_post_save_task(
    chapter_id: int,
    chapter_title: str,
    chapter_content: str,
    chapter_number: int,
    project_id: int,
    generate_summary: bool = False  # 🆕 新增参数：是否生成摘要
):
    """
    启动章节保存后的后台处理任务
    
    Args:
        chapter_id: 章节ID
        chapter_title: 章节标题
        chapter_content: 章节内容
        chapter_number: 章节编号
        project_id: 项目ID
        generate_summary: 是否生成摘要（默认False，仅工作流场景为True）
    """
    def run_async_task():
        """在新的事件循环中运行异步任务"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                process_chapter_post_save(
                    chapter_id=chapter_id,
                    chapter_title=chapter_title,
                    chapter_content=chapter_content,
                    chapter_number=chapter_number,
                    project_id=project_id,
                    generate_summary=generate_summary  # 🆕 传递摘要生成参数
                )
            )
        finally:
            loop.close()
    
    # 创建并启动后台线程
    thread = threading.Thread(
        target=run_async_task,
        daemon=True,
        name=f"ChapterPostSave-{chapter_id}"
    )
    thread.start()
    logger.info(f"🚀 已启动后台任务：章节 {chapter_id} 的后处理")
