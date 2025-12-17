"""Verify if parameters are being passed correctly"""
import asyncio
from dotenv import load_dotenv
load_dotenv()

async def test():
    from app.services.audiobook.tts_engine import TTSEngine
    import inspect
    
    engine = TTSEngine(provider="aliyun", enable_cache=False)
    
    # Check the _call_aliyun_tts method source
    print("="*70)
    print("Checking _call_aliyun_tts implementation:")
    print("="*70)
    
    source = inspect.getsource(engine._call_aliyun_tts)
    
    # Look for SpeechSynthesizer initialization
    lines = source.split('\n')
    for i, line in enumerate(lines):
        if 'SpeechSynthesizer(' in line:
            # Print surrounding 10 lines
            start = max(0, i-2)
            end = min(len(lines), i+10)
            print("SpeechSynthesizer initialization:")
            for j in range(start, end):
                print(f"  {lines[j]}")
            break
    
    print("\n" + "="*70)
    print("Testing actual call:")
    print("="*70)
    
    # Test with voice_params
    voice_params = {
        "speaker": "longxiaochun",
        "pitch": 60,
        "speed": 1.2,
        "volume": 55
    }
    
    print(f"voice_params: {voice_params}")
    
    audio = await engine.synthesize(
        text="测试文本",
        voice_params=voice_params,
        emotion="neutral"
    )
    
    if audio and len(audio) > 0:
        print(f"SUCCESS: {len(audio)} bytes")
    else:
        print("FAILED: empty audio")

if __name__ == "__main__":
    asyncio.run(test())
