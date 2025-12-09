#!/usr/bin/env python3
"""临时脚本：迁移内容创作 prompt 到模块化调用"""
import re

# 步骤1：在 content_creation.py 末尾添加 FirstChapterPrompts 类
CONTENT_CREATION_PATH = 'app/services/prompts/stages/content_creation.py'
COORDINATOR_PATH = 'app/services/agents/agent_coordinator.py'

FIRST_CHAPTER_CLASS = '''

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
'''

def main():
    # 步骤1：添加 FirstChapterPrompts 类到 content_creation.py
    print("📝 步骤1：添加 FirstChapterPrompts 类...")
    with open(CONTENT_CREATION_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if 'FirstChapterPrompts' not in content:
        content = content.rstrip() + FIRST_CHAPTER_CLASS
        with open(CONTENT_CREATION_PATH, 'w', encoding='utf-8') as f:
            f.write(content)
        print("✅ FirstChapterPrompts 类已添加")
    else:
        print("⏭ FirstChapterPrompts 已存在，跳过")
    
    # 步骤2：在 agent_coordinator.py 中迁移调用
    print("\n📝 步骤2：迁移 agent_coordinator.py 中的调用...")
    with open(COORDINATOR_PATH, 'r', encoding='utf-8') as f:
        coord_content = f.read()
    
    # 添加导入
    if 'FirstChapterPrompts' not in coord_content:
        # 在已有的 structure_design 导入后添加
        old_import = '''from app.services.prompts.stages.structure_design import (
    StructureDesignPrompts,
    get_genre_rhythm_guide
)'''
        new_import = '''from app.services.prompts.stages.structure_design import (
    StructureDesignPrompts,
    get_genre_rhythm_guide
)
from app.services.prompts.stages.content_creation import FirstChapterPrompts'''
        coord_content = coord_content.replace(old_import, new_import)
        print("✅ 添加 FirstChapterPrompts 导入")
    
    # 替换内容创作 prompt
    pattern = r'(        logger\.info\(f"✍️ 内容创作师正在生成第1章草稿（目标\{target\}章）\.\.\."\)\s+content_prompt = f"""请根据提供的情节大纲.*?请开始创作第1章内容，直接输出章节正文，不要包含任何额外的说明文字。""")'
    
    new_code = '''        logger.info(f"✍️ 内容创作师正在生成第1章草稿（目标{target}章）...")
        
        # 🆕 使用模块化提示词生成第1章创作 prompt
        content_prompt = FirstChapterPrompts.get_first_chapter_prompt(
            plot_outline=plot_outline[:500] if plot_outline else '无',
            concept=concept[:300] if concept else '无',
            world_setting=world_setting[:200] if world_setting else '无',
            characters=characters[:200] if characters else '无',
            target_words=2500
        )'''
    
    match = re.search(pattern, coord_content, re.DOTALL)
    if match:
        print(f"✅ 找到匹配内容，位置: {match.start()}-{match.end()}")
        coord_content = coord_content[:match.start()] + new_code + coord_content[match.end():]
        
        with open(COORDINATOR_PATH, 'w', encoding='utf-8') as f:
            f.write(coord_content)
        print("✅ 替换完成！内容创作 prompt 已迁移到模块化调用")
    else:
        print("❌ 未找到匹配内容")
    
    # 验证
    with open(COORDINATOR_PATH, 'r', encoding='utf-8') as f:
        verify = f.read()
    if 'FirstChapterPrompts.get_first_chapter_prompt(' in verify:
        print("✅ 验证成功：已包含模块化调用")
    else:
        print("❌ 验证失败")

if __name__ == '__main__':
    main()
