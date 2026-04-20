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

def _build_wanx_prompt(
    *,
    visual_desc: str,
    profile: Dict[str, str],
    entity_matches: Dict[str, List[Tuple[str, str]]],
    style_preset: str,
    style_prompt: str,
    dynamic: bool,
    audio_marker: Optional[Any] = None,
    narrative_context: Optional[Dict[str, Any]] = None,
) -> str:
    """
    按照阿里云百炼公式生成提示词
    
    阿里云百炼提示词公式：
    - 基础公式：提示词 = 主体 + 场景 + 运动
    - 进阶公式：提示词 = 主体（主体描述）+ 场景（场景描述）+ 运动（运动描述）+ 美学控制 + 风格化
    - 声音公式：提示词 = 主体 + 场景 + 运动 + 声音描述（人声/音效/背景音乐）
    
    Args:
        visual_desc: 视觉描述
        profile: 镜头配置
        entity_matches: 实体匹配结果
        style_preset: 风格预设
        style_prompt: 风格提示词
        dynamic: 是否动态
        audio_marker: 音频标记（可选）
        narrative_context: 叙事上下文
    
    Returns:
        阿里云百炼格式的提示词
    """
    chars_text = _format_entity_items(entity_matches.get("characters") or [], max_desc_len=36)
    scenes_text = _format_entity_items(entity_matches.get("scenes") or [], max_desc_len=48)
    props_text = _format_entity_items(entity_matches.get("props") or [], max_desc_len=36)
    
    camera = str(profile.get("camera") or "中景")
    lens = str(profile.get("lens") or "50mm")
    angle = str(profile.get("angle") or "平视")
    movement = str(profile.get("movement") or "镜头稳定")
    
    emotion_level = profile.get("emotion_level", "medium")
    
    subject_desc = _build_subject_description(visual_desc, chars_text, props_text, emotion_level)
    scene_desc = _build_scene_description(scenes_text, style_preset, narrative_context)
    motion_desc = _build_motion_description(visual_desc, movement, dynamic, emotion_level)
    aesthetic_desc = _build_aesthetic_description(camera, lens, angle, movement, style_preset, narrative_context)
    style_desc = _build_style_description(style_preset, style_prompt)
    
    parts = [
        f"主体描述：{subject_desc}",
        f"场景描述：{scene_desc}",
        f"运动描述：{motion_desc}",
        f"美学控制：{aesthetic_desc}",
        f"风格化：{style_desc}",
    ]
    
    if audio_marker and hasattr(audio_marker, "to_wanx_audio_description"):
        audio_desc = audio_marker.to_wanx_audio_description()
        if audio_desc:
            parts.append(f"声音描述：{audio_desc}")
    
    return "；".join(parts)


def _build_subject_description(
    visual_desc: str,
    chars_text: str,
    props_text: str,
    emotion_level: str
) -> str:
    """
    构建主体描述
    
    主体描述是对主体外观特征细节的描述，可通过形容词或短句列举
    """
    parts = [visual_desc]
    
    if chars_text:
        parts.append(f"角色：{chars_text}")
    
    if props_text:
        parts.append(f"道具：{props_text}")
    
    if emotion_level == "high":
        parts.append("表情生动，情感强烈")
    elif emotion_level == "medium":
        parts.append("表情自然，情感适中")
    
    return "，".join(parts)


def _build_scene_description(
    scenes_text: str,
    style_preset: str,
    narrative_context: Optional[Dict[str, Any]] = None
) -> str:
    """
    构建场景描述
    
    场景描述是对主体所处环境特征细节的描述，可通过形容词或短句列举
    """
    parts = []
    
    if scenes_text:
        parts.append(scenes_text)
    
    if narrative_context and isinstance(narrative_context, dict):
        scene_type = narrative_context.get("scene_type", "normal")
        emotion_intensity = narrative_context.get("emotion_intensity", "medium")
        
        if scene_type == "emotional" and emotion_intensity == "high":
            parts.append("环境氛围强烈，光影对比明显")
        elif scene_type == "action" and emotion_intensity == "high":
            parts.append("动态环境，空间层次丰富")
        elif scene_type == "dialogue":
            parts.append("对话环境，背景简洁清晰")
    
    scene_style_map = {
        "cinematic_realistic": "真实环境，自然光照，空间层次分明",
        "anime": "动画场景，色彩明快，背景简洁",
        "ink_wash": "古典环境，意境深远，留白空间",
        "cyberpunk": "未来场景，霓虹灯光，科技感强",
    }
    
    parts.append(scene_style_map.get(style_preset, "环境统一，氛围协调"))
    
    return "，".join(parts)


