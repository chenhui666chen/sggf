
from typing import Optional, Dict, Any
import logging
import json
import re

from .knowledge_base import NovelKnowledgeBase
from .memory_manager import NovelMemoryManager
from .agents import CreativeDirectorAgent, WorldArchitectAgent, CharacterDesignerAgent, ContentCreatorAgent, QualityReviewerAgent, OutlinePlanParserAgent
from .llm_singleton import create_deepseek_llm
from .intelligent_truncator import smart_truncate_for_context

# 导入模块化提示词
from app.services.prompts.stages.world_building import (
    WorldBuildingPrompts,
    CharacterDesignPrompts,
    get_genre_world_extension,
    get_genre_character_fields
)
from app.services.prompts.stages.structure_design import (
    StructureDesignPrompts,
    get_genre_rhythm_guide
)
from app.services.prompts.stages.content_creation import FirstChapterPrompts

logger = logging.getLogger(__name__)

# 🆕 题材术语映射字典
GENRE_TERMINOLOGY = {
    "修仙": {
        "power_system": "境界体系（炼气→筑基→金丹→元婴→化神→渡劫→大乘→仙人）",
        "resources": "灵石、丹药、功法、法宝、灵脉",
        "conflicts": "宗门争斗、资源掠夺、境界突破、天道压制",
        "social_structure": "上宗、中层宗门、散修、魔道",
        "key_terms": "悟性、灵根、天劫、飞升"
    },
    "玄幻": {
        "power_system": "境界体系（炼气→筑基→金丹→元婴→化神→渡劫→大乘→仙人）",
        "resources": "灵石、丹药、功法、法宝、灵脉",
        "conflicts": "宗门争斗、资源掠夺、境界突破、天道压制",
        "social_structure": "上宗、中层宗门、散修、魔道",
        "key_terms": "悟性、灵根、天劫、飞升"
    },
    "都市": {
        "power_system": "财富体系 / 特殊能力等级 / 社会地位层级",
        "resources": "资金、人脉、技术专利、商业情报、政治资源",
        "conflicts": "商业竞争、权力博弈、阶层跨越、利益冲突",
        "social_structure": "顶级家族/集团、中产阶层、底层民众、地下势力",
        "key_terms": "资本运作、人脉网络、背景势力、潜规则"
    },
    "悬疑": {
        "power_system": "信息掌控 / 推理能力 / 心理博弈",
        "resources": "线索、证据、关键证人、内幕消息、破案时间",
        "conflicts": "真相揭露、利益遮掩、时间压力、道德困境",
        "social_structure": "执法机构、犯罪团伙、目击者、幕后黑手",
        "key_terms": "悬念、反转、伏笔、红鲱鱼（假线索）"
    },
    "言情": {
        "power_system": "情感强度 / 社会地位 / 个人魅力",
        "resources": "情感投入、社交圈层、外貌才华、家庭背景",
        "conflicts": "感情纠葛、家庭阻力、身份差距、第三者介入",
        "social_structure": "豪门世家、普通家庭、职场关系、闺蜜团体",
        "key_terms": "甜宠、虐恋、双向奔赴、破镜重圆"
    },
    "耽美": {
        "power_system": "情感强度 / 社会地位 / 个人魅力",
        "resources": "情感投入、社交圈层、外貌才华、家庭背景",
        "conflicts": "感情纠葛、家庭阻力、身份差距、第三者介入",
        "social_structure": "豪门世家、普通家庭、职场关系、闺蜜团体",
        "key_terms": "甜宠、虐恋、双向奔赴、破镜重圆"
    },
    "科幻": {
        "power_system": "科技等级 / 基因改造 / 机械强化 / 能量掌控",
        "resources": "高级科技、能源晶体、基因药剂、星际领地、AI算力",
        "conflicts": "文明冲突、资源战争、技术垄断、伦理困境",
        "social_structure": "星际联邦、科技公司、殖民地、异星种族",
        "key_terms": "虫洞跳跃、基因优化、星际殖民、AI觉醒"
    },
    "纯文学": {
        "power_system": "精神成长 / 社会认知 / 人生阅历",
        "resources": "人生经验、情感深度、社会洞察、文化积淀",
        "conflicts": "内心挣扎、价值观冲突、时代变迁、人性探索",
        "social_structure": "知识分子、普通民众、时代背景、社会阶层",
        "key_terms": "隐喻、象征、意识流、现实批判"
    }
}

# 🆕 修仙/玄幻题材境界跨度阈值(章节数)
REALM_SPAN_WARNING_THRESHOLD = 500  # 单个境界超过500章触发建议
REALM_SPAN_RECOMMEND_SUBDIVISION = 300  # 推荐细分的理想跨度

