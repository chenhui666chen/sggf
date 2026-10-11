# -*- coding: utf-8 -*-
"""Shot Contract 引擎（Phase 2.3 核心）：beat → 12 字段 Contract（确定性、知识编译）。

路由链（对齐指导文档 2.3）：
  beat.family --T2--> dispatch DC ids（beat_family_routing）
  戏剧目的 --DC-035--> 运镜八映射（含约束：推拉≥3s / 快切禁复杂运镜 / 单一主导）
  戏剧目的 --DC-036--> 灯光八映射（低服从度 → 参考图标记）
  冲突动作族+接触交互 --DC-037--> keyframe_source=i2v_trajectory（迪士尼两阶段）
  beat.type/purpose + dialogue_coverage --> 五级景别（P1-P8 顺序模式）
  时长：对白预算（150wpm）→ clamp → 揭示后呼吸等待 ≥2s
  高价值族 --> R-pre 标记（10.6 candidate_selection_gate scope）
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from agents.storyboarder_pkg._knowledge import dispatch_dc_ids

# 五级景别（shot_size_system）与镜头档位（camera_tree 分组用 cam_idx）
SHOT_SIZES = ["LS", "FS", "MS", "CU", "ECU"]
SHOT_SIZE_ZH = {"LS": "远景", "FS": "全景", "MS": "中景", "CU": "近景", "ECU": "特写"}
SHOT_SIZE_LEVEL = {"LS": 0, "FS": 0, "MS": 1, "CU": 2, "ECU": 2}
SHOT_SIZE_LENS = {"LS": "24mm", "FS": "35mm", "MS": "50mm", "CU": "85mm", "ECU": "100mm"}
# 景别 → 主体位置（沿用旧模板的构图基准，供 head_frame.subject_pos）
SHOT_SIZE_POS = {
    "LS": (0.50, 0.65), "FS": (0.55, 0.62), "MS": (0.55, 0.58),
    "CU": (0.50, 0.45), "ECU": (0.50, 0.48),
}

# DC-035 运镜八映射：戏剧目的关键词 → (运镜, 模型语言, 服从度)
MOVEMENT_MAP: List[Tuple[List[str], str, str, str]] = [
    (["揭示", "首次亮相", "全貌", "展开"], "pull-back reveal 缓慢拉远",
     "slow dolly-out, camera gradually pulls back to reveal the space, very steady", "中"),
    (["压迫", "收紧", "逼近", "质问"], "slow push-in 缓慢推近",
     "slow dolly-in, camera gradually pushes toward the subject, very steady movement", "中"),
    (["不安", "潜伏", "危险", "窥视"], "unsettled drift 轻微漂移",
     "subtle slow drift, camera floats slightly unsettled", "中"),
    (["权力", "俯视", "仰视", "压制"], "升降机位", "", "低"),
    (["孤立", "失落", "吞没", "告别"], "缓慢拉远+主体占比缩小",
     "slow pull-out, subject becomes smaller in frame", "中"),
    (["主观", "失稳", "慌乱"], "handheld 手持(subtle)",
     "subtle natural handheld shaking, documentary feel", "中"),
    (["建置", "空间", "环境", "登场"], "establishing sweep 缓慢横移",
     "slow lateral sweep establishing the space", "中"),
]
LOCKED_OFF = ("locked-off 固定机位", "static camera, locked-off shot", "高")

# DC-036 灯光八映射：目的关键词 → (灯光方案, 服从度)
LIGHTING_MAP: List[Tuple[List[str], str, str]] = [
    (["对峙", "分裂", "摊牌"], "侧向硬光（伦勃朗式，明暗对比强，主体面向光源45°）", "中"),
    (["审问", "压迫", "威胁"], "顶光（眼窝阴影，配俯角机位）", "中"),
    (["温暖", "回忆", "安全", "拥抱"], "暖色窗光+柔光（大光源低对比）", "高"),
    (["秘密", "阴谋", "密谋"], "低调单源光（大面积黑）", "中"),
    (["虚伪", "体制", "冷漠"], "均匀平光（消除阴影）", "高"),
    (["崩塌", "揭露", "真相"], "光比拉大（fill 减少，阴影吞噬）", "低"),
    (["夜晚", "不安", "孤独"], "冷色月光/单点实用光源", "高"),
]
MOTIVATED_WINDOW = ("动机窗光（光源在场景内可见或可推断）", "高")

# R-pre 高价值族（10.6 candidate_selection_gate.scope）
R_PRE_FAMILIES = {"情绪爆发族", "信息揭示族", "冲突动作族"}
# 呼吸等待：关键揭示后保留 ≥2s（信息类镜头时长下限）
BREATH_WAIT_S = 2.0
WORDS_PER_SECOND = 2.5


def _count_words(line: str) -> int:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", line))
    latin = len(re.findall(r"[A-Za-z]+", line))
    return cjk + latin


def _match_map(text: str, mapping: List[Tuple[List[str], str, str]], default: Tuple[str, str]):
    for keywords, *value in mapping:
        if any(k in text for k in keywords):
            return tuple(value)
    return default


def pick_shot_size(
    *,
    beat: Dict[str, Any],
    scene_index: int,
    beat_index: int,
    beat_count: int,
) -> str:
    """五级景别选型：dialogue_coverage 五层 + shot_size_system P1-P8 顺序模式。"""
    family = str(beat.get("family") or "")
    btype = str(beat.get("type") or "")
    purpose = str(beat.get("shot_purpose") or "")
    dialogue = beat.get("dialogue") or []
    chars = beat.get("characters") or beat.get("scene_characters") or []

    # 开场建置族 / 场首 beat → P1 叙事流 LS/FS 起手
    if family == "开场建置族" or (beat_index == 0 and scene_index == 0):
        return "LS" if btype != "dialogue" else "FS"
    # 收尾定格族 → P4 渐进拉远收 MS/LS
    if family == "收尾定格族":
        return "MS" if beat_index < beat_count - 1 else "LS"
    # 信息揭示族 / reveal → Information Reveal：ECU/Insert
    if family == "信息揭示族" or btype == "reveal":
        return "ECU"
    # 冲突动作族 / action → DC-033：动作单元必须 CU/ECU/Insert
    if family == "冲突动作族" or btype == "action":
        return "CU"
    # 对白覆盖五层
    if btype == "reaction":
        return "CU"  # Listener Reaction
    if btype == "dialogue":
        if purpose == "建立关系" or len(chars) >= 2:
            return "FS"  # Relationship Shot 双人镜
        if dialogue:
            return "MS"  # Speaker Shot
        return "MS"
    # 情绪爆发族：场内渐进靠近 P3（MS→CU→ECU）
    if family == "情绪爆发族":
        progress = beat_index / max(1, beat_count - 1) if beat_count > 1 else 0.5
        return "CU" if progress < 0.6 else "ECU"
    # 默认 P1 叙事流中段
    return "MS"


def pick_movement(*, beat: Dict[str, Any], shot_size: str, duration_s: float, fast_cut: bool) -> Tuple[str, str, str]:
    """DC-035 运镜八映射 + 约束三条。返回 (中文运镜, 模型语言, 服从度)。"""
    text = " ".join([
        str(beat.get("description") or ""), str(beat.get("shot_purpose") or ""),
        str(beat.get("family") or ""),
    ])
    if fast_cut or duration_s < 1.5:
        return LOCKED_OFF  # 快切序列禁复杂运镜（节奏冲突）
    movement, model_lang, compliance = _match_map(text, MOVEMENT_MAP, LOCKED_OFF)
    # 约束：推/拉镜需 ≥3s 完成心理量变
    if ("push" in model_lang or "pull" in model_lang) and duration_s < 3.0:
        return LOCKED_OFF
    # ECU/固定特写让微表情发力（表演主导，运镜让位）
    if shot_size == "ECU" and movement == LOCKED_OFF[0]:
        pass
    return movement, model_lang, compliance


def pick_lighting(*, beat: Dict[str, Any]) -> Tuple[str, str]:
    """DC-036 灯光八映射。返回 (灯光方案, 服从度)。"""
    text = " ".join([
        str(beat.get("description") or ""), str(beat.get("shot_purpose") or ""),
        str(beat.get("family") or ""), str(beat.get("emotion") or ""),
    ])
    return _match_map(text, LIGHTING_MAP, MOTIVATED_WINDOW)


def _state_chain(action: str, description: str) -> Tuple[str, str]:
    """动作因果链 → (state_before, state_after)（State Engine 消费）。"""
    action = str(action or "").strip()
    if action and "→" in action:
        parts = [p.strip() for p in action.split("→") if p.strip()]
        if len(parts) >= 2:
            return parts[0], parts[-1]
        if parts:
            return "", parts[0]
    desc = str(description or "").strip()
    return "", desc[:60]


def _characters_for_beat(beat: Dict[str, Any], scene: Dict[str, Any]) -> List[str]:
    speakers = [str(d.get("speaker")) for d in beat.get("dialogue") or [] if isinstance(d, dict) and d.get("speaker")]
    if speakers:
        seen: List[str] = []
        for s in speakers:
            if s not in seen:
                seen.append(s)
        return seen
    return [str(c) for c in (scene.get("characters") or beat.get("characters") or [])]


def build_shot_contracts(
    *,
    script_document: Dict[str, Any],
    knowledge: Dict[str, Any],
    min_shot_s: float,
    max_shot_s: float,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """主入口：剧本 → Shot Contract 列表 + 统计报告。确定性，无 LLM。"""
    contracts: List[Dict[str, Any]] = []
    scenes = [s for s in script_document.get("scenes", []) if isinstance(s, dict)]
    shot_no = 0

    for scene_index, scene in enumerate(scenes, start=1):
        scene_id = str(scene.get("scene_id") or f"S{scene_index}")
        beats = [b for b in scene.get("beats", []) if isinstance(b, dict)]
        prev_state_after = ""
        for beat_index, beat in enumerate(beats):
            shot_no += 1
            family = str(beat.get("family") or "")
            shot_size = pick_shot_size(
                beat=beat, scene_index=scene_index, beat_index=beat_index, beat_count=len(beats),
            )
            dialogue = beat.get("dialogue") or []
            words = sum(_count_words(str(d.get("line") or "")) for d in dialogue if isinstance(d, dict))

            # 时长：hint → 对白预算 → clamp → 呼吸等待
            try:
                duration_s = float(beat.get("duration_hint_s") or 0)
            except (TypeError, ValueError):
                duration_s = 0.0
            if words > 0:
                duration_s = max(duration_s, words / WORDS_PER_SECOND)
            if family == "信息揭示族" or str(beat.get("type")) == "reveal":
                duration_s += BREATH_WAIT_S  # 揭示后呼吸等待（观众吸收时间不可省）
            duration_s = max(min_shot_s, min(max_shot_s, duration_s if duration_s > 0 else min_shot_s))
            duration_s = round(duration_s, 1)

            fast_cut = beat_index > 0 and duration_s < 1.5
            movement, movement_model, movement_compliance = pick_movement(
                beat=beat, shot_size=shot_size, duration_s=duration_s, fast_cut=fast_cut,
            )
            lighting, lighting_compliance = pick_lighting(beat=beat)
            state_before, state_after = _state_chain(beat.get("action"), beat.get("description"))
            if prev_state_after and not state_before:
                state_before = prev_state_after  # 状态链衔接：上镜结束态 = 本镜开始态

            # DC-037 关键帧来源分叉：冲突动作族 + 接触交互 → 两阶段法
            action = str(beat.get("action") or "")
            keyframe_source = "t2i_direct"
            if family == "冲突动作族" and ("→" in action or str(beat.get("type")) == "action"):
                keyframe_source = "i2v_trajectory"

            # 主导技巧（单一主导原则：运镜 or 灯光 or 表演）
            if movement != LOCKED_OFF[0]:
                technique = "camera_movement"
            elif lighting_compliance == "低":
                technique = "lighting"
            else:
                technique = "performance"

            contract = {
                # 12 核心字段（镜头卡）
                "shot_id": f"shot_{shot_no:03d}",
                "scene_id": scene_id,
                "beat_id": str(beat.get("beat_id") or f"{scene_id}-B{beat_index + 1}"),
                "shot_size": shot_size,
                "shot_size_zh": SHOT_SIZE_ZH[shot_size],
                "camera_angle": "平视" if shot_size in ("MS", "FS", "LS") else (
                    "微仰视" if family == "冲突动作族" else "平视"
                ),
                "camera_movement": movement,
                "lighting": lighting,
                "duration_s": duration_s,
                "action": action,
                "dialogue": dialogue,
                "visual_anchor": str(beat.get("visual_anchor") or beat.get("description") or ""),
                "technique": technique,
                # 路由与治理元数据
                "family": family,
                "dispatch_dc_ids": dispatch_dc_ids(family, knowledge),
                "shot_purpose": str(beat.get("shot_purpose") or ""),
                "keyframe_source": keyframe_source,
                "state_before": state_before,
                "state_after": state_after,
                "r_pre_eligible": family in R_PRE_FAMILIES,
                "movement_model_lang": movement_model,
                "movement_compliance": movement_compliance,
                "lighting_compliance": lighting_compliance,
                "reference_image_required": lighting_compliance == "低" or movement_compliance == "低",
                "characters": _characters_for_beat(beat, scene),
                "emotion": str(
                    (dialogue[0].get("emotion") if dialogue and isinstance(dialogue[0], dict) else "")
                    or beat.get("emotion") or "neutral"
                ),
            }
            contracts.append(contract)
            prev_state_after = state_after or str(beat.get("description") or "")[:60]

    report = {
        "total_contracts": len(contracts),
        "r_pre_eligible": sum(1 for c in contracts if c["r_pre_eligible"]),
        "i2v_trajectory_shots": sum(1 for c in contracts if c["keyframe_source"] == "i2v_trajectory"),
        "reference_image_shots": sum(1 for c in contracts if c["reference_image_required"]),
        "families_used": sorted({c["family"] for c in contracts if c["family"]}),
        "total_duration_s": round(sum(c["duration_s"] for c in contracts), 1),
    }
    return contracts, report
