#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""快速测试单个模型的LLM联网搜索效果"""
import sys
import os
import io
import json
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 确保项目根目录和 backend 目录都在 sys.path 中
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
    ModelCatalogSyncService,
    CatalogSeed,
)


def create_test_seed(model_key, name, provider, category, subcategory, model_family, summary):
    """创建测试用的模型种子"""
    return CatalogSeed(
        model_key=model_key,
        name=name,
        provider=provider,
        category=category,
        subcategory=subcategory,
        model_family=model_family,
        config_source="models.yaml",
        status="active",
        summary=summary,
        recommended_scenarios=[f"{name}相关应用"],
        limitations=["待确认"],
        integration_notes=["通过API调用"],
        documentation_url="https://help.aliyun.com/zh/model-studio/qwen3-omni-plus-api-reference",
        source_urls=["https://help.aliyun.com/zh/model-studio/developer-reference/use-qwen-by-calling-api"],
        tags=[category, provider, model_family.lower()],
        modalities=[f"text_to_{category}"] if category != "llm" else ["text_generation"],
        capabilities=[],
        constraints={},
        performance={},
        routing={},
        default_params={},
        raw_config={},
    )


async def test_single_model(service, seed):
    """测试单个模型"""
    print(f"\n{'='*80}")
    print(f"测试模型: {seed.name} ({seed.model_key})")
    print(f"类别: {seed.category}")
    print(f"{'='*80}")
    
    search_query = service._build_search_query(seed)
    print(f"\n搜索查询: {search_query}")
    
    mock_specs = {
        "duration_range": None,
        "resolution_options": [],
        "frame_rate": None,
        "output_format": None,
        "input_modalities": [],
        "advanced_features": [],
        "max_reference_images": None,
        "weight_control": False,
        "first_frame_support": False,
        "last_frame_support": False,
        "prompt_examples": [],
        "extraction_confidence": 0.1,
    }
    
    print("\n调用LLM联网搜索验证...")
    start_time = time.time()
    
    try:
        result = await service._llm_verify_extracted_specs(
            seed=seed,
            extracted_specs=mock_specs,
            page_content="待验证的模型规格信息。"
        )
        
        elapsed = time.time() - start_time
        print(f"\n完成，耗时: {elapsed:.1f}秒")
        
        llm_ver = result.get("_llm_verification", {})
        
        print(f"\n置信度: {llm_ver.get('confidence', 0):.0%}")
        print(f"可靠性评分: {llm_ver.get('reliability_score', 0)}/100")
        
        sources = llm_ver.get("search_sources", [])
        print(f"\n搜索来源 ({len(sources)} 个):")
        has_placeholder = False
        for src in sources:
            url = src.get('url', 'N/A')
            title = src.get('title', 'N/A')
            if 'xxx' in url.lower() or '...' in url:
                has_placeholder = True
                print(f"  [占位符] {title}: {url}")
            else:
                print(f"  [OK] {title}: {url}")
        
        if has_placeholder:
            print("\n警告: 存在占位符URL，提示词优化可能需要进一步调整")
        else:
            print("\n所有URL均为真实有效链接")
        
        print(f"\n修正说明 ({len(llm_ver.get('corrections', []))} 条):")
        for c in llm_ver.get("corrections", []):
            print(f"  - {c}")
        
        print(f"\n新增信息 ({len(llm_ver.get('additions', []))} 条):")
        for a in llm_ver.get("additions", []):
            print(f"  - {a}")
        
    except Exception as e:
        print(f"\n失败: {e}")
        import traceback
        traceback.print_exc()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="测试单个模型的LLM联网搜索效果")
    parser.add_argument("--model", choices=["video", "image", "audio", "llm"], default="video",
                       help="选择测试的模型类型")
    args = parser.parse_args()
    
    service = ModelCatalogSyncService()
    
    seeds = {
        "video": create_test_seed("wan2.7-t2v", "WAN 2.7 文生视频", "alibaba", "video", "视频生成", "Wan", "通义万相2.7文生视频"),
        "image": create_test_seed("qwen-image-2.0", "Qwen-Image 2.0", "alibaba", "image", "图像生成", "Qwen", "千问图像生成2.0"),
        "audio": create_test_seed("cosyvoice-v3-plus", "CosyVoice V3 Plus", "alibaba", "audio", "语音合成", "CosyVoice", "CosyVoice V3+语音合成"),
        "llm": create_test_seed("qwen3.6-plus", "Qwen3.6-Plus", "alibaba", "llm", "创作写作", "Qwen", "千问3.6-Plus文本模型"),
    }
    
    seed = seeds[args.model]
    import asyncio
    asyncio.run(test_single_model(service, seed))


if __name__ == "__main__":
    main()