def _build_motion_description(
    visual_desc: str,
    movement: str,
    dynamic: bool,
    emotion_level: str
) -> str:
    """
    构建运动描述
    
    运动描述包含运动的幅度、速率和运动作用的效果
    """
    motion_keywords = {
        "跑": "快速奔跑，身体前倾，步伐有力",
        "冲": "急速冲刺，动作迅猛，气势强烈",
        "追": "奋力追逐，速度极快，紧张激烈",
        "逃": "仓皇逃窜，动作慌乱，速度极快",
        "闪": "快速闪避，身手敏捷，动作流畅",
        "跳": "跳跃动作，幅度适中，落地轻盈",
        "扑": "猛扑向前，动作迅猛，气势逼人",
        "打": "挥拳打击，力量十足，动作干脆",
        "砍": "挥刀砍击，动作迅猛，力道强劲",
        "刺": "突刺攻击，速度极快，精准有力",
        "踢": "踢腿攻击，动作利落，力量集中",
        "挥": "挥手动作，幅度适中，自然流畅",
        "爆": "爆炸效果，冲击强烈，碎片飞溅",
        "炸": "炸裂效果，声势浩大，冲击波明显",
        "坠": "坠落动作，速度加快，重力明显",
        "飞": "飞行动作，姿态优雅，速度平稳",
        "翻": "翻滚动作，幅度适中，动作连贯",
        "撞": "撞击动作，力量集中，冲击强烈",
        "突袭": "突然袭击，速度极快，出其不意",
        "追逐": "追逐场景，速度极快，紧张激烈",
        "掠过": "快速掠过，动作轻盈，一闪而过",
        "狂奔": "疯狂奔跑，速度极快，气势猛烈",
        "急速": "急速运动，速度极快，动作迅猛",
    }
    
    motion_desc = []
    
    for keyword, desc in motion_keywords.items():
        if keyword in visual_desc:
            motion_desc.append(desc)
            break
    
    if dynamic:
        motion_desc.append("大幅度运动，动态强烈")
    else:
        motion_desc.append("小幅运动，动作自然")
    
    if emotion_level == "high":
        motion_desc.append("运动幅度大，速率快，效果强烈")
    elif emotion_level == "medium":
        motion_desc.append("运动幅度适中，速率正常，效果自然")
    else:
        motion_desc.append("运动幅度小，速率缓慢，效果温和")
    
    motion_desc.append(movement)
    
    return "，".join(motion_desc) if motion_desc else "动作自然，运动平缓"


def _build_aesthetic_description(
    camera: str,
    lens: str,
    angle: str,
    movement: str,
    style_preset: str,
    narrative_context: Optional[Dict[str, Any]] = None
) -> str:
    """
    构建美学控制描述
    
    美学控制包含光源、光线环境、景别、视角、镜头、运镜等
    """
    parts = []
    
    light_map = {
        "cinematic_realistic": "自然光，真实阴影，高光层次丰富",
        "anime": "柔和光照，赛璐璐阴影，边缘光明显",
        "ink_wash": "自然光，墨色渐变，留白光影",
        "cyberpunk": "霓虹灯光，冷色调主光，环境光丰富",
    }
    
    parts.append(f"光源：{light_map.get(style_preset, '自然光照，真实阴影')}")
    
    light_env_map = {
        "cinematic_realistic": "柔光，漫射光，真实光感",
        "anime": "柔光，均匀光照，色彩统一",
        "ink_wash": "柔和漫射，自然光感，意境深远",
        "cyberpunk": "强对比，环境光丰富，科技感强",
    }
    
    parts.append(f"光线环境：{light_env_map.get(style_preset, '柔光，自然光感')}")
    
    parts.append(f"景别：{camera}")
    parts.append(f"视角：{angle}")
    parts.append(f"镜头：{lens}")
    parts.append(f"运镜：{movement}")
    
    if narrative_context and isinstance(narrative_context, dict):
        emotion_intensity = narrative_context.get("emotion_intensity", "medium")
        
        if emotion_intensity == "high":
            parts.append("光影对比强烈，戏剧性效果")
        elif emotion_intensity == "low":
            parts.append("光影柔和，氛围平和")
    
    return "，".join(parts)


