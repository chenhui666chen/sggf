#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查所有模型验证状态"""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from adapters.registry import registry

# 已验证通过的模型列表
VERIFIED_MODELS = {
    # 图像生成 - 百炼
    "qwen-image-2.0",
    "qwen-image-2.0-pro",
    "wan2.7-image",
    "wan2.6-t2i",
    # 图像生成 - Kling (百炼异步)
    "kling/kling-v3-image-generation",
    "kling/kling-v3-omni-image-generation",
    # 图像生成 - 火山方舟
    "doubao-seedream-4-5",
    "doubao-seedream-5-0",
    # 图像编辑 - 百炼
    "qwen-image-edit-plus",
    "qwen-image-edit-max",
    # 文本对话 - 百炼
    "qwen3.5-omni-plus",
    "qwen3.6-plus",
    # 多模态对话 - 百炼
    "qwen3-vl-plus",
    # 文本对话 - 火山方舟
    "doubao-seed-2-0-pro",
    "doubao-seed-2-0-lite",
    # TTS - 百炼
    "MiniMax/speech-2.8-turbo",
    "MiniMax/speech-2.8-hd",
    "cosyvoice-v3-plus",
    "qwen3-tts-flash",
    # 音效 - Vidu平台
    "vidu-timing2audio",
    # 音乐 - Mureka平台
    "mureka-o1-instrumental",
    # 视频生成 - 百炼
    "wan2.7-t2v",
    "wan2.6-t2v-fast",
}

# 获取所有已注册的模型
registry._ensure_builtin_registration()
all_specs = registry.get_all_specs()

verified = []
unverified = []

for spec in all_specs:
    if spec.id in VERIFIED_MODELS:
        verified.append(spec)
    else:
        unverified.append(spec)

print("=" * 80)
print("模型验证状态报告")
print("=" * 80)

print(f"\n总计注册模型: {len(all_specs)}")
print(f"已验证通过: {len(verified)}")
print(f"未验证: {len(unverified)}")

print("\n" + "=" * 80)
print("已验证通过的模型")
print("=" * 80)
for spec in sorted(verified, key=lambda x: x.id):
    print(f"  [PASS] {spec.id:<45} | {spec.provider:<15} | {', '.join(spec.modality)}")

print("\n" + "=" * 80)
print("未验证的模型（按类型分组）")
print("=" * 80)

# 按modality分组
from collections import defaultdict
groups = defaultdict(list)
for spec in sorted(unverified, key=lambda x: x.id):
    if "text_to_image" in spec.modality or "image_to_image" in spec.modality:
        groups["图像生成"].append(spec)
    elif "text_to_video" in spec.modality or "image_to_video" in spec.modality or "reference_to_video" in spec.modality:
        groups["视频生成"].append(spec)
    elif "text_to_audio" in spec.modality or "text_to_speech" in spec.modality:
        groups["音频生成"].append(spec)
    elif "text_to_text" in spec.modality:
        groups["文本对话"].append(spec)
    else:
        groups["其他"].append(spec)

for group_name, specs in sorted(groups.items()):
    print(f"\n### {group_name} ({len(specs)}个)")
    for spec in specs:
        status = "需要测试"
        print(f"  [----] {spec.id:<45} | {spec.provider:<15} | {', '.join(spec.modality)}")

print("\n" + "=" * 80)
print("总结")
print("=" * 80)
print(f"  通过率: {len(verified)}/{len(all_specs)} ({len(verified)*100//len(all_specs)}%)")
print(f"  剩余未验证: {len(unverified)}个模型")
