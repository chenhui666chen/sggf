from __future__ import annotations

import base64
import json
import os
import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adapters.adapter_helpers import analyze_video, chat_messages, get_model_info
from agents.vlm_utils import clamp_text_list
from pipeline.autoqc_pkg._utils import _file_to_data_url, _normalize_state_text, _try_parse_json_object
from pipeline.media_presets import (
    DREAMWEAVER_I2V_ENGINE,
    is_dreamweaver_auto_engine,
    is_dreamweaver_t2v_engine,
    normalize_dreamweaver_video_engine,
)


DEFAULT_SIMILARITY_THRESHOLD = 0.9
DEFAULT_MAX_SUBJECT_POS_DELTA = 0.1
DEFAULT_WEIGHTS = {"identity": 0.4, "structure": 0.4, "style": 0.2}
DEFAULT_SEMANTIC_THRESHOLD = 0.6
DEFAULT_SEMANTIC_VLM_ADAPTER = "qwen3_vl_plus"
DEFAULT_SEMANTIC_FRAMES = "both"  # head|tail|both
DEFAULT_SEMANTIC_SAMPLE_RATE = 1.0
DEFAULT_SEMANTIC_MAX_CHECKS = 0  # 0 表示不设上限（保持历史行为）
DEFAULT_SEMANTIC_STRATEGY = "priority"  # priority|sample|all
DEFAULT_STATE_QC_THRESHOLD = 0.65
DEFAULT_STATE_QC_VLM_ADAPTER = DEFAULT_SEMANTIC_VLM_ADAPTER
DEFAULT_STATE_QC_SAMPLE_RATE = 1.0
DEFAULT_STATE_QC_MAX_CHECKS = 0  # 0 表示不设上限（与 semantic_max_checks 一致语义）
DEFAULT_STATE_QC_STRATEGY = "priority"  # priority|sample|all
DEFAULT_VIDEO_CLIP_QC_THRESHOLD = 6.5
DEFAULT_VIDEO_CLIP_QC_VLM_ADAPTER = DEFAULT_SEMANTIC_VLM_ADAPTER
DEFAULT_VIDEO_CLIP_QC_SAMPLE_RATE = 1.0
DEFAULT_VIDEO_CLIP_QC_MAX_CHECKS = 0  # 0 表示不设上限，可通过 qc_config/ENV 收紧
DEFAULT_VIDEO_CLIP_QC_CRITERIA = ["clarity", "smoothness", "consistency", "lighting", "color"]

def _semantic_match(
    *,
    vlm_adapter: Any,
    image_path: str,
    expected: str,
    max_tokens: int = 400,
) -> Optional[Dict[str, Any]]:
    if not vlm_adapter:
        return None
    if not image_path or not expected:
        return None
    p = Path(image_path)
    if not p.exists():
        return None

    system_prompt = (
        "你是视频/分镜质检员。\n"
        "任务：判断给定图片是否符合【期望描述】（语义一致性/主要元素/动作/场景）。\n"
        "只输出 JSON（不要 Markdown），字段：match_score(0~1, float)、issues(list[string])。"
    )
    system_prompt += "\nOutput JSON only. Keep issues <= 6 items; each item <= 120 chars."

    user_content = [
        {"type": "image_url", "image_url": {"url": _file_to_data_url(p)}},
        {"type": "text", "text": f"【期望描述】\n{expected}\n\n仅输出 JSON：{{\"match_score\":0.8,\"issues\":[\"...\"]}}"},
    ]
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        if isinstance(vlm_adapter, str):
            res = chat_messages(
                messages=messages,
                temperature=0.2,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                model_id=vlm_adapter,
            )
            if not getattr(res, "success", False):
                res = chat_messages(
                    messages=messages,
                    temperature=0.2,
                    max_tokens=max_tokens,
                    model_id=vlm_adapter,
                )
        else:
            if not hasattr(vlm_adapter, "chat"):
                return None
            res = vlm_adapter.chat(messages=messages, temperature=0.2, max_tokens=max_tokens, response_format={"type": "json_object"})
            if not getattr(res, "success", False):
                res = vlm_adapter.chat(messages=messages, temperature=0.2, max_tokens=max_tokens)
        if not getattr(res, "success", False):
            return None

        content = ""
        if isinstance(res.data, dict) and isinstance(res.data.get("content"), str):
            content = res.data["content"]
        obj = _try_parse_json_object(content)
        if not isinstance(obj, dict):
            return None

        score = obj.get("match_score")
        issues = obj.get("issues")
        if isinstance(score, (int, float)):
            score_f = float(score)
        else:
            return None
        issues_list = clamp_text_list(issues, max_items=6, max_chars=120)
        return {"match_score": score_f, "issues": issues_list}
    except Exception:  # noqa: BLE001
        return None


