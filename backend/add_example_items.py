"""
为每个体系集合添加一个示例设定项

每个体系的最终层级需要有至少一个通用实例作为示例
"""
import sqlite3
import os
import json

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "novel_app.db")

# 每个体系类型的默认示例
CATEGORY_EXAMPLES = {
    # 修仙/玄幻体系
    "cultivation_realm_system": {
        "name": "炼气期",
        "content": "修仙最初境界，需打通全身经脉，引气入体，凝聚真气。此阶段修士寿元可达150年。"
    },
    "technique_system": {
        "name": "《九天玄功》",
        "content": "玄级顶尖心法，可吸收天地灵气，温养丹田，为修炼各类功法的基础。"
    },
    "pill_system": {
        "name": "筑基丹",
        "content": "炼气期突破筑基期的必备丹药，需九转炼制，服用后可凝聚道基。"
    },
    "formation_system": {
        "name": "护山大阵",
        "content": "宗门守护阵法，融合防御与警示功能，可抵御化神期以下攻击。"
    },
    "talisman_system": {
        "name": "火球符",
        "content": "最常见的攻击符箓，激活后释放拳头大小火球，威力相当于筑基初期一击。"
    },
    "weapon_system": {
        "name": "赤霄剑",
        "content": "灵器级飞剑，剑身通红如血，锋利无比，可随主人神识操控。"
    },
    "resource_system": {
        "name": "千年灵芝",
        "content": "稀有灵药，吸收千年天地精华，可直接提升修为，炼丹的珍贵材料。"
    },
    "force_system": {
        "name": "天剑宗",
        "content": "顶级宗门，以剑道闻名天下，门下弟子过万，拥有元婴期长老三位。"
    },
    "map_system": {
        "name": "天元城",
        "content": "修仙界第一大城，位于大陆中央，各宗门势力汇聚于此，商贸繁荣。"
    },
    
    # 都市异能体系
    "ability_realm_system": {
        "name": "觉醒者(F级)",
        "content": "刚觉醒异能的能力者，能力不稳定，需要经过训练才能进阶。"
    },
    "ability_awakening_growth_system": {
        "name": "火焰掌控",
        "content": "常见的元素系异能，可操控火焰，威力随等级提升，高阶可凝聚火焰风暴。"
    },
    "hidden_organization_force_system": {
        "name": "异能者管理局",
        "content": "官方机构，负责管理觉醒者，维护社会秩序，总部设在首都。"
    },
    "network_social_relationship_system": {
        "name": "生死之交",
        "content": "经历生死考验的战友关系，互相信任，彼此守护。"
    },
    "special_artifact_relic_system": {
        "name": "增幅手环",
        "content": "稀有级装置，佩戴后可提升异能输出30%，是异能者的标配装备。"
    },
    "wealth_business_empire_system": {
        "name": "天星集团",
        "content": "跨国企业，涉足异能科技、佣兵服务等领域，背后有古老家族支持。"
    },
    
    # 西幻/魔法体系
    "magic_realm_system": {
        "name": "学徒",
        "content": "魔法修炼的起点，需掌握基础魔力控制，通过考核可晋升初级法师。"
    },
    "magic_system": {
        "name": "火球术",
        "content": "一环元素魔法，凝聚火元素形成火球，是法师最常用的攻击魔法。"
    },
    "race_bloodline_system": {
        "name": "精灵",
        "content": "长寿种族，天生亲和自然元素，擅长弓箭和自然魔法，寿命可达千年。"
    },
    "profession_class_system": {
        "name": "圣骑士",
        "content": "战士系高阶职业，兼具战斗和治疗能力，是教会的守护者。"
    },
    "martial_realm_system": {
        "name": "后天武者",
        "content": "武道起步境界，开始锻炼肉身，修炼内力，力量超越常人数倍。"
    },
    
    # 科幻体系
    "interstellar_travel_exploration_system": {
        "name": "曲速引擎",
        "content": "超光速航行技术，通过扭曲时空实现恒星际旅行，是星际文明的基础。"
    },
    "ai_robot_system": {
        "name": "通用型机器人",
        "content": "民用级AI机器人，具备基础智能，可执行简单任务，广泛应用于各行业。"
    },
    
    # 末世废土体系
    "survivor_settlement_order_system": {
        "name": "安全区",
        "content": "末世中的人类聚居地，有防御设施和基础秩序，由幸存者自发组织管理。"
    },
    "mutation_infection_aberration_system": {
        "name": "丧尸病毒",
        "content": "导致末世的元凶，感染者失去理智变成丧尸，病毒持续变异产生更强变异体。"
    },
    
    # 游戏系统体系
    "skill_talent_system": {
        "name": "力量天赋",
        "content": "基础物理系天赋，提升力量属性成长，是战士类职业的首选。"
    },
    
    # 角色体系
    "character_system": {
        "name": "主角模板",
        "content": "标准主角设定模板，包含基础属性、背景故事、成长路线等核心要素。"
    },
    
    # 权力政治体系（新增10个）
    "power_official_system": {
        "name": "丞相",
        "content": "一品大员，百官之首，总理朝政，辅佐天子治理天下，位高权重。"
    },
    "faction_clique_system": {
        "name": "帝党",
        "content": "以皇帝为核心的政治派系，主张加强皇权，与世家门阀对立。"
    },
    "military_warfare_system": {
        "name": "禁军",
        "content": "皇城守卫精锐，直属皇帝调遣，编制一万，装备精良，战力顶尖。"
    },
    "economy_taxation_system": {
        "name": "田赋",
        "content": "按田亩征收的农业税，是国家财政主要来源，税率因地区而异。"
    },
    "culture_etiquette_examination_system": {
        "name": "科举制度",
        "content": "选拔官员的考试制度，分乡试、会试、殿试三级，是寒门入仕的主要途径。"
    },
    "legal_criminal_system": {
        "name": "刑部",
        "content": "主管全国司法刑狱的中央机构，负责审理重案、复核死刑。"
    },
    "communication_intelligence_system": {
        "name": "驿站",
        "content": "官方通讯网络节点，负责传递公文、接待官员，遍布全国要道。"
    },
    "historical_event_legend_system": {
        "name": "开国传说",
        "content": "王朝建立的传奇故事，包含开国皇帝的丰功伟绩，是王朝正统性的来源。"
    },
    "lifestyle_custom_system": {
        "name": "春节习俗",
        "content": "最重要的传统节日，包含祭祖、守岁、拜年等习俗，举国欢庆。"
    },
    "special_secret_realm_system": {
        "name": "上古遗迹",
        "content": "远古文明遗留的神秘空间，藏有珍贵宝物和失传秘术，危险与机遇并存。"
    },
}


