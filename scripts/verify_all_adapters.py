# -*- coding: utf-8 -*-
"""最终验证测试 - 测试关键模型的适配器 + 真实API调用"""
import sys, os, time, json
sys.path.insert(0, '.')

from adapters.registry import registry
from dotenv import load_dotenv
load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

# 关键模型测试用例
TEST_CASES = [
    {"id": "qwen-image-2.0", "type": "image", "prompt": "a cute cat, photorealistic"},
    {"id": "qwen-image-2.0-pro", "type": "image", "prompt": "a beautiful sunset"},
    {"id": "wan2.7-image", "type": "image", "prompt": "mountains with lake"},
    {"id": "qwen3.5-omni-plus", "type": "text", "prompt": "你好，请简短介绍自己。"},
    {"id": "qwen3.6-plus", "type": "text", "prompt": "你好，请简短介绍自己。"},
    {"id": "MiniMax/speech-2.8-turbo", "type": "tts", "prompt": "你好，这是MiniMax语音测试。"},
    {"id": "MiniMax/speech-2.8-hd", "type": "tts", "prompt": "你好，这是MiniMax高清语音测试。"},
    {"id": "cosyvoice-v3-plus", "type": "tts", "prompt": "你好，这是CosyVoice测试。"},
    {"id": "qwen3-tts-instruct-flash", "type": "tts", "prompt": "你好，这是Qwen3 TTS测试。"},
    # 图像模型（百炼平台）
    {"id": "doubao-seedream-4-5", "type": "image", "prompt": "a flower garden"},
    {"id": "doubao-seedream-5-0", "type": "image", "prompt": "a flower garden"},
    {"id": "kling-v3-image-generation", "type": "image", "prompt": "a tree in spring"},
    {"id": "kling-v3-omni-image-generation", "type": "image", "prompt": "a tree in spring"},
]

def test_adapter_api(model_id, test_type, prompt):
    adapter = registry.get_adapter(model_id)
    if not adapter:
        return {"success": False, "error": "No adapter"}
    
    start = time.time()
    try:
        if test_type == "tts":
            result = adapter.generate(prompt=prompt)
        elif test_type == "image":
            result = adapter.generate(prompt=prompt)
        elif test_type == "text":
            result = adapter.generate(prompt=prompt)
        else:
            result = adapter.generate(prompt=prompt)
        
        return {
            "success": result.success,
            "latency": round(time.time() - start, 2),
            "outputs": result.outputs[:1] if result.outputs else [],
            "error": result.error,
        }
    except Exception as e:
        return {"success": False, "latency": round(time.time() - start, 2), "error": str(e)}

if __name__ == "__main__":
    print("=" * 80)
    print("最终验证测试 - 适配器 + 真实API")
    print("=" * 80)
    
    results = []
    for tc in TEST_CASES:
        mid = tc["id"]
        print(f"\n>>> {mid} ({tc['type']})...", end="", flush=True)
        
        # Check adapter first
        adapter = registry.get_adapter(mid)
        if not adapter:
            print(f"\n  [SKIP] No adapter registered")
            results.append({"id": mid, "success": False, "error": "No adapter"})
            continue
        
        r = test_adapter_api(mid, tc["type"], tc["prompt"])
        results.append({"id": mid, **r})
        
        if r["success"]:
            out = r["outputs"][0] if r["outputs"] else ""
            if out.startswith("http"):
                out = out[:60] + "..."
            print(f"\n  [PASS] {r['latency']}s {out}")
        else:
            err = r.get("error", "unknown")[:120]
            print(f"\n  [FAIL] {r['latency']}s {err}")
    
    passed = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]
    
    print("\n" + "=" * 80)
    print("测试汇总")
    print("=" * 80)
    print(f"\n测试数: {len(results)}")
    print(f"通过: {len(passed)}")
    print(f"失败: {len(failed)}")
    print(f"通过率: {len(passed)/len(results)*100:.0f}%" if results else "N/A")
    
    if passed:
        print(f"\n>>> 通过 ({len(passed)}):")
        for r in passed:
            print(f"  [PASS] {r['id']} ({r.get('latency', 0)}s)")
    
    if failed:
        print(f"\n>>> 失败 ({len(failed)}):")
        for r in failed:
            print(f"  [FAIL] {r['id']}: {r.get('error', 'unknown')[:120]}")
    
    report = {"total": len(results), "passed": len(passed), "failed": len(failed),
              "passed_models": [r["id"] for r in passed],
              "failed_models": [{"id": r["id"], "error": r.get("error", "")[:120]} for r in failed]}
    print(f"\n{json.dumps(report, ensure_ascii=False, indent=2)}")
