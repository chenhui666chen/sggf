"""
数据库迁移脚本：为 SettingItem 和 Character 表添加自动追踪字段

Phase 1: 基础关联 - 数据库Schema增强
"""
import sqlite3
import os

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "novel_app.db")

def migrate():
    """执行数据库迁移"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("🚀 开始数据库迁移...")
    
    try:
        # ==================== 1. SettingItem 表新增字段 ====================
        print("\n📋 Step 1: 为 setting_items 表添加自动追踪字段...")
        
        # 检查字段是否已存在（避免重复迁移）
        cursor.execute("PRAGMA table_info(setting_items)")
        existing_columns = {col[1] for col in cursor.fetchall()}
        
        if 'related_characters' not in existing_columns:
            cursor.execute("""
                ALTER TABLE setting_items 
                ADD COLUMN related_characters TEXT
            """)
            print("  ✅ 添加字段: related_characters")
        
        if 'referenced_chapters' not in existing_columns:
            cursor.execute("""
                ALTER TABLE setting_items 
                ADD COLUMN referenced_chapters TEXT
            """)
            print("  ✅ 添加字段: referenced_chapters")
        
        if 'usage_count' not in existing_columns:
            cursor.execute("""
                ALTER TABLE setting_items 
                ADD COLUMN usage_count INTEGER DEFAULT 0
            """)
            print("  ✅ 添加字段: usage_count")
        
        if 'last_referenced_at' not in existing_columns:
            cursor.execute("""
                ALTER TABLE setting_items 
                ADD COLUMN last_referenced_at TIMESTAMP
            """)
            print("  ✅ 添加字段: last_referenced_at")
        
        # ==================== 2. Character 表新增字段 ====================
        print("\n👤 Step 2: 为 characters 表添加体系关联字段...")
        
        cursor.execute("PRAGMA table_info(characters)")
        existing_columns = {col[1] for col in cursor.fetchall()}
        
        # 体系关联外键
        if 'faction_item_id' not in existing_columns:
            cursor.execute("""
                ALTER TABLE characters 
                ADD COLUMN faction_item_id INTEGER 
                REFERENCES setting_items(id) ON DELETE SET NULL
            """)
            print("  ✅ 添加字段: faction_item_id")
        
        if 'profession_item_id' not in existing_columns:
            cursor.execute("""
                ALTER TABLE characters 
                ADD COLUMN profession_item_id INTEGER 
                REFERENCES setting_items(id) ON DELETE SET NULL
            """)
            print("  ✅ 添加字段: profession_item_id")
        
        if 'race_item_id' not in existing_columns:
            cursor.execute("""
                ALTER TABLE characters 
                ADD COLUMN race_item_id INTEGER 
                REFERENCES setting_items(id) ON DELETE SET NULL
            """)
            print("  ✅ 添加字段: race_item_id")
        
        # JSON字段：功法/法宝/地点
        if 'techniques' not in existing_columns:
            cursor.execute("""
                ALTER TABLE characters 
                ADD COLUMN techniques TEXT
            """)
            print("  ✅ 添加字段: techniques (JSON)")
        
        if 'artifacts' not in existing_columns:
            cursor.execute("""
                ALTER TABLE characters 
                ADD COLUMN artifacts TEXT
            """)
            print("  ✅ 添加字段: artifacts (JSON)")
        
        if 'related_locations' not in existing_columns:
            cursor.execute("""
                ALTER TABLE characters 
                ADD COLUMN related_locations TEXT
            """)
            print("  ✅ 添加字段: related_locations (JSON)")
        
        # 自动维护字段：出场记录
        if 'first_mention_chapter_id' not in existing_columns:
            cursor.execute("""
                ALTER TABLE characters 
                ADD COLUMN first_mention_chapter_id INTEGER 
                REFERENCES chapters(id) ON DELETE SET NULL
            """)
            print("  ✅ 添加字段: first_mention_chapter_id")
        
        if 'last_appearance_chapter_id' not in existing_columns:
            cursor.execute("""
                ALTER TABLE characters 
                ADD COLUMN last_appearance_chapter_id INTEGER 
                REFERENCES chapters(id) ON DELETE SET NULL
            """)
            print("  ✅ 添加字段: last_appearance_chapter_id")
        
        if 'appearance_chapters' not in existing_columns:
            cursor.execute("""
                ALTER TABLE characters 
                ADD COLUMN appearance_chapters TEXT
            """)
            print("  ✅ 添加字段: appearance_chapters (JSON)")
        
        if 'relationship_network' not in existing_columns:
            cursor.execute("""
                ALTER TABLE characters 
                ADD COLUMN relationship_network TEXT
            """)
            print("  ✅ 添加字段: relationship_network (JSON)")
        
        # ==================== 3. 创建索引 ====================
        print("\n🔍 Step 3: 创建索引以提升查询性能...")
        
        try:
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_characters_faction_item_id 
                ON characters(faction_item_id)
            """)
            print("  ✅ 创建索引: idx_characters_faction_item_id")
        except Exception as e:
            print(f"  ⚠️ 索引已存在或创建失败: {e}")
        
        try:
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_characters_profession_item_id 
                ON characters(profession_item_id)
            """)
            print("  ✅ 创建索引: idx_characters_profession_item_id")
        except Exception as e:
            print(f"  ⚠️ 索引已存在或创建失败: {e}")
        
        try:
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_characters_race_item_id 
                ON characters(race_item_id)
            """)
            print("  ✅ 创建索引: idx_characters_race_item_id")
        except Exception as e:
            print(f"  ⚠️ 索引已存在或创建失败: {e}")
        
        try:
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_characters_first_mention_chapter_id 
                ON characters(first_mention_chapter_id)
            """)
            print("  ✅ 创建索引: idx_characters_first_mention_chapter_id")
        except Exception as e:
            print(f"  ⚠️ 索引已存在或创建失败: {e}")
        
        try:
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_characters_last_appearance_chapter_id 
                ON characters(last_appearance_chapter_id)
            """)
            print("  ✅ 创建索引: idx_characters_last_appearance_chapter_id")
        except Exception as e:
            print(f"  ⚠️ 索引已存在或创建失败: {e}")
        
        # 提交事务
        conn.commit()
        print("\n✅ 数据库迁移成功完成！")
        
        # 验证字段
        print("\n🔍 验证 setting_items 表结构:")
        cursor.execute("PRAGMA table_info(setting_items)")
        for col in cursor.fetchall():
            if col[1] in ['related_characters', 'referenced_chapters', 'usage_count', 'last_referenced_at']:
                print(f"  ✓ {col[1]}: {col[2]}")
        
        print("\n🔍 验证 characters 表结构:")
        cursor.execute("PRAGMA table_info(characters)")
        for col in cursor.fetchall():
            if col[1] in ['faction_item_id', 'profession_item_id', 'race_item_id', 
                          'techniques', 'artifacts', 'related_locations',
                          'first_mention_chapter_id', 'last_appearance_chapter_id', 
                          'appearance_chapters', 'relationship_network']:
                print(f"  ✓ {col[1]}: {col[2]}")
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ 迁移失败: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