def add_example_items():
    """为每个空的体系集合添加示例设定项"""
    
    if not os.path.exists(DB_PATH):
        print(f"数据库文件不存在: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        print("=" * 60)
        print("  为体系集合添加示例设定项")
        print("=" * 60)
        
        # 获取所有设定集合
        cursor.execute("""
            SELECT id, name, category, hierarchy_config
            FROM setting_collections
        """)
        collections = cursor.fetchall()
        
        total_added = 0
        
        for col_id, col_name, category, hierarchy_config in collections:
            # 检查该集合是否已有设定项
            cursor.execute("""
                SELECT COUNT(*) FROM setting_items WHERE collection_id = ?
            """, (col_id,))
            item_count = cursor.fetchone()[0]
            
            if item_count > 0:
                continue  # 已有数据，跳过
            
            # 检查是否有示例配置
            example = CATEGORY_EXAMPLES.get(category)
            if not example:
                print(f"跳过 {col_name}: 无示例配置")
                continue
            
            # 解析层级配置获取深度
            if hierarchy_config:
                try:
                    config = json.loads(hierarchy_config)
                    target_depth = config.get('max_depth', 2)
                except:
                    target_depth = 2
            else:
                target_depth = 2
            
            # 创建示例设定项
            cursor.execute("""
                INSERT INTO setting_items (
                    collection_id, name, code, level, tags, content, relations,
                    depth, node_type, is_leaf, path, summary, `order`,
                    created_at, updated_at
                ) VALUES (?, ?, '', NULL, NULL, ?, NULL, ?, 'detail', 1, ?, '', 0, 
                    datetime('now'), datetime('now'))
            """, (
                col_id,
                example['name'],
                example['content'],
                target_depth,
                f"/{col_name}/{example['name']}"
            ))
            
            print(f"✅ {col_name}: 添加 \"{example['name']}\"")
            total_added += 1
        
        conn.commit()
        
        print("\n" + "=" * 60)
        print(f"完成！共添加 {total_added} 个示例设定项")
        print("=" * 60)
        
    except Exception as e:
        print(f"失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    add_example_items()
