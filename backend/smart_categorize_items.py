"""
智能分类工具：根据设定项名称自动匹配到正确的分类
删除"未分类"节点，创建实际的分类节点
"""
import sqlite3
import os
import json
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.services.setting_templates import HIERARCHY_DEFAULTS

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "novel_app.db")


# 智能分类规则：根据设定项名称匹配分类
CATEGORY_KEYWORDS = {
    # 丹药体系
    "pill_system": {
        "突破丹药": ["破境", "筑基", "金丹", "元婴", "化神", "突破", "进阶"],
        "恢复丹药": ["疗伤", "回春", "恢复", "补元", "续命", "生机"],
        "辅助丹药": ["增幅", "淬体", "固本", "培元", "养气", "凝神"],
        "特殊丹药": ["毒", "解毒", "变化", "隐身", "易容", "驻颜"],
    },
    # 功法体系
    "technique_system": {
        "剑法": ["剑", "剑诀", "剑经"],
        "刀法": ["刀", "刀诀", "刀谱"],
        "拳法": ["拳", "拳经", "拳谱"],
        "掌法": ["掌", "掌经", "掌法"],
        "身法": ["身法", "轻功", "遁法", "步法"],
        "心法": ["心法", "内功", "功法", "经"],
    },
    # 阵法体系
    "formation_system": {
        "攻击阵法": ["杀", "攻", "灭", "破", "斩", "剑阵"],
        "防御阵法": ["护", "防", "守", "盾", "壁"],
        "困敌阵法": ["困", "封", "锁", "禁", "囚"],
        "辅助阵法": ["聚灵", "传送", "隐匿", "幻", "迷"],
    },
    # 符箓体系
    "talisman_system": {
        "攻击符箓": ["火", "雷", "冰", "剑", "杀", "爆"],
        "防御符箓": ["护", "盾", "金刚", "不坏"],
        "辅助符箓": ["神行", "隐身", "通灵", "破幻"],
        "特殊符箓": ["传送", "破禁", "收妖", "镇魂"],
    },
    # 武器法宝体系
    "weapon_system": {
        "武器": ["剑", "刀", "枪", "戟", "斧", "锤", "鞭"],
        "护甲": ["甲", "袍", "衣", "靴", "冠", "盔"],
        "法器": ["珠", "钵", "印", "镜", "塔", "鼎"],
        "灵宝": ["宝", "灵", "仙"],
    },
    # 资源体系
    "resource_system": {
        "灵草灵药": ["草", "花", "果", "芝", "参", "莲"],
        "矿石材料": ["石", "铁", "金", "银", "铜", "晶"],
        "妖兽材料": ["骨", "皮", "鳞", "角", "牙", "爪"],
        "特殊材料": ["精", "髓", "血", "丹", "符"],
    },
}


