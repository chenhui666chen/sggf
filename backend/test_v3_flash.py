"""Test cosyvoice-v3-flash with multiple voices and parameters"""
import asyncio
from dotenv import load_dotenv
load_dotenv()

async def test_v3_flash():
    from app.services.audiobook.tts_engine import TTSEngine
    
    # 使用v3-flash模型
    engine = TTSEngine(
        provider="aliyun", 
        enable_cache=False, 
        max_concurrent=1,
        model="cosyvoice-v3-flash"  # 最佳性价比模型
    )
    
    print("="*70)
    print("Testing cosyvoice-v3-flash with multiple voices & parameters:")
    print("="*70)
    print(f"Model: {engine.model}")
    print()
    
    # 测试不同音色和参数
    test_cases = [
        {
            "name": "男性音色 (longanyang)",
            "voice_params": {
                "speaker": "longanyang",
                "pitch": 50,      # v3支持！
                "speed": 1.0,     # v3支持！
                "volume": 55      # v3支持！
            },
            "text": "这是使用longanyang男性音色的测试。"
        },
        {
            "name": "女性音色 (longxiaochun)",
            "voice_params": {
                "speaker": "longxiaochun",
                "pitch": 60,      # 提高音高
                "speed": 1.1,     # 稍快语速
                "volume": 50
            },
            "text": "这是使用longxiaochun女性音色的测试。"
        },
        {
            "name": "男性音色 - 低音慢速",
            "voice_params": {
                "speaker": "longanyang",
                "pitch": 40,      # 降低音高
                "speed": 0.85,    # 慢速
                "volume": 52
            },
            "text": "青岚宗废丹房，一个常年弥漫着陈旧药渣与尘埃气味的角落。"
        }
    ]
    
    for i, case in enumerate(test_cases, 1):
        print(f"[{i}] {case['name']}")
        print(f"    voice_params: {case['voice_params']}")
        print(f"    text: {case['text'][:40]}...")
        
        try:
            audio = await engine.synthesize(
                text=case['text'],
                voice_params=case['voice_params'],
                emotion="neutral"
            )
            
            if audio and len(audio) > 0:
                print(f"    ✅ SUCCESS: {len(audio)} bytes")
            else:
                print(f"    ❌ FAILED: empty audio")
        except Exception as e:
            print(f"    ❌ ERROR: {e}")
        
        print()
        await asyncio.sleep(3)  # 间隔3秒
    
    # 成本统计
    stats = engine.get_cost_stats()
    print("="*70)
    print("Cost Statistics:")
    print(f"  Total segments: {stats['total_segments']}")
    print(f"  Total characters: {stats['total_chars']}")
    print(f"  Estimated cost: ¥{stats['estimated_cost']:.4f}")
    print("="*70)

if __name__ == "__main__":
    asyncio.run(test_v3_flash())
