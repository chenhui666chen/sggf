"""
章节规划阶段提示词模块

从 workflow.py 提取的章节规划相关提示词
"""

from typing import Dict, Optional
from dataclasses import dataclass

from app.services.prompts.genre_registry import (
    get_genre_chapter_plan_guide as _get_genre_chapter_plan_guide,
    resolve_genre,
)


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

- 章节定位：普通推进 / 开篇定调 / 小高潮 / 大高潮 / 关键转折 / 伏笔回收 / 人物突破 / 世界观揭示 / 卷末收束 / 完结收束
- 场景目标：...
- 冲突设计：...
- 关键事件：
  1. ...
  2. ...
- 涉及人物：...
- 人物推进：...
- 情节作用：...
- 结尾钩子：...
- 爽点类型：...（如无明显爽点可写“无”）
- 伏笔事项：...（如无则写“无”）

---

要求：
- 确保与整本书的情节大纲保持一致
- 确保与前面章节的剧情连贯
- 推进故事发展，不能原地踏步
- 爽点和钩子必须具体、可执行
- 章节定位必须从给定枚举中选择一个，不要自造标签
- 关键事件必须功能互斥：同一说服、拒绝、揭示、问责、接令等功能节拍只安排一个场景，多个事件不得重复承担同一叙事功能
- 关键事件中每个重要结果（追踪、反制、识破、传递）都要注明其达成手段；无手段支撑的结果不得写入规划
- 若上一章结尾存在未解除的即时危机（追兵逼近、对峙中、倒计时进行），本章规划必须把危机的闭合或过渡（脱身、转移、化解）列为首个关键事件并注明手段，不得直接从危机之后起笔
- 主角未完成的常驻任务与目标（寻人、解谜、复仇、交易等）须在关键事件中推进，或注明本章搁置的原因（如"本章暂无接触渠道"），不得无声跳过
- 章节定位必须与关键事件的实质内容匹配：定位为"关键转折"的章节，关键事件中必须包含主线任务本身的实质变化（新线索、新代价、关系重组、目标变更），仅有空间转移或阵营变更不足以支撑"关键转折"定位——此类内容应定位为"普通推进"或"伏笔回收"
- "人物推进"中安排了具体任务的具名配角，必须同时列入关键事件，确保其出场与任务在正文中有着落（不得只写人物关系却不给事件落点）
- 爽点与破局手段不得临时扩容既有规则、法条、制度的适用范围；引用规则须与大纲和前文已确立的用法一致，新用法须先在前文或本章事件中建立依据
- 规划引用的人物状态（受伤、被囚、失踪、持有物）必须与前文正文一致；新增的状态变化须注明"本章交代来源"；身负强制状态（死囚、重伤、被通缉）的角色不得安排与其状态冲突的行动（如死囚被私自带走）
- 上一章遗留的人物身体状态（伤势、力竭、药物效果、异能消耗、中毒）必须写入关键事件：或影响本章行动（疼痛干扰、体力受限、药效递减），或显式交代处置（治疗、休息、服药）；不得无声恢复满状态
- 情节大纲中标注于后续章节的核心爆点信息（如"第N章揭示XX真相"），本章规划不得提前完整引爆；本章触及时只可模糊铺垫或部分揭示，完整揭示保留到大纲指定章节——提前引爆会抽空后续章节的悬念支撑
- 前一章结尾悬置的"抉择"（取/舍、进/退、暴露/隐匿）必须作为本章首个关键事件兑现为明确选择并写出代价，不得用纯逃亡、跳过或时间跳跃回避选择
- 前一章结尾的钩子/悬念必须在规划中显式安排回应（推进、升级、部分揭示或标注悬置原因）；前章末尾点名的威胁人物本章须有着落（出场、被感知、被提及或主角对其的心理评估），不得无声消失
- 脱身、反制、追踪类场景须安排至少一个才智型手段（地形误导、伪造痕迹、借力打力、预判设伏），不得只靠体力逃亡或运气脱险
- 连续两章以上未推进的配角线与次级伏笔，本章须安排一次轮转（推进、提及或显式标注搁置原因），不得长期悬置"""

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


def get_genre_chapter_plan_guide(genre: str) -> str:
    """获取题材专属章节规划指导（委托给 genre_registry）"""
    return _get_genre_chapter_plan_guide(genre)


def get_climax_instruction(chapter_number: int, chapter_outline: str = "") -> str:
    """
    获取高潮章节指示（大纲节奏优先）

    优先依据本章细纲自带的节奏标注（章节定位 / 爽点强度 / 情节作用）生成指示，
    避免与大纲层精心设计的爽点节奏互相打架；
    仅当细纲缺失或无任何节奏标注时，才回退到"约每5章小高潮、每25章大高潮"
    的经验节奏，并明确声明以大纲为准。

    Args:
        chapter_number: 章节编号
        chapter_outline: 本章细纲文本（来自情节大纲的当前章节块）

    Returns:
        高潮章节指示字符串，非高潮章返回空字符串
    """
    outline_text = (chapter_outline or "").strip()

    if outline_text:
        # 大纲驱动：按细纲中的节奏标注判断本章定位
        major_markers = ("大高潮", "爆爽", "卷末收束", "完结收束", "终局对决")
        minor_markers = ("小高潮", "中爽", "小爽", "爆点前置", "爆点")

        if any(marker in outline_text for marker in major_markers):
            return f"""
⚠️ 【大高潮章节】第{chapter_number}章按大纲节奏为爆点章，需要：
- 设计一个让读者拍案叫绝的大爽点
- 本阶段主要矛盾要有阶段性解决
- 为后续剧情埋下新的悬念"""
        if any(marker in outline_text for marker in minor_markers):
            return f"""
⚠️ 【小高潮章节】第{chapter_number}章按大纲节奏需要设计一个明确的爽点：
- 可以是：打脸嘲讽者/突破升级/获得宝物/反转翻盘/装逼成功
- 爽点类型以细纲中标注的爽点类型为准"""

        # 细纲存在但无节奏标注：不注入硬性节奏指令，交由规划器按大纲自行判断
        return ""

    # 回退：无细纲时的经验节奏（若与大纲冲突，以大纲为准）
    is_major_climax = chapter_number % 25 == 0   # 每25章一个大高潮
    is_climax_chapter = chapter_number % 5 == 0  # 每5章一个小高潮

    if is_major_climax:
        return f"""
⚠️ 【卷末大高潮章节】第{chapter_number}章按经验节奏为本卷结尾，需要：
- 设计一个让读者拍案叫绝的大爽点
- 本卷主要矛盾要有阶段性解决
- 为下一卷埋下新的悬念
- 此为无细纲时的经验节奏，若与大纲节奏冲突，以大纲为准"""
    elif is_climax_chapter:
        return f"""
⚠️ 【小高潮章节】第{chapter_number}章按经验节奏需要设计一个明确的爽点：
- 可以是：打脸嘲讽者/突破升级/获得宝物/反转翻盘/装逼成功
- 此为无细纲时的经验节奏，若与大纲节奏冲突，以大纲为准"""

    return ""
