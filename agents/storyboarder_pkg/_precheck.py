# -*- coding: utf-8 -*-
"""T3 预检套件（Phase 2.3）：Contract 生成后、storyboard 输出前的构造性错误拦截。

四类检查（technique_interference_check + video_model_capability_watch O4）：
  1. 光学一致性：景别×焦距矛盾（特写×广角 → 修复为景别配套焦距）
  2. 技巧干涉：主动技巧 ≤2/镜、主导 =1、快切×复杂运镜、运镜时长约束
  3. CF 触发器：EMOTION_STALL（>6s 情绪场景无增量）等 16 条中可代码判定项
  4. 口型敏感标记：角色对白镜头 → lip_sync_sensitive（特写×口型 → 风险提示，
     不自动改景别——生成端音色参考路线可保留特写，后期 TTS 路线人工门裁决）

修复动作（internal_motion_priority / DC-035 约束）：
  低服从度运镜 → 降级固定机位+画面内动态；超预算技巧 → 删除支持位技巧；
  超时长 → clamp；EMOTION_STALL → trim 到 6s。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from agents.storyboarder_pkg._contract import (
    LOCKED_OFF,
    SHOT_SIZE_LENS,
    WORDS_PER_SECOND,
    _count_words,
)

EMOTION_FAMILIES = {"情绪爆发族", "关系状态族"}
EMOTION_STALL_MAX_S = 6.0
COMPLEX_MOVEMENT_MARKS = ("crane", "sweep", "dolly", "pull", "handheld", "升降", "横移")
# 口型敏感景别：紧凑特写下任何口型误差立现（Leyline 口型规避守则）
LIP_SYNC_RISK_SIZES = ("CU", "ECU")


def _is_complex(movement: str) -> bool:
    return any(m in movement for m in COMPLEX_MOVEMENT_MARKS)


def _has_character_dialogue(contract: Dict[str, Any]) -> bool:
    """口型镜头判定：存在非旁白 speaker 的台词（旁白走后期轨，无口型）。"""
    for d in contract.get("dialogue") or []:
        if not isinstance(d, dict):
            continue
        speaker = str(d.get("speaker") or "").strip()
        line = str(d.get("line") or "").strip()
        if line and speaker and speaker not in ("旁白", "narrator", "NARRATOR"):
            return True
    return False


def precheck_contracts(contracts: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """逐镜预检 + 自动修复。返回 (contracts, precheck_report)。"""
    issues: List[Dict[str, str]] = []
    fixes: List[Dict[str, str]] = []

    for i, c in enumerate(contracts):
        # ---- 1. 光学一致性：显式覆盖的 lens 与景别矛盾（特写×广角）----
        # 确定性引擎的 lens 由景别配套生成（SHOT_SIZE_LENS），永不矛盾；
        # 本检查拦截外部（LLM/人工）显式覆盖 lens 造成的矛盾。
        explicit_lens = str(c.get("lens") or "").strip()
        lens = explicit_lens or SHOT_SIZE_LENS.get(c.get("shot_size", "MS"), "50mm")
        c["lens"] = lens
        if c.get("shot_size") in ("CU", "ECU") and lens in ("16mm", "24mm", "35mm"):
            fixes.append({"shot_id": c["shot_id"], "type": "optical", "detail": f"{c['shot_size']}×{lens} 焦距修正为 {SHOT_SIZE_LENS['CU']}"})
            c["lens"] = SHOT_SIZE_LENS["CU"]
            issues.append({"shot_id": c["shot_id"], "type": "optical_consistency", "detail": "特写×广角矛盾（已修复焦距）"})

        # ---- 2. 技巧干涉 ----
        active = []
        if c.get("camera_movement") and c["camera_movement"] != LOCKED_OFF[0]:
            active.append("movement")
        if c.get("lighting_compliance") == "中":
            active.append("lighting_styling")
        if c.get("dialogue"):
            active.append("performance")
        if len(active) > 2:
            # 过载：删除支持位（保留主导）
            if "movement" in active and c.get("technique") != "camera_movement":
                fixes.append({"shot_id": c["shot_id"], "type": "interference", "detail": f"技巧过载({len(active)})→运镜降级固定"})
                c["camera_movement"], c["movement_model_lang"], c["movement_compliance"] = LOCKED_OFF
                c["technique"] = "performance"
                active.remove("movement")
                issues.append({"shot_id": c["shot_id"], "type": "technique_interference", "detail": f"主动技巧 {len(active)+1}>2（已降级运镜）"})

        # 快切×复杂运镜（节奏冲突）
        if c.get("duration_s", 0) < 1.5 and _is_complex(str(c.get("camera_movement") or "")):
            fixes.append({"shot_id": c["shot_id"], "type": "interference", "detail": "快切×复杂运镜→固定机位+画面内动态"})
            c["camera_movement"], c["movement_model_lang"], c["movement_compliance"] = LOCKED_OFF
            c["internal_motion"] = True  # internal_motion_priority：固定镜头注入画面内动态
            issues.append({"shot_id": c["shot_id"], "type": "technique_interference", "detail": "快切×复杂运镜节奏冲突（已降级内运动）"})

        # 推拉时长约束
        if ("推近" in str(c.get("camera_movement")) or "拉远" in str(c.get("camera_movement"))) and c.get("duration_s", 0) < 3.0:
            fixes.append({"shot_id": c["shot_id"], "type": "interference", "detail": "推拉<3s→固定机位"})
            c["camera_movement"], c["movement_model_lang"], c["movement_compliance"] = LOCKED_OFF
            issues.append({"shot_id": c["shot_id"], "type": "technique_interference", "detail": "推/拉镜 <3s 无法完成心理量变（已降级）"})

        # ---- 3. CF 触发器（可代码判定项） ----
        # EMOTION_STALL_CHECK（CF-088）：>6s 情绪场景无情绪增量
        family = str(c.get("family") or "")
        has_emotion_increment = bool(c.get("dialogue")) or bool(c.get("action")) or str(c.get("emotion")) not in ("", "neutral")
        if c.get("duration_s", 0) > EMOTION_STALL_MAX_S and family in EMOTION_FAMILIES and not has_emotion_increment:
            fixes.append({"shot_id": c["shot_id"], "type": "emotion_stall", "detail": f"{c['duration_s']}s→trim {EMOTION_STALL_MAX_S}s（无情绪增量）"})
            c["duration_s"] = EMOTION_STALL_MAX_S
            issues.append({"shot_id": c["shot_id"], "type": "emotion_stall", "detail": "情绪场景 >6s 无增量（CF-088，已 trim）"})

        # 对白预算：词数 vs 时长偏差 >40%（信息提示，不自动改）
        words = sum(_count_words(str(d.get("line") or "")) for d in c.get("dialogue") or [] if isinstance(d, dict))
        if words > 0 and c.get("duration_s", 0) > 0:
            expected = c["duration_s"] * WORDS_PER_SECOND
            if abs(words - expected) / expected > 0.4:
                issues.append({"shot_id": c["shot_id"], "type": "dialogue_budget", "detail": f"对白 {words} 词 vs 预算 {expected:.0f} 词（偏差>40%，提示给人工门）"})

        # ---- 4. 口型敏感标记（video_model_capability_watch O4）----
        # 角色对白镜头 → lip_sync_sensitive（供 model_router 路由与 sound_track 决策消费）；
        # 特写×口型 → 风险提示，不自动改景别（生成端音色参考路线可保留特写）。
        lip_sensitive = _has_character_dialogue(c)
        c["lip_sync_sensitive"] = lip_sensitive
        if lip_sensitive and c.get("shot_size") in LIP_SYNC_RISK_SIZES:
            issues.append({
                "shot_id": c["shot_id"], "type": "lip_sync_closeup",
                "detail": (
                    f"{c.get('shot_size')}×角色对白：紧凑特写口型误差立现"
                    "（生成端音色参考路线可保留；后期 TTS 路线建议放宽景别或过肩/反应镜头，人工门裁决）"
                ),
            })

        c["active_techniques"] = active

    lip_sync_count = sum(1 for c in contracts if c.get("lip_sync_sensitive"))
    report = {
        "suite": "t3_precheck",
        "checked": len(contracts),
        "issues_total": len(issues),
        "auto_fixed": len(fixes),
        "issues": issues[:30],
        "fixes": fixes[:30],
        "issue_types": sorted({i["type"] for i in issues}),
        "lip_sync_sensitive": lip_sync_count,
    }
    return contracts, report
