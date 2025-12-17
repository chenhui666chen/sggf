"""Test SpeechSynthesizer parameter acceptance"""
import os
from dotenv import load_dotenv
load_dotenv()

import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat
import inspect

api_key = os.getenv("DASHSCOPE_API_KEY")
dashscope.api_key = api_key

print("="*70)
print("SpeechSynthesizer __init__ signature:")
print("="*70)
sig = inspect.signature(SpeechSynthesizer.__init__)
for param_name, param in sig.parameters.items():
    print(f"  {param_name}: {param.annotation if param.annotation != inspect.Parameter.empty else 'Any'}")
    if param.default != inspect.Parameter.empty:
        print(f"    default = {param.default}")
print()

# Test with extra parameters
print("="*70)
print("Testing with pitch/speed/volume parameters:")
print("="*70)

try:
    # Try passing pitch, speed, volume
    synthesizer = SpeechSynthesizer(
        model="cosyvoice-v1",
        voice="longxiaochun",
        format=AudioFormat.MP3_22050HZ_MONO_256KBPS,
        pitch=60,  # Try this
        speed=1.2,  # Try this
        volume=55   # Try this
    )
    print("SUCCESS: Created with pitch/speed/volume")
    
    result = synthesizer.call("测试文本")
    if isinstance(result, bytes):
        print(f"SUCCESS: Generated {len(result)} bytes")
    else:
        print(f"FAILED: {result}")
        
except TypeError as e:
    print(f"ERROR: {e}")
    print("These parameters are NOT supported!")
