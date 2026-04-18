#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试使用指南自动生成功能"""
import sys
import os
import io
import json
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from dotenv import load_dotenv
load_dotenv()

from app.services.model_catalog_sync import (
    ModelCatalogEntry,
    _build_usage_guide,
    _get_category_common_guide,
)


def create_test_entry(model_key, name, category, raw_config=None):
    """创建测试用的模型目录条目"""
    return ModelCatalogEntry(
        model_key=model_key,
        name=name,
        provider="alibaba",
        category=category,
        subcategory="test",
        model_family="Test",
        config_source="models.yaml",
        status="active",
        summary=f"Test model {name}",
        modalities=["text_to_video"] if category == "video" else ["text_generation"],
        raw_config_json=raw_config or {},
    )


def test_usage_guide_generation():
    """测试使用指南生成"""
    print("=" * 80)
    print("测试使用指南自动生成功能")
    print("=" * 80)
    
    test_cases = [
        ("wan2.7-t2v", "WAN 2.7 文生视频", "video", {
            "detailed_specs": {
                "duration_range": "2-15秒",
                "resolution_options": ["720p", "1080p"],
                "input_modalities": ["text"],
                "advanced_features": ["多镜头叙事", "运镜控制", "尾帧控制"],
                "extraction_confidence": 0.9,
            }
        }),
        ("qwen-image-2.0", "Qwen-Image 2.0", "image", {
            "detailed_specs": {
                "resolution_options": ["1024x1024", "2048x2048"],
                "input_modalities": ["text", "image"],
                "advanced_features": ["中文渲染", "2K输出"],
                "extraction_confidence": 0.85,
            }
        }),
        ("qwen3.6-plus", "Qwen3.6-Plus", "llm", {
            "detailed_specs": {
                "context_window": "1000000 tokens",
                "input_modalities": ["text"],
                "advanced_features": ["function_calling", "web_search"],
                "extraction_confidence": 0.95,
            }
        }),
        ("cosyvoice-v3-plus", "CosyVoice V3 Plus", "audio", {
            "detailed_specs": {
                "sample_rate": "24kHz",
                "input_modalities": ["text"],
                "advanced_features": ["zero_shot_clone", "emotion_control"],
                "extraction_confidence": 0.95,
            }
        }),
    ]
    
    for model_key, name, category, raw_config in test_cases:
        print(f"\n{'='*80}")
        print(f"模型: {name} ({model_key})")
        print(f"类别: {category}")
        print(f"{'='*80}")
        
        entry = create_test_entry(model_key, name, category, raw_config)
        usage_guide = _build_usage_guide(entry)
        
        if usage_guide:
            print(f"\n使用指南标题: {usage_guide.get('title', 'N/A')}")
            print(f"模型标识: {usage_guide.get('model_key', 'N/A')}")
            print(f"类别: {usage_guide.get('category', 'N/A')}")
            
            sections = usage_guide.get("sections", [])
            print(f"\n章节数: {len(sections)}")
            for i, section in enumerate(sections, 1):
                section_title = section.get("title", "未命名")
                section_type = section.get("type", "unknown")
                print(f"  {i}. [{section_type}] {section_title}")
                
                items = section.get("items", [])
                if items:
                    for item in items[:3]:  # 只显示前3项
                        print(f"     - {item}")
                    if len(items) > 3:
                        print(f"     ... 及 {len(items) - 3} 项")
            
            print(f"\n完整JSON预览 (前1000字符):")
            print(json.dumps(usage_guide, ensure_ascii=False, indent=2)[:1000])
            print("...")
        else:
            print("\n未生成使用指南")


def test_category_common_guides():
    """测试各类别的通用指南模板"""
    print("\n" + "=" * 80)
    print("各类别通用指南模板")
    print("=" * 80)
    
    categories = ["video", "image", "audio", "llm"]
    for cat in categories:
        guide = _get_category_common_guide(cat)
        print(f"\n{cat.upper()} 类别通用指南:")
        print(f"  标题: {guide.get('title', 'N/A')}")
        sections = guide.get("sections", [])
        print(f"  章节数: {len(sections)}")
        for section in sections:
            print(f"    - {section.get('title', 'N/A')} ({section.get('type', 'N/A')})")


if __name__ == "__main__":
    test_category_common_guides()
    test_usage_guide_generation()
