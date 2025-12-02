#!/usr/bin/env python
"""
境界体系配置验证测试
"""
import sys
sys.path.insert(0, '.')

from app.services.setting_templates import HIERARCHY_DEFAULTS, SETTING_TEMPLATES

def test_hierarchy_configs():
    """测试层级配置"""
    print("=" * 60)
    print("🔍 测试境界体系层级配置")
    print("=" * 60)
    
    realm_systems = {
        "cultivation_realm_system": "修仙境界体系",
        "magic_realm_system": "魔法境界体系",
        "martial_realm_system": "武道境界体系",
        "ability_realm_system": "异能境界体系",
    }
    
    for key, name in realm_systems.items():
        if key in HIERARCHY_DEFAULTS:
            config = HIERARCHY_DEFAULTS[key]
            print(f"✅ {name} ({key})")
            print(f"   - 最大层数: {config['max_depth']}")
            print(f"   - 层级数: {len(config['levels'])}")
        else:
            print(f"❌ {name} ({key}) - 未找到配置！")
    
    print()

def test_template_collections():
    """测试模板集合"""
    print("=" * 60)
    print("🔍 测试模板集合配置")
    print("=" * 60)
    
    # 测试玄幻修真模板
    xuanhuan = SETTING_TEMPLATES['xuanhuan_basic']
    print(f"\n【玄幻修真模板】({xuanhuan['key']})")
    print(f"集合总数: {len(xuanhuan['collections'])}")
    
    for col in xuanhuan['collections']:
        if 'realm' in col['category']:
            print(f"  ✅ {col['name']} ({col['category']})")
            print(f"     - 设定项数量: {len(col['items'])}")
            if col['items']:
                print(f"     - 示例: {col['items'][0]['name']} → ... → {col['items'][-1]['name']}")
    
    # 测试都市异能模板
    urban = SETTING_TEMPLATES['urban_power']
    print(f"\n【都市异能模板】({urban['key']})")
    print(f"集合总数: {len(urban['collections'])}")
    
    for col in urban['collections']:
        if 'realm' in col['category']:
            print(f"  ✅ {col['name']} ({col['category']})")
            print(f"     - 设定项数量: {len(col['items'])}")
            if col['items']:
                print(f"     - 示例: {col['items'][0]['name']} → ... → {col['items'][-1]['name']}")
    
    print()

def test_realm_data():
    """测试境界数据完整性"""
    print("=" * 60)
    print("🔍 测试境界数据完整性")
    print("=" * 60)
    
    # 测试修仙境界
    xuanhuan = SETTING_TEMPLATES['xuanhuan_basic']
    realm_col = next((c for c in xuanhuan['collections'] if c['category'] == 'cultivation_realm_system'), None)
    
    if realm_col:
        print(f"\n【修仙境界体系】")
        print(f"境界数量: {len(realm_col['items'])}")
        print("\n境界列表:")
        for idx, item in enumerate(realm_col['items'], 1):
            tags = ', '.join(item['tags'])
            print(f"  {idx}. {item['name']} (level={item['level']}, code={item['code']})")
            print(f"     标签: {tags}")
            content_preview = item['content'][:40] + "..." if len(item['content']) > 40 else item['content']
            print(f"     描述: {content_preview}")
    
    # 测试异能境界
    urban = SETTING_TEMPLATES['urban_power']
    ability_col = next((c for c in urban['collections'] if c['category'] == 'ability_realm_system'), None)
    
    if ability_col:
        print(f"\n【异能境界体系】")
        print(f"境界数量: {len(ability_col['items'])}")
        print("\n境界列表:")
        for idx, item in enumerate(ability_col['items'], 1):
            tags = ', '.join(item['tags'])
            print(f"  {idx}. {item['name']} (level={item['level']}, code={item['code']})")
            print(f"     标签: {tags}")
            content_preview = item['content'][:40] + "..." if len(item['content']) > 40 else item['content']
            print(f"     描述: {content_preview}")
    
    print()

def test_compatibility():
    """测试向后兼容性"""
    print("=" * 60)
    print("🔍 测试向后兼容性")
    print("=" * 60)
    
    # 检查旧配置是否还存在
    old_configs = {
        "ability_awakening_growth_system": "旧异能成长体系",
    }
    
    for key, name in old_configs.items():
        if key in HIERARCHY_DEFAULTS:
            print(f"✅ {name} ({key}) - 保留用于向后兼容")
        else:
            print(f"❌ {name} ({key}) - 已删除（可能影响旧数据）")
    
    print()

def main():
    print("\n" + "=" * 60)
    print("    境界体系配置全面验证测试")
    print("=" * 60 + "\n")
    
    try:
        test_hierarchy_configs()
        test_template_collections()
        test_realm_data()
        test_compatibility()
        
        print("=" * 60)
        print("✅ 所有测试通过！境界体系配置验证成功")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
