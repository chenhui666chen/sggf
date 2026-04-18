#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试模型中心全量校验的实际联网搜索效果

用法:
    cd backend
    python scripts\\test_model_catalog_validation.py
"""
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


def create_test_seeds():
    """创建测试用的模型种子"""
    return [
        # 视频模型
        CatalogSeed(
            model_key="wan2.7-t2v",
            name="WAN 2.7 文生视频",
            provider="alibaba",
            category="video",
            subcategory="视频生成",
            model_family="Wan",
            config_source="models.yaml",
            status="active",
            summary="通义万相2.7文生视频模型",
            recommended_scenarios=["小说场景视频生成"],
            limitations=["需要文本提示词"],
            integration_notes=["通过百炼API调用"],
            documentation_url="https://help.aliyun.com/zh/model-studio/qwen3-omni-plus-api-reference",
            source_urls=["https://help.aliyun.com/zh/model-studio/developer-reference/use-qwen-by-calling-api"],
            tags=["video", "alibaba", "wan"],
            modalities=["text_to_video"],
            capabilities=[],
            constraints={},
            performance={},
            routing={},
            default_params={},
            raw_config={},
        ),
        # 图片模型
        CatalogSeed(
            model_key="qwen-image-2.0",
            name="Qwen-Image 2.0",
            provider="alibaba",
            category="image",
            subcategory="图像生成",
            model_family="Qwen",
            config_source="models.yaml",
            status="active",
            summary="通义千问图像生成模型2.0",
            recommended_scenarios=["小说角色插图"],
            limitations=["不支持复杂编辑"],
            integration_notes=["通过百炼API调用"],
            documentation_url="https://help.aliyun.com/zh/model-studio/qwen3-omni-plus-api-reference",
            source_urls=["https://help.aliyun.com/zh/model-studio/developer-reference/use-qwen-by-calling-api"],
            tags=["image", "alibaba", "qwen"],
            modalities=["text_to_image"],
            capabilities=[],
            constraints={},
            performance={},
            routing={},
            default_params={},
            raw_config={},
        ),
        # LLM模型
        CatalogSeed(
            model_key="qwen3.6-plus",
            name="Qwen3.6-Plus",
            provider="alibaba",
            category="llm",
            subcategory="创作写作",
            model_family="Qwen",
            config_source="llm_models.yaml",
            status="active",
            summary="通义千问3.6-Plus文本模型",
            recommended_scenarios=["小说章节生成", "创意写作"],
            limitations=["上下文窗口有限"],
            integration_notes=["支持联网搜索"],
            documentation_url="https://help.aliyun.com/zh/model-studio/qwen3-omni-plus-api-reference",
            source_urls=["https://help.aliyun.com/zh/model-studio/developer-reference/use-qwen-by-calling-api"],
            tags=["llm", "alibaba", "qwen"],
            modalities=["text_generation"],
            capabilities=[],
            constraints={},
            performance={},
            routing={},
            default_params={},
            raw_config={},
        ),
    ]


async def test_llm_web_search(service: ModelCatalogSyncService, seed: CatalogSeed):
    """测试单个模型的LLM联网搜索验证"""
    print(f"\n{'='*80}")
    print(f"测试模型: {seed.name} ({seed.model_key})")
    print(f"提供商: {seed.provider}")
    print(f"类别: {seed.category}")
    print(f"{'='*80}")
    
    # 显示生成的搜索查询词
    search_query = service._build_search_query(seed)
    print(f"\n生成的搜索查询: {search_query}")
    
    # 模拟提取的规格（用于LLM验证）
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
    
    print("\n正在调用LLM联网搜索验证...")
    start_time = time.time()
    
    try:
        result = await service._llm_verify_extracted_specs(
            seed=seed,
            extracted_specs=mock_specs,
            page_content="待验证的模型规格信息，需要通过联网搜索获取最新资料。"
        )
        
        elapsed = time.time() - start_time
        print(f"\n验证完成，耗时: {elapsed:.1f}秒")
        
        # 打印LLM返回的验证结果
        print(f"\n{'='*80}")
        print("LLM 联网搜索验证结果")
        print(f"{'='*80}")
        
        # 输出格式化的JSON结果
        print(json.dumps(result, ensure_ascii=False, indent=2))
        
        return result
        
    except Exception as e:
        print(f"\nLLM 联网搜索验证失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    print("模型中心全量校验 - LLM联网搜索测试")
    print(f"DASHSCOPE_API_KEY 已设置: {'是' if os.getenv('DASHSCOPE_API_KEY') else '否'}")
    
    # 初始化服务
    service = ModelCatalogSyncService()
    
    # 获取测试种子
    seeds = create_test_seeds()
    
    print(f"\n计划测试 {len(seeds)} 个模型")
    for i, seed in enumerate(seeds, 1):
        print(f"  {i}. {seed.name} ({seed.category})")
    
    # 异步运行测试
    import asyncio
    
    for seed in seeds:
        result = asyncio.run(test_llm_web_search(service, seed))
        
        if result:
            # 检查LLM是否返回了搜索来源
            llm_verification = result.get("_llm_verification", {})
            search_sources = llm_verification.get("search_sources", [])
            
            if search_sources:
                print(f"\n搜索来源 ({len(search_sources)} 个):")
                for src in search_sources:
                    print(f"  - {src.get('title', 'N/A')}: {src.get('url', 'N/A')}")
            else:
                print("\n未返回搜索来源")
            
            # 检查置信度
            confidence = llm_verification.get("confidence", 0)
            print(f"\n置信度: {confidence:.0%}")
            print(f"可靠性评分: {llm_verification.get('reliability_score', 0)}/100")
            
            # 检查修正说明
            corrections = llm_verification.get("corrections", [])
            if corrections:
                print(f"\n修正说明 ({len(corrections)} 条):")
                for c in corrections:
                    print(f"  - {c}")
            
            # 检查新增信息
            additions = llm_verification.get("additions", [])
            if additions:
                print(f"\n新增信息 ({len(additions)} 条):")
                for a in additions:
                    print(f"  - {a}")
        
        print("\n" + "="*80)
        print("等待5秒后继续下一个模型...")
        time.sleep(5)


if __name__ == "__main__":
    main()
