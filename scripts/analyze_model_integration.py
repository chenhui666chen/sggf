# -*- coding: utf-8 -*-
"""
模型接入分析报告
根据 MODEL_INTEGRATION_REFERENCE.md 的标准，结合真实API测试和DashScope可用模型列表
"""

import sys
import os
import yaml
import json
import requests
import time
import base64
from pathlib import Path

sys.path.insert(0, '.')

# ============================================================
# 1. 加载 models.yaml
# ============================================================

models_yaml_path = Path(__file__).resolve().parent.parent / "config" / "models.yaml"
with open(models_yaml_path, "r", encoding="utf-8") as f:
    yaml_data = yaml.safe_load(f)

yaml_models = {m["id"]: m for m in yaml_data.get("models", [])}

print(f"models.yaml 中定义的模型总数: {len(yaml_models)}")

# ============================================================
# 2. 获取 DashScope 实际可用的模型列表
# ============================================================

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "***REDACTED-DASHSCOPE-KEY***")
resp = requests.get(
    "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
    headers={"Authorization": f"Bearer {DASHSCOPE_API_KEY}"},
    timeout=15,
)
dashscope_data = resp.json()
dashscope_models = set(m["id"] for m in dashscope_data.get("data", []))

print(f"DashScope 实际可用模型总数: {len(dashscope_models)}")

# ============================================================
# 3. 检查每个模型的接入状态
# ============================================================

# 已有适配器的模型（从之前的检查得知）
ADAPTER_MODELS = {
    "wan2.6-t2i", "wan2.7-t2v", "wan2.6-t2v-fast", "wan2.7-i2v",
    "wan2.7-r2v", "wan2.7-videoedit", "qwen3-vl-plus",
    "qwen-image-edit-plus", "qwen-image-edit-max",
}

# 新创建的适配器模型
NEW_ADAPTER_MODELS = {
    "qwen-image-2.0", "qwen-image-2.0-pro", "wan2.7-image",
    "doubao-seedream-4-5", "doubao-seedream-5.0",
    "doubao-seedance-2-0", "doubao-seedance-2-0-fast", "doubao-seedance-1-5-pro",
    "doubao-seed-2-0-pro", "doubao-seed-2-0-lite",
    "qwen3.5-omni-plus", "qwen3.6-plus",
    "qwen3-tts-flash", "cosyvoice-v3-plus",
    "MiniMax/speech-2.8-turbo", "MiniMax/speech-2.8-hd",
    "pixverse-c1-r2v", "pixverse-v6-t2v",
    "vidu-q3-pro-img2video", "vidu-q3-pro-text2video", "vidu-q3-pro-start-end2video",
    "vidu-timing2audio", "mureka-o1-instrumental",
    "kling-v3-video-generation", "kling-v3-omni-video-generation",
    "kling-v3-image-generation", "kling-v3-omni-image-generation",
}

all_with_adapter = ADAPTER_MODELS | NEW_ADAPTER_MODELS

# 分类
results = {
    "fully_connected": [],       # 有adapter + 模型存在于DashScope
    "adapter_no_model": [],      # 有adapter但模型不在DashScope（模型ID不存在）
    "model_no_adapter": [],      # 模型在DashScope但没有adapter
    "neither": [],               # 既无adapter也不在DashScope（纯配置）
    "unknown_provider": [],      # 非DashScope提供商的模型
}

for model_id, spec in yaml_models.items():
    provider = spec.get("provider", "unknown")
    has_adapter = model_id in all_with_adapter
    exists_on_dashscope = model_id in dashscope_models

    if provider not in ("alibaba", "dashscope"):
        results["unknown_provider"].append({
            "id": model_id,
            "provider": provider,
            "has_adapter": has_adapter,
        })
        continue

    if has_adapter and exists_on_dashscope:
        results["fully_connected"].append(model_id)
    elif has_adapter and not exists_on_dashscope:
        results["adapter_no_model"].append(model_id)
    elif not has_adapter and exists_on_dashscope:
        results["model_no_adapter"].append(model_id)
    else:
        results["neither"].append(model_id)

# ============================================================
# 4. 真实API调用测试
# ============================================================

TEST_FIXTURES = Path(__file__).resolve().parent / "test_fixtures"
TEST_IMAGE = str(TEST_FIXTURES / "test_1_1.png")

def _encode_image(path: str) -> str:
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return ""
    suffix = p.suffix.lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(suffix, "image/png")
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"

