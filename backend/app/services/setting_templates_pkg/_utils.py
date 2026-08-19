"""类型化设定模板与设定摘要工具函数"""
from typing import Dict, Any, List, Optional
import json

from sqlalchemy.orm import Session

from app.models.setting import SettingCollection, SettingItem

from app.services.setting_templates_pkg._hierarchy_defaults import HIERARCHY_DEFAULTS

def get_hierarchy_config_json(category: str) -> str:
    """返回指定体系类别的默认层级模板JSON字符串"""
    cfg = HIERARCHY_DEFAULTS.get(category)
    if not cfg:
        # 默认配置：2层扁平结构
        cfg = {
            "max_depth": 2,
            "levels": [
                {"depth": 1, "name": "默认体系", "type": "system"},
                {"depth": 2, "name": "详情", "type": "detail", "leaf": True}
            ]
        }
    return json.dumps(cfg, ensure_ascii=False)


# ==================== 模板定义 ====================
# 每个模板包含适合该题材的体系集合（collections）
# 通用体系（map_system, organization_force_system, resource_system, character_system）会自动注入

SETTING_TEMPLATES: Dict[str, Dict[str, Any]] = {
    # ==================== 1. 玄幻修真模板 ====================
    "xuanhuan_basic": {
        "key": "xuanhuan_basic",
        "name": "玄幻修真基础模板",
        "description": "适用于凡人修真、大陆争霸类玄幻题材。包含修仙境界、功法、丹药、阵法、符箓、法宝等核心体系。",
        "collections": [
            {"name": "修仙境界体系", "category": "cultivation_realm_system", "description": "从凡人到飞升的修行阶段划分。"},
            {"name": "功法体系", "category": "technique_system", "description": "心法、剑法、拳法等各类修行功法。"},
            {"name": "丹药体系", "category": "pill_system", "description": "突破丹、恢复丹、辅助丹等各类丹药。"},
            {"name": "阵法体系", "category": "formation_system", "description": "护山大阵、困敌阵、传送阵等阵法设定。"},
            {"name": "符箓体系", "category": "talisman_system", "description": "攻击符、防御符、遁逃符等符箓设定。"},
            {"name": "武器法宝体系", "category": "weapon_system", "description": "飞剑、法器、灵器、仙器等装备设定。"},
        ],
    },

    # ==================== 2. 都市异能模板 ====================
    "urban_power": {
        "key": "urban_power",
        "name": "都市异能基础模板",
        "description": "适用于现代都市背景的超自然力量题材。包含异能体系、组织势力、人脉关系、特殊道具、商业财富等核心体系。",
        "collections": [
            {"name": "异能体系", "category": "ability_system", "description": "异能者的等级划分、能力类型与成长路径。"},
            {"name": "人脉关系体系", "category": "network_social_relationship_system", "description": "都市异能者的社会关系网络与人际资源。"},
            {"name": "特殊道具体系", "category": "special_artifact_relic_system", "description": "蕴含超自然力量的道具、遗物与装备。"},
            {"name": "财富商业体系", "category": "wealth_business_empire_system", "description": "异能者世界中的经济体系与商业运作。"},
        ],
    },

    # ==================== 3. 科幻世界模板 ====================
    "sci_fi": {
        "key": "sci_fi",
        "name": "科幻世界基础模板",
        "description": "适用于星际探索、未来科技等科幻题材。包含星际航行、AI机器人等核心体系。",
        "collections": [
            {"name": "星际航行体系", "category": "interstellar_travel_exploration_system", "description": "宇宙探索、星际旅行相关的技术与文明等级。"},
            {"name": "AI机器人体系", "category": "ai_robot_system", "description": "人工智能、仿生机器人、战斗机甲等设定。"},
        ],
    },

    # ==================== 4. 西方奇幻模板 ====================
    "western_fantasy": {
        "key": "western_fantasy",
        "name": "西方奇幻基础模板",
        "description": "适用于魔法世界、史诗冒险等西方奇幻题材。包含魔法体系、种族血脉、职业体系等核心设定。",
        "collections": [
            {"name": "魔法境界体系", "category": "magic_realm_system", "description": "魔法师的等级划分与成长阶段。"},
            {"name": "魔法体系", "category": "magic_system", "description": "各类魔法的分类、等级与具体法术。"},
            {"name": "种族血脉体系", "category": "race_bloodline_system", "description": "各智慧种族及其血脉传承设定。"},
            {"name": "职业体系", "category": "profession_class_system", "description": "战士、法师、牧师等职业分类与进阶。"},
        ],
    },

    # ==================== 5. 武侠模板 ====================
    "wuxia_basic": {
        "key": "wuxia_basic",
        "name": "武侠基础模板",
        "description": "适用于传统武侠、江湖题材。包含武道境界与武学体系。",
        "collections": [
            {"name": "武道境界体系", "category": "martial_realm_system", "description": "武者的境界划分与力量成长体系。"},
            {"name": "功法武学体系", "category": "technique_system", "description": "内功心法、轻功、刀法、剑法等武学设定。"},
        ],
    },

    # ==================== 6. 历史权谋模板 ====================
    "historical_intrigue": {
        "key": "historical_intrigue",
        "name": "历史权谋基础模板",
        "description": "适用于宫廷争斗、历史架空等题材。包含权力官制、军事战争、经济财税、文化礼制等核心体系。",
        "collections": [
            {"name": "权力官制体系", "category": "power_official_system", "description": "朝廷官职、权力等级与晋升规则。"},
            {"name": "军事战争体系", "category": "military_warfare_system", "description": "军队编制、战争形态与军功体系。"},
            {"name": "经济财税体系", "category": "economy_taxation_system", "description": "国家财政、税收制度与经济命脉。"},
            {"name": "文化礼制体系", "category": "culture_etiquette_examination_system", "description": "礼仪规范、科举制度与文化传承。"},
            {"name": "律法刑罚体系", "category": "legal_criminal_system", "description": "法律条文、刑罚制度与司法程序。"},
            {"name": "通讯情报体系", "category": "communication_intelligence_system", "description": "信息传递、情报网络与密探组织。"},
            {"name": "历史传说体系", "category": "historical_event_legend_system", "description": "重大历史事件与传说故事。"},
            {"name": "民生风俗体系", "category": "lifestyle_custom_system", "description": "节日庆典、婚丧嫁娶、饮食服饰等风俗。"},
        ],
    },

    # ==================== 7. 末世废土模板 ====================
    "post_apocalypse": {
        "key": "post_apocalypse",
        "name": "末世废土基础模板",
        "description": "适用于丧尸末日、核战废土等末世题材。包含聚落秩序、变异感染等核心体系。",
        "collections": [
            {"name": "聚落秩序体系", "category": "survivor_settlement_order_system", "description": "幸存者聚落、避难所与势力组织。"},
            {"name": "变异感染体系", "category": "mutation_infection_aberration_system", "description": "各类变异生物、感染等级与异变类型。"},
        ],
    },

    # ==================== 8. 悬疑推理模板 ====================
    "mystery_detective": {
        "key": "mystery_detective",
        "name": "悬疑推理基础模板",
        "description": "适用于侦探小说、犯罪悬疑等题材。包含犯罪类型、调查方法、法律程序等设定。",
        "collections": [
            {"name": "律法刑事体系", "category": "legal_criminal_system", "description": "刑事法律、犯罪类型与司法程序。"},
            {"name": "通讯情报体系", "category": "communication_intelligence_system", "description": "情报收集、线索追踪与信息网络。"},
        ],
    },

    # ==================== 9. 游戏异界/无限流模板 ====================
    "game_infinite_flow": {
        "key": "game_infinite_flow",
        "name": "游戏异界/无限流基础模板",
        "description": "适用于系统流、无限流、游戏穿越等题材。包含技能天赋、异能体系等游戏化设定。",
        "collections": [
            {"name": "技能天赋体系", "category": "skill_talent_system", "description": "主动技能、被动技能、天赋能力等游戏化设定。"},
            {"name": "异能体系", "category": "ability_system", "description": "超自然能力的分类与等级划分。"},
        ],
    },
}


