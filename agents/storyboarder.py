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


def _iter_entity_items(entities: Any, key: str, *, limit: int = 12) -> List[Tuple[str, str]]:
    if not isinstance(entities, dict):
        return []
    items = entities.get(key)
    if not isinstance(items, list):
        return []
    out: List[Tuple[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        desc = str(item.get("descriptor") or "").strip()
        out.append((name, desc))
        if len(out) >= limit:
            break
    return out


def _match_entities_in_text(
    text: str,
    entities: Any,
    *,
    max_characters: int = 2,
    max_scenes: int = 1,
    max_props: int = 2,
) -> Dict[str, List[Tuple[str, str]]]:
    raw = str(text or "")
    chars_all = _iter_entity_items(entities, "characters", limit=24)
    scenes_all = _iter_entity_items(entities, "scenes", limit=16)
    props_all = _iter_entity_items(entities, "props", limit=24)

    chars = [(n, d) for (n, d) in chars_all if n and n in raw][: max(0, int(max_characters))]
    scenes = [(n, d) for (n, d) in scenes_all if n and n in raw][: max(0, int(max_scenes))]
    props = [(n, d) for (n, d) in props_all if n and n in raw][: max(0, int(max_props))]

    # 场景缺失时，用第一个 scene 兜底（提升背景一致性）
    if not scenes and scenes_all and max_scenes > 0:
        scenes = scenes_all[:1]

    return {"characters": chars, "scenes": scenes, "props": props}


def _format_entity_items(items: List[Tuple[str, str]], *, max_desc_len: int = 42) -> str:
    out: List[str] = []
    for name, desc in items:
        name = str(name or "").strip()
        if not name:
            continue
        d = str(desc or "").strip()
        if d:
            d = d[: max(0, int(max_desc_len))].strip()
            out.append(f"{name}（{d}）")
        else:
            out.append(name)
        if len(out) >= 4:
            break
    return " / ".join(out)


def _postprocess_frame_prompt(prompt: str, *, style_preset: str, ratio: str) -> str:
    p = str(prompt or "").strip()
    if not p:
        return p
    ratio_norm = normalize_frame_ratio(ratio)
    ratio_alt = ratio_norm.replace(":", "：")
    if ratio_norm not in p and ratio_alt not in p:
        p = f"{p}，{ratio_norm}"
    if "单格" not in p and "单帧" not in p:
        p = f"单格分镜，{p}"
    if not re.search(r"(无文字|不要文字|no\\s*text)", p, flags=re.IGNORECASE):
        p = f"{p}，无文字"
    if not re.search(r"(无水印|不要水印|no\\s*watermark)", p, flags=re.IGNORECASE):
        p = f"{p}，无水印"
    if not re.search(r"(无logo|不要logo|no\\s*logo)", p, flags=re.IGNORECASE):
        p = f"{p}，无logo"
    if not re.search(r"(无边框|不要边框|no\\s*border)", p, flags=re.IGNORECASE):
        p = f"{p}，无边框"
    if not re.search(r"(无拼贴|不要拼贴|no\\s*collage|no\\s*montage)", p, flags=re.IGNORECASE):
        p = f"{p}，无拼贴"
    if style_preset == "anime":
        # anime 动作镜头的动效由调用方根据 dynamic 追加；这里不强行加。
        pass
    return p


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


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except Exception:  # noqa: BLE001
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return float(default)
    try:
        return float(str(raw).strip())
    except Exception:  # noqa: BLE001
        return float(default)


def _count_script_scenes(script_text: str) -> int:
    text = script_text or ""
    return len(re.findall(r"(?m)^###\s*场\s*\d+", text))


def _count_source_chars(text: str) -> int:
    cleaned = re.sub(r"\s+", "", str(text or ""))
    return len(cleaned)


def _looks_like_script(text: str) -> bool:
    raw = str(text or "")
    if not raw.strip():
        return False
    if _count_script_scenes(raw) > 0:
        return True
    return ("节拍" in raw) and ("人物" in raw)


def _count_script_beats(script_text: str) -> int:
    lines = [ln.strip() for ln in str(script_text or "").splitlines()]
    beats = 0
    in_beats = False
    for ln in lines:
        if not ln:
            continue
        if ln.startswith("节拍") and (ln.endswith(":") or ln.endswith("：") or ln == "节拍"):
            in_beats = True
            continue
        if ln.startswith(("对白", "视觉锚点", "人物", "###", "##")):
            in_beats = False
        if in_beats and ln.startswith("-"):
            beats += 1
    return beats


def _auto_target_total_s(*, source_text: str, quality_mode: str) -> float:
    """
    目标总时长（秒）：用于解决“长文本但总时长过短”的问题。
    - 仅作为“软目标”，仍受镜头上限/单镜头时长上限约束。
    """
    char_count = _count_source_chars(source_text)
    mode = str(quality_mode or "").strip().lower()
    if mode == "quality":
        base = 10.0
        cps = 20.0
        max_total = 180.0
    else:
        base = 6.0
        cps = 32.0
        max_total = 90.0
    est = float(base) + (float(char_count) / float(cps if cps > 0 else 20.0))
    if est < float(base):
        est = float(base)
    if est > float(max_total):
        est = float(max_total)
    return round(est, 1)


def _auto_storyboard_targets(
    *,
    source_text: str,
    quality_mode: str,
    uses_video_containers: bool,
    engine_label: str,
    min_shot_s: float,
    max_shot_s: float,
    shot_cap: int,
) -> Dict[str, Any]:
    if not _looks_like_script(source_text):
        return {
            "enabled": False,
            "text_chars": _count_source_chars(source_text),
            "target_total_s": None,
            "target_shots": None,
            "min_shots_hint": 0,
            "hint_max_shots": 0,
            "shot_cap": int(max(1, shot_cap)),
        }

    target_total_s = _auto_target_total_s(source_text=source_text, quality_mode=quality_mode)
    preferred_shot_s = 4.0
    if uses_video_containers:
        # 一致性优先：尽量使用更长的单段视频容器（5/10/15秒离散），减少跨片段漂移。
        prefer = _env_float(
            "DREAMWEAVER_WAN_VIDEO_PREFERRED_CONTAINER_S",
            _env_float("DREAMWEAVER_WAN_I2V_PREFERRED_CONTAINER_S", 15.0),
        )
        preferred_shot_s = normalize_dreamweaver_video_duration_s(prefer, default=15.0)
    else:
        preferred_shot_s = 4.0
    if preferred_shot_s <= 0.0:
        preferred_shot_s = float(min_shot_s) if float(min_shot_s) > 0 else 4.0
    target_shots = int(max(1, math.ceil(float(target_total_s) / float(preferred_shot_s))))
    if shot_cap > 0:
        target_shots = min(int(shot_cap), int(target_shots))

    min_shots_hint = int(max(1, round(float(target_shots) * 0.8)))
    if shot_cap > 0:
        min_shots_hint = min(int(min_shots_hint), int(shot_cap))

    hint_max_shots = int(max(min_shots_hint, round(float(target_shots) * 1.2)))
    if shot_cap > 0:
        hint_max_shots = min(int(hint_max_shots), int(shot_cap))

    return {
        "enabled": True,
        "text_chars": _count_source_chars(source_text),
        "target_total_s": float(target_total_s),
        "target_shots": int(target_shots),
        "min_shots_hint": int(min_shots_hint),
        "hint_max_shots": int(hint_max_shots),
        "shot_cap": int(max(1, shot_cap)),
        "min_shot_s": float(min_shot_s),
        "max_shot_s": float(max_shot_s),
        "engine": str(engine_label or (DREAMWEAVER_I2V_ENGINE if uses_video_containers else "slideshow")).strip().lower() or "slideshow",
    }


def _sum_storyboard_duration_s(storyboard: Any) -> float:
    if not isinstance(storyboard, list):
        return 0.0
    total = 0.0
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        try:
            d = float(item.get("duration_s") or 0.0)
        except Exception:  # noqa: BLE001
            d = 0.0
        if d > 0.0:
            total += d
    return float(round(total, 1))


def _rebalance_storyboard_total_duration(
    storyboard: Any,
    *,
    target_total_s: Optional[float],
    min_s: float,
    max_s: float,
    uses_video_containers: bool,
    engine_label: str,
    tolerance: float = 0.15,
) -> Dict[str, Any]:
    if not isinstance(storyboard, list) or not storyboard:
        return {"enabled": False}
    if target_total_s is None or float(target_total_s) <= 0.0:
        return {"enabled": False}

    target = float(target_total_s)
    tol = float(tolerance) if tolerance and tolerance > 0 else 0.15
    before = _sum_storyboard_duration_s(storyboard)
    low = target * (1.0 - tol)
    high = target * (1.0 + tol)
    if low <= before <= high:
        return {"enabled": True, "changed": False, "target_total_s": target, "before_total_s": before, "after_total_s": before}

    changed = False
    min_v = float(min_s)
    max_v = float(max_s)
    if max_v < min_v:
        max_v = min_v

    def _weight(it: Dict[str, Any]) -> int:
        return len(str(it.get("desc") or "")) + len(str(it.get("visual_desc") or ""))

    if before < low:
        delta = target - before
        if uses_video_containers:
            steps = [5.0, 10.0, 15.0]
            idxs = sorted(range(len(storyboard)), key=lambda i: _weight(storyboard[i]) if isinstance(storyboard[i], dict) else 0, reverse=True)
            for i in idxs:
                if delta <= 1e-6:
                    break
                it = storyboard[i]
                if not isinstance(it, dict):
                    continue
                try:
                    cur = float(it.get("duration_s") or 0.0)
                except Exception:  # noqa: BLE001
                    cur = 0.0
                if cur <= 0.0:
                    cur = 5.0
                if cur not in steps:
                    cur = normalize_dreamweaver_video_duration_s(cur, default=5.0)
                pos = steps.index(cur) if cur in steps else 0
                if pos >= len(steps) - 1:
                    continue
                nxt = steps[pos + 1]
                it["duration_s"] = float(nxt)
                delta -= float(nxt - cur)
                changed = True
        else:
            durations: List[Tuple[int, float, float]] = []
            for idx, it in enumerate(storyboard):
                if not isinstance(it, dict):
                    continue
                try:
                    cur = float(it.get("duration_s") or 0.0)
                except Exception:  # noqa: BLE001
                    cur = 0.0
                cur = max(min_v, min(max_v, cur if cur > 0 else min_v))
                headroom = max_v - cur
                if headroom > 1e-6:
                    durations.append((idx, cur, headroom))
            cap = sum(hr for _idx, _cur, hr in durations)
            if cap > 1e-6:
                for idx, cur, headroom in durations:
                    inc = delta * (headroom / cap)
                    if inc > headroom:
                        inc = headroom
                    new_v = cur + inc
                    if new_v > max_v:
                        new_v = max_v
                    storyboard[idx]["duration_s"] = round(float(new_v), 1)
                changed = True

    if before > high:
        delta = before - target
        if uses_video_containers:
            # 一致性优先：默认不做“缩短总时长”的回压，避免把 15s 容器又压回 10/5。
            # 若需要成本控制，可显式开启该开关。
            if not env_flag("DREAMWEAVER_WAN_I2V_REBALANCE_ALLOW_SHRINK", default=False):
                delta = 0.0
            if delta <= 1e-6:
                after = _sum_storyboard_duration_s(storyboard)
                return {
                    "enabled": True,
                    "changed": False,
                    "target_total_s": target,
                    "before_total_s": before,
                    "after_total_s": after,
                    "tolerance": tol,
                    "mode": str(engine_label or DREAMWEAVER_I2V_ENGINE),
                    "note": "skip_shrink",
                }
            steps = [5.0, 10.0, 15.0]
            idxs = sorted(range(len(storyboard)), key=lambda i: _weight(storyboard[i]) if isinstance(storyboard[i], dict) else 0)
            for i in idxs:
                if delta <= 1e-6:
                    break
                it = storyboard[i]
                if not isinstance(it, dict):
                    continue
                try:
                    cur = float(it.get("duration_s") or 0.0)
                except Exception:  # noqa: BLE001
                    cur = 0.0
                if cur <= 0.0:
                    cur = 5.0
                if cur not in steps:
                    cur = normalize_dreamweaver_video_duration_s(cur, default=5.0)
                pos = steps.index(cur) if cur in steps else 0
                if pos <= 0:
                    continue
                nxt = steps[pos - 1]
                it["duration_s"] = float(nxt)
                delta -= float(cur - nxt)
                changed = True
        else:
            durations = []
            for idx, it in enumerate(storyboard):
                if not isinstance(it, dict):
                    continue
                try:
                    cur = float(it.get("duration_s") or 0.0)
                except Exception:  # noqa: BLE001
                    cur = 0.0
                cur = max(min_v, min(max_v, cur if cur > 0 else min_v))
                reducible = cur - min_v
                if reducible > 1e-6:
                    durations.append((idx, cur, reducible))
            cap = sum(rd for _idx, _cur, rd in durations)
            if cap > 1e-6:
                for idx, cur, reducible in durations:
                    dec = delta * (reducible / cap)
                    if dec > reducible:
                        dec = reducible
                    new_v = cur - dec
                    if new_v < min_v:
                        new_v = min_v
                    storyboard[idx]["duration_s"] = round(float(new_v), 1)
                changed = True

    after = _sum_storyboard_duration_s(storyboard)
    return {
        "enabled": True,
        "changed": bool(changed),
        "target_total_s": target,
        "before_total_s": before,
        "after_total_s": after,
        "tolerance": tol,
        "mode": str(engine_label or (DREAMWEAVER_I2V_ENGINE if uses_video_containers else "continuous")),
    }


def _storyboard_too_short_reason(
    storyboard: Any,
    *,
    min_shots_hint: int,
    target_total_s: Optional[float],
    tolerance: float = 0.2,
) -> str:
    if not isinstance(storyboard, list) or not storyboard:
        return "empty storyboard"
    min_shots = max(0, int(min_shots_hint))
    if min_shots > 0 and len(storyboard) < min_shots:
        return f"shots {len(storyboard)} < hint {min_shots}"
    if target_total_s is None or float(target_total_s) <= 0.0:
        return ""
    total = _sum_storyboard_duration_s(storyboard)
    target = float(target_total_s)
    tol = float(tolerance) if tolerance and tolerance > 0 else 0.2
    if total < target * (1.0 - tol):
        return f"total_duration_s {total} < {(target * (1.0 - tol)):.1f}"
    return ""


def _auto_max_shots_from_script(*, script_text: str, quality_mode: str) -> int:
    text = str(script_text or "")
    scenes = max(1, int(_count_script_scenes(text)))
    beats = max(0, int(_count_script_beats(text)))
    char_count = _count_source_chars(text)

    mode = str(quality_mode or "").strip().lower()
    if mode == "quality":
        per_scene_floor = scenes * 2
        base = 12
        chars_per_shot = 140
        hard_cap = 240
    else:
        per_scene_floor = scenes * 1
        base = 8
        chars_per_shot = 240
        hard_cap = 120

    estimated_by_chars = max(1, int(math.ceil(float(char_count) / float(max(60, int(chars_per_shot))))))
    estimated = max(int(base), int(per_scene_floor), int(beats), int(estimated_by_chars))
    return int(min(int(hard_cap), int(estimated)))


def _storyboard_safety_max_shots(*, quality_mode: str) -> int:
    """
    防止 LLM 生成无限长 JSON 导致内存/耗时不可控的“安全上限”。
    - 不建议把它理解为业务上限；更像是系统保护阈值。
    """
    default = 240 if str(quality_mode or "").strip().lower() == "quality" else 120
    return max(1, int(_env_int("DREAMWEAVER_STORYBOARD_SAFETY_MAX_SHOTS", default)))


def _estimate_shot_duration_s(text: str, *, min_s: float, max_s: float, base_s: float, cps: float) -> float:
    """
    根据文本长度估算镜头时长，解决“默认3秒导致整体过短”的问题。
    - min_s/max_s：避免极端值（I2V 通常也有时长上限）
    - base_s：镜头基础时长
    - cps：chars-per-second，控制节奏（越大越快）
    """
    cleaned = re.sub(r"\s+", "", str(text or ""))
    char_count = len(cleaned)
    safe_cps = cps if cps and cps > 0 else 20.0
    duration = float(base_s) + (float(char_count) / float(safe_cps))
    if duration < float(min_s):
        duration = float(min_s)
    if duration > float(max_s):
        duration = float(max_s)
    return round(duration, 1)


def _auto_adjust_storyboard_durations(storyboard: Any, *, min_s: float, max_s: float, base_s: float, cps: float) -> None:
    """
    统一修正 LLM/规则输出的 duration_s：
    - 缺失/非法：使用估算值
    - 低于下限：抬到下限
    - 高于上限：压到上限（避免 I2V 不支持的过长镜头）
    - 若看起来是默认值 3.0：允许按估算拉长（但不缩短）
    """
    if not isinstance(storyboard, list):
        return
    min_v = float(min_s)
    max_v = float(max_s)
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        raw = item.get("duration_s")
        try:
            cur = float(raw) if raw is not None else None
        except Exception:  # noqa: BLE001
            cur = None

        est = _estimate_shot_duration_s(str(item.get("desc") or ""), min_s=min_v, max_s=max_v, base_s=base_s, cps=cps)
        if cur is None or cur <= 0:
            item["duration_s"] = est
            continue
        if cur < min_v:
            item["duration_s"] = min_v
            continue
        if cur > max_v:
            item["duration_s"] = max_v
            continue
        if abs(cur - 3.0) < 1e-6 and est > cur:
            item["duration_s"] = est


def _clamp_01(value: Any, default: float = 0.5) -> float:
    try:
        v = float(value)
    except Exception:  # noqa: BLE001
        return default
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _normalize_ratio(value: Any, default: str = "16:9") -> str:
    text = str(value or "").strip()
    if not text:
        return normalize_frame_ratio(None, default=default)
    return normalize_frame_ratio(text, default=default)


def _normalize_frame_spec(frame: Any, *, default_prompt: str, default_ratio: str) -> Dict[str, Any]:
    spec: Dict[str, Any] = frame if isinstance(frame, dict) else {}
    prompt = str(spec.get("prompt") or default_prompt or "").strip()
    ratio = _normalize_ratio(spec.get("ratio"), default=default_ratio)
    subject_pos = spec.get("subject_pos") if isinstance(spec.get("subject_pos"), dict) else {}
    x = _clamp_01(subject_pos.get("x"), default=0.5)
    y = _clamp_01(subject_pos.get("y"), default=0.5)
    out: Dict[str, Any] = {
        "prompt": prompt or default_prompt,
        "ratio": ratio,
        "subject_pos": {"x": x, "y": y},
    }
    seed = spec.get("seed")
    try:
        if seed is not None:
            seed_int = int(seed)
            out["seed"] = seed_int
    except Exception:  # noqa: BLE001
        pass
    return out


def _safe_float(value: Any) -> Optional[float]:
    try:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
        return float(value)
    except Exception:  # noqa: BLE001
        return None


def _normalize_video_subshots(subshots: Any, *, duration_s: float) -> List[Dict[str, Any]]:
    """
    归一化 Wan I2V 的容器内子分镜时间轴。

    目标：
    - 覆盖 [0, duration_s]，无重叠、无空洞（会做轻量修正）
    - start_s/end_s 为数字，且 0<=start<end<=duration_s
    """
    try:
        duration = float(duration_s)
    except Exception:  # noqa: BLE001
        return []
    if duration <= 0.0:
        return []

    if not isinstance(subshots, list):
        return []

    cleaned: List[Dict[str, Any]] = []
    for raw in subshots:
        if not isinstance(raw, dict):
            continue
        start = _safe_float(raw.get("start_s"))
        end = _safe_float(raw.get("end_s"))
        if start is None or end is None:
            continue
        if end <= start:
            continue
        # 轻量截断到容器范围内
        start = max(0.0, min(float(start), duration))
        end = max(0.0, min(float(end), duration))
        if end <= start:
            continue

        item: Dict[str, Any] = {
            "start_s": round(float(start), 3),
            "end_s": round(float(end), 3),
        }
        for key in ("transition", "shot_type", "camera_angle", "camera_movement", "emotion", "desc", "visual_desc"):
            val = raw.get(key)
            if isinstance(val, (str, int, float)):
                s = str(val).strip()
                if s:
                    item[key] = s
        cleaned.append(item)
        if len(cleaned) >= 12:
            break

    if not cleaned:
        return []

    cleaned.sort(key=lambda x: float(x.get("start_s") or 0.0))

    # 修正：消除重叠，并尽量保证连续。
    normalized: List[Dict[str, Any]] = []
    cursor = 0.0
    for raw in cleaned:
        start = float(raw["start_s"])
        end = float(raw["end_s"])
        if end <= cursor:
            continue
        if start < cursor:
            start = cursor
        if start > cursor + 1e-3:
            # 有空洞：向前贴齐，避免出现不可控的“空白时间段”
            start = cursor
        if end <= start:
            continue
        item = dict(raw)
        item["start_s"] = round(float(start), 3)
        item["end_s"] = round(float(end), 3)
        normalized.append(item)
        cursor = float(end)
        if cursor >= duration - 1e-3:
            break

    if not normalized:
        return []

    # 对齐起止：确保覆盖完整容器
    normalized[0]["start_s"] = 0.0
    normalized[-1]["end_s"] = round(duration, 3)

    # 过多子分镜会导致 prompt 过长：保守裁剪为最多 6 段（优先保留首尾）
    if len(normalized) > 6:
        head = normalized[0]
        tail = normalized[-1]
        middle = normalized[1:-1]
        keep_mid = middle[: max(0, 4 - 2)]
        normalized = [head] + keep_mid + [tail]
        # 重算时间轴：按顺序等分填满，避免因裁剪导致空洞
        segments = len(normalized)
        if segments >= 2:
            step = duration / float(segments)
            for idx, it in enumerate(normalized):
                s = round(float(idx) * step, 3)
                e = round(float(idx + 1) * step, 3)
                it["start_s"] = 0.0 if idx == 0 else s
                it["end_s"] = round(duration, 3) if idx == segments - 1 else e

    return normalized


def _fallback_video_subshots(*, duration_s: float, ff_desc: str, lf_desc: str, visual_desc: str) -> List[Dict[str, Any]]:
    """
    LLM 未输出 subshots 时的保底分解策略：保证时间戳可用，但不替代 LLM 的真实分镜设计。
    """
    duration = normalize_dreamweaver_video_duration_s(duration_s, default=15.0)
    if duration == 5.0:
        bins = [(0.0, 3.0), (3.0, 5.0)]
        types = ["wide_shot", "close_up"]
    elif duration == 10.0:
        bins = [(0.0, 4.0), (4.0, 7.0), (7.0, 10.0)]
        types = ["wide_shot", "medium_shot", "close_up"]
    else:
        bins = [(0.0, 4.0), (4.0, 8.0), (8.0, 12.0), (12.0, 15.0)]
        types = ["wide_shot", "medium_shot", "medium_shot", "close_up"]

    head_desc = ff_desc.strip() or visual_desc.strip()
    tail_desc = lf_desc.strip() or visual_desc.strip()
    mid_desc = visual_desc.strip() or head_desc or tail_desc

    out: List[Dict[str, Any]] = []
    for idx, (s, e) in enumerate(bins):
        desc = mid_desc
        if idx == 0:
            desc = head_desc or mid_desc
        elif idx == len(bins) - 1:
            desc = tail_desc or mid_desc
        out.append(
            {
                "start_s": s,
                "end_s": e,
                "transition": "hard_cut" if idx > 0 else "fade_in",
                "shot_type": types[min(idx, len(types) - 1)],
                "camera_movement": "static" if duration == 5.0 else ("dolly_in" if idx == 0 else "static"),
                "desc": desc[:160],
                "visual_desc": (visual_desc or desc)[:120],
            }
        )
    return out


def _ensure_video_subshots_for_storyboard(storyboard: Any) -> None:
    if not isinstance(storyboard, list):
        return
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        duration = normalize_dreamweaver_video_duration_s(item.get("duration_s"), default=15.0)
        item["duration_s"] = float(duration)
        subshots = _normalize_video_subshots(item.get("subshots"), duration_s=float(duration))
        if not subshots:
            subshots = _fallback_video_subshots(
                duration_s=float(duration),
                ff_desc=str(item.get("ff_desc") or ""),
                lf_desc=str(item.get("lf_desc") or ""),
                visual_desc=str(item.get("visual_desc") or item.get("desc") or ""),
            )
        item["subshots"] = subshots


def _clean_text_chars(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fa5]", "", str(text or ""))


def _scene_key_and_beat_text(text: str) -> Tuple[str, str]:
    """
    从形如“场 1 | 外景 | 地点 | 日：节拍内容”的行里提取 scene_key 与 beat_text。
    """
    s = str(text or "").strip()
    if not s:
        return ("", "")
    for sep in ("：", ":"):
        if sep not in s:
            continue
        head, tail = s.split(sep, 1)
        head = head.strip()
        tail = tail.strip()
        # 含 "|" 的一般是 scene header；限制长度避免把普通对白当 header
        if head and "|" in head and len(head) <= 96 and tail:
            return (head, tail)
        break
    return ("", s)


def _split_beat_once(text: str) -> List[str]:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
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


def _normalize_beats_count(beats: List[str], *, min_n: int, max_n: int) -> List[str]:
    items = [re.sub(r"\s+", " ", str(b or "")).strip() for b in beats if str(b or "").strip()]
    if not items:
        return []
    min_n = max(1, int(min_n))
    max_n = max(min_n, int(max_n))

    # 不足：拆分最长的节拍
    guard = 0
    while len(items) < min_n and guard < 64:
        guard += 1
        idx = max(range(len(items)), key=lambda i: len(items[i]))
        parts = _split_beat_once(items[idx])
        if len(parts) != 2:
            break
        items[idx : idx + 1] = parts

    # 过多：合并相邻最短的两个节拍
    guard = 0
    while len(items) > max_n and guard < 128:
        guard += 1
        if len(items) <= 1:
            break
        best_i = 0
        best_len = len(items[0]) + len(items[1])
        for i in range(len(items) - 1):
            cur = len(items[i]) + len(items[i + 1])
            if cur < best_len:
                best_len = cur
                best_i = i
        merged = f"{items[best_i]}；{items[best_i + 1]}".strip("； ")
        items[best_i : best_i + 2] = [merged]

    return items


def _estimate_video_subshot_weight(text: str) -> float:
    s = str(text or "").strip()
    if not s:
        return 1.0
    chars = len(_clean_text_chars(s))
    w = 1.0 + (float(chars) / 80.0)
    if _detect_dynamic(s):
        w += 0.35
    if any(k in s for k in ("转身", "表情", "眼神", "泪", "细节", "特写")):
        w += 0.15
    return max(0.5, min(w, 4.0))


def _allocate_integer_durations(*, total_s: int, weights: List[float], min_s: int, max_s: int) -> List[int]:
    n = len(weights)
    if n <= 0:
        return []
    total = int(max(1, int(total_s)))
    min_s = int(max(0, int(min_s)))
    max_s = int(max(min_s, int(max_s)))

    # 初分配：按权重比例取整
    wsum = sum(float(w) for w in weights) or 1.0
    durs = [int(round(float(total) * float(w) / wsum)) for w in weights]

    # 夹紧到边界
    durs = [max(min_s, min(max_s, int(d))) for d in durs]

    # 修正总和
    diff = int(total) - int(sum(durs))
    guard = 0
    while diff != 0 and guard < 256:
        guard += 1
        if diff > 0:
            # 给“还没到上限且权重高”的段加 1 秒
            candidates = [(i, weights[i], max_s - durs[i]) for i in range(n) if durs[i] < max_s]
            if not candidates:
                break
            i = max(candidates, key=lambda t: (t[2], t[1]))[0]
            durs[i] += 1
            diff -= 1
        else:
            # 从“高于下限且权重低”的段减 1 秒
            candidates = [(i, weights[i], durs[i] - min_s) for i in range(n) if durs[i] > min_s]
            if not candidates:
                break
            i = min(candidates, key=lambda t: (t[2], t[1]))[0]
            durs[i] -= 1
            diff += 1
    return durs


def _infer_subshot_type(text: str, *, index: int, total: int) -> str:
    s = str(text or "")
    if index == 0:
        return "wide_shot"
    if index == max(0, int(total) - 1):
        return "close_up"
    if any(k in s for k in ("特写", "细节", "眼神", "表情", "手", "泪", "嘴唇")):
        return "close_up"
    if any(k in s for k in ("远处", "全景", "远景", "环境", "场景", "城市", "街", "夜景", "海边", "天空")):
        return "wide_shot"
    return "medium_shot"


def _infer_subshot_movement(text: str, *, index: int, total: int) -> str:
    s = str(text or "")
    if _detect_dynamic(s):
        return "follow"
    if index == 0:
        return "dolly_in"
    if index == max(0, int(total) - 1):
        return "static"
    return "static"


def _plan_video_subshots_from_beats(*, duration_s: float, beats: List[str]) -> List[Dict[str, Any]]:
    duration = int(normalize_dreamweaver_video_duration_s(duration_s, default=15.0))
    if duration not in {5, 10, 15}:
        duration = 15

    raw_beats = [str(b or "").strip() for b in beats if str(b or "").strip()]
    if not raw_beats:
        return []

    total_chars = sum(len(_clean_text_chars(b)) for b in raw_beats)

    if duration == 5:
        target_min, target_max = 2, 2
    elif duration == 10:
        target_min, target_max = 3, 3
    else:
        # 15s：优先 4~6 段；当节拍较少但内容足够时，允许通过拆分补足到 4 段
        target_min, target_max = 4, 6

    normalized_beats = _normalize_beats_count(raw_beats, min_n=target_min, max_n=target_max)
    if not normalized_beats:
        return []

    n = len(normalized_beats)
    weights = [_estimate_video_subshot_weight(b) for b in normalized_beats]
    min_per = 2
    max_per = 5 if duration != 5 else 3
    # 若段数较少，允许更长停留以减少“空洞时间”
    if duration == 15 and n <= 3:
        max_per = 8
        min_per = 3
    if duration == 10 and n == 2:
        max_per = 7
        min_per = 3

    durs = _allocate_integer_durations(total_s=duration, weights=weights, min_s=min_per, max_s=max_per)
    if not durs or sum(durs) != duration:
        return []

    subshots: List[Dict[str, Any]] = []
    t = 0
    for idx, (beat, seg_s) in enumerate(zip(normalized_beats, durs)):
        start = int(t)
        end = int(min(duration, t + int(seg_s)))
        if end <= start:
            continue
        transition = "fade_in" if idx == 0 else "hard_cut"
        subshots.append(
            {
                "start_s": start,
                "end_s": end,
                "transition": transition,
                "shot_type": _infer_subshot_type(beat, index=idx, total=n),
                "camera_angle": "eye_level",
                "camera_movement": _infer_subshot_movement(beat, index=idx, total=n),
                "desc": beat[:160],
                "visual_desc": beat[:120],
            }
        )
        t = end
        if t >= duration:
            break
    if not subshots:
        return []
    subshots[0]["start_s"] = 0
    subshots[-1]["end_s"] = duration
    return subshots


def _pack_video_containers_from_segments(
    segments: List[str],
    *,
    entities: Any,
    max_containers: int,
    prefer_container_s: float,
) -> List[Dict[str, Any]]:
    """
    将“节拍级 segments”打包成更少的 Wan I2V 容器（偏向 15s），并为每个容器规划 subshots。
    """
    cap = int(max(1, max_containers))
    prefer = normalize_dreamweaver_video_duration_s(prefer_container_s, default=15.0)
    prefer_int = int(prefer)

    important_chars: set[str] = set()
    try:
        if isinstance(entities, dict) and isinstance(entities.get("characters"), list):
            for item in entities.get("characters") or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                importance = str(item.get("importance") or "").strip()
                if not importance:
                    continue
                if any(k in importance for k in ("主角", "重要", "固定", "核心")):
                    important_chars.add(name)
    except Exception:  # noqa: BLE001
        important_chars = set()

    hard_break_keywords = (
        "转场",
        "切换",
        "跳转",
        "镜头切换",
        "场景切换",
        "与此同时",
        "数小时后",
        "几小时后",
        "第二天",
        "翌日",
        "回忆",
        "梦境",
        "闪回",
        "忽然",
        "突然",
    )

    beats: List[Tuple[str, str]] = []
    for seg in segments:
        scene_key, beat = _scene_key_and_beat_text(seg)
        beats.append((scene_key, beat))

    containers: List[Dict[str, Any]] = []
    current_scene = ""
    current_beats: List[str] = []
    current_chars: set[str] = set()

    def _flush() -> None:
        nonlocal current_scene, current_beats, containers, current_chars
        if not current_beats:
            return
        merged_text = "\n".join([b for b in current_beats if b.strip()]).strip()
        beat_chars = sum(len(_clean_text_chars(b)) for b in current_beats)
        beat_count = len(current_beats)

        # 选择容器时长：偏向 prefer（默认 15s），信息量不足才降级
        if beat_count >= 4:
            duration = 15
        elif beat_count == 3:
            duration = 15 if (prefer_int == 15 and beat_chars >= 70) else 10
        elif beat_count == 2:
            if prefer_int == 15 and beat_chars >= 80:
                duration = 15
            elif beat_chars >= 55:
                duration = 10
            else:
                duration = 5
        else:
            if prefer_int == 15 and beat_chars >= 120:
                duration = 15
            elif beat_chars >= 70:
                duration = 10
            else:
                duration = 5

        # prefer=10/5 时，不使用更长容器（增加容器数以提升分镜可控性）
        if prefer_int in {5, 10}:
            duration = min(int(duration), prefer_int)

        subshots = _plan_video_subshots_from_beats(duration_s=float(duration), beats=current_beats)
        if not subshots:
            subshots = _fallback_video_subshots(
                duration_s=float(duration),
                ff_desc="",
                lf_desc="",
                visual_desc=merged_text[:140],
            )

        # 可选：为后续素材匹配提供更强提示（不影响现有 schema）
        entity_matches = _match_entities_in_text(merged_text, entities, max_characters=6, max_scenes=2, max_props=4)
        containers.append(
            {
                "scene_key": current_scene,
                "beats": list(current_beats),
                "merged_text": merged_text,
                "duration_s": float(duration),
                "subshots": subshots,
                "entity_matches": entity_matches,
            }
        )
        current_scene = ""
        current_beats = []
        current_chars = set()

    for scene_key, beat in beats:
        # 场景切换时强制换容器
        beat_text = str(beat or "").strip()
        beat_matches = _match_entities_in_text(beat_text, entities, max_characters=6, max_scenes=2, max_props=4) if beat_text else {}
        beat_char_names = {n for (n, _d) in (beat_matches.get("characters") or []) if n}
        introduces_important_char = False
        if important_chars and beat_char_names:
            introduces_important_char = any((c in important_chars) and (c not in current_chars) for c in beat_char_names)
        is_hard_break = bool(beat_text and any(k in beat_text for k in hard_break_keywords))

        if current_beats and scene_key and current_scene and scene_key != current_scene:
            _flush()
        if current_beats and is_hard_break and len(current_beats) >= 2:
            _flush()
        min_beats_for_split = _env_int("DREAMWEAVER_WAN_VIDEO_SPLIT_ON_NEW_IMPORTANT_CHAR_MIN_BEATS", 3)
        if current_beats and introduces_important_char and len(current_beats) >= max(1, int(min_beats_for_split)):
            _flush()

        if not current_beats:
            current_scene = scene_key or current_scene or ""
        if beat_text:
            current_beats.append(beat_text)
            current_chars.update(beat_char_names)
        # 15s 建议最多 6 段；达到即 flush（避免 prompt 过长）
        if len(current_beats) >= 6:
            _flush()
            if len(containers) >= cap:
                break
        if len(containers) >= cap:
            break

    if len(containers) < cap:
        _flush()

    # 若容器数超出 cap（理论上不会），把多余节拍合并到最后一个容器
    if len(containers) > cap:
        tail = containers[: cap - 1]
        last = containers[cap - 1]
        rest = containers[cap:]
        merged_beats: List[str] = []
        for c in [last] + rest:
            merged_beats.extend([b for b in (c.get("beats") or []) if isinstance(b, str)])
        last["beats"] = merged_beats
        last["merged_text"] = "\n".join(merged_beats).strip()
        last["subshots"] = _plan_video_subshots_from_beats(duration_s=float(last.get("duration_s") or 15.0), beats=merged_beats)
        containers = tail + [last]

    return containers


def _smooth_storyboard_subject_pos(storyboard: Any, *, max_delta: float, default_x: float = 0.5, default_y: float = 0.5) -> None:
    """
    归一化 storyboard 的 subject_pos，降低跨镜头/首尾帧构图跳变，避免 AutoQC 以连续性为由反复返工。

    - 约束：使用 L1 距离（abs(dx)+abs(dy)）与 AutoQC 口径一致。
    - 策略：逐镜头对 head_frame 做“最大步长”限幅，并将 tail_frame.subject_pos 对齐到 head_frame（保证镜头内连续）。
    """
    if not isinstance(storyboard, list):
        return
    try:
        limit = float(max_delta)
    except Exception:  # noqa: BLE001
        return
    if not limit or limit <= 0.0:
        return

    # 给浮点误差留余量，避免刚好卡阈值导致误判失败。
    safe_limit = max(0.0, limit - 1e-6)
    prev: Optional[Tuple[float, float]] = None
    for item in storyboard:
        if not isinstance(item, dict):
            continue
        head = item.get("head_frame") if isinstance(item.get("head_frame"), dict) else {}
        tail = item.get("tail_frame") if isinstance(item.get("tail_frame"), dict) else {}

        head_pos = head.get("subject_pos") if isinstance(head.get("subject_pos"), dict) else {}
        tail_pos = tail.get("subject_pos") if isinstance(tail.get("subject_pos"), dict) else {}
        x = _clamp_01(head_pos.get("x"), default=_clamp_01(tail_pos.get("x"), default=default_x))
        y = _clamp_01(head_pos.get("y"), default=_clamp_01(tail_pos.get("y"), default=default_y))

        if prev is not None and safe_limit > 0.0:
            dx = x - prev[0]
            dy = y - prev[1]
            dist = abs(dx) + abs(dy)
            if dist > safe_limit and dist > 0.0:
                factor = safe_limit / dist
                x = prev[0] + dx * factor
                y = prev[1] + dy * factor
                x = _clamp_01(x, default=default_x)
                y = _clamp_01(y, default=default_y)

        head["subject_pos"] = {"x": x, "y": y}
        tail["subject_pos"] = {"x": x, "y": y}
        item["head_frame"] = head
        item["tail_frame"] = tail
        prev = (x, y)


def _entities_summary(entities: Any, limit: int = 12) -> str:
    if not isinstance(entities, dict):
        return ""

    def _take(key: str) -> List[Tuple[str, str]]:
        items = entities.get(key)
        if not isinstance(items, list):
            return []
        out: List[Tuple[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            desc = str(item.get("descriptor") or "").strip()
            out.append((name, desc))
            if len(out) >= limit:
                break
        return out

    parts: List[str] = []
    chars = _take("characters")
    scenes = _take("scenes")
    props = _take("props")
    if chars:
        parts.append("角色：" + "；".join([f"{n}（{d[:40]}）" if d else n for n, d in chars]))
    if scenes:
        parts.append("场景：" + "；".join([f"{n}（{d[:40]}）" if d else n for n, d in scenes]))
    if props:
        parts.append("道具：" + "；".join([f"{n}（{d[:40]}）" if d else n for n, d in props]))
    return "\n".join(parts)


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


def _build_rule_storyboard(
    *,
    source_text: str,
    style_preset: str,
    style_prompt: str,
    ratio: str,
    entities: Any,
    max_segments: int,
    min_segments: int = 0,
    uses_video_containers: bool = False,
) -> List[Dict[str, Any]]:
    raw_segments = _split_into_segments(source_text, max_segments=max_segments, min_segments=min_segments)
    if not raw_segments:
        raw_segments = ["空场景：无输入文本，请补充章节内容。"]

    min_shot_s = _env_float("DREAMWEAVER_STORYBOARD_MIN_SHOT_S", 3.0)
    max_shot_s = _env_float("DREAMWEAVER_STORYBOARD_MAX_SHOT_S", 10.0)
    base_s = _env_float("DREAMWEAVER_STORYBOARD_BASE_S", 2.0)
    cps = _env_float("DREAMWEAVER_STORYBOARD_CHARS_PER_SECOND", 20.0)
    storyboard: List[Dict[str, Any]] = []

    segments: List[Dict[str, Any]] = []
    if uses_video_containers and _looks_like_script(source_text):
        container_cap = int(max(1, int(max_segments)))
        max_beats = min(240, max(12, container_cap * 6))
        min_beats = 0
        try:
            min_beats = max(0, min(int(min_segments) * 4, max_beats))
        except Exception:  # noqa: BLE001
            min_beats = 0
        beats = _split_into_segments(source_text, max_segments=max_beats, min_segments=min_beats)
        prefer_container_s = _env_float(
            "DREAMWEAVER_WAN_VIDEO_PREFERRED_CONTAINER_S",
            _env_float("DREAMWEAVER_WAN_I2V_PREFERRED_CONTAINER_S", 15.0),
        )
        packed = _pack_video_containers_from_segments(
            beats,
            entities=entities,
            max_containers=container_cap,
            prefer_container_s=prefer_container_s,
        )
        for plan in packed:
            if not isinstance(plan, dict):
                continue
            beats_list = plan.get("beats") if isinstance(plan.get("beats"), list) else []
            beats_list = [str(b).strip() for b in beats_list if isinstance(b, str) and str(b).strip()]
            merged_text = str(plan.get("merged_text") or "\n".join(beats_list)).strip()
            duration_s = float(plan.get("duration_s") or 15.0)
            subshots = plan.get("subshots") if isinstance(plan.get("subshots"), list) else []
            entity_matches = plan.get("entity_matches") if isinstance(plan.get("entity_matches"), dict) else None
            if entity_matches is None:
                entity_matches = _match_entities_in_text(merged_text, entities, max_characters=6, max_scenes=2, max_props=4)
            segments.append(
                {
                    "text": merged_text,
                    "duration_s": duration_s,
                    "subshots": subshots,
                    "beats": beats_list,
                    "entity_matches": entity_matches,
                }
            )
    else:
        for seg in raw_segments:
            segments.append({"text": str(seg), "duration_s": None, "subshots": [], "beats": [], "entity_matches": None})

    for idx, seg_obj in enumerate(segments, 1):
        seg = str(seg_obj.get("text") or "").strip()
        if not seg:
            continue
        shot_id = f"S1-{idx}"
        profile = _shot_profile(idx)
        beats_list = seg_obj.get("beats") if isinstance(seg_obj.get("beats"), list) else []
        first_beat = str(beats_list[0]).strip() if beats_list else seg
        last_beat = str(beats_list[-1]).strip() if beats_list else seg
        visual_desc = _build_visual_desc(seg)
        head_visual_desc = _build_visual_desc(first_beat)
        tail_visual_desc = _build_visual_desc(last_beat)
        dynamic = _detect_dynamic(seg)
        entity_matches = seg_obj.get("entity_matches") if isinstance(seg_obj.get("entity_matches"), dict) else None
        if entity_matches is None:
            entity_matches = _match_entities_in_text(seg, entities)
        vis_chars = [name for name, _desc in (entity_matches.get("characters") or []) if name]
        duration_override = seg_obj.get("duration_s")
        if duration_override is None:
            duration_s = _estimate_shot_duration_s(seg, min_s=min_shot_s, max_s=max_shot_s, base_s=base_s, cps=cps)
        else:
            try:
                duration_s = float(duration_override)
            except Exception:  # noqa: BLE001
                duration_s = _estimate_shot_duration_s(seg, min_s=min_shot_s, max_s=max_shot_s, base_s=base_s, cps=cps)
        
        narrative_context = _analyze_narrative_context(seg, storyboard=storyboard, shot_index=idx - 1)
        profile = _shot_profile(idx, narrative_context=narrative_context)
        
        audio_sync_info = _build_audio_sync_info(seg, shot_id, idx, duration_s)
        audio_desc = audio_sync_info.get("audio_desc", "")
        audio_markers = audio_sync_info.get("audio_markers", [])

        head_prompt = _build_frame_prompt(
            visual_desc=head_visual_desc or visual_desc,
            profile=profile,
            stage="head",
            style_preset=style_preset,
            style_prompt=style_prompt,
            ratio=ratio,
            entity_matches=entity_matches,
            dynamic=dynamic,
            narrative_context=narrative_context,
        )
        tail_prompt = _build_frame_prompt(
            visual_desc=tail_visual_desc or visual_desc,
            profile=profile,
            stage="tail",
            style_preset=style_preset,
            style_prompt=style_prompt,
            ratio=ratio,
            entity_matches=entity_matches,
            dynamic=dynamic,
            narrative_context=narrative_context,
        )
        motion_desc = _build_motion_desc(visual_desc=visual_desc, profile=profile, dynamic=dynamic)
        variation_type, variation_reason = _infer_variation_type(
            ff_desc=head_prompt,
            lf_desc=tail_prompt,
            ff_vis_char_ids=vis_chars,
            lf_vis_char_ids=vis_chars,
            state_before="",
            state_after="",
        )

        subject_x = _clamp_01(profile.get("subject_x"), default=0.5)
        subject_y = _clamp_01(profile.get("subject_y"), default=0.5)
        subshots = seg_obj.get("subshots") if isinstance(seg_obj.get("subshots"), list) else []
        storyboard.append(
            {
                "scene_id": "S1",
                "shot_id": shot_id,
                "desc": seg[:200],
                "duration_s": duration_s,
                # ShotSchemaV2 对齐字段（用于持久化与后续视频模型 prompt）
                "camera_index": idx,
                "cam_idx": idx,
                "visual_desc": visual_desc,
                "variation_type": variation_type,
                "variation_reason": variation_reason,
                "ff_desc": head_prompt,
                "lf_desc": tail_prompt,
                "motion_desc": motion_desc,
                "audio_desc": audio_desc,
                "audio_markers": audio_markers,
                "state_before": "",
                "state_after": "",
                "ff_vis_char_ids": vis_chars,
                "lf_vis_char_ids": vis_chars,
                "subshots": subshots,
                "head_frame": {
                    "prompt": head_prompt,
                    "ratio": normalize_frame_ratio(ratio),
                    "subject_pos": {"x": subject_x, "y": subject_y},
                },
                "tail_frame": {
                    "prompt": tail_prompt,
                    "ratio": normalize_frame_ratio(ratio),
                    "subject_pos": {"x": subject_x, "y": subject_y},
                },
            }
        )
    return storyboard


def _llm_storyboard(
    ctx: Any,
    *,
    source_text: str,
    style_preset: str,
    style_prompt: str,
    ratio: str,
    entities: Any,
    max_shots: Optional[int],
    safety_max_shots: int,
    min_shots_hint: int,
    hint_max_shots: int,
    target_total_s: Optional[float],
    uses_video_containers: bool,
    min_shot_s: float,
    max_shot_s: float,
    retry_reason: Optional[str],
    api_key: str,
    base_url: str,
    model: str,
    timeout_s: int,
    character_profiles: Optional[List[Dict[str, Any]]] = None,
    audio_markers: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    entities_text = _entities_summary(entities)
    ratio_norm = normalize_frame_ratio(ratio)
    hard_cap = int(max_shots) if isinstance(max_shots, int) and max_shots > 0 else int(max(1, int(safety_max_shots)))
    max_shots_line = f"- storyboard 数量 <= {hard_cap}\n"
    min_shots = max(0, int(min_shots_hint))
    min_shots_line = f"- storyboard 数量 >= {min_shots}\n" if min_shots > 0 else ""
    hint_max = max(0, int(hint_max_shots))
    hint_line = f"- 建议 storyboard 数量约 {min_shots}~{hint_max}\n" if (min_shots > 0 and hint_max > 0) else ""
    total_line = ""
    if target_total_s is not None and float(target_total_s) > 0.0:
        total_line = f"- 所有镜头 duration_s 之和约 {float(target_total_s):.1f} 秒（允许±20%）\n"
    duration_line = f"- duration_s 建议在 {float(min_shot_s):.1f}~{float(max_shot_s):.1f} 秒之间（可小数）\n"
    if uses_video_containers:
        duration_line = (
            "- duration_s 必须是 5/10/15 之一（对应 Wan2.7 单次视频生成容器时长），并且优先使用 15 秒以增强一致性。\n"
            "- 只有在以下情况才降级使用 10/5 秒：\n"
            "  - 需要引入新固定角色/新造型/新关键道具（需要先锁定外观）\n"
            "  - 明显场景/时间/光源逻辑切换（室内→室外、白天→夜晚等）\n"
            "  - 高风险大幅动作/高速运镜（更易漂移，缩短容器降低失败成本）\n"
        )

    character_profiles_text = ""
    if character_profiles and isinstance(character_profiles, list):
        character_profiles_text = "【角色档案】（用于通义万相2.6角色一致性）：\n"
        for profile in character_profiles:
            if isinstance(profile, dict):
                char_id = profile.get("character_id", "")
                name = profile.get("name", "")
                appearance = profile.get("appearance_description", "")
                personality = ", ".join(profile.get("personality_traits", []))
                voice_style = profile.get("voice_style", "natural")
                importance = profile.get("importance", "secondary")
                character_profiles_text += f"- {name}（{char_id}，{importance}）：{appearance}\n"
                if personality:
                    character_profiles_text += f"  性格：{personality}\n"
                if voice_style:
                    character_profiles_text += f"  声音风格：{voice_style}\n"
        character_profiles_text += "\n"

    audio_markers_text = ""
    if audio_markers and isinstance(audio_markers, list):
        audio_markers_text = "【音频标记】（用于通义万相2.6声画同步）：\n"
        for marker in audio_markers:
            if isinstance(marker, dict):
                marker_type = marker.get("marker_type", "")
                time_s = marker.get("time_s", 0)
                description = marker.get("description", "")
                character_name = marker.get("character_name", "")
                audio_markers_text += f"- {marker_type}（{time_s:.1f}秒）：{description}"
                if character_name:
                    audio_markers_text += f" - {character_name}"
                audio_markers_text += "\n"
        audio_markers_text += "\n"

    system = (
        "你是专业短剧/漫剧导演与分镜师，精通通义万相2.6视频生成技术。\n"
        "任务：把【剧本/章节文本】转换为可直接用于通义万相2.6生成分镜故事板。\n"
        "只输出严格 JSON（不要 Markdown/代码块/解释文字）。\n\n"
        "专业要求（针对通义万相2.6优化）：\n"
        "1. 镜头设计：根据场景内容选择合适的景别、角度和运镜方式，确保视觉表达准确\n"
        "2. 风格统一：所有镜头必须保持风格一致性，包括色彩、光影、质感、氛围\n"
        "3. 节奏控制：根据情节紧张程度调整镜头时长和运动强度\n"
        "4. 视觉连贯：确保相邻镜头之间构图、主体位置、光影的连贯性\n"
        "5. 细节丰富：描述要包含光照、氛围、质感等视觉细节\n"
        "6. 动作分解：动态场景要描述动作的起势、过程和结束\n"
        "7. 焦点明确：每个镜头都要有清晰的视觉焦点和构图意图\n"
        "8. 角色一致性：使用角色档案确保角色外观、服装、发型等在所有镜头中保持一致\n"
        "9. 多镜头叙事：合理运用不同景别和角度，增强叙事表现力\n"
        "10. 声画同步：根据音频标记设计镜头节奏和画面内容，确保声画同步"
    )

    subshots_schema_hint = ""
    multishot_requirements = ""
    if uses_video_containers:
        subshots_schema_hint = (
            '      "subshots": [\n'
            "        {\n"
            '          "start_s": 0,\n'
            '          "end_s": 3,\n'
            '          "transition": "hard_cut",\n'
            '          "shot_type": "wide_shot",\n'
            '          "camera_angle": "eye_level",\n'
            '          "camera_movement": "dolly_in",\n'
            '          "desc": "子分镜内容摘要（<=160字）",\n'
            '          "visual_desc": "画面要点（<=120字）"\n'
            "        }\n"
            "      ],\n"
        )
        multishot_requirements = (
            "- Wan2.7 多镜头叙事（单 prompt 多分镜）要求：\n"
            "  - 每个 storyboard 镜头是一个“视频容器”（duration_s=5/10/15），容器内部用 subshots 表达多个分镜。\n"
            "  - subshots 时间轴必须覆盖 [0, duration_s]，无重叠、无空洞，最后一个 end_s 必须等于 duration_s。\n"
            "  - 子分镜数量建议：5秒=2个，10秒=3个，15秒=4~6个；单个子分镜建议 2~5 秒。\n"
            "  - head_frame 必须对应第一个子分镜的开始画面；tail_frame 必须对应最后一个子分镜的结束画面。\n"
            "  - 若需要引入新固定角色/新造型/新关键道具，请新起一个 5/10 秒容器先锁定外观，再进入 15 秒连续容器。\n\n"
        )

    user = (
        "请输出如下 JSON 对象：\n"
        "{\n"
        '  "storyboard": [\n'
        "    {\n"
        '      "scene_id": "S1",\n'
        '      "shot_id": "S1-1",\n'
        '      "desc": "镜头内容摘要（<=200字）",\n'
        '      "duration_s": 3.0,\n'
        '      "cam_idx": 1,\n'
        '      "visual_desc": "画面要点（<=140字）",\n'
        '      "ff_desc": "首帧提示词（单格分镜 prompt：主体/环境/镜头构图/风格/可选动效）",\n'
        '      "lf_desc": "尾帧提示词（与首帧连续，保持主体与环境一致）",\n'
        '      "motion_desc": "运镜/动作/变化描述（用于图生视频）",\n'
        '      "audio_desc": "",\n'
        '      "ff_vis_char_ids": ["角色名1","角色名2"],\n'
        '      "lf_vis_char_ids": ["角色名1","角色名2"],\n'
        f"{subshots_schema_hint}"
        f'      "head_frame": {{"prompt":"...", "ratio":"{ratio_norm}", "subject_pos":{{"x":0.5,"y":0.5}}}},\n'
        f'      "tail_frame": {{"prompt":"...", "ratio":"{ratio_norm}", "subject_pos":{{"x":0.5,"y":0.5}}}}\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "硬性约束：\n"
        f"{max_shots_line}"
        f"{min_shots_line}"
        "- shot_id 必须唯一，按顺序递增（S1-1, S1-2 ...）\n"
        f"- head_frame/tail_frame 的 ratio 固定为 {ratio_norm}，subject_pos 的 x/y 必须在 0~1 之间\n"
        "- 首尾帧 prompt/head_frame.prompt/tail_frame.prompt 必须是“单格分镜”用的文生图提示词：\n"
        "  - 画面主体：角色/动作/表情（明确谁在做什么）\n"
        "  - 环境背景：场景/时段/氛围/光影（明确在哪里）\n"
        "  - 构图镜头：景别/角度/焦段/主体位置（可和 subject_pos 一致）\n"
        "  - 风格媒介：必须贯穿并与 style_prompt 一致\n"
        "  - 可选动效：仅在强动作镜头时使用（例如速度线/动感线/动态模糊），但不允许任何文字元素\n"
        "- 严禁生成任何文字：无对白、无拟声词、无字幕、无水印、无 logo、无边框、无拼贴、多格漫画页\n\n"
        f"{duration_line}"
        f"{hint_line}"
        f"{total_line}{multishot_requirements}"
        "- ff_vis_char_ids/lf_vis_char_ids：为首帧/尾帧可见人物名单（字符串数组），尽量从“已抽取实体-角色”中选取；没有人物则留空数组\n\n"
        f"风格预设：{style_preset}\n"
        f"风格（必须贯穿所有镜头）：{style_prompt}\n\n"
        + (f"【重试原因】上一次分镜不满足要求：{retry_reason}请显著提高拆分密度，保证总时长与镜头数达标。" + "\n\n" if retry_reason else "")
        + (f"已抽取实体（尽量在画面中体现一致性）：\n{entities_text}" + "\n\n" if entities_text else "")
        + character_profiles_text
        + audio_markers_text
        + "剧本/章节文本：\n"
        + f"{source_text[:12000]}"
    )

    user += (
        "\n\n补充输出字段（用于逻辑连续性与自动质检）：\n"
        "- state_before：本镜头开始时的关键状态（门开/关、人物站位、道具持有等），简短字符串\n"
        "- state_after：本镜头结束时的关键状态，简短字符串\n"
        "- variation_type：首尾画面变化幅度（small/medium/large）\n"
        "- variation_reason：选择该变化幅度的原因（简短说明）\n"
        "- shot_type：镜头类型（wide_shot/medium_shot/close_up/extreme_close_up等）\n"
        "- camera_angle：镜头角度（eye_level/high_angle/low_angle等）\n"
        "- camera_movement：镜头运动（static/pan/tilt/dolly/zoom等）\n"
        "- emotion：镜头情感氛围（neutral/happy/sad/tense/romantic等）\n"
        "- audio_sync：音频同步标记（用于声画同步，可选）\n"
        "- character_ids：本镜头涉及的角色ID列表（用于角色一致性，可选）\n"
        + ("- subshots：容器内子分镜数组（Wan2.7 视频场景），用于单提示词内时间戳分镜控制\n" if uses_video_containers else "")
        + '要求：state_before/state_after 尽量用"键=值；键=值"格式，长度控制在 80 字以内；若无明显变化可与上一镜头保持一致。\n'
    )

    with llm_stream_context(ctx, stage="storyboard", stream_key="storyboard") as on_chunk:
        content = chat_completions(
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            timeout_s=timeout_s,
            on_chunk=on_chunk,
        )
    obj = extract_json_object(content)
    items = obj.get("storyboard") if isinstance(obj, dict) else None
    if not isinstance(items, list) or not items:
        raise RuntimeError("invalid storyboard JSON: missing storyboard list")

    normalized: List[Dict[str, Any]] = []
    limit = int(max_shots) if isinstance(max_shots, int) and max_shots > 0 else int(max(1, int(safety_max_shots)))
    for idx, raw in enumerate(items[:limit], 1):
        if not isinstance(raw, dict):
            continue
        shot_id = str(raw.get("shot_id") or raw.get("shot_key") or f"S1-{idx}").strip() or f"S1-{idx}"
        scene_id = str(raw.get("scene_id") or "S1").strip() or "S1"
        desc = str(raw.get("desc") or raw.get("visual_desc") or "").strip()
        duration_s = raw.get("duration_s")
        try:
            duration = float(duration_s) if duration_s is not None else 3.0
        except Exception:  # noqa: BLE001
            duration = 3.0
        if duration <= 0.0:
            duration = 3.0
        cam_idx = raw.get("cam_idx") or raw.get("camera_index") or idx
        try:
            cam_idx_int = int(cam_idx)
        except Exception:  # noqa: BLE001
            cam_idx_int = idx

        visual_desc = str(raw.get("visual_desc") or desc or "").strip()[:140]
        ff_desc = str(raw.get("ff_desc") or "").strip()
        lf_desc = str(raw.get("lf_desc") or "").strip()

        head_prompt = ff_desc or visual_desc
        tail_prompt = lf_desc or (ff_desc or visual_desc)
        head = _normalize_frame_spec(raw.get("head_frame"), default_prompt=head_prompt, default_ratio=ratio_norm)
        tail = _normalize_frame_spec(raw.get("tail_frame"), default_prompt=tail_prompt, default_ratio=ratio_norm)

        motion_desc = str(raw.get("motion_desc") or "").strip()
        audio_desc = str(raw.get("audio_desc") or "").strip()
        state_before = str(raw.get("state_before") or "").replace("\n", " ").strip()
        state_after = str(raw.get("state_after") or "").replace("\n", " ").strip()
        if len(state_before) > 120:
            state_before = state_before[:120]
        if len(state_after) > 120:
            state_after = state_after[:120]

        variation_type_raw = raw.get("variation_type")
        variation_reason = str(raw.get("variation_reason") or "").replace("\n", " ").strip()
        if len(variation_reason) > 240:
            variation_reason = variation_reason[:240]

        def _norm_char_ids(value: Any) -> List[str]:
            if not isinstance(value, list):
                return []
            out: List[str] = []
            for item in value:
                if not isinstance(item, (str, int)):
                    continue
                name = str(item).strip()
                if not name or name in out:
                    continue
                out.append(name)
                if len(out) >= 8:
                    break
            return out

        ff_vis_char_ids = _norm_char_ids(raw.get("ff_vis_char_ids"))
        lf_vis_char_ids = _norm_char_ids(raw.get("lf_vis_char_ids"))

        profile = _shot_profile(cam_idx_int)
        dynamic = _detect_dynamic(" ".join([desc, visual_desc, ff_desc, lf_desc, motion_desc]))
        entity_matches = _match_entities_in_text(" ".join([desc, visual_desc]), entities)
        inferred_chars = [name for name, _d in (entity_matches.get("characters") or []) if name]
        if not ff_vis_char_ids:
            ff_vis_char_ids = inferred_chars
        if not lf_vis_char_ids:
            lf_vis_char_ids = inferred_chars

        def _need_rebuild(p: str) -> bool:
            s = str(p or "").strip()
            if not s:
                return True
            if len(s) < 20:
                return True
            if s == visual_desc.strip():
                return True
            return False

        head_p = str(head.get("prompt") or "").strip()
        tail_p = str(tail.get("prompt") or "").strip()
        if _need_rebuild(head_p):
            head_p = _build_frame_prompt(
                visual_desc=visual_desc,
                profile=profile,
                stage="head",
                style_preset=style_preset,
                style_prompt=style_prompt,
                ratio=ratio_norm,
                entity_matches=entity_matches,
                dynamic=dynamic,
            )
        else:
            head_p = _postprocess_frame_prompt(head_p, style_preset=style_preset, ratio=ratio_norm)
            if style_preset == "anime" and dynamic and "速度线" not in head_p and "动感线" not in head_p:
                head_p = f"{head_p}，漫画动效：速度线，动感线，轻微运动模糊（无文字）"
        if _need_rebuild(tail_p):
            tail_p = _build_frame_prompt(
                visual_desc=visual_desc,
                profile=profile,
                stage="tail",
                style_preset=style_preset,
                style_prompt=style_prompt,
                ratio=ratio_norm,
                entity_matches=entity_matches,
                dynamic=dynamic,
            )
        else:
            tail_p = _postprocess_frame_prompt(tail_p, style_preset=style_preset, ratio=ratio_norm)
            if style_preset == "anime" and dynamic and "速度线" not in tail_p and "动感线" not in tail_p:
                tail_p = f"{tail_p}，漫画动效：速度线，动感线，轻微运动模糊（无文字）"

        head["prompt"] = head_p
        tail["prompt"] = tail_p
        if not ff_desc:
            ff_desc = head_p
        if not lf_desc:
            lf_desc = tail_p
        if not motion_desc:
            motion_desc = _build_motion_desc(visual_desc=visual_desc, profile=profile, dynamic=dynamic)

        variation_type = _normalize_variation_type(variation_type_raw)
        inferred_type, inferred_reason = _infer_variation_type(
            ff_desc=ff_desc,
            lf_desc=lf_desc,
            ff_vis_char_ids=ff_vis_char_ids,
            lf_vis_char_ids=lf_vis_char_ids,
            state_before=state_before,
            state_after=state_after,
        )
        if not variation_type:
            variation_type = inferred_type
        if not variation_reason:
            variation_reason = inferred_reason

        shot_type = str(raw.get("shot_type") or "").strip()
        camera_angle = str(raw.get("camera_angle") or "").strip()
        camera_movement = str(raw.get("camera_movement") or "").strip()
        emotion = str(raw.get("emotion") or "").strip()
        audio_sync = str(raw.get("audio_sync") or "").strip()
        character_ids = raw.get("character_ids")
        if not isinstance(character_ids, list):
            character_ids = []
        subshots = _normalize_video_subshots(raw.get("subshots"), duration_s=duration) if uses_video_containers else []

        normalized.append(
            {
                "scene_id": scene_id,
                "shot_id": shot_id,
                "desc": desc[:200],
                "duration_s": duration,
                "cam_idx": cam_idx_int,
                "visual_desc": visual_desc,
                "variation_type": variation_type,
                "variation_reason": variation_reason,
                "ff_desc": ff_desc,
                "lf_desc": lf_desc,
                "motion_desc": motion_desc,
                "audio_desc": audio_desc,
                "state_before": state_before,
                "state_after": state_after,
                "ff_vis_char_ids": ff_vis_char_ids,
                "lf_vis_char_ids": lf_vis_char_ids,
                "subshots": subshots,
                "head_frame": head,
                "tail_frame": tail,
                "shot_type": shot_type,
                "camera_angle": camera_angle,
                "camera_movement": camera_movement,
                "emotion": emotion,
                "audio_sync": audio_sync,
                "character_ids": character_ids,
            }
        )

    if not normalized:
        raise RuntimeError("invalid storyboard JSON: empty normalized storyboard")
    return normalized


def run(ctx: Any) -> None:
    ensure_style_payload(ctx.payload)
    ensure_media_payload(ctx.payload)

    source_text = str(ctx.payload.get("script_text") or ctx.payload.get("source_text") or "")
    style_preset = str(ctx.payload.get("style_preset") or "")
    style_prompt = str(ctx.payload.get("style_prompt") or "")
    image_cfg = ctx.payload.get("image_config") if isinstance(ctx.payload.get("image_config"), dict) else {}
    ratio = str(image_cfg.get("ratio") or "")
    quality_mode = str(ctx.payload.get("quality_mode") or "").strip().lower()
    video_cfg = ctx.payload.get("video_config") if isinstance(ctx.payload.get("video_config"), dict) else {}
    video_engine = normalize_dreamweaver_video_engine(video_cfg.get("engine") or os.getenv("DREAMWEAVER_VIDEO_ENGINE") or "")
    uses_i2v_engine = is_dreamweaver_i2v_engine(video_engine)
    uses_t2v_engine = is_dreamweaver_t2v_engine(video_engine)
    uses_auto_engine = is_dreamweaver_auto_engine(video_engine)
    # Wan2.7 视频（I2V/T2V）通常需要将“镜头”量化为 5/10/15s 容器，并在单个 prompt 内用 subshots 表达多分镜。
    uses_video_containers = bool(uses_i2v_engine or uses_t2v_engine)
    engine_label = DREAMWEAVER_I2V_ENGINE if uses_i2v_engine else (DREAMWEAVER_T2V_ENGINE if uses_t2v_engine else "slideshow")
    if uses_auto_engine:
        uses_video_containers = True
        engine_label = DREAMWEAVER_AUTO_ENGINE

    enable_llm = env_flag("DREAMWEAVER_STORYBOARD_ENABLE_LLM", default=True)
    require_llm = env_flag("DREAMWEAVER_LLM_ONLY", default=False) or env_flag("DREAMWEAVER_STORYBOARD_REQUIRE_LLM", default=False)

    api_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
    base_url = (os.getenv("DASHSCOPE_API_BASE") or "https://dashscope.aliyuncs.com/compatible-mode/v1").strip()
    model = pick_model(primary_env="DREAMWEAVER_STORYBOARD_MODEL", fallback_env="DREAMWEAVER_SCRIPT_MODEL", default="qwen-plus")
    timeout_s = int(os.getenv("DREAMWEAVER_STORYBOARD_TIMEOUT", "180") or "180")
    max_shots_raw = _env_int("DREAMWEAVER_STORYBOARD_MAX_SHOTS", 0)
    safety_max_shots = _storyboard_safety_max_shots(quality_mode=quality_mode)
    if max_shots_raw > 0:
        max_shots = max(1, int(max_shots_raw))
        max_shots_mode = "fixed"
    elif max_shots_raw < 0:
        # 允许 LLM 自主决定分镜数量，但仍保留 safety 上限防止输出失控。
        max_shots = None
        max_shots_mode = "unbounded"
    else:
        max_shots = _auto_max_shots_from_script(script_text=source_text, quality_mode=quality_mode)
        max_shots_mode = "auto"

    can_llm = bool(enable_llm and api_key and base_url)
    if require_llm and not can_llm:
        raise RuntimeError("storyboard require LLM but DASHSCOPE_API_KEY/DASHSCOPE_API_BASE missing")

    min_shot_s = _env_float("DREAMWEAVER_STORYBOARD_MIN_SHOT_S", 5.0 if uses_video_containers else 3.0)
    max_shot_s = _env_float("DREAMWEAVER_STORYBOARD_MAX_SHOT_S", 15.0 if uses_video_containers else 10.0)
    if uses_video_containers:
        min_shot_s = max(5.0, float(min_shot_s))
        max_shot_s = min(15.0, float(max_shot_s))
        if max_shot_s < min_shot_s:
            max_shot_s = min_shot_s
        # Wan2.7 视频通常只支持离散时长（5/10/15s），min/max 也需要归一化，避免出现 7s 这类无法落地的配置。
        min_shot_s = normalize_dreamweaver_video_duration_s(min_shot_s, default=5.0)
        max_shot_s = normalize_dreamweaver_video_duration_s(max_shot_s, default=15.0)
        if max_shot_s < min_shot_s:
            max_shot_s = min_shot_s

    base_s = _env_float("DREAMWEAVER_STORYBOARD_BASE_S", 2.0)
    cps = _env_float("DREAMWEAVER_STORYBOARD_CHARS_PER_SECOND", 20.0)

    shot_cap = int(max_shots) if isinstance(max_shots, int) and max_shots > 0 else int(max(1, int(safety_max_shots)))
    targets = _auto_storyboard_targets(
        source_text=source_text,
        quality_mode=quality_mode,
        uses_video_containers=uses_video_containers,
        engine_label=engine_label,
        min_shot_s=float(min_shot_s),
        max_shot_s=float(max_shot_s),
        shot_cap=shot_cap,
    )

    mode = "rule"
    llm_error: str | None = None
    llm_warnings: List[str] = []
    rebalance: Dict[str, Any] = {"enabled": False}
    storyboard: List[Dict[str, Any]] = []

    def _postprocess(sb: List[Dict[str, Any]]) -> Dict[str, Any]:
        _auto_adjust_storyboard_durations(sb, min_s=min_shot_s, max_s=max_shot_s, base_s=base_s, cps=cps)
        if uses_video_containers:
            for item in sb:
                if not isinstance(item, dict):
                    continue
                item["duration_s"] = normalize_dreamweaver_video_duration_s(item.get("duration_s"), default=float(min_shot_s))
        rebalance = _rebalance_storyboard_total_duration(
            sb,
            target_total_s=targets.get("target_total_s") if targets.get("enabled") else None,
            min_s=min_shot_s,
            max_s=max_shot_s,
            uses_video_containers=uses_video_containers,
            engine_label=engine_label,
            tolerance=0.15,
        )
        if uses_video_containers:
            _ensure_video_subshots_for_storyboard(sb)
        return rebalance

    too_short = ""
    if can_llm:
        retries_default = 1 if quality_mode == "quality" else 0
        max_retries = max(0, _env_int("DREAMWEAVER_STORYBOARD_LLM_RETRIES", retries_default))
        retry_reason: Optional[str] = None
        for attempt in range(max_retries + 1):
            try:
                character_profiles = ctx.payload.get("character_profiles")
                audio_markers = ctx.payload.get("audio_markers")
                storyboard = _llm_storyboard(
                    ctx,
                    source_text=source_text,
                    style_preset=style_preset,
                    style_prompt=style_prompt,
                    ratio=ratio,
                    entities=ctx.payload.get("script_entities"),
                    max_shots=max_shots,
                    safety_max_shots=safety_max_shots,
                    min_shots_hint=int(targets.get("min_shots_hint") or 0),
                    hint_max_shots=int(targets.get("hint_max_shots") or 0),
                    target_total_s=targets.get("target_total_s"),
                    uses_video_containers=uses_video_containers,
                    min_shot_s=float(min_shot_s),
                    max_shot_s=float(max_shot_s),
                    retry_reason=retry_reason,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    timeout_s=timeout_s,
                    character_profiles=character_profiles,
                    audio_markers=audio_markers,
                )
                mode = "llm"
            except Exception as exc:  # noqa: BLE001
                llm_error = f"{exc.__class__.__name__}: {exc}"
                if require_llm:
                    raise RuntimeError(f"storyboard LLM failed: {exc}") from exc
                storyboard = []
                break

            rebalance = _postprocess(storyboard)
            too_short = _storyboard_too_short_reason(
                storyboard,
                min_shots_hint=int(targets.get("min_shots_hint") or 0),
                target_total_s=targets.get("target_total_s"),
                tolerance=0.2,
            )
            if too_short and attempt < max_retries:
                llm_warnings.append(f"storyboard too short: {too_short}")
                retry_reason = too_short
                continue
            if too_short:
                llm_warnings.append(f"storyboard too short: {too_short}")
            break

        if (not storyboard) or (too_short and not require_llm):
            storyboard = _build_rule_storyboard(
                source_text=source_text,
                style_preset=style_preset,
                style_prompt=style_prompt,
                ratio=ratio,
                entities=ctx.payload.get("script_entities"),
                max_segments=shot_cap,
                min_segments=int(targets.get("min_shots_hint") or 0),
                uses_video_containers=uses_video_containers,
            )
            mode = "llm_fallback" if mode == "llm" else "rule_fallback"
            rebalance = _postprocess(storyboard)
    else:
        storyboard = _build_rule_storyboard(
            source_text=source_text,
            style_preset=style_preset,
            style_prompt=style_prompt,
            ratio=ratio,
            entities=ctx.payload.get("script_entities"),
            max_segments=shot_cap,
            min_segments=int(targets.get("min_shots_hint") or 0),
            uses_video_containers=uses_video_containers,
        )
        mode = "rule"
        rebalance = _postprocess(storyboard)

    qc_cfg = ctx.payload.get("qc_config") if isinstance(ctx.payload.get("qc_config"), dict) else {}
    max_pos_delta = qc_cfg.get("max_subject_pos_delta")
    try:
        max_pos_delta_value = float(max_pos_delta) if max_pos_delta is not None else 0.1
    except Exception:  # noqa: BLE001
        max_pos_delta_value = 0.1
    _smooth_storyboard_subject_pos(storyboard, max_delta=max_pos_delta_value)
    ctx.payload["storyboard_subject_pos"] = {"mode": "smooth", "max_delta": max_pos_delta_value}

    camera_tree_mode = str(os.getenv("DREAMWEAVER_CAMERA_TREE_MODE", "heuristic") or "heuristic").strip().lower()
    camera_tree = build_camera_tree(storyboard if isinstance(storyboard, list) else [])
    camera_tree_generation: Dict[str, Any] = {"mode": "heuristic", "model": None, "error": None}
    if camera_tree_mode == "llm":
        if can_llm:
            try:
                llm_tree = build_camera_tree_llm(
                    storyboard if isinstance(storyboard, list) else [],
                    ctx=ctx,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    timeout_s=min(120, int(timeout_s)),
                    max_shots_per_camera=int(os.getenv("DREAMWEAVER_CAMERA_TREE_LLM_MAX_SHOTS_PER_CAMERA", "6") or "6"),
                )
                if llm_tree:
                    camera_tree = llm_tree
                    camera_tree_generation = {"mode": "llm", "model": model, "error": None}
            except Exception as exc:  # noqa: BLE001
                camera_tree_generation = {"mode": "heuristic_fallback", "model": model, "error": str(exc)}
        else:
            camera_tree_generation = {"mode": "heuristic_fallback", "model": None, "error": "LLM not available"}
    if camera_tree:
        ctx.payload["camera_tree"] = camera_tree
        ctx.payload["camera_tree_generation"] = camera_tree_generation

    camera_states = build_camera_states(storyboard if isinstance(storyboard, list) else [], camera_tree if camera_tree else None)
    if camera_states:
        ctx.payload["camera_states"] = camera_states

    ctx.payload["storyboard"] = storyboard
    ctx.payload["storyboard_generation"] = {
        "mode": mode,
        "model": model if str(mode).startswith("llm") else None,
        "llm_error": llm_error,
        "llm_warnings": llm_warnings,
        "max_shots": max_shots,
        "max_shots_mode": max_shots_mode,
        "safety_max_shots": safety_max_shots,
        "targets": targets,
        "duration_rebalance": rebalance,
    }
