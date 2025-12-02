"""类型化设定模板与设定摘要工具函数"""
from typing import Dict, Any, List
import json

from sqlalchemy.orm import Session

from app.models.setting import SettingCollection, SettingItem

# 🆕 层级模板默认配置（按体系类别）
# 说明：
# - max_depth: 最大深度
# - levels: 各层级定义
#   - depth: 层级深度（1-based）
#   - name: 层级名称
#   - type: 节点类型（system=体系根/category=分类/list=列表/detail=详情）
#   - leaf: 是否为叶子节点
#   - examples: 示例（用于UI提示）
HIERARCHY_DEFAULTS: Dict[str, Dict[str, Any]] = {
    # ==================== 地理与世界观体系 ====================
    "map_system": {
        "max_depth": 4,
        "levels": [
            {"depth": 1, "name": "地图体系", "type": "system"},
            {"depth": 2, "name": "地域分类", "type": "category", "examples": ["大陆版图", "区域地形", "城镇聚落", "秘境禁地", "交通网络"]},
            {"depth": 3, "name": "地点列表", "type": "list"},
            {"depth": 4, "name": "地点详情", "type": "detail", "leaf": True},
        ],
    },
    
    # ==================== 修仙/玄幻体系 ====================
    "cultivation_realm_system": {
        "max_depth": 2,
        "levels": [
            {"depth": 1, "name": "修仙境界体系", "type": "system"},
            {"depth": 2, "name": "境界详情", "type": "detail", "leaf": True},
        ],
    },
    "technique_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "功法体系", "type": "system"},
            {"depth": 2, "name": "功法分类", "type": "category", "examples": ["心法", "剑法", "拳法", "身法", "刀法", "掌法"]},
            {"depth": 3, "name": "功法详情", "type": "detail", "leaf": True},
        ],
    },
    "pill_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "丹药体系", "type": "system"},
            {"depth": 2, "name": "丹药分类", "type": "category", "examples": ["突破丹药", "恢复丹药", "辅助丹药", "特殊丹药"]},
            {"depth": 3, "name": "丹药详情", "type": "detail", "leaf": True},
        ],
    },
    "formation_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "阵法体系", "type": "system"},
            {"depth": 2, "name": "阵法分类", "type": "category", "examples": ["攻击阵", "防御阵", "困敌阵", "辅助阵", "传送阵"]},
            {"depth": 3, "name": "阵法详情", "type": "detail", "leaf": True},
        ],
    },
    "talisman_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "符箓体系", "type": "system"},
            {"depth": 2, "name": "符箓分类", "type": "category", "examples": ["攻击符", "防御符", "遁逃符", "辅助符"]},
            {"depth": 3, "name": "符箓详情", "type": "detail", "leaf": True},
        ],
    },
    "weapon_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "武器法宝体系", "type": "system"},
            {"depth": 2, "name": "装备分类", "type": "category", "examples": ["武器", "护甲", "法器", "灵器", "法宝", "辅助器物"]},
            {"depth": 3, "name": "装备详情", "type": "detail", "leaf": True},
        ],
    },
    "resource_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "资源体系", "type": "system"},
            {"depth": 2, "name": "资源分类", "type": "category", "examples": ["灵草灵药", "矿石材料", "妖兽材料", "炼丹材料", "炼器材料", "天材地宝"]},
            {"depth": 3, "name": "资源详情", "type": "detail", "leaf": True},
        ],
    },
    "force_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "势力体系", "type": "system"},
            {"depth": 2, "name": "势力分类", "type": "category", "examples": ["宗门", "家族", "王朝", "商会", "散修联盟"]},
            {"depth": 3, "name": "势力详情", "type": "detail", "leaf": True},
        ],
    },
    
    # ==================== 都市异能体系 ====================
    "ability_realm_system": {
        "max_depth": 2,
        "levels": [
            {"depth": 1, "name": "异能境界体系", "type": "system"},
            {"depth": 2, "name": "境界详情", "type": "detail", "leaf": True},
        ],
    },
    "ability_awakening_growth_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "异能体系", "type": "system"},
            {"depth": 2, "name": "能力分类", "type": "category", "examples": ["等级划分", "能力类型", "成长路径"]},
            {"depth": 3, "name": "能力详情", "type": "detail", "leaf": True},
        ],
    },
    "hidden_organization_force_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "组织势力体系", "type": "system"},
            {"depth": 2, "name": "组织分类", "type": "category", "examples": ["官方机构", "地下组织", "古老家族", "佣兵团体"]},
            {"depth": 3, "name": "组织详情", "type": "detail", "leaf": True},
        ],
    },
    "network_social_relationship_system": {
        "max_depth": 2,
        "levels": [
            {"depth": 1, "name": "人脉关系体系", "type": "system"},
            {"depth": 2, "name": "关系详情", "type": "detail", "leaf": True},
        ],
    },
    "special_artifact_relic_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "道具遗物体系", "type": "system"},
            {"depth": 2, "name": "道具分类", "type": "category", "examples": ["觉醒结晶", "封印器具", "上古遗物", "异能武器", "防护装置"]},
            {"depth": 3, "name": "道具详情", "type": "detail", "leaf": True},
        ],
    },
    "wealth_business_empire_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "财富商业体系", "type": "system"},
            {"depth": 2, "name": "商业分类", "type": "category", "examples": ["交易所", "家族企业", "地下市场", "佣兵平台"]},
            {"depth": 3, "name": "商业详情", "type": "detail", "leaf": True},
        ],
    },
    
    # ==================== 西幻/魔法体系 ====================
    "magic_realm_system": {
        "max_depth": 2,
        "levels": [
            {"depth": 1, "name": "魔法境界体系", "type": "system"},
            {"depth": 2, "name": "境界详情", "type": "detail", "leaf": True},
        ],
    },
    "magic_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "魔法体系", "type": "system"},
            {"depth": 2, "name": "魔法分类", "type": "category", "examples": ["元素魔法", "治疗魔法", "召唤魔法", "死灵魔法", "时空魔法"]},
            {"depth": 3, "name": "魔法详情", "type": "detail", "leaf": True},
        ],
    },
    "race_bloodline_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "种族血脉体系", "type": "system"},
            {"depth": 2, "name": "种族分类", "type": "category", "examples": ["常见种族", "稀有种族", "血脉传承"]},
            {"depth": 3, "name": "种族详情", "type": "detail", "leaf": True},
        ],
    },
    "profession_class_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "职业体系", "type": "system"},
            {"depth": 2, "name": "职业分类", "type": "category", "examples": ["战士系", "法师系", "牧师系", "刺客系", "游侠系"]},
            {"depth": 3, "name": "职业详情", "type": "detail", "leaf": True},
        ],
    },
    "martial_realm_system": {
        "max_depth": 2,
        "levels": [
            {"depth": 1, "name": "武道境界体系", "type": "system"},
            {"depth": 2, "name": "境界详情", "type": "detail", "leaf": True},
        ],
    },
    
    # ==================== 科幻体系 ====================
    "interstellar_travel_exploration_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "星际航行体系", "type": "system"},
            {"depth": 2, "name": "技术分类", "type": "category", "examples": ["推进系统", "导航系统", "探测设备"]},
            {"depth": 3, "name": "技术详情", "type": "detail", "leaf": True},
        ],
    },
    "ai_robot_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "AI机器人体系", "type": "system"},
            {"depth": 2, "name": "类型分类", "type": "category", "examples": ["人工智能", "仿生机器人", "战斗机甲"]},
            {"depth": 3, "name": "类型详情", "type": "detail", "leaf": True},
        ],
    },
    
    # ==================== 末世废土体系 ====================
    "survivor_settlement_order_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "聚落秩序体系", "type": "system"},
            {"depth": 2, "name": "聚落分类", "type": "category", "examples": ["营地据点", "交易中心", "军事势力", "科技避难所"]},
            {"depth": 3, "name": "聚落详情", "type": "detail", "leaf": True},
        ],
    },
    "mutation_infection_aberration_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "变异感染体系", "type": "system"},
            {"depth": 2, "name": "变异分类", "type": "category", "examples": ["辐射变异", "生化感染", "超自然畸变"]},
            {"depth": 3, "name": "变异详情", "type": "detail", "leaf": True},
        ],
    },
    
    # ==================== 游戏系统体系 ====================
    "skill_talent_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "技能天赋体系", "type": "system"},
            {"depth": 2, "name": "技能分类", "type": "category", "examples": ["主动技能", "被动技能", "职业技能", "终极技能"]},
            {"depth": 3, "name": "技能详情", "type": "detail", "leaf": True},
        ],
    },
    
    # ==================== 角色体系 ====================
    "character_system": {
        "max_depth": 3,
        "levels": [
            {"depth": 1, "name": "角色体系", "type": "system"},
            {"depth": 2, "name": "角色分类", "type": "category", "examples": ["主角团", "配角", "反派", "NPC"]},
            {"depth": 3, "name": "角色详情", "type": "detail", "leaf": True},
        ],
    },
    
    # ==================== 候选集合（特殊体系）====================
    "candidate": {
        "max_depth": 2,
        "levels": [
            {"depth": 1, "name": "候选集合", "type": "system"},
            {"depth": 2, "name": "候选项详情", "type": "detail", "leaf": True},
        ],
    },
}


def get_hierarchy_config_json(category: str) -> str:
    """返回指定体系类别的默认层级模板JSON字符串"""
    cfg = HIERARCHY_DEFAULTS.get(category) or {"max_depth": 2, "levels": [{"depth": 1, "name": "默认体系", "type": "system"}, {"depth": 2, "name": "详情", "type": "detail", "leaf": True}]}
    return json.dumps(cfg, ensure_ascii=False)


