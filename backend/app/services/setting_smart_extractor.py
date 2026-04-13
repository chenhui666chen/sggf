"""
设定项智能提取服务。
从章节内容中提取与设定项相关的内容，并推荐标签。
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.project import Chapter
from app.models.setting import SettingCollection, SettingItem

logger = logging.getLogger(__name__)


class SettingSmartExtractor:
    """设定项智能提取与推荐服务。"""

    TAG_SUGGESTIONS = {
        "technique_system": ["心法", "剑法", "拳法", "身法", "攻击", "防御", "辅助", "秘法"],
        "cultivation_realm_system": ["凡人", "修士", "大能", "仙人", "初期", "中期", "后期", "圆满"],
        "pill_system": ["恢复", "突破", "增强", "解毒", "一品", "二品", "三品", "极品"],
        "formation_system": ["攻击", "防御", "困敌", "幻境", "传送", "聚灵", "护山"],
        "weapon_system": ["剑", "刀", "枪", "戟", "法器", "灵器", "仙器", "神器"],
        "map_system": ["城市", "山脉", "森林", "秘境", "遗迹", "海域", "禁地"],
        "organization_force_system": ["宗门", "世家", "王朝", "商会", "暗势力", "正道", "魔道"],
        "character_system": ["主角", "配角", "反派", "龙套", "神秘人物"],
        "magic_system": ["元素", "召唤", "附魔", "治愈", "诅咒", "时空"],
        "ability_realm_system": ["觉醒", "E级", "D级", "C级", "B级", "A级", "S级", "SSS级"],
    }

    @staticmethod
    async def validate_excerpts_with_ai(
        setting_item_name: str,
        excerpts: List[Dict[str, Any]],
        max_count: int = 5,
    ) -> List[Dict[str, Any]]:
        """使用 AI 二次筛选摘录结果。"""
        if not excerpts:
            return []

        try:
            from core.langchain_bridge import get_task_llm

            llm = get_task_llm("summarize")
            candidate_lines = []
            for index, excerpt in enumerate(excerpts[: max(max_count * 3, 10)]):
                candidate_lines.append(
                    f"{index + 1}. [{excerpt['chapter_title']}] {excerpt['excerpt'][:200]}"
                )

            prompt = f"""你是小说设定分析专家。请判断以下内容哪些真正与“{setting_item_name}”这个设定项直接相关。

候选内容：
{chr(10).join(candidate_lines)}

请返回 JSON，格式如下：
{{"valid_indices": [1, 3], "reason": "简要说明"}}

