"""
诊断阿里云TTS配额和账户状态
"""
import asyncio
import os
from dotenv import load_dotenv
import time

load_dotenv()

async def test_quota_limit():
    """测试配额限制"""
    print("=" * 70)
    print("🔍 阿里云TTS配额诊断")
    print("=" * 70)
    
    from app.services.audiobook.tts_engine import TTSEngine
    
    # 创建TTS引擎（最保守配置）
    engine = TTSEngine(
        provider="aliyun",
        enable_cache=False,
        max_concurrent=1
    )
    
    print(f"\n📋 配置信息:")
    print(f"   并发数: {engine.max_concurrent}")
    print(f"   请求间隔: {engine.request_delay}秒")
    
    # 测试文本
    test_text = "测试"
    voice_params = {
        "speaker": "longxiaochun",
        "pitch": 0,
        "speed": 1.0
    }
    
    print(f"\n🧪 开始连续调用测试...")
    print(f"   目标: 连续调用10次，观察哪次开始失败")
    print(f"   间隔: {engine.request_delay}秒\n")
    
    success_count = 0
    fail_count = 0
    first_fail_at = None
    
    for i in range(1, 11):
        print(f"[{i}/10] ", end='', flush=True)
        
        try:
            start = time.time()
            audio = await engine.synthesize(
                text=test_text,
                voice_params=voice_params,
                emotion="neutral"
            )
            elapsed = time.time() - start
            
            if audio and len(audio) > 0:
                print(f"✅ 成功 ({len(audio)}字节, {elapsed:.1f}秒)")
                success_count += 1
            else:
                print(f"❌ 失败 (返回空)")
                fail_count += 1
                if first_fail_at is None:
                    first_fail_at = i
                    
        except Exception as e:
            print(f"❌ 异常: {str(e)[:50]}")
            fail_count += 1
            if first_fail_at is None:
                first_fail_at = i
        
        # 等待间隔
        if i < 10:
            await asyncio.sleep(engine.request_delay)
    
    # 汇总结果
    print("\n" + "=" * 70)
    print("📊 测试结果")
    print("=" * 70)
    print(f"✅ 成功: {success_count}/10")
    print(f"❌ 失败: {fail_count}/10")
    
    if first_fail_at:
        print(f"\n⚠️ 首次失败位置: 第{first_fail_at}次调用")
        print(f"💡 这可能表示:")
        if first_fail_at <= 3:
            print(f"   - 账户可能有严格的速率限制（每{first_fail_at}次就触发）")
            print(f"   - 或者免费配额已经用尽")
        else:
            print(f"   - 短时间内累计调用次数限制")
            print(f"   - 需要更长的冷却时间")
    else:
        print("\n✅ 所有测试通过！")
        print("💡 说明:")
        print("   - 小批量调用没有问题")
        print("   - 大批量(42次)可能触发其他限制")
    
    # 给出建议
    print("\n" + "=" * 70)
    print("💡 建议措施")
    print("=" * 70)
    
    if fail_count > 0:
        print("""
1️⃣  **检查阿里云控制台**
   访问: https://dashscope.console.aliyun.com/billing
   查看:
   - 当前配额使用情况
   - 免费额度剩余
   - 是否有速率限制提示

2️⃣  **尝试增加间隔时间**
   当前5秒可能不够，建议:
   - 增加到10秒
   - 或者分批生成（每次5-10个片段，中间休息）

3️⃣  **联系阿里云技术支持**
   如果确认有余额但仍418错误:
   - 可能是服务等级限制
   - 需要升级套餐或申请提额

4️⃣  **临时方案：分批生成**
   不要一次性生成42个片段:
   - 每次生成5个片段
   - 等待1分钟后继续下一批
        """)
    else:
        print("""
✅ 小批量测试通过！

🔍 但大批量(42次)仍失败，说明:
   - 可能有累计调用次数限制
   - 或者有时间窗口限制（如：每分钟最多X次）

💡 建议:
   1. 将42个片段分成多批
   2. 每批5-10个
   3. 批次之间等待30-60秒
        """)
    
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(test_quota_limit())