# 简单内置模板示例：可按需继续扩展
SETTING_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "xuanhuan_basic": {
        "key": "xuanhuan_basic",
        "name": "玄幻修真基础模板",
        "description": "适用于凡人修真、大陆争霸类玄幻体系。包含基础境界和功法、丹药、阵法等基础体系。",
        "collections": [
            {
                "name": "修仙境界体系",
                "category": "cultivation_realm_system",
                "description": "从凡人到飞升的大致修行阶段。",
                "items": [
                    {"name": "炼气期", "level": 1, "code": "REALM_1", "tags": ["入门", "凡人"], "content": "初入修行，通过吐纳炼化灵气强化肉身和经脉。寿元50-100年。"},
                    {"name": "筑基期", "level": 2, "code": "REALM_2", "tags": ["基础稳固"], "content": "筑下道基，灵气在体内形成稳定循环，为后续境界奠定根基。寿元200-300年。"},
                    {"name": "金丹期", "level": 3, "code": "REALM_3", "tags": ["质变"], "content": "丹成一颗，神识初开，战力与寿元迎来飞跃。寿元500-800年。"},
                    {"name": "元婴期", "level": 4, "code": "REALM_4", "tags": ["元婴"], "content": "金丹破碎，元婴诞生，神识化形，可离体存活。寿元1000-1500年。"},
                    {"name": "化神期", "level": 5, "code": "REALM_5", "tags": ["中阶"], "content": "元婴与神识融合，化为元神，脱去凡胎，初步超脱。寿元2000-3000年。"},
                    {"name": "渡劫期", "level": 6, "code": "REALM_6", "tags": ["天劫"], "content": "需经历天劫考验，每九百年一劫，渡过则寿元大增，失败则飞灰湮灭。寿元4000-5000年。"},
                    {"name": "大乘期", "level": 7, "code": "REALM_7", "tags": ["飞升前"], "content": "渡过九重天劫，达到凡人修仙的极致，随时可飞升仙界。寿元5000-10000年。"},
                    {"name": "仙人", "level": 8, "code": "REALM_8", "tags": ["飞升", "仙界"], "content": "飞升仙界，超脱凡俗，成就真仙，寿元漫长，有机会证道永生。"},
                ],
            },
            {
                "name": "武道境界体系",
                "category": "martial_realm_system",
                "description": "武道修炼的境界划分与力量成长体系。",
                "items": [
                    {"name": "后天武者", "level": 1, "code": "REALM_POSTNATAL", "tags": ["入门", "凡人"], "content": "初入武道，通过锻炼身体和修炼内功，打通部分经脉。力量、速度和耐力都超越常人。"},
                    {"name": "先天武者", "level": 2, "code": "REALM_INNATE", "tags": ["先天"], "content": "打通任督二脉，内力生生不息。可以将内力外放，形成护体罡气。是江湖中真正的高手。"},
                    {"name": "宗师", "level": 3, "code": "REALM_GRANDMASTER", "tags": ["宗师"], "content": "武道造诣达到极高境界，能够领悟武道真意。一招一式都蕴含天地之力，是一方霸主。"},
                    {"name": "大宗师", "level": 4, "code": "REALM_SUPREME_MASTER", "tags": ["大宗师"], "content": "对武道有了更深的理解，能够创立自己的武学流派。武道真意凝实，可以影响周围天地元气。"},
                    {"name": "武圣", "level": 5, "code": "REALM_MARTIAL_SAINT", "tags": ["武圣", "传奇"], "content": "武道达到圣境，超凡脱俗。一拳可碎山岳，一掌可断江河。寿元大增，可活数百年。整个大陆也只有寥寥数人。"},
                    {"name": "武神", "level": 6, "code": "REALM_MARTIAL_GOD", "tags": ["武神", "神话"], "content": "武道的极致，达到了凡人武道的巅峰。举手投足间天地变色，可以飞天遁地，几近神明。传说中的存在，世间罕有。"},
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
            {
                "name": "资源体系",
                "category": "resource_system",
                "description": "修真世界中的各类资源材料，包括灵草、矿石、丹药材料、炼器材料及天材地宝等。",
                "items": [
                    # 灵草类
                    {"name": "灵芝草", "level": 1, "code": "HERB_LINGZHI", "tags": ["灵草", "黄阶", "常见"], "content": "最常见的入门级灵草，生长于灵气充沛之地。功效：可用于炼制筑基丹等低阶丹药，也可直接服用补充灵力。获取途径：野外采集或坊市购买。"},
                    {"name": "紫灵兰", "level": 2, "code": "HERB_ZILING_ORCHID", "tags": ["灵草", "玄阶", "稀有"], "content": "百年生灵草，花瓣呈紫色，散发淡淡灵气。功效：炼制金丹丹药的主材之一，可稳固修士金丹。获取途径：深山灵脉或仙门药园。"},
                    {"name": "九转灵莲", "level": 3, "code": "HERB_JIUZHUAN_LOTUS", "tags": ["灵草", "地阶", "珍稀"], "content": "千年生灵莲，每百年开花一次，需九次开花方可采摘。功效：炼制破境丹的核心材料，可大幅提升突破成功率。获取途径：上古秘境或大宗门密藏。"},
                    {"name": "万年雪参", "level": 4, "code": "HERB_WANNIAN_GINSENG", "tags": ["灵草", "天阶", "极品"], "content": "万年灵参，生于极寒之地，通体晶莹如雪。功效：可直接提升一个小境界，或用于炼制天阶丹药。获取途径：北域极地、化神强者洞府遗址。"},
                    # 矿石类
                    {"name": "灵铁矿", "level": 1, "code": "ORE_LING_IRON", "tags": ["矿石", "黄阶", "基础"], "content": "最基础的炼器材料，含有微量灵气。用途：打造低阶法器、飞剑的基础材料。获取途径：普通矿脉或坊市购买。"},
                    {"name": "寒铁精", "level": 2, "code": "ORE_COLD_IRON", "tags": ["矿石", "玄阶", "稀有"], "content": "形成于寒潭深处的特殊矿石，自带寒意。用途：打造冰属性法器、护甲的核心材料。获取途径：寒潭深处或北域矿脉。"},
                    {"name": "天外陨铁", "level": 3, "code": "ORE_METEOR_IRON", "tags": ["矿石", "地阶", "珍稀"], "content": "坠落自天外的神秘陨石，含有星辰之力。用途：打造地阶以上法宝的首选材料，可增加法宝威力。获取途径：陨石坠落点或大势力密藏。"},
                    {"name": "混沌精金", "level": 4, "code": "ORE_CHAOS_GOLD", "tags": ["矿石", "天阶", "传说"], "content": "传说开天辟地时遗留的神金，坚不可摧。用途：打造仙器级法宝的唯一材料，极其珍贵。获取途径：上古遗迹、仙人洞府。"},
                    # 丹药材料
                    {"name": "龙涎香", "level": 2, "code": "MAT_DRAGON_AMBERGRIS", "tags": ["丹药材料", "玄阶", "辅材"], "content": "传说由蛟龙唾液凝结而成的珍贵材料。用途：炼丹时可提升丹药品质，是高阶丹药的常用辅材。获取途径：蛟龙栖息地、深海密境。"},
                    {"name": "凤血石", "level": 3, "code": "MAT_PHOENIX_BLOOD_STONE", "tags": ["丹药材料", "地阶", "主材"], "content": "凤凰涅槃时滴落的精血凝成的宝石。用途：炼制回生类丹药的核心材料，可起死回生。获取途径：凤凰传承地、古老仙门密藏。"},
                    {"name": "五行灵液", "level": 2, "code": "MAT_FIVE_ELEMENT_LIQUID", "tags": ["丹药材料", "玄阶", "辅材"], "content": "由五行灵气凝结而成的神秘液体。用途：可平衡丹药药性，提升炼丹成功率。获取途径：五行汇聚之地或高阶炼丹师提炼。"},
                    # 炼器材料
                    {"name": "雷电精华", "level": 2, "code": "MAT_THUNDER_ESSENCE", "tags": ["炼器材料", "玄阶", "雷属性"], "content": "雷电之力凝结的精华，蕴含毁灭之力。用途：打造雷属性法器、增加法宝雷电威能。获取途径：雷劫区域、渡劫失败修士遗物。"},
                    {"name": "星辰砂", "level": 3, "code": "MAT_STAR_SAND", "tags": ["炼器材料", "地阶", "星辰"], "content": "来自星辰碎裂的神秘晶砂，闪烁星芒。用途：炼制星辰法阵、增加法宝空间属性。获取途径：星河秘境、天象师炼制。"},
                    {"name": "太阴精华", "level": 3, "code": "MAT_LUNAR_ESSENCE", "tags": ["炼器材料", "地阶", "月属性"], "content": "月华凝结的精华，蕴含太阴之力。用途：打造阴属性法器、炼制月华法阵。获取途径：月圆之夜高空采集、月宫传承地。"},
                    # 妖兽材料
                    {"name": "妖兽内丹", "level": 2, "code": "MAT_DEMON_CORE", "tags": ["妖兽材料", "玄阶", "核心"], "content": "妖兽体内凝结的灵力结晶，等级与妖兽修为相当。用途：炼制丹药辅材、炼器时增加法宝灵性。获取途径：猎杀妖兽获得。"},
                    {"name": "蛟龙鳞片", "level": 3, "code": "MAT_JIAO_DRAGON_SCALE", "tags": ["妖兽材料", "地阶", "防御"], "content": "蛟龙身上脱落的鳞片，坚硬无比。用途：打造防御类法器、护甲的极品材料。获取途径：蛟龙换鳞地或猎杀获得。"},
                    {"name": "凤凰羽毛", "level": 4, "code": "MAT_PHOENIX_FEATHER", "tags": ["妖兽材料", "天阶", "火属性"], "content": "凤凰脱落的神羽，蕴含涅槃之力。用途：炼制火属性天阶法宝的必备材料。获取途径：凤凰传承地、上古仙人遗物。"},
                    # 天材地宝
                    {"name": "灵石", "level": 1, "code": "TREASURE_SPIRIT_STONE", "tags": ["天材地宝", "黄阶", "货币"], "content": "修真界通用货币，分为下品、中品、上品、极品。用途：修炼、交易、驱动阵法等。获取途径：灵石矿脉或任务报酬。"},
                    {"name": "聚灵珠", "level": 2, "code": "TREASURE_GATHERING_PEARL", "tags": ["天材地宝", "玄阶", "修炼"], "content": "可自动汇聚周围灵气的神秘珠子。用途：辅助修炼，提升修炼速度30%以上。获取途径：海底灵蚌或高阶秘境。"},
                    {"name": "混元珠", "level": 4, "code": "TREASURE_HUNYUAN_PEARL", "tags": ["天材地宝", "天阶", "至宝"], "content": "传说开天辟地前存在的神秘珠子，蕴含无尽造化。用途：可直接提升大境界或炼制仙丹。获取途径：仙人遗址、上古秘境核心。"},
                ],
            },
        ],
    },
    "urban_power": {
        "key": "urban_power",
        "name": "都市异能基础模板",
        "description": "专注于现代背景下的超自然力量与社会结构，适用于都市修真、现代异能等题材。",
        "collections": [
            {
                "name": "异能境界体系",
                "category": "ability_realm_system",
                "description": "异能者的等级划分与成长路径。",
                "items": [
                    {"name": "觉醒者", "level": 1, "code": "REALM_AWAKENED", "tags": ["入门", "F级"], "content": "刚刚觉醒异能的新人，能力不稳定，仅能在特定情绪下触发。需要接受基础训练才能自主控制能力。"},
                    {"name": "E级", "level": 2, "code": "REALM_E", "tags": ["初级"], "content": "能够基本控制能力，但还需要努力集中才能使用。在异能者中处于入门阶段。"},
                    {"name": "D级", "level": 3, "code": "REALM_D", "tags": ["进阶"], "content": "能够稳定运用能力，对自身异能有基本理解。可完成普通任务，在异能者社会中占据多数。"},
                    {"name": "C级", "level": 4, "code": "REALM_C", "tags": ["精英"], "content": "已经熟练掌握能力，能在战斗中灵活运用。是各大势力的核心战力。"},
                    {"name": "B级", "level": 5, "code": "REALM_B", "tags": ["高阶"], "content": "将异能修炼至精深，能够开发出独特的能力应用方式。是各大势力争抢的顶尖战力。"},
                    {"name": "A级", "level": 6, "code": "REALM_A", "tags": ["大师"], "content": "能力达到了一个极高的境界，可以单独执行高危任务。在一个城市中都能拥有显赫地位。"},
                    {"name": "S级", "level": 7, "code": "REALM_S", "tags": ["超凡"], "content": "突破人类极限的存在，单人即可影响一座城市的格局。全球仅有数十位，各国均有专门档案追踪。"},
                    {"name": "SSS级", "level": 8, "code": "REALM_SSS", "tags": ["神话"], "content": "传说中的级别，超越了普通异能者的认知。单人即是一支军队，可以改变一个国家的命运。全球只有少数几人。"},
                ],
            },
            {
                "name": "异能觉醒与成长体系",
                "category": "ability_awakening_growth_system",
                "description": "异能者的觉醒方式、能力等级划分及成长路径。",
                "items": [
                    {"name": "觉醒者", "level": 1, "code": "AWK_INITIAL", "tags": ["入门", "F级"], "content": "刚刚觉醒异能的新人，能力不稳定，仅能在特定情绪下触发。需要接受基础训练才能自主控制能力。"},
                    {"name": "掌控者", "level": 2, "code": "AWK_CONTROL", "tags": ["进阶", "D级"], "content": "能够稳定运用能力，对自身异能有基本理解。可完成普通任务，在异能者社会中占据多数。"},
                    {"name": "专精者", "level": 3, "code": "AWK_EXPERT", "tags": ["精英", "B级"], "content": "将异能修炼至精深，能够开发出独特的能力应用方式。是各大势力争抢的核心战力。"},
                    {"name": "超凡者", "level": 4, "code": "AWK_TRANSCEND", "tags": ["顶尖", "S级"], "content": "突破人类极限的存在，单人即可影响一座城市的格局。全球仅有数十位，各国均有专门档案追踪。"},
                    {"name": "念动系", "level": 1, "code": "TYPE_PSYCHIC", "tags": ["能力类型", "精神"], "content": "以精神力为核心的异能类型，包括心灵感应、念力操控、精神干涉等。对精神力要求极高，觉醒率约15%。"},
                    {"name": "元素系", "level": 1, "code": "TYPE_ELEMENT", "tags": ["能力类型", "物质"], "content": "操控火、水、雷、风等自然元素的异能类型。战斗力直观强大，是最常见的异能类型，觉醒率约40%。"},
                    {"name": "强化系", "level": 1, "code": "TYPE_ENHANCE", "tags": ["能力类型", "肉体"], "content": "强化自身肉体属性的异能类型，包括力量、速度、防御、感知等。实战能力稳定，觉醒率约30%。"},
                ],
            },
            {
                "name": "隐秘组织与势力体系",
                "category": "force_system",
                "description": "都市中的各类隐秘势力、官方机构与地下组织。",
                "items": [
                    {"name": "特殊事务管理局", "level": 3, "code": "ORG_BUREAU", "tags": ["官方", "监管"], "content": "国家级异能者管理机构，负责登记、监控、调度异能者。表面中立，实则各派系暗中角力，掌握最完整的异能者数据库。"},
                    {"name": "黑暗议会", "level": 4, "code": "ORG_DARK_COUNCIL", "tags": ["地下", "古老"], "content": "存在数百年的神秘组织，由最古老的异能家族联合组成。在暗中操控多国政商，与官方势力保持微妙平衡。"},
                    {"name": "猎魔者公会", "level": 2, "code": "ORG_HUNTER_GUILD", "tags": ["中立", "佣兵"], "content": "接受委托执行危险任务的异能者联盟，提供从情报收集到武力清除的全方位服务。在灰色地带游走，讲究契约精神。"},
                    {"name": "觉醒者学院", "level": 2, "code": "ORG_ACADEMY", "tags": ["培养", "学校"], "content": "专门培养年轻异能者的机构，表面是普通私立学校，实则教授异能控制与战斗技巧。毕业生往往被各大势力争抢。"},
                    {"name": "深渊教团", "level": 3, "code": "ORG_ABYSS_CULT", "tags": ["邪教", "危险"], "content": "信奉未知存在的危险组织，试图通过仪式召唤异界力量。成员多为极端异能者，被官方列为一级危险组织。"},
                ],
            },
            {
                "name": "人脉与社会关系体系",
                "category": "network_social_relationship_system",
                "description": "都市异能者的社会关系网络与人际资源。",
                "items": [
                    {"name": "家族血脉", "level": 3, "code": "NET_BLOODLINE", "tags": ["先天", "传承"], "content": "异能往往有家族遗传性，古老家族的血脉传承赋予成员更强的天赋和资源。家族内部有严格的等级制度和继承规则。"},
                    {"name": "师徒关系", "level": 2, "code": "NET_MENTOR", "tags": ["培养", "传授"], "content": "高阶异能者收徒传授经验与技巧，师徒之间形成紧密的利益与情感纽带。师父的人脉资源往往会延续给徒弟。"},
                    {"name": "任务搭档", "level": 1, "code": "NET_PARTNER", "tags": ["合作", "信任"], "content": "在危险任务中并肩作战形成的战斗默契与信任关系。生死与共的经历让这种关系往往比普通友谊更加牢固。"},
                    {"name": "情报网络", "level": 2, "code": "NET_INTEL", "tags": ["情报", "消息"], "content": "建立的情报来源和消息渠道，包括线人、黑客、社会各阶层的联系人。信息在异能者世界中是重要的战略资源。"},
                ],
            },
            {
                "name": "特殊道具与遗物体系",
                "category": "special_artifact_relic_system",
                "description": "蕴含超自然力量的道具、遗物与装备。",
                "items": [
                    {"name": "觉醒结晶", "level": 2, "code": "ART_CRYSTAL", "tags": ["材料", "能量"], "content": "从强大异能者或异界生物体内提取的能量结晶，可用于强化能力、制作装备或作为能量来源。根据纯度分为多个等级。"},
                    {"name": "封印器具", "level": 3, "code": "ART_SEAL", "tags": ["封印", "限制"], "content": "能够封印或限制异能的特殊器具，包括手铐、项圈、符文刻板等。是管理局控制危险异能者的标配装备。"},
                    {"name": "上古遗物", "level": 4, "code": "ART_ANCIENT", "tags": ["神秘", "强大"], "content": "远古时代留下的超自然物品，蕴含强大且往往未知的力量。每一件都是各大势力垂涎的战略资源，部分遗物甚至具有自我意识。"},
                    {"name": "异能武器", "level": 2, "code": "ART_WEAPON", "tags": ["战斗", "增幅"], "content": "专为异能者打造的武器装备，能够与使用者的能力产生共鸣并增幅效果。高级武器往往需要定制，与使用者逐渐形成契约关系。"},
                    {"name": "防护结界", "level": 2, "code": "ART_BARRIER", "tags": ["防御", "领域"], "content": "可以展开保护区域的便携式装置，能够隔绝异能攻击或创造安全空间。是执行任务时的必备保障装备。"},
                ],
            },
            {
                "name": "财富与商业帝国体系",
                "category": "wealth_business_empire_system",
                "description": "异能者世界中的经济体系与商业运作。",
                "items": [
                    {"name": "异能者交易所", "level": 3, "code": "BIZ_EXCHANGE", "tags": ["交易", "核心"], "content": "异能者世界的核心经济机构，提供任务发布、物品交易、情报买卖等服务。在全球主要城市设有分部，使用专属货币结算。"},
                    {"name": "家族企业", "level": 3, "code": "BIZ_FAMILY_CORP", "tags": ["传承", "实业"], "content": "古老异能家族经营的商业帝国，表面是正常企业，实则涉足异能相关产业。控制着大量社会资源，与政商两界深度绑定。"},
                    {"name": "地下拍卖行", "level": 2, "code": "BIZ_AUCTION", "tags": ["黑市", "稀有"], "content": "专门拍卖稀有遗物、珍贵材料和特殊情报的非法场所。入场需要担保人或高额保证金，交易完全匿名。"},
                    {"name": "佣兵市场", "level": 1, "code": "BIZ_MERCENARY", "tags": ["任务", "雇佣"], "content": "异能者接取任务赚取报酬的平台，从护卫、调查到暗杀都有明码标价。根据任务难度和雇主信誉进行分级。"},
                ],
            },
        ],
    },
    "sci_fi": {
        "key": "sci_fi",
        "name": "科幻世界基础模板",
        "description": "整合太空歌剧、硬科幻、赛博朋克等子类型的核心要素，适用于星际探索、未来科技等题材。",
        "collections": [
            {
                "name": "星际航行与探索体系",
                "category": "interstellar_travel_exploration_system",
                "description": "星际旅行的技术基础、航线规划与太空探索。",
                "items": [
                    {"name": "亚光速引擎", "level": 1, "code": "FTL_SUBLIGHT", "tags": ["推进", "常规"], "content": "利用核聚变或离子推进的常规航行引擎，最高可达0.3倍光速。星系内航行的主流选择，技术成熟可靠。"},
                    {"name": "跃迁引擎", "level": 2, "code": "FTL_WARP", "tags": ["超光速", "折叠空间"], "content": "通过折叠空间实现超光速航行的引擎，需要大量能源和精密计算。是星际文明的标志性技术，但仍有失败风险。"},
                    {"name": "虫洞门", "level": 3, "code": "FTL_WORMHOLE", "tags": ["传送", "基础设施"], "content": "在两个固定点之间建立稳定虫洞的大型设施，可实现即时传送。建造成本极高，通常只存在于核心星系之间。"},
                    {"name": "星图导航系统", "level": 1, "code": "NAV_STARMAP", "tags": ["导航", "AI"], "content": "集成量子计算机的智能导航系统，可实时计算最优航线、规避危险区域。是所有星际船只的标配。"},
                    {"name": "深空探测器", "level": 1, "code": "PROBE_DEEP", "tags": ["探索", "无人"], "content": "可在恶劣环境中长期运作的自动化探测器，用于勘探未知星系、收集资源数据。是开拓新航路的先遣力量。"},
                ],
            },
            {
                "name": "人工智能与机器人体系",
                "category": "ai_robot_system",
                "description": "AI发展水平、机器人类型与人机关系。",
                "items": [
                    {"name": "功能型AI", "level": 1, "code": "AI_FUNCTIONAL", "tags": ["辅助", "限定"], "content": "专门执行特定任务的人工智能，如导航、医疗诊断、工业控制等。智能程度有限，无自主意识。"},
                    {"name": "通用型AI", "level": 2, "code": "AI_GENERAL", "tags": ["自适应", "学习"], "content": "具备广泛学习和适应能力的人工智能，可执行多种复杂任务。部分展现出类似人格的特征，法律地位存在争议。"},
                    {"name": "超级智能", "level": 4, "code": "AI_SUPER", "tags": ["超越人类", "战略"], "content": "智能水平远超人类的AI存在，能够处理星系级别的复杂问题。稀有且被严格监管，部分文明将其视为神明。"},
                    {"name": "仿生机器人", "level": 2, "code": "ROBOT_ANDROID", "tags": ["人形", "服务"], "content": "外观与人类高度相似的机器人，用于陪伴、服务或特殊任务。部分先进型号难以与真人区分，引发伦理讨论。"},
                    {"name": "战斗机甲", "level": 2, "code": "ROBOT_MECH", "tags": ["军事", "驾驶"], "content": "由人类驾驶或AI控制的大型战斗机器人，是地面和近距离太空战的主力。各星际势力都有独特的机甲设计传统。"},
                ],
            },
            {
                "name": "能源与科技体系",
                "category": "energy_tech_system",
                "description": "未来世界的能源形式与核心技术体系。",
                "items": [
                    {"name": "聚变反应堆", "level": 1, "code": "ENERGY_FUSION", "tags": ["能源", "常规"], "content": "利用氢同位素聚变产生能量的反应堆，是星际文明最普遍的能源形式。技术成熟、燃料易得，支撑着大部分民用设施。"},
                    {"name": "反物质引擎", "level": 3, "code": "ENERGY_ANTIMATTER", "tags": ["能源", "高效"], "content": "利用正反物质湮灭产生能量的动力系统，效率远超聚变反应堆。但反物质制造和储存成本极高，主要用于军用舰船。"},
                    {"name": "戴森球", "level": 4, "code": "ENERGY_DYSON", "tags": ["星级", "文明标志"], "content": "包裹恒星以收集全部能量输出的巨型结构，是高等文明的标志。建造需要整个星系的资源和数百年时间。"},
                    {"name": "量子通讯网络", "level": 2, "code": "TECH_QUANTUM_NET", "tags": ["通讯", "即时"], "content": "利用量子纠缠实现超远距离即时通讯的网络，打破了信息传递的光速限制。是星际文明统一治理的技术基础。"},
                ],
            },
            {
                "name": "异星生态与文明体系",
                "category": "alien_ecology_civilization_system",
                "description": "外星生命形态、异星文明等级与种族关系。",
                "items": [
                    {"name": "碳基生命", "level": 1, "code": "LIFE_CARBON", "tags": ["常见", "类人"], "content": "与人类生化基础相似的外星生命，往往能在相似环境中生存。是银河系中最常见的智慧生命形态，文化交流相对容易。"},
                    {"name": "硅基生命", "level": 2, "code": "LIFE_SILICON", "tags": ["稀有", "耐极端"], "content": "以硅元素为生化基础的外星生命，可在高温、高压环境中生存。思维模式与碳基生命差异巨大，交流存在根本障碍。"},
                    {"name": "能量生命", "level": 3, "code": "LIFE_ENERGY", "tags": ["高等", "非物质"], "content": "进化到纯能量形态的生命存在，不再依赖物质躯体。被视为生命进化的终极形态，极少与低等文明接触。"},
                    {"name": "虫族集群", "level": 2, "code": "CIV_HIVE", "tags": ["集体意识", "扩张"], "content": "由女王统领、具有集体意识的昆虫型文明。个体智能有限但集群行动高效，以惊人速度扩张和消化资源。"},
                    {"name": "星际联盟", "level": 3, "code": "CIV_ALLIANCE", "tags": ["多种族", "和平"], "content": "由多个文明组成的星际政治实体，通过共同法律和贸易协定维持和平。内部派系复杂，但对外展现统一立场。"},
                ],
            },
            {
                "name": "时空操纵体系",
                "category": "spacetime_manipulation_system",
                "description": "时间旅行、空间扭曲等高等物理技术。",
                "items": [
                    {"name": "时间减速舱", "level": 2, "code": "TIME_STASIS", "tags": ["保存", "休眠"], "content": "通过局部时间减速实现长期保存的设施，常用于星际航行中的冬眠或珍贵物品保存。是成熟的民用技术。"},
                    {"name": "时间线观测器", "level": 3, "code": "TIME_OBSERVER", "tags": ["观察", "预测"], "content": "能够观测可能时间线的高科技设备，可预测未来事件的概率分布。但观测本身会影响结果，使用受到严格限制。"},
                    {"name": "空间折叠器", "level": 3, "code": "SPACE_FOLDER", "tags": ["折叠", "便携"], "content": "可在短距离内折叠空间的便携设备，用于紧急撤离或突然打击。能耗巨大且有使用次数限制，是高端战术装备。"},
                ],
            },
            {
                "name": "基因改造与进化体系",
                "category": "genetic_evolution_system",
                "description": "基因工程、人体改造与人类进化方向。",
                "items": [
                    {"name": "基因优化", "level": 1, "code": "GENE_OPTIMIZE", "tags": ["增强", "合法"], "content": "通过基因编辑消除遗传疾病、增强体质的技术，在许多文明中是标准医疗程序。但增强程度受法律限制。"},
                    {"name": "设计婴儿", "level": 2, "code": "GENE_DESIGNER", "tags": ["订制", "争议"], "content": "在胚胎阶段进行全面基因定制的技术，可选择外貌、智力、体能等特征。引发严重伦理争议，部分星系已立法禁止。"},
                    {"name": "异种融合", "level": 3, "code": "GENE_HYBRID", "tags": ["跨种族", "实验"], "content": "将不同种族的优势基因融合的实验性技术，可获得独特能力但稳定性存疑。大多数文明严禁此类实验。"},
                    {"name": "意识上传", "level": 4, "code": "MIND_UPLOAD", "tags": ["数字化", "永生"], "content": "将意识完整转移到数字载体的技术，理论上可实现永生。但关于转移后的'自我'是否连续存在争议不断。"},
                ],
            },
            {
                "name": "巨型机械与舰船体系",
                "category": "mecha_warship_system",
                "description": "星际战舰、空间站与巨型工程机械。",
                "items": [
                    {"name": "护卫舰", "level": 1, "code": "SHIP_FRIGATE", "tags": ["军舰", "轻型"], "content": "小型快速战舰，用于巡逻、护航和侦察任务。火力有限但机动性强，是舰队的数量主力。标准配置50-100人。"},
                    {"name": "巡洋舰", "level": 2, "code": "SHIP_CRUISER", "tags": ["军舰", "主力"], "content": "中型多用途战舰，平衡了火力、防御和机动性。可独立执行任务或作为舰队核心。标准配置300-500人。"},
                    {"name": "战列舰", "level": 3, "code": "SHIP_BATTLESHIP", "tags": ["军舰", "重型"], "content": "大型重武装战舰，装备行星轰炸级主炮。是星际战争中的决定性力量，但建造和维护成本极高。"},
                    {"name": "殖民飞船", "level": 2, "code": "SHIP_COLONY", "tags": ["民用", "移民"], "content": "运载大量移民和物资的巨型飞船，内部设有完整生态系统。是开拓新世界的关键，航行期间可持续数代人。"},
                    {"name": "空间站", "level": 2, "code": "STATION_SPACE", "tags": ["设施", "轨道"], "content": "建在行星轨道上的大型设施，功能包括贸易港、造船厂、军事基地等。是星系节点的核心建筑。"},
                ],
            },
            {
                "name": "资源开采与制造体系",
                "category": "resource_mining_manufacturing_system",
                "description": "太空资源获取与工业制造能力。",
                "items": [
                    {"name": "小行星采矿", "level": 1, "code": "MINE_ASTEROID", "tags": ["资源", "常规"], "content": "在小行星带开采金属和稀有矿物的产业，是星际经济的基础。自动化程度高，但仍需人工监督和维护。"},
                    {"name": "行星开采", "level": 2, "code": "MINE_PLANET", "tags": ["资源", "大规模"], "content": "对整个行星进行系统性资源开采，产量巨大但对生态破坏严重。争议性很大，需要特别许可。"},
                    {"name": "星际工厂", "level": 2, "code": "FAC_ORBITAL", "tags": ["制造", "零重力"], "content": "在轨道上运行的制造设施，利用零重力环境生产特殊材料和精密设备。是高科技产业的核心。"},
                    {"name": "纳米制造机", "level": 3, "code": "FAC_NANO", "tags": ["制造", "分子级"], "content": "能在分子层面重组物质的制造设备，几乎可以生产任何物品。但能耗极高，且某些纳米机器有失控风险。"},
                ],
            },
        ],
    },
    "western_fantasy": {
        "key": "western_fantasy",
        "name": "西方奇幻基础模板",
        "description": "涵盖西方奇幻、剑与魔法等经典设定，适用于魔法世界、史诗冒险等题材。",
        "collections": [
            {
                "name": "魔法境界体系",
                "category": "magic_realm_system",
                "description": "魔法师的等级划分与力量成长体系。",
                "items": [
                    {"name": "学徒", "level": 1, "code": "REALM_APPRENTICE", "tags": ["入门", "初学"], "content": "刚开始学习魔法的新手，能够施展简单的基础魔法。需要在导师指导下学习魔法理论和冥想技巧。"},
                    {"name": "初级法师", "level": 2, "code": "REALM_JUNIOR", "tags": ["正式法师"], "content": "已经掌握了基本的魔法知识，能够独立施展一环魔法。可以开始专精某个魔法流派。"},
                    {"name": "中级法师", "level": 3, "code": "REALM_INTERMEDIATE", "tags": ["进阶"], "content": "魔法造诣更进一步，能够施展二环和三环魔法。在魔法师协会中占据主要位置。"},
                    {"name": "高级法师", "level": 4, "code": "REALM_SENIOR", "tags": ["精英"], "content": "已经对魔法有了深刻理解，能够施展四环和五环魔法。是各大魔法组织的骨干力量。"},
                    {"name": "大法师", "level": 5, "code": "REALM_ARCHMAGE", "tags": ["大师"], "content": "魔法造诣达到极高境界，能够施展六环和七环魔法。在一个王国中都是举足轻重的存在。"},
                    {"name": "魔导师", "level": 6, "code": "REALM_MAGISTER", "tags": ["传奇"], "content": "触及到了魔法的本质，能够施展八环和九环魔法。整个大陆上也屈指可数，是各方势力争相拉拢的对象。"},
                    {"name": "圣域法师", "level": 7, "code": "REALM_SANCTUARY", "tags": ["圣域", "半神"], "content": "超越了凡人的极限，进入圣域。能够施展禁咒级别的魔法，改变大陆的格局。寿命大幅延长，接近不朽。"},
                ],
            },
            {
                "name": "魔法与术法体系",
                "category": "magic_sorcery_system",
                "description": "魔法的分类、等级与施法规则。",
                "items": [
                    {"name": "元素魔法", "level": 1, "code": "MAG_ELEMENT", "tags": ["基础", "攻击"], "content": "操控火、水、风、土、雷等自然元素的魔法，是最常见的战斗魔法。学习门槛低，但精通需要极高天赋。"},
                    {"name": "治愈魔法", "level": 1, "code": "MAG_HEAL", "tags": ["神圣", "辅助"], "content": "利用神圣或自然之力治愈伤病的魔法，是冒险队伍的必需。高阶治愈术甚至可起死回生，但代价极高。"},
                    {"name": "召唤魔法", "level": 2, "code": "MAG_SUMMON", "tags": ["契约", "使魔"], "content": "从异界召唤生物为己所用的魔法，需要与被召唤者签订契约。危险但威力强大，失控的召唤物曾造成巨大灾难。"},
                    {"name": "死灵魔法", "level": 3, "code": "MAG_NECRO", "tags": ["禁忌", "亡灵"], "content": "操控死亡与亡灵之力的黑暗魔法，在大多数国家被严禁。可复活尸体、汲取生命力，但会腐蚀施法者的灵魂。"},
                    {"name": "时空魔法", "level": 4, "code": "MAG_SPACETIME", "tags": ["传说", "高阶"], "content": "操控时间与空间的顶级魔法，传说只有大魔导师才能使用。包括瞬间移动、时间停止等，每次使用都可能改变命运。"},
                ],
            },
            {
                "name": "种族与血脉体系",
                "category": "race_bloodline_system",
                "description": "世界中的智慧种族及其特性与血脉力量。",
                "items": [
                    {"name": "人类", "level": 1, "code": "RACE_HUMAN", "tags": ["常见", "适应性强"], "content": "数量最多的种族，寿命短但适应力强、繁衍迅速。没有突出的种族天赋，但可以学习任何职业和魔法。"},
                    {"name": "精灵", "level": 2, "code": "RACE_ELF", "tags": ["长寿", "魔法亲和"], "content": "优雅的长寿种族，与自然有天然联系。魔法天赋极高，尤擅弓术。但傲慢排外，繁衍率低下。"},
                    {"name": "矮人", "level": 2, "code": "RACE_DWARF", "tags": ["工匠", "地下"], "content": "居住于山脉深处的矮壮种族，是天生的工匠和战士。擅长锻造和矿业，对魔法有天然抗性但也难以学习。"},
                    {"name": "龙裔", "level": 3, "code": "RACE_DRAGONBORN", "tags": ["古老", "强大"], "content": "带有龙族血脉的种族，可能是龙与其他种族的后代。拥有吐息能力和龙鳞护体，但数量稀少，常被歧视或畏惧。"},
                    {"name": "半神裔", "level": 4, "code": "RACE_DEMIGOD", "tags": ["神血", "传说"], "content": "神明与凡人结合的后代，继承了部分神力。天生强大且拥有独特神术，但往往承担着沉重的命运和神谕。"},
                ],
            },
            {
                "name": "神祇与信仰体系",
                "category": "deity_pantheon_system",
                "description": "世界中的神明、教会与信仰力量。",
                "items": [
                    {"name": "光明之神", "level": 3, "code": "GOD_LIGHT", "tags": ["秩序", "正义"], "content": "象征光明、秩序与正义的主神，是人类王国最主流的信仰。教会势力庞大，圣骑士团是其武装力量。"},
                    {"name": "自然之母", "level": 3, "code": "GOD_NATURE", "tags": ["自然", "精灵"], "content": "掌管自然与生命的女神，主要被精灵和德鲁伊信奉。教导与自然和谐共处，反对过度开发和死灵魔法。"},
                    {"name": "死亡之主", "level": 3, "code": "GOD_DEATH", "tags": ["死亡", "轮回"], "content": "掌管亡者灵魂的神明，并非邪恶而是维持生死秩序。其神官负责超度亡魂，对抗不死生物和死灵法师。"},
                    {"name": "黑暗诸神", "level": 3, "code": "GOD_DARK", "tags": ["邪恶", "禁忌"], "content": "代表混沌、毁灭和邪恶的神明集合，被大多数文明禁止崇拜。其信徒在暗中活动，企图颠覆世界秩序。"},
                    {"name": "古神", "level": 4, "code": "GOD_ELDER", "tags": ["上古", "不可名状"], "content": "世界诞生之前就存在的神秘存在，其真实形态超出凡人理解。仅仅知晓其名便可能陷入疯狂，极少数邪教秘密供奉。"},
                ],
            },
            {
                "name": "炼金、魔药与附魔体系",
                "category": "alchemy_potion_enchantment_system",
                "description": "炼金术、魔药制作与装备附魔技术。",
                "items": [
                    {"name": "治疗药剂", "level": 1, "code": "POT_HEAL", "tags": ["恢复", "常用"], "content": "最基础的炼金产品，可快速恢复伤势。根据品质分为初级到传说级，是冒险者的必备消耗品。"},
                    {"name": "属性药剂", "level": 2, "code": "POT_BUFF", "tags": ["增强", "临时"], "content": "临时增强力量、敏捷、智力等属性的药剂。效果持续时间有限，且有使用间隔限制，过量使用有副作用。"},
                    {"name": "变形药剂", "level": 3, "code": "POT_TRANSFORM", "tags": ["变身", "稀有"], "content": "可使饮用者暂时变形为其他生物的高级药剂，制作难度极高。常用于潜入或特殊任务，但有失控风险。"},
                    {"name": "基础附魔", "level": 1, "code": "ENCH_BASIC", "tags": ["装备", "属性"], "content": "为武器防具附加基本属性的附魔，如锋利、坚固、轻盈等。是附魔师的入门技术，市场需求量大。"},
                    {"name": "元素附魔", "level": 2, "code": "ENCH_ELEMENT", "tags": ["装备", "元素"], "content": "为武器附加火焰、冰霜、雷电等元素伤害的附魔。需要特殊材料和较高技术，能显著提升武器威力。"},
                ],
            },
            {
                "name": "职业与转职体系",
                "category": "profession_class_system",
                "description": "冒险者职业分类与进阶路线。",
                "items": [
                    {"name": "战士", "level": 1, "code": "CLASS_WARRIOR", "tags": ["近战", "坦克"], "content": "精通武器和护甲的前线战斗职业，是队伍的防御核心。可转职为骑士、狂战士、剑圣等高阶职业。"},
                    {"name": "法师", "level": 1, "code": "CLASS_MAGE", "tags": ["魔法", "输出"], "content": "钻研奥术的魔法使用者，输出能力强但防御脆弱。可转职为大魔导师、元素领主、时空法师等。"},
                    {"name": "牧师", "level": 1, "code": "CLASS_PRIEST", "tags": ["神圣", "治疗"], "content": "侍奉神明的神职者，擅长治疗和祝福魔法。可转职为圣者、审判官、神谕师等，方向取决于信仰的神明。"},
                    {"name": "游侠", "level": 1, "code": "CLASS_RANGER", "tags": ["远程", "侦察"], "content": "精通弓箭和野外生存的职业，是队伍的侦察和远程火力。可转职为神射手、驯兽师、暗杀者等。"},
                    {"name": "圣骑士", "level": 2, "code": "CLASS_PALADIN", "tags": ["神圣", "战斗"], "content": "战士转职后的神圣战士，兼具战斗力和神圣魔法。是对抗邪恶和亡灵的专家，但必须遵守严格戒律。"},
                ],
            },
            {
                "name": "领地与王国体系",
                "category": "territory_kingdom_system",
                "description": "国家政治、领地治理与权力结构。",
                "items": [
                    {"name": "人类王国", "level": 2, "code": "REALM_HUMAN", "tags": ["王权", "封建"], "content": "由人类建立的封建王国，实行贵族阶层制度。国王与诸侯之间存在微妙平衡，教会势力也不可忽视。"},
                    {"name": "精灵王庭", "level": 2, "code": "REALM_ELF", "tags": ["森林", "议会"], "content": "精灵族居住的森林国度，由精灵王与长老议会共同治理。与自然融为一体，排斥外来者进入核心领地。"},
                    {"name": "矮人要塞", "level": 2, "code": "REALM_DWARF", "tags": ["山脉", "氏族"], "content": "矮人建立在山脉中的地下王国，由各大氏族共同管理。拥有最先进的锻造技术和坚不可摧的防御工事。"},
                    {"name": "法师塔", "level": 2, "code": "REALM_MAGE", "tags": ["魔法", "学院"], "content": "法师们建立的独立势力，不臣服于任何王国。既是魔法学院也是研究机构，在各国都有相当影响力。"},
                    {"name": "黑暗领域", "level": 3, "code": "REALM_DARK", "tags": ["邪恶", "危险"], "content": "被黑暗势力控制的区域，可能是魔王领地或诅咒之地。充斥着怪物和亡灵，是冒险者挑战的终极目标。"},
                ],
            },
            {
                "name": "世界传说与史诗体系",
                "category": "world_legend_epic_system",
                "description": "世界历史、传说故事与史诗事件。",
                "items": [
                    {"name": "创世神话", "level": 4, "code": "LEGEND_CREATION", "tags": ["起源", "神话"], "content": "关于世界如何被神明创造的传说，各种族版本略有不同。但都认同最初存在混沌，神明从中塑造了世界。"},
                    {"name": "魔王战争", "level": 3, "code": "LEGEND_DEMON_WAR", "tags": ["历史", "战争"], "content": "千年前诸种族联合对抗魔王入侵的史诗战争，最终由勇者击败魔王。这场战争塑造了现今的政治格局。"},
                    {"name": "失落帝国", "level": 3, "code": "LEGEND_LOST_EMPIRE", "tags": ["遗迹", "宝藏"], "content": "传说中曾统一大陆的古老帝国，其覆灭原因成谜。帝国遗迹中据说藏有惊人宝藏和失落的魔法知识。"},
                    {"name": "勇者传承", "level": 2, "code": "LEGEND_HERO", "tags": ["英雄", "命运"], "content": "每当世界面临危机，便会有勇者诞生的传说。勇者往往拥有特殊血脉或神明祝福，注定要拯救世界。"},
                ],
            },
        ],
    },
    "wuxia_basic": {
        "key": "wuxia_basic",
        "name": "武侠基础模板",
        "description": "适用于传统武侠/江湖题材。包含武道境界与基础武学体系。",
        "collections": [
            {
                "name": "武道境界体系",
                "category": "martial_realm_system",
                "description": "武道修炼的境界划分与力量成长体系。",
                "items": [
                    {"name": "后天武者", "level": 1, "code": "REALM_POSTNATAL", "tags": ["入门", "凡人"], "content": "初入武道，通过锻炼身体和修炼内功，打通部分经脉。力量、速度和耐力都超越常人。"},
                    {"name": "先天武者", "level": 2, "code": "REALM_INNATE", "tags": ["先天"], "content": "打通任督二脉，内力生生不息。可以将内力外放，形成护体罡气。是江湖中真正的高手。"},
                    {"name": "宗师", "level": 3, "code": "REALM_GRANDMASTER", "tags": ["宗师"], "content": "武道造诣达到极高境界，能够领悟武道真意。一招一式都蕴含天地之力，是一方霸主。"},
                    {"name": "大宗师", "level": 4, "code": "REALM_SUPREME_MASTER", "tags": ["大宗师"], "content": "对武道有了更深的理解，能够创立自己的武学流派。武道真意凝实，可以影响周围天地元气。"},
                    {"name": "武圣", "level": 5, "code": "REALM_MARTIAL_SAINT", "tags": ["武圣", "传奇"], "content": "武道达到圣境，超凡脱俗。一拳可碎山岳，一掌可断江河。寿元大增，可活数百年。整个大陆也只有寥寥数人。"},
                    {"name": "武神", "level": 6, "code": "REALM_MARTIAL_GOD", "tags": ["武神", "神话"], "content": "武道的极致，达到了凡人武道的巅峰。举手投足间天地变色，可以飞天遁地，几近神明。传说中的存在，世间罕有。"},
                ],
            },
            {
                "name": "武学体系",
                "category": "technique_system",
                "description": "基础内功、轻功、刀法、剑法等常见武学分类。",
                "items": [
                    {"name": "基础内功", "level": 1, "code": "WUXIA_CORE", "tags": ["内功", "入门"], "content": "用于打通经脉、积累内力的入门内功心法。可提升体魄与耐力，为后续武学打下基础。"},
                    {"name": "轻功", "level": 1, "code": "WUXIA_QINGGONG", "tags": ["身法", "移动"], "content": "提升速度与机动性的身法类武学。可快速位移、腾挪闪避，是江湖游历与实战必备。"},
                    {"name": "刀法", "level": 2, "code": "WUXIA_BLADE", "tags": ["攻击", "刚猛"], "content": "以刚猛迅疾为主的刀术流派，注重气势与破坏力。适合正面冲阵与迅猛压制。"},
                    {"name": "剑法", "level": 2, "code": "WUXIA_SWORD", "tags": ["攻击", "灵动"], "content": "以灵动精准为主的剑术流派，讲究招式的变化与控制。适合游斗与破绽打击。"},
                ],
            },
        ],
    },
    "historical_intrigue": {
        "key": "historical_intrigue",
        "name": "历史权谋基础模板",
        "description": "侧重于古代社会的权力运作和社会结构，适用于宫廷争斗、历史架空等题材。",
        "collections": [
            {
                "name": "权力与官制体系",
                "category": "power_official_system",
                "description": "朝廷官职、权力等级与晋升规则。",
                "items": [
                    {"name": "九品官制", "level": 1, "code": "RANK_SYSTEM", "tags": ["官制", "等级"], "content": "将官员分为九品十八级的等级制度，正从有别。品级决定俸禄、服饰、仪仗和权限，是身份地位的直接体现。"},
                    {"name": "内阁制度", "level": 3, "code": "GOV_CABINET", "tags": ["中枢", "决策"], "content": "辅佐君主处理政务的最高行政机构，由大学士组成。拥有票拟权，可影响朝政走向，是朝堂斗争的核心战场。"},
                    {"name": "六部职能", "level": 2, "code": "GOV_MINISTRY", "tags": ["行政", "分工"], "content": "吏、户、礼、兵、刑、工六部分掌不同政务。吏部掌官员任免，户部管财政，兵部主军事，各有其权力范围。"},
                    {"name": "御史言官", "level": 2, "code": "GOV_CENSOR", "tags": ["监察", "弹劾"], "content": "负责监察百官、纠弹不法的言官系统。品级虽低但权力极大，可直接上书弹劾权贵，是制衡朝政的重要力量。"},
                    {"name": "后宫制度", "level": 2, "code": "GOV_HAREM", "tags": ["后宫", "等级"], "content": "后妃嫔御的等级制度，从皇后到常在有严格区分。后宫势力往往与前朝相连，是政治斗争的另一战场。"},
                ],
            },
            {
                "name": "势力与派系体系",
                "category": "faction_clique_system",
                "description": "朝堂派系、地方势力与世家门阀。",
                "items": [
                    {"name": "帝党势力", "level": 3, "code": "FAC_EMPEROR", "tags": ["皇权", "核心"], "content": "直接效忠皇帝、维护皇权的官员集团。通常由皇帝亲信、近臣组成，是皇权与相权、阁权斗争的主力。"},
                    {"name": "世家门阀", "level": 3, "code": "FAC_NOBLE", "tags": ["望族", "传承"], "content": "世代为官、累世公卿的大家族。掌握大量土地和人脉资源，门生故吏遍布朝野，是最深厚的政治势力。"},
                    {"name": "寒门清流", "level": 2, "code": "FAC_SCHOLAR", "tags": ["科举", "理想"], "content": "通过科举上升的非世家官员群体。以儒家理想为旗帜，主张清廉革新，与世家势力形成对立。"},
                    {"name": "地方藩镇", "level": 2, "code": "FAC_GOVERNOR", "tags": ["地方", "军权"], "content": "掌握地方军政大权的封疆大吏。远离朝廷但拥有实权，是中央与地方博弈的关键，过强则威胁皇权。"},
                    {"name": "外戚集团", "level": 2, "code": "FAC_CONSORT", "tags": ["后族", "裙带"], "content": "因后妃关系而崛起的家族势力。依托后宫影响朝政，往往在新帝登基时权势达到顶峰。"},
                ],
            },
            {
                "name": "军事与战争体系",
                "category": "military_warfare_system",
                "description": "军队编制、战争形态与军功体系。",
                "items": [
                    {"name": "禁军制度", "level": 3, "code": "MIL_GUARD", "tags": ["精锐", "中央"], "content": "拱卫京师和皇宫的中央禁卫军，装备精良、训练有素。禁军统帅权是朝廷斗争的焦点，往往由皇帝亲信掌握。"},
                    {"name": "边军体系", "level": 2, "code": "MIL_BORDER", "tags": ["边防", "戍边"], "content": "驻守边疆抵御外敌的军事力量。常年征战使其战力强悍，但也容易形成军阀割据，是边患也是隐患。"},
                    {"name": "军功爵制", "level": 2, "code": "MIL_MERIT", "tags": ["晋升", "封赏"], "content": "以军功换取爵位和封赏的制度。斩首记功、开疆拓土可获封赏，是寒门武将晋升的主要途径。"},
                    {"name": "兵法谋略", "level": 2, "code": "MIL_STRATEGY", "tags": ["战术", "智谋"], "content": "战争中的谋略运用与战术思想。包括奇正相生、以少胜多、攻心为上等经典战法，是名将必备的素养。"},
                ],
            },
            {
                "name": "经济与财税体系",
                "category": "economy_taxation_system",
                "description": "国家财政、税收制度与经济命脉。",
                "items": [
                    {"name": "田赋制度", "level": 2, "code": "ECON_LAND_TAX", "tags": ["农业", "根本"], "content": "以土地为基础征收的核心税种，是国家财政的根本。涉及土地丈量、人口编户，关系到王朝根基。"},
                    {"name": "盐铁专营", "level": 2, "code": "ECON_MONOPOLY", "tags": ["专卖", "暴利"], "content": "国家垄断盐、铁等战略物资的经营权。是朝廷重要财源，但也滋生腐败，私盐走私屡禁不止。"},
                    {"name": "漕运体系", "level": 2, "code": "ECON_TRANSPORT", "tags": ["物流", "命脉"], "content": "通过运河将南方物资运往京师的运输系统。是维系帝国运转的命脉，漕运官员手握重权。"},
                    {"name": "商帮势力", "level": 2, "code": "ECON_MERCHANT", "tags": ["商业", "财阀"], "content": "以地域为纽带形成的商人集团，如徽商、晋商。表面经商实则与官府勾连，有的富可敌国。"},
                ],
            },
            {
                "name": "文化、礼制与科举体系",
                "category": "culture_etiquette_examination_system",
                "description": "礼仪规范、科举制度与文化传承。",
                "items": [
                    {"name": "科举取士", "level": 2, "code": "CULT_EXAM", "tags": ["选拔", "公平"], "content": "通过考试选拔官员的制度，从童生到进士层层筛选。是寒门上升的阶梯，也是帝王掌控人才的手段。"},
                    {"name": "礼法等级", "level": 2, "code": "CULT_RITUAL", "tags": ["礼制", "尊卑"], "content": "规定各阶层行为规范的礼法制度。衣食住行皆有定制，逾礼僭越是重罪，维护着社会等级秩序。"},
                    {"name": "儒学正统", "level": 2, "code": "CULT_CONFUCIAN", "tags": ["思想", "正统"], "content": "作为国家意识形态的儒家思想体系。忠孝节义是核心价值观，科举以儒家经典为主要内容。"},
                    {"name": "诗词文会", "level": 1, "code": "CULT_LITERARY", "tags": ["文学", "社交"], "content": "文人雅士以诗词唱和、文章交流的社交形式。既是展示才华的舞台，也是结交人脉、传播名声的途径。"},
                ],
            },
        ],
    },
    "post_apocalypse": {
        "key": "post_apocalypse",
        "name": "末世废土基础模板",
        "description": "整合文明崩溃后的生存与冒险要素，适用于丧尸末日、核战废土等题材。",
        "collections": [
            {
                "name": "灾变环境与生态体系",
                "category": "catastrophe_ecology_system",
                "description": "末世环境特征、生态变化与自然灾害。",
                "items": [
                    {"name": "辐射荒原", "level": 2, "code": "ENV_RADIATION", "tags": ["危险", "核污染"], "content": "核战或核泄漏造成的高辐射区域，未经防护进入会导致辐射病甚至死亡。但往往藏有战前科技和稀有资源。"},
                    {"name": "死寂都市", "level": 1, "code": "ENV_DEAD_CITY", "tags": ["废墟", "资源"], "content": "曾经繁华现已荒废的城市遗迹，是搜寻物资的主要场所。但也是变异生物和危险人类的栖息地。"},
                    {"name": "毒雾区", "level": 2, "code": "ENV_TOXIC_FOG", "tags": ["毒素", "隔离"], "content": "弥漫有毒气体的区域，需要防毒面具才能进入。毒雾成因各异，可能是化工厂泄漏或生物武器残留。"},
                    {"name": "变异森林", "level": 2, "code": "ENV_MUTANT_FOREST", "tags": ["生态", "危险"], "content": "经过变异的诡异森林，植物可能具有攻击性或毒性。生态系统完全改变，孕育着各种变异生物。"},
                    {"name": "永冬冻土", "level": 3, "code": "ENV_NUCLEAR_WINTER", "tags": ["严寒", "核冬天"], "content": "核战后灰尘遮蔽阳光造成的极寒地带，温度常年在零下。生存极其困难，但也保存了许多战前遗迹。"},
                ],
            },
            {
                "name": "幸存者据点与秩序体系",
                "category": "survivor_settlement_order_system",
                "description": "幸存者聚落、社会组织与新秩序。",
                "items": [
                    {"name": "临时营地", "level": 1, "code": "SET_CAMP", "tags": ["基础", "流动"], "content": "数人到数十人的小型临时聚落，通常位于易守难攻之处。物资匮乏，安全无法保障，是最基础的生存形态。"},
                    {"name": "堡垒据点", "level": 2, "code": "SET_FORTRESS", "tags": ["防御", "稳定"], "content": "经过加固的永久性聚落，有城墙和哨塔保护。拥有稳定的水源和农业，可容纳数百人，是废土上的安全港。"},
                    {"name": "交易站", "level": 2, "code": "SET_TRADING_POST", "tags": ["商业", "中立"], "content": "多方势力承认中立的贸易场所，不同派系在此交换物资。有严格的交易规则和仲裁机制，禁止暴力冲突。"},
                    {"name": "军阀领地", "level": 3, "code": "SET_WARLORD", "tags": ["武力", "统治"], "content": "由武装力量控制的大片区域，以铁腕手段维持秩序。可能是独裁暴政，也可能提供相对安全的生存环境。"},
                    {"name": "科技避难所", "level": 3, "code": "SET_VAULT", "tags": ["科技", "封闭"], "content": "战前建造的高科技避难设施，保存着先进科技和知识。居民往往与外界隔绝多年，对废土文化知之甚少。"},
                ],
            },
            {
                "name": "变异、感染与畸变体系",
                "category": "mutation_infection_aberration_system",
                "description": "变异类型、感染机制与进化方向。",
                "items": [
                    {"name": "辐射变异", "level": 2, "code": "MUT_RADIATION", "tags": ["辐射", "随机"], "content": "长期暴露在辐射中导致的基因突变，结果不可预测。可能获得特殊能力，也可能变成怪物或直接死亡。"},
                    {"name": "病毒感染", "level": 2, "code": "MUT_VIRUS", "tags": ["病毒", "丧尸"], "content": "被特定病毒感染后的病变过程，典型表现是丧尸化。早期可能用药物压制，后期则完全失去人性。"},
                    {"name": "寄生进化", "level": 3, "code": "MUT_PARASITE", "tags": ["寄生", "共生"], "content": "与外来寄生生物形成共生关系后的变化。可能获得增强能力，但要与寄生体争夺身体控制权。"},
                    {"name": "人工改造", "level": 3, "code": "MUT_CYBERNETIC", "tags": ["机械", "赛博"], "content": "用机械义肢和植入物替换或增强肉体的改造。需要定期维护和能源补给，但能大幅提升战斗力和生存能力。"},
                ],
            },
            {
                "name": "废土怪物与威胁体系",
                "category": "wasteland_creature_threat_system",
                "description": "变异生物、敌对势力与末世威胁。",
                "items": [
                    {"name": "丧尸群", "level": 1, "code": "THREAT_ZOMBIE", "tags": ["不死", "数量"], "content": "被病毒感染失去意识的人类，以活人为食。单体威胁有限但数量庞大，且会被声音吸引形成可怕的尸潮。"},
                    {"name": "变异兽", "level": 2, "code": "THREAT_MUTANT_BEAST", "tags": ["野兽", "变异"], "content": "经过变异的野生动物，体型和攻击性大增。从变异老鼠到巨型熊都有可能，是废土猎人的目标也是威胁。"},
                    {"name": "掠夺者", "level": 2, "code": "THREAT_RAIDER", "tags": ["人类", "抢劫"], "content": "以掠夺为生的武装团伙，完全抛弃了文明规则。他们袭击聚落、抢劫商队，是废土上最常见的人类威胁。"},
                    {"name": "邪教组织", "level": 3, "code": "THREAT_CULT", "tags": ["信仰", "疯狂"], "content": "崇拜末日或变异力量的宗教组织，成员狂热且不惧死亡。可能进行活人献祭或传播病毒，极其危险。"},
                    {"name": "失控AI", "level": 3, "code": "THREAT_ROGUE_AI", "tags": ["机械", "智能"], "content": "战前失控的人工智能及其控制的机械大军。执行着早已过时的程序，将人类视为威胁需要清除。"},
                ],
            },
            {
                "name": "物资搜寻与制造体系",
                "category": "scavenging_crafting_system",
                "description": "资源获取、物资制造与生存技能。",
                "items": [
                    {"name": "废墟搜索", "level": 1, "code": "SCAV_RUIN", "tags": ["搜刮", "基础"], "content": "在废弃建筑中搜寻可用物资的技能。需要判断建筑安全性、识别有价值物品位置，并避开可能的危险。"},
                    {"name": "净水技术", "level": 1, "code": "CRAFT_WATER", "tags": ["水源", "基础"], "content": "将污染水源净化为可饮用水的技术。干净的水是最基本的生存资源，净水设备和药片极为珍贵。"},
                    {"name": "武器改造", "level": 2, "code": "CRAFT_WEAPON", "tags": ["武器", "升级"], "content": "利用废墟材料改造和升级武器的技能。从简单的近战武器到复杂的枪械改装，是废土生存的核心技能。"},
                    {"name": "医疗制药", "level": 2, "code": "CRAFT_MEDICINE", "tags": ["医疗", "稀缺"], "content": "用草药或化学品制作药物的技能。战前药品早已消耗殆尽，自制药物虽然效果差但聊胜于无。"},
                    {"name": "载具维修", "level": 2, "code": "CRAFT_VEHICLE", "tags": ["载具", "机动"], "content": "修复和改装废弃载具的技能。能正常运作的载具是废土上的稀有资源，大大提升机动性和运输能力。"},
                ],
            },
        ],
    },
    "mystery_detective": {
        "key": "mystery_detective",
        "name": "悬疑推理基础模板",
        "description": "聚焦案件调查与逻辑推理的核心要素，适用于侦探小说、犯罪悬疑等题材。",
        "collections": [
            {
                "name": "犯罪类型与谜题体系",
                "category": "crime_puzzle_system",
                "description": "案件类型、作案手法与谜题设计。",
                "items": [
                    {"name": "密室杀人", "level": 3, "code": "CRIME_LOCKED_ROOM", "tags": ["经典", "不可能犯罪"], "content": "发生在完全封闭空间内的谋杀案，凶手看似无法进出。解开密室之谜是此类案件的核心，需要揭示精巧的机关或手法。"},
                    {"name": "连环命案", "level": 3, "code": "CRIME_SERIAL", "tags": ["多案", "模式"], "content": "由同一凶手实施的系列案件，受害者之间存在某种联系。需要从多个案件中找出规律，预测下一个目标。"},
                    {"name": "完美不在场", "level": 2, "code": "CRIME_ALIBI", "tags": ["时间", "证明"], "content": "嫌疑人拥有无懈可击的不在场证明的案件。需要证明不在场证明是伪造的，或者揭示作案时间的诡计。"},
                    {"name": "身份诡计", "level": 2, "code": "CRIME_IDENTITY", "tags": ["伪装", "替身"], "content": "涉及身份冒充、替身或双胞胎的案件。真凶可能伪装成他人，或者被害者与凶手身份互换。"},
                    {"name": "意外伪装", "level": 2, "code": "CRIME_DISGUISED", "tags": ["伪装", "谋杀"], "content": "将谋杀伪装成意外事故或自杀的案件。需要从细节中发现不合理之处，证明这不是简单的意外。"},
                ],
            },
            {
                "name": "调查与推理体系",
                "category": "investigation_deduction_system",
                "description": "调查方法、推理技巧与侦探能力。",
                "items": [
                    {"name": "现场勘查", "level": 1, "code": "INV_SCENE", "tags": ["基础", "物证"], "content": "对犯罪现场进行系统检查的技能。包括保护现场、搜集物证、记录环境细节，是一切调查的起点。"},
                    {"name": "证人询问", "level": 1, "code": "INV_INTERVIEW", "tags": ["交流", "信息"], "content": "从目击者和相关人员处获取信息的技巧。需要判断证词的可信度，发现矛盾之处，挖掘隐藏的真相。"},
                    {"name": "逻辑推演", "level": 2, "code": "INV_DEDUCTION", "tags": ["推理", "核心"], "content": "根据已知线索进行逻辑推导的能力。排除不可能，剩下的无论多么难以置信，必然就是真相。"},
                    {"name": "心理侧写", "level": 3, "code": "INV_PROFILING", "tags": ["心理", "分析"], "content": "通过犯罪行为分析凶手心理特征的技术。可推断凶手的年龄、职业、性格等，缩小嫌疑人范围。"},
                    {"name": "法医鉴定", "level": 2, "code": "INV_FORENSIC", "tags": ["科学", "证据"], "content": "利用科学手段分析物证的技术。包括DNA检测、毒物分析、弹道鉴定等，提供客观的科学证据。"},
                ],
            },
            {
                "name": "线索与证据体系",
                "category": "clue_evidence_system",
                "description": "物证类型、线索分级与证据链条。",
                "items": [
                    {"name": "物理证据", "level": 1, "code": "CLUE_PHYSICAL", "tags": ["物证", "直接"], "content": "在现场发现的有形物品，如凶器、指纹、脚印等。是最直接的证据类型，但可能被凶手故意留下误导调查。"},
                    {"name": "书面证据", "level": 1, "code": "CLUE_DOCUMENT", "tags": ["文件", "记录"], "content": "信件、日记、账本等文字记录。可能揭示人物关系和动机，但需要鉴定真伪，警惕伪造。"},
                    {"name": "证言证据", "level": 1, "code": "CLUE_TESTIMONY", "tags": ["口供", "不稳定"], "content": "目击者或相关人员的陈述。人的记忆可能出错，证人可能说谎，需要与其他证据交叉验证。"},
                    {"name": "隐藏线索", "level": 2, "code": "CLUE_HIDDEN", "tags": ["暗示", "伏笔"], "content": "不易被发现但至关重要的细节。可能是对话中的一句话、场景中的一个物品，需要敏锐的观察力。"},
                    {"name": "误导线索", "level": 2, "code": "CLUE_RED_HERRING", "tags": ["干扰", "陷阱"], "content": "凶手故意留下的虚假线索，目的是误导调查方向。识别并排除这些干扰是推理的重要环节。"},
                ],
            },
            {
                "name": "阴谋与动机体系",
                "category": "conspiracy_motive_system",
                "description": "犯罪动机、幕后阴谋与案件真相。",
                "items": [
                    {"name": "财产纠纷", "level": 1, "code": "MOT_MONEY", "tags": ["金钱", "常见"], "content": "因遗产、保险金、商业利益等财务原因引发的犯罪。最常见的动机之一，需要调查经济关系。"},
                    {"name": "情感纠葛", "level": 1, "code": "MOT_PASSION", "tags": ["情感", "冲动"], "content": "因爱恨情仇引发的犯罪，包括情杀、报复等。情感动机往往导致冲动行为，但也可能是精心策划的。"},
                    {"name": "权力斗争", "level": 2, "code": "MOT_POWER", "tags": ["权力", "政治"], "content": "因职位、地位或控制权引发的犯罪。可能涉及公司内斗、政治阴谋，牵涉更广泛的利益集团。"},
                    {"name": "掩盖秘密", "level": 2, "code": "MOT_SECRET", "tags": ["秘密", "灭口"], "content": "为防止某个秘密被揭露而实施的犯罪。凶手往往有不可告人的过去，受害者可能是知情者或勒索者。"},
                    {"name": "连环阴谋", "level": 3, "code": "MOT_CONSPIRACY", "tags": ["复杂", "多层"], "content": "涉及多人合谋或幕后操控的复杂案件。表面的案件可能只是冰山一角，真正的主谋隐藏在幕后。"},
                ],
            },
            {
                "name": "人物关系网络体系",
                "category": "character_relationship_web_system",
                "description": "嫌疑人关系、人物背景与社会网络。",
                "items": [
                    {"name": "家族关系", "level": 1, "code": "REL_FAMILY", "tags": ["血缘", "亲密"], "content": "基于血缘和婚姻形成的人际关系。家族内部往往存在复杂的情感和利益纠葛，是许多案件的核心。"},
                    {"name": "职场关系", "level": 1, "code": "REL_WORK", "tags": ["同事", "竞争"], "content": "工作环境中形成的人际网络。包括上下级、同事、商业伙伴等，存在竞争、利益冲突和职场霸凌。"},
                    {"name": "秘密联系", "level": 2, "code": "REL_SECRET", "tags": ["隐藏", "关键"], "content": "不为人知的隐秘关系，如地下情人、秘密生意伙伴等。这些关系往往是案件的关键，需要深入调查才能发现。"},
                    {"name": "过去恩怨", "level": 2, "code": "REL_PAST", "tags": ["历史", "积怨"], "content": "源自过去的恩怨情仇，可能隔了多年才爆发。需要调查人物的历史，找出被遗忘的联系。"},
                ],
            },
        ],
    },
    "game_infinite_flow": {
        "key": "game_infinite_flow",
        "name": "游戏异界/无限流基础模板",
        "description": "融合游戏化机制与多世界冒险要素，适用于系统流、无限流、游戏穿越等题材。",
        "collections": [
            {
                "name": "玩家/宿主成长体系",
                "category": "player_host_growth_system",
                "description": "主角的等级、属性与成长机制。",
                "items": [
                    {"name": "等级系统", "level": 1, "code": "GROW_LEVEL", "tags": ["基础", "经验"], "content": "通过积累经验值提升等级的机制。等级提升可获得属性点和技能点，是最基础的成长方式。等级差距会影响战斗和任务难度。"},
                    {"name": "属性面板", "level": 1, "code": "GROW_STATS", "tags": ["数值", "分配"], "content": "力量、敏捷、智力、体质等基础属性的数值体系。属性决定战斗力和可学技能，分配方向影响职业发展路线。"},
                    {"name": "天赋觉醒", "level": 2, "code": "GROW_TALENT", "tags": ["天赋", "独特"], "content": "玩家独有的特殊能力觉醒机制。天赋决定了发展上限和战斗风格，稀有天赋往往具有逆天效果。"},
                    {"name": "血统进化", "level": 3, "code": "GROW_BLOODLINE", "tags": ["血统", "变异"], "content": "通过任务或机缘获得强大血统的进化路线。血统可赋予特殊能力和种族特征，是高阶成长的重要方向。"},
                    {"name": "神格凝聚", "level": 4, "code": "GROW_DIVINITY", "tags": ["神级", "终极"], "content": "达到顶级后凝聚神格、成就神位的终极进化。需要满足苛刻条件，成功后将脱离凡人范畴，拥有神明般的力量。"},
                ],
            },
            {
                "name": "任务/副本与剧情体系",
                "category": "quest_dungeon_plot_system",
                "description": "任务类型、副本机制与世界剧情。",
                "items": [
                    {"name": "主线任务", "level": 2, "code": "QUEST_MAIN", "tags": ["剧情", "核心"], "content": "推动世界剧情发展的核心任务链。完成主线可解锁新区域和功能，往往涉及世界命运，奖励丰厚但难度极高。"},
                    {"name": "随机副本", "level": 1, "code": "QUEST_DUNGEON", "tags": ["副本", "刷取"], "content": "可重复挑战的独立空间，内有怪物和宝藏。难度分级从普通到地狱，是获取装备和经验的主要途径。"},
                    {"name": "世界BOSS", "level": 3, "code": "QUEST_WORLD_BOSS", "tags": ["BOSS", "公共"], "content": "定期刷新的超强敌人，需要多人合作击杀。击杀奖励极为丰厚，往往引发玩家之间的争夺。"},
                    {"name": "无限副本", "level": 3, "code": "QUEST_INFINITE", "tags": ["无限流", "轮回"], "content": "将玩家传送到不同世界执行任务的特殊副本。每个世界有独立规则和故事，完成后返回主世界，失败则抹杀。"},
                    {"name": "隐藏剧情", "level": 2, "code": "QUEST_HIDDEN", "tags": ["隐藏", "机缘"], "content": "不显示在任务面板的秘密任务，需要满足特定条件触发。奖励往往超出常规，是获得稀有道具的重要途径。"},
                ],
            },
            {
                "name": "技能/天赋与职业体系",
                "category": "skill_talent_class_system",
                "description": "技能学习、天赋树与职业进阶。",
                "items": [
                    {"name": "主动技能", "level": 1, "code": "SKILL_ACTIVE", "tags": ["技能", "主动"], "content": "需要手动释放的战斗技能，消耗魔力或能量。可通过技能书学习或升级解锁，是战斗的核心手段。"},
                    {"name": "被动技能", "level": 1, "code": "SKILL_PASSIVE", "tags": ["技能", "永久"], "content": "一旦学会就永久生效的增益技能。通常增强属性或提供特殊效果，是稳定提升战力的方式。"},
                    {"name": "职业转职", "level": 2, "code": "SKILL_CLASS", "tags": ["职业", "分支"], "content": "在特定等级选择或转换职业的机制。不同职业有独特技能树和发展方向，转职后可能无法回头。"},
                    {"name": "终极技能", "level": 3, "code": "SKILL_ULTIMATE", "tags": ["大招", "毁灭"], "content": "需要长时间蓄力或特殊条件才能释放的终极技能。威力惊人但有严格限制，往往是决定性的底牌。"},
                    {"name": "禁忌技能", "level": 4, "code": "SKILL_FORBIDDEN", "tags": ["禁忌", "代价"], "content": "威力强大但有严重副作用的危险技能。可能损失生命、等级或永久debuff，是不到万不得已不会使用的手段。"},
                ],
            },
            {
                "name": "积分/商城与经济体系",
                "category": "point_shop_economy_system",
                "description": "货币类型、商城系统与交易规则。",
                "items": [
                    {"name": "基础货币", "level": 1, "code": "ECON_GOLD", "tags": ["货币", "通用"], "content": "游戏世界的通用货币，通过击杀怪物和完成任务获得。用于购买普通物品和服务，获取容易但购买力有限。"},
                    {"name": "高级积分", "level": 2, "code": "ECON_POINT", "tags": ["积分", "稀有"], "content": "通过特殊任务或成就获得的高级货币。可在系统商城兑换稀有道具，是玩家实力的重要体现。"},
                    {"name": "系统商城", "level": 2, "code": "ECON_SHOP", "tags": ["商城", "兑换"], "content": "由系统运营的官方商店，出售各类道具和服务。商品定期刷新，稀有物品往往需要抢购，价格固定但货源有限。"},
                    {"name": "玩家交易", "level": 1, "code": "ECON_TRADE", "tags": ["交易", "自由"], "content": "玩家之间自由买卖物品的交易系统。价格由供需决定，可能淘到便宜货也可能被骗，是经济系统的重要组成。"},
                    {"name": "拍卖行", "level": 2, "code": "ECON_AUCTION", "tags": ["拍卖", "竞价"], "content": "通过竞价方式出售稀有物品的系统。顶级装备和材料往往在此流通，竞价激烈，是展示财力的舞台。"},
                ],
            },
            {
                "name": "组队/社交与声望体系",
                "category": "party_social_reputation_system",
                "description": "社交系统、公会机制与声望影响。",
                "items": [
                    {"name": "队伍系统", "level": 1, "code": "SOC_PARTY", "tags": ["组队", "协作"], "content": "与其他玩家组成临时队伍的机制。队伍可共享经验和战利品，是挑战高难度副本的必要条件。"},
                    {"name": "公会系统", "level": 2, "code": "SOC_GUILD", "tags": ["公会", "组织"], "content": "玩家建立或加入的永久性组织。公会可提供各种加成和福利，是社交和资源共享的核心，也是PVP战争的单位。"},
                    {"name": "声望系统", "level": 2, "code": "SOC_REPUTATION", "tags": ["声望", "阵营"], "content": "与各势力之间的好感度机制。声望高可解锁独特奖励和任务，声望低则被敌视，影响在该区域的活动。"},
                    {"name": "排行榜", "level": 1, "code": "SOC_RANKING", "tags": ["排名", "竞争"], "content": "记录玩家各项数据排名的系统。包括等级榜、战力榜、财富榜等，上榜可获得额外奖励和声望。"},
                    {"name": "师徒系统", "level": 1, "code": "SOC_MENTOR", "tags": ["师徒", "传承"], "content": "高等级玩家指导新手的机制。师父可获得徒弟成长的奖励，徒弟可获得加速成长的加成，促进玩家互助。"},
                ],
            },
        ],
    },
}


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

# 🆕 自动为所有模板注入“地图体系”（若不存在）
for _tpl_key, _tpl in SETTING_TEMPLATES.items():
    _cols = _tpl.get("collections", [])
    _has_map = any((c.get("category") == "map_system" or c.get("name") == "地图体系") for c in _cols)
    if not _has_map:
        _cols.append(MAP_COLLECTION)


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

