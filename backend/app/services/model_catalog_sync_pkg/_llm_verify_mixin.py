from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
import asyncio
import json
import logging
import os
import re

import httpx
import yaml
from sqlalchemy.orm import Session, selectinload

from app.models.model_catalog import ModelCatalogEntry, ModelCatalogSource

try:
    from core.unified_llm_client import get_llm_client
    _LLM_CLIENT_AVAILABLE = True
except ImportError:
    _LLM_CLIENT_AVAILABLE = False
    get_llm_client = None

try:
    from core.model_catalog_runtime import get_model_catalog_runtime_index
    _RUNTIME_SIGNAL_AVAILABLE = True
except ImportError:
    _RUNTIME_SIGNAL_AVAILABLE = False
    get_model_catalog_runtime_index = None

logger = logging.getLogger(__name__)

from app.services.model_catalog_sync_pkg._constants import (
    CatalogSeed, SourceVerification, DetailedSpecExtraction,
    _LLM_VERIFICATION_TRIGGER, PRICING_VERIFICATION_CONFIG,
    VERIFIED_PRICING_DATA, _ERROR_PAGE_KEYWORDS,
)

class LlmVerifyMixin:
    def _build_search_query(self, seed: CatalogSeed) -> str:
        """根据模型类型构建精准的搜索查询词。

        Args:
            seed: 模型种子信息

        Returns:
            优化后的搜索查询字符串
        """
        provider_map = {
            "alibaba": "阿里云百炼",
            "volcengine": "火山方舟",
            "kuaishou": "可灵",
            "pixverse": "PixVerse",
            "vidu": "Vidu",
            "kunlun": "Mureka",
            "minimax": "MiniMax",
            "deepseek": "DeepSeek",
        }
        provider_label = provider_map.get(seed.provider, seed.provider)

        model_name = seed.name or seed.model_key

        query_templates = {
            "video": f"{model_name} {provider_label} API 视频生成 参数 duration resolution 输入格式",
            "image": f"{model_name} {provider_label} API 图片生成 参数 prompt 分辨率 风格",
            "audio": f"{model_name} {provider_label} API 语音合成 参数 音色 采样率",
            "llm": f"{model_name} {provider_label} API 参数 上下文窗口 函数调用 联网搜索",
        }

        base_query = query_templates.get(seed.category, f"{model_name} {provider_label} API 参数 功能")

        site_hints = {
            "alibaba": "site:help.aliyun.com",
            "volcengine": "site:volcengine.com",
            "kuaishou": "site:help.aliyun.com",
            "pixverse": "site:help.aliyun.com",
            "vidu": "site:help.aliyun.com OR site:platform.vidu.cn",
            "kunlun": "site:platform.mureka.cn",
            "minimax": "site:help.aliyun.com",
            "deepseek": "site:help.aliyun.com",
        }
        site_hint = site_hints.get(seed.provider, "")

        if site_hint:
            return f"{base_query} {site_hint}"
        return base_query

    def _get_type_specific_guidance(self, category: str) -> str:
        """获取按模型类型的 LLM 校验提示指导。
        
        Args:
            category: 模型类别（video/image/audio/llm）
            
        Returns:
            类型特定的校验指导文本
        """
        guidance_map = {
            "video": """- 时长范围：如 "支持 5-10 秒"
- 分辨率选项：如 "720p, 1080p"
- 帧率：如 "24fps, 30fps"
- 输出格式：如 "mp4, webm"
- 输入模态：文本/图像/视频/音频
- 高级功能：多镜头叙事、声画同步、运镜控制、动作控制
- 首帧/尾帧支持：是否支持首帧/尾帧控制
- 参考图上限：最多支持几张参考图""",
            "image": """- 分辨率选项：如 "1024x1024, 512x512"
- 宽高比：如 "16:9, 1:1, 9:16"
- 输出格式：如 "png, jpg, webp"
- 输入模态：文本/图像
- 风格支持：是否支持多种风格
- Seed 支持：是否支持随机种子（可复现性）
- 负向提示词：是否支持排除内容
- 图像编辑：是否支持基于参考图编辑
- 多图输入：最多支持几张参考图""",
            "audio": """- 采样率：如 "16kHz, 44.1kHz"
- 音频格式：如 "mp3, wav, flac"
- 时长范围：如 "最长 30 秒"
- 输入模态：文本/音频/视频
- 声音克隆：是否支持音色复制
- 多语言支持：支持哪些语言
- 情感控制：是否支持情感表达
- 音乐风格：是否支持音乐生成
- 乐器控制：是否支持指定乐器
- 人声分离：是否支持人声提取""",
            "llm": """- 上下文窗口：如 "128K tokens"
- 最大输出：如 "8192 tokens"
- 输入模态：文本/图像/音频/视频
- 函数调用：是否支持 tool calling
- 流式输出：是否支持 streaming
- 多轮对话：对话能力
- 推理能力：链式思维推理
- 代码生成：编程能力
- 数学能力：数学计算推理
- 联网搜索：是否支持 web search""",
        }
        return guidance_map.get(category, "- 基础字段：分辨率、格式、时长等通用参数")

    async def _llm_verify_extracted_specs(
        self,
        seed: CatalogSeed,
        extracted_specs: dict[str, Any],
        page_content: str,
    ) -> dict[str, Any]:
        """使用大模型验证提取的规格信息可靠性。

        使用 qwen3.6-plus 的联网搜索能力，主动搜索模型相关信息进行验证。

        Args:
            seed: 模型种子信息
            extracted_specs: 正则提取的规格信息
            page_content: 页面文本内容

        Returns:
            验证后的规格信息，包含置信度和修正建议
        """
        if not _LLM_CLIENT_AVAILABLE:
            logger.warning("LLM 客户端不可用，跳过大模型校验")
            return extracted_specs

        try:
            llm_client = get_llm_client(strategy="auto")
            model_id = os.getenv("VERIFICATION_LLM_MODEL", "qwen3.6-plus")

            search_query = self._build_search_query(seed)
            
            prompt = f"""你是一个专业的模型能力分析专家。请通过联网搜索验证以下模型信息。

## 待验证模型
- 模型名称: {seed.name}
- 模型ID: {seed.model_key}
- 提供商: {seed.provider}
- 类别: {seed.category}

## 按类型重点校验字段
{self._get_type_specific_guidance(seed.category)}

## 已提取的规格信息（需要验证）
```json
{json.dumps(extracted_specs, ensure_ascii=False, indent=2)}
```

## 已有页面内容
```
{page_content[:3000]}
```

## 任务
1. 使用联网搜索功能，搜索该模型的官方文档和权威评测
2. 验证已提取信息的准确性
3. 补充遗漏的重要规格
4. 修正明显错误的信息
5. 评估整体提取置信度（0-1）

## 重要要求
- search_sources 中必须使用搜索功能实际返回的真实URL，禁止使用占位符（如xxx、...、doc-xxxxxx等）
- 如果搜索未返回某个来源，不要编造URL，仅包含实际获取的URL
- 每个search_source的url字段必须是完整有效的HTTP URL

## 输出格式
请以 JSON 格式输出，包含以下字段：
- verified_specs: 验证后的规格信息
- confidence: 整体置信度（0-1）
- corrections: 修正说明列表
- additions: 新增信息列表
- reliability_score: 数据可靠性评分（0-100）
- search_sources: 搜索来源列表（必须包含真实有效的URL和标题）

只输出 JSON，不要其他解释。"""

            messages = [
                {"role": "system", "content": "你是一个专业的模型能力分析专家，擅长联网搜索并验证模型规格信息。请使用联网搜索功能获取最新信息。"},
                {"role": "user", "content": prompt},
            ]

            response = await llm_client.chat(
                messages=messages,
                model=model_id,
                temperature=0.1,
                max_tokens=2000,
                extra_body={
                    "enable_search": True,
                    "search_options": {
                        "forced_search": True,
                        "search_strategy": "max",
                        "enable_source": True,
                    }
                },
            )

            response_text = response.strip()
            if response_text.startswith("```"):
                response_text = re.sub(r"^```(?:json)?\s*", "", response_text)
                response_text = re.sub(r"\s*```$", "", response_text)

            llm_result = json.loads(response_text)

            verified_specs = llm_result.get("verified_specs", extracted_specs)
            confidence = llm_result.get("confidence", 0.5)
            corrections = llm_result.get("corrections", [])
            additions = llm_result.get("additions", [])
            reliability_score = llm_result.get("reliability_score", 50)
            search_sources = llm_result.get("search_sources", [])

            logger.info(
                f"LLM 联网搜索校验完成 | model={seed.model_key} | confidence={confidence:.2f} | reliability={reliability_score}"
            )

            if corrections:
                logger.info(f"LLM 修正: {corrections}")
            if additions:
                logger.info(f"LLM 补充: {additions}")
            if search_sources:
                logger.info(f"LLM 搜索来源: {len(search_sources)} 条")

            verified_specs["_llm_verification"] = {
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "confidence": confidence,
                "reliability_score": reliability_score,
                "corrections": corrections,
                "additions": additions,
                "model": model_id,
                "search_enabled": True,
                "search_sources": search_sources[:5],
            }

            return verified_specs

        except json.JSONDecodeError as e:
            logger.warning(f"LLM 响应解析失败: {e}")
            return extracted_specs
        except Exception as e:
            logger.warning(f"LLM 联网搜索校验失败: {e}")
            return extracted_specs

    def _should_trigger_llm_verification(
        self,
        seed: CatalogSeed,
        existing_entry: Optional["ModelCatalogEntry"] = None,
    ) -> tuple[bool, str]:
        """判断是否应该触发LLM联网搜索验证。

        智能触发策略：
        1. 新模型首次校验 → 必须联网
        2. 已有校验结果且未过期 → 跳过联网，使用缓存
        3. 已有校验结果但已过期 → 重新联网
        4. 配置发生变更 → 强制联网
        5. 环境变量控制是否跳过静态校验的LLM

        Args:
            seed: 模型种子信息
            existing_entry: 数据库中已有的模型条目（如果有）

        Returns:
            (should_trigger: bool, reason: str)
        """
        # 策略1：静态校验模式，跳过所有LLM
        if _LLM_VERIFICATION_TRIGGER["skip_llm_for_static_validation"]:
            return False, "静态校验模式，跳过LLM联网搜索"

        # 策略2：新模型首次校验，必须联网
        if existing_entry is None:
            if _LLM_VERIFICATION_TRIGGER["force_verify_new_models"]:
                return True, "新模型首次校验，强制联网搜索"
            else:
                return False, "新模型，但配置为不强制联网"

        # 策略3：检查已有校验结果是否过期
        last_verified_at = existing_entry.last_verified_at
        if last_verified_at is not None:
            now = datetime.now(timezone.utc)
            age_hours = (now - last_verified_at).total_seconds() / 3600
            max_age = _LLM_VERIFICATION_TRIGGER["max_verified_age_hours"]

            if age_hours < max_age:
                # 校验结果还在有效期内
                return False, f"已有校验结果（{age_hours:.1f}小时前），在有效期内（{max_age}小时）"
            else:
                # 校验结果已过期
                return True, f"校验结果已过期（{age_hours:.1f}小时 > {max_age}小时）"

        # 策略4：没有校验时间记录，需要联网
        return True, "缺少校验时间记录，需要联网验证"

    def _sync_verify_with_llm(
        self,
        seed: CatalogSeed,
        extracted_specs: dict[str, Any],
        page_content: str,
    ) -> dict[str, Any]:
        """同步包装器：在同步上下文中调用异步 LLM 校验。"""
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is None:
                # No running event loop (e.g., in background thread)
                # Create a new event loop for this thread
                new_loop = asyncio.new_event_loop()
                try:
                    asyncio.set_event_loop(new_loop)
                    return new_loop.run_until_complete(
                        self._llm_verify_extracted_specs(seed, extracted_specs, page_content)
                    )
                finally:
                    new_loop.close()
                    asyncio.set_event_loop(None)
            else:
                # Event loop is already running (e.g., in async context)
                future = asyncio.run_coroutine_threadsafe(
                    self._llm_verify_extracted_specs(seed, extracted_specs, page_content),
                    loop,
                )
                return future.result(timeout=60)
        except Exception as e:
            logger.warning(f"同步调用 LLM 校验失败: {e}")
            return extracted_specs

