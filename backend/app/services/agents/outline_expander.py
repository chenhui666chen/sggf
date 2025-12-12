"""
情节大纲和人物扩展器 - 自动扩展简短大纲和增加人物数量
"""
from typing import Dict, Any, List, Optional
from .agents import CreativeDirectorAgent, PlotArchitectAgent, CharacterDesignerAgent
from .llm_singleton import create_deepseek_llm
from .knowledge_base import NovelKnowledgeBase
from .memory_manager import NovelMemoryManager
# 🎯 任务6：导入题材自适应模板系统
from .agent_coordinator import GENRE_PROMPT_MODULES, DEFAULT_GENRE_MODULE, REALM_SPAN_WARNING_THRESHOLD, REALM_SPAN_RECOMMEND_SUBDIVISION
# 🎆 引入分层摘要器
from .layered_summarizer import LayeredSummarizer


class OutlineExpander:
    """情节大纲和人物扩展器"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None,
                 genre: str = "",  # 🎯 任务6：添加题材参数
                 planned_chapters_max: int = 0):  # 🎯 任务6.1：添加章节数参数用于境界检查
        """初始化扩展器

        Args:
            knowledge_base: 知识库实例
            memory_manager: 记忆管理器实例
            genre: 题材类型（修仙、都市、悬疑等）
            planned_chapters_max: 规划的最大章节数
        """
        self.knowledge_base = knowledge_base or NovelKnowledgeBase()
        self.memory_manager = memory_manager or NovelMemoryManager()
        self.genre = genre  # 🎯 保存题材
        self.planned_chapters_max = planned_chapters_max

        # 初始化AI Agent
        self.creative_director = CreativeDirectorAgent(self.knowledge_base, self.memory_manager)
        self.plot_architect = PlotArchitectAgent(self.knowledge_base, self.memory_manager)
        self.character_designer = CharacterDesignerAgent(self.knowledge_base, self.memory_manager)

        # 🔔 为扩展大纲使用 qwen-long
        self.llm = create_deepseek_llm(task_type="outline_expand")
        
        # 🎆 初始化分层摘要器
        self.layered_summarizer = LayeredSummarizer(self.knowledge_base)
        
        # 🎯 任务6.3：获取题材专属Prompt模块
        self.genre_module = GENRE_PROMPT_MODULES.get(genre, DEFAULT_GENRE_MODULE)
        print(f"🎯 题材：{genre}，已加载专属Prompt模块")

    def count_chapters_in_outline(self, outline: str) -> int:
        """智能识别大纲中的章节数

        通过正则表达式和AI判断识别当前大纲有多少章

        Args:
            outline: 当前的情节大纲

        Returns:
            识别到的章节数
        """
        import re

        if not outline or outline.strip() == '':
            return 0

        # 方法1：正则表达式匹配
        # 匹配形如：“第N章”、“Chapter N”、“第N回”等
        patterns = [
            r'第(\d+)章',
            r'第(\d+)回',
            r'Chapter\s+(\d+)',
            r'第([一二三四五六七八九十百]+)章',  # 中文数字
        ]

        chapter_numbers = []
        for pattern in patterns:
            matches = re.findall(pattern, outline)
            chapter_numbers.extend(matches)

        if chapter_numbers:
            # 转换中文数字为阿拉伯数字
            chinese_nums = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}

            max_chapter = 0
            for num_str in chapter_numbers:
                try:
                    if num_str.isdigit():
                        max_chapter = max(max_chapter, int(num_str))
                    elif num_str in chinese_nums:
                        max_chapter = max(max_chapter, chinese_nums[num_str])
                except:
                    continue

            if max_chapter > 0:
                print(f"✅ 正则识别到章节数: {max_chapter}")
                return max_chapter

        # 方法2：如果正则没有匹配到，使用AI判断
        print("⚠️  正则无法识别章节数，使用AI判断...")

        ai_prompt = f"""请分析以下大纲有多少章。

【大纲】
{outline[:1000]}

请直接返回一个数字，代表识别到的章节数。
如果无法识别或大纲太简略无明确章节划分，返回0。

示例格式：
- 如果有第1章到第5章，返回：5
- 如果是简要描述无章节，返回：0

只返回数字，不要其他内容。"""

        try:
            ai_result = self.creative_director.process(ai_prompt, {})
            # 提取数字
            import re
            numbers = re.findall(r'\d+', ai_result)
            if numbers:
                chapter_count = int(numbers[0])
                print(f"✅ AI识别到章节数: {chapter_count}")
                return chapter_count
        except Exception as e:
            print(f"❌ AI识别失败: {e}")

        print("⚠️  无法识别章节数，默认返回0")
        return 0

    def check_realm_span_and_suggest(self) -> str:
        """🎯 任务6.1：修仙题材境界跨度检查和细分建议
        
        当修仙/玄幻题材的长篇小说超过500章时，建议将境界细分
        
        Returns:
            建议文本，如果不需要建议则返回空字符串
        """
        # 只对修仙/玄幻题材生效
        if self.genre not in ["修仙", "玄幻"]:
            return ""
        
        # 只对超过500章的长篇生效
        if self.planned_chapters_max < REALM_SPAN_WARNING_THRESHOLD:
            return ""
        
        # 生成建议文本
        suggestion = f"""

【🎯 修仙题材境界跨度优化建议】

⚠️ **检测到长篇小说**：本书规划约{self.planned_chapters_max}章，属于长篇作品

**境界细分建议**：
- 📉 **推荐境界跨度**：每个大境界约{REALM_SPAN_RECOMMEND_SUBDIVISION}章以内
- ❌ **避免单个境界超过{REALM_SPAN_WARNING_THRESHOLD}章**，否则会导致：
  1. 节奏拖沓，读者疑惑"为什么还不突破"
  2. 爽点单一，缺少境界跨越的震撑感
  3. 后期境界压缩，前后不均

**具体建议**：
1. **细分大境界**：将原本5个大境界细分为7-8个，例如：
   - 原：炼气 → 筑基 → 金丹 → 元婴 → 化神
   - 改：炼气 → 筑基 → 金丹 → 元婴 → 化神 → 炼虚 → 合体 → 渡劫

2. **增加小境界层次**：每个大境界内设置3-5个小境界（初期/中期/后期/大圆满）
   - 每10-30章一个小境界突破，增加爽点密度
   - 大境界突破作为卷末高潮

3. **增加特殊体质/功法升级线**：除境界外，增加其他提升线
   - 体质觉醒：普通 → 隐藏体质 → 神体觉醒
   - 功法进阶：黄阶 → 玄阶 → 地阶 → 天阶
   - 法宝成长：法器 → 灵器 → 宝器 → 仙器

