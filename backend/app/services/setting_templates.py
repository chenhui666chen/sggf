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
            {
                "depth": 1,
                "name": "地图体系",
                "type": "system",
                "description": "世界空间结构与地理要素的统一规范"
            },
            {
                "depth": 2,
                "name": "地域分类",
                "type": "category",
                "description": "按地理特征和功能划分的区域类型",
                "examples": [
                    "大陆版图",      # 世界整体地理格局
                    "区域地形",      # 山脉/平原/森林/沙漠等
                    "城镇聚落",      # 城市/城镇/村庄
                    "宗门势力驻地",  # 修仙门派/帮会总部
                    "秘境禁地",      # 危险区域/探险目的地
                    "交通要道",      # 官道/运河/传送阵网络
                    "资源产地",      # 矿脉/灵田/药园
                ]
            },
            {
                "depth": 3,
                "name": "区域列表",
                "type": "list",
                "description": "该分类下的具体区域或地点集合",
                "examples": [
                    "某国",       # 大陆版图下的国家
                    "某山脉",       # 区域地形下的山脉
                    "某城市",         # 城镇聚落下的城市
                    "某宗门山门",     # 宗门驻地下的具体地点
                    "某秘境",         # 秘境禁地下的区域
                    "某官道",       # 交通要道下的路线
                    "某矿脉",       # 资源产地下的矿区
                ]
            },
            {
                "depth": 4,
                "name": "地点详情",
                "type": "detail",
                "leaf": True,
                "description": "具体地点的详细设定",
                "examples": [
                    "皇城·紫禁天宫",           # 城市中的核心建筑
                    "天剑峰·剑冢",              # 宗门中的重要地点
                    "迷雾森林·精灵古树",        # 区域中的地标
                    "万妖窟·妖王殿",            # 秘境中的核心区
                    "极北冰原·冰封神殿",        # 禁地中的遗迹
                    "东海龙宫·藏经阁",          # 势力中的功能建筑
                ]
            },
        ],
    },
    
    # ==================== 修仙/玄幻体系 ====================
    "cultivation_realm_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "修仙境界体系",
                "type": "system",
                "description": "修真世界的力量等级划分，从凡人到仙人的完整修行阶梯。",
            },
            {
                "depth": 2,
                "name": "境界大类",
                "type": "category",
                "description": "按修行阶段划分的大境界分类。",
                "examples": ["凡人境界", "修士境界", "大能境界", "仙人境界"],
            },
            {
                "depth": 3,
                "name": "具体境界",
                "type": "list",
                "description": "每个大类下的具体境界等级。",
                "examples": ["炼气期", "筑基期", "金丹期", "元婴期", "化神期", "炼虚期", "合体期", "大乘期", "渡劫期"],
            },
            {
                "depth": 4,
                "name": "境界细分",
                "type": "detail",
                "leaf": True,
                "description": "每个境界的小阶段划分与详细描述。",
                "examples": ["炼气一层", "炼气中期", "炼气大圆满", "筑基初期", "金丹后期"],
            },
        ],
    },
    "technique_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "功法体系",
                "type": "system",
                "description": "修真世界的修炼功法与武学技艺总纲。",
            },
            {
                "depth": 2,
                "name": "功法分类",
                "type": "category",
                "description": "按修炼方式或战斗风格划分的功法大类。",
                "examples": ["心法内功", "剑道功法", "拳掌武学", "身法轻功", "刀法", "枪法", "特殊秘法"],
            },
            {
                "depth": 3,
                "name": "功法品级",
                "type": "list",
                "description": "功法的品质等级划分。",
                "examples": ["凡级", "黄级下品", "黄级上品", "玄级", "地级", "天级", "仙级", "神级"],
            },
            {
                "depth": 4,
                "name": "功法详情",
                "type": "detail",
                "leaf": True,
                "description": "具体功法的名称、修炼方法与威力描述。",
                "examples": ["九天玄功", "太虚剑诀", "降龙十八掌", "凌波微步"],
            },
        ],
    },
    "pill_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "丹药体系",
                "type": "system",
                "description": "修真世界的丹药炼制与药物效用体系。",
            },
            {
                "depth": 2,
                "name": "丹药分类",
                "type": "category",
                "description": "按功效划分的丹药大类。",
                "examples": ["突破类丹药", "恢复类丹药", "增强类丹药", "解毒类丹药", "特殊类丹药"],
            },
            {
                "depth": 3,
                "name": "丹药品级",
                "type": "list",
                "description": "丹药的品质等级，通常与可服用的境界相关。",
                "examples": ["一品", "二品", "三品", "四品", "五品", "六品", "七品", "八品", "九品", "仙丹"],
            },
            {
                "depth": 4,
                "name": "丹药详情",
                "type": "detail",
                "leaf": True,
                "description": "具体丹药的名称、配方、功效与副作用。",
                "examples": ["筑基丹", "金丹破境丹", "九转还魂丹", "洗髓丹", "聚灵丹"],
            },
        ],
    },
    "formation_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "阵法体系",
                "type": "system",
                "description": "修真世界的阵法布置与运作体系。",
            },
            {
                "depth": 2,
                "name": "阵法分类",
                "type": "category",
                "description": "按功能划分的阵法大类。",
                "examples": ["攻击阵法", "防御阵法", "困敌阵法", "幻境阵法", "传送阵法", "聚灵阵法", "杀阵"],
            },
            {
                "depth": 3,
                "name": "阵法等级",
                "type": "list",
                "description": "阵法的威力等级划分。",
                "examples": ["一阶", "二阶", "三阶", "四阶", "五阶", "六阶", "仙阵", "神阵"],
            },
            {
                "depth": 4,
                "name": "阵法详情",
                "type": "detail",
                "leaf": True,
                "description": "具体阵法的名称、布置方法、阵眼与威力。",
                "examples": ["护山大阵", "九天玄火阵", "诛仙剑阵", "传送阵", "聚灵阵"],
            },
        ],
    },
    "talisman_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "符箓体系",
                "type": "system",
                "description": "修真世界的符箓制作与使用体系。",
            },
            {
                "depth": 2,
                "name": "符箓分类",
                "type": "category",
                "description": "按功能划分的符箓大类。",
                "examples": ["攻击符", "防御符", "遁逃符", "辅助符", "禁制符", "通讯符", "探查符"],
            },
            {
                "depth": 3,
                "name": "符箓品阶",
                "type": "list",
                "description": "符箓的品质与威力等级。",
                "examples": ["下品", "中品", "上品", "极品", "仙符"],
            },
            {
                "depth": 4,
                "name": "符箓详情",
                "type": "detail",
                "leaf": True,
                "description": "具体符箓的名称、绘制方法与使用效果。",
                "examples": ["火球符", "金刚符", "遁地符", "传讯符", "禁魔符"],
            },
        ],
    },
    "weapon_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "武器法宝体系",
                "type": "system",
                "description": "修真世界的武器装备与法宝器物体系。",
            },
            {
                "depth": 2,
                "name": "装备分类",
                "type": "category",
                "description": "按用途划分的装备大类。",
                "examples": ["武器类", "护甲类", "饰品类", "辅助器物", "特殊法宝"],
            },
            {
                "depth": 3,
                "name": "装备品质",
                "type": "list",
                "description": "装备的品质等级划分。",
                "examples": ["凡品", "宝器", "灵器", "法器", "仙器", "神器", "混沌至宝"],
            },
            {
                "depth": 4,
                "name": "装备详情",
                "type": "detail",
                "leaf": True,
                "description": "具体装备的名称、材质、能力与来历。",
                "examples": ["轩辕剑", "昆仑镜", "东皇钟", "盘古斧", "混沌珠"],
            },
        ],
    },
    "resource_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "资源体系",
                "type": "system",
                "description": "世界中的各类资源材料体系。",
            },
            {
                "depth": 2,
                "name": "资源分类",
                "type": "category",
                "description": "按来源或用途划分的资源大类。",
                "examples": ["灵草灵药", "矿石材料", "妖兽材料", "能量结晶", "天材地宝", "货币资源"],
            },
            {
                "depth": 3,
                "name": "资源等级",
                "type": "list",
                "description": "资源的稀有度与品质等级。",
                "examples": ["普通", "稀有", "珍稀", "史诗", "传说", "神级"],
            },
            {
                "depth": 4,
                "name": "资源详情",
                "type": "detail",
                "leaf": True,
                "description": "具体资源的名称、产地、获取方式与用途。",
                "examples": ["万年灵芝", "天外陨铁", "龙血晶", "凤凰神羽", "混沌精金"],
            },
        ],
    },
    # 通用组织势力体系（合并自: force_system, hidden_organization_force_system, faction_clique_system）
    "organization_force_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "组织势力体系",
                "type": "system",
                "description": "世界中的组织、门派、势力与派系体系。",
            },
            {
                "depth": 2,
                "name": "组织分类",
                "type": "category",
                "description": "按性质划分的组织类型。",
                "examples": ["宗门门派", "世家家族", "王朝政权", "商会组织", "隐秘势力", "江湖帮派"],
            },
            {
                "depth": 3,
                "name": "势力等级",
                "type": "list",
                "description": "组织势力的规模与影响力等级。",
                "examples": ["地方小势力", "区域中等势力", "一方霸主", "顶级大势力", "超然势力"],
            },
            {
                "depth": 4,
                "name": "势力详情",
                "type": "detail",
                "leaf": True,
                "description": "具体组织的名称、历史、架构、核心人物与势力范围。",
                "examples": ["某宗门", "某世家", "某王朝", "某商会", "某组织"],
            },
        ],
    },
    
    # ==================== 都市异能体系 ====================
    # 通用异能体系（合并自: ability_realm_system, ability_awakening_growth_system）
    "ability_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "异能体系",
                "type": "system",
                "description": "超自然能力的分类与等级划分体系。",
            },
            {
                "depth": 2,
                "name": "能力分类",
                "type": "category",
                "description": "按能力性质划分的异能大类。",
                "examples": ["元素系", "精神系", "肉体强化系", "时空系", "特殊系", "辅助系"],
            },
            {
                "depth": 3,
                "name": "能力等级",
                "type": "list",
                "description": "异能者的力量等级划分。",
                "examples": ["F级", "E级", "D级", "C级", "B级", "A级", "S级", "SS级", "SSS级"],
            },
            {
                "depth": 4,
                "name": "能力详情",
                "type": "detail",
                "leaf": True,
                "description": "具体异能的名称、效果、觉醒条件与成长路径。",
                "examples": ["火焰操控", "心灵感应", "超级力量", "时间暂停", "空间切割"],
            },
        ],
    },
    "network_social_relationship_system": {
        "max_depth": 3,
        "levels": [
            {
                "depth": 1,
                "name": "人脉关系体系",
                "type": "system",
                "description": "角色的社会关系网络与人际资源体系。",
            },
            {
                "depth": 2,
                "name": "关系分类",
                "type": "category",
                "description": "按关系性质划分的人脉类型。",
                "examples": ["血缘亲属", "师门传承", "战斗同伴", "商业伙伴", "情报网络", "仇敌对手"],
            },
            {
                "depth": 3,
                "name": "关系详情",
                "type": "detail",
                "leaf": True,
                "description": "具体关系的描述、亲密度与互动方式。",
                "examples": ["生死之交", "利益同盟", "世仇", "暗恋对象", "情报线人"],
            },
        ],
    },
    "special_artifact_relic_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "道具遗物体系",
                "type": "system",
                "description": "蕴含超自然力量的道具、遗物与装备体系。",
            },
            {
                "depth": 2,
                "name": "道具分类",
                "type": "category",
                "description": "按用途划分的道具大类。",
                "examples": ["能量结晶", "封印器具", "上古遗物", "异能武器", "防护装备", "辅助道具"],
            },
            {
                "depth": 3,
                "name": "道具等级",
                "type": "list",
                "description": "道具的稀有度与威力等级。",
                "examples": ["普通", "稀有", "精良", "史诗", "传说", "神话"],
            },
            {
                "depth": 4,
                "name": "道具详情",
                "type": "detail",
                "leaf": True,
                "description": "具体道具的名称、来历、能力与使用方法。",
                "examples": ["觉醒石", "封魔锁链", "远古神杖", "能量光刃", "隐形斗篷"],
            },
        ],
    },
    "wealth_business_empire_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "财富商业体系",
                "type": "system",
                "description": "世界中的经济体系与商业运作。",
            },
            {
                "depth": 2,
                "name": "商业分类",
                "type": "category",
                "description": "按行业划分的商业类型。",
                "examples": ["交易所", "家族企业", "地下市场", "佣兵组织", "科技集团", "拍卖行"],
            },
            {
                "depth": 3,
                "name": "商业规模",
                "type": "list",
                "description": "企业或组织的规模等级。",
                "examples": ["个体户", "小型企业", "中型企业", "大型集团", "跨国财阀", "垄断巨头"],
            },
            {
                "depth": 4,
                "name": "商业详情",
                "type": "detail",
                "leaf": True,
                "description": "具体商业实体的名称、业务范围、核心人物与影响力。",
                "examples": ["天星集团", "暗夜拍卖行", "佣兵公会", "银河科技"],
            },
        ],
    },
    
    # ==================== 西幻/魔法体系 ====================
    "magic_realm_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "魔法境界体系",
                "type": "system",
                "description": "西方奇幻世界的魔法师等级划分体系。",
            },
            {
                "depth": 2,
                "name": "境界大类",
                "type": "category",
                "description": "按修行阶段划分的魔法师大境界。",
                "examples": ["入门阶段", "初级阶段", "中级阶段", "高级阶段", "大师阶段", "传奇阶段", "圣域阶段"],
            },
            {
                "depth": 3,
                "name": "具体阶位",
                "type": "list",
                "description": "每个阶段内的具体魔法师等级。",
                "examples": ["学徒", "初级法师", "中级法师", "高级法师", "大法师", "魔导师", "圣域法师"],
            },
            {
                "depth": 4,
                "name": "阶位详情",
                "type": "detail",
                "leaf": True,
                "description": "具体阶位的能力描述、晋升条件与标志性特征。",
                "examples": ["初级法师·二环", "大法师·七环", "圣域法师·禁咒"],
            },
        ],
    },
    "magic_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "魔法体系",
                "type": "system",
                "description": "西方奇幻世界的魔法分类与施法体系。",
            },
            {
                "depth": 2,
                "name": "魔法派系",
                "type": "category",
                "description": "按元素或效果划分的魔法流派。",
                "examples": ["火系魔法", "水系魔法", "风系魔法", "土系魔法", "雷系魔法", "光明魔法", "黑暗魔法", "空间魔法", "时间魔法", "召唤魔法", "治愈魔法", "死灵魔法"],
            },
            {
                "depth": 3,
                "name": "魔法环级",
                "type": "list",
                "description": "魔法的威力等级划分（环级制）。",
                "examples": ["零环戏法", "一环魔法", "二环魔法", "三环魔法", "四环魔法", "五环魔法", "六环魔法", "七环魔法", "八环魔法", "九环魔法", "禁咒"],
            },
            {
                "depth": 4,
                "name": "魔法详情",
                "type": "detail",
                "leaf": True,
                "description": "具体魔法的名称、咒语、效果与施法要求。",
                "examples": ["火球术", "冰锥术", "闪电链", "治愈术", "传送门", "时间停止", "流星火雨"],
            },
        ],
    },
    "race_bloodline_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "种族血脉体系",
                "type": "system",
                "description": "奇幻世界的种族分类与血脉传承体系。",
            },
            {
                "depth": 2,
                "name": "种族大类",
                "type": "category",
                "description": "按起源划分的种族类型。",
                "examples": ["人类种族", "精灵族系", "矮人族系", "兽人种族", "龙族血裔", "魔族", "神族", "元素生命"],
            },
            {
                "depth": 3,
                "name": "血脉纯度",
                "type": "list",
                "description": "血脉的纯净程度与传承等级。",
                "examples": ["普通血脉", "贵族血脉", "王族血脉", "远古血脉", "神圣血脉", "始祖血脉"],
            },
            {
                "depth": 4,
                "name": "种族详情",
                "type": "detail",
                "leaf": True,
                "description": "具体种族或血脉的特征、能力与文化。",
                "examples": ["高等精灵", "黑暗精灵", "山地矮人", "龙裔人类", "半神血统"],
            },
        ],
    },
    "profession_class_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "职业体系",
                "type": "system",
                "description": "奇幻世界的职业分类与晋升体系。",
            },
            {
                "depth": 2,
                "name": "职业系列",
                "type": "category",
                "description": "按战斗风格划分的职业大类。",
                "examples": ["战士系", "法师系", "牧师系", "盗贼系", "游侠系", "召唤系", "工匠系"],
            },
            {
                "depth": 3,
                "name": "职业阶位",
                "type": "list",
                "description": "职业的成长阶段划分。",
                "examples": ["学徒", "初阶", "中阶", "高阶", "专家", "大师", "宗师", "传奇"],
            },
            {
                "depth": 4,
                "name": "职业详情",
                "type": "detail",
                "leaf": True,
                "description": "具体职业的名称、技能树与转职路径。",
                "examples": ["圣骑士", "元素法师", "暗影刺客", "德鲁伊", "死灵法师", "符文铸造师"],
            },
        ],
    },
    "martial_realm_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "武道境界体系",
                "type": "system",
                "description": "武侠世界的武学修为等级划分。",
            },
            {
                "depth": 2,
                "name": "境界大类",
                "type": "category",
                "description": "按修为深浅划分的武道阶段。",
                "examples": ["凡俗境界", "后天境界", "先天境界", "宗师境界", "武圣境界", "武神境界"],
            },
            {
                "depth": 3,
                "name": "境界细分",
                "type": "list",
                "description": "每个大境界内的小阶段。",
                "examples": ["后天初期", "后天中期", "后天大成", "先天初期", "先天中期", "先天大成", "半步宗师"],
            },
            {
                "depth": 4,
                "name": "境界详情",
                "type": "detail",
                "leaf": True,
                "description": "具体境界的能力表现、突破条件与标志性特征。",
                "examples": ["后天九重", "先天大圆满", "一代宗师", "绝代武圣"],
            },
        ],
    },
    
    # ==================== 科幻体系 ====================
    "interstellar_travel_exploration_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "星际航行体系",
                "type": "system",
                "description": "科幻世界的星际旅行与宇宙探索技术体系。",
            },
            {
                "depth": 2,
                "name": "技术分类",
                "type": "category",
                "description": "按功能划分的星际技术大类。",
                "examples": ["推进引擎", "导航系统", "探测设备", "舰船武器", "防护系统", "通讯系统", "生命维持"],
            },
            {
                "depth": 3,
                "name": "技术等级",
                "type": "list",
                "description": "按文明发展程度划分的技术等级。",
                "examples": ["I级文明技术", "II级文明技术", "III级文明技术", "IV级文明技术", "V级神级技术"],
            },
            {
                "depth": 4,
                "name": "技术详情",
                "type": "detail",
                "leaf": True,
                "description": "具体技术的名称、原理、参数与使用场景。",
                "examples": ["曲速引擎", "跃迁门", "量子通讯器", "护盾发生器", "离子炮"],
            },
        ],
    },
    "ai_robot_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "AI机器人体系",
                "type": "system",
                "description": "科幻世界的人工智能与机器人分类体系。",
            },
            {
                "depth": 2,
                "name": "类型分类",
                "type": "category",
                "description": "按用途划分的AI与机器人大类。",
                "examples": ["智能AI", "仿生机器人", "战斗机甲", "工业机器人", "服务机器人", "纳米机器人"],
            },
            {
                "depth": 3,
                "name": "智能等级",
                "type": "list",
                "description": "AI的智能程度与自主性等级。",
                "examples": ["弱AI", "强AI", "通用AI", "超级AI", "自我意识AI", "神级AI"],
            },
            {
                "depth": 4,
                "name": "类型详情",
                "type": "detail",
                "leaf": True,
                "description": "具体AI或机器人的名称、能力、限制与特点。",
                "examples": ["舰载AI·普罗米修斯", "战斗机甲·泰坦", "仿生人·伊芙", "纳米蜂群"],
            },
        ],
    },

    # ==================== 末世废土体系 ====================
    "survivor_settlement_order_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "聚落秩序体系",
                "type": "system",
                "description": "末世废土中的幸存者聚落与社会秩序体系。",
            },
            {
                "depth": 2,
                "name": "聚落分类",
                "type": "category",
                "description": "按性质划分的聚落类型。",
                "examples": ["临时营地", "定居据点", "贸易枢纽", "军事堡垒", "科技避难所", "游牧部落"],
            },
            {
                "depth": 3,
                "name": "聚落规模",
                "type": "list",
                "description": "聚落的人口规模与势力等级。",
                "examples": ["小队级", "据点级", "基地级", "城镇级", "城市级", "区域联盟级"],
            },
            {
                "depth": 4,
                "name": "聚落详情",
                "type": "detail",
                "leaf": True,
                "description": "具体聚落的名称、位置、人口、资源与社会结构。",
                "examples": ["曙光营地", "废土商会", "钢铁兄弟会", "伊甸园避难所", "荒野猎人部落"],
            },
        ],
    },
    "mutation_infection_aberration_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "变异感染体系",
                "type": "system",
                "description": "末世废土中的变异生物与感染机制体系。",
            },
            {
                "depth": 2,
                "name": "变异分类",
                "type": "category",
                "description": "按变异来源划分的类型。",
                "examples": ["辐射变异", "病毒感染", "生化改造", "基因突变", "寄生异化", "超自然畸变"],
            },
            {
                "depth": 3,
                "name": "威胁等级",
                "type": "list",
                "description": "变异生物的危险程度等级。",
                "examples": ["I级威胁", "II级威胁", "III级威胁", "IV级威胁", "V级威胁", "灾厄级", "终焉级"],
            },
            {
                "depth": 4,
                "name": "变异详情",
                "type": "detail",
                "leaf": True,
                "description": "具体变异生物的名称、特征、能力与弱点。",
                "examples": ["行尸", "变异狼", "巨型蜘蛛", "辐射巨兽", "寄生母体", "异形领主"],
            },
        ],
    },

    # ==================== 游戏系统体系 ====================
    "skill_talent_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "技能天赋体系",
                "type": "system",
                "description": "游戏化世界的技能与天赋系统。",
            },
            {
                "depth": 2,
                "name": "技能分类",
                "type": "category",
                "description": "按使用方式划分的技能大类。",
                "examples": ["主动技能", "被动技能", "职业技能", "通用技能", "终极技能", "隐藏技能"],
            },
            {
                "depth": 3,
                "name": "技能等级",
                "type": "list",
                "description": "技能的熟练度与强度等级。",
                "examples": ["Lv1-10入门", "Lv11-30熟练", "Lv31-50精通", "Lv51-70大师", "Lv71-90宗师", "Lv91-100极限"],
            },
            {
                "depth": 4,
                "name": "技能详情",
                "type": "detail",
                "leaf": True,
                "description": "具体技能的名称、效果、消耗与升级路径。",
                "examples": ["火球术", "闪避精通", "狂暴", "凤凰涅槃", "时间停止"],
            },
        ],
    },

    # ==================== 角色体系 ====================
    "character_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "角色体系",
                "type": "system",
                "description": "故事中的人物角色分类与管理体系。",
            },
            {
                "depth": 2,
                "name": "角色分类",
                "type": "category",
                "description": "按故事功能划分的角色类型。",
                "examples": ["主角", "核心配角", "反派", "中立势力", "群众演员", "历史人物"],
            },
            {
                "depth": 3,
                "name": "角色重要性",
                "type": "list",
                "description": "角色在故事中的重要程度。",
                "examples": ["核心角色", "重要角色", "次要角色", "背景角色", "一次性角色"],
            },
            {
                "depth": 4,
                "name": "角色详情",
                "type": "detail",
                "leaf": True,
                "description": "具体角色的姓名、身份、性格、能力与人物弧光。",
                "examples": ["主角·林风", "师尊·玄天真人", "反派·魔君", "红颜·雪儿"],
            },
        ],
    },

    # ==================== 候选集合（特殊体系）====================
    "candidate": {
        "max_depth": 2,
        "levels": [
            {
                "depth": 1,
                "name": "候选集合",
                "type": "system",
                "description": "临时存储的候选设定项集合。",
            },
            {
                "depth": 2,
                "name": "候选项详情",
                "type": "detail",
                "leaf": True,
                "description": "待确定的候选设定内容。",
            },
        ],
    },
    
    # ==================== 权力政治体系（历史权谋）====================
    "power_official_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "权力与官制体系",
                "type": "system",
                "description": "历史背景中的官僚制度与权力结构。",
            },
            {
                "depth": 2,
                "name": "官制分类",
                "type": "category",
                "description": "按职能划分的官僚系统。",
                "examples": ["中央朝官", "地方官员", "军职武官", "爵位封号", "特殊机构"],
            },
            {
                "depth": 3,
                "name": "官阶品级",
                "type": "list",
                "description": "官员的品级与俸禄等级。",
                "examples": ["正一品", "从一品", "正二品", "从二品", "正三品", "从九品", "未入流"],
            },
            {
                "depth": 4,
                "name": "官职详情",
                "type": "detail",
                "leaf": True,
                "description": "具体官职的名称、职责、权限与任职条件。",
                "examples": ["丞相", "太尉", "御史大夫", "刺史", "县令", "锦衣卫指挥使"],
            },
        ],
    },
    "military_warfare_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "军事与战争体系",
                "type": "system",
                "description": "军队编制、兵种、战术与战争相关设定。",
            },
            {
                "depth": 2,
                "name": "军事分类",
                "type": "category",
                "description": "按类型划分的军事内容。",
                "examples": ["军队编制", "兵种类型", "战略战术", "武器装备", "防御工事", "后勤补给"],
            },
            {
                "depth": 3,
                "name": "规模等级",
                "type": "list",
                "description": "军事单位的规模划分。",
                "examples": ["伍", "什", "队", "营", "卫", "军", "集团军"],
            },
            {
                "depth": 4,
                "name": "军事详情",
                "type": "detail",
                "leaf": True,
                "description": "具体军事元素的名称、编制、装备与战绩。",
                "examples": ["虎贲军", "羽林卫", "重骑兵", "神机营", "雁门关", "连弩"],
            },
        ],
    },
    "economy_taxation_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "经济与财税体系",
                "type": "system",
                "description": "经济制度、货币流通与税收体系。",
            },
            {
                "depth": 2,
                "name": "经济分类",
                "type": "category",
                "description": "按领域划分的经济内容。",
                "examples": ["税收制度", "货币体系", "商业贸易", "农业生产", "手工业", "专卖制度"],
            },
            {
                "depth": 3,
                "name": "经济规模",
                "type": "list",
                "description": "经济活动的规模等级。",
                "examples": ["家庭作坊", "小型商铺", "中型商号", "大型商会", "官营产业", "国家专营"],
            },
            {
                "depth": 4,
                "name": "经济详情",
                "type": "detail",
                "leaf": True,
                "description": "具体经济元素的名称、运作方式与影响。",
                "examples": ["田赋两税", "盐铁专卖", "丝绸之路", "钱庄票号", "坊市制度"],
            },
        ],
    },
    "culture_etiquette_examination_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "文化礼制体系",
                "type": "system",
                "description": "科举制度、礼仪规范与文化传统。",
            },
            {
                "depth": 2,
                "name": "文化分类",
                "type": "category",
                "description": "按领域划分的文化内容。",
                "examples": ["科举考试", "礼仪制度", "学术流派", "文学艺术", "宗教信仰", "教育制度"],
            },
            {
                "depth": 3,
                "name": "等级层次",
                "type": "list",
                "description": "科举或学位的等级。",
                "examples": ["童生", "秀才", "举人", "贡士", "进士", "探花", "榜眼", "状元"],
            },
            {
                "depth": 4,
                "name": "文化详情",
                "type": "detail",
                "leaf": True,
                "description": "具体文化元素的内容与社会影响。",
                "examples": ["殿试", "五服礼制", "儒学", "诗词歌赋", "道教", "书院"],
            },
        ],
    },
    "legal_criminal_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "律法刑罚体系",
                "type": "system",
                "description": "法律制度、刑罚体系与司法程序。",
            },
            {
                "depth": 2,
                "name": "法律分类",
                "type": "category",
                "description": "按性质划分的法律类型。",
                "examples": ["刑律", "民律", "军法", "宗族族规", "江湖规矩", "行会律令"],
            },
            {
                "depth": 3,
                "name": "罪行等级",
                "type": "list",
                "description": "罪行的严重程度。",
                "examples": ["轻罪", "中罪", "重罪", "大罪", "死罪", "十恶不赦"],
            },
            {
                "depth": 4,
                "name": "律法详情",
                "type": "detail",
                "leaf": True,
                "description": "具体法律条文、刑罚方式与执行程序。",
                "examples": ["笞刑", "杖刑", "流放", "斩首", "凌迟", "株连九族"],
            },
        ],
    },
    "communication_intelligence_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "通讯情报体系",
                "type": "system",
                "description": "信息传递、情报收集与密探组织。",
            },
            {
                "depth": 2,
                "name": "情报分类",
                "type": "category",
                "description": "按渠道划分的情报类型。",
                "examples": ["官方驿站", "密探组织", "飞鸽传书", "烽火狼烟", "暗语密码", "江湖消息"],
            },
            {
                "depth": 3,
                "name": "保密等级",
                "type": "list",
                "description": "情报的机密程度。",
                "examples": ["公开消息", "内部情报", "机密", "绝密", "最高机密"],
            },
            {
                "depth": 4,
                "name": "情报详情",
                "type": "detail",
                "leaf": True,
                "description": "具体情报系统的运作方式与关键节点。",
                "examples": ["六百里加急", "锦衣卫", "东厂", "飞鸽传书", "暗语本"],
            },
        ],
    },
    "historical_event_legend_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "历史与传说体系",
                "type": "system",
                "description": "重大历史事件与民间传说故事。",
            },
            {
                "depth": 2,
                "name": "事件分类",
                "type": "category",
                "description": "按性质划分的事件类型。",
                "examples": ["战争战役", "政变变革", "天灾人祸", "神话传说", "英雄事迹", "王朝更替"],
            },
            {
                "depth": 3,
                "name": "影响等级",
                "type": "list",
                "description": "事件的历史影响程度。",
                "examples": ["地方影响", "区域震动", "国家大事", "时代转折", "改变历史进程"],
            },
            {
                "depth": 4,
                "name": "事件详情",
                "type": "detail",
                "leaf": True,
                "description": "具体事件的时间、经过、影响与相关人物。",
                "examples": ["长平之战", "靖康之变", "黄巾起义", "封神榜", "武穆抗金"],
            },
        ],
    },
    "lifestyle_custom_system": {
        "max_depth": 4,
        "levels": [
            {
                "depth": 1,
                "name": "民生风俗体系",
                "type": "system",
                "description": "日常生活、风俗习惯与社会风貌。",
            },
            {
                "depth": 2,
                "name": "风俗分类",
                "type": "category",
                "description": "按领域划分的民俗内容。",
                "examples": ["节日庆典", "婚丧嫁娶", "饮食文化", "服饰制度", "居住建筑", "娱乐游艺"],
            },
            {
                "depth": 3,
                "name": "阶层分布",
                "type": "list",
                "description": "不同社会阶层的风俗差异。",
                "examples": ["平民百姓", "商贾富户", "士族门阀", "官宦世家", "皇室贵族"],
            },
            {
                "depth": 4,
                "name": "风俗详情",
                "type": "detail",
                "leaf": True,
                "description": "具体风俗的内容、由来与社会意义。",
                "examples": ["春节", "清明", "六礼婚俗", "满汉全席", "汉服", "四合院"],
            },
        ],
    },
}


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

