"""快速验证全局Engine实例的配置"""
import sys
sys.path.insert(0, 'c:/Users/cuigu/novel_writing_agent/backend')

from app.services.audiobook import get_engine_instance

# 获取全局实例（模拟API调用时的行为）
engine = get_engine_instance()

print("=" * 60)
print("🔍 验证全局Engine实例配置")
print("=" * 60)
print(f"\n✅ TTS引擎配置:")
print(f"   Provider: {engine.tts_engine.provider}")
print(f"   并发数: {engine.tts_engine.max_concurrent}")
print(f"   请求间隔: {engine.tts_engine.request_delay}秒")
print(f"   Semaphore: {engine.tts_engine.semaphore._value}")

print("\n" + "=" * 60)
if engine.tts_engine.max_concurrent == 1:
    print("✅ 完美！全局实例配置正确！")
    print("💡 现在API调用会使用正确的并发=1配置")
else:
    print(f"❌ 错误！并发数={engine.tts_engine.max_concurrent}，应为1")
    print("⚠️ 需要重启后端服务")
print("=" * 60)
