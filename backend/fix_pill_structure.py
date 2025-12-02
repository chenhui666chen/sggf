"""
专门修复丹药、功法等3层体系的数据结构
为缺失的中间分类节点创建占位符，并正确组织现有数据
"""
import sqlite3
import os
import json
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.services.setting_templates import HIERARCHY_DEFAULTS

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "novel_app.db")


def fix_3level_structure(cursor, collection_id, name, category):
    """修复3层体系的结构"""
    
    if category not in HIERARCHY_DEFAULTS:
        return 0
    
    config = HIERARCHY_DEFAULTS[category]
    
    if config["max_depth"] != 3:
        return 0
    
    # 获取第2层的分类配置
    level_2 = config["levels"][1]
    examples = level_2.get("examples", [])
    
    if not examples:
        print(f"   ⚠️ 没有定义分类示例")
        return 0
    
    # 查询现有的设定项
    cursor.execute("""
        SELECT id, name, depth, path, node_type, is_leaf
        FROM setting_items
        WHERE collection_id = ?
        ORDER BY id
    """, (collection_id,))
    
    items = cursor.fetchall()
    
    # 按 depth 分组
    depth_map = {}
    for item in items:
        item_id, item_name, depth, path, node_type, is_leaf = item
        if depth not in depth_map:
            depth_map[depth] = []
        depth_map[depth].append(item)
    
    # 检查是否已经有第2层分类节点
    if 2 in depth_map:
        # 有第2层节点，检查是否是分类节点
        has_category_nodes = any(
            item[4] == 'category' and not item[5]  # node_type == 'category' and not is_leaf
            for item in depth_map[2]
        )
        
        if has_category_nodes:
            print(f"   ✅ 已有分类节点，跳过")
            return 0
    
    # 创建默认分类节点
    print(f"   🔧 开始修复3层结构...")
    
    # 第一步：创建"未分类"节点作为默认分类
    default_category = "未分类"
    cursor.execute("""
        INSERT INTO setting_items (
            collection_id, name, code, level, tags, content, relations,
            depth, node_type, is_leaf, path, summary, `order`,
            created_at, updated_at
        ) VALUES (?, ?, '', NULL, NULL, '自动创建的默认分类', NULL, 2, 'category', 0, ?, '', 0, datetime('now'), datetime('now'))
    """, (collection_id, default_category, f"/{name}/{default_category}"))
    
    default_category_id = cursor.lastrowid
    
    # 第二步：将所有现有的叶子节点移动到"未分类"下
    moved_count = 0
    
    for item in items:
        item_id, item_name, depth, path, node_type, is_leaf = item
        
        # 只处理叶子节点
        if not is_leaf:
            continue
        
        # 如果已经是第3层，跳过
        if depth == 3:
            continue
        
        # 更新路径和深度
        new_path = f"/{name}/{default_category}/{item_name}"
        cursor.execute("""
            UPDATE setting_items
            SET depth = 3,
                node_type = 'detail',
                path = ?
            WHERE id = ?
        """, (new_path, item_id))
        
        moved_count += 1
    
    print(f"   ✅ 创建了默认分类节点: {default_category}")
    print(f"   ✅ 移动了 {moved_count} 个设定项到'未分类'")
    
    return 1


def fix_all_3level_collections():
    """修复所有3层体系的集合"""
    
    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库文件不存在: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        print("="*60)
        print("  🔧 修复3层体系的数据结构")
        print("="*60)
        
        # 查询所有max_depth=3的集合
        cursor.execute("""
            SELECT id, name, category
            FROM setting_collections
            WHERE max_depth = 3
            ORDER BY id
        """)
        
        collections = cursor.fetchall()
        
        if not collections:
            print("\n⚠️ 没有找到3层体系的集合")
            return
        
        print(f"\n📋 找到 {len(collections)} 个3层体系集合\n")
        
        fixed_count = 0
        
        for col_id, name, category in collections:
            print(f"{'─'*60}")
            print(f"📦 {name} (ID: {col_id}, 分类: {category or '未分类'})")
            
            if category:
                fixed = fix_3level_structure(cursor, col_id, name, category)
                fixed_count += fixed
            else:
                print(f"   ⚠️ 没有分类信息，跳过")
        
        # 提交更改
        conn.commit()
        
        print(f"\n{'='*60}")
        print(f"  ✅ 修复完成")
        print(f"{'='*60}")
        print(f"\n📊 统计:")
        print(f"   ✅ 已修复: {fixed_count} 个集合")
        
        if fixed_count > 0:
            print(f"\n🎉 成功修复数据结构！")
            print("\n📖 下一步:")
            print("　　1. 刷新前端页面")
            print("　　2. 打开'世界观设定'查看树形结构")
            print("　　3. 手动将设定项拖拽到正确的分类（如'突破丹药'、'恢复丹药'）")
            print("　　4. 可以删除'未分类'节点")
        else:
            print("\n💡 所有集合的结构都已正确")
        
    except Exception as e:
        print(f"\n❌ 修复失败: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║         🔧 3层体系结构修复工具                              ║
║                                                              ║
║  功能：为缺失分类节点的3层体系创建默认分类                  ║
║  策略：创建"未分类"节点，用户后续可手动调整                 ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    fix_all_3level_collections()