# ==================== 通用体系自动注入 ====================

# 🆕 地图体系通用集合（自动注入所有基础模板）
MAP_COLLECTION: Dict[str, Any] = {
    "name": "地图体系",
    "category": "map_system",
    "description": "世界空间结构与地理要素的统一规范。用于承载大陆/区域/城镇/秘境/交通网络等信息，支持RAG检索与设定引用。",
    "max_depth": 4,
    "hierarchy_config": get_hierarchy_config_json("map_system"),
    "items": [
        {"name": "大陆版图", "level": 1, "code": "MAP_CONTINENT", "tags": ["地理", "整体"], "content": "世界整体地理格局（大陆/海洋/群岛）。列出主要大陆名称、相互位置与边界，以及自然与政治分区的宏观描述。"},
        {"name": "区域地形", "level": 1, "code": "MAP_REGION", "tags": ["地形", "区域"], "content": "各区域的地形特征（山脉/平原/森林/沙漠/冰原等），并简述资源分布与气候特点，为剧情场景与资源系统提供基础。"},
        {"name": "城镇与功能", "level": 1, "code": "MAP_TOWNS", "tags": ["城镇", "功能"], "content": "主要城市/城镇/据点的列表与定位，标注功能（贸易/宗门驻地/行政中心/黑市/学院等），用于人物与势力活动的落点。"},
        {"name": "秘境与禁地", "level": 2, "code": "MAP_SECRET_REALM", "tags": ["秘境", "危险"], "content": "秘境、遗迹、实验区、阵法结界、危险禁区等的空间位置与进入条件，结合阵法/资源/遗物设定，为任务与冒险提供钩子。"},
        {"name": "交通与传送网络", "level": 1, "code": "MAP_TRANSPORT", "tags": ["道路", "传送"], "content": "道路/航线/虫洞/传送阵/地铁/星门等交通体系。说明主要节点与连接关系，支持剧情推进与世界范围移动的合理性。"},
    ],
}