请在生成大纲时，结合以上建议，确保境界提升节奏合理，爽点分布均匀。
"""
        
        print(f"🎯 境界跨度检查：长篇{self.planned_chapters_max}章，已添加细分建议")
        return suggestion

    def count_characters_in_text(self, characters_text: str) -> int:
        """智能识别人物文本中的人物数

        通过正则表达式和AI判断识别当前有多少个人物

        Args:
            characters_text: 当前的人物设定文本

        Returns:
            识别到的人物数
        """
        import re

        if not characters_text or characters_text.strip() == '':
            return 0

        # 方法1：正则表达式匹配 - 优化识别逻辑
        # 🔥 关键修复：排除标题性关键词，只匹配真实人物名

        # 匹配【姓名】格式（最常见的人物档案格式）
        bracket_names = re.findall(r'【姓名】[：:]\s*([\u4e00-\u9fa5]{2,4})', characters_text)

        if bracket_names:
            count = len(bracket_names)
            print(f"✅ 正则识别到人物数: {count} ({', '.join(bracket_names[:5])}...)")
            return count

        # 备用方案：匹配其他格式
        character_names = set()

        # 排除的关键词列表（这些不是人物名）
        exclude_keywords = [
            '人物', '角色', '主角', '配角', '对手', '支持', '新增', '完整',
            '列表', '档案', '体系', '关系', '分布', '阵营', '所有', '更新',
            '姓名', '年龄', '性别', '外貌', '性格', '背景', '动机', '能力',
            '弱点', '成长', '关键'
        ]

        # 匹配格式：
        # 1. 林墨、苏娜（顿号分隔）
        comma_names = re.findall(r'([\u4e00-\u9fa5]{2,4})、', characters_text)
        for name in comma_names:
            if name not in exclude_keywords and len(name) >= 2:
                character_names.add(name)

        # 2. 姓名：张三
        colon_names = re.findall(r'(?:姓名|角色)[：:]s*([\u4e00-\u9fa5]{2,4})', characters_text)
        for name in colon_names:
            if name not in exclude_keywords:
                character_names.add(name)

        # 3. **姓名** 或 **张三**
        bold_names = re.findall(r'\*\*([\u4e00-\u9fa5]{2,4})\*\*', characters_text)
        for name in bold_names:
            if name not in exclude_keywords and len(name) >= 2:
                character_names.add(name)

        if character_names:
            count = len(character_names)
            print(f"✅ 正则识别到人物数: {count} ({', '.join(list(character_names)[:5])}...)")
            return count

        # 方法2：如果正则没有匹配到，使用AI判断
        print("⚠️  正则无法识别人物数，使用AI判断...")

        ai_prompt = f"""请分析以下文本中有多少个具体的人物角色（有姓名的角色）。

【人物文本】
{characters_text[:1500]}

请统计有明确姓名的角色数量。
注意：不要统计"主角"、"配角"、"新增角色"等标题性词语。

示例：
- 如果文本中有林墨、苏娜、老周三个人物，返回：3
- 如果只是标题和分类，没有具体人物，返回：0

只返回一个数字，不要其他内容。"""

        try:
            ai_result = self.character_designer.process(ai_prompt, {})
            # 提取数字
            import re
            numbers = re.findall(r'\d+', ai_result)
            if numbers:
                character_count = int(numbers[0])
                print(f"✅ AI识别到人物数: {character_count}")
                return character_count
        except Exception as e:
            print(f"❌ AI识别失败: {e}")

        print("⚠️  无法识别人物数，默认返回0")
        return 0

    def expand_plot_outline(self, current_outline: str, world_setting: str,
                          characters: str, target_chapters: int = 50) -> Dict[str, Any]:
        """扩展情节大纲

        将简短大纲扩展为适合长篇小说的详细章节规划

        Args:
            current_outline: 当前的情节大纲
            world_setting: 世界观设定
            characters: 人物设定
            target_chapters: 目标章节数（默认50章，约150万字）

        Returns:
            扩展后的大纲字典，包含:
            - expanded_outline: 扩展后的完整大纲
            - chapter_breakdown: 章节分解（每章简要说明）
            - plot_arcs: 情节线索分析
            - expansion_suggestions: 扩展建议
        """
        print(f"\n{'='*70}")
        print(f"【情节大纲扩展器】启动大纲扩展，目标章节数: {target_chapters}")
        print(f"{'='*70}\n")

        # 第一步：分析当前大纲的可扩展点
        analysis_prompt = f"""你是一位资深小说策划师。请分析以下简短大纲的扩展潜力。

【当前大纲】
{current_outline}

【世界观】
{world_setting}

【人物设定】
{characters}

请分析：
1. **主线情节可扩展点**：识别可以深入展开的情节环节
2. **支线剧情机会**：可以添加哪些有价值的支线故事
3. **情节转折点**：需要增加哪些铺垫和转折
4. **节奏分布建议**：如何分配高潮、低潮、过渡章节
5. **伏笔埋设点**：可以在哪些地方设置伏笔

Please给出具体分析，为扩展到{target_chapters}章提供依据。"""

        print("【第一步】分析大纲扩展潜力...")
        expansion_analysis = self.creative_director.process(analysis_prompt, {})
        print("✅ 扩展潜力分析完成\n")

        # 第二步：生成情节线索
        plot_arcs_prompt = f"""基于以下分析，设计长篇小说的情节线索体系。

【扩展分析】
{expansion_analysis}

【原始大纲】
{current_outline}

Please design：
1. **主线情节**：整本书的核心故事线（占比40%）
2. **A支线**：与主线紧密相关的次要故事线（占比25%）
3. **B支线**：人物成长或感情线（占比20%）
4. **C支线**：世界观探索或社会背景线（占比15%）

每条线索需要包括：
- 起始章节范围
- 核心冲突
- 关键转折点
- 与其他线索的交织点
- 高潮和解决方案

目标章节数：{target_chapters}章"""

        print("【第二步】设计多线索情节体系...")
        plot_arcs = self.plot_architect.process(plot_arcs_prompt, {})
        print("✅ 情节线索设计完成\n")

        # 第三步：生成章节分解
        chapter_breakdown_prompt = f"""基于以下情节线索，生成详细的章节分解（{target_chapters}章）。

【情节线索】
{plot_arcs}

【原始设定】
- 世界观: {world_setting}
- 人物: {characters}

Please为每一章生成结构清晰的简要说明（2-4句话），格式如下：

第1章：[标题]
- 主要内容：...
- 关键事件：...
- 涉及人物：[列出主要出场角色]
- 人物发展：[本章人物的重要变化或关系进展]
- 情节定位：[开端/发展/高潮/结局中的哪个部分]
- 所属线索：[本章涉及的主线/支线（可多条，例如：主线；主线 + A支线）]

第2章：[标题]
- 主要内容：...
- 关键事件：...
- 涉及人物：...
- 人物发展：...
- 情节定位：...
- 所属线索：...

...（直到第{target_chapters}章）

要求：
1. 确保情节发展节奏合理（避免前松后紧）
2. 适当分布高潮章节（每10-15章一个小高潮）
3. 支线穿插自然，不影响主线推进
4. 伏笔和回收配对明确
5. 确保所有主要角色在不同阶段都有出场与推进，避免长时间“消失”。
"""

        print(f"【第三步】生成{target_chapters}章详细分解...")
        chapter_breakdown = self.plot_architect.process(chapter_breakdown_prompt, {})
        print("✅ 章节分解完成\n")

        # 第四步：生成完整扩展大纲
        expanded_outline_prompt = f"""基于以下信息，撰写完整的长篇小说情节大纲。

【章节分解】
{chapter_breakdown}

【情节线索】
{plot_arcs}

Please撰写一份完整的情节大纲，包括：
1. **故事概述**（500字）
2. **情节发展**（按起承转合分四部分）
3. **重要转折点**（列出5-8个关键转折）
4. **高潮设计**（中期高潮 + 最终高潮）
5. **结局规划**（开放式/封闭式，是否留续集空间）

这份大纲将指导{target_chapters}章的创作。"""

        print("【第四步】生成完整扩展大纲...")
        expanded_outline = self.creative_director.process(expanded_outline_prompt, {})
        print("✅ 完整大纲生成完成\n")

        print(f"{'='*70}")
        print(f"【情节大纲扩展器】扩展完成！")
        print(f"{'='*70}\n")

        return {
            "expanded_outline": expanded_outline,
            "chapter_breakdown": chapter_breakdown,
            "plot_arcs": plot_arcs,
            "expansion_analysis": expansion_analysis,
            "target_chapters": target_chapters
        }

    def expand_characters(self, main_characters: str, world_setting: str,
                        plot_outline: str, target_count: int = 15) -> Dict[str, Any]:
        """扩展人物体系

        基于主要人物自动生成配角、对手、辅助角色等

        Args:
            main_characters: 当前主要人物设定
            world_setting: 世界观设定
            plot_outline: 情节大纲
            target_count: 目标人物总数（默认15个）

        Returns:
            扩展后的人物体系字典，包含:
            - all_characters: 完整人物列表
            - character_relationships: 人物关系网络
            - character_arcs: 人物成长线
            - role_distribution: 角色定位分布
        """
        print(f"\n{'='*70}")
        print(f"【人物体系扩展器】启动人物扩展，目标人物数: {target_count}")
        print(f"{'='*70}\n")

        # 第一步：分析现有人物和需求
        analysis_prompt = f"""你是一位资深人物设计师。请分析以下人物体系的扩展需求。

