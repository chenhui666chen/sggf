import re

# 测试正则
pattern = re.compile(r'^(#+\s*)?[【\[]?第([0-9]+)卷[】\]]?[：:]?')  # 🔧 添加 ? 使冒号可选

test_lines = [
    '【第1卷】初露锋芒（预计80-100章）',
    '## 第1卷：初露锋芒',
    '第1卷：初露锋芒',
    '[第1卷]初露锋芒'
]

for line in test_lines:
    match = pattern.match(line)
    if match:
        print(f'✅ {line[:40]} → 匹配，卷号={match.group(2)}')
    else:
        print(f'❌ {line[:40]} → 不匹配')
