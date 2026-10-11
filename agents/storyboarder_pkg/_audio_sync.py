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

def _extract_dialogue_from_text(text: str) -> List[Dict[str, Any]]:
    """
    从文本中提取对话
    
    Args:
        text: 文本内容
    
    Returns:
        对话列表，每个包含 text, speaker, start_time, end_time
    """
    dialogues: List[Dict[str, Any]] = []
    
    lines = str(text or "").split("\n")
    current_speaker = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        speaker_match = re.match(r"^([A-Za-z\u4e00-\u9fa5]+)[：:]\s*(.+)$", line)
        if speaker_match:
            current_speaker = speaker_match.group(1)
            dialogue_text = speaker_match.group(2).strip()
            
            if dialogue_text:
                dialogues.append({
                    "text": dialogue_text,
                    "speaker": current_speaker,
                    "start_time": None,
                    "end_time": None
                })
        elif current_speaker and line.startswith("-"):
            dialogue_text = line[1:].strip()
            if dialogue_text:
                dialogues.append({
                    "text": dialogue_text,
                    "speaker": current_speaker,
                    "start_time": None,
                    "end_time": None
                })
    
    return dialogues


def _estimate_dialogue_duration(dialogue_text: str, speed: float = 4.0) -> float:
    """
    估算对话时长（秒）
    
    Args:
        dialogue_text: 对话文本
        speed: 语速（字/秒）
    
    Returns:
        估算时长（秒）
    """
    text = re.sub(r"[^\w\u4e00-\u9fa5]", "", dialogue_text)
    char_count = len(text)
    return max(1.0, float(char_count) / speed)


def _build_audio_sync_info(
    text: str,
    shot_id: str,
    shot_index: int,
    duration_s: float
) -> Dict[str, Any]:
    """
    构建音频同步信息
    
    Args:
        text: 文本内容
        shot_id: 镜头ID
        shot_index: 镜头索引
        duration_s: 镜头时长
    
    Returns:
        音频同步信息字典
    """
    dialogues = _extract_dialogue_from_text(text)
    
    if not dialogues:
        return {
            "has_audio": False,
            "audio_markers": [],
            "audio_desc": ""
        }
    
    audio_markers: List[Dict[str, Any]] = []
    current_time = 0.0
    
    for idx, dialogue in enumerate(dialogues):
        dialogue_text = dialogue.get("text", "")
        speaker = dialogue.get("speaker", "")
        
        if not dialogue_text:
            continue
        
        estimated_duration = _estimate_dialogue_duration(dialogue_text)
        
        marker = {
            "marker_type": "dialogue",
            "time_s": current_time,
            "description": f"{speaker}说：{dialogue_text}",
            "character_name": speaker,
            "dialogue_text": dialogue_text,
            "duration_s": estimated_duration
        }
        
        audio_markers.append(marker)
        current_time += estimated_duration
    
    audio_desc = f"包含{len(dialogues)}句对话"
    if dialogues:
        speakers = set(d.get("speaker", "") for d in dialogues)
        audio_desc += f"，角色：{', '.join(speakers)}"
    
    return {
        "has_audio": True,
        "audio_markers": audio_markers,
        "audio_desc": audio_desc
    }


