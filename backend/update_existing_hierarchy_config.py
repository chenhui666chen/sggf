"""
更新现有设定集合的层级配置
将新的 HIERARCHY_DEFAULTS 配置应用到数据库中已存在的集合
"""
import sqlite3
import os
import json
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(__file__))

from app.services.setting_templates import HIERARCHY_DEFAULTS, get_hierarchy_config_json

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "novel_app.db")


def update_hierarchy_configs():
    """更新所有设定集合的层级配置"""
    
    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库文件不存在: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        print("="*60)
        print("  🔄 开始更新现有集合的层级配置")
        print("="*60)
        
        # 查询所有设定集合
        cursor.execute("""
            SELECT id, name, category, max_depth, hierarchy_config
            FROM setting_collections
            ORDER BY id
        """)
        
        collections = cursor.fetchall()
        
        if not collections:
            print("\n⚠️ 数据库中没有设定集合")
            return
        
        print(f"\n📋 找到 {len(collections)} 个设定集合\n")
        
        updated_count = 0
        skipped_count = 0
        
        for col_id, name, category, max_depth, hierarchy_config in collections:
            print(f"{'─'*60}")
            print(f"📦 {name} (ID: {col_id})")
            print(f"   分类: {category or '未分类'}")
            
            # 如果category存在且在HIERARCHY_DEFAULTS中
            if category and category in HIERARCHY_DEFAULTS:
                new_config = HIERARCHY_DEFAULTS[category]
                new_max_depth = new_config["max_depth"]
                new_hierarchy_config = json.dumps(new_config, ensure_ascii=False)
                
                # 检查是否需要更新
                current_config_dict = None
                if hierarchy_config:
                    try:
                        current_config_dict = json.loads(hierarchy_config)
                    except:
                        pass
                
                needs_update = (
                    max_depth != new_max_depth or 
                    current_config_dict != new_config
                )
                
                if needs_update:
                    # 更新配置
                    cursor.execute("""
                        UPDATE setting_collections
                        SET max_depth = ?,
                            hierarchy_config = ?
                        WHERE id = ?
                    """, (new_max_depth, new_hierarchy_config, col_id))
                    
                    print(f"   ✅ 已更新:")
                    print(f"      最大深度: {max_depth} → {new_max_depth}")
                    print(f"      层级配置: 已注入 {len(new_config['levels'])} 层定义")
                    
                    # 显示层级结构
                    for level in new_config['levels']:
                        leaf_mark = " [叶子]" if level.get('leaf') else ""
                        print(f"        • 第{level['depth']}层: {level['name']} ({level['type']}){leaf_mark}")
                    
                    updated_count += 1
                else:
                    print(f"   ⏭️ 配置已是最新，跳过")
                    skipped_count += 1
            else:
                print(f"   ⚠️ 未找到对应的层级配置模板")
                print(f"      分类 '{category}' 不在 HIERARCHY_DEFAULTS 中")
                skipped_count += 1
        
        # 提交更改
        conn.commit()
        
        print(f"\n{'='*60}")
        print(f"  ✅ 更新完成")
        print(f"{'='*60}")
        print(f"\n📊 统计:")
        print(f"   ✅ 已更新: {updated_count} 个集合")
        print(f"   ⏭️ 已跳过: {skipped_count} 个集合")
        print(f"   📦 总计:   {len(collections)} 个集合")
        
        if updated_count > 0:
            print(f"\n🎉 成功更新 {updated_count} 个集合的层级配置！")
            print("\n📖 下一步:")
            print("   1. 重启后端服务")
            print("   2. 刷新前端页面")
            print("   3. 打开'世界观设定'查看树形结构")
        else:
            print("\n💡 所有集合的配置都已是最新，无需更新")
        
    except Exception as e:
        print(f"\n❌ 更新失败: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║         🔧 层级配置数据库更新工具                           ║
║                                                              ║
║  功能：将新的层级配置应用到现有的设定集合                    ║
║  适用：已有项目和设定数据的情况                              ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    update_hierarchy_configs()