# 🆕 自动为所有模板注入“地图/势力/资源体系”（若不存在）
ORGANIZATION_FORCE_COLLECTION: Dict[str, Any] = {
    "name": "组织势力体系",
    "category": "organization_force_system",
    "description": "组织势力的统一规范。用于宗门/家族/王朝/商会/机构等信息，支持RAG检索与设定引用。",
    "hierarchy_config": get_hierarchy_config_json("organization_force_system"),
}
RESOURCE_COLLECTION: Dict[str, Any] = {
    "name": "资源体系",
    "category": "resource_system",
    "description": "世界资源与材料的统一规范。用于灵草/矿石/妖兽材料/天材地宝等信息，支持RAG检索与设定引用。",
    "hierarchy_config": get_hierarchy_config_json("resource_system"),
}
for _tpl_key, _tpl in SETTING_TEMPLATES.items():
    _cols = _tpl.get("collections", [])
    # 地图
    _has_map = any((c.get("category") == "map_system" or c.get("name") == "地图体系") for c in _cols)
    if not _has_map:
        _cols.append(MAP_COLLECTION)
    # 组织势力
    _has_force = any(c.get("category") == "organization_force_system" for c in _cols)
    if not _has_force:
        _cols.append(ORGANIZATION_FORCE_COLLECTION)
    # 资源
    _has_res = any(c.get("category") == "resource_system" for c in _cols)
    if not _has_res:
        _cols.append(RESOURCE_COLLECTION)


def get_templates_metadata() -> List[Dict[str, Any]]:
    """返回用于前端展示的模板元数据列表（包含集合简要信息）"""
    return [
        {
            "key": key,
            "name": tpl.get("name", key),
            "description": tpl.get("description", ""),
            "collections_count": len(tpl.get("collections", [])),
            "collections": [
                {"name": c.get("name", ""), "category": c.get("category", "")}
                for c in tpl.get("collections", [])
            ],
        }
        for key, tpl in SETTING_TEMPLATES.items()
    ]


