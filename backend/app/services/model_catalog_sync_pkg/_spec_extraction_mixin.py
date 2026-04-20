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

class SpecExtractionMixin:
    def _extract_detailed_specs(
        self,
        html: str,
        seed: CatalogSeed,
        url: str,
    ) -> DetailedSpecExtraction:
        """从网页内容中提取详细规格信息（按模型类型差异化提取）。"""
        text = self._extract_search_text(html)
        extraction = DetailedSpecExtraction()
        extraction.extraction_source = url
        
        # 根据模型类型调用不同的提取逻辑
        if seed.category == "video":
            return self._extract_video_specs(text, seed, url)
        elif seed.category == "image":
            return self._extract_image_specs(text, seed, url)
        elif seed.category == "audio":
            return self._extract_audio_specs(text, seed, url)
        elif seed.category == "llm":
            return self._extract_llm_specs(text, seed, url)
        else:
            # 其他类型使用通用提取
            return self._extract_generic_specs(text, seed, url)
    
    def _extract_video_specs(
        self,
        text: str,
        seed: CatalogSeed,
        url: str,
    ) -> DetailedSpecExtraction:
        """视频模型专用提取逻辑。
        
        核心字段：duration_range, frame_rate, resolution, aspect_ratios
        高级功能：multi_shot, audio_sync, camera_control, motion_control
        输入模态：first_frame_support, last_frame_support, reference_images, reference_videos
        """
        extraction = DetailedSpecExtraction()
        extraction.extraction_source = url
        confidence_points = 0
        total_checks = 0

        # 核心字段：时长范围
        duration_match = _DURATION_RANGE_RE.search(text)
        if duration_match:
            extraction.duration_range = {
                "min_seconds": int(duration_match.group(1)),
                "max_seconds": int(duration_match.group(2)),
                "unit": "seconds",
                "step": 1,
            }
            confidence_points += 1
        total_checks += 1

        # 核心字段：分辨率选项
        resolutions = list(set(_RESOLUTION_RE.findall(text)))
        if resolutions:
            extraction.resolution_options = sorted(resolutions, key=lambda x: int(x[:-1]) if x[:-1].isdigit() else 100)
            confidence_points += 1
        total_checks += 1

        # 核心字段：帧率
        frame_rate_match = _FRAME_RATE_RE.search(text)
        if frame_rate_match:
            extraction.frame_rate = int(frame_rate_match.group(1))
            confidence_points += 1
        total_checks += 1

        # 输出格式
        formats = list(set(_FORMAT_RE.findall(text)))
        if formats:
            extraction.output_format = ", ".join(formats[:3])
            confidence_points += 0.5
        total_checks += 1

        # 输入模态（视频/音频特有）
        input_modalities = []
        if re.search(r"文本|text", text, re.IGNORECASE):
            input_modalities.append("text")
        if re.search(r"图像|图片|image", text, re.IGNORECASE):
            input_modalities.append("image")
        if re.search(r"视频|video", text, re.IGNORECASE):
            input_modalities.append("video")
        if re.search(r"音频|声音|audio", text, re.IGNORECASE):
            input_modalities.append("audio")
        if input_modalities:
            extraction.input_modalities = input_modalities
            confidence_points += 1
        total_checks += 1

        # 高级功能：视频特有
        advanced_features = []
        if _MULTI_SHOT_RE.search(text):
            advanced_features.append("multi_shot")
            confidence_points += 1
        if _AUDIO_SYNC_RE.search(text):
            advanced_features.append("audio_sync")
            confidence_points += 1
        if _PROMPT_REWRITE_RE.search(text):
            advanced_features.append("prompt_rewrite")
            confidence_points += 0.5
        # 运镜控制
        if re.search(r"运镜|camera.*control|镜头.*移动", text, re.IGNORECASE):
            advanced_features.append("camera_control")
            confidence_points += 1
        # 动作控制
        if re.search(r"动作.*控制|motion.*control|首尾.*帧", text, re.IGNORECASE):
            advanced_features.append("motion_control")
            confidence_points += 1
        if advanced_features:
            extraction.advanced_features = advanced_features
        total_checks += 5

        # 参考图/视频支持
        max_ref_match = _MAX_REFERENCE_RE.search(text)
        if max_ref_match:
            extraction.max_reference_images = int(max_ref_match.group(1))
            confidence_points += 1
        total_checks += 1

        # 首帧/尾帧支持
        if _FIRST_FRAME_RE.search(text):
            extraction.first_frame_support = True
            confidence_points += 1
        total_checks += 1

        if _LAST_FRAME_RE.search(text):
            extraction.last_frame_support = True
            confidence_points += 1
        total_checks += 1

        # 权重控制
        if _WEIGHT_CONTROL_RE.search(text):
            extraction.weight_control = True
            confidence_points += 1
        total_checks += 1

        extraction.extraction_confidence = confidence_points / max(total_checks, 1)
        return extraction
    
    def _extract_image_specs(
        self,
        text: str,
        seed: CatalogSeed,
        url: str,
    ) -> DetailedSpecExtraction:
        """图像模型专用提取逻辑。
        
        核心字段：resolution_options, aspect_ratios, max_output_count
        生成参数：style_support, seed_support, negative_prompt
        编辑功能：image_edit_support, multi_image_input, style_transfer
        """
        extraction = DetailedSpecExtraction()
        extraction.extraction_source = url
        confidence_points = 0
        total_checks = 0

        # 核心字段：分辨率选项
        resolutions = list(set(_RESOLUTION_RE.findall(text)))
        if resolutions:
            extraction.resolution_options = sorted(resolutions, key=lambda x: int(x[:-1]) if x[:-1].isdigit() else 100)
            confidence_points += 1
        total_checks += 1

        # 宽高比支持
        ratio_patterns = [
            r"(\d+:\d+)",
            r"支持.*比例.*?([\d:]+)",
        ]
        for pattern in ratio_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                ratios = list(set(matches))
                if ratios:
                    extraction.output_format = ", ".join(ratios[:5])  # 暂存到 output_format
                    confidence_points += 0.5
                    break
        total_checks += 1

        # 输出格式
        formats = list(set(_FORMAT_RE.findall(text)))
        if formats:
            extraction.output_format = (extraction.output_format + ", " if extraction.output_format else "") + ", ".join(formats[:3])
            confidence_points += 0.5
        total_checks += 1

        # 输入模态
        input_modalities = []
        if re.search(r"文本|text", text, re.IGNORECASE):
            input_modalities.append("text")
        if re.search(r"图像|图片|image", text, re.IGNORECASE):
            input_modalities.append("image")
        if input_modalities:
            extraction.input_modalities = input_modalities
            confidence_points += 1
        total_checks += 1

        # 风格支持
        if re.search(r"风格.*支持|style.*support|多种风格", text, re.IGNORECASE):
            if not extraction.advanced_features:
                extraction.advanced_features = []
            extraction.advanced_features.append("style_support")
            confidence_points += 1
        total_checks += 1

        # Seed 支持（可复现性）
        if re.search(r"seed|随机种子|可复现", text, re.IGNORECASE):
            if not extraction.advanced_features:
                extraction.advanced_features = []
            extraction.advanced_features.append("seed_support")
            confidence_points += 0.5
        total_checks += 1

        # 负向提示词支持
        if re.search(r"负向.*提示|negative.*prompt|排除", text, re.IGNORECASE):
            if not extraction.advanced_features:
                extraction.advanced_features = []
            extraction.advanced_features.append("negative_prompt")
            confidence_points += 0.5
        total_checks += 1

        # 多图输入支持
        if re.search(r"多图.*输入|multi.*image|参考.*图.*多", text, re.IGNORECASE):
            extraction.max_reference_images = 2  # 默认多图
            confidence_points += 1
        total_checks += 1

        # 图像编辑支持
        if re.search(r"图像.*编辑|image.*edit|编辑.*功能", text, re.IGNORECASE):
            if not extraction.advanced_features:
                extraction.advanced_features = []
            extraction.advanced_features.append("image_edit")
            confidence_points += 1
        total_checks += 1

        # 权重控制
        if _WEIGHT_CONTROL_RE.search(text):
            extraction.weight_control = True
            confidence_points += 1
        total_checks += 1

        extraction.extraction_confidence = confidence_points / max(total_checks, 1)
        return extraction
    
    def _extract_audio_specs(
        self,
        text: str,
        seed: CatalogSeed,
        url: str,
    ) -> DetailedSpecExtraction:
        """音频模型专用提取逻辑。
        
        核心字段：sample_rate, audio_format, duration_range
        语音合成：voice_clone, language_support, emotion_control
        音乐生成：music_style, instrument_control, vocal_removal
        """
        extraction = DetailedSpecExtraction()
        extraction.extraction_source = url
        confidence_points = 0
        total_checks = 0

        # 采样率
        sample_rate_match = re.search(r"(\d+)\s*kHz", text, re.IGNORECASE)
        if sample_rate_match:
            extraction.output_format = f"{sample_rate_match.group(1)}kHz"
            confidence_points += 1
        total_checks += 1

        # 音频格式
        audio_formats = re.findall(r"\.(mp3|wav|flac|aac|ogg)", text, re.IGNORECASE)
        if audio_formats:
            extraction.output_format = (extraction.output_format + ", " if extraction.output_format else "") + ", ".join(set(audio_formats[:3]))
            confidence_points += 0.5
        total_checks += 1

        # 时长范围（音频特有）
        duration_match = _DURATION_RANGE_RE.search(text)
        if duration_match:
            extraction.duration_range = {
                "min_seconds": int(duration_match.group(1)),
                "max_seconds": int(duration_match.group(2)),
                "unit": "seconds",
                "step": 1,
            }
            confidence_points += 1
        total_checks += 1

        # 输入模态
        input_modalities = []
        if re.search(r"文本|text", text, re.IGNORECASE):
            input_modalities.append("text")
        if re.search(r"音频|audio", text, re.IGNORECASE):
            input_modalities.append("audio")
        if re.search(r"视频|video", text, re.IGNORECASE):
            input_modalities.append("video")
        if input_modalities:
            extraction.input_modalities = input_modalities
            confidence_points += 1
        total_checks += 1

        # 高级功能：音频特有
        advanced_features = []
        
        # 声音克隆
        if re.search(r"声音.*克隆|voice.*clone|音色.*复制", text, re.IGNORECASE):
            advanced_features.append("voice_clone")
            confidence_points += 1
        
        # 语言支持
        if re.search(r"多语言|multi.*language|.*种语言", text, re.IGNORECASE):
            advanced_features.append("multi_language")
            confidence_points += 1
        
        # 情感控制
        if re.search(r"情感.*控制|emotion.*control|情绪.*表达", text, re.IGNORECASE):
            advanced_features.append("emotion_control")
            confidence_points += 1
        
        # 音乐风格
        if re.search(r"音乐.*风格|music.*style|流派", text, re.IGNORECASE):
            advanced_features.append("music_style")
            confidence_points += 1
        
        # 乐器控制
        if re.search(r"乐器|instrument|伴奏", text, re.IGNORECASE):
            advanced_features.append("instrument_control")
            confidence_points += 1
        
        # 人声分离
        if re.search(r"人声.*分离|vocal.*removal|伴奏.*提取", text, re.IGNORECASE):
            advanced_features.append("vocal_removal")
            confidence_points += 1
        
        if advanced_features:
            extraction.advanced_features = advanced_features
        total_checks += 6

        extraction.extraction_confidence = confidence_points / max(total_checks, 1)
        return extraction
    
    def _extract_llm_specs(
        self,
        text: str,
        seed: CatalogSeed,
        url: str,
    ) -> DetailedSpecExtraction:
        """LLM 模型专用提取逻辑。
        
        核心字段：context_window, max_output_tokens, temperature_range
        功能特性：function_calling, tool_use, multi_turn, streaming
        推理能力：reasoning, code_generation, math
        """
        extraction = DetailedSpecExtraction()
        extraction.extraction_source = url
        confidence_points = 0
        total_checks = 0

        # 上下文窗口
        context_match = re.search(r"(\d+[KkMm]?)\s*(tokens?|上下文|context)", text, re.IGNORECASE)
        if context_match:
            extraction.output_format = context_match.group(1)
            confidence_points += 1
        total_checks += 1

        # 输出长度
        output_match = re.search(r"最大.*输出.*?(\d+)", text, re.IGNORECASE)
        if output_match:
            extraction.duration_range = {"max_tokens": int(output_match.group(1))}
            confidence_points += 0.5
        total_checks += 1

        # 输入模态
        input_modalities = ["text"]
        if re.search(r"视觉|vision|image.*understanding|多模态", text, re.IGNORECASE):
            input_modalities.append("image")
        if re.search(r"音频|audio|语音", text, re.IGNORECASE):
            input_modalities.append("audio")
        if re.search(r"视频|video", text, re.IGNORECASE):
            input_modalities.append("video")
        extraction.input_modalities = input_modalities
        confidence_points += 1
        total_checks += 1

        # 高级功能：LLM 特有
        advanced_features = []
        
        # 函数调用
        if re.search(r"function.*call|工具.*调用|function.*calling", text, re.IGNORECASE):
            advanced_features.append("function_calling")
            confidence_points += 1
        
        # 流式输出
        if re.search(r"流式|streaming|stream", text, re.IGNORECASE):
            advanced_features.append("streaming")
            confidence_points += 0.5
        
        # 多轮对话
        if re.search(r"多轮|multi.*turn|对话|chat", text, re.IGNORECASE):
            advanced_features.append("multi_turn")
            confidence_points += 0.5
        
        # 推理能力
        if re.search(r"推理|reasoning|chain.*of.*thought", text, re.IGNORECASE):
            advanced_features.append("reasoning")
            confidence_points += 1
        
        # 代码生成
        if re.search(r"代码|code.*generation|编程", text, re.IGNORECASE):
            advanced_features.append("code_generation")
            confidence_points += 0.5
        
        # 数学能力
        if re.search(r"数学|math|计算", text, re.IGNORECASE):
            advanced_features.append("math")
            confidence_points += 0.5
        
        # 联网搜索
        if re.search(r"联网|web.*search|搜索", text, re.IGNORECASE):
            advanced_features.append("web_search")
            confidence_points += 1
        
        if advanced_features:
            extraction.advanced_features = advanced_features
        total_checks += 7

        extraction.extraction_confidence = confidence_points / max(total_checks, 1)
        return extraction
    
    def _extract_generic_specs(
        self,
        text: str,
        seed: CatalogSeed,
        url: str,
    ) -> DetailedSpecExtraction:
        """通用提取逻辑（用于其他模型类型）。"""
        extraction = DetailedSpecExtraction()
        extraction.extraction_source = url
        confidence_points = 0
        total_checks = 0

        # 基础字段提取
        duration_match = _DURATION_RANGE_RE.search(text)
        if duration_match:
            extraction.duration_range = {
                "min_seconds": int(duration_match.group(1)),
                "max_seconds": int(duration_match.group(2)),
                "unit": "seconds",
                "step": 1,
            }
            confidence_points += 1
        total_checks += 1

        resolutions = list(set(_RESOLUTION_RE.findall(text)))
        if resolutions:
            extraction.resolution_options = sorted(resolutions, key=lambda x: int(x[:-1]) if x[:-1].isdigit() else 100)
            confidence_points += 1
        total_checks += 1

        formats = list(set(_FORMAT_RE.findall(text)))
        if formats:
            extraction.output_format = ", ".join(formats[:3])
            confidence_points += 0.5
        total_checks += 1

        extraction.extraction_confidence = confidence_points / max(total_checks, 1)
        return extraction

    def _extract_prompt_examples_from_html(self, html: str) -> list[dict[str, str]]:
        """从 HTML 中提取提示词示例。"""
        examples: list[dict[str, str]] = []
        text = self._extract_search_text(html)

        example_patterns = [
            r"示例\s*[:：]\s*[「「\"']([^」」\"']+)[」」\"']",
            r"prompt\s*[:：]\s*[「「\"']([^」」\"']+)[」」\"']",
            r"提示词\s*[:：]\s*[「「\"']([^」」\"']+)[」」\"']",
        ]

        for pattern in example_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches[:3]:
                if len(match) > 20 and len(match) < 500:
                    examples.append({
                        "title": "提取的示例",
                        "content": match.strip(),
                    })

        return examples[:5]

    def _merge_extracted_specs(
        self,
        extractions: list[DetailedSpecExtraction],
        existing_specs: dict[str, Any],
        category: str = "video",
    ) -> dict[str, Any]:
        """合并从多个来源提取的规格信息（按模型类型差异化合并）。
        
        Args:
            extractions: 提取结果列表
            existing_specs: 已有规格
            category: 模型类别（video/image/audio/llm）
        """
        if not extractions:
            return existing_specs

        merged = deepcopy(existing_specs) if existing_specs else {}
        best_extraction = max(extractions, key=lambda e: e.extraction_confidence)
        
        # 根据模型类型合并到对应的 section
        if category == "video":
            return self._merge_video_specs(merged, best_extraction)
        elif category == "image":
            return self._merge_image_specs(merged, best_extraction)
        elif category == "audio":
            return self._merge_audio_specs(merged, best_extraction)
        elif category == "llm":
            return self._merge_llm_specs(merged, best_extraction)
        else:
            return self._merge_generic_specs(merged, best_extraction)
    
    def _merge_video_specs(
        self,
        merged: dict[str, Any],
        extraction: DetailedSpecExtraction,
    ) -> dict[str, Any]:
        """合并视频模型规格。"""
        video_specs = merged.get("video_generation", {})

        if extraction.duration_range and "basic_params" not in video_specs:
            video_specs.setdefault("basic_params", {})["duration"] = extraction.duration_range

        if extraction.resolution_options and "basic_params" not in video_specs:
            video_specs.setdefault("basic_params", {})["resolution"] = {
                "options": extraction.resolution_options,
            }

        if extraction.frame_rate and "output_format" not in video_specs:
            video_specs["output_format"] = {
                "frame_rate": extraction.frame_rate,
            }

        if extraction.input_modalities:
            video_specs["input_modalities"] = [
                {"id": m, "name": {"text": "文本", "image": "图像", "audio": "音频", "video": "视频"}.get(m, m), "required": m == "text"}
                for m in extraction.input_modalities
            ]

        if extraction.advanced_features:
            feature_labels = {
                "multi_shot": "多镜头叙事",
                "audio_sync": "声画同步",
                "prompt_rewrite": "智能改写",
                "camera_control": "运镜控制",
                "motion_control": "动作控制",
            }
            video_specs["advanced_features"] = [
                {"id": f, "name": feature_labels.get(f, f), "description": ""}
                for f in extraction.advanced_features
            ]
        
        # 首帧/尾帧/参考支持
        if extraction.first_frame_support or extraction.last_frame_support:
            video_specs.setdefault("frame_control", {})
            if extraction.first_frame_support:
                video_specs["frame_control"]["first_frame"] = True
            if extraction.last_frame_support:
                video_specs["frame_control"]["last_frame"] = True
        
        if extraction.max_reference_images:
            video_specs.setdefault("reference_images", {})["max_count"] = extraction.max_reference_images

        if video_specs:
            merged["video_generation"] = video_specs

        return merged
    
    def _merge_image_specs(
        self,
        merged: dict[str, Any],
        extraction: DetailedSpecExtraction,
    ) -> dict[str, Any]:
        """合并图像模型规格。"""
        image_specs = merged.get("image_generation", {})

        if extraction.resolution_options and "basic_params" not in image_specs:
            image_specs.setdefault("basic_params", {})["resolution"] = {
                "options": extraction.resolution_options,
            }

        if extraction.output_format and "output_format" not in image_specs:
            image_specs["output_format"] = {"format": extraction.output_format}

        if extraction.input_modalities:
            image_specs["input_modalities"] = [
                {"id": m, "name": {"text": "文本", "image": "图像"}.get(m, m), "required": m == "text"}
                for m in extraction.input_modalities
            ]

        if extraction.advanced_features:
            feature_labels = {
                "style_support": "风格支持",
                "seed_support": "随机种子",
                "negative_prompt": "负向提示词",
                "image_edit": "图像编辑",
                "style_transfer": "风格迁移",
            }
            image_specs.setdefault("advanced_features", []).extend([
                {"id": f, "name": feature_labels.get(f, f), "description": ""}
                for f in extraction.advanced_features
            ])
        
        if extraction.max_reference_images:
            image_specs.setdefault("reference_images", {})["max_count"] = extraction.max_reference_images

        if extraction.weight_control:
            image_specs.setdefault("weight_control", {"enabled": True})

        if image_specs:
            merged["image_generation"] = image_specs

        return merged
    
    def _merge_audio_specs(
        self,
        merged: dict[str, Any],
        extraction: DetailedSpecExtraction,
    ) -> dict[str, Any]:
        """合并音频模型规格。"""
        audio_specs = merged.get("audio_generation", {})

        if extraction.output_format and "output_format" not in audio_specs:
            audio_specs["output_format"] = {"format": extraction.output_format}

        if extraction.duration_range and "basic_params" not in audio_specs:
            audio_specs.setdefault("basic_params", {})["duration"] = extraction.duration_range

        if extraction.input_modalities:
            audio_specs["input_modalities"] = [
                {"id": m, "name": {"text": "文本", "audio": "音频", "video": "视频"}.get(m, m), "required": m == "text"}
                for m in extraction.input_modalities
            ]

        if extraction.advanced_features:
            feature_labels = {
                "voice_clone": "声音克隆",
                "multi_language": "多语言支持",
                "emotion_control": "情感控制",
                "music_style": "音乐风格",
                "instrument_control": "乐器控制",
                "vocal_removal": "人声分离",
            }
            audio_specs["advanced_features"] = [
                {"id": f, "name": feature_labels.get(f, f), "description": ""}
                for f in extraction.advanced_features
            ]

        if audio_specs:
            merged["audio_generation"] = audio_specs

        return merged
    
    def _merge_llm_specs(
        self,
        merged: dict[str, Any],
        extraction: DetailedSpecExtraction,
    ) -> dict[str, Any]:
        """合并 LLM 模型规格。"""
        llm_specs = merged.get("llm_config", {})

        if extraction.output_format:
            llm_specs.setdefault("basic_params", {})["context_window"] = extraction.output_format

        if extraction.duration_range and "max_tokens" in extraction.duration_range:
            llm_specs.setdefault("basic_params", {})["max_output_tokens"] = extraction.duration_range["max_tokens"]

        if extraction.input_modalities:
            llm_specs["input_modalities"] = [
                {"id": m, "name": {"text": "文本", "image": "图像", "audio": "音频", "video": "视频"}.get(m, m), "required": m == "text"}
                for m in extraction.input_modalities
            ]

        if extraction.advanced_features:
            feature_labels = {
                "function_calling": "函数调用",
                "streaming": "流式输出",
                "multi_turn": "多轮对话",
                "reasoning": "推理能力",
                "code_generation": "代码生成",
                "math": "数学能力",
                "web_search": "联网搜索",
            }
            llm_specs["advanced_features"] = [
                {"id": f, "name": feature_labels.get(f, f), "description": ""}
                for f in extraction.advanced_features
            ]

        if llm_specs:
            merged["llm_config"] = llm_specs

        return merged
    
    def _merge_generic_specs(
        self,
        merged: dict[str, Any],
        extraction: DetailedSpecExtraction,
    ) -> dict[str, Any]:
        """合并通用模型规格。"""
        if extraction.duration_range:
            merged.setdefault("basic_params", {})["duration"] = extraction.duration_range
        
        if extraction.resolution_options:
            merged.setdefault("basic_params", {})["resolution"] = {
                "options": extraction.resolution_options,
            }
        
        if extraction.output_format:
            merged["output_format"] = extraction.output_format

        return merged