# 🆕 题材专属Prompt模块配置
GENRE_PROMPT_MODULES = {
    "修仙": {
        # 世界观专属部分
        "world_extra_sections": """

### 【修仙题材专属要求】

**境界体系详细规划**:
- 必须明确列出完整境界序列(如: 炼气→筑基→金丹→元婴→化神→渡劫→大乘→仙人)
- 每个大境界需说明: ①突破条件 ②能力跃迁 ③寿命增幅 ④天劫/代价
- 标注"最适合主线突破的境界节点"(通常在卷尾或转折处)
- 若用户指定境界体系,必须严格使用用户提供的境界名称,不得自行创造

**修真资源体系**:
- 核心货币: 灵石等级(下品/中品/上品/极品)及兑换比例
- 修炼资源: 丹药(筑基丹/金丹/破婴丹)、功法(黄阶→玄阶→地阶→天阶)、法宝分级
- 资源垄断点: 明确哪些资源被上层宗门垄断,为主角"逆袭破局"提供抓手

**宗门势力格局**:
- 上宗(顶级宗门)、中层宗门、散修联盟、魔道势力的力量对比
- 标注至少1个"即将衰落的老牌宗门"或"新兴势力的薄弱环节",为卷一冲突提供切入点
- 说明宗门资源分配规则(外门→内门→真传→长老的晋升路径)
""",
        
        # 大纲专属节奏要求
        "outline_rhythm_guide": """

### 【修仙题材节奏设计】

**境界突破节奏**:
- 短篇(50-100章): 2-3个大境界突破
- 中篇(100-300章): 3-5个大境界突破,每卷1次
- 长篇(300-800章): 5-8个大境界突破,重大转折时跨2境界
- 超长篇(800+章): 完整修仙体系,每200-300章1个大境界

**修仙爽点类型**:
- 【资源爽】: 意外获得天材地宝/上古传承/系统奖励
- 【越级爽】: 低境界击败高境界(依靠技巧/法宝/特殊体质)
- 【打脸爽】: 被轻视的废材逆袭,震惊嘲讽者
- 【突破爽】: 关键时刻境界突破,瓶颈破碎
- 【收服爽】: 收服强大妖兽/傀儡/剑灵作为战力

**节奏建议**:
- 每5-8章设置1个小爽点(资源获取/小打脸)
- 每15-25章设置1个中爽点(越级战斗/境界突破)
- 每卷结尾(50-100章)设置1个爆爽点(大境界突破+势力格局改变)
- 避免连续3章无任何进展,可穿插"修炼描写+顿悟时刻"维持节奏
""",
        
        # 人物专属字段
        "character_extra_fields": """

### 【修仙题材人物专属字段】

每个人物除通用字段外,还需补充:

**【灵根资质】**: 五行灵根(金木水火土单灵根为天才/杂灵根为废材)、特殊体质(如剑体/雷体)、变异灵根

**【当前修为】**: 具体境界+小境界(如"筑基中期"/"金丹初期"),需与情节时间线一致

**【主修功法】**: 功法名称、品阶(黄阶/玄阶/地阶/天阶)、特殊效果(如"可越级战斗"/"修炼速度快")

**【法宝/灵器】**: 主要法宝名称、品级、特殊能力(仅核心人物需详细说明)

**【宗门地位】**: 外门弟子/内门弟子/真传弟子/长老/掌门,影响资源获取途径

**示例**:
【灵根资质】: (请根据人物设定设计合理的灵根类型)
【当前修为】: (请根据剧情进展设定境界)
【主修功法】: (请创造独特的功法名称和品阶)
【法宝/灵器】: (请设计符合题材的法宝名称)
【宗门地位】: (请根据世界观设定宗门名称和地位)
""",
        
        # 🆕 增强版章节细纲模板（修仙专属）
        "chapter_detail_template": """第{chapter_num}章：《{chapter_title}》

【核心目标】本章在故事中的作用

【境界变化】章节开始境界 → 章节结束境界，修为提升原因

【情节分镜】（3-5个场景）
1. 开场(10%)：场景描述
2. 发展(30%)：场景描述
3. 小高潮(25%)：场景描述
4. 延伸(20%)：场景描述
5. 收尾(15%)：场景描述

【关键对话】（1-2段核心对话大意）

【情绪曲线】压抑→爆发→小爽→期待→悬疑

【伏笔设计】埋设/回收的伏笔

【爽点设计】
类型：越级战/打脸/获宝/突破
强度：⭐~⭐⭐⭐⭐（小爽/中爽/大爽/爆爽）
实现方式与铺垫手法

【结尾钩子】类型+具体内容

【涉及人物与发展】主要人物及本章变化
""",
        
        # 🆕 章节规划题材专属指导（修仙）
        "chapter_plan_guide": """
## 🔮 修仙题材规划要点

**境界与战力系统**：
- 明确主角当前境界及本章是否有突破机会
- 越级战斗需合理（法宝/秘术/奇遇支撑）
- 标注修为进度：距离下一境界还有多远

**爽点类型侧重**：
- 优先考虑：获得传承/越级斩敌/打脸嘲讽者/境界突破
- 每5章必有1个小爽点（小打脸/获得资源）
- 每25章必有1个大爽点（大境界突破/宗门震动）

**修仙特色元素**：
- 灵石消耗与获取要平衡
- 法宝/丹药使用要节制，留有成长空间
- 人物对话可融入修真术语
"""
    },
    
    "玄幻": {
        "world_extra_sections": """

### 【玄幻题材专属要求】

**力量体系详细规划**:
- 明确力量等级序列(如: 武徒→武者→武师→大武师→武灵→武王→武皇→武帝→武圣)
- 每个等级需说明: ①突破条件 ②核心能力 ③寿命/力量倍数 ④进阶难度
- 可包含多种力量体系并存(武道+魔法+血脉+灵魂力),说明相互关系

**特殊血脉与体质**:
- 列出3-5种核心血脉(如神兽血脉/上古血脉/帝族血脉)
- 说明血脉觉醒条件、能力加成、稀有度排序
- 标注"可通过后天手段获取/提升血脉"的机制,为主角成长预留空间

**异世界地理与位面**:
- 明确世界结构: 下位面→中位面→上位面,或大陆分区(东域/西荒/南疆/北境/中州)
- 标注主角成长路径: 从哪个区域起步→何时跨域→最终去往何处
- 说明位面/区域间的压制规则(如"低位面武帝=高位面武灵")
""",
        
        "outline_rhythm_guide": """

### 【玄幻题材节奏设计】

**力量提升节奏**:
- 短篇: 3-5个等级跨越
- 中篇: 5-8个等级跨越,含1次血脉觉醒
- 长篇: 完整体系晋升,含2-3次质变(血脉觉醒/神器认主/传承融合)
- 超长篇: 跨位面成长,从下位面凡人到上位面强者

**玄幻爽点类型**:
- 【血脉爽】: 废材血脉觉醒,震惊全场
- 【越级爽】: 低等级击败高等级(依靠功法/武技/神器)
- 【打脸爽】: 退婚/轻视后的强势回归
- 【收服爽】: 收服魔兽/追随者/建立势力
- 【传承爽】: 获得上古强者传承/神器认主

**节奏建议**:
- 每3-5章设置1个小爽点(小突破/小打脸)
- 每10-20章设置1个中爽点(等级跨越/血脉觉醒)
- 每卷设置1个爆爽点(质变提升+跨域/跨位面)
""",
        
        "character_extra_fields": """

### 【玄幻题材人物专属字段】

**【血脉等级】**: 凡人血脉/兽族血脉/神兽血脉/帝族血脉/上古血脉,觉醒度百分比

**【当前等级】**: 具体等级+星级(如"三星武者"/"九星大武师"),需与剧情一致

**【核心武技/魔法】**: 招式名称、品阶(黄阶→玄阶→地阶→天阶→神阶)、威力描述

**【神器/魔兵】**: 武器名称、品级、特殊能力、器灵(如有)

**【所属位面/区域】**: 出生地、当前所在位面、目标位面

**示例**:
【血脉等级】: (请创造独特的血脉设定)
【当前等级】: (请根据剧情进展设定等级)
【核心武技】: (请创造独特的武技名称)
【神器】: (请设计独特的神器名称)
【所属位面】: (请根据世界观设计位面名称)
""",
        
        # 🆕 增强版章节细纲模板（玄幻专属）
        "chapter_detail_template": """第{chapter_num}章：《{chapter_title}》

【核心目标】本章在故事中的作用

【力量/血脉变化】等级变化+血脉觉醒度，变化原因

【情节分镜】（3-5个场景）
1. 开场(10%)：场景描述
2. 发展(30%)：场景描述
3. 小高潮(25%)：场景描述
4. 延伸(20%)：场景描述
5. 收尾(15%)：场景描述

【关键对话】（1-2段核心对话大意）

【情绪曲线】压抑→爆发→小爽→期待→悬疑

【伏笔设计】埋设/回收的伏笔

【爽点设计】
类型：血脉觉醒/越级战/神器认主/传承
强度：⭐~⭐⭐⭐⭐
实现方式与铺垫手法

【结尾钩子】类型+具体内容

【涉及人物与发展】主要人物及本章变化
""",
        
        # 🆕 章节规划题材专属指导（玄幻）
        "chapter_plan_guide": """
## ⚔️ 玄幻题材规划要点

**力量与血脉系统**：
- 明确主角当前等级及血脉觉醒度
- 越级挑战需合理（武技/血脉/神器支撑）
- 标注进化进度：距离下一等级/血脉觉醒还有多远

**爽点类型侧重**：
- 优先考虑：血脉觉醒/神器认主/越级战/传承获得
- 每3-5章必有1个小爽点（小打脸/小突破）
- 每20章必有1个大爽点（血脉觉醒/跨域/跨位面）

**玄幻特色元素**：
- 血脉压制与解放是重要爽点
- 神器成长线要设计
- 可融入多力量体系并存
"""
    },
    
    "都市": {
        "world_extra_sections": """

### 【都市题材专属要求】

**经济运作机制**:
- 明确财富等级: 普通人(月入5千)→中产(月入5万)→富人(资产千万)→顶级(资产百亿+)
- 说明主角财富积累路径: 第一桶金来源→产业布局→资本运作→商业帝国
- 标注核心产业领域: 科技/金融/地产/娱乐/新能源等,及行业壁垒

**权力规则体系**:
- 商界: 顶级家族/上市集团/新兴独角兽/中小企业的层级关系
- 政界(如涉及): 明确边界,仅作背景烘托,避免敏感内容
- 地下势力(如涉及): 帮派/灰色产业的生存规则,需符合法律底线

**人脉与资源网络**:
- 说明"人脉即资源"的运作机制: 商会/校友会/俱乐部的准入门槛
- 标注主角可突破的"人脉薄弱点": 新兴行业的平等机会/特殊技能的稀缺性
- 列出关键资源: 技术专利/政策红利/信息差/关键人才
""",
        
        "outline_rhythm_guide": """

### 【都市题材节奏设计】

**财富积累节奏**:
- 短篇: 从负债/底层到小富(百万级)
- 中篇: 从小富到中产顶端(千万-亿级),建立初步产业
- 长篇: 从亿级到顶级富豪(百亿+),商业帝国成型
- 超长篇: 跨国商业版图,影响国家经济走向

**都市爽点类型**:
- 【财富爽】: 一夜暴富/投资暴涨/商业奇迹
- 【打脸爽】: 被轻视后的强势逆袭(同学会/商业谈判)
- 【智斗爽】: 商战布局/谈判博弈/信息战
- 【征服爽】: 收购对手公司/挖走核心团队/颠覆行业
- 【情感爽】: 追求女神成功/拒绝拜金女/真爱相守

**节奏建议**:
- 每3-5章设置1个商业进展(签约/融资/产品发布)
- 每8-15章设置1个中爽点(打脸/商战胜利)
- 每卷设置1个爆爽点(财富阶级跨越+社会地位质变)
- 穿插情感线、日常生活,避免全程商战疲劳
""",
        
        "character_extra_fields": """

### 【都市题材人物专属字段】

**【财富等级】**: 当前资产规模(负债/月光/小康/中产/富豪/顶级),动态变化

**【社会地位】**: 底层打工人/中层白领/企业高管/创业者/行业大佬/顶级圈层

**【核心资源】**: 掌握的关键资源(技术/人脉/资金/信息/政策资源)

**【所属势力/公司】**: 就职公司或自有企业,股份占比,行业地位

**【特殊能力】**(如有): 商业天赋/谈判能力/技术专长/异能(都市异能流)

**示例**:
【财富等级】: (请根据剧情设定合理的财富变化)
【社会地位】: (请设计符合题材的职业发展路径)
【核心资源】: (请根据世界观设计关键资源)
【所属势力】: (请创造独特的公司/组织名称)
【特殊能力】: (请根据题材设计特殊能力,如有)
""",
        
        # 🆕 增强版章节细纲模板（都市专属）
        "chapter_detail_template": """第{chapter_num}章：《{chapter_title}》

【核心目标】本章在故事中的作用（商业布局/打脸对手/情感推进）

【财富/地位变化】资产规模+社会地位变化，变化原因

【情节分镜】（3-5个场景）
1. 开场：场景描述
2. 发展：场景描述
3. 小高潮：场景描述
4. 延伸：场景描述
5. 收尾：场景描述

【关键对话/谈判】商业对话+情感对话

【情绪曲线】被轻视→展示实力→打脸成功→谨慎应对→新挑战

【商战/人脉布局】本章关键布局与后续铺垫

【爽点设计】
类型：商战胜利/打脸/财富暴涨/情感收获
强度：⭐~⭐⭐⭐⭐
实现方式

【结尾钩子】具体内容

【涉及人物与发展】主要人物及本章变化
""",
        
        # 🆕 章节规划题材专属指导（都市）
        "chapter_plan_guide": """
## 🏢 都市题材规划要点

**财富与地位系统**：
- 明确主角当前资产规模及社会地位
- 商业布局要合理（一步一步积累）
- 标注财富进度：距离下一阶层还有多远

**爽点类型侧重**：
- 优先考虑：商战胜利/打脸轻视者/财富爆发/情感收获
- 每3-5章必有1个商业进展（签约/融资）
- 每卷必有1个财富阶级跨越

**都市特色元素**：
- 人脉经营与资源整合
- 商业谈判的智斗细节
- 情感线穿插，避免纯商战疲劳
"""
    },
    
    "悬疑": {
        "world_extra_sections": """

### 【悬疑题材专属要求】

**信息掌控体系**:
- 明确信息层级: 公开信息→内幕消息→核心秘密→终极真相
- 说明信息获取途径: 调查取证/线人情报/黑客技术/权限查阅
- 标注"信息壁垒": 谁掌握关键信息,谁在刻意隐瞒,为何隐瞒

**调查规则与限制**:
- 法律框架: 执法权限/证据链要求/程序正义
- 时间压力: 案件追诉期/连环案倒计时/人质生命倒计时
- 资源限制: 警力/经费/技术手段的现实约束

**真相层级结构**:
- 表面真相(第一层,10-20%剧情揭露)
- 隐藏真相(第二层,40-60%剧情揭露)
- 核心真相(第三层,80-90%剧情揭露)
- 终极秘密(终章揭露,可留白引发思考)
""",
        
        "outline_rhythm_guide": """

### 【悬疑题材节奏设计】

**线索布局节奏**:
- 短篇: 单一案件,3-5条主线索,1-2个反转
- 中篇: 连环案件,5-8条线索交织,3-5个反转
- 长篇: 多案件关联,隐藏真相层层剥离,6-10个反转

**悬疑爽点类型**:
- 【推理爽】: 逻辑推理破解谜题,真相呼之欲出
- 【反转爽】: 意外反转,之前线索重新解读
- 【揭秘爽】: 关键证据出现,案情大白
- 【心理爽】: 与嫌疑人心理博弈,诱导认罪
- 【复仇爽】: 正义伸张,恶人伏法

**节奏建议**:
- 每2-3章推进一条线索/发现一个证据
- 每5-8章设置一个小反转(嫌疑人反转/动机反转)
- 每15-25章设置一个大反转(真凶反转/真相层级跃迁)
- 每卷结尾揭露一层真相,同时埋下新疑问
- 避免冗长调查过程,控制单条线索推进在2-3章内
""",
        
        "character_extra_fields": """

### 【悬疑题材人物专属字段】

**【角色类型】**: 侦探/警察/嫌疑人/证人/受害者/幕后黑手

**【嫌疑等级】**(针对嫌疑人): 高度嫌疑/一般嫌疑/已排除,动态变化

**【掌握信息】**: 该角色知道哪些关键信息,是否对外隐瞒

**【真实动机】**: 表面动机 vs 真实动机(可能在后期反转)

**【关键线索】**: 该角色身上的关键证据/线索/矛盾点

**示例**:
【角色类型】: 刑警队长(主角)
【掌握信息】: 知晓案发时间线、三名嫌疑人行踪、凶器来源,但不知真实动机
【推理能力】: 逻辑推理能力强,擅长心理侧写,但易受情感干扰

【角色类型】: 首要嫌疑人(实为替罪羊)
【嫌疑等级】: 高度嫌疑(前期)→已排除(中期揭露真相后)
【掌握信息】: 知道真凶身份,但因被威胁而隐瞒
【真实动机】: 表面(报复受害者)→真实(保护家人,被迫背锅)
【关键线索】: 不在场证明存在破绽(实为真凶伪造)
""",
        
        # 🆕 增强版章节细纲模板（悬疑专属）
        "chapter_detail_template": """第{chapter_num}章：《{chapter_title}》

【核心目标】本章在真相揭露中的作用（发现证据/排除嫌疑人/反转）

【真相进度】
- 当前层级：表面真相/隐藏真相/核心真相
- 本章揭露内容
- 保留的悬念

【情节分镜】（悬疑节奏）
1. 开场（发现异常）
2. 调查推进
3. 小反转
4. 推理整合
5. 悬念收尾

【线索与证据】
发现的线索、证据有效性、逻辑链推进

【嫌疑人状态变化】嫌疑度动态变化

【情绪曲线】困惑→突破口→新疑问→紧张→更大谜团

【反转设计】
类型：证据反转/嫌疑人反转/动机反转
强度：小反转/中反转/大反转
实现方式

【结尾钩子】具体内容

【涉及人物】侦探、嫌疑人、证人等
""",
        
        # 🆕 章节规划题材专属指导（悬疑）
        "chapter_plan_guide": """
## 🔍 悬疑题材规划要点

**线索与证据系统**：
- 明确本章推进哪条线索/发现哪个证据
- 推理逻辑要严密，避免柿子奇迹
- 标注真相进度：当前揭露到哪一层

**爽点类型侧重**：
- 优先考虑：推理突破/反转揭晓/心理博弈/正义伸张
- 每2-3章推进一条线索
- 每5-8章一个小反转，每15-25章一个大反转

**悬疑特色元素**：
- 红鲱鱼（假线索）要合理埋设
- 嫌疑人嫌疑度动态变化
- 每章结尾留有悬念
"""
    },
    
    "言情": {
        "world_extra_sections": """

### 【言情题材专属要求】

**情感发展阶段体系**:
- 明确情感递进路径: 陌生→初识→好感→暧昧→表白→热恋→矛盾→和解→承诺
- 说明每个阶段的标志性事件和情感浓度
- 标注"情感转折点": 从友情转爱情、从误会到理解的关键时刻

**情感障碍设定**:
- 外部障碍: 家族反对/身份差距/事业冲突/第三者介入/时空阻隔
- 内部障碍: 性格缺陷/过往创伤/自卑/恐惧承诺/价值观差异
- 标注"核心虐点": 最打动读者的情感冲突点(如生离死别/误会割裂)

**社会背景与圈层**:
- 明确主角所处社会环境: 校园/职场/豪门/娱乐圈/古代宫廷
- 说明圈层规则: 门当户对观念/社交礼仪/权力游戏
- 标注"阶层跨越路径": 灰姑娘如何进入上流社会并被接纳
""",
        
        "outline_rhythm_guide": """

### 【言情题材节奏设计】

**情感递进节奏**:
- 短篇(5-10万字): 快节奏甜宠,初识→热恋→小矛盾→HE,虐点少
- 中篇(10-50万字): 先虐后甜,误会/障碍占40%,甜蜜占60%
- 长篇(50-200万字): 情感线+事业线并行,含2-3次重大情感危机

**言情爽点类型**:
- 【甜宠爽】: 霸总宠溺/细节关怀/公开秀恩爱
- 【打脸爽】: 被前任/情敌轻视后的逆袭,男主护短
- 【吃醋爽】: 男主吃醋/争风吃醋场面
- 【表白爽】: 深情告白/求婚场景/身份揭秘
- 【虐后甜】: 经历误会/分离后的重逢和解

**节奏建议**:
- 甜宠文: 每3-5章1个甜蜜互动,避免全程高糖疲劳,穿插小波澜
- 虐恋文: 虐点分布"小虐→中虐→大虐→极致虐→甜蜜HE",虐恋比3:7或4:6
- 每卷设置1个情感里程碑(表白/订婚/分手/和解)
- 避免无意义拖剧情,误会需在5-15章内解开
""",
        
        "character_extra_fields": """

### 【言情题材人物专属字段】

**【情感状态】**: 单身/暗恋/暧昧/热恋/冷战/分手/已婚,动态变化

**【家庭背景】**: 豪门/中产/普通/贫困,家族势力对情感的影响权重

**【外貌魅力值】**: 绝世美颜/清秀可人/平凡/丑小鸭(可逆袭),需符合人设

**【性格类型】**: 霸道总裁/温柔暖男/高冷禁欲/阳光少年/腹黑毒舌/傲娇别扭

**【情感创伤】**(如有): 过往感情经历对当前的影响,恋爱恐惧症根源

**【对CP的情感进度】**: 无感→好感→心动→深爱→刻骨铭心,需标注转折章节

**示例**:
【情感状态】: 单身(卷一)→暧昧(卷二)→秘密交往(卷三)→公开恋情(卷四)
【家庭背景】: 顾氏财团继承人,家族联姻压力大
【外貌魅力值】: 俊美无俦,商界第一黄金单身汉
【性格类型】: 表面高冷禁欲,实则占有欲强、忠犬属性
【情感创伤】: 初恋背叛导致七年不近女色,对女主例外
【对女主情感进度】: 商业联姻对象(初期)→心动(第15章)→深爱(第40章)→非她不娶(第80章)
""",
        
        # 🆕 增强版章节细纲模板（言情专属）
        "chapter_detail_template": """第{chapter_num}章：《{chapter_title}》

【核心目标】本章在情感线中的作用（暗昧升温/误会产生/表白/和解）

【情感进度】
- 章节开始：情感状态
- 章节结束：情感状态
- 推进原因

【情节分镜】（言情节奏）
1. 开场（情感铺垫）
2. 互动升温
3. 甜蜜/虐心高潮
4. 情感延伸
5. 悬念收尾

【关键对话】甜蜜对话+情感冲突对话

【情绪曲线】心动→甜蜜→小虐→期待→悬念

【甜/虐设计】
类型：甜蜜互动/吃醋/表白/误会/虐心
甜虐比：本章甜虐比例
关键场景

【CP互动亮点】关键情感场景

【结尾钩子】具体内容

【涉及人物与情感发展】主要人物及本章变化
""",
        
        # 🆕 章节规划题材专属指导（言情）
        "chapter_plan_guide": """
## 💖 言情题材规划要点

**情感阶段系统**：
- 明确当前情感状态（暗恋/暗昧/热恋/冒战）
- 情感推进要合理（有铺垫、有契机）
- 标注情感进度：距离下一里程碑还有多远

**爽点类型侧重**：
- 优先考虑：甜蜜互动/吃醋/表白/男主护短打脸
- 甜宠文：每3-5章一个甜蜜互动
- 虐恋文：虐后必有甜蜜补偿

**言情特色元素**：
- 设计CP互动名场面
- 误会要合理，5-15章内解开
- 用细节展现心动，避免直白叙述
"""
    },
    
    "耽美": {
        "world_extra_sections": """

### 【耽美题材专属要求】

**情感发展阶段体系**:
- 明确双男主情感递进: 陌生/敌对→了解→暧昧→试探→捅破窗户纸→确认关系→公开/保密
- 说明"攻受定位"(如需要): 强强/一攻一受/互攻/年下/年上等设定
- 标注"情感转折点": 从兄弟情到爱情的质变时刻

**社会接受度设定**:
- 现代背景: 社会对同性恋的接受度(开放/保守/家族压力)
- 古代背景: 男风盛行/禁忌/特殊设定(如ABO/哨向)
- 幻想背景: 完全接受/特殊种族设定

**情感障碍设定**:
- 外部: 家族压力/社会歧视/事业冲突/情敌介入
- 内部: 性向认知/身份差距/权力不平等/过往创伤
""",
        
        "outline_rhythm_guide": """

### 【耽美题材节奏设计】

**情感递进节奏**:
- 短篇: 快节奏甜宠,初识→暧昧→确认关系→小波折→HE
- 中篇: 先虐后甜,身份/立场冲突占30-40%
- 长篇: 情感+事业/权谋线并行,含2-3次重大危机

**耽美爽点类型**:
- 【甜宠爽】: 攻方宠溺/细节关怀/护短
- 【暧昧爽】: 试探/吃醋/肢体接触的暧昧张力
- 【表白爽】: 深情告白/强制爱/霸道示爱
- 【打脸爽】: 受方被轻视后,攻方强势护短
- 【肉体爽】: 激情戏/情趣互动(需符合平台尺度)

**节奏建议**:
- 甜文: 每5-8章1个甜蜜互动,穿插小波澜维持张力
- 虐文: 虐恋比4:6,虐点后必有甜蜜补偿
- 每卷设置1个情感里程碑(确认心意/初吻/确认关系/公开)
""",
        
        "character_extra_fields": """

### 【耽美题材人物专属字段】

**【性向认知】**: 直男/弯的/双性恋/性向未明→因对方而弯

**【攻受属性】**(如适用): 强攻/忠犬攻/腹黑攻/美受/强受/傲娇受

**【情感状态】**: 单身/暗恋/暧昧/秘密交往/公开恋情

**【家庭背景】**: 家族对同性恋的态度(接受/反对/不知情)

**【外貌气质】**: 符合攻受设定的外貌描写(攻方英挺/受方精致等)

**【对CP的情感进度】**: 无感→好感→心动→确认心意→深爱,标注转折章节

**示例**:
【性向认知】: 直男(初期)→因沈墨而弯(第20章)
【攻受属性】: 强攻,占有欲强,外冷内热
【情感状态】: 单身(卷一)→暗中追求(卷二)→确认关系(卷三)
【家庭背景】: 军人世家,父母保守,需保密
【对沈墨情感进度】: 战友情(初期)→心动(第18章)→确认爱意(第35章)→非他不可(第60章)
""",
        
        # 🆕 增强版章节细纲模板（耽美专属）
        "chapter_detail_template": """第{chapter_num}章：《{chapter_title}》

【核心目标】本章在情感线中的作用

【情感进度】章节开始 → 章节结束，推进原因

【情节分镜】
1. 开场（双男主独处场景）
2. 暗昧升温
3. 情感高潮
4. 情感延伸
5. 悬念收尾

【关键对话】暗昧对话+深情对话

【情绪曲线】试探→心动→沉温→等待→悬念

【甜/虐设计】
类型、甜虐比、关键场景

【CP互动亮点】

【结尾钩子】

【涉及人物与情感发展】主要人物及本章变化
""",
        
        # 🆕 章节规划题材专属指导（耽美）
        "chapter_plan_guide": """
## 🌈 耽美题材规划要点

**情感阶段系统**：
- 明确双男主当前情感状态
- 情感推进要合理（性向认知/试探/确认）
- 标注情感进度：距离下一里程碑还有多远

**爽点类型侧重**：
- 优先考虑：暗昧升温/攻方护短/表白/吃醋
- 甜文：每5-8章一个甜蜜互动
- 虐文：虐后必有甜蜜补偿

**耽美特色元素**：
- 攻受定位与互动模式
- 试探/捕捉的张力
- 符合平台尺度要求
"""
    },
    
    "科幻": {
        "world_extra_sections": """

### 【科幻题材专属要求】

**科技等级体系**:
- 明确科技发展阶段: 行星文明→恒星文明→星系文明→宇宙文明
- 说明核心科技: 曲速引擎/虫洞跳跃/能量护盾/基因改造/机甲系统/AI等级
- 标注"技术代差": 高等文明对低等文明的碾压优势,主角如何逆袭

**星际格局与种族**:
- 列出3-5个核心势力: 人类联邦/外星帝国/机械文明/虫族/灵能种族
- 说明种族特性: 生理优势/科技特长/文化特点/敌对关系
- 标注"星际规则": 贸易协定/战争公约/禁忌技术

**能源与资源体系**:
- 核心能源: 反物质/暗能量/灵能晶体/零点能
- 稀有资源: 特殊矿石/古代遗迹/基因样本
- 资源争夺点: 富矿星球/虫洞节点/古代战舰
""",
        
        "outline_rhythm_guide": """

### 【科幻题材节奏设计】

**科技升级节奏**:
- 短篇: 单一科技突破/星球冒险
- 中篇: 个人→小队→舰队成长,含2-3次技术跃迁
- 长篇: 星际战争/文明对抗,含基因进化/机甲升级/舰队建设
- 超长篇: 跨星系远征,文明等级跃迁

**科幻爽点类型**:
- 【科技爽】: 黑科技碾压/技术突破/古代科技重现
- 【战斗爽】: 机甲战/舰队战/星球攻防
- 【探索爽】: 发现新星球/古代遗迹/未知文明
- 【进化爽】: 基因优化/身体改造/灵能觉醒
- 【征服爽】: 收服外星种族/建立势力/称霸星域

**节奏建议**:
- 每5-10章完成一次探索/战斗/科研突破
- 每15-25章设置一次技术跃迁或势力扩张
- 每卷设置一次文明等级提升或星际格局改变
""",
        
        "character_extra_fields": """

### 【科幻题材人物专属字段】

**【种族】**: 人类/改造人/外星种族/混血/AI意识体

**【基因等级】**: 基础人类/基因优化(1-5级)/完美基因/返祖基因

**【职业/军衔】**: 星舰舰长/机甲驾驶员/科研人员/雇佣兵/星际海盗,军衔等级

**【核心装备】**: 个人机甲/能量武器/生化改造/AI助手

**【特殊能力】**: 灵能等级/机械操控/虫群感应/时空感知

**【所属势力】**: 人类联邦/星际商会/雇佣兵团/外星帝国

**示例**:
【种族】: 人类(基因优化三代)
【基因等级】: C级(初期)→S级(后期觉醒远古基因)
【职业】: 星际佣兵→舰队指挥官→星域领主
【核心装备】: 泰坦级机甲"弑神者"、反物质步枪、AI助手"雅典娜"
【特殊能力】: 灵能等级A(可进行短距离瞬移和精神攻击)
【所属势力】: 自由佣兵团"黑鹰"(创始人)→人类第七舰队(指挥官)
""",
        
        # 🆕 增强版章节细纲模板（科幻专属）
        "chapter_detail_template": """第{chapter_num}章：《{chapter_title}》

【核心目标】本章在星际叙事中的作用（科技突破/星际战斗/种族接触）

【科技/战力变化】机甲等级/舰队规模变化，变化原因

【情节分镜】
1. 开场（如：接收到神秘信号）
2. 探索/战斗
3. 科技/战斗高潮
4. 延伸
5. 收尾

【科技/世界观扩展】
新科技、新势力/种族、宇宙谜题

【情绪曲线】好奇→惊险→震撼→敬畏→野心

【爽点设计】
类型：科技碾压/机甲战/舰队战/遗迹发现
强度：⭐~⭐⭐⭐⭐
实现方式

【结尾钩子】具体内容

【涉及人物/势力与发展】主要人物及本章变化
""",
        
        # 🆕 章节规划题材专属指导（科幻）
        "chapter_plan_guide": """
## 🚀 科幻题材规划要点

**科技与战力系统**：
- 明确当前科技等级/机甲等级/舰队规模
- 科技突破要合理（研究/遗迹/传承）
- 标注进度：距离下一次技术跳跃还有多远

**爽点类型侧重**：
- 优先考虑：科技碎压/机甲战/舰队战/遗迹发现
- 每5-10章完成一次探索/战斗
- 每15-25章一次技术跳跃

**科幻特色元素**：
- 星际设定要严谨有体系
- 种族/文明冲突要有层次
- 科技感与人性光辉并重
"""
    },
    
    "纯文学": {
        "world_extra_sections": """

### 【纯文学题材专属要求】

**时代背景与社会环境**:
- 明确历史时期: 具体年代/历史事件/社会变迁背景
- 说明时代特征: 政治氛围/经济状况/文化思潮/阶级矛盾
- 标注"时代对个体的影响": 命运如何被大时代裹挟/个体如何挣扎

**精神世界架构**:
- 主题探讨: 人性/孤独/存在意义/自由意志/道德困境
- 价值观冲突: 传统vs现代/集体vs个人/理想vs现实
- 象征体系: 核心意象/隐喻手法/象征意义

**人物精神成长轨迹**:
- 明确精神发展阶段: 蒙昧→觉醒→挣扎→顿悟→和解/毁灭
- 说明成长代价: 理想破灭/情感创伤/信仰崩塌
- 标注"精神转折点": 关键事件导致的价值观重塑
""",
        
        "outline_rhythm_guide": """

### 【纯文学题材节奏设计】

**叙事节奏**:
- 短篇: 单一事件/片段式人生/意识流叙述
- 中篇: 人物成长史/家族变迁/社会横切面
- 长篇: 史诗式叙事/多代人物/时代变迁全景

**纯文学"触动点"类型**(替代爽点):
- 【顿悟时刻】: 人物精神觉醒/价值观重塑的关键瞬间
- 【情感共鸣】: 深刻的孤独/爱/失落/和解
- 【诗意时刻】: 优美的环境描写/哲理性独白
- 【残酷真相】: 理想破灭/现实揭露的冲击力
- 【人性光辉】: 绝境中的善良/牺牲/坚守

**节奏建议**:
- 避免网文式密集爽点,注重情绪铺垫和氛围营造
- 每10-20章设置一个精神转折点或重大事件
- 允许大段环境/心理描写,节奏可舒缓
- 结局可留白/开放式,不必强求圆满
""",
        
        "character_extra_fields": """

### 【纯文学题材人物专属字段】

**【精神状态】**: 迷茫/觉醒/挣扎/顿悟/和解/绝望,动态演变

**【价值观立场】**: 对时代/社会/人性的核心看法,及其转变过程

**【社会阶层】**: 知识分子/工人/农民/市民,阶层对命运的影响

**【精神创伤】**: 战争/饥荒/政治运动/情感背叛等经历留下的心理烙印

**【象征意义】**: 该人物在作品中的象征内涵(如代表某一类人/某种精神)

**【命运轨迹】**: 从何处来/到何处去/如何被时代改变

**示例**:
【精神状态】: 理想主义(青年)→幻灭(中年)→和解(晚年)
【价值观立场】: 坚信个人奋斗可改变命运→认清时代洪流不可抗→在有限空间寻求尊严
【社会阶层】: 知识分子家庭出身→下放农村→平反后成为大学教师
【精神创伤】: 十年浩劫中目睹父亲自杀,导致终生无法与权威和解
【象征意义】: 代表一代知识分子在时代巨变中的精神困境与韧性
【命运轨迹】: 从理想主义青年→被时代碾压→在废墥中重建信仰
""",
        
        # 🆕 增强版章节细纲模板（纯文学专属）
        "chapter_detail_template": """第{chapter_num}章：《{chapter_title}》

【核心目标】本章在精神成长中的作用（价值观冲突/精神转折/顿悟时刻）

【精神状态变化】章节开始 → 章节结束，变化契机

【情节分镜】（注重氛围与内心描写）
1. 环境铺垫（时代背景/氛围烘托）
2. 事件/冲突（道德抖择）
3. 内心独白/顿悟（精神转折）
4. 人物互动（揭示主题）
5. 余韵收尾（诗意收束）

【核心意象/象征】（如：白桦林象征故土）

【主题探讨】（如：个人命运与时代洪流）

【情绪曲线】沉郁→挣扎→微光→惆怅→和解

【触动点设计】（替代爽点）
类型：顿悟时刻/情感共鸣/残酷真相/人性光辉/诗意时刻
实现方式

【结尾余韵】（如：那片白桦林依旧在风中沙沙作响...）

【涉及人物与精神变化】主要人物及本章变化
""",
        
        # 🆕 章节规划题材专属指导（纯文学）
        "chapter_plan_guide": """
## 📖 纯文学题材规划要点

**精神成长系统**：
- 明确主角当前精神状态（迷茫/觉醒/挣扎/和解）
- 价值观变化要有契机（事件/遇见/签悉）
- 标注进度：距离下一次精神转折还有多远

**触动点类型**（替代爽点）：
- 优先考虑：顷悟时刻/情感共鸣/残酷真相/人性光辉
- 节奏可舒缓，注重情绪铺垫
- 每10-20章一个精神转折点

**纯文学特色元素**：
- 象征、隐喻的运用
- 内心独白与环境描写
- 留白与诗意的余韵
"""
    }
}