def _state_continuity_match(
    *,
    vlm_adapter: Any,
    prev_tail_path: str,
    next_head_path: str,
    prev_state_after: str,
    next_state_before: str,
    max_tokens: int = 500,
) -> Optional[Dict[str, Any]]:
    if not vlm_adapter:
        return None
    if not prev_tail_path or not next_head_path:
        return None

    prev_p = Path(prev_tail_path)
    next_p = Path(next_head_path)
    if not prev_p.exists() or not next_p.exists():
        return None

    state_after = _normalize_state_text(prev_state_after)
    state_before = _normalize_state_text(next_state_before)
    if not state_after and not state_before:
        return None

    system_prompt = (
        "你是视频/分镜连续性质检员。\n"
        "任务：基于【上一镜头尾帧】与【下一镜头首帧】，核验两帧之间是否在关键状态上连续。\n"
        "请重点检查：门开/关、人物站位/朝向、道具持有、关键物体是否突然消失/出现、场景是否突变。\n"
        "同时参考提供的【状态约束】：若画面与状态约束矛盾，应判为不连续。\n"
        "只输出 JSON（不要 Markdown），字段：match_score(0~1,float)、issues(list[string])、suggestions(list[string],可选)。"
    )
    system_prompt += "\nOutput JSON only. Keep issues/suggestions <= 6 items; each item <= 120 chars."

    constraint_text = (
        "【状态约束】\n"
        f"- 上一镜头结束(state_after)：{state_after or '(未提供)'}\n"
        f"- 下一镜头开始(state_before)：{state_before or '(未提供)'}\n\n"
        "仅输出 JSON 示例："
        "{\"match_score\":0.82,\"issues\":[\"...\"],\"suggestions\":[\"... (可选)\"]}"
    )

    user_content = [
        {"type": "text", "text": "上一镜头尾帧"},
        {"type": "image_url", "image_url": {"url": _file_to_data_url(prev_p)}},
        {"type": "text", "text": "下一镜头首帧"},
        {"type": "image_url", "image_url": {"url": _file_to_data_url(next_p)}},
        {"type": "text", "text": constraint_text},
    ]
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        if isinstance(vlm_adapter, str):
            res = chat_messages(
                messages=messages,
                temperature=0.2,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                model_id=vlm_adapter,
            )
            if not getattr(res, "success", False):
                res = chat_messages(
                    messages=messages,
                    temperature=0.2,
                    max_tokens=max_tokens,
                    model_id=vlm_adapter,
                )
        else:
            if not hasattr(vlm_adapter, "chat"):
                return None
            res = vlm_adapter.chat(messages=messages, temperature=0.2, max_tokens=max_tokens, response_format={"type": "json_object"})
            if not getattr(res, "success", False):
                res = vlm_adapter.chat(messages=messages, temperature=0.2, max_tokens=max_tokens)
        if not getattr(res, "success", False):
            return None

        content = ""
        if isinstance(res.data, dict) and isinstance(res.data.get("content"), str):
            content = res.data["content"]
        obj = _try_parse_json_object(content)
        if not isinstance(obj, dict):
            return None

        score = obj.get("match_score")
        if not isinstance(score, (int, float)):
            return None
        score_f = float(score)
        if score_f < 0.0:
            score_f = 0.0
        if score_f > 1.0:
            score_f = 1.0

        issues_raw = obj.get("issues") if isinstance(obj.get("issues"), list) else []
        issues = clamp_text_list(issues_raw, max_items=6, max_chars=120)

        suggestions_raw = obj.get("suggestions") if isinstance(obj.get("suggestions"), list) else []
        suggestions = clamp_text_list(suggestions_raw, max_items=6, max_chars=120)

        return {"match_score": score_f, "issues": issues, "suggestions": suggestions}
    except Exception:  # noqa: BLE001
        return None


