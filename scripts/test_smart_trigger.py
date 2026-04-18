#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试智能触发策略效果"""
import sys
import os
import io
import json
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

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
    ModelCatalogSyncService,
    CatalogSeed,
    _LLM_VERIFICATION_TRIGGER,
)
from app.models.model_catalog import ModelCatalogEntry


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


def create_mock_entry(last_verified_at=None):
    """创建模拟的数据库条目"""
    entry = ModelCatalogEntry()
    entry.model_key = "test-model"
    entry.name = "Test Model"
    entry.provider = "alibaba"
    entry.category = "video"
    entry.subcategory = "test"
    entry.model_family = "Test"
    entry.config_source = "models.yaml"
    entry.status = "active"
    entry.summary = "Test"
    entry.last_verified_at = last_verified_at
    return entry


def test_trigger_strategy():
    """测试智能触发策略"""
    print("=" * 80)
    print("智能触发策略配置")
    print("=" * 80)
    for key, value in _LLM_VERIFICATION_TRIGGER.items():
        print(f"  {key}: {value}")
    
    service = ModelCatalogSyncService()
    
    test_cases = [
        ("新模型首次校验", create_test_seed("wan2.7-t2v", "WAN 2.7", "alibaba", "video", "视频生成", "Wan", "测试"), None),
        ("已有校验结果（1小时前）", create_test_seed("wan2.7-t2v", "WAN 2.7", "alibaba", "video", "视频生成", "Wan", "测试"), 
         create_mock_entry(last_verified_at=datetime.now(timezone.utc) - timedelta(hours=1))),
        ("已有校验结果（48小时前）", create_test_seed("wan2.7-t2v", "WAN 2.7", "alibaba", "video", "视频生成", "Wan", "测试"),
         create_mock_entry(last_verified_at=datetime.now(timezone.utc) - timedelta(hours=48))),
        ("已有校验结果（100小时前-过期）", create_test_seed("wan2.7-t2v", "WAN 2.7", "alibaba", "video", "视频生成", "Wan", "测试"),
         create_mock_entry(last_verified_at=datetime.now(timezone.utc) - timedelta(hours=100))),
        ("无校验时间记录", create_test_seed("wan2.7-t2v", "WAN 2.7", "alibaba", "video", "视频生成", "Wan", "测试"),
         create_mock_entry(last_verified_at=None)),
    ]
    
    print("\n" + "=" * 80)
    print("测试用例")
    print("=" * 80)
    
    for case_name, seed, existing_entry in test_cases:
        should_trigger, reason = service._should_trigger_llm_verification(seed, existing_entry)
        print(f"\n【{case_name}】")
        print(f"  模型: {seed.model_key}")
        print(f"  是否触发: {'是' if should_trigger else '否'}")
        print(f"  原因: {reason}")


if __name__ == "__main__":
    test_trigger_strategy()
