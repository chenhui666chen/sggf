from __future__ import annotations

from typing import Any, Dict, Optional


STYLE_PRESETS: Dict[str, Dict[str, str]] = {
    "cinematic_realistic": {
        "label": "电影写实",
        "prompt": "电影写实风格，专业电影质感，自然光照，真实光影，皮肤纹理细腻，材质质感真实，色彩自然饱满，景深效果明显，统一风格，高细节，8K超清",
    },
    "anime": {
        "label": "二次元动画",
        "prompt": "二次元动画风格，赛璐璐渲染，线条清晰流畅，色彩明快鲜艳，光影柔和统一，角色造型精致，背景细节丰富，统一画风，日式动画美学，高对比度边缘",
    },
    "ink_wash": {
        "label": "国风水墨",
        "prompt": "国风水墨风格，传统水墨技法，留白意境深远，宣纸质感自然，淡彩晕染层次丰富，笔触飘逸流畅，墨色浓淡相宜，东方美学意境，统一笔触，古典雅致",
    },
    "cyberpunk": {
        "label": "赛博朋克",
        "prompt": "赛博朋克风格，霓虹灯光绚丽，未来城市景观，高对比光影，冷色调主调，金属质感强烈，科技细节丰富，暗部细节保留，统一风格，电影级特效，8K超清",
    },
}

DEFAULT_STYLE_PRESET = "cinematic_realistic"
DEFAULT_STYLE_NEGATIVE_PROMPT = "文字,水印,logo,边框,拼贴,text,watermark,logo,border,collage"

STYLE_NEGATIVE_PROMPTS: Dict[str, str] = {
    "cinematic_realistic": (
        "二次元,动漫,卡通,插画,手绘,线稿,赛璐璐,低多边形,3d渲染," + DEFAULT_STYLE_NEGATIVE_PROMPT
    ),
    "anime": (
        "写实,照片,摄影,真实皮肤,毛孔,真人,电影质感,photorealistic," + DEFAULT_STYLE_NEGATIVE_PROMPT
    ),
    "ink_wash": (
        "写实,照片,动漫,卡通,3d渲染,油画厚涂,photorealistic," + DEFAULT_STYLE_NEGATIVE_PROMPT
    ),
    "cyberpunk": (
        "水墨,国风水墨,二次元,卡通,手绘线稿,低对比,photorealistic," + DEFAULT_STYLE_NEGATIVE_PROMPT
    ),
}


def normalize_style_preset(style_preset: Optional[str]) -> str:
    raw = (style_preset or "").strip()
    if raw in STYLE_PRESETS:
        return raw
    for key, meta in STYLE_PRESETS.items():
        if raw and raw == meta.get("label"):
            return key
    return DEFAULT_STYLE_PRESET


def style_prompt_for_preset(style_preset: Optional[str]) -> str:
    key = normalize_style_preset(style_preset)
    return STYLE_PRESETS.get(key, STYLE_PRESETS[DEFAULT_STYLE_PRESET])["prompt"]


def style_negative_prompt_for_preset(style_preset: Optional[str]) -> str:
    key = normalize_style_preset(style_preset)
    return STYLE_NEGATIVE_PROMPTS.get(key, DEFAULT_STYLE_NEGATIVE_PROMPT)


def ensure_style_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    确保 payload 内存在可用的 style_preset/style_prompt/style_negative_prompt（用于贯通素材库/分镜/首尾帧生成）。
    """
    raw_preset = payload.get("style_preset") if isinstance(payload.get("style_preset"), str) else None
    preset = normalize_style_preset(raw_preset)
    payload["style_preset"] = preset
    if not isinstance(payload.get("style_prompt"), str) or not payload.get("style_prompt").strip():
        payload["style_prompt"] = style_prompt_for_preset(preset)
    if not isinstance(payload.get("style_negative_prompt"), str) or not payload.get("style_negative_prompt").strip():
        payload["style_negative_prompt"] = style_negative_prompt_for_preset(preset)
    return payload
