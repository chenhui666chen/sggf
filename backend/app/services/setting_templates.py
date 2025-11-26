"""类型化设定模板与设定摘要工具函数"""
from typing import Dict, Any, List
import json

from sqlalchemy.orm import Session

from app.models.setting import SettingCollection, SettingItem

# 简单内置模板示例：可按需继续扩展
SETTING_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "xuanhuan_basic": {
        "key": "xuanhuan_basic",
        "name": "玄幻修真基础模板",
        "description": "适用于凡人修真、大陆争霸类玄幻体系。包含基础境界和功法、丹药、阵法等基础体系。",
        "collections": [
            {
                "name": "境界体系",
                "category": "cultivation_system",
                "description": "从凡人到飞升的大致修行阶段。",
                "items": [
                    {"name": "炼气期", "level": 1, "code": "L1", "tags": ["入门", "凡人"], "content": "初入修行，通过吐纳炼化灵气强化肉身和经脉。"},
                    {"name": "筑基期", "level": 2, "code": "L2", "tags": ["基础稳固"], "content": "筑下道基，灵气在体内形成稳定循环，为后续境界奠定根基。"},
                    {"name": "金丹期", "level": 3, "code": "L3", "tags": ["质变"], "content": "丹成一颗，神识初开，战力与寿元迎来飞跃。"},
                ],
            },
            {
                "name": "功法体系",
                "category": "technique_system",
                "description": "区分不同修行功法与流派，可在人物设定中通过关联表示“已掌握功法”。",
                "items": [
                    {"name": "基础心法", "level": 1, "code": "BASIC_CORE", "tags": ["通用", "心法", "黄阶下品"], "content": "适用于大多数凡人修行者的入门心法，用于打通经脉，为后续高阶功法奠定根基。修炼要求：炼气期及以上。"},
                    {"name": "宗门镇派功法", "level": 3, "code": "SECT_CORE", "tags": ["宗门", "核心", "玄阶上品"], "content": "只有核心弟子才有资格修炼的高阶功法，往往与宗门气运相连。修炼要求：至少达到金丹期，并通过宗门大考。"},
                    {"name": "太虚剑诀", "level": 4, "code": "SWORD_TAIXU", "tags": ["剑修", "攻击", "地阶上品"], "content": "主打极速与锋锐的剑道功法，可在瞬间爆发毁灭性剑气。修炼要求：金丹后期以上剑修，需兼具强大神识与剑意。"},
                ],
            },
            {
                "name": "丹药体系",
                "category": "pill_system",
                "description": "各类修行丹药及其品阶与功效。",
                "items": [
                    {"name": "筑基丹", "level": 1, "code": "PILL_FOUNDATION", "tags": ["突破", "筑基", "黄阶上品"], "content": "帮助炼气期修士稳固道基、冲击筑基境界的基础丹药。炼制难度较低，主材为灵草与一两株百年药材。"},
                    {"name": "金丹", "level": 2, "code": "PILL_GOLD_CORE", "tags": ["突破", "金丹", "玄阶中品"], "content": "协助筑基晚期修士冲击金丹境界的关键丹药，能显著提升凝聚金丹的成功率。炼制难度中等，需要多种百年灵药。"},
                    {"name": "破境丹", "level": 3, "code": "PILL_BREAKTHROUGH", "tags": ["突破", "高阶", "地阶下品"], "content": "用于冲击高阶大境界（如元婴、化神）的强效丹药，可在短时间内大幅提升灵力运转上限，但副作用明显。"},
                    {"name": "疗伤丹", "level": 1, "code": "PILL_HEALING", "tags": ["恢复", "战斗后"], "content": "常见恢复类丹药，可快速愈合外伤、止血镇痛，多用于战斗后修整。炼制难度低，材料易得。"},
                ],
            },
            {
                "name": "阵法体系",
                "category": "formation_system",
                "description": "护山大阵、困敌阵、传送阵等各类阵法体系。",
                "items": [
                    {"name": "护山大阵", "level": 3, "code": "FORM_MOUNTAIN_GUARD", "tags": ["防御", "宗门"], "content": "守护宗门山门的核心防御大阵，可在遭受攻击时自动激活护罩，抵挡同境界修士的联手攻伐。布阵要求：需多名阵法师联手，在山门各处埋下阵基。"},
                    {"name": "困敌阵", "level": 2, "code": "FORM_TRAP_ENEMY", "tags": ["困锁", "战斗"], "content": "以地势和阵旗为引，将敌人锁在阵中，使其难以脱身，适合围捕与消耗战。布阵要求：提前布置阵旗或阵盘，引导敌人踏入阵眼。"},
                    {"name": "传送阵", "level": 2, "code": "FORM_TELEPORT", "tags": ["传送", "远程"], "content": "可在两地之间开辟稳定通道，实现修士与物资的长距离传送。布阵要求：两端同时布置阵基，并消耗大量灵石维持。"},
                    {"name": "聚灵阵", "level": 1, "code": "FORM_SPIRIT_GATHER", "tags": ["修炼", "灵气浓郁"], "content": "汇聚天地灵气，使阵内灵气浓度远超外界，适合作为修炼密室或洞府的基础阵法。布阵要求：在节点埋下灵石与灵纹石。"},
                ],
            },
            {
                "name": "符箓体系",
                "category": "talisman_system",
                "description": "常见攻防身法与辅助类符箓。",
                "items": [
                    {"name": "火球符", "level": 1, "code": "TAL_FIREBALL", "tags": ["攻击", "一次性"], "content": "激活后释放一枚相当于炼气中期修士全力一击的火球术，适合凡人或低阶修士保命使用。绘制难度低，消耗少量灵力与灵墨。"},
                    {"name": "金刚符", "level": 1, "code": "TAL_DIAMOND", "tags": ["防御", "护身"], "content": "在短时间内大幅提升身体与护体灵光的防御力，可抵挡多次普通攻击。绘制难度中等，需使用金属性灵材研制的符纸。"},
                    {"name": "遁地符", "level": 2, "code": "TAL_EARTH_ESCAPE", "tags": ["遁逃", "保命"], "content": "激活后可让持符者短时间融入大地，快速脱离战场，适合作为底牌保命之用。绘制难度较高，对符师神识要求严苛。"},
                    {"name": "传讯符", "level": 1, "code": "TAL_MESSAGE", "tags": ["通讯", "远程"], "content": "可将一段语音或神识讯息封入符中，跨越数千里传递给指定对象。常用于宗门内部联络。"},
                ],
            },
            {
                "name": "武器与法宝体系",
                "category": "weapon_system",
                "description": "飞剑、法杖、护甲、储物类法宝等常见战斗与辅助器物。",
                "items": [
                    {"name": "飞剑", "level": 1, "code": "WEAPON_FLYING_SWORD", "tags": ["武器", "剑修", "法器"], "content": "最常见的攻击型法器之一，可用于近战斩击或御剑远攻。品质从凡铁飞剑到灵器飞剑不等，是剑修标配。"},
                    {"name": "灵木法杖", "level": 1, "code": "WEAPON_WOOD_STAFF", "tags": ["法器", "辅助", "术修"], "content": "以千年灵木炼制的法杖，可加持术法威力并稳定法阵，多见于术士与辅助型修士手中。"},
                    {"name": "护心甲", "level": 2, "code": "ARMOR_HEART_GUARD", "tags": ["防御", "护甲", "灵器"], "content": "覆盖胸腹要害的轻甲类灵器，可自动感应危机，在受到致命一击前激活护盾。对身法无明显影响。"},
                    {"name": "储物戒指", "level": 1, "code": "TREASURE_STORAGE_RING", "tags": ["空间", "辅助"], "content": "内藏独立小型空间，可存放大量物资与灵材，是中高阶修士的标配法宝。品质越高，容量越大。"},
                ],
            },
        ],
    },
    "urban_power": {
        "key": "urban_power",
        "name": "都市异能模板",
        "description": "适用于现代都市+异能/财阀博弈题材。",
        "collections": [
            {
                "name": "能力体系",
                "category": "ability_system",
                "description": "对各类超凡能力进行分级和命名。",
                "items": [
                    {"name": "觉醒者", "level": 1, "code": "AWAKENED", "tags": ["入门", "能力觉醒"], "content": "刚刚觉醒异能，能力不稳定，需通过训练掌握。"},
                    {"name": "操控者", "level": 2, "code": "CONTROLLER", "tags": ["能力熟练"], "content": "能够稳定运用能力，并在战斗和商业领域初露锋芒。"},
                ],
            },
            {
                "name": "势力体系",
                "category": "faction_system",
                "description": "主要财阀、财团、地下组织、官方机构等划分。",
                "items": [
                    {"name": "官方能力管理局", "level": 1, "code": "GOV_BUREAU", "tags": ["官方", "秩序"], "content": "负责登记、监管异能者，表面中立，内部派系林立。"},
                    {"name": "黑金财团", "level": 2, "code": "BLACK_GOLD", "tags": ["财团", "灰色势力"], "content": "掌控多家跨国公司与地下组织，以资本和人脉影响城市秩序。"},
                ],
            },
        ],
    },
}