【当前主要人物】
{main_characters}

【世界观】
{world_setting}

【情节大纲】
{plot_outline}

Please分析：
1. **现有人物数量**：当前有几个主要人物
2. **角色类型缺口**：缺少哪些类型的角色（对手、导师、辅助者、中立者等）
3. **情节需求分析**：根据情节发展，需要增加哪些角色
4. **人物关系机会**：可以设计哪些有趣的人物关系
5. **多样性建议**：如何增加人物的多样性和丰富性

目标人物总数：{target_count}个（包括主角、配角、次要角色）"""

        print("【第一步】分析人物扩展需求...")
        character_analysis = self.character_designer.process(analysis_prompt, {})
        print("✅ 人物需求分析完成\n")

        # 第二步：设计角色定位分布
        role_distribution_prompt = f"""基于以下分析，设计人物角色定位体系。

【人物需求分析】
{character_analysis}

【现有主角】
{main_characters}

Please design{target_count}个人物的角色定位， including：

1. **主角阵营**（3-5人）
   - 主角：{main_characters.split('\\n')[0] if main_characters else '待定'}
   - 核心盟友：...
   - 导师/引路人：...

2. **对手阵营**（2-4人）
   - 主要反派：...
   - 次要对手：...
   - 中期敌人（后期可能转化）：...

3. **中立/辅助角色**（5-8人）
   - 信息提供者：...
   - 技能支持者：...
   - 情感陪伴者：...
   - 社会背景人物：...

每个角色需要注明：
- 姓名和基本设定（1句话）
- 在故事中的作用
- 与主角的关系
"""

        print("【第二步】设计角色定位体系...")
        role_distribution = self.character_designer.process(role_distribution_prompt, {})
        print("✅ 角色定位设计完成\n")

        # 第三步：生成完整人物档案
        character_profiles_prompt = f"""基于以下角色定位，为每个人物生成完整档案。

【角色定位】
{role_distribution}

【世界观】
{world_setting}

Please为{target_count}个人物生成详细档案，每个人物包括：

**格式模板**：
---
【姓名】：...
【年龄/性别】：...
【角色定位】：（主角/配角/对手/支持角色/中立角色等）
【外貌特征】：（2-3句）
【性格特点】：（核心性格 + 矛盾性格）
【背景故事】：（3-5句，简要说明过去经历）
【世界观/价值观立场】：（例如对系统/秩序/自由/科技的态度，1-2句）
【核心动机】：（为什么参与故事，想要什么）
【能力/特长】：（在故事中的优势）
【弱点/缺陷】：（人物的局限性）
【在情节中的作用】：（与主线/支线的关系，2-3句）
【人物成长线】：（在故事中的变化，尽量用“从……到……”描述）
【关键关系】：（与3-5个其他人物的关系）
【关联线索】：（本角色主要参与的情节线，可简要命名主线/支线）
---

要求：
1. 人物要立体，有优点也有缺点
2. 避免脸谱化和刻板印象
3. 确保人物之间有化学反应
4. 每个人物都要有存在的价值
"""

        print(f"【第三步】生成{target_count}个人物完整档案...")
        all_characters = self.character_designer.process(character_profiles_prompt, {})
        print("✅ 人物档案生成完成\n")

        # 第四步：生成人物关系网络
        relationships_prompt = f"""基于以下人物档案，设计人物关系网络图。

【所有人物】
{all_characters}

Please design人物关系网络， including：

1. **核心关系链**
   - 主角 ↔ 盟友
   - 主角 ↔ 对手
   - 主角 ↔ 导师

2. **三角关系**
   - 人物A ↔ 人物B ↔ 人物C
   - 可以是友情、爱情、竞争等

3. **隐藏关系**
   - 在故事中后期揭示的关系
   - 意想不到的联系

4. **关系演变线**
   - 敌人→盟友
   - 陌生→亲密
   - 信任→背叛

格式示例：
- 主角 ⇄ 盟友A：战友关系，相互信任（第1章建立）
- 主角 → 导师B：单向崇拜，导师引导（第5章出现）
- 主角 ⇄ 反派C：宿敌关系，理念冲突（第10章首次交锋）
"""

        print("【第四步】生成人物关系网络...")
        character_relationships = self.character_designer.process(relationships_prompt, {})
        print("✅ 人物关系网络完成\n")

        print(f"{'='*70}")
        print(f"【人物体系扩展器】扩展完成！")
        print(f"{'='*70}\n")

        return {
            "all_characters": all_characters,
            "character_relationships": character_relationships,
            "role_distribution": role_distribution,
            "character_analysis": character_analysis,
            "target_count": target_count
        }

    def generate_expansion_summary(self, outline_expansion: Dict[str, Any],
                                  character_expansion: Dict[str, Any]) -> str:
        """生成扩展总结报告

        Args:
            outline_expansion: 情节扩展结果
            character_expansion: 人物扩展结果

        Returns:
            格式化的扩展总结报告
        """
        summary = f"""
{'='*70}
【长篇小说扩展总结报告】
{'='*70}

## 一、情节大纲扩展

### 目标章节数
{outline_expansion.get('target_chapters', 'N/A')} 章

### 扩展策略
{outline_expansion.get('expansion_analysis', 'N/A')[:300]}...

### 情节线索
{outline_expansion.get('plot_arcs', 'N/A')[:300]}...

### 章节分解（示例前5章）
{outline_expansion.get('chapter_breakdown', 'N/A')[:500]}...

---

## 二、人物体系扩展

### 目标人物数
{character_expansion.get('target_count', 'N/A')} 个

### 角色定位
{character_expansion.get('role_distribution', 'N/A')[:300]}...

### 人物关系网络
{character_expansion.get('character_relationships', 'N/A')[:300]}...

---

## 三、实施建议

### 创作顺序
1. 使用扩展后的大纲更新 project_settings.plot_outline
2. 将扩展后的人物档案更新到 project_settings.characters
3. 保存章节分解到知识库，作为后续创作参考
4. 保存人物关系网络到知识库
5. 开始按章节顺序创作

### 注意事项
⚠️ 扩展后的内容较长，建议分阶段实施
⚠️ 在创作过程中可以根据实际情况调整细节
⚠️ 定期检查情节和人物的一致性

