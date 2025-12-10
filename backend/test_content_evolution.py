"""
内容创作进化器快速验证脚本

用途：
1. 验证经验优化器是否正常工作
2. 检查分批去重逻辑
3. 测试冲突检测
"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from app.services.content_evolution.experience_optimizer import (
    get_content_experience_optimizer,
    ExperienceItem
)


# Mock LLM Client
class MockLLMClient:
    """模拟LLM客户端，用于测试"""
    
    async def chat(self, messages, task_type=None, temperature=0.3, use_cache=False):
        """模拟LLM响应"""
        # 返回标准格式的去重响应
        return """===MERGED_GROUPS===
1,2|增加细节描写可提升读者代入感（测试5次，成功率85%）
===MERGED_GROUPS_END===

===CONFLICT_REMOVED===
3|与第4条冲突（都关注对话比例，但第4条更新且成功率更高）
===CONFLICT_REMOVED_END===

===DEDUPLICATED_LIST===
增加细节描写可提升读者代入感（测试5次，成功率85%）
增加对话比例可提升阅读趣味（测试2次，成功率90%）
过度使用形容词导致累赘
===DEDUPLICATED_LIST_END==="""


async def test_experience_optimization():
    """测试经验优化功能"""
    print("=" * 60)
    print("🧪 内容创作进化器验证测试")
    print("=" * 60)
    
    # 🔧 使用Mock LLM创建优化器
    from app.services.content_evolution.experience_optimizer import ContentExperienceOptimizer
    optimizer = ContentExperienceOptimizer(llm_client=MockLLMClient())
    print("✅ 使用Mock LLM客户端")
    
    # 构造测试数据（模拟大量经验）
    test_experiences = {
        "variant_success": [
            ExperienceItem(
                text="增加细节描写可提升读者代入感",
                category="variant_success",
                appearance_count=5,
                success_rate=0.85,
                last_seen="2025-12-10T16:00:00"
            ),
            ExperienceItem(
                text="增加感官描写能提升代入感",  # 相似，应被合并
                category="variant_success",
                appearance_count=3,
                success_rate=0.80,
                last_seen="2025-12-10T15:00:00"
            ),
            ExperienceItem(
                text="降低对话比例可提升叙事节奏",
                category="variant_success",
                appearance_count=4,
                success_rate=0.75,
                last_seen="2025-12-10T14:00:00"
            ),
            # 模拟冲突：新经验
            ExperienceItem(
                text="增加对话比例可提升阅读趣味",  # 与上一条冲突
                category="variant_success",
                appearance_count=2,
                success_rate=0.90,
                last_seen="2025-12-10T16:30:00"  # 更新
            ),
        ],
        "variant_failure": [
            ExperienceItem(
                text="过度使用形容词导致累赘",
                category="variant_failure",
                appearance_count=3,
                success_rate=0.20,
                last_seen="2025-12-09T16:00:00"
            ),
        ],
        "feedback_patterns": []
    }
    
    print(f"\n📊 原始数据:")
    print(f"   - variant_success: {len(test_experiences['variant_success'])}条")
    print(f"   - variant_failure: {len(test_experiences['variant_failure'])}条")
    print(f"   - feedback_patterns: {len(test_experiences['feedback_patterns'])}条")
    
    # 执行优化
    print(f"\n⚙️ 开始优化...")
    try:
        top_experiences, summary = await optimizer.optimize_experiences(
            experiences=test_experiences,
            module_name="chapter",
            genre="玄幻"
        )
        
        print(f"\n✅ 优化完成!")
        print(f"   保留经验数: {len(top_experiences)}")
        print(f"\n{summary}")
        
        print("\n🏆 TOP经验详情:")
        for i, exp in enumerate(top_experiences[:5], 1):
            print(f"   {i}. [{exp.category}] {exp.text}")
            print(f"      成功率: {exp.success_rate:.1%}, 出现: {exp.appearance_count}次")
        
        return True
        
    except Exception as e:
        print(f"\n❌ 优化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_batch_processing():
    """测试分批处理（模拟150条经验）"""
    print("\n" + "=" * 60)
    print("🧪 分批处理测试（150条经验）")
    print("=" * 60)
    
    # 🔧 使用Mock LLM创建优化器
    from app.services.content_evolution.experience_optimizer import ContentExperienceOptimizer
    optimizer = ContentExperienceOptimizer(llm_client=MockLLMClient())
    print("✅ 使用Mock LLM客户端")
    
    # 生成150条测试经验
    test_experiences = {
        "variant_success": [
            ExperienceItem(
                text=f"测试经验{i}: 优化策略描述",
                category="variant_success",
                appearance_count=i % 10 + 1,
                success_rate=(i % 100) / 100,
                last_seen=f"2025-12-{10 - i%10:02d}T16:00:00"
            )
            for i in range(150)
        ],
        "variant_failure": [],
        "feedback_patterns": []
    }
    
    print(f"\n📊 原始数据: {len(test_experiences['variant_success'])}条")
    print(f"   预期：应触发分批处理（batch_size=100）")
    
    try:
        top_experiences, summary = await optimizer.optimize_experiences(
            experiences=test_experiences,
            module_name="chapter",
            genre="玄幻"
        )
        
        print(f"\n✅ 分批处理完成!")
        print(f"   最终保留: {len(top_experiences)}条")
        
        return True
        
    except Exception as e:
        print(f"\n❌ 分批处理失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_trigger_mechanism():
    """测试触发机制"""
    print("\n" + "=" * 60)
    print("🧪 触发机制测试")
    print("=" * 60)
    
    # 🔧 使用Mock LLM创建优化器
    from app.services.content_evolution.experience_optimizer import ContentExperienceOptimizer
    optimizer = ContentExperienceOptimizer(llm_client=MockLLMClient())
    
    # 测试不同场景
    test_cases = [
        (10, 0, False, "初始状态：10个变体，未优化过"),
        (15, 0, True, "达到阈值：15个新变体"),
        (20, 10, False, "增量不足：20个总数，上次10个"),
        (35, 0, True, "总数超限：35个变体，从未优化"),
    ]
    
    for total, last, expected, desc in test_cases:
        result = optimizer.should_trigger_optimization(total, last)
        status = "✅" if result == expected else "❌"
        print(f"{status} {desc}")
        print(f"   total={total}, last={last}, 预期={expected}, 实际={result}")
    
    return True


async def main():
    """主函数"""
    print("\n🚀 开始内容创作进化器验证\n")
    
    results = []
    
    # 测试1：基础优化功能
    print("\n【测试1/3】基础优化功能")
    results.append(await test_experience_optimization())
    
    # 测试2：分批处理
    print("\n【测试2/3】分批处理")
    results.append(await test_batch_processing())
    
    # 测试3：触发机制
    print("\n【测试3/3】触发机制")
    results.append(await test_trigger_mechanism())
    
    # 总结
    print("\n" + "=" * 60)
    print("📊 验证结果汇总")
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"通过: {passed}/{total}")
    
    if passed == total:
        print("✅ 所有测试通过！内容创作进化器工作正常")
    else:
        print(f"❌ 有{total - passed}个测试失败，请检查")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
