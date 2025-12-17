"""验证最终配置"""
import sys
sys.path.insert(0, 'c:/Users/cuigu/novel_writing_agent/backend')

from app.services.audiobook import get_engine_instance

engine = get_engine_instance()

print("=" * 60)
print("Final Configuration Verification")
print("=" * 60)
print(f"\nTTS Engine Config:")
print(f"  Max Concurrent: {engine.tts_engine.max_concurrent}")
print(f"  Request Delay: {engine.tts_engine.request_delay}s")
print(f"  Semaphore: {engine.tts_engine.semaphore._value}")

print("\n" + "=" * 60)
if engine.tts_engine.max_concurrent == 1 and engine.tts_engine.request_delay == 10.0:
    print("SUCCESS! Configuration is optimal!")
    print("\nBatch Strategy:")
    print("  - 42 segments divided into 5 batches")
    print("  - Each batch: 8-10 segments")
    print("  - Batch interval: 60 seconds")
    print("  - Request delay: 10 seconds")
    print("\nEstimated Time:")
    print("  - Per segment: ~11s (10s delay + 1s process)")
    print("  - 42 segments: 42 x 11s = 462s = 7.7 min")
    print("  - Batch pauses: 60s x 4 = 240s = 4 min")
    print("  - Total: ~12 minutes")
else:
    print(f"WARNING! Config mismatch:")
    print(f"  Expected: concurrent=1, delay=10.0")
    print(f"  Actual: concurrent={engine.tts_engine.max_concurrent}, delay={engine.tts_engine.request_delay}")
print("=" * 60)
