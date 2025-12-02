"""
测试地点层级提取功能
演示如何从章节内容中自动生成地图节点
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.services.location_hierarchy_extractor import LocationHierarchyExtractor


async def test_location_extraction():
    """测试地点提取"""
    
    # 模拟章节内容
    chapter_title = "第一章：初入修仙界"
    chapter_content = """
林凡穿越到了修仙界的东域，这里是一片广袤的大陆。

他首先来到了青云宗，这是东域最大的修仙门派之一。青云宗坐落在玄天山脉中，
占据了三座主峰：青云峰、紫霞峰和天剑峰。

林凡被分配到了青云峰，这里是外门弟子的修炼之地。青云峰上有藏经阁、
练功场和丹房等建筑。藏经阁位于青云峰的山腰处，收藏着无数功法秘籍。

宗门附近有一个繁华的坊市——云中坊市，许多修士在此交易灵药和法宝。

据说在玄天山脉深处，有一处上古遗迹——天机秘境，里面蕴藏着惊天机缘，
但也危机四伏。只有筑基期以上的修士才敢进入探索。

青云宗与云中坊市之间有一座传送阵，可以瞬间往返，极为便利。
    """
    
    print("="*60)
    print("  🗺️ 地点层级提取测试")
    print("="*60)
    print(f"\n📖 章节标题: {chapter_title}")
    print(f"📄 章节长度: {len(chapter_content)} 字\n")
    
    # 提取地点层级
    print("⏳ 正在提取地点...")
    locations = await LocationHierarchyExtractor.extract_location_hierarchy(
        chapter_title=chapter_title,
        chapter_content=chapter_content,
    )
    
    if not locations:
        print("❌ 未提取到地点")
        return
    
    print(f"\n✅ 提取到 {len(locations)} 个地点\n")
    print("="*60)
    
    # 按层级分组显示
    levels = {}
    for loc in locations:
        level = loc['level']
        if level not in levels:
            levels[level] = []
        levels[level].append(loc)
    
    level_names = {
        1: "🌍 最大范围（大陆/界域）",
        2: "🏔️ 中等范围（宗门/山脉）",
        3: "🏘️ 具体地点（峰/阁/市）",
        4: "📍 详细位置（层/侧/区）",
    }
    
    for level in sorted(levels.keys()):
        print(f"\n{level_names.get(level, f'Level {level}')}")
        print("-" * 60)
        
        for loc in levels[level]:
            parent_str = f" [父: {loc['parent']}]" if loc['parent'] else ""
            print(f"  • {loc['name']}{parent_str}")
            print(f"    分类: {loc['category']}")
            print(f"    描述: {loc['description'][:50]}...")
            print()
    
    # 显示树形结构
    print("\n" + "="*60)
    print("  🌳 树形结构预览")
    print("="*60)
    
    # 构建树
    def build_tree(parent=None, indent=0):
        for loc in locations:
            if loc['parent'] == parent:
                prefix = "  " * indent + "├── "
                print(f"{prefix}{loc['name']} ({loc['category']})")
                build_tree(loc['name'], indent + 1)
    
    print("\n地图体系")
    build_tree(None, 0)
    
    print("\n" + "="*60)
    print("  ✅ 测试完成")
    print("="*60)
    print("\n💡 说明:")
    print("   • 这些地点将自动添加到'地图体系'集合")
    print("   • 系统会自动创建层级关系和分类节点")
    print("   • 用户可以在前端查看完整的地图树")
    print("   • 后续章节会继续扩充地图体系")


if __name__ == "__main__":
    asyncio.run(test_location_extraction())