{'='*70}
"""
        return summary

    def expand_plot_outline_incremental(self, current_outline: str, world_setting: str,
                                       characters: str, current_chapter_count: int,
                                       increment: int = 10,
                                       target_total_chapters: Optional[int] = None) -> Dict[str, Any]:
        """渐进式扩展情节大纲

        每次增加5-10章，直到AI判断不再需要扩展

        Args:
            current_outline: 当前的情节大纲
            world_setting: 世界观设定
            characters: 人物设定
            current_chapter_count: 当前已有的章节数（如为0则自动识别）
            increment: 本次扩展的章节数（默认10章）
            target_total_chapters: 长篇小说目标总章节数（如未提供则按100章进行规划判断）

        Returns:
            扩展后的大纲字典，包含:
            - expanded_outline: 扩展后的完整大纲
            - chapter_breakdown: 章节分解
            - plot_arcs: 情节线索分析
            - current_chapter_count: 当前总章节数
            - should_continue: AI判断是否还需要继续扩展
            - continue_reason: 继续扩展的原因（如果需要）
        """
        # 🆕 智能识别当前章节数
        if current_chapter_count == 0:
            print("🔍 检测到 current_chapter_count=0，开始自动识别当前大纲的章节数...")
            detected_count = self.count_chapters_in_outline(current_outline)
            if detected_count > 0:
                current_chapter_count = detected_count
                print(f"🎯 识别成功！当前大纲已有 {current_chapter_count} 章\n")
            else:
                print("🆕 未识别到章节，从 0 章开始扩展\n")

        print(f"\n{'='*70}")
        print(f"【渐进式大纲扩展】从 {current_chapter_count} 章扩展到 {current_chapter_count + increment} 章")
        print(f"{'='*70}\n")

        target_chapters = current_chapter_count + increment

        # 🎯 任务6.1：修仙题材境界跨度检查
        realm_suggestion = self.check_realm_span_and_suggest()

        # 🎆 启用分层摘要策略 - 智能准备上下文
        print(f"\n{'='*70}")
        print(f"【分层摘要器】准备上下文")
        print(f"{'='*70}\n")
        
        context_result = self.layered_summarizer.prepare_context_for_expansion(
            outline=current_outline,
            characters=characters,
            worldview=world_setting,
            scenario="outline_expand",
            current_count=target_chapters,  # 使用目标章节数选择模型
            focus_range=None  # 大纲扩展不需要聚焦特定范围
        )
        
        # 🔥 使用智能选择的模型
        selected_model = context_result["selected_model"]
        optimized_context = context_result["context"]
        stats = context_result["stats"]
        
        print(f"\n📊 上下文优化结果:")
        print(f"   - 选择模型: {selected_model}")
        print(f"   - 原始总长: {len(current_outline) + len(characters) + len(world_setting):,}字符")
        print(f"   - 优化后: {len(optimized_context):,}字符 (压缩{(1-stats['compression_ratio'])*100:.1f}%)")
        print(f"   - Token使用: {stats['total_tokens']:,} / {stats['target_tokens']:,} ({stats['total_tokens']/stats['target_tokens']*100:.1f}%)\n")
        
        # 🎆 更新LLM：使用智能选择的模型
        if selected_model != "qwen-long":  # 如果不是qwen-long，需要创建新的LLM
            from langchain_openai import ChatOpenAI
            from .config import Config
            import os
            
            if selected_model.startswith("qwen"):
                api_key = os.getenv("DASHSCOPE_API_KEY", Config.DEEPSEEK_API_KEY)
                api_base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
            else:
                api_key = Config.DEEPSEEK_API_KEY
                api_base = Config.DEEPSEEK_API_BASE
            
            dynamic_llm = ChatOpenAI(
                model=selected_model,
                temperature=0.7,
                api_key=api_key,
                base_url=api_base
            )
            print(f"🔄 动态创建 LLM: {selected_model}\n")
        else:
            dynamic_llm = self.llm  # 使用默认的qwen-long
            print(f"✅ 使用默认 LLM: qwen-long\n")

        # 🔥 修改：先执行扩展，再判断是否继续
        # 🆕 计算卷数和每卷章节数（网文通常每卷20-30章）
        chapters_per_volume = 25  # 每卷约25章
        volume_count = max(2, (target_chapters + chapters_per_volume - 1) // chapters_per_volume)

        # 第一步：执行扩展（网文卷结构）
        # 🎆 使用优化后的上下文替换原始内容
        expansion_prompt = f"""基于以下优化后的上下文，进行整体性扩展到{target_chapters}章。

{optimized_context}

【网文结构设计原则】
⚠️ 网络小说不同于传统文学，需要特别注意：
1. **卷结构**：按"卷"划分，每卷有独立的小高潮和阶段性目标
2. **爽点密度**：每3-5章必须有一个爽点（打脸/升级/获得/反转）
3. **钩子设计**：每章结尾必须有悬念，让读者想点下一章
4. **节奏控制**：紧张-舒缓交替，避免长时间铺垫
5. **金手指展示**：定期展示主角的优势，给读者爽感
{self.genre_module.get('outline_rhythm_guide', '')}
{realm_suggestion}

【扩展要求】
🔥 重要：这不是简单增加章节，而是整体重新规划为网文卷结构

1. **整体视角**：从第1章到第{target_chapters}章的完整规划
2. **卷结构划分**：
   - 本书规划为**约{target_chapters}章**，分为**{volume_count}卷**
   - 每卷约{chapters_per_volume}章，有独立的阶段性高潮
   - 各卷章节数可灵活调整，但总数应接近{target_chapters}章

3. **人物全覆盖**：
   - 确保参考所有已生成的人物（主角、对手、支持、中立阵营）
   - 每个重要角色都有充分的出场和发展
   - 避免角色在后续章节中消失

4. **爽点节奏规划**：
   - 每5章一个小爽点（打脸/升级/获得宝物）
   - 每25章（卷末）一个大爽点（击败Boss/重大突破）
   - 爽点类型：打脸/升级/获得宝物/装逼成功/反转翻盘/美人倾心/万众瞩目

5. **钩子设计**：
   - 每章结尾必须有悬念或钩子
   - 钩子类型：悬念式/危机式/反转式/升级式/对决式

Please生成完整的{target_chapters}章规划（🔥重点：每章必须有完整的详细规划）：

## 一、故事概述
[基于扩展后的完整故事，概述核心概念、主线冲突、主角成长轨迹，300-500字]

---

## 二、卷结构与章节详情（共{volume_count}卷，约{target_chapters}章）

### 【第一卷】「卷名」

**卷概述**：
- **章节范围**：第1-{chapters_per_volume}章
- **阶段目标**：（本卷主角的核心目标）
- **核心冲突**：（本卷的主要矛盾）
- **卷末高潮**：（本卷结尾的高潮事件）
- **关键人物**：（本卷重点登场人物）

**章节详情**：

#### 第1章：《章节标题》
- **主要内容**：（本章核心剧情，50-100字）
- **关键事件**：（推动情节的关键事件）
- **涉及人物**：（出场角色列表）
- **人物发展**：（本章人物关系或状态变化）
- **情节线索**：主线 / 主线+支线A
- **爽点设计**：⭐⭐ [类型] 描述 / 无
- **结尾钩子**：[类型] 钩子内容

#### 第2章：《章节标题》
...（同上格式，每章都要详细填写，不可省略）

---

### 【第二卷】「卷名」
...（同上格式，每卷每章都要详细填写）

---

（继续规划后续各卷，直到第{volume_count}卷的最后一章）

---

## 三、爽点节奏总览

| 卷 | 章节 | 爽点类型 | 爽点描述 | 强度 |
|----|------|----------|----------|------|
| 一 | 第3章 | 首秀 | 首次展示金手指 | ⭐⭐ |
| 一 | 第{chapters_per_volume}章 | 卷末大爽 | 击败本卷Boss | ⭐⭐⭐⭐⭐ |
| ... | ... | ... | ... | ... |

---

## 四、情节线索总览

| 线索名称 | 类型 | 起始章 | 关键节点 | 收束章 |
|----------|------|--------|----------|--------|
| 主线 | 核心 | 第1章 | 第X章转折 | 第{target_chapters}章 |
| 支线A | 感情 | 第X章 | 第Y章 | 第Z章 |

---

## 五、人物出场统计

| 角色 | 阵营 | 首次登场 | 关键章节 | 角色弧光 |
|------|------|----------|----------|----------|
| 主角 | 主角 | 第1章 | 1,X,Y,Z | 成长轨迹 |
| ... | ... | ... | ... | ... |"""

        print(f"【第一步】整体性扩展章节（重新规划第1-{target_chapters}章）...")
        print(f"   📌 参考优化后的上下文（{len(optimized_context):,}字符）")
        print(f"   🔄 从{current_chapter_count}章整体扩展到{target_chapters}章")
        print(f"   🤖 调用模型: {selected_model}")
        
        # 🔥 使用动态选择的LLM
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(content="你是一位杰出的情节架构师，精通网络小说结构设计与爽点节奏规划。"),
            HumanMessage(content=expansion_prompt)
        ]
        response = dynamic_llm.invoke(messages)
        expansion_content = response.content
        print("✅ 章节扩展完成\n")

        # 第二步：整合更新大纲（不是简单追加，而是整体重构）
        integration_prompt = f"""基于当前大纲和新扩展的章节规划，生成一份完整的、结构清晰的大纲。

