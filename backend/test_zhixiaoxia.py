"""Test zhixiaoxia voice"""
import os
from dotenv import load_dotenv
load_dotenv()

import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat

api_key = os.getenv("DASHSCOPE_API_KEY")
dashscope.api_key = api_key

print("="*70)
print("Testing zhixiaoxia voice:")
print("="*70)

try:
    synthesizer = SpeechSynthesizer(
        model="cosyvoice-v1",
        voice="zhixiaoxia",  # 问题音色
        format=AudioFormat.MP3_22050HZ_MONO_256KBPS,
        pitch_rate=1.0,
        speech_rate=1.0,
        volume=50
    )
    
    result = synthesizer.call("第一章 废丹房里的异象")
    
    if isinstance(result, bytes):
        print(f"SUCCESS: {len(result)} bytes")
    else:
        print(f"FAILED: {result}")
        
except Exception as e:
    print(f"ERROR: {e}")

print("\n" + "="*70)
print("Testing longxiaochun voice (known working):")
print("="*70)

try:
    synthesizer = SpeechSynthesizer(
        model="cosyvoice-v1",
        voice="longxiaochun",  # 已知可用
        format=AudioFormat.MP3_22050HZ_MONO_256KBPS,
        pitch_rate=1.0,
        speech_rate=1.0,
        volume=50
    )
    
    result = synthesizer.call("第一章 废丹房里的异象")
    
    if isinstance(result, bytes):
        print(f"SUCCESS: {len(result)} bytes")
    else:
        print(f"FAILED: {result}")
        
except Exception as e:
    print(f"ERROR: {e}")
