"""
AI痕迹降低方案集成测试脚本
"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(__file__))

from config import Config


def test_module_imports():
    """测试模块导入"""
    print("=" * 60)
    print("测试1：模块导入")
    print("=" * 60)
    
    try:
        from ai_trace_reduction_processor import AITraceReductionProcessor, reduce_ai_traces
        print("✅ ai_trace_reduction_processor 导入成功")
    except Exception as e:
        print(f"❌ ai_trace_reduction_processor 导入失败: {e}")
        return False
    
    try:
        from author_voice_system import (
            AuthorVoiceProfile, AuthorVoiceManager, 
            create_voice_profile, get_voice_manager
        )
        print("✅ author_voice_system 导入成功")
    except Exception as e:
        print(f"❌ author_voice_system 导入失败: {e}")
        return False
    
    try:
        from dialogue_authenticity_module import (
            DialogueAuthenticityEngine,
            optimize_dialogue_rhythm, analyze_dialogue_authenticity
        )
        print("✅ dialogue_authenticity_module 导入成功")
    except Exception as e:
        print(f"❌ dialogue_authenticity_module 导入失败: {e}")
        return False
    
    print("✅ 所有模块导入成功\n")
    return True


def test_coordinator_integration():
    """测试协调器集成"""
    print("=" * 60)
    print("测试2：协调器集成")
    print("=" * 60)
    
    try:
        from agent_coordinator import CreativeDirectorCoordinator
        print("✅ CreativeDirectorCoordinator 导入成功")
        
        # 创建协调器实例
        coordinator = CreativeDirectorCoordinator()
        print("✅ CreativeDirectorCoordinator 实例创建成功")
        
        # 检查AI痕迹处理器
        if hasattr(coordinator, 'ai_trace_processor'):
            print("✅ ai_trace_processor 属性存在")
        else:
            print("❌ ai_trace_processor 属性不存在")
            return False
        
        # 检查作者腔调档案
        if hasattr(coordinator, 'author_voice_profile'):
            print("✅ author_voice_profile 属性存在")
        else:
            print("❌ author_voice_profile 属性不存在")
            return False
        
        # 检查set_author_voice方法
        if hasattr(coordinator, 'set_author_voice'):
            print("✅ set_author_voice 方法存在")
        else:
            print("❌ set_author_voice 方法不存在")
            return False
        
        print("✅ 协调器集成成功\n")
        return True
        
    except Exception as e:
        print(f"❌ 协调器集成失败: {e}")
        return False


def test_author_voice_setup():
    """测试作者腔调设置"""
    print("=" * 60)
    print("测试3：作者腔调设置")
    print("=" * 60)
    
    try:
        from agent_coordinator import CreativeDirectorCoordinator
        
        coordinator = CreativeDirectorCoordinator()
        
        # 测试预定义模板
        templates = ["冷静克制", "诗意浪漫", "激情澎湃"]
        for template in templates:
            result = coordinator.set_author_voice(template_name=template)
            if result:
                print(f"✅ 作者腔调设置成功：{template}")
            else:
                print(f"❌ 作者腔调设置失败：{template}")
                return False
        
        # 测试自定义腔调
        result = coordinator.set_author_voice(
            custom_config={
                "narrative_style": "测试风格",
                "value_system": {"人性观": "测试观点"}
            }
        )
        if result:
            print("✅ 自定义作者腔调设置成功")
        else:
            print("❌ 自定义作者腔调设置失败")
            return False
        
        print("✅ 作者腔调设置测试通过\n")
        return True
        
    except Exception as e:
        print(f"❌ 作者腔调设置测试失败: {e}")
        return False


def test_basic_functionality():
    """测试基本功能"""
    print("=" * 60)
    print("测试4：基本功能")
    print("=" * 60)
    
    try:
        from ai_trace_reduction_processor import reduce_ai_traces
        from author_voice_system import create_voice_profile, get_voice_manager
        from dialogue_authenticity_module import optimize_dialogue_rhythm
        
        # 测试内容
        test_content = "这是一个测试内容。她是一位杰出的女性，拥有优美的气质。"
        
        print(f"原始内容：{test_content}")
        
        # 测试作者腔调创建
        profile = create_voice_profile(
            project_id=1,
            template_name="冷静克制"
        )
        print("✅ 作者腔调创建成功")
        
        # 测试腔调管理器
        manager = get_voice_manager()
        consistency = manager.validate_voice_consistency(test_content, profile)
        print(f"✅ 腔调一致性检查成功，评分：{consistency['consistency_score']:.1f}/100")
        
        # 测试对话优化
        test_dialogue = "她说：'我已经准备好了。'"
        optimized = optimize_dialogue_rhythm(test_dialogue)
        print(f"✅ 对话优化成功")
        
        print("✅ 基本功能测试通过\n")
        return True
        
    except Exception as e:
        print(f"❌ 基本功能测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """运行所有测试"""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 58 + "║")
    print("║" + "  AI痕迹降低方案集成测试".center(58) + "║")
    print("║" + " " * 58 + "║")
    print("╚" + "=" * 58 + "╝")
    print("\n")
    
    # 验证配置
    try:
        Config.validate()
        print("✅ 配置验证成功\n")
    except Exception as e:
        print(f"❌ 配置验证失败: {e}\n")
        return False
    
    # 运行测试
    tests = [
        ("模块导入", test_module_imports),
        ("协调器集成", test_coordinator_integration),
        ("作者腔调设置", test_author_voice_setup),
        ("基本功能", test_basic_functionality),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} 测试异常: {e}\n")
            results.append((test_name, False))
    
    # 输出总结
    print("=" * 60)
    print("测试总结")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status}：{test_name}")
    
    print(f"\n总体结果：{passed}/{total} 测试通过")
    
    if passed == total:
        print("\n🎉 所有测试通过！集成成功！")
        return True
    else:
        print(f"\n⚠️  有 {total - passed} 个测试失败，请检查错误信息")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

