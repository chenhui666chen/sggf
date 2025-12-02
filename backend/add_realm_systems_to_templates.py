"""
添加魔法境界体系和武道境界体系到现有模板
"""

# 注意：此脚本需要手动添加魔法境界体系和武道境界体系的集合定义

# 魔法境界体系（添加到西幻/奇幻模板中）
magic_realm_collection = {
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
}

# 武道境界体系（添加到武侠/玄幻武道模板中）
martial_realm_collection = {
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
}

print("魔法境界体系集合定义：")
print(magic_realm_collection)
print("\n武道境界体系集合定义：")
print(martial_realm_collection)
print("\n请将这些集合添加到对应的模板中。")