def smart_categorize_collection(cursor, collection_id, name, category):
    """智能分类一个集合的设定项"""
    
    if category not in HIERARCHY_DEFAULTS:
        return 0
    
    config = HIERARCHY_DEFAULTS[category]
    
    if config["max_depth"] != 3:
        return 0
    
    # 获取分类规则
    category_rules = CATEGORY_KEYWORDS.get(category, {})
    
    if not category_rules:
        print(f"   ⚠️ 没有定义分类规则，跳过")
        return 0
    
    # 查询所有设定项
    cursor.execute("""
        SELECT id, name, depth, path, node_type, is_leaf
        FROM setting_items
        WHERE collection_id = ?
        ORDER BY id
    """, (collection_id,))
    
    items = cursor.fetchall()
    
    # 找出所有叶子节点
    leaf_items = [item for item in items if item[5]]  # is_leaf
    
    if not leaf_items:
        print(f"   ℹ️ 没有叶子节点")
        return 0
    
    # 删除旧的"未分类"节点
    cursor.execute("""
        DELETE FROM setting_items
        WHERE collection_id = ? AND name = '未分类' AND node_type = 'category'
    """, (collection_id,))
    
    deleted_count = cursor.rowcount
    if deleted_count > 0:
        print(f"   🗑️ 删除了 {deleted_count} 个'未分类'节点")
    
    # 为每个分类创建节点
    category_nodes = {}
    
    for category_name, keywords in category_rules.items():
        # 创建分类节点
        cursor.execute("""
            INSERT INTO setting_items (
                collection_id, name, code, level, tags, content, relations,
                depth, node_type, is_leaf, path, summary, `order`,
                created_at, updated_at
            ) VALUES (?, ?, '', NULL, NULL, '', NULL, 2, 'category', 0, ?, '', 0, datetime('now'), datetime('now'))
        """, (collection_id, category_name, f"/{name}/{category_name}"))
        
        category_nodes[category_name] = {
            'id': cursor.lastrowid,
            'keywords': keywords,
        }
    
    print(f"   ✅ 创建了 {len(category_nodes)} 个分类节点")
    
    # 智能匹配设定项到分类
    matched_count = 0
    unmatched_items = []
    
    for item in leaf_items:
        item_id, item_name, depth, path, node_type, is_leaf = item
        
        # 尝试匹配分类
        matched_category = None
        max_match_score = 0
        
        for category_name, node_info in category_nodes.items():
            # 计算匹配分数（包含的关键词数量）
            score = sum(1 for keyword in node_info['keywords'] if keyword in item_name)
            
            if score > max_match_score:
                max_match_score = score
                matched_category = category_name
        
        if matched_category:
            # 更新设定项到匹配的分类
            new_path = f"/{name}/{matched_category}/{item_name}"
            cursor.execute("""
                UPDATE setting_items
                SET depth = 3,
                    node_type = 'detail',
                    is_leaf = 1,
                    path = ?
                WHERE id = ?
            """, (new_path, item_id))
            
            matched_count += 1
        else:
            unmatched_items.append(item_name)
    
    print(f"   ✅ 自动分类了 {matched_count} 个设定项")
    
    if unmatched_items:
        print(f"   ⚠️ 未匹配的设定项 ({len(unmatched_items)}个): {', '.join(unmatched_items[:5])}")
        if len(unmatched_items) > 5:
            print(f"       ... 还有 {len(unmatched_items) - 5} 个")
        
        # 为未匹配的项创建"其他"分类
        cursor.execute("""
            INSERT INTO setting_items (
                collection_id, name, code, level, tags, content, relations,
                depth, node_type, is_leaf, path, summary, `order`,
                created_at, updated_at
            ) VALUES (?, '其他', '', NULL, NULL, '未能自动分类的项', NULL, 2, 'category', 0, ?, '', 999, datetime('now'), datetime('now'))
        """, (collection_id, f"/{name}/其他"))
        
        other_category_id = cursor.lastrowid
        
        # 将未匹配的项移动到"其他"
        for item in leaf_items:
            item_id, item_name, depth, path, node_type, is_leaf = item
            if item_name in unmatched_items:
                new_path = f"/{name}/其他/{item_name}"
                cursor.execute("""
                    UPDATE setting_items
                    SET depth = 3,
                        node_type = 'detail',
                        is_leaf = 1,
                        path = ?
                    WHERE id = ?
                """, (new_path, item_id))
        
        print(f"   ✅ 创建了'其他'分类，收容 {len(unmatched_items)} 个未匹配项")
    
    return 1


def smart_categorize_all():
    """智能分类所有3层体系"""
    
    if not os.path.exists(DB_PATH):
        print(f"❌ 数据库文件不存在: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        print("="*60)
        print("  🤖 智能分类工具")
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
        
        categorized_count = 0
        
        for col_id, name, category in collections:
            print(f"{'─'*60}")
            print(f"📦 {name} (ID: {col_id}, 分类: {category or '未分类'})")
            
            if category:
                result = smart_categorize_collection(cursor, col_id, name, category)
                categorized_count += result
            else:
                print(f"   ⚠️ 没有分类信息，跳过")
        
        # 提交更改
        conn.commit()
        
        print(f"\n{'='*60}")
        print(f"  ✅ 智能分类完成")
        print(f"{'='*60}")
        print(f"\n📊 统计:")
        print(f"   ✅ 已处理: {categorized_count} 个集合")
        
        if categorized_count > 0:
            print(f"\n🎉 成功完成智能分类！")
            print("\n📖 下一步:")
            print("　　1. 刷新前端页面")
            print("　　2. 打开'世界观设定'查看树形结构")
            print("　　3. 检查分类结果，手动调整不准确的分类")
        else:
            print("\n💡 没有需要处理的集合")
        
    except Exception as e:
        print(f"\n❌ 分类失败: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║         🤖 智能分类工具                                     ║
║                                                              ║
║  功能：基于关键词匹配自动将设定项分类到正确的类别            ║
║  策略：删除"未分类"，创建实际的分类节点并智能匹配            ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    smart_categorize_all()
