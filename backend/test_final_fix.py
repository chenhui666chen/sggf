"""Test final fix"""
import asyncio
from dotenv import load_dotenv
load_dotenv()

async def test():
    from app.services.audiobook.tts_engine import TTSEngine
    
    engine = TTSEngine(provider="aliyun", enable_cache=False, max_concurrent=1)
    
    print("="*70)
    print("Testing with voice_params (like real usage):")
    print("="*70)
    
    voice_params = {
        "speaker": "longxiaochun",
        "pitch": 60,      # 音高 60
        "speed": 1.2,     # 语速 1.2
        "volume": 55      # 音量 55
    }
    
    audio = await engine.synthesize(
        text="第一章 废丹房里的异象",
        voice_params=voice_params,
        emotion="neutral"
    )
    
    if audio and len(audio) > 0:
        print(f"SUCCESS: {len(audio)} bytes")
        print("418 error should be FIXED!")
    else:
        print(f"FAILED: empty audio")

if __name__ == "__main__":
    asyncio.run(test())
