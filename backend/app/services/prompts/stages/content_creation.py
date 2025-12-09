"""
内容创作阶段提示词模块

从 chapter_prompt_builder.py 提取的内容创作相关提示词
"""

from typing import Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class ContentCreationPrompts:
    """内容创作提示词集合"""
    
    # 版本信息
    version: str = "1.0.0"
    
    @staticmethod
    def get_system_prompt(genre: str = "") -> str:
        """
        获取内容创作的 system prompt（基础部分）
        
        Args:
            genre: 题材名称
        """
        genre_hint = f"，专注于{genre}题材" if genre else ""
        
        base_prompt = f"""你是一位经验丰富的小说作家{genre_hint}。请根据提供的章节规划、世界观设定和人物设定，创作符合当前题材风格的章节内容。

创作要求：
1. 语言生动流畅，描写具体细腻，避免空洞的形容词堆砌
2. 对话自然真实，符合人物性格，不要用对话塞满全部信息
3. 情节推进合理，节奏张弛有度，保持阅读吸引力
4. 场景描写要有画面感和细节感
5. 注意段落分隔，便于阅读
6. 开头要有抓力，结尾要有悬念或情绪余味
7. 综合使用场景描写、对话、心理描写、动作描写等多种手法"""
        
        # 添加题材专属指导
        genre_guide = GENRE_CREATION_GUIDES.get(genre, "")
        if genre_guide:
            base_prompt += f"""

【题材专属细化】（以下为通用要求的具体落地方式，请结合使用）
{genre_guide}"""
        
        # 添加质量标准和输出格式
        base_prompt += """

【质量标准】
- ✅ 与前面章节的情节连贯一致
- ✅ 人物性格和行为符合已有描写
- ✅ 遵循已建立的世界观规则和设定
- ✅ 延续已有的叙事风格和文笔特点
- ✅ 推进主线情节，避免原地踏步
- ✅ 注重细节的合理性和真实感

【输出格式要求】⚠️
请直接输出章节内容，格式必须如下：

第X章 章节标题

章节正文内容...

注意：
- 第一行必须是章节标题，格式为"第X章 标题名称"（X为章节数字）
- 章节标题要简洁有力，能概括本章核心内容或悬念
- 不要包含任何额外的说明文字、作者话语等"""
        
        return base_prompt

    @staticmethod
    def get_user_prompt_template() -> str:
        """获取内容创作的 user prompt 模板"""
        return """请创作第{chapter_number}章内容：

【章节规划】⭐⭐⭐（核心指导，请严格遵循）
{chapter_plan}

【前一章结尾】⭐⭐（保持连贯）
{previous_ending}

【RAG检索-人物细节】
{rag_character_context}

【RAG检索-世界设定细节】
{rag_world_context}

【目标字数】约{target_words}字

【本章开头方式】⚠️ 必须使用【{opening_style}】
- 技巧：{opening_technique}
- 示例：{opening_example}

【本章结尾方式】⚠️ 必须使用【{ending_style}】
- 技巧：{ending_technique}
- 示例：{ending_example}

请开始创作第{chapter_number}章内容："""

    @staticmethod
    def build_user_prompt(
        chapter_number: int,
        chapter_plan: str,
        previous_ending: str,
        rag_character_context: str,
        rag_world_context: str,
        selected_opening: Tuple[str, str, str],
        selected_ending: Tuple[str, str, str],
        target_words: int = 3000
    ) -> str:
        """
        构建完整的 user prompt
        
        Args:
            chapter_number: 章节编号
            chapter_plan: 章节规划
            previous_ending: 前一章结尾
            rag_character_context: RAG人物上下文
            rag_world_context: RAG世界观上下文
            selected_opening: 开头方式 (名称, 技巧, 示例)
            selected_ending: 结尾方式 (名称, 技巧, 示例)
            target_words: 目标字数
        
        Returns:
            完整的 user prompt
        """
        return ContentCreationPrompts.get_user_prompt_template().format(
            chapter_number=chapter_number,
            chapter_plan=chapter_plan,
            previous_ending=previous_ending if previous_ending else '（这是第一章，请设计一个引人入胜的开场）',
            rag_character_context=rag_character_context if rag_character_context else '（无额外人物细节）',
            rag_world_context=rag_world_context if rag_world_context else '（无额外设定细节）',
            target_words=target_words,
            opening_style=selected_opening[0],
            opening_technique=selected_opening[1],
            opening_example=selected_opening[2],
            ending_style=selected_ending[0],
            ending_technique=selected_ending[1],
            ending_example=selected_ending[2]
        )


