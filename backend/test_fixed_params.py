"""Test fixed parameters for cosyvoice-v1"""
import asyncio
from dotenv import load_dotenv
load_dotenv()

async def test():
    from app.services.audiobook.tts_engine import TTSEngine
    
    engine = TTSEngine(provider="aliyun", enable_cache=False, max_concurrent=1)
    
    print("="*70)
    print("Testing FIXED implementation (v1 without unsupported params):")
    print("="*70)
    
    # Test with voice_params (v1 will ignore pitch/speed/volume)
    voice_params = {
        "speaker": "longxiaochun",
        "pitch": 60,      # 将被忽略（v1不支持）
        "speed": 1.2,     # 将被忽略（v1不支持）
        "volume": 55      # 将被忽略（v1不支持）
    }
    
    print(f"voice_params: {voice_params}")
    print("Note: pitch/speed/volume will be ignored by v1 implementation")
    print()
    
    # Test multiple texts
    test_texts = [
        "第一章 废丹房里的异象",
        "青岚宗废丹房，一个常年弥漫着陈旧药渣与尘埃气味的角落。",
        "测试文本"
    ]
    
    for i, text in enumerate(test_texts, 1):
        print(f"[{i}] Testing: {text[:30]}...")
        audio = await engine.synthesize(
            text=text,
            voice_params=voice_params,
            emotion="neutral"
        )
        
        if audio and len(audio) > 0:
            print(f"    SUCCESS: {len(audio)} bytes")
        else:
            print(f"    FAILED: empty audio")
        
        # Wait between requests
        await asyncio.sleep(engine.request_delay)
    
    print("\n" + "="*70)
    print("All tests completed!")
    print("="*70)

if __name__ == "__main__":
    asyncio.run(test())
