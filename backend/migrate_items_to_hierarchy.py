"""
迁移现有设定项数据到新的层级结构

问题：现有setting_items的depth/node_type/is_leaf/path字段都是None
解决：根据collection的hierarchy_config，为现有数据设置正确的层级信息

层级规则（以4层体系为例）：
- depth=1: 体系根节点（不存储在setting_items中）
- depth=2: 分类节点 (category)
- depth=3: 列表/等级节点 (list)
- depth=4: 详情节点 (detail, is_leaf=True)

对于现有的扁平数据，我们将它们视为最终层级的叶子节点
"""
import sqlite3
import os
import json

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "novel_app.db")

def migrate_items():
    """迁移设定项数据到新的层级结构"""
    
    if not os.path.exists(DB_PATH):
        print(f"数据库文件不存在: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        print("=" * 60)
        print("  设定项层级数据迁移工具")
        print("=" * 60)
        
        # 获取所有设定集合
        cursor.execute("""
            SELECT id, name, category, hierarchy_config, max_depth
            FROM setting_collections
        """)
        collections = cursor.fetchall()
        
        total_updated = 0
        
        for col_id, col_name, category, hierarchy_config, max_depth in collections:
            print(f"\n处理集合: {col_name} (ID={col_id}, category={category})")
            
            # 解析层级配置
            if hierarchy_config:
                try:
                    config = json.loads(hierarchy_config)
                    target_depth = config.get('max_depth', 2)
                    levels = config.get('levels', [])
                except:
                    target_depth = max_depth or 2
                    levels = []
            else:
                target_depth = max_depth or 2
                levels = []
            
            print(f"  层级深度: {target_depth}")
            
            # 获取该集合的所有设定项
            cursor.execute("""
                SELECT id, name, depth, path, node_type, is_leaf
                FROM setting_items
                WHERE collection_id = ?
            """, (col_id,))
            
            items = cursor.fetchall()
            
            if not items:
                print("  无设定项，跳过")
                continue
            
            print(f"  设定项数量: {len(items)}")
            
            # 更新每个设定项
            updated_count = 0
            for item_id, item_name, depth, path, node_type, is_leaf in items:
                # 检查是否需要更新（字段为空）
                needs_update = depth is None or node_type is None or is_leaf is None or path is None
                
                if needs_update:
                    # 设置为叶子节点（详情层）
                    new_depth = target_depth  # 最深层
                    new_node_type = 'detail'
                    new_is_leaf = 1
                    new_path = f"/{col_name}/{item_name}"
                    
                    cursor.execute("""
                        UPDATE setting_items
                        SET depth = ?,
                            node_type = ?,
                            is_leaf = ?,
                            path = ?
                        WHERE id = ?
                    """, (new_depth, new_node_type, new_is_leaf, new_path, item_id))
                    
                    updated_count += 1
            
            if updated_count > 0:
                print(f"  已更新 {updated_count} 个设定项")
                total_updated += updated_count
            else:
                print(f"  所有设定项已有层级数据，跳过")
        
        conn.commit()
        
        print("\n" + "=" * 60)
        print(f"迁移完成！共更新 {total_updated} 个设定项")
        print("=" * 60)
        
    except Exception as e:
        print(f"迁移失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate_items()