【原有大纲】
{current_outline}

【新扩展的章节规划】
{expansion_content}

【整合要求】
🔥 重要：这是整体重构，不是简单拼接

1. **不要简单堆码**：
   - 不要直接把新内容追加在后面
   - 不要保留重复的章节
   - 不要有“原有章节”和“新增章节”的分隔

2. **网文卷结构**：
   - 按"卷"划分，每卷{chapters_per_volume}章左右
   - 共{volume_count}卷，总计{target_chapters}章
   - 每卷有独立的阶段性高潮和爽点设计

3. **章节信息完整**：
   - 🔥 每章必须包含7项完整信息
   - 确保第1章到第{target_chapters}章都有详细规划
   - 所有人物都有合理出场和发展

4. **爽点和钩子集成**：
   - 爽点和钩子信息直接写在每章内，不要分离成单独表格
   - 同时在末尾提供爽点总览表便于快速查看

Please输出完整的、重新整合后的网文大纲（🔥重点：每章必须有完整的详细规划）：

## 一、故事概述
[整合后的完整故事概述，300-500字]

---

## 二、卷结构与章节详情（共{volume_count}卷，约{target_chapters}章）

### 【第一卷】「卷名」

**卷概述**：
- **章节范围**：第1-{chapters_per_volume}章
- **阶段目标**：（本卷主角的核心目标）
- **核心冲突**：（本卷的主要矛盾）
- **卷末高潮**：（本卷结尾的高潮事件）
- **关键人物**：（本卷重点登场人物）

**章节详情**：

#### 第1章：《章节标题》
- **主要内容**：（本章核心剧情，50-100字）
- **关键事件**：（推动情节的关键事件）
- **涉及人物**：（出场角色列表）
- **人物发展**：（本章人物关系或状态变化）
- **情节线索**：主线 / 主线+支线A
- **爽点设计**：⭐⭐ [类型] 描述 / 无
- **结尾钩子**：[类型] 钩子内容

#### 第2章：《章节标题》
...（同上格式，每章都要详细填写，不可省略）

---

### 【第二卷】「卷名」
...（同上格式，每卷每章都要详细填写）

---

## 三、爽点节奏总览

| 卷 | 章节 | 爽点类型 | 爽点描述 | 强度 |
|----|------|----------|----------|------|
| 一 | 第3章 | 首秀 | ... | ⭐⭐ |
| ... | ... | ... | ... | ... |

---

## 四、情节线索总览

| 线索名称 | 类型 | 起始章 | 关键节点 | 收束章 |
|----------|------|--------|----------|--------|
| 主线 | 核心 | 第1章 | 第X章 | 第{target_chapters}章 |

---

## 五、人物出场统计

| 角色 | 阵营 | 首次登场 | 关键章节 | 角色弧光 |
|------|------|----------|----------|----------|
| 主角 | 主角 | 第1章 | ... | ... |"""

        print(f"【第二步】整体重构大纲（最佳格式：章节详情+总览表）...")
        print(f"   🔄 重新组织所有{target_chapters}章的内容")
        print(f"   🤖 调用模型: {selected_model}")
        
        # 🔥 使用动态选择的LLM
        messages = [
            SystemMessage(content="你是一位杰出的情节架构师，精通网络小说结构设计与卷结构整合。"),
            HumanMessage(content=integration_prompt)
        ]
        response = dynamic_llm.invoke(messages)
        integrated_outline = response.content
        print("✅ 大纲整体重构完成\n")
        # 🆕 长篇小说目标章节数（用于判断是否继续扩展）
        long_novel_target = target_total_chapters or 100
        lower_threshold = int(long_novel_target * 0.5)
        upper_threshold = int(long_novel_target * 0.9)


        # 🔥 第三步：AI判断是否需要继续扩展（简化提示词，只传递统计信息）
        analysis_prompt = f"""你是一位资深小说策划师。Please analyze以下大纲是否 needs继续扩展。

【当前状态】
- 当前已有章节数：{target_chapters}
- 刚完成扩展：从{current_chapter_count}章扩展到{target_chapters}章
- 长篇目标总章节数：{long_novel_target}章

Please analyze：
1. **当前大纲的完整性**：是否已经覆盖了完整的故事线（开端、发展、高潮、结局）
2. **情节密度**：每章的情节容量是否合适，是否需要更多的过渡或详细描写
3. **支线发展**：是否有未展开的支线故事或人物关系
4. **伏笔和回收**：是否需要更多的伏笔铺垫

最后，以JSON格式回答：
{{
  "should_continue": true/false,
  "reason": "原因说明（100字以内）"
}}

判断标准（面向长篇小说）：
- 如果当前章节数 < {lower_threshold}，通常建议继续扩展（重点补充主线和支线）
- 如枟 {lower_threshold}-{upper_threshold} 章，根据故事完整性和情节复杂度判断
- 如果 > {upper_threshold} 章，需要非常充分的理由才继续扩展（例如仍有重要支线或伏笔尚未完成）
- 如果已有完整的故事结构，应该停止扩展"""

        print("【第三步】AI判断是否需要继续扩展...")
        print(f"   🤖 调用模型: {selected_model}")
        
        # 🔥 使用动态选择的LLM
        messages = [
            SystemMessage(content="你是一位资深小说策划师，擅长分析大纲完整性与判断是否需要继续扩展。"),
            HumanMessage(content=analysis_prompt)
        ]
        response = dynamic_llm.invoke(messages)
        analysis_result = response.content

        # 解析JSON结果
        import json
        import re

        # 提取JSON内容
        json_match = re.search(r'\{[\s\S]*?"should_continue"[\s\S]*?\}', analysis_result)
        should_continue = True
        continue_reason = ""

        if json_match:
            try:
                decision = json.loads(json_match.group())
                should_continue = decision.get('should_continue', True)
                continue_reason = decision.get('reason', '')
                print(f"✅ AI决策：{'继续扩展' if should_continue else '停止扩展'}")
                print(f"   原因：{continue_reason}")
            except:
                print("⚠️  无法解析AI结果，默认继续扩展")
        else:
            print("⚠️  无法解析AI结果，默认继续扩展")

        print(f"{'='*70}")
        print(f"【渐进式大纲扩展】本轮完成！")
        print(f"{'='*70}\n")

        return {
            "expanded_outline": integrated_outline,  # 🔥 返回整合后的大纲
            "chapter_breakdown": expansion_content,
            "plot_arcs": {},  # 🔥 前端会智能提取摘要
            "current_chapter_count": target_chapters,
            "should_continue": should_continue,
            "continue_reason": continue_reason
        }

    def expand_characters_incremental(self, main_characters: str, world_setting: str,
                                     plot_outline: str, current_character_count: int,
                                     increment: int = 5,
                                     target_total_characters: Optional[int] = None) -> Dict[str, Any]:
        """渐进式扩展人物体系

        每次增加3-6个角色，直到AI判断不再需要扩展

        Args:
            main_characters: 当前主要人物设定
            world_setting: 世界观设定
            plot_outline: 情节大纲
            current_character_count: 当前已有的人物数（如为0则自动识别）
            increment: 本次扩展的人物数（默认5个）
            target_total_characters: 长篇小说目标人物总数（如未提供则按25人进行规划判断）

        Returns:
            扩展后的人物体系字典，包含:
            - all_characters: 完整人物列表
            - character_relationships: 人物关系网络
            - role_distribution: 角色定位分布
            - current_character_count: 当前总人物数
            - should_continue: AI判断是否还需要继续扩展
            - continue_reason: 继续扩展的原因（如果需要）
        """
        # 🆕 智能识别当前人物数
        if current_character_count == 0:
            print("🔍 检测到 current_character_count=0，开始自动识别当前人物数...")
            detected_count = self.count_characters_in_text(main_characters)
            if detected_count > 0:
                current_character_count = detected_count
                print(f"🎯 识别成功！当前已有 {current_character_count} 个人物\n")
            else:
                print("🆕 未识别到人物，从 0 个开始扩展\n")

        print(f"\n{'='*70}")
        print(f"【渐进式人物扩展】从 {current_character_count} 个扩展到 {current_character_count + increment} 个")
        print(f"{'='*70}\n")

        target_count = current_character_count + increment

        # 🎆 启用分层摘要策略 - 智能准备上下文
        context_result = self.layered_summarizer.prepare_context_for_expansion(
            outline=plot_outline,
            characters=main_characters,
            worldview=world_setting,
            scenario="character_expand",
            current_count=target_count,  # 使用目标人物数选择模型
            focus_range=None  # 人物扩展不需要聚焦特定范围
        )
        
        # 🔥 使用智能选择的模型
        selected_model = context_result["selected_model"]
        optimized_context = context_result["context"]
        stats = context_result["stats"]
        
        # 打印优化结果日志
        print(f"\n📊 上下文优化结果:")
        print(f"   - 选择模型: {selected_model}")
        print(f"   - 原始总长: {len(plot_outline) + len(main_characters) + len(world_setting):,}字符")
        print(f"   - 优化后: {len(optimized_context):,}字符 (压缩{(1-stats['compression_ratio'])*100:.1f}%)")
        print(f"   - Token使用: {stats['total_tokens']:,} / {stats['target_tokens']:,}\n")

        # 🎆 更新LLM：使用智能选择的模型
        if selected_model != "qwen-long":
            from langchain_openai import ChatOpenAI
            dynamic_llm = ChatOpenAI(
                model=selected_model,
                base_url=self.character_designer.llm.openai_api_base,
                api_key=self.character_designer.llm.openai_api_key,
                temperature=0.8,
                max_tokens=4000
            )
        else:
            dynamic_llm = self.character_designer.llm
        
        # 临时替换LLM
        original_llm = self.character_designer.llm
        self.character_designer.llm = dynamic_llm
        
        try:
            # 🆕 获取题材专属人物字段
            character_extra_fields = self.genre_module.get('character_extra_fields', '')
            genre_specific_hint = f"\n\n🎯 【题材专属细化】（以下为人物设定的补充字段，请结合使用）\n{character_extra_fields}" if character_extra_fields else ""

            # 🔥 修改：先执行扩展，再判断是否继续
            # 第一步：执行扩展（使用优化后的上下文）
            expansion_prompt = f"""基于以下优化后的上下文，扩展到{target_count}个角色。

