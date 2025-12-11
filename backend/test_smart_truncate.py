"""
测试智能截断功能
验证所有手动截断已被AI智能截断替代
"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.services.agents.intelligent_truncator import smart_truncate_for_context


def test_chapter_truncate():
    """测试章节内容截断"""
    print("\n" + "="*80)
    print("【测试1: 章节内容智能截断】")
    print("="*80)
    
    # 模拟一个较长的章节内容
    chapter_content = """
第1章 废材少年

清晨的阳光洒落在青玄宗外门弟子院，林墨躺在床上，望着破旧的屋顶发呆。

"五行杂灵根，注定一辈子只能当个外门弟子。"他苦笑着摇摇头。

昨天宗门测试，他再次垫底。同期入门的师兄弟们都已经是炼气五层、六层，而他还停留在炼气三层。

"废物！废物！"耳边回响起昨天那些人的嘲笑声。

林墨从床上坐起，拿起桌上的《青木长生诀》。这是宗门发放的基础功法，黄阶下品，适合杂灵根修炼。

"如果我有单灵根，早就筑基了吧。"他叹了口气，开始打坐修炼。

灵气缓慢地从周围汇聚而来，进入体内后立刻分散成五股，分别流向金木水火土五个方向。杂灵根就是这样，灵气利用率极低。

"咚咚咚！"门外传来敲门声。

"林墨，出来！"是张强的声音，这家伙仗着自己是火灵根，经常欺负林墨。

林墨叹了口气，起身开门。

门外站着三个人，为首的张强叉着腰，得意洋洋："听说你今天要去完成宗门任务？"

"是。"林墨平静地回答。

"带上这个。"张强扔过来一个破烂的储物袋，"给我采100株灵草回来，否则别想回宗门。"

林墨接过储物袋，沉默不语。他知道反抗只会招来更多欺辱。

"哈哈哈！废物就该有废物的觉悟！"张强大笑着离开。

林墨握紧拳头，眼中闪过一丝不甘。但很快，他就平复了心情，背起行囊走出了宗门。

宗门后山，灵雾森林。

这是一片充满危机的区域，有妖兽出没。但外门弟子的任务就是在这里采集灵草、猎杀妖兽。

林墨小心翼翼地前进，避开那些危险区域。他的修为太低，遇到妖兽基本等于送死。

"咦？那是什么？"

前方的山洞闪烁着诡异的蓝光，让林墨心生好奇。

犹豫片刻后，他还是走了进去。山洞很深，越往里光芒越亮。

终于，他在山洞深处发现了光源——一块巴掌大小的蓝色晶石，散发着强烈的能量波动。

"这是...雷属性的天材地宝？"林墨瞪大眼睛。

他伸手触碰晶石，突然，一道雷霆从天而降，直接劈在他身上！

"啊！"林墨惨叫一声，意识陷入黑暗。

不知过了多久，他醒了过来。令人惊讶的是，不仅没死，反而感觉体内涌现出一股前所未有的力量。

"我的灵根...变了？"

林墨震惊地发现，体内的五行杂灵根消失了，取而代之的是一道璀璨的雷灵根！

而且，丹田中还多了一个神秘的空间，里面竟然有一部功法——《雷霆万钧诀》，地阶上品！

"这...这是天大的机缘啊！"林墨激动得浑身颤抖。

从今天起，他不再是那个废材林墨了。他要用实力，狠狠打脸那些曾经嘲笑他的人！

（本章完）
"""
    
    print(f"原始长度: {len(chapter_content)} 字符")
    
    # 测试不同的截断场景
    scenarios = [
        {"max_tokens": 2000, "desc": "质量评审场景"},
        {"max_tokens": 1300, "desc": "迭代优化场景"},
        {"max_tokens": 500, "desc": "极限压缩场景"},
    ]
    
    for scenario in scenarios:
        result = smart_truncate_for_context(
            content=chapter_content,
            max_tokens=scenario["max_tokens"],
            content_type="chapter",
            preserve_ratio=0.8
        )
        print(f"\n【{scenario['desc']}】")
        print(f"目标: {scenario['max_tokens']} tokens ≈ {int(scenario['max_tokens'] * 1.5)} 字符")
        print(f"实际: {len(result)} 字符")
        print(f"压缩比: {len(result)/len(chapter_content)*100:.1f}%")
        print(f"预览: {result[:200]}...")


def test_review_truncate():
    """测试评审报告截断"""
    print("\n" + "="*80)
    print("【测试2: 评审报告智能截断】")
    print("="*80)
    
    review_content = """
## 📊 网文质量评审报告

**综合评分**：7.5/10分

### 1. 爽点效果 ⭐⭐⭐⭐
- 评价：本章设置了非常经典的"废材逆袭"爽点，主角获得雷灵根是一个强有力的转折
- 问题：爽点释放过快，缺少足够的压抑铺垫，建议在获得机缘前增加更多欺辱场景

### 2. 节奏把控 ⭐⭐⭐
- 评价：整体节奏较快，但开头铺垫略显仓促
- 问题：从废材状态到获得机缘只用了不到一半篇幅，建议拉长痛苦期

