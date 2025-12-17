"""
测试阿里云TTS旧版SDK
按照官方文档推荐的方式调用
"""
import os

# 设置API Key
api_key = "***REDACTED-DASHSCOPE-KEY***"
os.environ["DASHSCOPE_API_KEY"] = api_key

print("=" * 60)
print("🎤 阿里云TTS - 旧版SDK测试（官方推荐）")
print("=" * 60)
print()

# 测试1: 使用旧版SDK
print("📝 测试1: 旧版 SDK (dashscope.audio.tts)")
try:
    from dashscope.audio.tts import SpeechSynthesizer
    
    result = SpeechSynthesizer.call(
        model='sambert-zhichu-v1',
        text='今天天气怎么样',
        sample_rate=48000,
        format='wav'
    )
    
    if result.get_audio_data() is not None:
        audio_data = result.get_audio_data()
        print(f"   ✅ 成功！音频大小: {len(audio_data)} 字节")
        
        with open('test_old_sdk.wav', 'wb') as f:
            f.write(audio_data)
        print(f"   💾 已保存到: test_old_sdk.wav")
    else:
        print(f"   ❌ 失败：{result.get_response()}")
        
except Exception as e:
    print(f"   ❌ 异常：{e}")
    import traceback
    traceback.print_exc()

print()

# 测试2: 测试cosyvoice-v1是否在旧版SDK中可用
print("📝 测试2: 旧版 SDK + cosyvoice-v1")
try:
    from dashscope.audio.tts import SpeechSynthesizer
    
    result = SpeechSynthesizer.call(
        model='cosyvoice-v1',
        text='这是一个测试文本',
        sample_rate=22050,
        format='mp3'
    )
    
    if result.get_audio_data() is not None:
        audio_data = result.get_audio_data()
        print(f"   ✅ 成功！音频大小: {len(audio_data)} 字节")
        
        with open('test_old_sdk_cosyvoice.mp3', 'wb') as f:
            f.write(audio_data)
        print(f"   💾 已保存到: test_old_sdk_cosyvoice.mp3")
    else:
        print(f"   ❌ 失败：{result.get_response()}")
        
except Exception as e:
    print(f"   ❌ 异常：{e}")
    import traceback
    traceback.print_exc()

print()
print("=" * 60)
print("✅ 测试完成")
print("=" * 60)
