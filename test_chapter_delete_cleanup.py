"""
测试章节删除时清理追踪数据的功能

测试场景：
1. 创建测试数据：章节、人物、设定项
2. 建立追踪关系（人物出场、设定引用）
3. 删除章节
4. 验证追踪数据是否正确清理
"""

import sqlite3
import json
from datetime import datetime

DB_PATH = 'novel_app.db'

def print_section(title):
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70)

def setup_test_data():
    """准备测试数据"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print_section("📝 准备测试数据")
    
    # 1. 查找项目ID
    cursor.execute("SELECT id FROM projects LIMIT 1")
    project = cursor.fetchone()
    if not project:
        print("  ⚠️  未找到项目，请先创建项目")
        conn.close()
        return None
    
    project_id = project[0]
    print(f"  ✓ 使用项目ID: {project_id}")
    
    # 2. 创建测试章节
    cursor.execute("""
        INSERT INTO chapters (project_id, chapter_number, title, content, word_count, status)
        VALUES (?, 999, '测试章节999', '测试角色A出场了。使用了测试功法。', 20, 'draft')
    """, (project_id,))
    
    test_chapter_id = cursor.lastrowid
    print(f"  ✓ 创建测试章节: ID={test_chapter_id}, 章节号=999")
    
    # 3. 创建或查找测试人物
    cursor.execute("""
        SELECT id FROM characters WHERE name = '测试角色A' AND project_id = ?
    """, (project_id,))
    character = cursor.fetchone()
    
    if character:
        character_id = character[0]
        print(f"  ✓ 找到已存在的测试角色: ID={character_id}")
    else:
        cursor.execute("""
            INSERT INTO characters (project_id, name, appearance_chapters, first_mention_chapter_id, last_appearance_chapter_id)
            VALUES (?, '测试角色A', ?, ?, ?)
        """, (project_id, json.dumps([test_chapter_id]), test_chapter_id, test_chapter_id))
        character_id = cursor.lastrowid
        print(f"  ✓ 创建测试角色: ID={character_id}")
    
    # 更新人物的出场章节列表（确保包含测试章节）
    cursor.execute("SELECT appearance_chapters FROM characters WHERE id = ?", (character_id,))
    result = cursor.fetchone()
    appearance_chapters = json.loads(result[0]) if result[0] else []
    if test_chapter_id not in appearance_chapters:
        appearance_chapters.append(test_chapter_id)
        cursor.execute("""
            UPDATE characters 
            SET appearance_chapters = ?,
                first_mention_chapter_id = ?,
                last_appearance_chapter_id = ?
            WHERE id = ?
        """, (json.dumps(appearance_chapters), min(appearance_chapters), max(appearance_chapters), character_id))
        print(f"  ✓ 更新角色出场章节: {appearance_chapters}")
    
    # 4. 创建或查找测试设定项
    cursor.execute("""
        SELECT id FROM setting_collections WHERE project_id = ? LIMIT 1
    """, (project_id,))
    collection = cursor.fetchone()
    
    if not collection:
        cursor.execute("""
            INSERT INTO setting_collections (project_id, name, category, max_depth)
            VALUES (?, '测试集合', 'test_system', 2)
        """)
        collection_id = cursor.lastrowid
        print(f"  ✓ 创建测试设定集合: ID={collection_id}")
    else:
        collection_id = collection[0]
        print(f"  ✓ 使用已存在的设定集合: ID={collection_id}")
    
    cursor.execute("""
        SELECT id FROM setting_items WHERE name = '测试功法' AND collection_id = ?
    """, (collection_id,))
    setting = cursor.fetchone()
    
    if setting:
        setting_id = setting[0]
        print(f"  ✓ 找到已存在的测试设定: ID={setting_id}")
    else:
        cursor.execute("""
            INSERT INTO setting_items (collection_id, name, referenced_chapters, usage_count)
            VALUES (?, '测试功法', ?, 1)
        """, (collection_id, json.dumps([test_chapter_id])))
        setting_id = cursor.lastrowid
        print(f"  ✓ 创建测试设定: ID={setting_id}")
    
    # 更新设定项的引用章节列表（确保包含测试章节）
    cursor.execute("SELECT referenced_chapters FROM setting_items WHERE id = ?", (setting_id,))
    result = cursor.fetchone()
    referenced_chapters = json.loads(result[0]) if result[0] else []
    if test_chapter_id not in referenced_chapters:
        referenced_chapters.append(test_chapter_id)
        cursor.execute("""
            UPDATE setting_items 
            SET referenced_chapters = ?,
                usage_count = ?
            WHERE id = ?
        """, (json.dumps(referenced_chapters), len(referenced_chapters), setting_id))
        print(f"  ✓ 更新设定引用章节: {referenced_chapters}")
    
    conn.commit()
    conn.close()
    
    return {
        'project_id': project_id,
        'chapter_id': test_chapter_id,
        'chapter_number': 999,
        'character_id': character_id,
        'setting_id': setting_id
    }

def check_before_delete(test_data):
    """删除前检查数据状态"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print_section("🔍 删除前数据检查")
    
    # 检查章节
    cursor.execute("SELECT id, chapter_number, title FROM chapters WHERE id = ?", 
                   (test_data['chapter_id'],))
    chapter = cursor.fetchone()
    print(f"\n📄 章节状态:")
    if chapter:
        print(f"  ✓ 章节存在: ID={chapter[0]}, 章节号={chapter[1]}, 标题={chapter[2]}")
    else:
        print(f"  ✗ 章节不存在")
    
    # 检查人物追踪数据
    cursor.execute("""
        SELECT appearance_chapters, first_mention_chapter_id, last_appearance_chapter_id 
        FROM characters WHERE id = ?
    """, (test_data['character_id'],))
    character = cursor.fetchone()
    print(f"\n👤 人物追踪数据:")
    if character:
        appearance_chapters = json.loads(character[0]) if character[0] else []
        print(f"  出场章节列表: {appearance_chapters}")
        print(f"  首次提及: {character[1]}")
        print(f"  最后出场: {character[2]}")
        print(f"  包含测试章节: {'✓' if test_data['chapter_id'] in appearance_chapters else '✗'}")
    
    # 检查设定追踪数据
    cursor.execute("""
        SELECT referenced_chapters, usage_count 
        FROM setting_items WHERE id = ?
    """, (test_data['setting_id'],))
    setting = cursor.fetchone()
    print(f"\n⚙️ 设定追踪数据:")
    if setting:
        referenced_chapters = json.loads(setting[0]) if setting[0] else []
        print(f"  引用章节列表: {referenced_chapters}")
        print(f"  使用次数: {setting[1]}")
        print(f"  包含测试章节: {'✓' if test_data['chapter_id'] in referenced_chapters else '✗'}")
    
    conn.close()

