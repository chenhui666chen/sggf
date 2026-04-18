#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试模型信息来源网址的可达性和内容价值"""
import sys
import os
import io
from pathlib import Path
import json
import time

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

import httpx
from app.services.model_catalog_sync import (
    ModelCatalogSyncService,
)


# 待测试的网址列表
TEST_URLS = [
    {
        "url": "https://www.modelscope.cn/home",
        "name": "ModelScope (魔搭)",
        "description": "阿里巴巴达摩院模型开放平台",
    },
    {
        "url": "https://huggingface.co",
        "name": "Hugging Face",
        "description": "全球最大的AI模型社区",
    },
    {
        "url": "https://artificialanalysis.ai/",
        "name": "Artificial Analysis",
        "description": "AI模型性能分析和基准测试",
    },
    {
        "url": "https://arena.ai/",
        "name": "Arena AI",
        "description": "AI模型竞技场",
    },
    {
        "url": "https://waytoagi.feishu.cn/wiki/QPe5w5g7UisbEkkow8XcDmOpn8e",
        "name": "WayToAGI 飞书知识库",
        "description": "AGI学习资源和模型信息汇总",
    },
]


def test_url_reachability(url_info: dict) -> dict:
    """测试单个网址的可达性和基本信息"""
    url = url_info["url"]
    result = {
        "url": url,
        "name": url_info["name"],
        "description": url_info["description"],
        "reachable": False,
        "status_code": None,
        "final_url": None,
        "content_type": None,
        "content_length": None,
        "title": None,
        "error": None,
        "response_time": None,
    }
    
    try:
        start_time = time.time()
        with httpx.Client(
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
        ) as client:
            response = client.get(url)
            elapsed = time.time() - start_time
            
            result["reachable"] = response.status_code == 200
            result["status_code"] = response.status_code
            result["final_url"] = str(response.url)
            result["content_type"] = response.headers.get("content-type", "")
            result["content_length"] = response.headers.get("content-length", "")
            result["response_time"] = f"{elapsed:.2f}s"
            
            # 提取标题
            html_content = response.text
            import re
            title_match = re.search(r"<title[^>]*>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL)
            if title_match:
                result["title"] = title_match.group(1).strip()
            
    except httpx.TimeoutException as e:
        result["error"] = f"超时: {e}"
    except httpx.RequestError as e:
        result["error"] = f"请求错误: {e}"
    except Exception as e:
        result["error"] = f"未知错误: {e}"
    
    return result


def analyze_content_value(url: str, html_content: str) -> dict:
    """分析网页内容中可以提取哪些有价值的模型信息"""
    analysis = {
        "has_model_specs": False,
        "has_pricing": False,
        "has_api_docs": False,
        "has_benchmarks": False,
        "has_examples": False,
        "has_model_categories": False,
        "has_provider_info": False,
        "has_capabilities_description": False,
        "extractable_fields": [],
        "content_summary": "",
    }
    
    html_lower = html_content.lower()
    
    # 检查是否包含模型规格信息
    spec_keywords = ["parameter", "context", "token", "resolution", "duration", "model", "api", "endpoint"]
    if any(kw in html_lower for kw in spec_keywords):
        analysis["has_model_specs"] = True
        analysis["extractable_fields"].append("模型规格参数")
    
    # 检查是否包含价格信息
    pricing_keywords = ["price", "cost", "pricing", "免费", "付费", "元/", "$/", "token"]
    if any(kw in html_lower for kw in pricing_keywords):
        analysis["has_pricing"] = True
        analysis["extractable_fields"].append("价格信息")
    
    # 检查是否包含API文档
    api_keywords = ["api reference", "api文档", "接口", "endpoint", "request", "response"]
    if any(kw in html_lower for kw in api_keywords):
        analysis["has_api_docs"] = True
        analysis["extractable_fields"].append("API文档")
    
    # 检查是否包含基准测试
    benchmark_keywords = ["benchmark", "评测", "测试", "score", "accuracy", "performance"]
    if any(kw in html_lower for kw in benchmark_keywords):
        analysis["has_benchmarks"] = True
        analysis["extractable_fields"].append("基准测试数据")
    
    # 检查是否包含示例
    example_keywords = ["example", "示例", "demo", "sample", "use case"]
    if any(kw in html_lower for kw in example_keywords):
        analysis["has_examples"] = True
        analysis["extractable_fields"].append("使用示例")
    
    # 检查是否包含模型分类
    category_keywords = ["category", "分类", "text-to-image", "video", "audio", "llm"]
    if any(kw in html_lower for kw in category_keywords):
        analysis["has_model_categories"] = True
        analysis["extractable_fields"].append("模型分类信息")
    
    # 检查是否包含提供商信息
    provider_keywords = ["provider", "提供商", "provider", "organization", "公司"]
    if any(kw in html_lower for kw in provider_keywords):
        analysis["has_provider_info"] = True
        analysis["extractable_fields"].append("提供商信息")
    
    # 检查是否包含能力描述
    capability_keywords = ["capability", "能力", "feature", "特性", "support", "支持"]
    if any(kw in html_lower for kw in capability_keywords):
        analysis["has_capabilities_description"] = True
        analysis["extractable_fields"].append("能力描述")
    
    return analysis


def main():
    print("=" * 80)
    print("模型信息来源网址可达性测试")
    print("=" * 80)
    
    results = []
    for url_info in TEST_URLS:
        print(f"\n{'='*80}")
        print(f"测试: {url_info['name']}")
        print(f"URL: {url_info['url']}")
        print(f"说明: {url_info['description']}")
        print(f"{'='*80}")
        
        # 测试可达性
        result = test_url_reachability(url_info)
        results.append(result)
        
        print(f"\n可达性: {'✅ 可达' if result['reachable'] else '❌ 不可达'}")
        print(f"状态码: {result['status_code']}")
        print(f"响应时间: {result['response_time']}")
        
        if result['final_url'] != url_info['url']:
            print(f"最终URL: {result['final_url']}")
        
        if result['title']:
            print(f"页面标题: {result['title']}")
        
        if result['error']:
            print(f"错误: {result['error']}")
        
        if result['reachable']:
            print(f"\n内容类型: {result['content_type']}")
            
            # 尝试获取内容并分析价值
            try:
                with httpx.Client(
                    follow_redirects=True,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    },
                    timeout=httpx.Timeout(30.0, connect=10.0),
                ) as client:
                    response = client.get(url_info['url'])
                    analysis = analyze_content_value(url_info['url'], response.text)
                    
                    print(f"\n内容价值分析:")
                    print(f"  包含模型规格: {'是' if analysis['has_model_specs'] else '否'}")
                    print(f"  包含价格信息: {'是' if analysis['has_pricing'] else '否'}")
                    print(f"  包含API文档: {'是' if analysis['has_api_docs'] else '否'}")
                    print(f"  包含基准测试: {'是' if analysis['has_benchmarks'] else '否'}")
                    print(f"  包含使用示例: {'是' if analysis['has_examples'] else '否'}")
                    print(f"  包含模型分类: {'是' if analysis['has_model_categories'] else '否'}")
                    print(f"  包含提供商信息: {'是' if analysis['has_provider_info'] else '否'}")
                    print(f"  包含能力描述: {'是' if analysis['has_capabilities_description'] else '否'}")
                    
                    if analysis['extractable_fields']:
                        print(f"\n可提取字段: {', '.join(analysis['extractable_fields'])}")
                        
            except Exception as e:
                print(f"\n内容分析失败: {e}")
    
    # 汇总结果
    print(f"\n{'='*80}")
    print("汇总结果")
    print(f"{'='*80}")
    
    reachable_count = sum(1 for r in results if r['reachable'])
    print(f"\n可达网址: {reachable_count}/{len(results)}")
    
    print(f"\n{'网址':<50} {'状态':<8} {'响应时间':<12}")
    print(f"{'-'*50} {'-'*8} {'-'*12}")
    for r in results:
        status = "✅" if r['reachable'] else "❌"
        print(f"{r['url']:<50} {status:<8} {r['response_time'] or 'N/A':<12}")


if __name__ == "__main__":
    main()
