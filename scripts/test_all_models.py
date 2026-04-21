#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量模型测试脚本 - 逐个调用真实API"""
import sys
import os
import time
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from adapters.registry import registry
from schemas.model_spec import ModelSpec

# 测试用例
TEST_CASES = {
    # === 已验证通过的模型（快速验证） ===
    "qwen-image-2.0": {"type": "image", "prompt": "a red rose"},
    "qwen-image-2.0-pro": {"type": "image", "prompt": "a sunset"},
    "wan2.7-image": {"type": "image", "prompt": "mountains"},
    "qwen3.5-omni-plus": {"type": "text", "prompt": "你好"},
    "qwen3.6-plus": {"type": "text", "prompt": "你好"},
    "MiniMax/speech-2.8-turbo": {"type": "tts", "prompt": "你好"},
    "MiniMax/speech-2.8-hd": {"type": "tts", "prompt": "你好"},
    "cosyvoice-v3.5-plus": {"type": "tts", "prompt": "你好"},
    "qwen3-tts-instruct-flash": {"type": "tts", "prompt": "你好"},
    "doubao-seedream-4-5": {"type": "image", "prompt": "a flower"},
    "doubao-seedream-5-0": {"type": "image", "prompt": "a cat"},

    # === 新增待测试模型 ===
    "wan2.6-t2i": {"type": "image", "prompt": "a beautiful garden"},
    "kling/kling-v3-image-generation": {"type": "image", "prompt": "a tree in spring"},
    "kling/kling-v3-omni-image-generation": {"type": "image", "prompt": "a dog running"},
    "qwen3-vl-plus": {"type": "text", "prompt": "你好，请简短介绍自己"},
    "qwen-image-edit-plus": {"type": "image", "prompt": "change background to blue sky"},
    "qwen-image-edit-max": {"type": "image", "prompt": "change background to sunset"},
    "doubao-seed-2-0-pro": {"type": "text", "prompt": "你好"},
    "doubao-seed-2-0-lite": {"type": "text", "prompt": "你好"},
    "vidu-timing2audio": {"type": "audio", "prompt": "thunder sound effect"},
    "mureka-o1-instrumental": {"type": "audio", "prompt": "epic cinematic music"},

    # === 视频模型（只提交任务，不等待完成） ===
    "wan2.7-t2v": {"type": "video", "prompt": "a cat running"},
    "wan2.6-t2v-fast": {"type": "video", "prompt": "a dog playing"},
    "wan2.7-i2v": {"type": "video", "prompt": "animate this image"},
    "wan2.7-r2v": {"type": "video", "prompt": "a bird flying"},
    "wan2.7-videoedit": {"type": "video", "prompt": "edit video"},
    "pixverse-c1-r2v": {"type": "video", "prompt": "a landscape"},
    "pixverse-v6-t2v": {"type": "video", "prompt": "a city at night"},
    "vidu-q3-pro-text2video": {"type": "video", "prompt": "a fish swimming"},
    "vidu-q3-pro-img2video": {"type": "video", "prompt": "animate this"},
    "vidu-q3-pro-start-end2video": {"type": "video", "prompt": "transition video"},
    "kling/kling-v3-video-generation": {"type": "video", "prompt": "a sunset timelapse"},
    "kling/kling-v3-omni-video-generation": {"type": "video", "prompt": "a river flowing"},
    "doubao-seedance-2-0": {"type": "video", "prompt": "a cat walking"},
    "doubao-seedance-2-0-fast": {"type": "video", "prompt": "a dog running"},
    "doubao-seedance-1-5-pro": {"type": "video", "prompt": "a bird flying"},
}