def test_model_api(model_id: str, category: str) -> dict:
    """Test actual API call"""
    result = {"id": model_id, "category": category, "success": False, "error": None}
    start = time.time()

    try:
        if category == "text":
            import openai
            client = openai.OpenAI(api_key=DASHSCOPE_API_KEY, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
            resp = client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": "你好，请简短回复。"}],
                max_tokens=50,
            )
            content = resp.choices[0].message.content
            result["success"] = bool(content)
            result["output_preview"] = content[:100]

        elif category == "tts":
            import openai
            client = openai.OpenAI(api_key=DASHSCOPE_API_KEY, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
            resp = client.audio.speech.create(
                model=model_id,
                voice="Cherry",
                input="这是一段测试语音。",
            )
            result["success"] = len(resp.content) > 0
            result["output_preview"] = f"audio:{len(resp.content)} bytes"

        elif category == "image":
            # Try sync first (many DashScope image models need sync via OpenAI compatible API)
            import openai
            client = openai.OpenAI(api_key=DASHSCOPE_API_KEY, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
            try:
                # Try OpenAI images API (sync)
                resp = client.images.generate(model=model_id, prompt="a beautiful sunset", size="1024x1024", n=1)
                urls = [img.url for img in resp.data if img.url]
                result["success"] = bool(urls)
                result["output_preview"] = urls[0][:80] + "..." if urls else ""
            except Exception as e1:
                # Fallback to async DashScope native API
                url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
                headers = {
                    "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
                    "Content-Type": "application/json",
                }
                # Some models need sync (no X-DashScope-Async header)
                payload = {
                    "model": model_id,
                    "input": {"messages": [{"role": "user", "content": [{"text": "a beautiful sunset"}]}]},
                    "parameters": {"size": "1024*1024", "n": 1},
                }
                resp = requests.post(url, json=payload, headers=headers, timeout=60)
                data = resp.json()

                if "output" in data and "results" in data["output"]:
                    # Sync response
                    results_list = data["output"].get("results", [])
                    urls = [r.get("url", "") for r in results_list if r.get("url")]
                    result["success"] = bool(urls)
                    result["output_preview"] = urls[0][:80] + "..." if urls else ""
                elif "output" in data and "task_id" in data["output"]:
                    # Async - poll
                    task_id = data["output"]["task_id"]
                    poll_start = time.time()
                    while time.time() - poll_start < 120:
                        pr = requests.get(
                            f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}",
                            headers={"Authorization": f"Bearer {DASHSCOPE_API_KEY}"},
                            timeout=10,
                        )
                        pd = pr.json()
                        status = pd.get("output", {}).get("task_status", "")
                        if status == "SUCCEEDED":
                            outputs = pd.get("output", {}).get("results", [])
                            urls = [o.get("url", "") for o in outputs if o.get("url")]
                            result["success"] = bool(urls)
                            result["output_preview"] = urls[0][:80] + "..." if urls else ""
                            break
                        elif status in {"FAILED", "CANCELED"}:
                            result["error"] = f"Task failed: {pd.get('output', {}).get('message', 'Unknown')}"
                            break
                        time.sleep(2)
                else:
                    result["error"] = f"Unexpected response: {json.dumps(data, ensure_ascii=False)[:150]}"

        elif category == "video":
            url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"
            headers = {
                "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            }
            payload = {
                "model": model_id,
                "input": {"prompt": "a cat walking on street"},
                "parameters": {"duration": 5, "resolution": "480P"},
            }
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            data = resp.json()
            task_id = data.get("output", {}).get("task_id")
            if not task_id:
                result["error"] = f"No task_id: {json.dumps(data, ensure_ascii=False)[:150]}"
            else:
                poll_start = time.time()
                while time.time() - poll_start < 300:
                    pr = requests.get(
                        f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}",
                        headers={"Authorization": f"Bearer {DASHSCOPE_API_KEY}"},
                        timeout=10,
                    )
                    pd = pr.json()
                    status = pd.get("output", {}).get("task_status", "")
                    if status == "SUCCEEDED":
                        outputs = pd.get("output", {}).get("results", [])
                        urls = [o.get("url", "") for o in outputs if o.get("url")]
                        result["success"] = bool(urls)
                        result["output_preview"] = urls[0][:80] + "..." if urls else ""
                        break
                    elif status in {"FAILED", "CANCELED"}:
                        result["error"] = f"Task failed: {pd.get('output', {}).get('message', 'Unknown')}"
                        break
                    time.sleep(2)

        elif category == "audio":
            # For mureka - test via their own API
            api_key = os.getenv("MUREKA_API_KEY", "")
            api_url = os.getenv("MUREKA_API_URL", "https://api.mureka.cn")
            if api_key and "mureka" in model_id.lower():
                r = requests.post(
                    f"{api_url}/api/v1/audio/generation",
                    json={"prompt": "cinematic music", "duration": 30},
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    timeout=60,
                )
                data = r.json()
                result["success"] = "audio_url" in data
            else:
                result["error"] = "No Mureka API key configured"
        else:
            result["error"] = f"Unknown category: {category}"

    except Exception as e:
        result["error"] = str(e)

    result["latency"] = round(time.time() - start, 2)
    return result

# ============================================================
# 5. 执行测试
# ============================================================

def _detect_category(model_id: str) -> str:
    mid = model_id.lower()
    if "tts" in mid or "speech" in mid or "cosyvoice" in mid:
        return "tts"
    if "video" in mid or "seedance" in mid:
        return "video"
    if "mureka" in mid:
        return "audio"
    if "seed" in mid or "doubao" in mid or "qwen3" in mid or "minimax" in mid and "speech" not in mid:
        return "text"
    return "image"

# Test all fully_connected models + those with adapter but no model
test_targets = results["fully_connected"] + results["adapter_no_model"]

# Filter out already-working models (wan2.6-t2i etc) and focus on the 27 new ones
new_targets = [m for m in test_targets if m in NEW_ADAPTER_MODELS]

print(f"\n{'=' * 80}")
print(f"真实API测试 - 目标模型数: {len(new_targets)}")
print(f"{'=' * 80}")

api_results = []
for model_id in new_targets:
    category = _detect_category(model_id)
    spec = yaml_models.get(model_id, {})
    provider = spec.get("provider", "unknown")

    # Skip non-DashScope models (they need different API keys)
    if provider not in ("alibaba", "dashscope"):
        if provider == "mureka" and os.getenv("MUREKA_API_KEY"):
            pass  # Test Mureka
        else:
            print(f"\n[SKIP] {model_id} (provider={provider}, no API access)")
            api_results.append({"id": model_id, "category": category, "success": False, "error": f"No API access for provider: {provider}", "latency": 0})
            continue

    # Skip models not on DashScope entirely
    if model_id not in dashscope_models:
        print(f"\n[SKIP] {model_id} (NOT on DashScope)")
        api_results.append({"id": model_id, "category": category, "success": False, "error": "Model not on DashScope", "latency": 0})
        continue

    print(f"\n>>> 测试: {model_id} ({category})...", end="", flush=True)
    tr = test_model_api(model_id, category)
    api_results.append(tr)

    if tr["success"]:
        print(f"\n  [PASS] latency={tr['latency']:.1f}s {tr.get('output_preview', '')[:60]}")
    else:
        print(f"\n  [FAIL] latency={tr['latency']:.1f}s {tr.get('error', 'unknown')[:120]}")

# ============================================================
# 6. 生成最终报告
# ============================================================

print(f"\n{'=' * 80}")
print("最终分析报告")
print(f"{'=' * 80}")

print(f"\n--- 全局统计 ---")
print(f"models.yaml 总模型数: {len(yaml_models)}")
print(f"DashScope 实际可用: {len(dashscope_models)}")
print(f"有适配器实现: {len(all_with_adapter)}")

print(f"\n--- 接入状态分类 ---")
print(f"完全接入 (adapter + DashScope存在): {len(results['fully_connected'])}")
for m in results['fully_connected']:
    print(f"  [OK] {m}")

print(f"\n有适配器但DashScope不存在: {len(results['adapter_no_model'])}")
for m in results['adapter_no_model']:
    print(f"  [WARN] {m} - 模型ID在DashScope上不存在")

print(f"\nDashScope存在但无适配器: {len(results['model_no_adapter'])}")
for m in results['model_no_adapter']:
    print(f"  [MISS] {m}")

print(f"\n既无适配器也不在DashScope: {len(results['neither'])}")
for m in results['neither']:
    print(f"  [NONE] {m}")

print(f"\n非DashScope提供商: {len(results['unknown_provider'])}")
for m in results['unknown_provider']:
    print(f"  [EXT] {m} (provider={m['provider']})")

# API测试结果汇总
print(f"\n{'=' * 80}")
print("API测试结果")
print(f"{'=' * 80}")

api_passed = [r for r in api_results if r.get("success")]
api_failed = [r for r in api_results if not r.get("success")]

print(f"\nAPI测试通过: {len(api_passed)}")
for r in api_passed:
    print(f"  [PASS] {r['id']} ({r['latency']:.1f}s)")

print(f"\nAPI测试失败: {len(api_failed)}")
for r in api_failed:
    print(f"  [FAIL] {r['id']}: {r.get('error', 'unknown')[:120]}")

# 保存完整报告
report = {
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    "summary": {
        "yaml_models": len(yaml_models),
        "dashscope_models": len(dashscope_models),
        "with_adapter": len(all_with_adapter),
        "fully_connected": len(results["fully_connected"]),
        "adapter_no_model": len(results["adapter_no_model"]),
        "model_no_adapter": len(results["model_no_adapter"]),
        "neither": len(results["neither"]),
        "unknown_provider": len(results["unknown_provider"]),
    },
    "fully_connected": results["fully_connected"],
    "adapter_no_model": results["adapter_no_model"],
    "model_no_adapter": results["model_no_adapter"],
    "neither": results["neither"],
    "unknown_provider": results["unknown_provider"],
    "api_test_results": api_results,
}

report_path = Path(__file__).resolve().parent / "model_integration_report.json"
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n完整报告已保存到: {report_path}")