# 🆕 通用题材(兆底方案)
DEFAULT_GENRE_MODULE = {
    "world_extra_sections": "",
    "outline_rhythm_guide": """

### 【通用题材节奏建议】
- 每5-10章推进一次主线剧情
- 每15-25章设置一次重大转折
- 注意张弛有度,避免平铺直叙
""",
    "character_extra_fields": "",
    
    # 🆕 章节规划题材专属指导（通用默认）
    "chapter_plan_guide": """
## 📝 通用章节规划要点

**剧情推进**：
- 明确本章在整体故事中的位置
- 情节推进要有实质进展，避免原地踏步
- 每章结尾留有钩子

**节奏控制**：
- 注意张弛有度，紧张-舒缓交替
- 每5-10章一个小高潮
- 每卷一个大高潮

**人物与场景**：
- 人物行为符合性格设定
- 场景转换自然流畅
""",
    
    # 🆕 增强版章节细纲模板（通用默认）
    "chapter_detail_template": """第{chapter_num}章：《{chapter_title}》

【核心目标】本章在故事中的作用

【进度变化】章节开始 → 章节结束的关键变化

【情节分镜】（3-5个场景）
1. 开场(10%)：场景描述
2. 发展(30%)：场景描述
3. 小高潮(25%)：场景描述
4. 延伸(20%)：场景描述
5. 收尾(15%)：场景描述

【关键对话】（1-2段核心对话大意）

【情绪曲线】情绪走势（如：平静→紧张→释放→期待）

【伏笔设计】埋设/回收的伏笔

【高潮/转折设计】
类型、强度、实现方式

【结尾钩子】具体内容

【涉及人物与发展】主要人物及本章变化
"""
}


