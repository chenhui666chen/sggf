"""检查丹药体系的实际数据"""
import sqlite3
import os
import json

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "novel_app.db")

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# 查找丹药体系
cursor.execute("""
    SELECT id, name, category, max_depth, hierarchy_config
    FROM setting_collections
    WHERE name LIKE '%丹药%'
    ORDER BY id
""")

collections = cursor.fetchall()

print("="*60)
print("  丹药体系集合信息")
print("="*60)

for col_id, name, category, max_depth, hierarchy_config in collections:
    print(f"\n📦 {name} (ID: {col_id})")
    print(f"   分类: {category}")
    print(f"   最大深度: {max_depth}")
    
    if hierarchy_config:
        config = json.loads(hierarchy_config)
        print(f"   层级配置:")
        for level in config.get('levels', []):
            leaf_mark = " [叶子]" if level.get('leaf') else ""
            examples = level.get('examples', [])
            examples_str = f" - 示例: {', '.join(examples)}" if examples else ""
            print(f"      • 第{level['depth']}层: {level['name']} ({level['type']}){leaf_mark}{examples_str}")
    
    # 查询该集合的设定项
    cursor.execute("""
        SELECT id, name, depth, node_type, is_leaf, path
        FROM setting_items
        WHERE collection_id = ?
        ORDER BY depth, id
    """, (col_id,))
    
    items = cursor.fetchall()
    
    print(f"\n   设定项 ({len(items)}个):")
    for item_id, item_name, depth, node_type, is_leaf, path in items:
        depth_str = f"第{depth}层" if depth else "未设置"
        leaf_str = "🍃叶子" if is_leaf else "📁非叶子"
        print(f"      [{depth_str}] {leaf_str} {item_name}")
        if path:
            print(f"              路径: {path}")

conn.close()
