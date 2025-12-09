#!/usr/bin/env python3
"""临时脚本：迁移结构设计 prompt 到模块化调用"""
import re

FILE_PATH = 'app/services/agents/agent_coordinator.py'

# 新的模块化调用代码
NEW_CODE = '''        logger.info("📝 创意总监正在生成网文卷结构大纲...")
        
        # 🆕 使用模块化提示词生成结构设计 prompt
        rhythm_guide = genre_module.get('outline_rhythm_guide', '') or get_genre_rhythm_guide(current_genre)
        structure_prompt = StructureDesignPrompts.get_structure_prompt(
            concept=concept[:500] if concept else '无',
            world_setting=world_setting[:300] if world_setting else '无',
            characters=characters[:300] if characters else '无',
            genre_rhythm_guide=rhythm_guide
        )'''

def main():
    with open(FILE_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 使用正则表达式匹配整个 structure_prompt 块
    pattern = r'(        logger\.info\("📝 创意总监正在生成网文卷结构大纲\.\.\."\)\s+structure_prompt = f""".*?请根据以上要求输出完整的卷结构大纲。\{genre_module\.get\(\'outline_rhythm_guide\', \'\'\)\}""")'
    
    match = re.search(pattern, content, re.DOTALL)
    if match:
        print(f"✅ 找到匹配内容，位置: {match.start()}-{match.end()}")
        print(f"   匹配长度: {len(match.group(1))} 字符")
        
        # 执行替换
        new_content = content[:match.start()] + NEW_CODE + content[match.end():]
        
        with open(FILE_PATH, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        print("✅ 替换完成！结构设计 prompt 已迁移到模块化调用")
        
        # 验证替换后的内容
        with open(FILE_PATH, 'r', encoding='utf-8') as f:
            verify = f.read()
        if 'StructureDesignPrompts.get_structure_prompt(' in verify:
            print("✅ 验证成功：已包含模块化调用")
        else:
            print("❌ 验证失败")
    else:
        print("❌ 未找到匹配内容，可能已经迁移或格式有变化")

if __name__ == '__main__':
    main()
