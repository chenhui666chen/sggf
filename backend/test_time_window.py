"""
测试阿里云TTS的时间窗口限制
目标：找出触发418错误的确切阈值
"""
import asyncio
import time
from dotenv import load_dotenv

load_dotenv()

async def test_time_window():
    """测试时间窗口限制"""
    from app.services.audiobook.tts_engine import TTSEngine
    
    print("=" * 70)
    print("Time Window Limit Test")
    print("=" * 70)
    
    engine = TTSEngine(
        provider="aliyun",
        enable_cache=False,
        max_concurrent=1
    )
    
    print(f"\nConfig:")
    print(f"  Request delay: {engine.request_delay}s")
    
    # 测试策略：持续调用直到失败
    test_text = "测试"
    voice_params = {"speaker": "longxiaochun", "pitch": 0, "speed": 1.0}
    
    print("\nStrategy: Call continuously until first 418 error")
    print("This will help identify the exact quota window\n")
    
    results = []
    start_time = time.time()
    
    for i in range(1, 51):  # 最多测试50次
        call_start = time.time()
        
        try:
            audio = await engine.synthesize(
                text=test_text,
                voice_params=voice_params,
                emotion="neutral"
            )
            
            elapsed = time.time() - call_start
            total_elapsed = time.time() - start_time
            
            if audio and len(audio) > 0:
                result = "SUCCESS"
                print(f"[{i:2d}] SUCCESS - {len(audio):5d} bytes | "
                      f"call: {elapsed:4.1f}s | total: {total_elapsed:5.1f}s")
            else:
                result = "EMPTY"
                print(f"[{i:2d}] EMPTY   - (418?)      | "
                      f"call: {elapsed:4.1f}s | total: {total_elapsed:5.1f}s")
                
            results.append({
                "index": i,
                "result": result,
                "total_time": total_elapsed
            })
            
            # 如果连续3次失败，说明触发限制了
            if len(results) >= 3:
                recent = [r["result"] for r in results[-3:]]
                if all(r in ["EMPTY", "FAIL"] for r in recent):
                    print(f"\nDetected quota limit at call #{i}")
                    break
                    
        except Exception as e:
            elapsed = time.time() - call_start
            total_elapsed = time.time() - start_time
            error_msg = str(e)[:50]
            
            result = "FAIL"
            print(f"[{i:2d}] FAIL    - {error_msg:50s} | "
                  f"call: {elapsed:4.1f}s | total: {total_elapsed:5.1f}s")
            
            results.append({
                "index": i,
                "result": result,
                "total_time": total_elapsed
            })
            
            # 检查是否触发限制
            if "418" in error_msg or len(results) >= 3:
                recent = [r["result"] for r in results[-3:]]
                if all(r in ["EMPTY", "FAIL"] for r in recent):
                    print(f"\nDetected quota limit at call #{i}")
                    break
        
        # 等待间隔（使用当前配置的10秒）
        if i < 50:
            await asyncio.sleep(engine.request_delay)
    
    # 分析结果
    print("\n" + "=" * 70)
    print("Analysis")
    print("=" * 70)
    
    success_count = sum(1 for r in results if r["result"] == "SUCCESS")
    fail_count = len(results) - success_count
    
    print(f"\nTotal calls: {len(results)}")
    print(f"Success: {success_count}")
    print(f"Failed: {fail_count}")
    
    if success_count > 0:
        last_success = [r for r in results if r["result"] == "SUCCESS"][-1]
        print(f"\nLast success at:")
        print(f"  Call #: {last_success['index']}")
        print(f"  Total time: {last_success['total_time']:.1f}s")
        
        if fail_count > 0:
            first_fail = [r for r in results if r["result"] != "SUCCESS"][0]
            print(f"\nFirst failure at:")
            print(f"  Call #: {first_fail['index']}")
            print(f"  Total time: {first_fail['total_time']:.1f}s")
            
            # 计算窗口
            window_size = first_fail["total_time"]
            print(f"\nEstimated quota window:")
            print(f"  Time window: ~{window_size:.0f} seconds ({window_size/60:.1f} minutes)")
            print(f"  Max calls in window: {success_count}")
            print(f"  Required delay: {window_size/success_count:.1f}s per call")
    
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(test_time_window())
