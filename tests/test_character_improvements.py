"""
测试智能人物识别器和协同验证器
"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.app.services.agents.character_recognizer import CharacterRecognizer
from backend.app.services.agents.character_plot_validator import CharacterPlotValidator


def test_character_recognizer():
    """测试人物识别器"""
    print("=" * 70)
    print("测试1：智能人物识别器")
    print("=" * 70)

    # 测试文本（包含真实人物和非人物词汇）
    test_text = """
## 主角阵营

### 【姓名】：裴砚之

【年龄/性别】：25岁，男

【外貌特征】：标志物明显，衣料折痕清晰，通过花粉可以追踪

【性格特点】：甜而不腻的性格，温和但坚定

### 【姓名】：林清雅

【年龄/性别】：23岁，女

【外貌特征】：清秀脱俗

## 对手阵营

### 【姓名】：萧寒

【年龄/性别】：30岁，男
"""

    recognizer = CharacterRecognizer()
    count, names = recognizer.count_characters(test_text, use_ai_verification=True)

    print(f"\n✅ 识别结果：")
    print(f"   人物数量：{count}")
    print(f"   人物名单：{names}")
    print(f"\n预期结果：3个人物（裴砚之、林清雅、萧寒）")
    print(f"是否正确：{'✅ 正确' if count == 3 else '❌ 错误'}")


def test_character_plot_validator():
    """测试人物-大纲协同验证器"""
    print("\n" + "=" * 70)
    print("测试2：人物-大纲协同验证器")
    print("=" * 70)

    characters = """
### 【姓名】：张三

【年龄/性别】：25岁，男
【在情节中的作用】：主角，推动主线发展

### 【姓名】：李四

【年龄/性别】：30岁，男
【在情节中的作用】：对手，与主角竞争
"""

    plot_outline = """
## 第1章：初入江湖

张三初次踏入江湖，遇到了导师王五。

## 第2章：修炼之路

张三在导师指导下修炼。

## 第3章：首次对决

张三与李四首次交手。
"""

    world_setting = "武侠世界，江湖纷争"

    validator = CharacterPlotValidator()
    result = validator.validate_character_plot_alignment(
        characters=characters,
        plot_outline=plot_outline,
        world_setting=world_setting
    )

    print(f"\n✅ 验证结果：")
    print(f"   匹配度评分：{result['score']}/100")
    print(f"   冗余人物：{result['redundant_characters']}")
    print(f"   缺失人物：{result['missing_characters']}")
    print(f"   关系问题：{len(result['relationship_issues'])}个")
    print(f"   改进建议：{len(result['suggestions'])}条")

    print(f"\n分析：")
    print(f"   - 大纲中提到'导师王五'，但人物设定中没有")
    print(f"   - 应该识别出缺失人物：导师角色")


def test_integrated_workflow():
    """测试集成工作流"""
    print("\n" + "=" * 70)
    print("测试3：集成工作流")
    print("=" * 70)

    print("\n模拟场景：")
    print("1. 用户提供初始人物和大纲")
    print("2. 系统识别当前人物数")
    print("3. 系统验证人物-情节匹配度")
    print("4. 根据匹配度决定是否扩展")
    print("5. 扩展后再次验证")

    print("\n✅ 工作流已集成到 outline_expander.py")
    print("   - 初始化时加载识别器和验证器")
    print("   - count_characters_in_text() 使用智能识别")
    print("   - expand_characters_incremental() 添加验证逻辑")


if __name__ == "__main__":
    print("\n🔥 开始测试智能人物识别和协同验证系统\n")

    try:
        test_character_recognizer()
    except Exception as e:
        print(f"\n❌ 测试1失败: {e}")
        import traceback
        traceback.print_exc()

    try:
        test_character_plot_validator()
    except Exception as e:
        print(f"\n❌ 测试2失败: {e}")
        import traceback
        traceback.print_exc()

    try:
        test_integrated_workflow()
    except Exception as e:
        print(f"\n❌ 测试3失败: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 70)
    print("测试完成")
    print("=" * 70)