def _build_style_description(style_preset: str, style_prompt: str) -> str:
    """
    构建风格化描述
    
    风格化是对画面风格语言的描述
    """
    style_map = {
        "cinematic_realistic": "电影写实风格，真实质感，高清细节",
        "anime": "动漫风格，色彩明快，线条清晰",
        "ink_wash": "水墨风格，东方美学，意境深远",
        "cyberpunk": "赛博朋克风格，未来感，科技美学",
    }
    
    base_style = style_map.get(style_preset, "写实风格，统一风格")
    
    if style_prompt:
        return f"{base_style}，{style_prompt}"
    
    return base_style


def _build_multi_shot_prompt(
    *,
    storyboard: List[Dict[str, Any]],
    overall_description: str,
    narrative_style: str = "third_person",
    main_emotion: str = "neutral",
    entity_matches: Dict[str, List[Tuple[str, str]]],
    style_preset: str,
    style_prompt: str,
    audio_markers: Optional[List[Any]] = None,
) -> str:
    """
    构建多镜头连贯叙事提示词（遵循阿里云百炼多镜头公式）
    
    阿里云百炼多镜头公式：
    提示词 = 总体描述 + 镜头序号 + 时间戳 + 分镜内容
    
    - 总体描述：简要概述整个视频内容，说明故事主题、叙述风格、主要情感或核心事件
    - 镜头序号：为每个镜头分配编号，用于区分视频中不同的场景或段落顺序
    - 时间戳：标明每个镜头在视频中的具体时间范围，确保镜头内容与视频时间线对应
    - 分镜内容：详细描述每个分镜头中主要角色或物体的具体行为
    
    Args:
        storyboard: 分镜列表
        overall_description: 总体描述
        narrative_style: 叙述风格（first_person/third_person）
        main_emotion: 主要情感
        entity_matches: 实体匹配结果
        style_preset: 风格预设
        style_prompt: 风格提示词
        audio_markers: 音频标记列表（可选）
    
    Returns:
        多镜头连贯叙事提示词
    """
    narrative_style_map = {
        "first_person": "第一人称视角",
        "third_person": "第三人称视角",
        "omniscient": "全知视角",
    }
    
    emotion_map = {
        "neutral": "平静",
        "happy": "欢乐",
        "sad": "悲伤",
        "angry": "愤怒",
        "fearful": "恐惧",
        "surprised": "惊讶",
        "tense": "紧张",
        "calm": "温和",
        "excited": "兴奋",
    }
    
    parts = []
    
    overall_desc = (
        f"这个故事以{narrative_style_map.get(narrative_style, '第三人称视角')}，"
        f"主要情感为{emotion_map.get(main_emotion, '平静')}。"
        f"{overall_description}"
    )
    parts.append(f"总体描述：{overall_desc}")
    
    chars_text = _format_entity_items(entity_matches.get("characters") or [], max_desc_len=36)
    scenes_text = _format_entity_items(entity_matches.get("scenes") or [], max_desc_len=48)
    
    current_time = 0.0
    avg_duration = 3.0
    
    for idx, shot in enumerate(storyboard):
        if not isinstance(shot, dict):
            continue
        
        shot_num = idx + 1
        start_time = current_time
        duration = shot.get("duration", avg_duration)
        end_time = start_time + duration
        current_time = end_time
        
        visual_desc = shot.get("visual_desc", "")
        profile = shot.get("profile", {})
        dynamic = shot.get("dynamic", False)
        
        camera = str(profile.get("camera") or "中景")
        lens = str(profile.get("lens") or "50mm")
        angle = str(profile.get("angle") or "平视")
        movement = str(profile.get("movement") or "镜头稳定")
        
        shot_content = _build_single_shot_content(
            visual_desc=visual_desc,
            camera=camera,
            lens=lens,
            angle=angle,
            movement=movement,
            dynamic=dynamic,
            chars_text=chars_text,
            scenes_text=scenes_text,
            style_preset=style_preset,
            style_prompt=style_prompt,
        )
        
        parts.append(f"第{shot_num}个镜头[{start_time:.0f}-{end_time:.0f}秒]{shot_content}")
    
    if audio_markers and isinstance(audio_markers, list):
        for marker in audio_markers:
            if hasattr(marker, "to_wanx_audio_description"):
                audio_desc = marker.to_wanx_audio_description()
                if audio_desc:
                    parts.append(audio_desc)
    
    return "\n".join(parts)