def check_after_delete(test_data):
    """删除后检查数据状态"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print_section("✅ 删除后数据验证")
    
    # 检查章节
    cursor.execute("SELECT id FROM chapters WHERE id = ?", (test_data['chapter_id'],))
    chapter = cursor.fetchone()
    print(f"\n📄 章节状态:")
    if chapter:
        print(f"  ✗ 章节仍存在（删除失败）")
    else:
        print(f"  ✓ 章节已删除")
    
    # 检查人物追踪数据
    cursor.execute("""
        SELECT appearance_chapters, first_mention_chapter_id, last_appearance_chapter_id 
        FROM characters WHERE id = ?
    """, (test_data['character_id'],))
    character = cursor.fetchone()
    print(f"\n👤 人物追踪数据:")
    if character:
        appearance_chapters = json.loads(character[0]) if character[0] else []
        print(f"  出场章节列表: {appearance_chapters}")
        print(f"  首次提及: {character[1]}")
        print(f"  最后出场: {character[2]}")
        
        if test_data['chapter_id'] in appearance_chapters:
            print(f"  ❌ 测试章节仍在列表中（清理失败）")
        else:
            print(f"  ✅ 测试章节已从列表中移除")
    
    # 检查设定追踪数据
    cursor.execute("""
        SELECT referenced_chapters, usage_count 
        FROM setting_items WHERE id = ?
    """, (test_data['setting_id'],))
    setting = cursor.fetchone()
    print(f"\n⚙️ 设定追踪数据:")
    if setting:
        referenced_chapters = json.loads(setting[0]) if setting[0] else []
        print(f"  引用章节列表: {referenced_chapters}")
        print(f"  使用次数: {setting[1]}")
        
        if test_data['chapter_id'] in referenced_chapters:
            print(f"  ❌ 测试章节仍在列表中（清理失败）")
        else:
            print(f"  ✅ 测试章节已从列表中移除")
    
    conn.close()

def main():
    print("\n" + "🧪 章节删除追踪数据清理功能测试".center(70, "="))
    print("此测试会创建测试数据，然后通过API删除章节并验证清理结果")
    print("="*70)
    
    # 1. 准备测试数据
    test_data = setup_test_data()
    if not test_data:
        return
    
    # 2. 删除前检查
    check_before_delete(test_data)
    
    # 3. 提示用户
    print_section("⚠️ 准备删除测试章节")
    print(f"\n请执行以下操作：")
    print(f"  1. 确保后端服务正在运行")
    print(f"  2. 在前端或通过API删除章节 ID={test_data['chapter_id']} (章节号999)")
    print(f"  3. 观察后端日志，应该能看到以下输出：")
    print(f"     - 🧹 清理人物追踪数据...")
    print(f"     - ✅ 已清理 X 个人物的追踪数据")
    print(f"     - 🧹 清理设定追踪数据...")
    print(f"     - ✅ 已清理 X 个设定项的追踪数据")
    print(f"\n删除完成后，按Enter键继续验证...")
    input()
    
    # 4. 删除后检查
    check_after_delete(test_data)
    
    print_section("🎉 测试完成")

if __name__ == "__main__":
    main()
