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

def _build_frame_prompt(
    *,
    visual_desc: str,
    profile: Dict[str, str],
    stage: str,
    style_preset: str,
    style_prompt: str,
    ratio: str,
    entity_matches: Dict[str, List[Tuple[str, str]]],
    dynamic: bool,
    narrative_context: Optional[Dict[str, Any]] = None,
) -> str:
    """
    stage: head|tail
    
    优化说明：
    - 增加场景细节描述（光照、氛围、背景层次）
    - 增强动作描述（动作分解、速度感、动态模糊）
    - 优化构图指导（视觉引导、焦点控制）
    - 强化风格一致性（色彩倾向、质感细节）
    - 支持多镜头叙事（根据叙事上下文调整镜头语言）
    
    Args:
        visual_desc: 视觉描述
        profile: 镜头配置
        stage: 阶段（head/tail）
        style_preset: 风格预设
        style_prompt: 风格提示词
        ratio: 宽高比
        entity_matches: 实体匹配结果
        dynamic: 是否动态
        narrative_context: 叙事上下文
    """
    style = (style_prompt or "").strip() or "写实风格，电影质感，光影真实，高清细节，统一风格"
    camera = str(profile.get("camera") or "中景")
    lens = str(profile.get("lens") or "50mm")
    angle = str(profile.get("angle") or "平视")
    composition = str(profile.get("composition") or "三分法构图")
    movement = str(profile.get("movement") or "镜头稳定")
    
    narrative_role = profile.get("narrative_role", "normal")
    emotion_level = profile.get("emotion_level", "medium")

    chars_text = _format_entity_items(entity_matches.get("characters") or [], max_desc_len=36)
    scenes_text = _format_entity_items(entity_matches.get("scenes") or [], max_desc_len=48)
    props_text = _format_entity_items(entity_matches.get("props") or [], max_desc_len=36)

    manga_fx = ""
    if style_preset == "anime" and dynamic:
        manga_fx = "漫画动效：速度线，动感线，轻微运动模糊（无文字）"

    stage_tag = "镜头开始，动作起势，主体清晰，焦点明确" if stage != "tail" else "镜头结束，动作延续，保持风格与构图一致，焦点稳定"

    lighting_desc = _get_lighting_description(style_preset, dynamic, narrative_context)
    atmosphere_desc = _get_atmosphere_description(style_preset, narrative_context)
    texture_desc = _get_texture_description(style_preset)
    
    narrative_guidance = _get_narrative_guidance(narrative_role, emotion_level, narrative_context)

    parts = [
        "单格分镜",
        normalize_frame_ratio(ratio),
        style,
        f"{camera}，{angle}，{lens}",
        composition,
        f"运镜：{movement}",
        f"光照：{lighting_desc}",
        f"氛围：{atmosphere_desc}",
        f"质感：{texture_desc}",
        f"画面要点：{visual_desc}",
        f"角色：{chars_text}" if chars_text else "",
        f"环境：{scenes_text}" if scenes_text else "",
        f"道具：{props_text}" if props_text else "",
        narrative_guidance,
        manga_fx,
        stage_tag,
        "无文字，无水印，无logo，无边框，无拼贴",
    ]
    return "，".join([p for p in parts if p])


def _get_lighting_description(style_preset: str, dynamic: bool, narrative_context: Optional[Dict[str, Any]] = None) -> str:
    """根据风格、动态程度和叙事上下文生成光照描述"""
    base_lighting_map = {
        "cinematic_realistic": "自然光，柔和漫射，真实阴影，高光层次丰富" if not dynamic else "戏剧性光影，强烈对比，动态阴影，高光突出",
        "anime": "柔和光照，赛璐璐阴影，边缘光，色彩统一" if not dynamic else "动态光照，速度光效，高对比阴影，强调轮廓",
        "ink_wash": "自然光，柔和漫射，墨色渐变，留白光影" if not dynamic else "动态笔触，墨色流动，光影变化，意境深远",
        "cyberpunk": "霓虹灯光，冷色调主光，环境光丰富，高对比" if not dynamic else "动态霓虹，光效流动，强烈对比，科技感光影",
    }
    
    lighting = base_lighting_map.get(style_preset, "自然光照，真实阴影，层次丰富")
    
    if narrative_context and isinstance(narrative_context, dict):
        emotion_intensity = narrative_context.get("emotion_intensity", "medium")
        scene_type = narrative_context.get("scene_type", "normal")
        
        if emotion_intensity == "high":
            if scene_type == "emotional":
                lighting = "戏剧性侧光，强烈对比，情感化阴影，高光突出"
            elif scene_type == "action":
                lighting = "动态光照，强烈对比，速度光效，高光突出"
        elif emotion_intensity == "low":
            lighting = "柔和自然光，均匀漫射，柔和阴影，层次细腻"
    
    return lighting


