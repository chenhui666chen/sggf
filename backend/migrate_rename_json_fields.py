"""
数据库迁移脚本：重命名Character模型的JSON字段

原因：避免字段名与relationship名称冲突
- techniques → techniques_json
- artifacts → artifacts_json
- related_locations → related_locations_json
"""
import sys
from pathlib import Path

# 添加backend目录到Python路径
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from app.db.base import get_db, engine
from sqlalchemy import text

def main():
    print("🔧 开始数据库迁移：重命名Character JSON字段")
    
    with engine.connect() as conn:
        # 检查表是否存在
        result = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='characters'"
        ))
        if not result.fetchone():
            print("⚠️  characters表不存在，跳过迁移")
            return
        
        # 检查旧字段是否存在
        result = conn.execute(text("PRAGMA table_info(characters)"))
        columns = {row[1] for row in result.fetchall()}
        
        print(f"📋 当前字段: {columns}")
        
        # 如果新字段已存在，说明已迁移
        if 'techniques_json' in columns:
            print("✅ 新字段已存在，无需迁移")
            return
        
        print("\n🔄 执行字段重命名...")
        
        # SQLite不支持直接ALTER COLUMN RENAME，需要重建表
        # 但我们可以用简单的ALTER TABLE ADD + UPDATE + DROP方案
        
        try:
            # 1. 添加新字段
            conn.execute(text("""
                ALTER TABLE characters ADD COLUMN techniques_json TEXT
            """))
            conn.execute(text("""
                ALTER TABLE characters ADD COLUMN artifacts_json TEXT
            """))
            conn.execute(text("""
                ALTER TABLE characters ADD COLUMN related_locations_json TEXT
            """))
            conn.commit()
            print("✅ 新字段已添加")
            
            # 2. 复制数据
            conn.execute(text("""
                UPDATE characters 
                SET techniques_json = techniques,
                    artifacts_json = artifacts,
                    related_locations_json = related_locations
            """))
            conn.commit()
            print("✅ 数据已复制")
            
            # 3. 删除旧字段（SQLite需要重建表，这里我们保留旧字段）
            print("⚠️  SQLite不支持DROP COLUMN，旧字段将保留")
            print("   建议：在确认数据无误后，手动删除旧字段或重建表")
            
            print("\n✅ 迁移完成！")
            print("📝 新字段名称：")
            print("   - techniques_json")
            print("   - artifacts_json") 
            print("   - related_locations_json")
            
        except Exception as e:
            print(f"❌ 迁移失败: {e}")
            conn.rollback()
            raise

if __name__ == "__main__":
    main()