def build_project_settings_summary(
    project_id: int,
    db: Session,
    relevant_categories: Optional[List[str]] = None,
    max_content_length: int = 300,
    max_items_per_collection: int = 12,
    max_total_length: int = 2400,
) -> str:
    """为指定项目生成世界观设定摘要（供AI Prompt或前端展示使用）

    修复 P1-1：此前条目数量无上限，长篇项目数百条设定会无限膨胀挤占生成预算。
    现按双层预算控制：每集合最多 max_items_per_collection 条 + 总长 max_total_length。

    Args:
        project_id: 项目ID
        db: 数据库会话
        relevant_categories: 需要包含的体系类别列表，None 表示全部
        max_content_length: 单条设定内容的最大长度
        max_items_per_collection: 每个集合最多列出的设定项数量
        max_total_length: 摘要总长度上限（字符）
    """
    query = db.query(SettingCollection).filter(
        SettingCollection.project_id == project_id,
        SettingCollection.category != "candidate",
    )
    if relevant_categories:
        query = query.filter(SettingCollection.category.in_(relevant_categories))

    collections = query.order_by(SettingCollection.order, SettingCollection.id).all()

    if not collections:
        return ""

    collection_ids = [collection.id for collection in collections]
    items = (
        db.query(SettingItem)
        .filter(SettingItem.collection_id.in_(collection_ids))
        .order_by(SettingItem.collection_id, SettingItem.order, SettingItem.id)
        .all()
    )
    items_by_collection: Dict[int, List[SettingItem]] = {}
    for item in items:
        items_by_collection.setdefault(item.collection_id, []).append(item)

    lines: List[str] = []
    lines.append("## 世界观设定体系")
    total_length = len(lines[0])

    for collection in collections:
        if total_length >= max_total_length:
            break

        collection_items = items_by_collection.get(collection.id, [])
        # 预算控制：每集合最多保留 max_items_per_collection 条
        shown_items = collection_items[:max_items_per_collection]
        if not shown_items and not collection.description:
            continue

        lines.append("")
        title = collection.name or "未命名集合"
        lines.append(f"### {title}")
        total_length += len(title) + 5
        if collection.category:
            lines.append(f"- 分类：{collection.category}")
            total_length += len(collection.category) + 6
        if collection.description:
            desc = collection.description.strip()
            lines.append(desc)
            total_length += len(desc) + 1

        truncated_hint = ""
        if len(collection_items) > max_items_per_collection:
            truncated_hint = (
                f"（其余 {len(collection_items) - max_items_per_collection} 项略）"
            )

        for item in shown_items:
            if total_length >= max_total_length:
                truncated_hint = "（超出预算，其余项略）"
                break
            try:
                tags = json.loads(item.tags) if item.tags else None
            except Exception:
                tags = None
            tag_str = f" [{'、'.join(tags)}]" if tags else ""
            code_part = f"（{item.code}）" if item.code else ""

            indent = "  " * max((item.depth or 1) - 1, 0)
            name_line = f"{indent}- {item.name}{code_part}{tag_str}"
            lines.append(name_line)
            total_length += len(name_line) + 1
            if item.content:
                content = item.content.strip()
                if len(content) > max_content_length:
                    content = content[:max_content_length] + "..."
                content_line = f"{indent}  - {content}"
                lines.append(content_line)
                total_length += len(content_line) + 1

        if truncated_hint:
            lines.append(f"- {truncated_hint}")

    summary = "\n".join(lines)
    if len(summary) > max_total_length:
        summary = summary[:max_total_length] + "…"
    return summary


def build_settings_catalog_text(
    project_id: int,
    db: Session,
    *,
    max_names_per_category: int = 15,
    max_total_length: int = 1500,
) -> str:
    """生成项目设定中心的紧凑设定清单（仅供章节规划引用，不含内容）。

    按体系类别分组列出设定项名称，供章节规划 LLM 在"设定调用"字段中
    选择复用，避免规划发明与设定中心冲突的新设定。

    Args:
        project_id: 项目ID
        db: 数据库会话
        max_names_per_category: 每个类别最多列出的设定名称数
        max_total_length: 清单总长度上限（字符）
    """
    collections = (
        db.query(SettingCollection)
        .filter(
            SettingCollection.project_id == project_id,
            SettingCollection.category != "candidate",
        )
        .order_by(SettingCollection.order, SettingCollection.id)
        .all()
    )
    if not collections:
        return ""

    collection_ids = [collection.id for collection in collections]
    items = (
        db.query(SettingItem)
        .filter(SettingItem.collection_id.in_(collection_ids))
        .order_by(SettingItem.collection_id, SettingItem.order, SettingItem.id)
        .all()
    )
    names_by_collection: Dict[int, List[str]] = {}
    for item in items:
        name = (item.name or "").strip()
        if name:
            names_by_collection.setdefault(item.collection_id, []).append(name)

    lines: List[str] = []
    for collection in collections:
        names = names_by_collection.get(collection.id, [])
        if not names:
            continue
        if len(names) > max_names_per_category:
            shown = names[:max_names_per_category]
            lines.append(f"- {collection.name}（{len(names)}项）：{'、'.join(shown)}等")
        else:
            lines.append(f"- {collection.name}：{'、'.join(names)}")

    catalog = "\n".join(lines)
    if len(catalog) > max_total_length:
        catalog = catalog[:max_total_length] + "…"
    return catalog


def extract_relevant_categories_from_text(text: str) -> List[str]:
    """从文本中提取涉及的体系类别关键词，用于按需注入设定摘要。

    扫描文本中出现的类别关键词，返回匹配的体系类别列表。
    """
    from app.services.setting_categories import TYPE_TO_CATEGORY_MAP

    if not text:
        return []

    matched: set = set()
    for keyword, category in TYPE_TO_CATEGORY_MAP.items():
        if keyword in text:
            matched.add(category)

    return list(matched)

