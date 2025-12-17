"""Debug 418 error with exact text"""
import asyncio
from dotenv import load_dotenv
load_dotenv()

async def test():
    import os
    import dashscope
    from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat
    
    api_key = os.getenv("DASHSCOPE_API_KEY")
    dashscope.api_key = api_key
    
    # Test different texts
    test_cases = [
        ("第一章 废丹房里的异象", "章节标题（11字）"),
        ("第一章 废丹房里的异象。", "标题+句号（12字）"),
        ("青岚宗废丹房，一个常年弥漫着陈旧药渣与尘埃气味的角落。", "正常叙述（30字）"),
        ("测试", "短文本（2字）"),
    ]
    
    for text, desc in test_cases:
        print(f"\n{'='*70}")
        print(f"Testing: {desc}")
        print(f"Text: {text}")
        print(f"{'='*70}")
        
        try:
            synthesizer = SpeechSynthesizer(
                model="cosyvoice-v1",
                voice="longxiaochun",
                format=AudioFormat.MP3_22050HZ_MONO_256KBPS
            )
            
            result = synthesizer.call(text)
            
            if isinstance(result, bytes):
                print(f"SUCCESS: {len(result)} bytes")
            else:
                print(f"FAILED: {result}")
                
        except Exception as e:
            print(f"ERROR: {e}")
        
        await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(test())