def _get_atmosphere_description(style_preset: str, narrative_context: Optional[Dict[str, Any]] = None) -> str:
    """根据风格和叙事上下文生成氛围描述"""
    base_atmosphere_map = {
        "cinematic_realistic": "电影级氛围，真实感强，情感细腻",
        "anime": "动画氛围，活力十足，色彩明快",
        "ink_wash": "古典意境，东方美学，宁静致远",
        "cyberpunk": "未来感，科技氛围，冷峻神秘",
    }
    
    atmosphere = base_atmosphere_map.get(style_preset, "氛围统一，情感表达清晰")
    
    if narrative_context and isinstance(narrative_context, dict):
        emotion_intensity = narrative_context.get("emotion_intensity", "medium")
        scene_type = narrative_context.get("scene_type", "normal")
        
        if emotion_intensity == "high":
            if scene_type == "emotional":
                atmosphere = "情感强烈，氛围紧张，情绪饱满"
            elif scene_type == "action":
                atmosphere = "紧张激烈，动感十足，节奏紧凑"
        elif emotion_intensity == "low":
            atmosphere = "平静舒缓，氛围温和，节奏舒缓"
    
    return atmosphere


def _get_narrative_guidance(narrative_role: str, emotion_level: str, narrative_context: Optional[Dict[str, Any]] = None) -> str:
    """根据叙事角色和情感强度生成叙事指导"""
    guidance_map = {
        "establishing": "建立场景，展现环境，交代空间关系",
        "action": "动作清晰，动态强烈，节奏紧凑",
        "emotional": "情感突出，表情细腻，氛围渲染",
        "dialogue": "对话清晰，人物互动，焦点明确",
        "power": "气势强大，主体突出，压迫感强",
        "vulnerable": "主体渺小，环境压迫，脆弱感强",
        "intensify": "逐渐增强，情绪递进，张力提升",
        "reveal": "逐步展现，信息释放，视觉冲击",
    }
    
    guidance = guidance_map.get(narrative_role, "")
    
    if emotion_level == "high":
        guidance += "，情感强烈，张力十足"
    elif emotion_level == "low":
        guidance += "，情感平和，节奏舒缓"
    
    if narrative_context and isinstance(narrative_context, dict):
        scene_type = narrative_context.get("scene_type", "normal")
        if scene_type == "dialogue":
            guidance += "，注重人物表情和眼神交流"
        elif scene_type == "action":
            guidance += "，强调动作连贯和速度感"
        elif scene_type == "emotional":
            guidance += "，突出情感变化和内心世界"
    
    return guidance


def _get_texture_description(style_preset: str) -> str:
    """根据风格生成质感描述"""
    texture_map = {
        "cinematic_realistic": "皮肤纹理细腻，材质质感真实，细节丰富",
        "anime": "线条清晰流畅，色彩纯净，造型精致",
        "ink_wash": "宣纸质感自然，墨色浓淡相宜，笔触飘逸",
        "cyberpunk": "金属质感强烈，科技细节丰富，表面光滑",
    }
    return texture_map.get(style_preset, "质感统一，细节清晰")


def _build_motion_desc(*, visual_desc: str, profile: Dict[str, str], dynamic: bool) -> str:
    """
    优化说明：
    - 增强动作描述的细节和层次
    - 根据动态程度调整运动强度
    - 添加速度感和节奏控制
    - 强调连续性和一致性
    """
    snippet = visual_desc[:80]
    movement = str(profile.get("movement") or "镜头稳定")
    
    if dynamic:
        intensity = "动作明显，节奏紧张，速度感强"
        motion_detail = "动态模糊适度，主体运动轨迹清晰，背景有自然流动感"
        continuity = "动作连贯，无跳变，保持人物与风格一致，动态效果自然"
    else:
        intensity = "主体有细微动作变化，节奏舒缓平稳"
        motion_detail = "动态微妙，呼吸感自然，环境有轻微流动"
        continuity = "画面稳定，连续性好，保持人物与风格一致"
    
    return f"{movement}，{intensity}，{motion_detail}，{continuity}。参考画面要点：{snippet}"


