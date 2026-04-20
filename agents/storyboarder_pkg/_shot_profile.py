from __future__ import annotations

import difflib
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from agents.camera_states import build_camera_states
from agents.camera_tree import build_camera_tree, build_camera_tree_llm
from agents.llm_client import chat_completions, env_flag, extract_json_object, pick_model, llm_stream_context
from pipeline.media_presets import (
    DREAMWEAVER_AUTO_ENGINE,
    DREAMWEAVER_I2V_ENGINE,
    DREAMWEAVER_T2V_ENGINE,
    ensure_media_payload,
    is_dreamweaver_auto_engine,
    is_dreamweaver_i2v_engine,
    is_dreamweaver_t2v_engine,
    normalize_dreamweaver_video_duration_s,
    normalize_dreamweaver_video_engine,
    normalize_frame_ratio,
)
from pipeline.style_presets import ensure_style_payload

def _shot_profile(shot_index: int, narrative_context: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """
    轻量镜头模板（避免引入 LLM 依赖），用于补齐 motion/camera 等可用字段。

    说明：
    - 目标是为后续 I2V 提供稳定的"运镜/动作"描述；
    - 同时让 head/tail 帧 prompt 有轻微差异，便于连续性与 Anchor。
    - 扩展多种镜头类型，提供更丰富的视觉表达。
    - 支持多镜头叙事，根据叙事上下文选择合适的镜头类型。
    
    Args:
        shot_index: 镜头索引
        narrative_context: 叙事上下文，包含场景类型、情感强度等信息
    """
    profiles = [
        {
            "camera": "全景",
            "lens": "24mm",
            "angle": "略俯视",
            "composition": "建立空间关系，主体偏画面中下",
            "movement": "镜头缓慢推进",
            "subject_x": "0.50",
            "subject_y": "0.65",
            "narrative_role": "establishing",
            "emotion_level": "neutral",
        },
        {
            "camera": "中景",
            "lens": "50mm",
            "angle": "平视",
            "composition": "三分法构图，主体居中偏右",
            "movement": "镜头轻微平移",
            "subject_x": "0.55",
            "subject_y": "0.60",
            "narrative_role": "action",
            "emotion_level": "neutral",
        },
        {
            "camera": "特写",
            "lens": "85mm",
            "angle": "微仰视",
            "composition": "面部/手部特写，占画面主体区域",
            "movement": "镜头微微推近",
            "subject_x": "0.50",
            "subject_y": "0.45",
            "narrative_role": "emotional",
            "emotion_level": "high",
        },
        {
            "camera": "远景",
            "lens": "16mm",
            "angle": "俯视",
            "composition": "展现环境全貌，主体较小",
            "movement": "镜头稳定",
            "subject_x": "0.50",
            "subject_y": "0.70",
            "narrative_role": "establishing",
            "emotion_level": "low",
        },
        {
            "camera": "近景",
            "lens": "35mm",
            "angle": "平视",
            "composition": "上半身构图，背景虚化",
            "movement": "镜头缓慢右移",
            "subject_x": "0.60",
            "subject_y": "0.55",
            "narrative_role": "action",
            "emotion_level": "medium",
        },
        {
            "camera": "大特写",
            "lens": "100mm",
            "angle": "平视",
            "composition": "眼部/细节特写，极浅景深",
            "movement": "镜头轻微推近",
            "subject_x": "0.50",
            "subject_y": "0.50",
            "narrative_role": "emotional",
            "emotion_level": "very_high",
        },
        {
            "camera": "过肩镜头",
            "lens": "50mm",
            "angle": "平视",
            "composition": "主体在前景人物肩后",
            "movement": "镜头轻微跟随",
            "subject_x": "0.45",
            "subject_y": "0.55",
            "narrative_role": "dialogue",
            "emotion_level": "medium",
        },
        {
            "camera": "低角度",
            "lens": "35mm",
            "angle": "仰视",
            "composition": "主体显得高大，背景天空",
            "movement": "镜头缓慢上升",
            "subject_x": "0.50",
            "subject_y": "0.40",
            "narrative_role": "power",
            "emotion_level": "high",
        },
        {
            "camera": "高角度",
            "lens": "35mm",
            "angle": "俯视",
            "composition": "主体显得渺小，展现环境",
            "movement": "镜头缓慢下降",
            "subject_x": "0.50",
            "subject_y": "0.60",
            "narrative_role": "vulnerable",
            "emotion_level": "low",
        },
        {
            "camera": "跟拍",
            "lens": "50mm",
            "angle": "平视",
            "composition": "主体居中，背景流动",
            "movement": "镜头跟随主体移动",
            "subject_x": "0.50",
            "subject_y": "0.50",
            "narrative_role": "action",
            "emotion_level": "medium",
        },
        {
            "camera": "推镜头",
            "lens": "35mm-85mm",
            "angle": "平视",
            "composition": "从广角逐渐聚焦主体",
            "movement": "镜头持续推进",
            "subject_x": "0.50",
            "subject_y": "0.50",
            "narrative_role": "intensify",
            "emotion_level": "high",
        },
        {
            "camera": "拉镜头",
            "lens": "85mm-35mm",
            "angle": "平视",
            "composition": "从主体逐渐展现环境",
            "movement": "镜头持续拉远",
            "subject_x": "0.50",
            "subject_y": "0.50",
            "narrative_role": "reveal",
            "emotion_level": "medium",
        },
    ]
    
    selected_profile = profiles[(shot_index - 1) % len(profiles)]
    
    if narrative_context and isinstance(narrative_context, dict):
        scene_type = narrative_context.get("scene_type", "normal")
        emotion_intensity = narrative_context.get("emotion_intensity", "medium")
        
        if scene_type == "dialogue" and emotion_intensity == "high":
            dialogue_profiles = [p for p in profiles if p.get("narrative_role") == "dialogue"]
            if dialogue_profiles:
                selected_profile = dialogue_profiles[shot_index % len(dialogue_profiles)]
        elif scene_type == "action" and emotion_intensity == "high":
            action_profiles = [p for p in profiles if p.get("narrative_role") == "action"]
            if action_profiles:
                selected_profile = action_profiles[shot_index % len(action_profiles)]
        elif scene_type == "emotional":
            emotional_profiles = [p for p in profiles if p.get("narrative_role") == "emotional"]
            if emotional_profiles:
                selected_profile = emotional_profiles[shot_index % len(emotional_profiles)]
    
    return selected_profile


def _detect_dynamic(text: str) -> bool:
    t = str(text or "")
    keywords = (
        "跑",
        "冲",
        "追",
        "逃",
        "闪",
        "跳",
        "扑",
        "打",
        "砍",
        "刺",
        "踢",
        "挥",
        "爆",
        "炸",
        "坠",
        "飞",
        "翻",
        "撞",
        "突袭",
        "追逐",
        "掠过",
        "狂奔",
        "急速",
    )
    return any(k in t for k in keywords)


def _normalize_variation_type(value: Any) -> Optional[str]:
    s = str(value or "").strip().lower()
    if s in {"small", "medium", "large"}:
        return s
    return None


