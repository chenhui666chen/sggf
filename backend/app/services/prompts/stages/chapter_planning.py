"""
章节规划阶段提示词模块

从 workflow.py 提取的章节规划相关提示词
"""

from typing import Dict, Optional
from dataclasses import dataclass


@dataclass
class ChapterPlanningPrompts:
    """章节规划提示词集合"""
    
    # 版本信息
    version: str = "1.0.0"
    
    @staticmethod
    def get_system_prompt(genre: str = "") -> str:
        """
        获取章节规划的 system prompt
        
        Args:
            genre: 题材名称
        """
        genre_hint = f"，专注于{genre}题材" if genre else ""
        
        return f"""你是一位资深的小说策划编辑{genre_hint}，擅长章节规划和节奏把控。
你的职责是根据整体大纲，为每一章制定详细的创作计划，确保：
- 情节推进合理有序
- 节奏张弛有度
- 伏笔和钩子安排得当
- 与前文保持连贯

请严格按照提供的结构输出章节规划。"""

    @staticmethod
    def get_user_prompt_template() -> str:
        """获取章节规划的 user prompt 模板"""
        return """请为第{chapter_number}章制定详细的创作计划。

【整体情节大纲】
{plot_outline}

【世界观设定摘要】
{world_setting_summary}

【人物设定摘要】
{characters_summary}

【前序章节分析】（最近3章）
{previous_analysis}

【前一章结尾】
{previous_ending}

请按以下结构输出本章规划：

## 1. 本章定位
- 在整体故事中的位置和作用
- 与前一章的衔接点

## 2. 核心事件
- 本章必须发生的主要事件
- 情节推进要点

## 3. 人物安排
- 出场人物及其戏份分配
- 人物关系发展

## 4. 爽点设计
- 爽点类型（获宝/突破/打脸/反转等）
- 爽点强度（⭐~⭐⭐⭐⭐）
- 实现方式和铺垫

## 5. 情绪曲线
- 情绪走势：（如：紧张→释放→悬疑）
- 关键情绪转折点

## 6. 场景设计
- 主要场景描述
- 时间、地点、氛围
- 场景转换节点

---

要求：
- 确保与整本书的情节大纲保持一致
- 确保与前面章节的剧情连贯
- 推进故事发展，不能原地踏步
- 爽点和钩子必须具体、可执行"""

    @staticmethod
    def build_user_prompt(
        chapter_number: int,
        plot_outline: str,
        world_setting_summary: str,
        characters_summary: str,
        previous_analysis: str,
        previous_ending: str,
        genre_guide: str = ""
    ) -> str:
        """
        构建完整的 user prompt
        
        Args:
            chapter_number: 章节编号
            plot_outline: 情节大纲
            world_setting_summary: 世界观摘要
            characters_summary: 人物摘要
            previous_analysis: 前序章节分析
            previous_ending: 前一章结尾
            genre_guide: 题材专属指导
        
        Returns:
            完整的 user prompt
        """
        base_prompt = ChapterPlanningPrompts.get_user_prompt_template().format(
            chapter_number=chapter_number,
            plot_outline=plot_outline or "（暂无情节大纲）",
            world_setting_summary=world_setting_summary or "（暂无世界观摘要）",
            characters_summary=characters_summary or "（暂无人物摘要）",
            previous_analysis=previous_analysis or "（这是第一章）",
            previous_ending=previous_ending or "（这是第一章）"
        )
        
        # 添加题材专属指导
        if genre_guide and genre_guide.strip():
            base_prompt += f"""
【题材专属细化】（以下为通用规划要求的具体落地方式，请结合使用）
{genre_guide}"""
        
        return base_prompt