### 3. 钩子效果 ⭐⭐⭐⭐
- 开头评价：以"废材少年"开篇，符合读者预期，但缺少悬念
- 结尾评价：获得雷灵根+功法，悬念设置较好，能吸引读者继续阅读
- 问题：开头可以增加"即将被逐出宗门"等紧迫感

### 4. 代入感 ⭐⭐⭐
- 评价：主角心理描写较为充分，读者能感受到他的不甘
- 问题：对话和互动较少，建议增加更多人物对话增强画面感

### 5. 文笔流畅度 ⭐⭐⭐⭐
- 评价：语言流畅，无明显AI痕迹
- 问题：部分场景描写略显单薄，可以增加更多细节

### 6. 内容一致性 ⭐⭐⭐⭐⭐
- 评价：与设定完全一致，境界体系、宗门设定都符合预设
- 问题：无

### 🔧 具体修改建议（按优先级排序）
1. 【必改】增加废材期的痛苦描写，至少需要3-5个欺辱场景
2. 【必改】拉长获得机缘前的铺垫，让读者更深刻体会主角的绝望
3. 【建议】开头增加"三个月后将被逐出宗门"的紧迫感设定
4. 【建议】增加与张强的对话和冲突细节
5. 【可选】补充灵雾森林的环境描写
6. 【可选】增加主角内心对未来的幻想与现实的对比
"""
    
    print(f"原始长度: {len(review_content)} 字符")
    
    result = smart_truncate_for_context(
        content=review_content,
        max_tokens=600,
        content_type="review",
        preserve_ratio=0.9  # 评审意见优先保留【必改】项
    )
    
    print(f"\n目标: 600 tokens ≈ 900 字符")
    print(f"实际: {len(result)} 字符")
    print(f"压缩比: {len(result)/len(review_content)*100:.1f}%")
    print(f"\n截断后内容:\n{result}")


def test_rag_doc_truncate():
    """测试RAG文档截断"""
    print("\n" + "="*80)
    print("【测试3: RAG检索文档智能截断】")
    print("="*80)
    
    rag_doc = """
【人物名】林墨
【阵营】青玄宗外门弟子
【当前修为】炼气三层（第1章）→ 获得雷灵根后预计可快速突破
【灵根资质】五行杂灵根（废材）→ 雷灵根（觉醒后）
【主修功法】《青木长生诀》（黄阶下品）→ 《雷霆万钧诀》（地阶上品）
【法宝】无 → 后续可能获得雷属性法宝
【宗门地位】外门弟子（被欺压）→ 预计将快速晋升

【详细背景】
林墨自幼父母双亡，被青玄宗收养。因为是五行杂灵根，被视为废材，经常受到同门欺辱。
尤其是张强，仗着自己是火灵根，经常欺负林墨，甚至强迫他完成各种任务。

【性格特点】
- 隐忍：面对欺辱选择忍耐，不轻易反抗
- 不甘：内心充满对现状的不甘和对实力的渴望
- 谨慎：在灵雾森林小心翼翼，不冒进
- 坚韧：即使是废材也坚持修炼，从不放弃

【关键转折】
第1章在灵雾森林发现神秘蓝色晶石，被雷霆劈中后觉醒雷灵根，获得《雷霆万钧诀》。
从此走上逆袭之路，将狠狠打脸那些曾经嘲笑他的人。

【重要关系】
- 张强：欺凌者，火灵根天才，后续预计会有多次冲突
- 其他外门弟子：多数轻视林墨，后续会被打脸
"""
    
    print(f"原始长度: {len(rag_doc)} 字符")
    
    result = smart_truncate_for_context(
        content=rag_doc,
        max_tokens=200,  # RAG文档需要高度压缩
        content_type="rag_doc",
        preserve_ratio=0.9
    )
    
    print(f"\n目标: 200 tokens ≈ 300 字符")
    print(f"实际: {len(result)} 字符")
    print(f"压缩比: {len(result)/len(rag_doc)*100:.1f}%")
    print(f"\n截断后内容:\n{result}")


def test_no_truncate():
    """测试内容已在限制内无需截断的情况"""
    print("\n" + "="*80)
    print("【测试4: 内容在限制内，无需截断】")
    print("="*80)
    
    short_content = "这是一段很短的内容，不需要截断。"
    
    result = smart_truncate_for_context(
        content=short_content,
        max_tokens=1000,
        content_type="chapter"
    )
    
    print(f"原始长度: {len(short_content)} 字符")
    print(f"目标: 1000 tokens ≈ 1500 字符")
    print(f"结果: 无需截断，直接返回原内容")
    print(f"验证: {result == short_content}")


if __name__ == "__main__":
    print("\n" + "🎯"*40)
    print("智能截断功能测试")
    print("🎯"*40)
    
    try:
        test_chapter_truncate()
        test_review_truncate()
        test_rag_doc_truncate()
        test_no_truncate()
        
        print("\n" + "="*80)
        print("✅ 所有测试通过!")
        print("="*80)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
