#!/usr/bin/env python3
"""
修复best_prompts.json中的第一人称要求
将"严格采用第一人称'我'"修改为"严格采用原文人称视角"
"""
import json

# 读取JSON文件
with open(r'c:\Users\cuigu\novel_writing_agent\data\prompt_evolution\best_prompts.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 要查找和替换的文本
old_text = '严格采用第一人称"我"。你只能描写"我"'
new_text = '严格采用原文人称视角（若原文为第一人称则保持"我"，若为第三人称则使用主角名字或"他/她"）。你只能描写主角'

# 第二处修改
old_text2 = '核心是“用‘我’的粗粝语言讲故事”'
new_text2 = '核心是“用主角的粗粝语言讲故事”'

# 第三处修改
old_text3 = '绝不可退回客观叙述**。必须用“我”的粗粝语言进行重构'
new_text3 = '绝不可退回客观叙述**。必须用主角的粗粝语言进行重构'

# 第四处修改  
old_text4 = '绝不可退回客观叙述**。必须用“我”的粗粝语言进行重构'
new_text4 = '绝不可退回客观叙述**。必须用主角的粗粝语言进行重构'

# 统计修改次数
count = 0

# 遍历所有版本并替换
for version in data:
    if 'prompt_text' in version:
        original = version['prompt_text']
        modified = original
        
        if old_text in modified:
            modified = modified.replace(old_text, new_text)
            count += 1
            print(f"✓ 修改版本 {version.get('version_id', 'unknown')} - 主视角")
            
        if old_text2 in modified:
            modified = modified.replace(old_text2, new_text2)
            print(f"  ✓ 修改示例文字1")
            
        if old_text3 in modified:
            modified = modified.replace(old_text3, new_text3)
            print(f"  ✓ 修改示例文字2")
        
        version['prompt_text'] = modified

# 保存修改后的文件
with open(r'c:\Users\cuigu\novel_writing_agent\data\prompt_evolution\best_prompts.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"\n✅ 完成！共修改 {count} 个提示词版本")
