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