def _build_single_shot_content(
    *,
    visual_desc: str,
    camera: str,
    lens: str,
    angle: str,
    movement: str,
    dynamic: bool,
    chars_text: str,
    scenes_text: str,
    style_preset: str,
    style_prompt: str,
) -> str:
    """
    构建单个镜头的内容描述
    """
    parts = []
    
    if visual_desc:
        parts.append(visual_desc)
    
    if chars_text:
        parts.append(f"角色：{chars_text}")
    
    if scenes_text:
        parts.append(f"环境：{scenes_text}")
    
    parts.append(f"{camera}，{angle}，{lens}")
    parts.append(f"运镜：{movement}")
    
    if dynamic:
        parts.append("动态强烈")
    else:
        parts.append("动态自然")
    
    style_map = {
        "cinematic_realistic": "电影写实风格",
        "anime": "动漫风格",
        "ink_wash": "水墨风格",
        "cyberpunk": "赛博朋克风格",
    }
    
    base_style = style_map.get(style_preset, "写实风格")
    if style_prompt:
        parts.append(f"{base_style}，{style_prompt}")
    else:
        parts.append(base_style)
    
    return "，".join(parts)


def _build_character_reference_prompt(
    *,
    character_profiles: List[Any],
    shot_description: str,
    scene_description: str,
    action_description: str,
    dialogue: Optional[str] = None,
    max_references: int = 3,
) -> str:
    """
    构建使用参考主角的提示词（遵循阿里云百炼参考主角公式）
    
    阿里云百炼参考主角公式：
    提示词 = 主角 + 动作 + 台词 + 场景
    
    - 主角：通过"character1"等标识引用参考主角，最多可同时参考3个主角
    - 动作：描述主角或其他元素的运动状态
    - 台词：主角的说话内容，支持单主角说话或多主角对话
    - 场景：主角所在的环境，包括背景和前景
    
    Args:
        character_profiles: 角色档案列表
        shot_description: 镜头描述
        scene_description: 场景描述
        action_description: 动作描述
        dialogue: 对话内容（可选）
        max_references: 最大参考主角数量
    
    Returns:
        使用参考主角的提示词
    """
    if not character_profiles:
        return shot_description
    
    parts = []
    
    for idx, profile in enumerate(character_profiles[:max_references]):
        if not hasattr(profile, "name") or not hasattr(profile, "character_id"):
            continue
        
        char_id = f"character{idx + 1}"
        char_name = profile.name
        char_desc = profile.appearance_description if hasattr(profile, "appearance_description") else ""
        
        char_ref = f"{char_id}（{char_name}"
        if char_desc:
            char_ref += f"，{char_desc}"
        char_ref += "）"
        
        parts.append(char_ref)
    
    if parts:
        char_refs = "，".join(parts)
    else:
        return shot_description
    
    prompt_parts = []
    
    if action_description:
        prompt_parts.append(f"{char_refs}{action_description}")
    else:
        prompt_parts.append(char_refs)
    
    if dialogue:
        prompt_parts.append(f"说道：{dialogue}")
    
    if scene_description:
        prompt_parts.append(f"场景：{scene_description}")
    
    return "，".join(prompt_parts)


def _format_character_references(character_profiles: List[Any], max_refs: int = 3) -> str:
    """
    格式化角色参考信息
    
    Args:
        character_profiles: 角色档案列表
        max_refs: 最大参考数量
    
    Returns:
        格式化的角色参考字符串
    """
    if not character_profiles:
        return ""
    
    refs = []
    for idx, profile in enumerate(character_profiles[:max_refs]):
        if not hasattr(profile, "name") or not hasattr(profile, "character_id"):
            continue
        
        char_id = f"character{idx + 1}"
        char_name = profile.name
        char_desc = profile.appearance_description if hasattr(profile, "appearance_description") else ""
        
        ref = f"{char_id}={char_name}"
        if char_desc:
            ref += f"（{char_desc}）"
        
        refs.append(ref)
    
    return "；".join(refs) if refs else ""


