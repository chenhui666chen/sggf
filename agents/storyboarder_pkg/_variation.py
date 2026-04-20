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

def _simplify_variation_text(text: str) -> str:
    s = str(text or "").strip().lower()
    if not s:
        return ""
    s = re.sub(r"\d+:\d+", "", s)
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[，。！？!?.;；:：、（）()\\[\\]{}<>《》“”\"'`~…—-]+", "", s)
    return s


def _infer_variation_type(
    *,
    ff_desc: str,
    lf_desc: str,
    ff_vis_char_ids: List[str],
    lf_vis_char_ids: List[str],
    state_before: str,
    state_after: str,
) -> Tuple[str, str]:
    ff_chars = {str(s).strip() for s in (ff_vis_char_ids or []) if str(s).strip()}
    lf_chars = {str(s).strip() for s in (lf_vis_char_ids or []) if str(s).strip()}
    char_delta = sorted((ff_chars ^ lf_chars))

    state_changed = bool(state_before and state_after and state_before.strip() != state_after.strip())

    a = _simplify_variation_text(ff_desc)
    b = _simplify_variation_text(lf_desc)
    similarity: Optional[float] = None
    if a and b:
        similarity = difflib.SequenceMatcher(None, a, b).ratio()

    if len(char_delta) >= 2:
        return "large", f"启发式：首尾可见角色变化较大（{', '.join(char_delta[:4])}）"
    if len(char_delta) == 1:
        if similarity is not None and similarity < 0.60:
            return "large", f"启发式：角色变化（{char_delta[0]}）且首尾差异较大（相似度{similarity:.2f}）"
        return "medium", f"启发式：首尾可见角色有变化（{char_delta[0]}）"

    if state_changed:
        if similarity is not None and similarity < 0.55:
            return "large", f"启发式：状态变化且首尾差异较大（相似度{similarity:.2f}）"
        return "medium", "启发式：镜头首尾状态有变化"

    if similarity is None:
        return "medium", "启发式：缺少可比对信息，按中等变化处理"
    if similarity >= 0.86:
        return "small", f"启发式：首尾提示词相似度高（{similarity:.2f}）"
    if similarity >= 0.68:
        return "medium", f"启发式：首尾提示词相似度中等（{similarity:.2f}）"
    return "large", f"启发式：首尾提示词相似度低（{similarity:.2f}）"


def _analyze_narrative_context(text: str, storyboard: Optional[List[Dict[str, Any]]] = None, shot_index: int = 0) -> Dict[str, Any]:
    """
    分析叙事上下文，用于多镜头叙事优化
    
    Args:
        text: 文本内容
        storyboard: 已生成的分镜列表（用于上下文连贯性）
        shot_index: 当前镜头索引
    
    Returns:
        叙事上下文字典，包含场景类型、情感强度等信息
    """
    t = str(text or "").lower()
    
    dialogue_keywords = ["说", "问", "答", "道", "道：", "说：", "问：", "答：", "“", "”", "「", "」"]
    action_keywords = ["跑", "冲", "追", "逃", "打", "杀", "战", "斗", "攻", "击", "突", "袭", "闪", "跳", "扑"]
    emotional_keywords = ["哭", "笑", "怒", "悲", "喜", "惊", "恐", "爱", "恨", "悔", "痛", "伤", "泪", "叹", "忧"]
    intense_keywords = ["激烈", "紧张", "激烈", "激烈", "激烈", "激烈", "激烈", "激烈", "激烈", "激烈", "激烈"]
    
    scene_type = "normal"
    emotion_intensity = "medium"
    
    dialogue_count = sum(1 for kw in dialogue_keywords if kw in t)
    action_count = sum(1 for kw in action_keywords if kw in t)
    emotional_count = sum(1 for kw in emotional_keywords if kw in t)
    
    if dialogue_count > 2:
        scene_type = "dialogue"
    elif action_count > 2:
        scene_type = "action"
    elif emotional_count > 2:
        scene_type = "emotional"
    
    if any(kw in t for kw in ["激烈", "紧张", "愤怒", "绝望", "狂喜", "极度"]):
        emotion_intensity = "high"
    elif any(kw in t for kw in ["平静", "温和", "轻松", "安详"]):
        emotion_intensity = "low"
    
    if storyboard and isinstance(storyboard, list) and shot_index > 0:
        prev_shot = storyboard[shot_index - 1]
        if isinstance(prev_shot, dict):
            prev_emotion = prev_shot.get("emotion", "")
            if prev_emotion in ["tense", "angry", "fearful"]:
                emotion_intensity = "high"
            elif prev_emotion in ["calm", "peaceful", "relaxed"]:
                emotion_intensity = "low"
    
    return {
        "scene_type": scene_type,
        "emotion_intensity": emotion_intensity,
        "dialogue_count": dialogue_count,
        "action_count": action_count,
        "emotional_count": emotional_count,
    }


