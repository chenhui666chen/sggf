#!/usr/bin/env python3
"""临时脚本：迁移人物设计 prompt 到模块化调用"""
import re

FILE_PATH = 'app/services/agents/agent_coordinator.py'

# 新的模块化调用代码
NEW_CODE = '''        if should_generate_characters:
            logger.info("👥 人物设计师正在生成人物...")
            
            # 🆕 使用模块化提示词生成人物设计 prompt
            char_extra = genre_module.get('character_extra_fields', '') or get_genre_character_fields(current_genre)
            char_prompt = CharacterDesignPrompts.get_character_prompt(
                concept=concept[:500] if concept else '',
                world_setting=world[:300] if world else '',
                requirement=requirement or "暂无特别要求",
                genre_extra_fields=char_extra
            )'''

def main():
    with open(FILE_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 使用正则表达式匹配整个 char_prompt 块
    # 从 "if should_generate_characters:" 到 """结束
    pattern = r'(        if should_generate_characters:\s+logger\.info\("👥 人物设计师正在生成人物\.\.\."\)\s+char_prompt = f""".*?请严格按照上述格式输出完整的主要人物设定，每个字段后必须换行。\{genre_module\.get\(\'character_extra_fields\', \'\'\)\}""")'
    
    match = re.search(pattern, content, re.DOTALL)
    if match:
        print(f"✅ 找到匹配内容，位置: {match.start()}-{match.end()}")
        print(f"   匹配长度: {len(match.group(1))} 字符")
        
        # 执行替换
        new_content = content[:match.start()] + NEW_CODE + content[match.end():]
        
        with open(FILE_PATH, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        print("✅ 替换完成！人物设计 prompt 已迁移到模块化调用")
        
        # 验证替换后的内容
        with open(FILE_PATH, 'r', encoding='utf-8') as f:
            verify = f.read()
        if 'CharacterDesignPrompts.get_character_prompt(' in verify:
            print("✅ 验证成功：已包含模块化调用")
        else:
            print("❌ 验证失败")
    else:
        print("❌ 未找到匹配内容，可能已经迁移或格式有变化")

if __name__ == '__main__':
    main()
