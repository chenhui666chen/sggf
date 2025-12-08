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
        """构建章节创作的 system prompt（目前仅使用通用模板）。"""
        # 暂时直接复用 workflow.py 中的通用 system prompt 文本
        # 后续如需在此注入题材专属章节指导，再从 self.genre_module 中读取
        return (
            "你是一位经验丰富的小说作家。请根据提供的章节规划、世界观设定和人物设定，"
            "创作符合当前题材风格的章节内容。\n\n"
            "创作要求：\n"
            "1. 语言生动流畅，描写具体细腻，避免空洞的形容词堆砌\n"
            "2. 对话自然真实，符合人物性格，不要用对话塞满全部信息\n"
            "3. 情节推进合理，节奏张弛有度，保持阅读吸引力\n"
            "4. 场景描写要有画面感和细节感\n"
            "5. 注意段落分隔，便于阅读\n"
            "6. 开头要有抓力，结尾要有悬念或情绪余味\n"
            "7. 综合使用场景描写、对话、心理描写、动作描写等多种手法\n\n"
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
            "- 不要包含任何额外的说明文字、作者话语等"
        )

    def build_user_prompt(
        self,
        next_chapter_number: int,
        optimized_context: Dict[str, str],
        chapter_plan: str,
        plot_outline: str,
        world_setting: str,
        characters: str,
        previous_ending: str,
        previous_chapters_analysis: str,
        rag_character_context: str,
        rag_world_context: str,
        selected_opening: Tuple[str, str, str],
        selected_ending: Tuple[str, str, str],
    ) -> str:
        """构建章节创作的 user prompt（与当前 workflow 逻辑保持一致）。"""
        return f"""请创作第{next_chapter_number}章内容：

【章节规划】
{optimized_context.get('chapter_plan', chapter_plan)}

【世界观设定】
{optimized_context.get('world_setting', world_setting)}

【人物设定】
{optimized_context.get('characters', characters)}

【RAG检索-人物（自动注入）】
{rag_character_context if rag_character_context else '（无）'}

【RAG检索-世界设定（自动注入）】
{rag_world_context if rag_world_context else '（无）'}

【情节大纲】
{optimized_context.get('plot_outline', plot_outline)}

【前一章结尾】
{optimized_context.get('previous_ending', previous_ending) if previous_ending else '（这是第一章，请设计一个引人入胜的开场）'}

【前序章节信息】
{optimized_context.get('previous_chapters_analysis', previous_chapters_analysis)}

【目标字数】约3000字

【本章开头方式 - 强制要求】⚠️
本章必须使用【{selected_opening[0]}】方式开头！
- 技巧说明：{selected_opening[1]}
- 参考示例：{selected_opening[2]}

【本章结尾方式 - 强制要求】⚠️
本章必须使用【{selected_ending[0]}】结尾！
- 技巧说明：{selected_ending[1]}
- 参考示例：{selected_ending[2]}

请开始创作第{next_chapter_number}章内容："""
