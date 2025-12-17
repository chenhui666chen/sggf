"""Verify batch configuration is active"""
import sys
sys.path.insert(0, 'c:/Users/cuigu/novel_writing_agent/backend')

from app.services.audiobook import get_engine_instance
import inspect

engine = get_engine_instance()

print("=" * 70)
print("Batch Configuration Verification")
print("=" * 70)

# Check TTS Engine config
print(f"\n[1] TTS Engine Basic Config:")
print(f"    Max Concurrent: {engine.tts_engine.max_concurrent}")
print(f"    Request Delay: {engine.tts_engine.request_delay}s")

# Check synthesize_batch signature
sig = inspect.signature(engine.tts_engine.synthesize_batch)
params = list(sig.parameters.keys())
print(f"\n[2] synthesize_batch Parameters:")
for i, param in enumerate(params, 1):
    param_obj = sig.parameters[param]
    default = param_obj.default
    if default == inspect.Parameter.empty:
        print(f"    {i}. {param} (required)")
    else:
        print(f"    {i}. {param} = {default}")

# Check if batch_size and batch_interval exist
has_batch_size = 'batch_size' in params
has_batch_interval = 'batch_interval' in params

print(f"\n[3] Batch Feature Status:")
if has_batch_size and has_batch_interval:
    print(f"    Status: ENABLED")
    print(f"    batch_size default: {sig.parameters['batch_size'].default}")
    print(f"    batch_interval default: {sig.parameters['batch_interval'].default}")
else:
    print(f"    Status: DISABLED")
    print(f"    Missing: {[] if has_batch_size else ['batch_size']} {[] if has_batch_interval else ['batch_interval']}")

print("\n" + "=" * 70)
if has_batch_size and has_batch_interval:
    print("SUCCESS! Batch strategy is configured!")
    print("\nExpected behavior:")
    print("  - 42 segments will be split into 5 batches")
    print("  - Each batch: 8-10 segments")
    print("  - Batch interval: 60 seconds")
    print("  - Request delay: 10 seconds per segment")
    print("  - Total time: ~12 minutes")
else:
    print("ERROR! Batch strategy NOT configured!")
    print("Service needs restart to load new code!")
print("=" * 70)
