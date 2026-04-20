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


