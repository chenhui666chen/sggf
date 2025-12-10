from typing import Dict, Any, Tuple

from .agent_coordinator import GENRE_PROMPT_MODULES, DEFAULT_GENRE_MODULE


class ChapterPromptBuilder:
    """章节创作提示词组装器

    负责根据通用规则 + 题材模块，组装 system_prompt 和 user_prompt
    当前仅实现通用骨架，后续可继续注入题材专属章节指导
    """

    def __init__(self, genre: str = "") -> None:
        self.genre = genre or ""
        self.genre_module: Dict[str, Any] = GENRE_PROMPT_MODULES.get(self.genre, DEFAULT_GENRE_MODULE)

    def build_system_prompt(self) -> str:
        """构建章节创作的 system prompt（题材自适应版）。"""
        
        # 🆕 题材专属创作指导
        genre_creation_guides = {
            "修仙": """
【修仙题材创作指导】
- 境界突破要有天劫、灵光、气息变化等具体表现
- 战斗描写用具体招式替代"剑光如虹"等空洞词汇
- 修炼场景用身体反应替代"感受到力量澎湃"
- 对话可融入修真术语，但不必文绉绉
""",
            "玄幻": """
【玄幻题材创作指导】
- 血脉觉醒要有异象、灵魂震动等具体表现
- 战斗描写注重武技动作细节
- 神器与主角的羁绊要有情感置入
- 跨位面/跨域时描写环境差异
""",
            "都市": """
【都市题材创作指导】
- 商业谈判要有策略博弈细节
- 打脸场景需要铺垫和围观者反应
- 财富数字要具体，让读者有概念
- 情感线自然穿插，避免生硬
""",
            "悬疑": """
【悬疑题材创作指导】
- 线索埋设要自然，避免强行插入
- 推理过程要逻辑严密
- 气氛营造注重细节描写
- 反转前要有足够的误导和铺垫
""",
            "言情": """
【言情题材创作指导】
- 心动时刻用细节展现（心跳、脸红、视线）
- 甜蜜互动要有新意，避免套路
- 男主护短场景要有强势感
- 误会要合理，读者能理解
""",
            "耽美": """
【耽美题材创作指导】
- 性向认知过程要自然
- 攻受互动符合人设
- 突破暗昧边界的时刻要细腻
- 符合平台尺度要求
""",
            "科幻": """
【科幻题材创作指导】
- 科技描写要有体系感，避免魔法化
- 星际战斗注重战术和视觉冲击
- 外星种族要有独特文化特征
- 人性光辉与科技感并重
""",
            "纯文学": """
【纯文学题材创作指导】
- 注重内心独白和心理描写
- 环境描写可诗意化，营造氛围
- 象征手法自然融入
- 结局可留白，引发思考
"""
        }
        
        # 获取题材专属指导
        genre_guide = genre_creation_guides.get(self.genre, "")
        genre_hint = f"，专注于{self.genre}题材" if self.genre else ""
        
        base_prompt = (
            f"你是一位经验丰富的小说作家{genre_hint}。请根据提供的章节规划、世界观设定和人物设定，"
            "创作符合当前题材风格的章节内容。\n\n"
            "创作要求：\n"
            "1. 语言生动流畅，描写具体细腻，避免空洞的形容词堆砌\n"
            "2. 对话自然真实，符合人物性格，不要用对话塞满全部信息\n"
            "3. 情节推进合理，节奏张弛有度，保持阅读吸引力\n"
            "4. 场景描写要有画面感和细节感\n"
            "5. 注意段落分隔，便于阅读\n"
            "6. 开头要有抓力，结尾要有悬念或情绪余味\n"
            "7. 综合使用场景描写、对话、心理描写、动作描写等多种手法\n\n"
        )
        
        # 添加题材专属指导（作为通用要求的细化补充）
        if genre_guide:
            base_prompt += "\n【题材专属细化】（以下为通用要求的具体落地方式，请结合使用）\n" + genre_guide + "\n"
        
        base_prompt += (
            "【质量标准】\n"
            "- ✅ 与前面章节的情节连贯一致\n"
            "- ✅ 人物性格和行为符合已有描写\n"
            "- ✅ 遵循已建立的世界观规则和设定\n"
            "- ✅ 延续已有的叙事风格和文笔特点\n"
            "- ✅ 推进主线情节，避免原地踏步\n"
            "- ✅ 注重细节的合理性和真实感\n\n"
            "【输出格式要求】⚠️\n"
            "请直接输出章节内容，格式必须如下：\n\n"
            "第X章 章节标题\n\n"
            "章节正文内容...\n\n"
            "注意：\n"
            "- 第一行必须是章节标题，格式为\"第X章 标题名称\"（X为章节数字）\n"
            "- 章节标题要简洁有力，能概括本章核心内容或悬念\n"
            "- 不要包含任何额外的说明文字、作者话语等\n\n"
            "【严禁出现的格式】❌\n"
            "- ❌ 禁止使用\"第一节\"、\"第二节\"等小节标题划分内容\n"
            "- ❌ 禁止使用\"结尾钩子\"、\"开篇\"、\"高潮\"等结构性标记\n"
            "- ❌ 禁止使用\"【场景一】\"、\"【转折点】\"等大纲式标注\n"
            "- ❌ 禁止在正文中保留任何规划痕迹（如\"本节要点\"、\"情节推进\"）\n"
            "- 输出应该是可以直接发表的小说正文，不是大纲或创作笔记"
        )
        
        return base_prompt

    def build_user_prompt(
        self,
        next_chapter_number: int,
        chapter_plan: str,
        previous_ending: str,
        rag_character_context: str,
        rag_world_context: str,
        selected_opening: Tuple[str, str, str],
        selected_ending: Tuple[str, str, str],
        # 以下参数保留向后兼容，但不再使用（章节规划已消化）
        optimized_context: Dict[str, str] = None,
        plot_outline: str = "",
        world_setting: str = "",
        characters: str = "",
        previous_chapters_analysis: str = "",
    ) -> str:
        """构建章节创作的 user prompt（精简版）
        
        优化逻辑：
        - 章节规划已消化情节大纲、世界观、人物、前序章节信息
        - 章节创作只需：章节规划 + 前一章结尾 + RAG补充 + 开头结尾方式
        - 移除冗余内容，减少 token 消耗约 60-70%
        """
        return f"""请创作第{next_chapter_number}章内容：

【章节规划】⭐⭐⭐（核心指导，请严格遵循）
{chapter_plan}

【前一章结尾】⭐⭐（保持连贯）
{previous_ending if previous_ending else '（这是第一章，请设计一个引人入胜的开场）'}

【RAG检索-人物细节】
{rag_character_context if rag_character_context else '（无额外人物细节）'}

【RAG检索-世界设定细节】
{rag_world_context if rag_world_context else '（无额外设定细节）'}

【目标字数】约3000字

【本章开头方式】⚠️ 必须使用【{selected_opening[0]}】
- 技巧：{selected_opening[1]}
- 示例：{selected_opening[2]}

【本章结尾方式】⚠️ 必须使用【{selected_ending[0]}】
- 技巧：{selected_ending[1]}
- 示例：{selected_ending[2]}

请开始创作第{next_chapter_number}章内容："""
