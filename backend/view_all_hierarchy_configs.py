#!/usr/bin/env python
"""
设定体系层级配置查看工具
快速查看所有27个体系的层级结构和示例
"""
import sys
sys.path.insert(0, '.')

from app.services.setting_templates import HIERARCHY_DEFAULTS
import json

def print_separator(char="=", length=80):
    print(char * length)

def print_system_config(category, config, index):
    """打印单个体系的配置"""
    print(f"\n{'='*80}")
    print(f"【{index}】 {config['levels'][0]['name']} ({category})")
    print(f"{'='*80}")
    print(f"最大深度: {config['max_depth']}层")
    print(f"\n层级结构:")
    
    for level in config['levels']:
        depth = level['depth']
        name = level['name']
        level_type = level['type']
        is_leaf = level.get('leaf', False)
        examples = level.get('examples', [])
        
        indent = "  " * (depth - 1)
        leaf_mark = " [叶子节点]" if is_leaf else ""
        
        print(f"{indent}├─ 第{depth}层: {name} (类型:{level_type}){leaf_mark}")
        
        if examples:
            example_str = "、".join(examples[:5])
            if len(examples) > 5:
                example_str += f"... (共{len(examples)}个)"
            print(f"{indent}   示例: {example_str}")

def main():
    print_separator()
    print("🎯 设定体系层级配置全览")
    print_separator()
    
    # 按类别组织体系
    categories = {
        "地理与世界观": ["map_system"],
        "修仙/玄幻体系": [
            "cultivation_realm_system", "technique_system", "pill_system",
            "formation_system", "talisman_system", "weapon_system",
            "resource_system", "force_system"
        ],
        "都市异能体系": [
            "ability_realm_system", "ability_awakening_growth_system",
            "hidden_organization_force_system", "network_social_relationship_system",
            "special_artifact_relic_system", "wealth_business_empire_system"
        ],
        "西幻/魔法体系": [
            "magic_realm_system", "magic_system", "race_bloodline_system",
            "profession_class_system", "martial_realm_system"
        ],
        "科幻体系": [
            "interstellar_travel_exploration_system", "ai_robot_system"
        ],
        "末世废土体系": [
            "survivor_settlement_order_system", "mutation_infection_aberration_system"
        ],
        "游戏系统体系": ["skill_talent_system"],
        "角色体系": ["character_system"],
        "特殊体系": ["candidate"]
    }
    
    total_count = 0
    for category_name, systems in categories.items():
        print(f"\n\n{'#'*80}")
        print(f"# {category_name} ({len(systems)}个)")
        print(f"{'#'*80}")
        
        for system_key in systems:
            if system_key in HIERARCHY_DEFAULTS:
                total_count += 1
                config = HIERARCHY_DEFAULTS[system_key]
                print_system_config(system_key, config, total_count)
            else:
                print(f"\n⚠️  警告: {system_key} 未找到配置")
    
    # 统计信息
    print(f"\n\n{'='*80}")
    print("📊 统计信息")
    print(f"{'='*80}")
    print(f"总体系数: {len(HIERARCHY_DEFAULTS)}个")
    
    depth_count = {}
    for config in HIERARCHY_DEFAULTS.values():
        depth = config['max_depth']
        depth_count[depth] = depth_count.get(depth, 0) + 1
    
    print(f"\n层级深度分布:")
    for depth in sorted(depth_count.keys()):
        count = depth_count[depth]
        percentage = (count / len(HIERARCHY_DEFAULTS)) * 100
        print(f"  {depth}层: {count}个 ({percentage:.1f}%)")
    
    # 示例统计
    total_examples = 0
    systems_with_examples = 0
    for config in HIERARCHY_DEFAULTS.values():
        has_example = False
        for level in config['levels']:
            if 'examples' in level:
                total_examples += len(level['examples'])
                has_example = True
        if has_example:
            systems_with_examples += 1
    
    print(f"\n示例统计:")
    print(f"  含示例的体系: {systems_with_examples}个")
    print(f"  总示例数量: {total_examples}个")
    print(f"  平均每体系: {total_examples/len(HIERARCHY_DEFAULTS):.1f}个示例")
    
    print(f"\n{'='*80}")
    print("✅ 全部配置加载成功！")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    main()