筛选要求：
- 排除只是顺带提到名称的句子
- 排除严重缺少上下文的片段
- 保留对设定本身有实质描述、解释或推进作用的内容
"""
            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            content = re.sub(r"```json\s*", "", content)
            content = re.sub(r"```\s*$", "", content).strip()

            result = json.loads(content)
            valid_indices = result.get("valid_indices", [])

            validated: List[Dict[str, Any]] = []
            for index in valid_indices:
                if 1 <= index <= len(excerpts):
                    excerpt = dict(excerpts[index - 1])
                    excerpt["ai_validated"] = True
                    validated.append(excerpt)
                    if len(validated) >= max_count:
                        break
            return validated
        except Exception as exc:
            logger.debug("AI 校验摘录失败: %s", exc)
            filtered = []
            for excerpt in excerpts:
                text = excerpt.get("excerpt", "")
                if len(text) >= 50:
                    filtered.append(excerpt)
            return filtered[:max_count]

    @staticmethod
    def _build_excerpt(paragraph: str, setting_item_name: str) -> Optional[Dict[str, Any]]:
        clean_paragraph = re.sub(r"\s+", " ", paragraph).strip()
        if len(clean_paragraph) < 10 or setting_item_name not in clean_paragraph:
            return None

        if len(clean_paragraph) > 500:
            position = clean_paragraph.find(setting_item_name)
            start = max(0, position - 150)
            end = min(len(clean_paragraph), position + 350)
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(clean_paragraph) else ""
            clean_paragraph = f"{prefix}{clean_paragraph[start:end]}{suffix}"

        mention_count = clean_paragraph.count(setting_item_name)
        confidence = min(0.95, 0.45 + mention_count * 0.12 + len(clean_paragraph) / 1000)
        return {
            "excerpt": clean_paragraph,
            "confidence": round(confidence, 2),
        }

    @staticmethod
    async def extract_related_content(
        setting_item_name: str,
        project_id: int,
        db: Session,
        max_excerpts: int = 10,
        use_ai_validation: bool = True,
    ) -> List[Dict[str, Any]]:
        """从项目全部章节中提取与设定项相关的内容。"""
        if not setting_item_name or not setting_item_name.strip():
            return []

        chapters = (
            db.query(Chapter)
            .filter(Chapter.project_id == project_id)
            .order_by(Chapter.chapter_number)
            .all()
        )

        candidates: List[Dict[str, Any]] = []
        for chapter in chapters:
            if not chapter.content or setting_item_name not in chapter.content:
                continue

            chapter_hits = 0
            for paragraph in chapter.content.split("\n\n"):
                excerpt_data = SettingSmartExtractor._build_excerpt(paragraph, setting_item_name)
                if not excerpt_data:
                    continue

                candidates.append(
                    {
                        "chapter_id": chapter.id,
                        "chapter_number": chapter.chapter_number,
                        "chapter_title": chapter.title,
                        "excerpt": excerpt_data["excerpt"],
                        "confidence": excerpt_data["confidence"],
                    }
                )
                chapter_hits += 1
                if chapter_hits >= 2:
                    break

        candidates.sort(
            key=lambda item: (
                float(item.get("confidence", 0.0)),
                int(item.get("chapter_number", 0)),
            ),
            reverse=True,
        )

        if use_ai_validation and candidates:
            return await SettingSmartExtractor.validate_excerpts_with_ai(
                setting_item_name,
                candidates,
                max_excerpts,
            )

        return candidates[:max_excerpts]

    @staticmethod
    def suggest_tags(
        item_name: str,
        item_content: Optional[str],
        collection_category: Optional[str] = None,
    ) -> List[str]:
        """根据设定名称、内容和体系类别推荐标签。"""
        suggested: List[str] = []

        content_to_check = f"{item_name} {item_content or ''}"
        if collection_category and collection_category in SettingSmartExtractor.TAG_SUGGESTIONS:
            for tag in SettingSmartExtractor.TAG_SUGGESTIONS[collection_category]:
                if tag in content_to_check and tag not in suggested:
                    suggested.append(tag)

        level_patterns = [
            (r"(初级|中级|高级|顶级)", lambda match: match.group(1)),
            (r"(一品|二品|三品|四品|五品|六品|七品|八品|九品)", lambda match: match.group(1)),
            (r"(下品|中品|上品|极品)", lambda match: match.group(1)),
            (r"(初期|中期|后期|大圆满|圆满)", lambda match: match.group(1)),
        ]
        for pattern, extractor in level_patterns:
            match = re.search(pattern, content_to_check)
            if match:
                tag = extractor(match)
                if tag not in suggested:
                    suggested.append(tag)

        attribute_keywords = {
            "火": "火属性",
            "水": "水属性",
            "雷": "雷属性",
            "风": "风属性",
            "土": "土属性",
            "冰": "冰属性",
            "光": "光属性",
            "暗": "暗属性",
            "剑": "剑类",
            "刀": "刀类",
            "枪": "枪类",
            "攻击": "攻击",
            "防御": "防御",
            "辅助": "辅助",
            "治疗": "治疗",
        }
        for keyword, tag in attribute_keywords.items():
            if keyword in content_to_check and tag not in suggested:
                suggested.append(tag)

        content_length = len(item_content or "")
        if len(suggested) < 2:
            if content_length > 200 and "已完善" not in suggested:
                suggested.append("已完善")
            elif content_length < 50 and "待完善" not in suggested:
                suggested.append("待完善")

        return suggested[:5]

    @staticmethod
    def merge_content(
        existing_content: Optional[str],
        new_excerpts: List[str],
        item_name: str,
    ) -> str:
        """将新摘录内容追加到设定正文中，并避免简单重复。"""
        if not new_excerpts:
            return existing_content or ""

        parts: List[str] = []
        if existing_content and existing_content.strip():
            parts.append(existing_content.strip())

        deduped_excerpts: List[str] = []
        existing_text = existing_content or ""
        for excerpt in new_excerpts:
            if excerpt and excerpt not in existing_text and excerpt not in deduped_excerpts:
                deduped_excerpts.append(excerpt)

        if not deduped_excerpts:
            return existing_content or ""

        parts.append("\n\n---\n从章节中提取的相关内容：\n")
        for index, excerpt in enumerate(deduped_excerpts, start=1):
            parts.append(f"\n{index}. {excerpt}")
        return "\n".join(parts)

    @staticmethod
    def get_extraction_summary(setting_item_id: int, db: Session) -> Dict[str, Any]:
        """获取设定项提取摘要。"""
        item = db.query(SettingItem).get(setting_item_id)
        if not item:
            return {"error": "Setting item not found"}

        collection = db.query(SettingCollection).get(item.collection_id)
        referenced_chapters: List[Dict[str, Any]] = []
        if item.referenced_chapters:
            try:
                chapter_ids = json.loads(item.referenced_chapters)
                chapters = db.query(Chapter).filter(Chapter.id.in_(chapter_ids)).all()
                referenced_chapters = [
                    {"id": chapter.id, "number": chapter.chapter_number, "title": chapter.title}
                    for chapter in chapters
                ]
            except Exception:
                referenced_chapters = []

        return {
            "item": {
                "id": item.id,
                "name": item.name,
                "content": item.content,
                "tags": json.loads(item.tags) if item.tags else [],
            },
            "collection": {
                "id": collection.id if collection else None,
                "name": collection.name if collection else None,
                "category": collection.category if collection else None,
            },
            "referenced_chapters": referenced_chapters,
            "usage_count": item.usage_count or 0,
        }
