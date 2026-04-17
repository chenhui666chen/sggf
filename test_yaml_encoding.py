#!/usr/bin/env python
"""测试 YAML 文件编码和加载"""
import chardet

# 检测文件编码
print("检测文件编码...")
with open('config/models.yaml', 'rb') as f:
    raw_data = f.read(100000)  # 读取前 100KB
    result = chardet.detect(raw_data)
    print(f"检测结果：{result}")

# 尝试用不同编码加载
encodings_to_try = ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'cp936']

for encoding in encodings_to_try:
    try:
        with open('config/models.yaml', 'r', encoding=encoding) as f:
            content = f.read()
        print(f"✓ {encoding}: 成功读取 {len(content)} 字符")
        
        # 尝试解析 YAML
        import yaml
        data = yaml.safe_load(content)
        print(f"  YAML 解析成功：{len(data)} 个模型")
        
        # 查找 Vidu 模型
        vidu_models = [m for m in data if 'vidu' in str(m.get('id', ''))]
        print(f"  Vidu 模型：{len(vidu_models)} 个")
        break
    except Exception as e:
        print(f"✗ {encoding}: {e}")