# 题材专属创作指导
GENRE_CREATION_GUIDES: Dict[str, str] = {
    "修仙": """【修仙题材创作指导】
- 境界突破要有天劫、灵光、气息变化等具体表现
- 战斗描写用具体招式替代"剑光如虹"等空洞词汇
- 修炼场景用身体反应替代"感受到力量澎湃"
- 对话可融入修真术语，但不必文绉绉""",

    "玄幻": """【玄幻题材创作指导】
- 血脉觉醒要有异象、灵魂震动等具体表现
- 战斗描写注重武技动作细节
- 神器与主角的羁绊要有情感置入
- 跨位面/跨域时描写环境差异""",

    "都市": """【都市题材创作指导】
- 商业谈判要有策略博弈细节
- 打脸场景需要铺垫和围观者反应
- 财富数字要具体，让读者有概念
- 情感线自然穿插，避免生硬""",

    "悬疑": """【悬疑题材创作指导】
- 线索埋设要自然，避免强行插入
- 推理过程要逻辑严密
- 气氛营造注重细节描写
- 反转前要有足够的误导和铺垫""",

    "言情": """【言情题材创作指导】
- 心动时刻用细节展现（心跳、脸红、视线）
- 甜蜜互动要有新意，避免套路
- 男主护短场景要有强势感
- 误会要合理，读者能理解""",

    "耽美": """【耽美题材创作指导】
- 性向认知过程要自然
- 攻受互动符合人设
- 突破暧昧边界的时刻要细腻
- 符合平台尺度要求""",

    "科幻": """【科幻题材创作指导】
- 科技描写要有体系感，避免魔法化
- 星际战斗注重战术和视觉冲击
- 外星种族要有独特文化特征
- 人性光辉与科技感并重""",

    "纯文学": """【纯文学题材创作指导】
- 注重内心独白和心理描写
- 环境描写可诗意化，营造氛围
- 象征手法自然融入
- 结局可留白，引发思考"""
}


# 开头方式定义
OPENING_STYLES: Dict[str, Tuple[str, str, str]] = {
    "对话开头": ("对话开头", "直接进入冲突或紧张场景", "'站住！'身后传来一声厉喝。"),
    "动作开头": ("动作开头", "正在发生的动态事件", "刀光闪过，血珠在空中划出一道弧线。"),
    "悬念开头": ("悬念开头", "抛出问题，引发好奇", "三天后回想起这个决定时，她依然后悔不已。"),
    "场景开头": ("场景开头", "氛围渲染，快速建立情境", "暴雨倾盆，整个长安城笼罩在一片灰蒙蒙的水雾中。"),
    "反转开头": ("反转开头", "与上章结尾形成对比或反差", "然而他睁开眼时，发现自己躺在一张软榻上。"),
}

# 结尾方式定义
ENDING_STYLES: Dict[str, Tuple[str, str, str]] = {
    "悬念式": ("悬念式", "关键信息揭露一半", "信封里只有一张纸，上面写着三个字——"),
    "转折式": ("转折式", "意外事件发生", "就在她以为一切结束时，门外响起了敲门声。来人是——"),
    "动作中断式": ("动作中断式", "危机时刻戛然而止", "刀锋距离她的咽喉只有一寸。她闭上眼睛——"),
    "信息炸弹式": ("信息炸弹式", "惊人真相揭露", "'你以为我是谁？'他摘下面具，露出一张与她父亲一模一样的脸。"),
    "选择困境式": ("选择困境式", "主角面临艰难抉择", "救左边的师父，还是右边的爱人？她只有三秒钟做出决定。"),
}

# 情节类型 → 推荐的开头/结尾方式
SCENE_STYLE_RULES: Dict[str, Dict] = {
    "战斗": {"keywords": ["战斗", "打斗", "厮杀", "对决", "交手", "出招", "攻击", "防御", "刀剑", "拳脚"],
            "opening": "动作开头", "ending": "动作中断式"},
    "悬疑": {"keywords": ["悬疑", "推理", "谜团", "线索", "真相", "秘密", "调查", "疑点", "隐情", "身世"],
            "opening": "悬念开头", "ending": "悬念式"},
    "转折": {"keywords": ["转折", "揭秘", "真相大白", "身份", "背叛", "反转", "意外", "惊人", "原来", "竟然"],
            "opening": "反转开头", "ending": "信息炸弹式"},
    "情感": {"keywords": ["告别", "离别", "重逢", "表白", "感情", "思念", "回忆", "温情", "感动", "眼泪"],
            "opening": "场景开头", "ending": "选择困境式"},
    "危机": {"keywords": ["危机", "危险", "生死", "逃亡", "追杀", "困境", "绝境", "险境", "紧急", "千钧一发"],
            "opening": "动作开头", "ending": "动作中断式"},
    "对话": {"keywords": ["谈判", "对话", "交涉", "质问", "争执", "辩论", "说服", "威胁", "警告", "摊牌"],
            "opening": "对话开头", "ending": "转折式"},
    "日常": {"keywords": ["日常", "休息", "准备", "旅途", "修炼", "学习", "训练", "恢复", "整顿", "计划"],
            "opening": "场景开头", "ending": "悬念式"},
    "升级": {"keywords": ["突破", "升级", "进阶", "觉醒", "获得", "传承", "机缘", "宝物", "功法", "神通"],
            "opening": "悬念开头", "ending": "信息炸弹式"},
}


