"""检查数据库结构和现有数据"""
import sqlite3
import os
import json

# 检查所有可能的数据库路径
db_paths = [
    "novel_app.db",
    "../novel_app.db",
    "app.db",
    "novel_writing.db"
]

for db_path in db_paths:
    if os.path.exists(db_path):
        print(f"\n{'='*60}")
        print(f"数据库: {db_path}")
        print(f"大小: {os.path.getsize(db_path) / 1024:.1f} KB")
        print('='*60)
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 获取所有表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cursor.fetchall()]
        print(f"表: {tables}")
        
        # 如果有setting_items表，查看数据
        if 'setting_items' in tables:
            print("\n--- setting_items 数据 ---")
            cursor.execute("SELECT id, collection_id, name, depth, path, node_type, is_leaf FROM setting_items LIMIT 15")
            rows = cursor.fetchall()
            for r in rows:
                print(f"  ID={r[0]}, col={r[1]}, name={r[2]}, depth={r[3]}, type={r[5]}, leaf={r[6]}")
                if r[4]:
                    print(f"      path: {r[4]}")
        
        if 'setting_collections' in tables:
            print("\n--- setting_collections 数据 ---")
            cursor.execute("SELECT id, name, category, hierarchy_config FROM setting_collections LIMIT 10")
            cols = cursor.fetchall()
            for c in cols:
                cfg_preview = c[3][:80] + "..." if c[3] and len(c[3]) > 80 else c[3]
                print(f"  ID={c[0]}, name={c[1]}, category={c[2]}")
                if c[3]:
                    try:
                        config = json.loads(c[3])
                        print(f"      max_depth={config.get('max_depth')}, levels={len(config.get('levels', []))}")
                    except:
                        pass
        
        conn.close()