class CreativeDirectorCoordinator:
    """
    真实协调器（简版实现）：提供五阶段方法与必要的上下文接口，
    以满足系统的调用约定并避免导入失败。
    """

    def __init__(
        self,
        knowledge_base: Optional[NovelKnowledgeBase] = None,
        memory_manager: Optional[NovelMemoryManager] = None,
        enable_communication: bool = True,
        enable_conflict_detection: bool = True,
        enable_detailed_logging: bool = True,
    ) -> None:
        self.knowledge_base = knowledge_base or NovelKnowledgeBase()
        self.memory_manager = memory_manager or NovelMemoryManager()

        self.enable_communication = enable_communication
        self.enable_conflict_detection = enable_conflict_detection
        self.enable_detailed_logging = enable_detailed_logging
        
        # 初始化真实Agent
        self.creative_director = CreativeDirectorAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)
        self.world_architect = WorldArchitectAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)
        self.character_designer = CharacterDesignerAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)
        self.content_creator = ContentCreatorAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)
        self.quality_reviewer = QualityReviewerAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)
        self.outline_plan_parser = OutlinePlanParserAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)

        # 项目上下文
        self.project_id: Optional[int] = None
        self.project_context: Dict[str, Any] = {
            "concept": "",
            "world_setting": "",
            "characters": "",
            "plot_outline": "",
            "content": "",
            "chapters": [],
            "review": "",
        }

        # 长篇创作配置
        self.target_chapter_count: Optional[int] = None

        # 进度回调（可选）
        self._progress_cb = None
        self._progress_task_id = None
        self._progress_project_id = None

    # ---- 基础接口 ----
    def set_project_context(self, project_id: int) -> None:
        self.project_id = project_id

    def set_longform_config(self, target_chapter_count: Optional[int] = None) -> None:
        self.target_chapter_count = target_chapter_count

    def set_progress_callback(self, cb, task_id: str, project_id: int) -> None:
        self._progress_cb = cb
        self._progress_task_id = task_id
        self._progress_project_id = project_id

    def parse_outline_plan(self, user_outline_plan: str, genre: str = "", planned_length_type: str = "") -> Dict[str, Any]:
        """
        解析用户自定义大纲规划文本，生成结构化JSON
        
        Args:
            user_outline_plan: 用户输入的自然语言大纲规划
            genre: 项目题材
            planned_length_type: 篇幅类型 (short/mid/long/epic)
        
        Returns:
            结构化规划数据，包含：
            - volume_plan: 卷结构规划
            - realm_plan: 境界规划（修仙题材）
            - rhythm_plan: 节奏要求
        """
        logger.info(f"📝 开始解析用户大纲规划...")
        
        if not user_outline_plan or not user_outline_plan.strip():
            logger.info("⚠️ 用户未提供自定义规划，返回空结果")
            return {}
        
        # 构建解析prompt
        parse_prompt = f"""请解析以下用户输入的大纲规划文本，提取其中的结构化信息。

【项目信息】
- 题材：{genre or "未指定"}
- 篇幅：{planned_length_type or "未指定"}

【用户规划原文】
{user_outline_plan}

【解析任务】
请从上述文本中提取以下信息（如果存在）：

1. **卷结构规划** (volume_plan)
   - 卷数：共几卷
   - 卷信息列表：[{{
       "volume_number": 1,
       "volume_title": "卷标题",
       "chapter_range": "1-30章" 或 {"min": 1, "max": 30},
       "main_goal": "本卷主要目标",
       "key_events": ["关键事件1", "关键事件2"]
     }}]

2. **境界规划** (realm_plan) - 仅适用于修仙/玄幻题材
   - 境界列表：[{{
       "realm_name": "境界名称",
       "chapter_range": "1-100章" 或 {"min": 1, "max": 100},
       "sub_levels": ["初期", "中期", "后期", "大圆满"],
       "key_abilities": ["核心能力1", "核心能力2"]
     }}]

3. **节奏要求** (rhythm_plan)
   - 爽点分布：每几章一个小爽点，每几章一个大爽点
   - 情绪起伏：["小爽", "压抑", "大爽", "悬疑", "爆爽"]
   - 转折点：主要转折点位置

【输出JSON Schema】
请严格按照以下JSON格式输出，**只输出JSON，不要添加任何markdown代码块标记或解释性文字**：

{{
  "volume_plan": {{
    "total_volumes": 数字,
    "volumes": [
      {{
        "volume_number": 1,
        "volume_title": "卷标题",
        "chapter_range": {{
          "min": 起始章,
          "max": 结束章
        }},
        "main_goal": "本卷主要目标",
        "key_events": ["事件1", "事件2"]
      }}
    ]
  }},
  "realm_plan": {{
    "realms": [
      {{
        "realm_name": "境界名",
        "chapter_range": {{
          "min": 起始章,
          "max": 结束章
        }},
        "sub_levels": ["阶段1", "阶段2"],
        "key_abilities": ["能力1", "能力2"]
      }}
    ]
  }},
  "rhythm_plan": {{
    "small_climax_interval": 每几章,
    "big_climax_interval": 每几章,
    "emotion_flow": ["小爽", "压抑", "大爽"],
    "major_turning_points": [章节号列表]
  }}
}}

**重要提醒**：
1. 如果用户文本中没有提到某个部分，请直接忽略该字段（不要输出null或空对象）
2. 如果是非修仙题材，可以忽略realm_plan
3. 必须输出合法的JSON格式，不要使用任何注释
4. 章节范围必须使用{{"min": X, "max": Y}}格式

现在请开始解析，直接输出JSON："""
        
        try:
            # 调用解析Agent
            result = self.outline_plan_parser.process(parse_prompt)
            
            # 清理输出，移除markdown代码块标记
            result = result.strip()
            if result.startswith("```json"):
                result = result[7:]
            if result.startswith("```"):
                result = result[3:]
            if result.endswith("```"):
                result = result[:-3]
            result = result.strip()
            
            # 解析JSON
            parsed_plan = json.loads(result)
            logger.info(f"✅ 大纲规划解析成功: {list(parsed_plan.keys())}")
            
            # 存储到项目上下文
            self.project_context["parsed_outline_plan"] = parsed_plan
            
            return parsed_plan
            
        except json.JSONDecodeError as e:
            logger.error(f"⚠️ JSON解析失败: {e}")
            logger.error(f"原始输出: {result[:500]}")
            # 尝试使用正则表达式提取
            return self._fallback_parse(user_outline_plan)
        except Exception as e:
            logger.error(f"⚠️ 解析过程出错: {e}")
            return self._fallback_parse(user_outline_plan)
    
    def _fallback_parse(self, text: str) -> Dict[str, Any]:
        """降级方案：使用正则表达式提取基本信息"""
        logger.info("🔧 使用降级方案解析大纲规划...")
        plan = {}
        
        # 提取卷数
        volume_match = re.search(r'(\d+)\s*卷', text)
        if volume_match:
            plan["volume_plan"] = {
                "total_volumes": int(volume_match.group(1)),
                "volumes": []
            }
        
        # 提取境界
        realm_matches = re.findall(r'(炼气|筑基|金丹|元婴|化神|渡劫|大乘|仙人)', text)
        if realm_matches:
            plan["realm_plan"] = {
                "realms": [{"realm_name": r} for r in set(realm_matches)]
            }
        
        logger.info(f"✅ 降级解析完成: {list(plan.keys())}")
        return plan

    # ---- 阶段方法 ----
    def _stage_one_concept_development(self, requirement: str) -> Dict[str, Any]:
        """
        阶段1：概念开发 - 调用真实Agent生成
        返回 keys：concept, world_setting, characters
        """
        logger.info(f"🎯 开始真实Agent概念开发，需求: {requirement[:100]}...")
        
        # 🔧 获取重生信息（在创意总监执行前就读取）
        regenerate_targets = self.project_context.get("regenerate_targets", [])
        is_regenerate = self.project_context.get("regenerate", False)
        
        # 1. 创意总监生成故事概念（按 regenerate_targets 条件执行）
        should_generate_concept = not is_regenerate or "story" in regenerate_targets
        
        if should_generate_concept:
            logger.info("📝 创意总监正在生成故事概念...")
            # 🔧 重生时的特别提示
            regenerate_hint = ""
            if is_regenerate and "story" in regenerate_targets:
                regenerate_hint = "\n\n【重生成说明】\n这是一次重新生成，请基于用户反馈进行优化与调整，确保有明显改进。若用户未提供具体反馈，则从以下角度进行轻微优化：\n1. 增强核心标签的差异化锐度\n2. 优化Logline的吸引力\n3. 调整核心冲突的层次感"
            concept_prompt = f"""你是一名擅长网文结构设计的"创意总监"，需要为一个新项目生成【故事概念】和初步【世界观设定】。{regenerate_hint}

【已知信息】
- 项目题目：{self.project_context.get("title") or self.project_context.get("project_title") or "未命名项目"}
- 题材类型：{self.project_context.get("genre") or self.project_context.get("project_genre") or "通用题材"}
- 用户提供的初始想法（如有）：{requirement or "暂无"}

【总体要求】
1. 先完成“故事概念”六段标准输出，再给出一个与之匹配的高度概括版世界观（可简略）。
2. 保持网文向：强调爽点潜力、冲突强度和持续升级空间。
3. 若 context 中提供了已有大纲或人物设定（重生成场景），须确保新概念与它们在世界观与核心矛盾上相容。

——————————
一、请先生成【故事概念】，严格按以下六个部分输出（用 Markdown 粗体标记小标题）：

1. **一句话卖点（Logline）**：
- 用一句极具吸引力的网文式概括，包含主角类型、核心能力/优势、主要对手/系统，以及最具爽感的长期目标或爆点。
- 优先使用“主角行动 + 意外结果”句式，例如：“废柴掌控修真流水线，反手碾压宗门大佬”，而不是单纯罗列设定。
- 控制在 30–60 字之间。

2. **日志标题（短标题）**：
- 用 4–10 个字给出一个便于读者记忆的项目名，偏网文风格。

3. **概念摘要（80–150字）**：
- 简要交代主角身份、初始困境、长期目标、主要阻力，以及世界观的一个独特钩子。
- 语气偏“介绍本书卖点”，而不是平铺剧情。

4. **题材与流派（主题材/子流派）**：
- 主题材例如：玄幻修真 / 反乌托邦科幻 / 历史权谋 / 都市奇能 等；
- 子流派例如：系统流 / 科技修仙流 / 穿越流 / 言情权谋 / 无限流 等；
- 用“主题材 / 子流派1+子流派2”的形式表述，保持网文分类习惯。

5. **核心标签（3–6个）**：
- 提炼最能体现本书差异化的关键词，如“末法时代、格物修真、底层逆袭、技术流打脸”；
- 必须至少包含 1 个“反套路/细分创新”标签（例如：“修真+工业流水线”“系统是反派”“主角不想飞升只想活下去”），避免全是常规标签；
- 避免只出现“热血、成长”这类无区分度的词语。

6. **核心冲突与情感基调**：
- 用 2–3 句话说明：
  - 主线冲突是谁对谁，是什么利益/观念/系统矛盾；
  - 整体情绪是偏爽文逆袭、黑暗现实、甜宠成长还是悬疑惊悚等（可以混合）。

——————————
二、在完成六段“故事概念”之后，请追加一个小节：

7. **世界观高概摘要（可简略）**：
- 用 3–5 句简要说明故事发生的时代背景、主要势力格局和核心规则特点；
- 此处只做高度概括，详细世界观将在后续阶段展开。

请严格按照上述顺序与小标题输出，不要添加其他额外说明。"""
            # 🎲 提高temperature增加创造性，避免相同题材生成重复内容
            concept_result = self.creative_director.process(
                concept_prompt,
                temperature=0.9  # 使用高温度增加随机性和创造性
            )
            concept = concept_result if isinstance(concept_result, str) else concept_result.get("output", requirement)
            logger.info(f"✅ 故事概念生成完成，长度: {len(concept)}")
        else:
            # 重生时不重生story，沿用旧概念
            concept = self.project_context.get("concept") or ""
            logger.info("⏭ 跳过故事概念生成，沿用现有故事概念。")
        
        # 2. 世界观架构师生成世界观设定（按 regenerate_targets 条件执行）
        # 判断是否需要重生世界观
        should_generate_world = not is_regenerate or "world" in regenerate_targets
        
        if should_generate_world:
            logger.info("🌍 世界观架构师正在生成世界观...")
            
            # 🆕 构建题材篇幅信息
            genre_info = ""
            parsed_plan = self.project_context.get("parsed_outline_plan", {})
            
            if self.project_context.get("genre"):
                genre_info += f"\n- 题材：{self.project_context.get('genre')}"
            if self.project_context.get("planned_length_type"):
                length_labels = {"short": "短篇", "mid": "中篇", "long": "长篇", "epic": "超长篇"}
                planned_length = length_labels.get(self.project_context.get("planned_length_type"), self.project_context.get("planned_length_type"))
                genre_info += f"\n- 篇幅：{planned_length}"
                if self.project_context.get("planned_chapters_min") and self.project_context.get("planned_chapters_max"):
                    genre_info += f"（{self.project_context.get('planned_chapters_min')}-{self.project_context.get('planned_chapters_max')}章）"
            
            # 🆕 获取题材专属Prompt模块
            current_genre = self.project_context.get("genre", "")
            genre_module = GENRE_PROMPT_MODULES.get(current_genre, DEFAULT_GENRE_MODULE)
            genre_terms = GENRE_TERMINOLOGY.get(current_genre, {})
            
            # 🆕 构建规划约束
            plan_constraint = ""
            if parsed_plan:
                plan_constraint += "\n\n【用户自定义规划约束】"
                
                # 境界规划
                if "realm_plan" in parsed_plan and parsed_plan["realm_plan"].get("realms"):
                    plan_constraint += "\n**境界规划**：用户已指定以下境界体系，世界观必须兼容："
                    
                    # 🆕 修仙/玄幻题材境界节奏检查
                    current_genre = self.project_context.get("genre", "")
                    if current_genre in ["修仙", "玄幻"]:
                        for realm in parsed_plan["realm_plan"]["realms"][:5]:  # 最多显示5个
                            realm_name = realm.get('realm_name', '')
                            plan_constraint += f"\n- {realm_name}"
                            
                            if realm.get('sub_levels'):
                                plan_constraint += f" (包含: {', '.join(realm['sub_levels'][:3])})"
                            
                            # 检查境界跨度
                            chapter_range = realm.get('chapter_range', {})
                            if isinstance(chapter_range, dict):
                                span = chapter_range.get('max', 0) - chapter_range.get('min', 0)
                                
                                # 超过500章触发建议
                                if span > REALM_SPAN_WARNING_THRESHOLD:
                                    plan_constraint += f" ⚠️ 跨度{span}章，建议细分为【{realm_name}·初期/中期/后期/大圆满】等子阶段"
                                # 300-500章给出温和提示
                                elif span > REALM_SPAN_RECOMMEND_SUBDIVISION:
                                    plan_constraint += f" 💡 跨度{span}章，可考虑细分子阶段以优化节奏"
                    else:
                        # 非修仙题材，简单显示
                        for realm in parsed_plan["realm_plan"]["realms"][:5]:
                            plan_constraint += f"\n- {realm.get('realm_name', '')}"
                            if realm.get('sub_levels'):
                                plan_constraint += f" (包含: {', '.join(realm['sub_levels'][:3])})"
                
                # 卷结构
                if "volume_plan" in parsed_plan and parsed_plan["volume_plan"].get("total_volumes"):
                    total_vols = parsed_plan["volume_plan"]["total_volumes"]
                    plan_constraint += f"\n**卷结构**：用户规划了{total_vols}卷结构，世界观需为这个长度预留升级空间。"
            
            # 🆕 构建题材术语适配提示
            if genre_terms:
                plan_constraint += "\n\n【题材术语适配建议】"
                plan_constraint += f"\n- 核心体系：{genre_terms.get('power_system', '')}"
                plan_constraint += f"\n- 关键资源：{genre_terms.get('resources', '')}"
                plan_constraint += f"\n- 典型冲突：{genre_terms.get('conflicts', '')}"
                plan_constraint += f"\n- 社会结构：{genre_terms.get('social_structure', '')}"
                if current_genre not in ["都市", "纯文学", "悬疑", "言情", "耽美"]:
                    plan_constraint += f"\n- 关键术语：{genre_terms.get('key_terms', '')}"
            
            # 🆕 使用模块化提示词生成世界观 prompt（引用式）
            genre_extra = genre_module.get('world_extra_sections', '') or get_genre_world_extension(current_genre)
            world_prompt = WorldBuildingPrompts.get_world_prompt(
                genre=f"{self.project_context.get('genre') or self.project_context.get('project_genre') or '通用题材'}{genre_info}",
                requirement=requirement or "暂无特别要求",
                genre_constraint=plan_constraint,
                genre_extra_sections=genre_extra
            )
            # 🔥 完整concept传入context,由_format_context智能截断
            world_context = {
                "concept": concept,
                "requirement": requirement
            }
            world_result = self.world_architect.process(world_prompt, context=world_context)
            world = world_result if isinstance(world_result, str) else world_result.get("output", "世界观设定")
            logger.info(f"✅ 世界观生成完成，长度: {len(world)}")
        else:
            # 重生时不重生world，沿用旧世界观
            world = self.project_context.get("world_setting") or ""
            logger.info("⏭ 跳过世界观生成，沿用现有世界观设定。")
        
        # 3. 人物设计师生成人物设定（按 regenerate_targets 条件执行）
        # 判断是否需要重生人物（目前 UI 只有 story/world，没有人物，所以重生时不该跳过）
        should_generate_characters = not is_regenerate or "characters" in regenerate_targets
        
        if should_generate_characters:
            logger.info("👥 人物设计师正在生成人物...")
            
            # 🆕 使用模块化提示词生成人物设计 prompt（引用式）
            char_extra = genre_module.get('character_extra_fields', '') or get_genre_character_fields(current_genre)
            char_prompt = CharacterDesignPrompts.get_character_prompt(
                requirement=requirement or "暂无特别要求",
                genre_extra_fields=char_extra
            )
            # 🔥 完整concept+world_setting传入context,由_format_context智能截断
            char_context = {
                "concept": concept,
                "world_setting": world,
                "requirement": requirement
            }
            char_result = self.character_designer.process(char_prompt, context=char_context)
            chars = char_result if isinstance(char_result, str) else char_result.get("output", "人物设定")
            logger.info(f"✅ 人物生成完成，长度: {len(chars)}")
        else:
            # 重生时不重生人物，沿用旧人物设定
            chars = self.project_context.get("characters") or ""
            logger.info("⏭ 跳过人物生成，沿用现有人物设定。")
        
        # 更新上下文
        self.project_context.update({
            "concept": concept,
            "world_setting": world,
            "characters": chars,
        })
        
        logger.info("🎉 概念开发阶段完成！")
        return {"concept": concept, "world_setting": world, "characters": chars}

    def _stage_two_structure_design(self, concept_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        阶段2：结构设计 - 调用真实Agent生成
        返回 keys：plot_outline
        """
        logger.info(f"🎯 开始真实Agent结构设计...")
        
        concept = concept_result.get("concept") or self.project_context.get("concept")
        world_setting = concept_result.get("world_setting") or self.project_context.get("world_setting")
        characters = concept_result.get("characters") or self.project_context.get("characters")
        
        # 获取题材专属Prompt模块
        current_genre = self.project_context.get("genre", "")
        genre_module = GENRE_PROMPT_MODULES.get(current_genre, DEFAULT_GENRE_MODULE)
        
        logger.info("📝 创意总监正在生成网文卷结构大纲...")
        
        # 🎆 使用分层摘要策略优化上下文
        from .layered_summarizer import LayeredSummarizer
        
        logger.info(f"\n{'='*70}")
        logger.info(f"【分层摘要器】为结构设计阶段准备上下文")
        logger.info(f"{'='*70}\n")
        
        layered_summarizer = LayeredSummarizer(self.knowledge_base)
        context_result = layered_summarizer.prepare_context_for_expansion(
            outline=concept or "",  # 结构设计阶段使用concept作为大纲
            characters=characters or "",
            worldview=world_setting or "",
            scenario="structure_design",
            current_count=self.target_chapter_count or 50
        )
        
        # 🔥 使用智能选择的模型和优化后的上下文
        selected_model = context_result["selected_model"]
        optimized_context = context_result["context"]
        stats = context_result["stats"]
        
        logger.info(f"📊 上下文优化（结构设计 - 分层摘要）:")
        logger.info(f"   - 选择模型: {selected_model}")
        logger.info(f"   - 原始总长: {len(concept or '') + len(characters or '') + len(world_setting or ''):,}字符")
        logger.info(f"   - 优化后: {len(optimized_context):,}字符 (压缩{(1-stats['compression_ratio'])*100:.1f}%)")
        logger.info(f"   - 目标tokens: {stats['total_tokens']:,} / {stats['target_tokens']:,}\n")
        
        # 🆕 使用模块化提示词生成结构设计 prompt（方案A - 纯引用式）
        rhythm_guide = genre_module.get('outline_rhythm_guide', '') or get_genre_rhythm_guide(current_genre)
        structure_prompt = StructureDesignPrompts.get_structure_prompt(
            genre_rhythm_guide=rhythm_guide,
            genre=current_genre or "通用"
        )
        
        # 🔥 只传optimized_context,避免与分层摘要冲突
        structure_context = {
            "optimized_context": optimized_context
        }
        # 🔄 临时切换创意总监到分层摘要器选择的模型
        orig_llm = getattr(self.creative_director, "llm", None)
        try:
            # 根据分层摘要器选择的模型创建llm实例
            if selected_model == "deepseek-r1":
                structure_llm = create_deepseek_llm(task_type="quality_review")  # R1模型
                logger.info("⚙️ [生效日志] 结构阶段启用R1模型：task_type=quality_review, model=deepseek-reasoner")
            elif "qwen" in selected_model:
                # 使用qwen系列模型
                structure_llm = create_deepseek_llm(task_type="outline_expand" if selected_model == "qwen-long" else "summarize")
                logger.info(f"⚙️ [生效日志] 结构阶段启用{selected_model}模型")
            else:
                structure_llm = create_deepseek_llm(task_type="quality_review")  # 默认R1
                logger.info("⚙️ [生效日志] 结构阶段默认使用R1模型")
            
            self.creative_director.llm = structure_llm
            structure_result = self.creative_director.process(structure_prompt, context=structure_context)
        finally:
            if orig_llm is not None:
                self.creative_director.llm = orig_llm
                logger.info("🔄 [生效日志] 结构阶段结束，创意总监恢复原模型配置")
        
        outline = structure_result if isinstance(structure_result, str) else structure_result.get("output", "结构大纲")
        logger.info(f"✅ 结构大纲生成完成，长度: {len(outline)}")
        
        self.project_context.update({"plot_outline": outline})
        return {"plot_outline": outline}

    def _extract_first_chapter_plan(self, plot_outline: str) -> str:
        """从完整大纲中提取第1章的规划内容
        
        Args:
            plot_outline: 完整的情节大纲
            
        Returns:
            第1章的规划内容,如果提取失败返回简化版本
        """
        if not plot_outline:
            return "请根据故事概念和世界观设定,创作引人入胜的第一章内容。"
        
        # 尝试提取第1章内容（支持多种格式）
        import re
        
        # 模式1: 匹配 "第1章" 或 "第一章" 开头的段落
        patterns = [
            r'第1章[：:](.*?)(?=第2章|第二章|卷二|$)',
            r'第一章[：:](.*?)(?=第2章|第二章|卷二|$)',
            r'第1章\s+(.*?)(?=第2章|第二章|卷二|$)',
            r'第一章\s+(.*?)(?=第2章|第二章|卷二|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, plot_outline, re.DOTALL | re.IGNORECASE)
            if match:
                extracted = match.group(0).strip()
                # 限制长度在2000字以内（保持精简）
                if len(extracted) > 2000:
                    extracted = extracted[:2000] + "..."
                logger.info(f"✅ 成功提取第1章规划,长度: {len(extracted)}")
                return extracted
        
        # 如果没有明确的章节标记,尝试提取开头部分
        lines = plot_outline.split('\n')
        first_section = []
        for line in lines[:50]:  # 只看前50行
            if line.strip():
                first_section.append(line)
                if len('\n'.join(first_section)) > 1500:
                    break
        
        if first_section:
            extracted = '\n'.join(first_section)
            logger.info(f"✅ 提取大纲开头作为第1章规划,长度: {len(extracted)}")
            return extracted
        
        # 兜底:返回整个大纲的前1500字
        fallback = plot_outline[:1500]
        logger.warning(f"⚠️ 无法识别第1章规划结构,使用大纲前1500字")
        return fallback

    def _stage_three_content_creation(self, structure_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        阶段3：内容创作 - 调用真实Agent生成
        返回 keys：content 或 chapters
        """
        logger.info(f"🎯 开始真实Agent内容创作...")
        
        plot_outline = structure_result.get("plot_outline") or self.project_context.get("plot_outline")
        concept = self.project_context.get("concept")
        world_setting = self.project_context.get("world_setting")
        characters = self.project_context.get("characters")
        target = self.target_chapter_count or 1
        current_genre = self.project_context.get('genre') or self.project_context.get('project_genre') or ''
        
        logger.info(f"✍️ 内容创作师正在生成第1章草稿（目标{target}章）...")
        
        # 🔥 从大纲中提取第1章规划
        chapter_plan = self._extract_first_chapter_plan(plot_outline or '')
        
        # 🆕 定义开头/结尾方式（与 workflow.py 保持同步）
        opening_styles = {
            "对话开头": ("对话开头", "直接进入冲突或紧张场景，用对话抽出矛盾", ""),
            "动作开头": ("动作开头", "从正在发生的动态事件开始，制造紧迫感", ""),
            "悬念开头": ("悬念开头", "抛出问题或异常现象，引发读者好奇，创造独特的开场", ""),
            "场景开头": ("场景开头", "通过环境氛围描写快速建立情境，融入题材特色", ""),
            "反转开头": ("反转开头", "与上章结尾形成对比或反差，制造意外效果", ""),
        }
        ending_styles = {
            "悬念式": ("悬念式", "关键信息揭露一半，留下悬念让读者想继续阅读", ""),
            "转折式": ("转折式", "意外事件发生，打破读者预期", ""),
            "动作中断式": ("动作中断式", "危机时刻戈然而止，制造紧张感", ""),
            "信息炸弹式": ("信息炸弹式", "揭露惊人真相或身份，制造震撼效果", ""),
            "选择困境式": ("选择困境式", "主角面临艰难拉择，强化情绪张力", ""),
        }
        
        # ✅ 第1章使用固定的开头/结尾方式（适合开篇）
        selected_opening = opening_styles["悬念开头"]  # 第1章用悬念开头吸引读者
        selected_ending = ending_styles["悬念式"]  # 第1章结尾留悬念
        
        # 🆕 使用ChapterPromptBuilder（与生成下一章保持一致）
        from .chapter_prompt_builder import ChapterPromptBuilder
        
        builder = ChapterPromptBuilder(genre=current_genre)
        content_system_prompt = builder.build_system_prompt()
        content_user_prompt = builder.build_user_prompt(
            next_chapter_number=1,
            chapter_plan=chapter_plan,  # ✅ 只传第1章规划(~1500字)
            previous_ending="",  # 第1章无前文
            rag_character_context="",  # 初始化时RAG还是空的
            rag_world_context="",  # 初始化时RAG还是空的
            selected_opening=selected_opening,
            selected_ending=selected_ending,
        )
        
        # ✅ 使用双prompt调用
        content_result = self.content_creator.process(
            prompt=content_user_prompt,
            context=None,  # 不需要context
            system_prompt=content_system_prompt  # 传入system_prompt
        )
        content = content_result if isinstance(content_result, str) else content_result.get("output", "章节内容")
        logger.info(f"✅ 第1章创作完成，长度: {len(content)}")
        
        self.project_context.update({"content": content, "chapters": [content]})
        return {"content": content}

    def _stage_four_quality_review(self, content_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        阶段4：质量评审 - 调用真实Agent生成
        返回 keys：review, needs_revision
        """
        logger.info(f"🎯 开始真实Agent质量评审...")
        
        content = (
            content_result.get("content")
            or self.project_context.get("content")
            or self.project_context.get("plot_outline")
            or ""
        )
        
        if not content:
            logger.warning("⚠️ 无内容可评审，返回占位符")
            return {"review": "无可评审内容", "needs_revision": False}
        
        logger.info("🔍 质量评审官正在评审内容...")
        
        # 🆕 使用智能截断替代手动截断
        # qwen-max限制: 30720 tokens ≈ 46000字符
        # 评审模板约1500字 + content，需确保总输入不超限
        truncated_content = smart_truncate_for_context(
            content=content,
            max_tokens=20000,  # 为评审模板预留10720 tokens空间
            content_type="chapter",
            preserve_ratio=0.8  # 章节内容优先保留完整情节
        )
        
        logger.info(f"📏 内容长度: {len(content)} → {len(truncated_content)}字符")
        
        review_prompt = f"""你是一位专业的网络小说质量评审官。请使用【网文6维度评审体系】对以下内容进行评审：

【待评审内容】
{truncated_content}

## 📊 网文6维度评审体系

### 1. 爽点效果（权重25%）
- 本章是否有明确的爽点或为后续爽点做了铺垫？
- 是否成功吸引读者？

### 2. 节奏把控（权重20%）
- 信息密度是否适中？
- 场景转换是否流畅？
- 对话与叙述比例是否合理（建议30-50%对话）？

### 3. 钩子效果（权重15%）
- 章节开头是否吸引人？
- 章节结尾是否有悬念/钩子？
- 读者是否有“想点下一章”的冲动？

### 4. 代入感（权重15%）
- 主角视角是否清晰？
- 是否有强烈的画面感与情感渲染？

### 5. 文笔流畅度（权重10%）
- 是否存在明显AI痕迹或机械感？
- 对话是否自然、符合人物性格？
- 描写是否生动有画面感？

### 6. 内容一致性（权重15%）
- 与人物设定、世界观规则是否一致？

【输出格式】
请使用以下格式输出评审报告：

## 📊 网文质量评审报告

**综合评分**：X/10分

### 1. 爽点效果 ⭐⭐⭐
- 评价：...
- 问题：...

### 2. 节奏把控 ⭐⭐⭐
- 评价：...
- 问题：...

### 3. 钩子效果 ⭐⭐⭐
- 开头评价：...
- 结尾评价：...
- 问题：...

### 4. 代入感 ⭐⭐⭐
- 评价：...
- 问题：...

### 5. 文笔流畅度 ⭐⭐⭐
- 评价：...
- 问题：...

### 6. 内容一致性 ⭐⭐⭐
- 评价：...
- 问题：...

### 🔧 具体修改建议（按优先级排序）
1. 【必改】...
2. 【建议】...
3. 【可选】..."""
        
        # 🔥 prompt中已包含content[:3000],context不再重复传递
        review_context = None
        review_result = self.quality_reviewer.process(review_prompt, context=review_context)
        review = review_result if isinstance(review_result, str) else review_result.get("output", "评审报告")
        logger.info(f"✅ 质量评审完成，长度: {len(review)}")
        
        # 简单判断是否需要修订（基于关键词）
        needs_revision = any(keyword in review for keyword in ["需要修订", "建议修改", "必须改进", "严重问题"])
        logger.info(f"📋 是否需要修订: {needs_revision}")
        
        self.project_context.update({"review": review})
        return {"review": review, "needs_revision": needs_revision}

    def _stage_five_iteration_optimization(self, review_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        阶段5：迭代优化 - 调用真实Agent生成
        返回 keys：revised_content, final_review
        """
        logger.info(f"🎯 开始真实Agent迭代优化...")
        
        original_content = self.project_context.get("content") or ""
        review = review_result.get("review") or self.project_context.get("review") or ""
        needs_revision = review_result.get("needs_revision", False)
        
        if not needs_revision:
            logger.info("✅ 内容无需修订，直接通过")
            return {"revised_content": original_content, "final_review": "内容质量达标，无需修订"}
        
        logger.info("✏️ 内容创作师正在根据评审意见优化内容...")
        
        # 🆕 使用智能截断替代手动截断
        truncated_original = smart_truncate_for_context(
            content=original_content,
            max_tokens=13000,  # 为评审意见和提示词预留空间
            content_type="chapter",
            preserve_ratio=0.8
        )
        
        truncated_review = smart_truncate_for_context(
            content=review,
            max_tokens=6000,  # 评审意见保留核心问题
            content_type="review",
            preserve_ratio=0.9  # 评审意见优先保留【必改】项
        )
        
        logger.info(f"📏 原始内容: {len(original_content)} → {len(truncated_original)}字符")
        logger.info(f"📏 评审意见: {len(review)} → {len(truncated_review)}字符")
        
        revision_prompt = f"""请根据以下评审意见优化内容：

【原始内容】
{truncated_original}

【评审意见】
{truncated_review}

优化要求：
1. 保持故事主线和人物设定不变
2. 针对评审中指出的具体问题进行修改
3. 优化语言表达和叙事节奏
4. 增强细节描写和情感渲染
5. 确保逻辑连贯性

请输出优化后的完整内容。"""
        
        # 🔥 prompt中已包含original_content[:2000]和review[:1000],context不重复
        revision_context = None
        revision_result = self.content_creator.process(revision_prompt, context=revision_context)
        revised_content = revision_result if isinstance(revision_result, str) else revision_result.get("output", original_content)
        logger.info(f"✅ 内容优化完成，长度: {len(revised_content)}")
        
        # 最终评审
        logger.info("🔍 质量评审官进行最终评审...")
        
        # 🆕 使用智能截断
        truncated_revised = smart_truncate_for_context(
            content=revised_content,
            max_tokens=13000,
            content_type="chapter",
            preserve_ratio=0.8
        )
        
        logger.info(f"📏 优化后内容: {len(revised_content)} → {len(truncated_revised)}字符")
        
        final_review_prompt = f"""请对优化后的内容进行最终评审：

【优化后内容】
{truncated_revised}

Please confirm：
1. 是否解决了之前指出的问题
2. 整体质量是否达标
3. 是否可以发布

给出简短的最终评审意见。"""
        
        # 🔥 prompt中已包含revised_content[:2000],context不重复
        final_review_result = self.quality_reviewer.process(final_review_prompt, context=None)
        final_review = final_review_result if isinstance(final_review_result, str) else final_review_result.get("output", "最终评审完成")
        logger.info(f"✅ 最终评审完成，长度: {len(final_review)}")
        
        self.project_context.update({"content": revised_content})
        return {"revised_content": revised_content, "final_review": final_review}