{optimized_context}

【扩展要求】
- 新增 {increment} 个角色（从第{current_character_count + 1}个开始）
- 每个新角色需要完整的人物卡信息，包括：
  * 姓名、年龄、性别
  * 故事立场：主角方/反派方/中立方/亦正亦邪
  * 所属势力：具体组织名称（如天剑宗/魔教/散修联盟/无）
  * 重要性（戏份权重）：主角/重要角色/次要角色/群众角色
  * 外貌特征（2-3句）
  * 性格特点（2-3句），包括典型行为与矛盾性格
  * 背景故事（关键人生经历，3-5句）
  * 世界观/价值观立场（例如对系统/秩序/自由/科技的态度，1-2句）
  * 核心动机（推动其行动的内在驱动力，1-2句）
  * 能力/特长（在故事中的优势）
  * 弱点/缺陷（性格或能力上的短板，1-2句）
  * 在情节中的作用（2-3句），以及与主线/支线的关联
  * 人物成长线（在故事中的变化与发展方向，1-2句）
  * 与主要角色及关键配角的关系（3-5个关键关系）
  * 关联线索（本角色主要参与的情节线，可简要命名主线/支线）

🔥 重要输出格式要求：
Please直接按阵营分类输出，格式如下（每个人物必须包含完整人物卡字段，**每个字段后必须换行**）：

⚠️ 【重要：姓名创作要求】
- **必须创作独特姓名**：不要使用常见、普通的名字
- **符合题材风格**：修仙题材用古风名字，科幻题材用现代或未来感名字，西幻题材用西式名字
- **避免重复**：每个人物的名字必须不同，不要使用如“林墨”、“苏娜”、“陈朔”、“老周”、“张伟”等示例名
- **富有意境**：名字应该有寃意或符号意义，与角色性格或命运相关

## 主角阵营

### 【姓名】：（请生成独特姓名）

【年龄/性别】：...

【故事立场】：主角方

【所属势力】：...

【重要性】：主角

【外貌特征】：...

【性格特点】：...

【背景故事】：...

【世界观/价值观立场】：...

【核心动机】：...

【能力/特长】：...

【弱点/缺陷】：...

【在情节中的作用】：...

【人物成长线】：...

【关键关系】：...

【关联线索】：...

---

### 【姓名】：（请生成独特姓名）

【年龄/性别】：...

...

---

## 对手阵营

### 【姓名】：（请生成独特姓名）
...

## 支持角色

### 【姓名】：（请生成独特姓名）
...

## 中立角色

### 【姓名】：（请生成独特姓名）
...

注意：
1. **关键：每个字段后必须有两个换行符**，保证排版清晰
2. 不要单独列出“新增角色列表”，直接合并到各阵营中
3. 使用【姓名】格式，方便识别和统计
4. 每个阵营的角色按重要性排序
5. 人物之间使用 --- 分隔线
6. 确保所有{target_count}个角色都包含在内{genre_specific_hint}"""

            print(f"【第一步】扩展角色（{current_character_count + 1}-{target_count}个）...")
            try:
                expansion_content = self.character_designer.process(expansion_prompt, {})
                print("✅ 角色扩展完成\n")
            except Exception as e:
                print(f"❌ 角色扩展失败: {e}")
                import traceback
                traceback.print_exc()
                raise

            # 第二步：整合更新人物体系（使用优化后的上下文）
            integration_prompt = f"""Please将新扩展的角色整合到现有人物体系中，生成一份完整的、结构清晰的人物档案。

【优化后的当前人物上下文】
{optimized_context}

【新增角色】
{expansion_content}

【整合要求】
1. **不要简单堆码**：不要直接把新内容追加在后面
2. **按阵营重新组织**：所有角色按阵营分类（主角、对手、支持、中立）
3. **信息完整 & 深度塑造**：保留原有角色的所有信息，并为每个角色补充背景故事、世界观/价值观立场、核心动机、能力/特长、弱点/缺陷和人物成长线等关键字段
4. **统一档案格式**：所有角色使用相同的详细档案格式，包含：基础信息、内在构成、背景与世界观立场、在情节中的作用、成长线、关系网络、关联线索
5. **去重去重复**：如果有重复的角色，只保留一份最完整的
6. **规模控制**：在保证角色完整性的前提下，尽量让总人数接近{target_count}个（允许±2人的浮动）

Please输出完整的、重新整合后的人物档案，**每个字段后必须有两个换行符**，格式如下：

## 主角阵营

### 【姓名】：[姓名]

【年龄/性别】：...

【角色定位】：主角/核心配角 等

【外貌特征】：...

【性格特点】：...

【背景故事】：...

【世界观/价值观立场】：...

【核心动机】：...

【能力/特长】：...

【弱点/缺陷】：...

【在情节中的作用】：...

【人物成长线】：...

【关键关系】：（与主要角色及重要配角的关系）

【关联线索】：（本角色主要参与的情节线）

---

...（所有主角阵营角色）

## 对手阵营

### 【姓名】：[姓名]
...

## 支持角色

### 【姓名】：[姓名]
...

## 中立角色

### 【姓名】：[姓名]
...

