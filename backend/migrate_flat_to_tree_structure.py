"""
将扁平的设定项数据迁移到树形结构
基于新的 hierarchy_config 自动创建父节点和分类节点
"""
import sqlite3
import os
import json
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.services.setting_templates import HIERARCHY_DEFAULTS

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "novel_app.db")


def migrate_collection_to_tree(cursor, collection_id, name, category, hierarchy_config_str):
    """将一个集合的数据从扁平结构迁移到树形结构"""
    
    if not hierarchy_config_str:
        print(f"   ⚠️ 没有层级配置，跳过")
        return 0
    
    try:
        hierarchy_config = json.loads(hierarchy_config_str)
    except:
        print(f"   ❌ 层级配置JSON解析失败")
        return 0
    
    max_depth = hierarchy_config.get("max_depth", 2)
    levels = hierarchy_config.get("levels", [])
    
    if max_depth == 2:
        # 2层结构：system → detail（扁平），无需迁移
        print(f"   ⏭️ 2层扁平结构，保持现状")
        return 0
    
    # 查询当前集合的所有设定项
    cursor.execute("""
        SELECT id, name, depth, path, is_leaf
        FROM setting_items
        WHERE collection_id = ?
        ORDER BY id
    """, (collection_id,))
    
    items = cursor.fetchall()
    
    if not items:
        print(f"   ℹ️ 无设定项数据")
        return 0
    
    # 检查是否已经有树形结构（depth > 1的非叶子节点）
    has_tree_structure = any(item[2] is not None and item[2] > 1 for item in items)
    
    if has_tree_structure:
        print(f"   ✅ 已有树形结构，跳过")
        return 0
    
    # 获取所有叶子节点（depth为None或1的设定项）
    leaf_items = [item for item in items if item[2] is None or item[2] <= 1]
    
    if not leaf_items:
        print(f"   ℹ️ 没有可迁移的叶子节点")
        return 0
    
    # 3层结构示例：system → category → detail
    # 我们需要创建category层
    
    if max_depth == 3 and len(levels) >= 3:
        # 获取第2层的配置
        level_2 = levels[1]
        examples = level_2.get("examples", [])
        category_name = level_2.get("name", "分类")
        
        if not examples:
            print(f"   ⚠️ 没有定义分类示例，无法自动迁移")
            return 0
        
        # 智能分类：根据设定项名称匹配分类
        migrated_count = 0
        
        # 为每个示例分类创建父节点
        for example in examples:
            # 创建分类节点（depth=2）
            cursor.execute("""
                INSERT INTO setting_items (
                    collection_id, name, code, level, tags, content, relations,
                    depth, node_type, is_leaf, path, summary, order
                ) VALUES (?, ?, '', NULL, NULL, '', NULL, 2, 'category', 0, ?, '', 0)
            """, (collection_id, example, f"/{name}/{example}"))
            
            category_node_id = cursor.lastrowid
            
            # 查找匹配此分类的叶子节点
            # 简单策略：名称包含关键词
            keywords = []
            if example == "突破丹药":
                keywords = ["破境", "筑基", "金丹", "元婴", "突破"]
            elif example == "恢复丹药":
                keywords = ["疗伤", "回春", "恢复", "补元"]
            elif example == "辅助丹药":
                keywords = ["增幅", "淬体", "固本", "培元"]
            elif example == "特殊丹药":
                keywords = ["毒", "解毒", "变化", "隐身"]
            # 功法分类
            elif example == "剑法":
                keywords = ["剑"]
            elif example == "刀法":
                keywords = ["刀"]
            elif example == "拳法":
                keywords = ["拳"]
            elif example == "掌法":
                keywords = ["掌"]
            elif example == "身法":
                keywords = ["身法", "轻功"]
            elif example == "心法":
                keywords = ["心法", "内功"]
            
            # 更新匹配的设定项
            for item in leaf_items:
                item_id, item_name, item_depth, item_path, is_leaf = item
                
                # 检查是否匹配关键词
                matches = any(keyword in item_name for keyword in keywords)
                
                if matches:
                    # 更新为树形结构
                    new_path = f"/{name}/{example}/{item_name}"
                    cursor.execute("""
                        UPDATE setting_items
                        SET depth = 3,
                            node_type = 'detail',
                            is_leaf = 1,
                            path = ?
                        WHERE id = ?
                    """, (new_path, item_id))
                    
                    migrated_count += 1
        
        if migrated_count > 0:
            print(f"   ✅ 成功迁移 {migrated_count} 个设定项到树形结构")
        else:
            print(f"   ⚠️ 没有找到可自动分类的设定项")
        
        return migrated_count
    
    elif max_depth == 4:
        print(f"   ℹ️ 4层结构需要手动创建（如地图体系）")
        return 0
    
    return 0


def migrate_all():
    """迁移所有需要更新的集合"""
    
    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库文件不存在: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        print("="*60)
        print("  🔄 开始将扁平数据迁移到树形结构")
        print("="*60)
        
        # 查询所有设定集合
        cursor.execute("""
            SELECT id, name, category, hierarchy_config
            FROM setting_collections
            ORDER BY id
        """)
        
        collections = cursor.fetchall()
        
        if not collections:
            print("\n⚠️ 数据库中没有设定集合")
            return
        
        print(f"\n📋 找到 {len(collections)} 个设定集合\n")
        
        total_migrated = 0
        
        for col_id, name, category, hierarchy_config in collections:
            print(f"{'─'*60}")
            print(f"📦 {name} (ID: {col_id}, 分类: {category or '未分类'})")
            
            migrated = migrate_collection_to_tree(
                cursor, col_id, name, category, hierarchy_config
            )
            
            total_migrated += migrated
        
        # 提交更改
        conn.commit()
        
        print(f"\n{'='*60}")
        print(f"  ✅ 迁移完成")
        print(f"{'='*60}")
        print(f"\n📊 统计:")
        print(f"   ✅ 共迁移: {total_migrated} 个设定项")
        
        if total_migrated > 0:
            print(f"\n🎉 成功迁移数据到树形结构！")
            print("\n⚠️ 注意:")
            print("   • 自动分类基于关键词匹配，可能不完全准确")
            print("   • 建议在前端检查分类结果，手动调整")
            print("   • 可以使用拖拽功能移动设定项到正确的分类")
        else:
            print("\n💡 所有集合都已是树形结构或无需迁移")
        
    except Exception as e:
        print(f"\n❌ 迁移失败: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║         🌳 扁平数据 → 树形结构 迁移工具                     ║
║                                                              ║
║  功能：基于 hierarchy_config 自动创建树形结构                ║
║  策略：使用关键词匹配自动分类                                ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    migrate_all()