def match_scene_type(chapter_plan: str) -> Optional[str]:
    """
    根据章节规划匹配情节类型
    
    Args:
        chapter_plan: 章节规划内容
    
    Returns:
        匹配的情节类型名称，如无匹配返回 None
    """
    matched_scene_type = None
    max_keyword_count = 0
    
    for scene_type, rule in SCENE_STYLE_RULES.items():
        keyword_count = sum(1 for kw in rule["keywords"] if kw in chapter_plan)
        if keyword_count > max_keyword_count:
            max_keyword_count = keyword_count
            matched_scene_type = scene_type
    
    if max_keyword_count >= 1:
        return matched_scene_type
    return None


def get_recommended_styles(
    chapter_plan: str,
    chapter_number: int
) -> Tuple[Tuple[str, str, str], Tuple[str, str, str], str]:
    """
    获取推荐的开头/结尾方式
    
    Args:
        chapter_plan: 章节规划内容
        chapter_number: 章节编号
    
    Returns:
        (开头方式, 结尾方式, 匹配方法描述)
    """
    matched_scene_type = match_scene_type(chapter_plan)
    
    if matched_scene_type:
        rule = SCENE_STYLE_RULES[matched_scene_type]
        selected_opening = OPENING_STYLES[rule["opening"]]
        selected_ending = ENDING_STYLES[rule["ending"]]
        match_method = f"关键词匹配({matched_scene_type}场景)"
    else:
        # 回退到章节编号轮换
        opening_list = list(OPENING_STYLES.values())
        ending_list = list(ENDING_STYLES.values())
        opening_index = (chapter_number - 1) % len(opening_list)
        ending_index = (chapter_number + 2) % len(ending_list)
        selected_opening = opening_list[opening_index]
        selected_ending = ending_list[ending_index]
        match_method = "章节编号轮换(未匹配到关键词)"
    
    return selected_opening, selected_ending, match_method


def get_genre_creation_guide(genre: str) -> str:
    """获取题材专属创作指导"""
    return GENRE_CREATION_GUIDES.get(genre, "")

class FirstChapterPrompts:
    """第1章创作提示词（用于agent_coordinator的阶段3）"""
    
    @staticmethod
    def get_first_chapter_prompt(
        plot_outline: str,
        concept: str,
        world_setting: str,
        characters: str,
        target_words: int = 2500
    ) -> str:
        """
        获取第1章创作的 user prompt
        
        Args:
            plot_outline: 情节大纲（截断至500字）
            concept: 故事概念（截断至300字）
            world_setting: 世界观设定（截断至200字）
            characters: 人物设定（截断至200字）
            target_words: 目标字数
        
        Returns:
            完整的第1章创作 user prompt
        """
        return f"""请根据提供的情节大纲、世界观设定和人物设定，创作精彩的第1章内容。

【结构大纲】
{plot_outline}

【故事概念】
{concept}

【世界观设定】
{world_setting}

【主要人物】
{characters}

【创作要求】
1. **语言风格**：语言生动，描写细腻，符合网文风格
2. **对话要求**：对话自然，符合人物性格
3. **情节节奏**：情节紧凑，引人入胜，注意爽点节奏
4. **场景描写**：场景描写要有画面感
5. **段落分隔**：注意段落分隔，便于阅读
6. **开篇建立**：第一章要快速建立世界观和主角形象
7. **多种手法**：使用场景描写、对话、心理描写等多种手法

【质量标准】
- ✅ 人物性格和行为符合设定
- ✅ 遵循已建立的世界观规则
- ✅ 注重细节的合理性和真实感
- ✅ 开头要有吸引力，结尾要有悬念

【禁止事项】
❌ 禁止使用：用"XXX醒来/睁开眼睛/阳光照进房间"开头
❌ 禁止使用：总结式内心独白 + 对未来的展望（如"他知道，从这一刻起..."）

【目标字数】约{target_words}字

请开始创作第1章内容，直接输出章节正文，不要包含任何额外的说明文字。"""
