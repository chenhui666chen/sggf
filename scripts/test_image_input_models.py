#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
综合测试脚本 - 按依赖顺序测试模型:
1. 先用图片生成模型生成测试图片
2. 用文生视频模型生成测试视频
3. 测试需要图片输入的视频模型
4. 测试需要视频输入的视频编辑模型
"""
import sys
import os
import io
import time
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from adapters.registry import ModelRegistry

registry = ModelRegistry()
registry._ensure_builtin_registration()


def test_model(model_id, prompt="", **kwargs):
    try:
        adapter = registry.get_adapter(model_id)
        if adapter is None:
            return False, "No adapter registered"
        result = adapter.generate(prompt=prompt, **kwargs)
        if result.success:
            output_info = ""
            if result.outputs:
                first = str(result.outputs[0])
                if first.startswith("http"):
                    output_info = f"URL: {first[:80]}..."
                else:
                    output_info = first[:80]
            return True, f"OK {output_info} ({result.latency:.1f}s)", result.outputs
        else:
            return False, (result.error or "Unknown error")[:200], []
    except Exception as e:
        return False, str(e)[:200], []


def main():
    image_url = None
    video_url = None
    results = []

    # ============================================================
    # Step 1: 生成测试图片
    # ============================================================
    print("=" * 80)
    print("Step 1: 生成测试图片 (qwen-image-2.0)")
    print("=" * 80)
    success, msg, outputs = test_model("qwen-image-2.0", "a cute orange cat sitting on a windowsill, photorealistic, high quality")
    print(f"  qwen-image-2.0: [{'PASS' if success else 'FAIL'}] {msg}")
    if success and outputs:
        image_url = outputs[0]
        print(f"  Image URL: {image_url[:100]}...")
    else:
        print("  WARNING: 无法生成测试图片，将使用默认URL")
        image_url = "https://dashscope.oss-cn-beijing.aliyuncs.com/images/dog_and_girl.jpeg"

    # ============================================================
    # Step 2: 生成测试视频 (用于videoedit)
    # ============================================================
    print()
    print("=" * 80)
    print("Step 2: 生成测试视频 (wan2.7-t2v)")
    print("=" * 80)
    success, msg, outputs = test_model("wan2.7-t2v", "a cute orange cat sitting on a windowsill, gentle movement, cinematic")
    print(f"  wan2.7-t2v: [{'PASS' if success else 'FAIL'}] {msg}")
    if success and outputs:
        video_url = outputs[0]
        print(f"  Video URL: {video_url[:100]}...")
    else:
        print("  WARNING: 无法生成测试视频，videoedit测试将跳过")

    # ============================================================
    # Step 3: 测试需要图片输入的视频模型
    # ============================================================
    print()
    print("=" * 80)
    print("Step 3: 测试需要图片输入的视频模型")
    print("=" * 80)

    image_video_models = [
        ("wan2.7-i2v", "animate this cat, make it blink slowly", {}),
        ("wan2.7-r2v", "a cat sitting on a windowsill looking outside, gentle movement", {}),
        ("pixverse-c1-r2v", "a cat on a windowsill, gentle movement", {}),
        ("pixverse-v6-t2v", "a cat on a windowsill, cinematic lighting", {}),
        ("vidu-q3-pro-img2video", "animate this cat, make it move naturally", {}),
        ("vidu-q3-pro-start-end2video", "a cat transitions from sitting to standing", {}),
        ("kling/kling-v3-omni-video-generation", "a cat on a windowsill, slow motion", {}),
        ("doubao-seedance-2-0", "一只橘猫坐在窗台上，慢慢眨眼", {}),
        ("doubao-seedance-2-0-fast", "一只橘猫坐在窗台上，慢慢眨眼", {}),
    ]

    for model_id, prompt, extra_kwargs in image_video_models:
        kwargs = {"image_path": image_url, **extra_kwargs}
        print(f"  Testing {model_id}...", end=" ", flush=True)
        success, msg, _ = test_model(model_id, prompt, **kwargs)
        status = "PASS" if success else "FAIL"
        print(f"[{status}] {msg}")
        results.append((model_id, success, msg))

    # ============================================================
    # Step 4: 测试需要视频输入的视频编辑模型
    # ============================================================
    print()
    print("=" * 80)
    print("Step 4: 测试需要视频输入的视频编辑模型")
    print("=" * 80)

    if video_url:
        video_edit_models = [
            ("wan2.7-videoedit", "将整个画面转换为温暖的日落风格", {"video_path": video_url}),
        ]
        for model_id, prompt, extra_kwargs in video_edit_models:
            kwargs = {"video_path": video_url, **extra_kwargs}
            print(f"  Testing {model_id}...", end=" ", flush=True)
            success, msg, _ = test_model(model_id, prompt, **kwargs)
            status = "PASS" if success else "FAIL"
            print(f"[{status}] {msg}")
            results.append((model_id, success, msg))
    else:
        print("  SKIPPED: 没有测试视频可用")

    # ============================================================
    # Step 5: 测试纯文生视频模型
    # ============================================================
    print()
    print("=" * 80)
    print("Step 5: 测试纯文生视频模型")
    print("=" * 80)

    text_video_models = [
        ("wan2.6-t2v-fast", "a dog running on the beach, cinematic"),
        ("vidu-q3-pro-text2video", "a bird flying over the ocean at sunset"),
        ("kling/kling-v3-video-generation", "a beautiful sunset over mountains, cinematic"),
        ("doubao-seedance-1-5-pro", "一只小狗在草地上奔跑"),
    ]

    for model_id, prompt in text_video_models:
        print(f"  Testing {model_id}...", end=" ", flush=True)
        success, msg, _ = test_model(model_id, prompt)
        status = "PASS" if success else "FAIL"
        print(f"[{status}] {msg}")
        results.append((model_id, success, msg))

    # ============================================================
    # 汇总
    # ============================================================
    print()
    print("=" * 80)
    print("测试结果汇总")
    print("=" * 80)

    passed = sum(1 for _, s, _ in results if s)
    failed = sum(1 for _, s, _ in results if not s)
    print(f"\n通过: {passed}/{len(results)}")
    print(f"失败: {failed}/{len(results)}")

    if failed > 0:
        print(f"\n失败模型:")
        for model_id, success, msg in results:
            if not success:
                print(f"  - {model_id}: {msg}")

    if passed > 0:
        print(f"\n通过模型:")
        for model_id, success, msg in results:
            if success:
                print(f"  + {model_id}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