确保所有{target_count}个角色都包含在内，按重要性排序。人物之间使用 --- 分隔。"""

            print(f"【第二步】整合更新人物体系（不进行简单堆码）...")
            try:
                integrated_characters = self.character_designer.process(integration_prompt, {})
                print("✅ 人物体系整合完成\n")
            except Exception as e:
                print(f"❌ 人物体系整合失败: {e}")
                import traceback
                traceback.print_exc()
                raise

            # 第三步：生成人物关系网络
            relationship_prompt = f"""基于以下完整的人物体系，生成完整的人物关系网络。

【所有人物】
{integrated_characters}

Please以下列格式生成人物关系网络：

### 人物关系网络

**主角阵营内部**：
- [角色A] ↔ [角色B]：[关系类型]（[关系描述]）

**对手阵营内部**：
- [角色C] ↔ [角色D]：[关系类型]（[关系描述]）

**跨阵营关系**：
- [主角] ↔ [对手]：[关系类型]（[关系描述]）

**支持角色关系**：
- [支持角色] ↔ [主要角色]：[关系类型]（[关系描述]）

Please确保：
1. 包含所有{target_count}个角色
2. 关系类型包括：师徒、盟友、对手、亲人、同事、竞争等
3. 每个关系都有简短描述（20字以内）"""

            print(f"【第三步】生成人物关系网络...")
            relationships = self.character_designer.process(relationship_prompt, {})
            print("✅ 关系网络生成完成\n")

            # 第四步：统计角色分布
            distribution_prompt = f"""基于以下完整的人物体系，统计角色分布。

【所有人物】
{integrated_characters}

Please以以下格式输出JSON：
{{
  "主角": 数量,
  "配角": 数量,
  "对手": 数量,
  "支持角色": 数量,
  "中立角色": 数量
}}

Please确保所有数量加起来等于{target_count}。
只返回JSON，不要其他文字。"""

            print(f"【第四步】统计角色分布...")
            distribution_result = self.character_designer.process(distribution_prompt, {})
            print("✅ 角色分布统计完成\n")

            # 解析角色分布JSON
            import json
            import re

            distribution_dict = {}
            json_match = re.search(r'\{[\s\S]*?\}', distribution_result)
            if json_match:
                try:
                    distribution_dict = json.loads(json_match.group())
                    print(f"✅ 角色分布：{distribution_dict}")
                except:
                    print("⚠️  无法解析角色分布JSON")


            # 🆕 长篇小说目标人物数量（用于判断是否继续扩展）
            character_target = target_total_characters or 25
            lower_threshold = max(15, character_target - 10)
            upper_threshold = character_target + 5

            # 🔥 第五步：AI判断是否需要继续扩展（在扩展完成后判断）
            # 🔥 优化：只传递统计信息，不传递完整文本，避免超过token限制
            analysis_prompt = f"""你是一位资深人物设计师。Please analyze以下人物体系是否 needs继续扩展。

【当前状态】
- 当前已有人物数：{target_count}
- 刚完成扩展：从{current_character_count}个扩展到{target_count}个
- 长篇目标人物数：{character_target}个
- 角色分布：{distribution_dict}

Please analyze：
1. **主要角色覆盖**：主角、配角、对手、师友等关键角色是否齐全
2. **角色均衡**：正面、负面、中立角色的比例是否合适

最后，以JSON格式回答：
{{
  "should_continue": true/false,
  "reason": "原因说明（100字以内）"
}}

判断标准（面向长篇小说人物体系）：
- 如果当前人物数 < {lower_threshold}，通常建议继续扩展，补足主要角色和关键配角
- 如果 {lower_threshold}-{character_target} 个，根据角色分布情况判断
- 如果 {character_target}-{upper_threshold} 个，偏向于收束人物，只在确有需要时少量补充
- 如果 > {upper_threshold} 个，需要非常充分的理由才继续扩展，避免角色过多导致人物形象被稀释"""

            print("【第五步】AI判断是否需要继续扩展...")
            analysis_result = self.character_designer.process(analysis_prompt, {})

            # 解析JSON结果
            import json
            import re

            json_match = re.search(r'\{[\s\S]*?"should_continue"[\s\S]*?\}', analysis_result)
            should_continue = True
            continue_reason = ""

            if json_match:
                try:
                    decision = json.loads(json_match.group())
                    should_continue = decision.get('should_continue', True)
                    continue_reason = decision.get('reason', '')
                    print(f"✅ AI决策：{'继续扩展' if should_continue else '停止扩展'}")
                    print(f"   原因：{continue_reason}")
                except:
                    print("⚠️  无法解析AI结果，默认继续扩展")
            else:
                print("⚠️  无法解析AI结果，默认继续扩展")

            print(f"{'='*70}")
            print(f"【渐进式人物扩展】本轮完成！")
            print(f"{'='*70}\n")

            return {
                "all_characters": integrated_characters,  # 🔥 返回整合后的人物体系
                "character_relationships": relationships,  # 🔥 现在生成完整的关系网络
                "role_distribution": distribution_dict,  # 🔥 现在生成角色分布
                "current_character_count": target_count,
                "should_continue": should_continue,
                "continue_reason": continue_reason
            }
        finally:
            # 🔄 恢复原始 LLM
            self.character_designer.llm = original_llm

    def generate_epic_framework(self, world_setting: str, characters: str,
                               total_volumes: int, total_chapters_range: tuple[int, int]) -> Dict[str, Any]:
        """生成史诗框架（超长网文总体规划）
        
        为1000+章的超长网文生成宏观框架，每卷仅200-300字概要
        
        Args:
            world_setting: 世界观设定
            characters: 人物设定
            total_volumes: 总卷数(10-50卷)
            total_chapters_range: 总章节范围(min, max)
            
        Returns:
            史诗框架字典，包含:
            - expanded_outline: 史诗框架内容
            - total_volumes: 总卷数
            - estimated_chapters: 预估总章节数
        """
        print(f"\n{'='*70}")
        print(f"🌟 【史诗框架生成器】{total_volumes}卷，预计{total_chapters_range[0]}-{total_chapters_range[1]}章")
        print(f"{'='*70}\n")
        
        framework_prompt = f"""你是顶级网文架构师，擅长规划超长篇网文（1000章以上）。

【任务】
规划一部{total_volumes}卷的超长网文，预计{total_chapters_range[0]}-{total_chapters_range[1]}章

【当前设定】
世界观：
{world_setting}

主要人物：
{characters[:1000] if characters else '待完善'}

【输出要求】
⚠️ 这是史诗框架，不是详细大纲！每卷仅需200-300字概要

## 一、整体叙事节奏
分为前中后三期，每期占多少卷，预计章节数：
- 前期（第1-X卷）：主题/场景 → Y章
- 中期（第X-Y卷）：主题/场景 → Z章
- 后期（第Y-{total_volumes}卷）：主题/场景 → W章

## 二、境界/实力体系进阶
🔥 根据题材和总章数智能规划：

【境界密度规则】
- 若总章数 < 500：大境界3-5个，每大境界100-150章
- 若500-1500章：大境界5-8个，每大境界100-250章
- 若 > 1500章：大境界8-12个，每大境界150-300章

【题材适配】
- 修仙类：炼气→1-9层→筑基→金丹→元婴→化神→合体→渡劫（可下分初/中/后期）
- 玄幻类：战士→战师1-9星→大斗师→斗灵→斗圣→斗帝
- 武侠类：三流→二流→一流→宗师→大宗师→武圣
- 都市类：以财富/权势/影响力为阶段，如：起步→初有成就→行业精英→领域霸主

【具体要求】
1. 首先分析世界观是什么题材（修仙/玄幻/武侠/都市/其他）
2. 根据总章数{total_chapters_range[0]}-{total_chapters_range[1]}决定大境界数量
3. 每个大境界应分配80-250章，避免500+章才进阶一次
4. 修仙类需考虑小境界（如炼气1-9层），提供更频繁的成就感
5. 列出具体的境界进阶路径，格式如：
   - 第1-3卷：炼气1层→9层（约150-200章）
   - 第4-6卷：筑基初期→后期（约180-220章）
   - 第7-10卷：金丹初期→后期（约250-300章）
   - ...

