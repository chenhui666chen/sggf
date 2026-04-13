"""
设定自动合并服务。
实现高置信度候选设定项的自动合并与版本化快照。
"""
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from app.models.setting import SettingCollection, SettingItem

logger = logging.getLogger(__name__)


class SettingAutoMergeService:
    """设定自动合并服务。"""

    HIGH_CONFIDENCE_THRESHOLD = 0.8

    @staticmethod
    def calculate_confidence(
        item_name: str,
        item_content: str,
        chapter_plan: str,
        chapter_content: str,
    ) -> float:
        """根据文本命中情况估算候选设定置信度。"""
        score = 0.0

        format_patterns = [
            r"【[^】]+】\s*" + re.escape(item_name),
            r"(功法|丹药|阵法|秘境|城市|门派)[:：]\s*" + re.escape(item_name),
            r"境界[:：]\s*" + re.escape(item_name),
        ]
        for pattern in format_patterns:
            if re.search(pattern, item_content):
                score += 0.3
                break

        if item_name in chapter_plan and item_name in chapter_content:
            score += 0.4
        elif item_name in chapter_content:
            score += 0.2

        if len(item_content) > 50:
            score += 0.3

        return min(score, 1.0)

    @staticmethod
    def create_snapshot(item: SettingItem) -> Dict[str, Any]:
        """创建设定快照。"""
        return {
            "timestamp": datetime.now().isoformat(),
            "name": item.name,
            "code": item.code,
            "level": item.level,
            "order": item.order,
            "content": item.content,
            "tags": item.tags,
            "relations": item.relations,
            "confidence_score": item.confidence_score,
            "depth": item.depth,
            "node_type": item.node_type,
            "is_leaf": item.is_leaf,
            "path": item.path,
            "summary": item.summary,
        }

    @staticmethod
    def save_snapshot(item: SettingItem, db: Session, *, commit: bool = True) -> None:
        """保存当前状态到快照列表。"""
        snapshot = SettingAutoMergeService.create_snapshot(item)
        try:
            snapshots = json.loads(item.snapshots) if item.snapshots else []
        except Exception:
            snapshots = []

        snapshots.append(snapshot)
        if len(snapshots) > 10:
            snapshots = snapshots[-10:]

        item.snapshots = json.dumps(snapshots, ensure_ascii=False)
        db.flush()
        if commit:
            db.commit()

    @staticmethod
    def find_or_create_target_item(
        db: Session,
        project_id: int,
        target_collection_id: int,
        item_name: str,
    ) -> Tuple[SettingItem, bool]:
        """在目标集合中查找或创建设定项。"""
        collection = db.query(SettingCollection).get(target_collection_id)
        if not collection or collection.project_id != project_id:
            raise ValueError(
                f"目标集合 {target_collection_id} 不存在或不属于项目 {project_id}"
            )

        existing = (
            db.query(SettingItem)
            .filter(
                SettingItem.collection_id == target_collection_id,
                SettingItem.name == item_name,
            )
            .first()
        )
        if existing:
            return existing, False

        new_item = SettingItem(
            collection_id=target_collection_id,
            name=item_name,
            content="",
            tags=json.dumps(["自动创建"], ensure_ascii=False),
            order=0,
            depth=1,
            node_type="detail",
            is_leaf=True,
            path=f"{collection.name}/{item_name}",
        )
        db.add(new_item)
        db.flush()
        return new_item, True

    @staticmethod
    def merge_content(old_content: str, new_content: str) -> str:
        """合并设定内容，优先保留信息更完整的版本。"""
        if not old_content:
            return new_content
        if not new_content:
            return old_content
        if len(new_content) > len(old_content) * 1.2:
            return new_content
        return old_content

    @staticmethod
    def auto_merge_high_confidence_items(
        db: Session,
        project_id: int,
        candidate_collection_id: int,
        chapter_plan: str,
        chapter_content: str,
    ) -> Dict[str, Any]:
        """自动合并高置信度候选设定项。"""
        from app.services.setting_categories import TYPE_TO_CATEGORY_MAP
        from app.services.vector_sync import (
            delete_setting_from_vector_db,
            upsert_setting_to_vector_db,
        )

        candidate_items = (
            db.query(SettingItem)
            .filter(SettingItem.collection_id == candidate_collection_id)
            .all()
        )

        merged_count = 0
        skipped_count = 0
        details: List[Dict[str, Any]] = []

        for item in candidate_items:
            confidence = SettingAutoMergeService.calculate_confidence(
                item.name,
                item.content or "",
                chapter_plan,
                chapter_content,
            )
            item.confidence_score = confidence

            if confidence < SettingAutoMergeService.HIGH_CONFIDENCE_THRESHOLD:
                skipped_count += 1
                details.append(
                    {
                        "item_name": item.name,
                        "confidence": round(confidence, 2),
                        "action": "skipped_low_confidence",
                    }
                )
                continue

            type_match = re.search(r"类型[:：]\s*([^\n,，]+)", item.content or "")
            recommend_match = re.search(r"推荐归类[:：]\s*([^\n,，]+)", item.content or "")
            item_type = type_match.group(1).strip() if type_match else None

            target_category = None
            if item_type:
                target_category = TYPE_TO_CATEGORY_MAP.get(item_type)

            if not target_category and recommend_match:
                recommend_val = recommend_match.group(1).strip()
                target_category = recommend_val if recommend_val in TYPE_TO_CATEGORY_MAP.values() else None
                if not target_category:
                    for cat_key, cat_val in TYPE_TO_CATEGORY_MAP.items():
                        if recommend_val in cat_val or cat_val in recommend_val:
                            target_category = cat_key
                            break

            if not target_category:
                try:
                    tags = json.loads(item.tags) if item.tags else []
                except Exception:
                    tags = []
                for tag in tags:
                    if tag in TYPE_TO_CATEGORY_MAP:
                        target_category = TYPE_TO_CATEGORY_MAP[tag]
                        break

            if not target_category and item_type:
                for cat_key in TYPE_TO_CATEGORY_MAP:
                    if cat_key in item_type or item_type in cat_key:
                        target_category = TYPE_TO_CATEGORY_MAP[cat_key]
                        break

            if not target_category:
                skipped_count += 1
                details.append(
                    {
                        "item_name": item.name,
                        "confidence": round(confidence, 2),
                        "action": "skipped_no_target_category",
                    }
                )
                continue

            target_collection = (
                db.query(SettingCollection)
                .filter(
                    SettingCollection.project_id == project_id,
                    SettingCollection.category == target_category,
                )
                .first()
            )
            if not target_collection:
                skipped_count += 1
                details.append(
                    {
                        "item_name": item.name,
                        "confidence": round(confidence, 2),
                        "action": "skipped_no_target_collection",
                    }
                )
                continue

            candidate_item_id = item.id
            try:
                target_item, is_new = SettingAutoMergeService.find_or_create_target_item(
                    db,
                    project_id,
                    target_collection.id,
                    item.name,
                )

                if not is_new:
                    SettingAutoMergeService.save_snapshot(target_item, db, commit=False)

                target_item.content = SettingAutoMergeService.merge_content(
                    target_item.content or "",
                    item.content or "",
                )

                try:
                    tags = json.loads(target_item.tags) if target_item.tags else []
                except Exception:
                    tags = []
                if "自动合并" not in tags:
                    tags.append("自动合并")
                target_item.tags = json.dumps(tags, ensure_ascii=False)
                target_item.confidence_score = confidence

                db.flush()

                if target_item.content:
                    try:
                        upsert_setting_to_vector_db(
                            setting_id=target_item.id,
                            setting_name=target_item.name,
                            content=target_item.content,
                            project_id=project_id,
                            category=target_category,
                        )
                    except Exception as exc:
                        logger.warning("合并后向量同步失败: %s", exc)

                db.delete(item)
                db.flush()

                try:
                    delete_setting_from_vector_db(candidate_item_id, project_id)
                except Exception as exc:
                    logger.warning("删除候选设定向量失败: %s", exc)

                db.commit()
                db.refresh(target_item)

                merged_count += 1
                details.append(
                    {
                        "item_name": item.name,
                        "confidence": round(confidence, 2),
                        "action": "created_and_merged" if is_new else "merged",
                    }
                )
            except Exception as exc:
                db.rollback()
                skipped_count += 1
                details.append(
                    {
                        "item_name": item.name,
                        "confidence": round(confidence, 2),
                        "action": f"error: {exc}",
                    }
                )

        return {
            "merged_count": merged_count,
            "skipped_count": skipped_count,
            "details": details,
        }

    @staticmethod
    async def llm_reclassify_candidates(
        db: Session,
        project_id: int,
    ) -> Dict[str, Any]:
        """使用LLM对候选集合中规则匹配失败的项进行再分类。

        只处理规则匹配无法归类的候选项，使用 qwen-turbo 低成本模型。
        """
        from app.services.setting_categories import TYPE_TO_CATEGORY_MAP, SYSTEM_CATEGORIES

        candidate_collection = (
            db.query(SettingCollection)
            .filter(
                SettingCollection.project_id == project_id,
                SettingCollection.category == "candidate",
            )
            .first()
        )
        if not candidate_collection:
            return {"reclassified": 0, "skipped": 0, "details": []}

        candidate_items = (
            db.query(SettingItem)
            .filter(SettingItem.collection_id == candidate_collection.id)
            .all()
        )

        rule_classified_names: set = set()
        for item in candidate_items:
            type_match = re.search(r"类型[:：]\s*([^\n,，]+)", item.content or "")
            recommend_match = re.search(r"推荐归类[:：]\s*([^\n,，]+)", item.content or "")
            item_type = type_match.group(1).strip() if type_match else None

            matched = False
            if item_type and TYPE_TO_CATEGORY_MAP.get(item_type):
                matched = True
            if not matched and recommend_match:
                rv = recommend_match.group(1).strip()
                if rv in TYPE_TO_CATEGORY_MAP.values():
                    matched = True
            if not matched:
                try:
                    tags = json.loads(item.tags) if item.tags else []
                except Exception:
                    tags = []
                for tag in tags:
                    if tag in TYPE_TO_CATEGORY_MAP:
                        matched = True
                        break
            if not matched and item_type:
                for cat_key in TYPE_TO_CATEGORY_MAP:
                    if cat_key in item_type or item_type in cat_key:
                        matched = True
                        break

            if matched:
                rule_classified_names.add(item.name)

        unclassified = [i for i in candidate_items if i.name not in rule_classified_names]
        if not unclassified:
            return {"reclassified": 0, "skipped": 0, "details": [], "message": "所有候选项已可规则匹配，无需LLM"}

        type_options = "/".join(sorted(set(TYPE_TO_CATEGORY_MAP.keys())))
        batch_items = []
        for item in unclassified[:20]:
            content_preview = (item.content or "")[:150]
            batch_items.append(f"名称：{item.name}\n内容：{content_preview}")

        items_text = "\n---\n".join(batch_items)

        prompt = f"""请为以下小说设定项选择最合适的类型。类型必须从以下选项中选择：
{type_options}

设定项：
{items_text}

请以JSON数组格式返回，每个元素包含name和type两个字段：
[{{"name": "设定项名称", "type": "最合适的类型"}}]

只返回JSON，不要其他内容。"""

        try:
            import os
            from core.langchain_bridge import create_model_llm
            model = os.getenv("RECLASSIFY_MODEL", "qwen-turbo")
            llm = create_model_llm(model=model, temperature=0.1)
            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            content = re.sub(r"```json\s*", "", content)
            content = re.sub(r"```\s*$", "", content)
            content = content.strip()
            classifications = json.loads(content)
        except Exception as e:
            logger.warning(f"LLM再分类调用失败: {e}")
            return {"reclassified": 0, "skipped": len(unclassified), "details": [], "error": str(e)}

        if not isinstance(classifications, list):
            return {"reclassified": 0, "skipped": len(unclassified), "details": [], "error": "LLM返回格式错误"}

        name_to_type: Dict[str, str] = {}
        for c in classifications:
            if isinstance(c, dict) and "name" in c and "type" in c:
                name_to_type[c["name"]] = c["type"]

        reclassified = 0
        skipped = 0
        details: List[Dict[str, Any]] = []

        for item in unclassified:
            llm_type = name_to_type.get(item.name)
            if not llm_type:
                skipped += 1
                details.append({"item_name": item.name, "action": "skipped_no_llm_type"})
                continue

            target_category = TYPE_TO_CATEGORY_MAP.get(llm_type)
            if not target_category:
                for cat_key in TYPE_TO_CATEGORY_MAP:
                    if cat_key in llm_type or llm_type in cat_key:
                        target_category = TYPE_TO_CATEGORY_MAP[cat_key]
                        break

            if not target_category:
                skipped += 1
                details.append({"item_name": item.name, "action": "skipped_no_category", "llm_type": llm_type})
                continue

            target_collection = (
                db.query(SettingCollection)
                .filter(
                    SettingCollection.project_id == project_id,
                    SettingCollection.category == target_category,
                )
                .first()
            )

            if not target_collection:
                if target_category in SYSTEM_CATEGORIES:
                    target_collection = SettingCollection(
                        project_id=project_id,
                        name=SYSTEM_CATEGORIES[target_category],
                        category=target_category,
                        description=f"LLM再分类自动创建",
                        order=100,
                    )
                    db.add(target_collection)
                    db.commit()
                    db.refresh(target_collection)
                else:
                    skipped += 1
                    details.append({"item_name": item.name, "action": "skipped_no_collection"})
                    continue

            try:
                target_item, is_new = SettingAutoMergeService.find_or_create_target_item(
                    db, project_id, target_collection.id, item.name,
                )
                if not is_new:
                    SettingAutoMergeService.save_snapshot(target_item, db, commit=False)

                merged_content = SettingAutoMergeService.merge_content(
                    target_item.content or "", item.content or "",
                )
                target_item.content = merged_content
                try:
                    tags = json.loads(target_item.tags) if target_item.tags else []
                except Exception:
                    tags = []
                if "LLM再分类" not in tags:
                    tags.append("LLM再分类")
                target_item.tags = json.dumps(tags, ensure_ascii=False)
                target_item.confidence_score = item.confidence_score
                db.flush()

                try:
                    from app.services.vector_sync import upsert_setting_to_vector_db, delete_setting_from_vector_db
                    if target_item.content:
                        upsert_setting_to_vector_db(
                            setting_id=target_item.id,
                            setting_name=target_item.name,
                            content=target_item.content,
                            project_id=project_id,
                            category=target_category,
                        )
                except Exception as exc:
                    logger.warning("LLM再分类向量同步失败: %s", exc)

                candidate_item_id = item.id
                db.delete(item)
                db.flush()

                try:
                    from app.services.vector_sync import delete_setting_from_vector_db
                    delete_setting_from_vector_db(candidate_item_id, project_id)
                except Exception:
                    pass

                db.commit()
                reclassified += 1
                details.append({
                    "item_name": item.name,
                    "action": "reclassified",
                    "target_category": target_category,
                    "llm_type": llm_type,
                })
            except Exception as exc:
                db.rollback()
                skipped += 1
                details.append({"item_name": item.name, "action": f"error: {exc}"})

        return {
            "reclassified": reclassified,
            "skipped": skipped,
            "details": details,
            "model": model if 'model' in dir() else "qwen-turbo",
        }
