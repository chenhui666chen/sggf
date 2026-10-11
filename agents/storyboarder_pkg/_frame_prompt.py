# -*- coding: utf-8 -*-
"""Contract 驱动的帧 prompt 编译器（重写自旧拼接式 _frame_prompt）。

与旧版差异（指导文档 F.3）：
  - 输入是 Shot Contract（12 字段 + 路由元数据），不再是硬编码 profile 模板
  - 运镜走 camera_lighting_prompt_lexicon 翻译（模型语言 + 服从度量化词），
    低服从项带 reference_image_required 标记（生成侧走参考图而非文字）
  - head/tail 差异由 state_transition 驱动（state_before/state_after），
    不再只差一句 stage_tag
  - 光学一致性：lens 由景别配套（T3 预检已修正）
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from pipeline.media_presets import normalize_frame_ratio

from agents.storyboarder_pkg._contract import SHOT_SIZE_ZH

_DEFAULT_STYLE = "写实风格，电影质感，光影真实，高清细节，统一风格"


def build_frame_prompt(
    *,
    contract: Dict[str, Any],
    stage: str,
    style_preset: str,
    style_prompt: str,
    ratio: str,
    entity_matches: Dict[str, List[Tuple[str, str]]],
    scene_meta: Optional[Dict[str, Any]] = None,
) -> str:
    """编译单帧 prompt。stage ∈ {"head", "tail"}。

    entity_matches: {"characters": [(name, desc)...], "scenes": [...], "props": [...]}
    scene_meta: {"location", "time_of_day", "interior"} 场景上下文
    """
    style = (style_prompt or "").strip() or _DEFAULT_STYLE
    scene_meta = scene_meta or {}

    shot_size = contract.get("shot_size", "MS")
    camera = f"{SHOT_SIZE_ZH.get(shot_size, '中景')}（{contract.get('lens', '50mm')}）"
    angle = str(contract.get("camera_angle") or "平视")
    composition = str(contract.get("visual_anchor") or "三分法构图，主体清晰")
    movement_model = str(contract.get("movement_model_lang") or "").strip()
    movement = str(contract.get("camera_movement") or "固定机位")
    lighting = str(contract.get("lighting") or "动机窗光")

    # state_transition 驱动的 head/tail 差异（替代旧 stage_tag 单句差异）
    if stage == "head":
        state_desc = str(contract.get("state_before") or "").strip()
        stage_tag = "镜头开始，动作起势，主体清晰，焦点明确"
    else:
        state_desc = str(contract.get("state_after") or "").strip()
        stage_tag = "镜头结束，动作落定，保持风格与构图一致，焦点稳定"
    if state_desc:
        stage_tag = f"{stage_tag}，画面状态：{state_desc}"

    # 画面内动态（internal_motion_priority：固定机位时的信息增量）
    internal_motion = ""
    if contract.get("camera_movement") == "locked-off 固定机位":
        internal_motion = "画面内动态：主体微动作与光影呼吸"

    # 低服从度 → 参考图路径标记（生成侧消费，文字不再强写）
    reference_note = ""
    if contract.get("reference_image_required"):
        reference_note = "（低服从度项以参考图实现为准）"

    chars_text = _format_items(entity_matches.get("characters") or [], 36)
    scenes_text = _format_items(entity_matches.get("scenes") or [], 48)
    props_text = _format_items(entity_matches.get("props") or [], 36)

    atmosphere = _atmosphere(scene_meta, contract)
    action_text = str(contract.get("action") or "").strip()

    # 图片层补强（2026-10-07）：摄影域知识驱动的帧 prompt 增强
    lens_comp = _lens_compensation(contract.get("lens", "50mm"))  # 焦距×距离×透视补偿
    separation = _separation_hint(shot_size)  # 主体分离（I2V 防漂移）
    texture = _texture_hint(style_preset)  # 质感 + 瑕疵美学（按风格启用）

    parts = [
        "单格分镜",
        normalize_frame_ratio(ratio),
        style,
        f"{camera}，{angle}",
        composition,
        lens_comp,
        separation,
        f"运镜：{movement}{reference_note}" if movement else "",
        f"运镜模型语言：{movement_model}{reference_note}" if movement_model else "",
        internal_motion,
        f"光照：{lighting}",
        f"氛围：{atmosphere}",
        texture,
        f"画面要点：{contract.get('visual_anchor') or contract.get('action') or ''}",
        f"动作：{action_text}" if action_text else "",
        f"角色：{chars_text}" if chars_text else "",
        f"环境：{scenes_text}" if scenes_text else "",
        f"道具：{props_text}" if props_text else "",
        stage_tag,
        "无文字，无水印，无logo，无边框，无拼贴",
    ]
    return "，".join([p for p in parts if p])


def _lens_compensation(lens: str) -> str:
    """焦距×距离×透视补偿（lens_camera_distance_perspective）：AI 无真实镜头，显式写几何特征。"""
    try:
        mm = int("".join(ch for ch in str(lens) if ch.isdigit()) or 50)
    except ValueError:
        mm = 50
    if mm <= 28:
        return "广角透视：camera very close to subject，前景放大，近大远小明显，背景纵深延伸"
    if mm >= 100:
        return "长焦压缩：camera far from subject，窄视野，背景层向主体视觉压缩，远距观察式取景"
    return ""


def _separation_hint(shot_size: str) -> str:
    """主体分离提示（subject_separation + i2v_frame_quality_protocol）：I2V 防漂移硬指标。"""
    if shot_size in ("CU", "ECU"):
        return "主体占比≥30%画面，与背景清晰分离，浅景深背景虚化"
    return "主体与背景清晰分离，避免杂乱背景"


def _texture_hint(style_preset: str = "") -> str:
    """帧端质感（texture_boost L4 + imperfection_aesthetics）。

    L2 瑕疵基础词汇全风格启用（对抗 AI 油腻感：皮肤抹平/过度完美）；
    L4 烂镜头模拟仅纪实/复古/胶片风启用（activation_rule）。
    """
    base = "质感：材质纹理清晰，自然光影层次，真实皮肤与布料质感，raw photo 原图质感，皮肤纹理与毛孔可见，film grain 胶片颗粒"
    preset = str(style_preset or "").lower()
    imperfect_styles = ("documentary", "film_noir", "retro", "90s", "wong", "纪实", "复古", "胶片", " noir")
    if any(s in preset for s in imperfect_styles):
        base += "，轻度暗角与边缘色散，轻微动态模糊"
    return base


def _format_items(items: List[Tuple[str, str]], max_desc: int) -> str:
    out = []
    for name, desc in items[:4]:
        if desc:
            out.append(f"{name}（{desc[:max_desc]}）")
        else:
            out.append(name)
    return "；".join(out)


def _atmosphere(scene_meta: Dict[str, Any], contract: Dict[str, Any]) -> str:
    tod = str(scene_meta.get("time_of_day") or "")
    interior = str(scene_meta.get("interior") or "")
    emotion = str(contract.get("emotion") or "neutral")
    base = f"{tod}{'·' + interior if interior else ''}".strip("·")
    emotion_zh = {
        "neutral": "平静", "happy": "明快", "sad": "低沉", "angry": "紧绷",
        "fearful": "不安", "surprised": "骤停", "tense": "紧张", "calm": "温和", "excited": "高扬",
    }.get(emotion, "")
    return "，".join(x for x in (base, emotion_zh) if x) or "生活质感"