⚠️ 关键：不要固定“有5卷一个大境界”，而是根据题材和总章数灵活调整！

## 三、{total_volumes}卷概要
每卷格式：
【第X卷】卷名（预计Y章）
- 核心：本卷主题/目标
- 境界：主角境界范围（如：炼气3层→7层）
- 主要敌人：本卷Boss
- 卷末高潮：关键事件

## 四、关键伏笔布局
| 伏笔 | 埋设位置 | 铺垫卷 | 揭秘卷 |
|------|---------|--------|--------|
| 主角真实身份 | 第X卷 | 第Y,Z卷 | 第W卷 |
| 天道黑幕 | 第A卷 | 第B,C卷 | 第D卷 |
(至少10条跨卷伏笔)

## 五、核心人物生命周期
| 角色 | 登场 | 活跃期 | 退场/转型 |
|------|------|--------|-------------|
| 女主 | 第1卷 | 1-{total_volumes}卷 | 始终在线 |
| 师父 | 第1卷 | 1-8卷 | 第9卷羽化 |
(主要角色的登场退场规划)

记住：这是框架，不是详细大纲，保持高层视角！"""

        print("【第一步】生成史诗框架...")
        framework_content = self.creative_director.process(framework_prompt, {})
        print("✅ 史诗框架生成完成\n")
        
        print(f"{'='*70}")
        print(f"【史诗框架生成】完成！")
        print(f"{'='*70}\n")
        
        return {
            "expanded_outline": framework_content,
            "total_volumes": total_volumes,
            "estimated_chapters": (total_chapters_range[0] + total_chapters_range[1]) // 2,
            "framework_type": "epic"
        }
    
    def expand_volume_detail(self, framework_content: str, target_volume_index: int,
                            world_setting: str, characters: str,
                            chapters_range: tuple[int, int]) -> Dict[str, Any]:
        """基于史诗框架详细扩展单卷
        
        根据已有的史诗框架，将指定的卷扩展为详细的章节大纲
        
        Args:
            framework_content: 史诗框架内容
            target_volume_index: 扩展第几卷
            world_setting: 世界观设定
            characters: 人物设定
            chapters_range: 本卷章节范围(min, max)
            
        Returns:
            单卷详细字典，包含:
            - expanded_outline: 详细大纲
            - volume_index: 卷索引
            - chapter_count: 实际章节数
        """
        print(f"\n{'='*70}")
        print(f"📖 【单卷详细扩展】第{target_volume_index}卷，{chapters_range[0]}-{chapters_range[1]}章")
        print(f"{'='*70}\n")
        
        # 🆕 获取题材专属的章节细纲模板
        chapter_template = self.genre_module.get('chapter_detail_template', '')
        template_example = chapter_template.format(
            chapter_num=1,
            chapter_title="章节标题"
        ) if chapter_template else ""
        
        detail_prompt = f"""基于已有的史诗框架，详细扩展第{target_volume_index}卷。

【史诗框架】
{framework_content}

【世界观设定】
{world_setting}

【人物设定】
{characters[:2000] if characters else '待完善'}

【扩展要求】
生成{chapters_range[0]}-{chapters_range[1]}章的详细大纲

🔥 【章节细纲模板】每章必须严格按以下格式：
{template_example if template_example else '''第{chapter_num}章：《{chapter_title}》

【核心目标】本章在故事中的作用

【进度变化】章节开始 → 章节结束的关键变化

【情节分镜】（3-5个场景，标注字数占比）
1. 开场(10%)：场景描述
2. 发展(30%)：场景描述
3. 小高潮(25%)：场景描述
4. 延伸(20%)：场景描述
5. 收尾(15%)：场景描述

【关键对话】（1-2段核心对话大意）

【情绪曲线】情绪走势

【伏笔设计】埋设/回收的伏笔

【爽点/高潮设计】
类型、强度⭐~⭐⭐⭐⭐、实现方式

【结尾钩子】具体内容

【涉及人物与发展】主要人物及本章变化
'''}

⚠️ 必须检查：
1. 是否符合史诗框架中本卷的定位
2. 是否正确埋设/回收框架中规划的伏笔
3. 人物登场是否符合框架中的生命周期规划

Please输出完整的、重新整合后的网文大纲（🔥重点：每章必须有完整的详细规划）：

## 一、故事概述
[整合后的完整故事概述，300-500字]

## 二、第{target_volume_index}卷详细规划

(按上述模板格式输出每一章...)

## 三、伏笔埋设检查
✅ 第X章：埋设主角身份伏笔（符合史诗框架）
✅ 第Y章：提及"天道"异常（为第Z卷铺垫）"""

        print("【第一步】详细扩展第{target_volume_index}卷...")
        
        # 🛡️ 内容安全重试机制
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 第一次尝试：正常prompt
                # 后续尝试：添加内容安全约束
                if attempt > 0:
                    print(f"⚠️ 检测到内容安全问题，第{attempt + 1}次重试（共{max_retries}次）...")
                    # 在prompt末尾添加内容安全约束
                    safety_constraint = """

⚠️ 内容安全要求：
1. 避免包含暴力、血腥、恐怖等过度描写
2. 人物关系和情节发展应符合主流价值观
3. 使用委婉、克制的表达方式
4. 重点突出正面价值观和人物成长"""
                    detail_prompt_safe = detail_prompt + safety_constraint
                    volume_content = self.plot_architect.process(detail_prompt_safe, {})
                else:
                    volume_content = self.plot_architect.process(detail_prompt, {})
                
                print("✅ 单卷详细扩展完成\n")
                break  # 成功则跳出重试循环
                
            except Exception as e:
                error_str = str(e)
                # 检查是否是内容安全问题
                if 'data_inspection_failed' in error_str or 'inappropriate content' in error_str:
                    if attempt < max_retries - 1:
                        print(f"⚠️ 内容安全审查失败: {error_str[:100]}...")
                        continue  # 继续重试
                    else:
                        # 最后一次重试也失败，返回占位内容
                        print(f"❌ 第{target_volume_index}卷内容安全审查多次失败，使用占位内容")
                        volume_content = f"""## 第{target_volume_index}卷：内容生成失败

⚠️ 由于内容安全审查限制，本卷详细大纲暂时无法生成。
建议：
1. 调整世界观设定或人物关系，避免敏感内容
2. 手动编写本卷大纲
3. 稍后重试单卷扩展

章节范围：第{chapters_range[0]}-{chapters_range[1]}章（预计）"""
                        break
                else:
                    # 非内容安全问题，直接抛出
                    raise
        
        print(f"{'='*70}")
        print(f"【单卷详细扩展】完成！")
        print(f"{'='*70}\n")
        
        # 估算实际章节数(取范围中值)
        estimated_chapters = (chapters_range[0] + chapters_range[1]) // 2
        
        return {
            "expanded_outline": volume_content,
            "volume_index": target_volume_index,
            "chapter_count": estimated_chapters,
            "current_chapter_count": estimated_chapters
        }


def create_outline_expander(knowledge_base: Optional[NovelKnowledgeBase] = None,
                           memory_manager: Optional[NovelMemoryManager] = None,
                           genre: str = "",  # 🎯 任务6：添加题材参数
                           planned_chapters_max: int = 0) -> OutlineExpander:  # 🎯 任务6.1
    """创建大纲扩展器的工厂函数

    Args:
        knowledge_base: 知识库实例
        memory_manager: 记忆管理器实例
        genre: 题材类型
        planned_chapters_max: 规划的最大章节数

    Returns:
        配置好的OutlineExpander实例
    """
    return OutlineExpander(knowledge_base, memory_manager, genre, planned_chapters_max)
