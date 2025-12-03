import sqlite3
from datetime import datetime

# 连接数据库
conn = sqlite3.connect('novel_app.db')
cursor = conn.cursor()

print("="*70)
print("📍 地点提取结果验证")
print("="*70)

# 1. 查询地图体系集合统计
cursor.execute("""
    SELECT sc.id, sc.name, sc.category, sc.project_id, COUNT(si.id) as item_count 
    FROM setting_collections sc 
    LEFT JOIN setting_items si ON sc.id = si.collection_id 
    WHERE sc.category = 'map_system' 
    GROUP BY sc.id
""")

collections = cursor.fetchall()
print(f"\n📊 地图体系集合概览:")
if collections:
    for coll in collections:
        coll_id, name, category, project_id, count = coll
        print(f"  ✓ 集合ID: {coll_id}")
        print(f"    名称: {name}")
        print(f"    项目ID: {project_id}")
        print(f"    包含地点数: {count}")
        print()
else:
    print("  ⚠️ 未找到地图体系集合")

# 2. 查询最近创建的地点（按创建时间倒序）
print("\n📍 最近创建的地点 (最多15个):")
print("-"*70)

cursor.execute("""
    SELECT si.id, si.name, si.depth, si.path, si.content, si.created_at,
           sc.name as collection_name
    FROM setting_items si
    JOIN setting_collections sc ON si.collection_id = sc.id
    WHERE sc.category = 'map_system'
    ORDER BY si.created_at DESC
    LIMIT 15
""")

locations = cursor.fetchall()
if locations:
    for i, loc in enumerate(locations, 1):
        loc_id, name, depth, path, content, created_at, coll_name = loc
        print(f"\n{i}. 【{name}】")
        print(f"   ID: {loc_id}")
        print(f"   层级: {depth}")
        print(f"   路径: {path or '(无)'}")
        print(f"   所属集合: {coll_name}")
        if content:
            preview = content[:100] + "..." if len(content) > 100 else content
            print(f"   描述: {preview}")
        print(f"   创建时间: {created_at[:19]}")
else:
    print("  ⚠️ 未找到地点记录")

# 3. 统计今天创建的地点数
today = datetime.now().strftime('%Y-%m-%d')
cursor.execute("""
    SELECT COUNT(*) 
    FROM setting_items si
    JOIN setting_collections sc ON si.collection_id = sc.id
    WHERE sc.category = 'map_system' 
    AND si.created_at LIKE ?
""", (f"{today}%",))

today_count = cursor.fetchone()[0]
print(f"\n📈 统计信息:")
print(f"  今天创建的地点数: {today_count}")

# 4. 按层级统计
cursor.execute("""
    SELECT si.depth, COUNT(*) as count
    FROM setting_items si
    JOIN setting_collections sc ON si.collection_id = sc.id
    WHERE sc.category = 'map_system'
    GROUP BY si.depth
    ORDER BY si.depth
""")

depth_stats = cursor.fetchall()
if depth_stats:
    print(f"\n  按层级分布:")
    for depth, count in depth_stats:
        print(f"    层级 {depth}: {count} 个地点")

conn.close()
print("\n" + "="*70)
print("✅ 查询完成")
print("="*70)
