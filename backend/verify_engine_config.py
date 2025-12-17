"""
验证AudiobookEngine的并发配置
"""
from app.services.audiobook.engine import AudiobookEngine

# 创建引擎实例（使用默认参数）
engine = AudiobookEngine()

print("=" * 60)
print("🔍 验证AudiobookEngine配置")
print("=" * 60)
print(f"\n✅ TTS引擎配置:")
print(f"   Provider: {engine.tts_engine.provider}")
print(f"   并发数 (max_concurrent): {engine.tts_engine.max_concurrent}")
print(f"   请求间隔 (request_delay): {engine.tts_engine.request_delay}秒")
print(f"   Semaphore值: {engine.tts_engine.semaphore._value}")

print("\n" + "=" * 60)
if engine.tts_engine.max_concurrent == 1:
    print("✅ 配置正确！并发数已设置为1")
    print("💡 现在可以安全生成有声书，不会触发限流")
else:
    print(f"⚠️ 配置异常！并发数为{engine.tts_engine.max_concurrent}，应为1")
print("=" * 60)