VIDEO_MODELS = {
    "wan2.7-t2v", "wan2.6-t2v-fast", "wan2.7-i2v", "wan2.7-r2v", "wan2.7-videoedit",
    "pixverse-c1-r2v", "pixverse-v6-t2v",
    "vidu-q3-pro-text2video", "vidu-q3-pro-img2video", "vidu-q3-pro-start-end2video",
    "kling/kling-v3-video-generation", "kling/kling-v3-omni-video-generation",
    "doubao-seedance-2-0", "doubao-seedance-2-0-fast", "doubao-seedance-1-5-pro",
}


def test_model(model_id, test_case, skip_video_wait=True):
    """测试单个模型"""
    try:
        adapter = registry.get_adapter(model_id)
        if adapter is None:
            return False, "No adapter registered"

        prompt = test_case["prompt"]
        kwargs = {}

        if skip_video_wait and model_id in VIDEO_MODELS:
            kwargs["parameters"] = {"duration": 5, "resolution": "480P"}

        result = adapter.generate(prompt=prompt, **kwargs)

        if result.success:
            output_info = ""
            if result.outputs:
                first = str(result.outputs[0])
                if first.startswith("http"):
                    output_info = f"URL: {first[:80]}..."
                elif first.startswith("audio:"):
                    output_info = first
                else:
                    output_info = first[:80]
            return True, f"OK {output_info} ({result.latency:.1f}s)"
        else:
            error = result.error or "Unknown error"
            return False, error[:150]
    except Exception as e:
        return False, str(e)[:150]


def main():
    registry._ensure_builtin_registration()

    # 选择测试批次
    batch = sys.argv[1] if len(sys.argv) > 1 else "all"

    models_to_test = []
    if batch == "quick":
        # 快速测试：已验证通过的模型
        quick_models = [
            "qwen-image-2.0", "qwen-image-2.0-pro", "wan2.7-image",
            "qwen3.5-omni-plus", "qwen3.6-plus",
            "MiniMax/speech-2.8-turbo", "MiniMax/speech-2.8-hd",
            "cosyvoice-v3.5-plus", "qwen3-tts-instruct-flash",
            "doubao-seedream-4-5", "doubao-seedream-5-0",
        ]
        models_to_test = [(m, TEST_CASES[m]) for m in quick_models if m in TEST_CASES]
    elif batch == "new":
        # 新模型测试
        new_models = [
            "wan2.6-t2i", "kling/kling-v3-image-generation", "kling/kling-v3-omni-image-generation",
            "qwen3-vl-plus", "qwen-image-edit-plus", "qwen-image-edit-max",
            "doubao-seed-2-0-pro", "doubao-seed-2-0-lite",
            "vidu-timing2audio", "mureka-o1-instrumental",
        ]
        models_to_test = [(m, TEST_CASES[m]) for m in new_models if m in TEST_CASES]
    elif batch == "video":
        # 视频模型测试
        video_models = list(VIDEO_MODELS)
        models_to_test = [(m, TEST_CASES[m]) for m in video_models if m in TEST_CASES]
    else:
        models_to_test = list(TEST_CASES.items())

    print(f"\n{'='*80}")
    print(f"模型测试 - 批次: {batch} ({len(models_to_test)}个模型)")
    print(f"{'='*80}\n")

    results = []
    for model_id, test_case in models_to_test:
        print(f"测试 {model_id}...", end=" ", flush=True)
        skip_video = batch != "video"
        success, msg = test_model(model_id, test_case, skip_video_wait=skip_video)
        status = "PASS" if success else "FAIL"
        print(f"[{status}] {msg}")
        results.append((model_id, success, msg))

    # 汇总
    print(f"\n{'='*80}")
    print("测试结果汇总")
    print(f"{'='*80}")

    passed = sum(1 for _, s, _ in results if s)
    failed = sum(1 for _, s, _ in results if not s)

    print(f"\n通过: {passed}/{len(results)}")
    print(f"失败: {failed}/{len(results)}")

    if failed > 0:
        print(f"\n失败模型:")
        for model_id, success, msg in results:
            if not success:
                print(f"  - {model_id}: {msg}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
