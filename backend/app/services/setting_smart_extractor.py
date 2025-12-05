"""
设定项智能提取服务
从章节内容中提取与设定项相关的内容，并推荐标签
使用AI进行语义分析，避免提取垃圾内容
"""
import re
import json
import os
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models.project import Chapter
from app.models.setting import SettingCollection, SettingItem


class SettingSmartExtractor:
    """设定项智能提取与推荐服务"""
    
    # 预定义的标签推荐映射（按体系类型）
    TAG_SUGGESTIONS = {
        "technique_system": ["心法", "剑法", "拳法", "身法", "攻击", "防御", "辅助", "秘法"],
        "cultivation_realm_system": ["凡人", "修士", "大能", "仙人", "初期", "中期", "后期", "圆满"],
        "pill_system": ["恢复", "突破", "增强", "解毒", "一品", "二品", "三品", "极品"],
        "formation_system": ["攻击", "防御", "困敌", "幻境", "传送", "聚灵", "护山"],
        "weapon_system": ["剑", "刀", "枪", "戟", "法器", "灵器", "仙器", "神器"],
        "map_system": ["城市", "山脉", "森林", "秘境", "遗迹", "海域", "禁地"],
        "force_system": ["宗门", "世家", "王朝", "商会", "暗势力", "正道", "魔道"],
        "character_system": ["主角", "配角", "反派", "龙套", "神秘人物"],
        "magic_system": ["元素", "召唤", "附魔", "治愈", "诅咒", "时空"],
        "ability_realm_system": ["觉醒", "E级", "D级", "C级", "B级", "A级", "S级", "SSS级"],
    }
    
    # 通用标签
    COMMON_TAGS = ["重要", "核心", "待完善", "已完成", "关键", "辅助"]

    @staticmethod
    async def validate_excerpts_with_ai(
        setting_item_name: str,
        excerpts: List[Dict[str, Any]],
        max_count: int = 5
    ) -> List[Dict[str, Any]]:
        """
        使用AI验证和过滤提取的内容，避免垃圾数据
        
        Args:
            setting_item_name: 设定项名称
            excerpts: 候选摘录列表
            max_count: 最多返回数量
            
        Returns:
            经AI验证后的有效摘录列表
        """
        if not excerpts:
            return []
        
        try:
            from langchain_community.chat_models import ChatOpenAI
            
            # 使用轻量级模型进行验证
            llm = ChatOpenAI(
                model_name=os.getenv("QWEN_MODEL", "qwen-turbo"),
                temperature=0.3,
                openai_api_key=os.getenv("DASHSCOPE_API_KEY", ""),
                openai_api_base="https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
            
            # 准备候选内容
            candidates = []
            for i, exc in enumerate(excerpts[:10]):  # 最多验证10条
                candidates.append(f"{i+1}. [{exc['chapter_title']}] {exc['excerpt'][:200]}")
            
            prompt = f"""你是一个小说设定分析专家。请判断以下内容哪些真正与「{setting_item_name}」这个设定项相关。

候选内容：
{chr(10).join(candidates)}

请返回JSON格式，包含：
1. valid_indices: 有效内容的序号数组（只保留真正描述该设定的内容）
2. reason: 简要说明筛选理由

注意：
- 排除只是偶然提到名称的句子
- 排除不完整或断章取义的片段
- 保留有实质性描述的内容

返回JSON：
{{"valid_indices": [1, 3, 5], "reason": "..."}}
"""
            
            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            
            # 解析结果
            content = re.sub(r'```json\s*', '', content)
            content = re.sub(r'```\s*$', '', content)
            content = content.strip()
            
            result = json.loads(content)
            valid_indices = result.get("valid_indices", [])
            
            # 返回有效的摘录
            validated = []
            for idx in valid_indices:
                if 1 <= idx <= len(excerpts):
                    exc = excerpts[idx - 1]
                    exc["ai_validated"] = True
                    validated.append(exc)
                    if len(validated) >= max_count:
                        break
            
            return validated
            
        except Exception as e:
            print(f"AI验证失败: {e}")
            # 回退到简单过滤：只保留较长的完整句子
            filtered = []
            for exc in excerpts:
                text = exc.get("excerpt", "")
                # 基本过滤：排除明显不完整的句子
                if len(text) > 50 and not text.startswith("的") and "（" not in text[-10:]:
                    filtered.append(exc)
            return filtered[:max_count]

    @staticmethod
    async def extract_related_content(
        setting_item_name: str,
        project_id: int,
        db: Session,
        max_excerpts: int = 10,
        use_ai_validation: bool = True
    ) -> List[Dict[str, Any]]:
        """
        从项目所有章节中提取与设定项相关的内容
        
        Args:
            setting_item_name: 设定项名称
            project_id: 项目ID
            db: 数据库会话
            max_excerpts: 最大摘录数量
            use_ai_validation: 是否使用AI验证过滤垃圾内容
            
        Returns:
            [
                {
                    "chapter_id": 1,
                    "chapter_number": 1,
                    "chapter_title": "第一章",
                    "excerpt": "相关段落内容...",
                    "confidence": 0.8
                }
            ]
        """
        if not setting_item_name or not setting_item_name.strip():
            return []
        
        # 获取项目所有章节
        chapters = db.query(Chapter).filter(
            Chapter.project_id == project_id
        ).order_by(Chapter.chapter_number).all()
        
        related_contents = []
        
        for chapter in chapters:
            if not chapter.content:
                continue
            
            # 检查章节内容是否包含设定项名称
            if setting_item_name not in chapter.content:
                continue
            
            # 提取相关段落
            paragraphs = chapter.content.split('\n\n')
            for para in paragraphs:
                if setting_item_name in para:
                    # 清理段落
                    clean_para = re.sub(r'\s+', ' ', para).strip()
                    if len(clean_para) < 10:  # 太短的段落跳过
                        continue
                    
                    # 截取适当长度
                    if len(clean_para) > 300:
                        # 找到设定项名称位置，截取周围内容
                        pos = clean_para.find(setting_item_name)
                        start = max(0, pos - 100)
                        end = min(len(clean_para), pos + 200)
                        clean_para = "..." + clean_para[start:end] + "..."
                    
                    # 计算置信度（基于出现次数和段落长度）
                    mention_count = clean_para.count(setting_item_name)
                    confidence = min(0.9, 0.5 + mention_count * 0.1 + len(clean_para) / 1000)
                    
                    related_contents.append({
                        "chapter_id": chapter.id,
                        "chapter_number": chapter.chapter_number,
                        "chapter_title": chapter.title,
                        "excerpt": clean_para,
                        "confidence": round(confidence, 2)
                    })
                    
                    # 每章最多取2条
                    if len([c for c in related_contents if c["chapter_id"] == chapter.id]) >= 2:
                        break
            
            # 达到最大数量后停止
            if len(related_contents) >= max_excerpts:
                break
        
        # 按置信度排序
        related_contents.sort(key=lambda x: x["confidence"], reverse=True)
        
        # 使用AI验证过滤垃圾内容
        if use_ai_validation and related_contents:
            related_contents = await SettingSmartExtractor.validate_excerpts_with_ai(
                setting_item_name,
                related_contents,
                max_excerpts
            )
        
        return related_contents[:max_excerpts]

    @staticmethod
    def suggest_tags(
        item_name: str,
        item_content: Optional[str],
        collection_category: Optional[str] = None
    ) -> List[str]:
        """
        智能推荐标签
        
        Args:
            item_name: 设定项名称
            item_content: 设定项内容
            collection_category: 所属集合类型
            
        Returns:
            推荐的标签列表（最多5个）
        """
        suggested = []
        
        # 1. 基于体系类型推荐
        if collection_category and collection_category in SettingSmartExtractor.TAG_SUGGESTIONS:
            category_tags = SettingSmartExtractor.TAG_SUGGESTIONS[collection_category]
            # 检查内容中是否包含这些标签关键词
            content_to_check = f"{item_name} {item_content or ''}"
            for tag in category_tags:
                if tag in content_to_check:
                    suggested.append(tag)
        
        # 2. 基于内容关键词推荐
        content_to_analyze = f"{item_name} {item_content or ''}"
        
        # 等级/品质相关
        level_patterns = [
            (r'(初级|中级|高级|顶级)', lambda m: m.group(1)),
            (r'(一品|二品|三品|四品|五品|六品|七品|八品|九品)', lambda m: m.group(1)),
            (r'(下品|中品|上品|极品)', lambda m: m.group(1)),
            (r'(初期|中期|后期|大圆满|圆满)', lambda m: m.group(1)),
        ]
        
        for pattern, extractor in level_patterns:
            match = re.search(pattern, content_to_analyze)
            if match:
                tag = extractor(match)
                if tag not in suggested:
                    suggested.append(tag)
        
        # 3. 属性相关
        attribute_keywords = {
            "火": "火属性", "水": "水属性", "雷": "雷属性", "风": "风属性",
            "土": "土属性", "冰": "冰属性", "光": "光属性", "暗": "暗属性",
            "剑": "剑类", "刀": "刀类", "枪": "枪类",
            "攻击": "攻击", "防御": "防御", "辅助": "辅助", "治疗": "治疗",
        }
        
        for keyword, tag in attribute_keywords.items():
            if keyword in content_to_analyze and tag not in suggested:
                suggested.append(tag)
        
        # 4. 添加通用标签（如果需要）
        if len(suggested) < 2:
            # 根据内容长度判断完善程度
            content_len = len(item_content or "")
            if content_len > 200:
                if "已完成" not in suggested:
                    suggested.append("已完成")
            elif content_len < 50:
                if "待完善" not in suggested:
                    suggested.append("待完善")
        
        # 限制最多5个标签
        return suggested[:5]

    @staticmethod
    def merge_content(
        existing_content: Optional[str],
        new_excerpts: List[str],
        item_name: str
    ) -> str:
        """
        智能合并内容
        
        Args:
            existing_content: 现有内容
            new_excerpts: 新的摘录列表
            item_name: 设定项名称（用于去重）
            
        Returns:
            合并后的内容
        """
        if not new_excerpts:
            return existing_content or ""
        
        parts = []
        
        # 添加现有内容
        if existing_content and existing_content.strip():
            parts.append(existing_content.strip())
        
        # 添加新摘录
        parts.append("\n\n---\n📚 从章节中提取的相关内容：\n")
        
        for i, excerpt in enumerate(new_excerpts, 1):
            # 去除已有内容中出现过的片段
            if existing_content and excerpt in existing_content:
                continue
            parts.append(f"\n{i}. {excerpt}")
        
        return "\n".join(parts)

    @staticmethod
    def get_extraction_summary(
        setting_item_id: int,
        db: Session
    ) -> Dict[str, Any]:
        """
        获取设定项的提取摘要信息
        
        Args:
            setting_item_id: 设定项ID
            db: 数据库会话
            
        Returns:
            {
                "item": {...},
                "collection": {...},
                "referenced_chapters": [...],
                "usage_count": 5
            }
        """
        item = db.query(SettingItem).get(setting_item_id)
        if not item:
            return {"error": "Setting item not found"}
        
        collection = db.query(SettingCollection).get(item.collection_id)
        
        # 解析引用章节
        referenced_chapters = []
        if item.referenced_chapters:
            try:
                chapter_ids = json.loads(item.referenced_chapters)
                chapters = db.query(Chapter).filter(Chapter.id.in_(chapter_ids)).all()
                referenced_chapters = [
                    {"id": c.id, "number": c.chapter_number, "title": c.title}
                    for c in chapters
                ]
            except:
                pass
        
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
