"""
测试分批生成策略
模拟42个片段的实际场景
"""
import asyncio
import time
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

from app.services.audiobook.tts_engine import TTSEngine

async def test_batch_strategy():
    """测试分批策略"""
    print("=" * 70)
    print("🧪 测试分批生成策略")
    print("=" * 70)
    
    # 创建TTS引擎
    engine = TTSEngine(
        provider="aliyun",
        enable_cache=False,
        max_concurrent=1
    )
    
    print(f"\n📋 配置信息:")
    print(f"   并发数: {engine.max_concurrent}")
    print(f"   请求间隔: {engine.request_delay}秒")
    
    # 模拟42个片段（缩减到15个用于快速测试）
    test_segments = [
        {
            "text": f"这是第{i+1}个测试片段",
            "voice_params": {"speaker": "longxiaochun", "pitch": 0, "speed": 1.0},
            "emotion": "neutral"
        }
        for i in range(15)  # 测试15个片段
    ]
    
    print(f"\n📦 测试配置:")
    print(f"   总片段数: {len(test_segments)}")
    print(f"   分批策略: 每批5个，批次间隔10秒")
    print(f"   预计时间: ~{len(test_segments) * 6 + 10 * 2}秒 (约2分钟)\n")
    
    # 开始测试
    start_time = time.time()
    
    audio_list = await engine.synthesize_batch(
        segments=test_segments,
        batch_size=5,  # 每批5个
        batch_interval=10  # 批次间隔10秒（测试用）
    )
    
    elapsed = time.time() - start_time
    
    # 统计结果
    success_count = len([a for a in audio_list if a and len(a) > 0])
    fail_count = len(test_segments) - success_count
    
    print("\n" + "=" * 70)
    print("📊 测试结果")
    print("=" * 70)
    print(f"✅ 成功: {success_count}/{len(test_segments)}")
    print(f"❌ 失败: {fail_count}/{len(test_segments)}")
    print(f"⏱️  总耗时: {elapsed:.1f}秒")
    
    if success_count == len(test_segments):
        print("\n🎉 完美！所有片段生成成功！")
        print("💡 分批策略有效，可以应用到实际42片段生成")
        print("\n📋 实际42片段预计:")
        print(f"   - 分批数: 5批 (每批8-10个)")
        print(f"   - 批次间隔: 60秒")
        print(f"   - 总耗时: 约6-7分钟")
    elif success_count > 0:
        print(f"\n⚠️ 部分成功 ({success_count}/{len(test_segments)})")
        print("💡 可能需要:")
        print("   - 增加批次间隔（如60秒）")
        print("   - 减少每批数量（如5个）")
    else:
        print("\n❌ 全部失败！")
        print("💡 请检查:")
        print("   - 阿里云账户余额")
        print("   - API Key权限")
        print("   - 网络连接")
    
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(test_batch_strategy())