# 题材专属章节规划指导（从 agent_coordinator.py 迁移）
GENRE_CHAPTER_PLAN_GUIDES: Dict[str, str] = {
    "修仙": """## 🔮 修仙题材规划要点

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
- 人物对话可融入修真术语""",

    "玄幻": """## ⚡ 玄幻题材规划要点

**力量与血脉系统**：
- 明确主角当前等级及血脉觉醒度
- 越级战斗要有支撑（武技/神器/血脉能力）
- 标注进度：距离下一次质变还有多远

**爽点类型侧重**：
- 优先考虑：血脉觉醒/越级战/打脸/神器认主
- 每3-5章一个小爽点
- 每15-20章一个大爽点（等级跨越/血脉突破）

**玄幻特色元素**：
- 战斗场面要有视觉冲击力
- 血脉能力逐步解锁
- 可安排追随者收服情节""",

    "都市": """## 🏙️ 都市题材规划要点

**商业与权力系统**：
- 明确主角当前资产/地位
- 商战要有策略博弈
- 标注进度：距离下一个商业目标还有多远

**爽点类型侧重**：
- 优先考虑：商战胜利/打脸装X/财富跨越/美女青睐
- 每3-5章一个小爽点（小打脸/小收获）
- 每15-20章一个大爽点（重大商战胜利/地位跃升）

**都市特色元素**：
- 现实逻辑要合理
- 财富数字要具体
- 人脉关系要清晰""",

    "悬疑": """## 🔍 悬疑题材规划要点

**信息与真相系统**：
- 明确本章揭露/隐藏哪些线索
- 推理过程要逻辑严密
- 标注进度：距离真相揭露还有多少步

**触发点类型侧重**：
- 优先考虑：发现线索/推理突破/真相反转/身份揭露
- 每3-5章埋设或回收一个线索
- 每卷结尾一次重大真相揭露

**悬疑特色元素**：
- 气氛营造要到位
- 误导要自然合理
- 反转要有足够铺垫""",

    "言情": """## 💕 言情题材规划要点

**情感与关系系统**：
- 明确男女主当前情感阶段
- 感情发展要自然有节奏
- 标注进度：距离下一个情感里程碑还有多远

**爽点类型侧重**：
- 优先考虑：心动时刻/甜蜜互动/男主护短/误会解开
- 每2-3章一个小甜点
- 每10-15章一个大甜点（表白/确定关系/重大进展）

**言情特色元素**：
- 细节描写要细腻
- 心理活动要丰富
- 配角要有存在感但不抢戏""",

    "耽美": """## 🌈 耽美题材规划要点

**情感与认知系统**：
- 明确双方当前情感阶段和性向认知
- 感情发展要细腻自然
- 标注进度：距离下一个情感里程碑还有多远

**爽点类型侧重**：
- 优先考虑：暧昧张力/突破边界/表白/互诉心意
- 每2-3章一个小甜点或心动时刻
- 每10-15章一个大进展

**耽美特色元素**：
- 攻受互动符合人设
- 心理描写要细腻
- 符合平台尺度要求""",

    "科幻": """## 🚀 科幻题材规划要点

**科技与战力系统**：
- 明确当前科技等级/机甲等级/舰队规模
- 科技突破要合理（研究/遗迹/传承）
- 标注进度：距离下一次技术跳跃还有多远

**爽点类型侧重**：
- 优先考虑：科技碾压/机甲战/舰队战/遗迹发现
- 每5-10章完成一次探索/战斗
- 每15-25章一次技术跳跃

**科幻特色元素**：
- 星际设定要严谨有体系
- 种族/文明冲突要有层次
- 科技感与人性光辉并重""",

    "纯文学": """## 📖 纯文学题材规划要点

**精神与成长系统**：
- 明确主角当前精神状态和价值观
- 成长变化要细腻渐进
- 标注进度：距离下一个精神转折点还有多远

**触动点类型侧重**：
- 优先考虑：顿悟时刻/情感共鸣/诗意时刻/残酷真相
- 每10-20章一个精神转折点
- 允许大段环境/心理描写

**纯文学特色元素**：
- 注重氛围营造
- 象征手法自然融入
- 结局可留白引发思考"""
}


def get_genre_chapter_plan_guide(genre: str) -> str:
    """获取题材专属章节规划指导"""
    return GENRE_CHAPTER_PLAN_GUIDES.get(genre, "")


def get_climax_instruction(chapter_number: int) -> str:
    """
    获取高潮章节指示
    
    Args:
        chapter_number: 章节编号
    
    Returns:
        高潮章节指示字符串，如非高潮章返回空字符串
    """
    is_major_climax = chapter_number % 25 == 0   # 每25章一个大高潮
    is_climax_chapter = chapter_number % 5 == 0  # 每5章一个小高潮
    
    if is_major_climax:
        return f"""
⚠️ 【卷末大高潮章节】第{chapter_number}章是本卷结尾，需要：
- 设计一个让读者拍案叫绝的大爽点
- 本卷主要矛盾要有阶段性解决
- 为下一卷埋下新的悬念"""
    elif is_climax_chapter:
        return f"""
⚠️ 【小高潮章节】第{chapter_number}章需要设计一个明确的爽点：
- 可以是：打脸嘲讽者/突破升级/获得宝物/反转翻盘/装逼成功"""
    
    return ""