def _split_into_segments(source_text: str, *, max_segments: int = 12, min_segments: int = 0) -> List[str]:
    text = (source_text or "").strip()
    if not text:
        return []

    def _split_more(segments: List[str], *, target: int) -> List[str]:
        if not segments:
            return segments
        desired = max(1, int(target))
        if len(segments) >= desired:
            return segments

        def _split_once(block: str) -> List[str]:
            raw = re.sub(r"\s+", " ", str(block or "")).strip()
            if not raw or len(raw) <= 2:
                return []
            sentences = [s.strip() for s in re.split(r"[。！？!?；;]+", raw) if s.strip()]
            if len(sentences) >= 2:
                mid = max(1, len(sentences) // 2)
                left = "。".join(sentences[:mid]).strip()
                right = "。".join(sentences[mid:]).strip()
            else:
                mid = max(1, len(raw) // 2)
                left = raw[:mid].strip()
                right = raw[mid:].strip()
            if not left or not right:
                return []
            return [left, right]

        guard = 0
        while len(segments) < desired and guard < 10_000:
            guard += 1
            idx = max(range(len(segments)), key=lambda i: len(segments[i]))
            parts = _split_once(segments[idx])
            if len(parts) != 2:
                break
            segments[idx : idx + 1] = parts
        return segments

    def _extract_scene_beats(block: str) -> List[str]:
        lines = [ln.rstrip() for ln in str(block or "").splitlines()]
        if not lines:
            return []

        scene_header = ""
        first = lines[0].strip()
        if first.startswith("###"):
            scene_header = re.sub(r"^###\s*", "", first).strip()

        # 1) 优先使用“节拍：”下的要点（更适合转为可画画面）
        beats_idx = None
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s.startswith("节拍") and (s.endswith(":") or s.endswith("：") or s == "节拍"):
                beats_idx = i
                break
        if beats_idx is not None:
            beats: List[str] = []
            for ln in lines[beats_idx + 1 :]:
                s = ln.strip()
                if not s:
                    if beats:
                        break
                    continue
                if s.startswith(("对白", "视觉锚点", "人物", "###")):
                    if beats:
                        break
                    continue
                if s.startswith("-"):
                    beats.append(s.lstrip("-").strip())
                else:
                    if beats:
                        beats[-1] = f"{beats[-1]} {s}".strip()
                    else:
                        beats.append(s)
            out = [re.sub(r"\s+", " ", b).strip() for b in beats if str(b).strip()]
            if scene_header and out:
                out = [f"{scene_header}：{b}" for b in out]
            return out

        # 2) 回退：过滤结构化行，取前若干行作为段落摘要
        picked: List[str] = []
        for ln in lines:
            s = ln.strip()
            if not s:
                continue
            if s.startswith(("###", "人物", "对白", "视觉锚点", "节拍")):
                continue
            if s.startswith("-"):
                s = s.lstrip("-").strip()
            picked.append(s)
            if len(" ".join(picked)) >= 260:
                break
        summary = re.sub(r"\s+", " ", " ".join(picked)).strip()
        if scene_header and summary:
            summary = f"{scene_header}：{summary}"
        return [summary] if summary else []

    # 优先按“### 场X”切分（更贴合短剧工程的 Scene 结构）
    scene_starts = [m.start() for m in re.finditer(r"(?m)^###\s*场\s*\d+", text)]
    if scene_starts:
        blocks: List[str] = []
        for i, start in enumerate(scene_starts):
            end = scene_starts[i + 1] if i + 1 < len(scene_starts) else len(text)
            blocks.append(text[start:end].strip())
        segments: List[str] = []
        for b in blocks:
            segments.extend(_extract_scene_beats(b))
            if len(segments) >= max_segments:
                break
        segments = [s for s in segments if str(s).strip()]
        if segments:
            target = max(0, int(min_segments))
            if target > 1:
                segments = _split_more(segments, target=min(target, int(max_segments)))
            return segments[:max_segments]

    # 回退：按空行切分
    segments = [s.strip() for s in re.split(r"\n\s*\n+", text) if s.strip()]
    segments = segments or [text]
    target = max(0, int(min_segments))
    if target > 1:
        segments = _split_more(segments, target=min(target, int(max_segments)))
    return segments[:max_segments]


def _build_visual_desc(text: str) -> str:
    snippet = str(text or "")
    # 去掉对白引号（避免把大量对白当作画面指令）
    snippet = re.sub(r"“[^”]{0,120}”", "", snippet)
    snippet = re.sub(r"\s+", " ", snippet).strip()
    return snippet[:140]