def get_templates_metadata() -> List[Dict[str, Any]]:
    """返回用于前端展示的模板元数据列表"""
    return [
        {
            "key": key,
            "name": tpl.get("name", key),
            "description": tpl.get("description", ""),
            "collections_count": len(tpl.get("collections", [])),
        }
        for key, tpl in SETTING_TEMPLATES.items()
    ]


def build_project_settings_summary(project_id: int, db: Session) -> str:
    """为指定项目生成世界观设定摘要（供AI Prompt或前端展示使用）"""
    collections = (
        db.query(SettingCollection)
        .filter(SettingCollection.project_id == project_id)
        .order_by(SettingCollection.order, SettingCollection.id)
        .all()
    )

    if not collections:
        return ""

    lines: List[str] = []
    lines.append("## 世界观设定体系")

    for collection in collections:
        lines.append("")
        title = collection.name or "未命名集合"
        lines.append(f"### {title}")
        if collection.category:
            lines.append(f"- 分类：{collection.category}")
        if collection.description:
            lines.append(collection.description.strip())

        items = (
            db.query(SettingItem)
            .filter(SettingItem.collection_id == collection.id)
            .order_by(SettingItem.order, SettingItem.id)
            .all()
        )

        for item in items:
            try:
                tags = json.loads(item.tags) if item.tags else None
            except Exception:
                tags = None
            tag_str = f" [{'、'.join(tags)}]" if tags else ""
            level_part = f"Lv.{item.level} " if item.level is not None else ""
            code_part = f"（{item.code}）" if item.code else ""
            lines.append(f"- {level_part}{item.name}{code_part}{tag_str}")
            if item.content:
                content = item.content.strip()
                # 控制单条过长内容，避免Prompt过度膨胀
                if len(content) > 200:
                    content = content[:200] + "..."
                lines.append(f"  - {content}")

    return "\n".join(lines)

