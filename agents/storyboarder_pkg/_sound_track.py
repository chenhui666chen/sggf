# -*- coding: utf-8 -*-
"""四轨声音策略（video_model_capability_watch O4，Phase 2 增量）。

逐镜决策四个声音轨道的来源（native 生成端 / post 后期）：
  ① 环境音/动作音效 → ambience_track：模型支持原生音频走生成端（帧级动作同步
     为后期不可替代优势），否则后期 SFX
  ② 人物对白（口型镜头）→ dialogue_track：模型支持音频参考 且 全部 speaker
     有参考音频 → 生成端音色参考（口型帧级同步）；否则后期 TTS
  ③ 旁白/画外音 → narration_track：恒后期 TTS（无口型约束，逐句情绪控制）
  ④ BGM → bgm_track：恒后期（原生 BGM 弱且混音差，业界共识）

决策为确定性知识编译（零 LLM）：模型能力来自 model_router 知识（native_audio /
voice_reference 结构化字段），参考音频来自 audiobook voice_reference_asset 池
（跨板块复用，provenance 由 backend 桥登记）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.storyboarder_pkg._knowledge import KNOWLEDGE_DIR

NARRATION_SPEAKERS = {"旁白", "narrator", "NARRATOR"}

# 模型家族能力兜底（model_router 知识缺失时使用；知识层为运行时权威）
FAMILY_CAPS_FALLBACK: Dict[str, Dict[str, bool]] = {
    "Seedance": {"native_audio": True, "voice_reference": True},
    "Kling": {"native_audio": True, "voice_reference": True},
    "Wan": {"native_audio": True, "voice_reference": True},
    "MiniMax": {"native_audio": True, "voice_reference": True},
    "PixVerse": {"native_audio": True, "voice_reference": False},
    "Vidu": {"native_audio": True, "voice_reference": False},
    "HappyHorse": {"native_audio": True, "voice_reference": False},
}

# engine / provider_model 字符串 → 模型家族（关键词匹配，未识别返回 ""）
_ENGINE_FAMILY_MARKS = (
    ("kling", "Kling"),
    ("seedance", "Seedance"),
    ("wan", "Wan"),
    ("vidu", "Vidu"),
    ("pixverse", "PixVerse"),
    ("hailuo", "MiniMax"),
    ("minimax", "MiniMax"),
    ("happyhorse", "HappyHorse"),
)

_CACHE: Dict[str, Any] = {}


def engine_to_family(engine: str) -> str:
    """引擎/模型名 → 模型家族（kling_omni→Kling、wan-i2v→Wan…；未知返回 ""）。"""
    text = str(engine or "").strip().lower()
    if not text:
        return ""
    for mark, family in _ENGINE_FAMILY_MARKS:
        if mark in text:
            return family
    return ""


def load_family_caps(family: str) -> Dict[str, bool]:
    """家族声音能力（native_audio / voice_reference）：model_router 知识优先，兜底常量。"""
    if family in _CACHE:
        return _CACHE[family]
    caps = dict(FAMILY_CAPS_FALLBACK.get(family, {"native_audio": False, "voice_reference": False}))
    try:
        router_path = KNOWLEDGE_DIR / "modules" / "model_router.json"
        if router_path.exists():
            with open(router_path, encoding="utf-8") as f:
                router = json.load(f)
            for entry in router.get("families", []):
                if isinstance(entry, dict) and str(entry.get("family") or "") == family:
                    native = entry.get("native_audio")
                    voice_ref = entry.get("voice_reference")
                    if isinstance(native, bool):
                        caps["native_audio"] = native
                    if isinstance(voice_ref, bool):
                        caps["voice_reference"] = voice_ref
                    break
    except (OSError, ValueError):
        pass  # 知识文件异常时用兜底常量（决策不阻断）
    _CACHE[family] = caps
    return caps


def _dialogue_speakers(contract: Dict[str, Any]) -> List[str]:
    """镜内角色台词 speaker（去重，保持顺序；旁白不计）。"""
    speakers: List[str] = []
    for d in contract.get("dialogue") or []:
        if not isinstance(d, dict):
            continue
        speaker = str(d.get("speaker") or "").strip()
        line = str(d.get("line") or "").strip()
        if line and speaker and speaker not in NARRATION_SPEAKERS and speaker not in speakers:
            speakers.append(speaker)
    return speakers


def _has_narration(contract: Dict[str, Any]) -> bool:
    for d in contract.get("dialogue") or []:
        if not isinstance(d, dict):
            continue
        line = str(d.get("line") or "").strip()
        speaker = str(d.get("speaker") or "").strip()
        if line and speaker in NARRATION_SPEAKERS:
            return True
    return False


def _ref_available(speaker: str, voice_refs: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(voice_refs, dict):
        return False
    ref = voice_refs.get(speaker)
    return isinstance(ref, dict) and bool(str(ref.get("storage_uri") or ref.get("audio_path") or "").strip())


def annotate_sound_tracks(
    contracts: List[Dict[str, Any]],
    *,
    engine: str,
    voice_refs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """逐镜注入 sound_track 四轨决策，返回统计报告。确定性，无 LLM。

    voice_refs：{speaker: {asset_id, storage_uri, ...}}（backend voice_reference_bridge 注入）。
    对白轨要求全部 speaker 有参考音频才走生成端（禁止同镜混两套人声来源）。
    """
    family = engine_to_family(engine)
    caps = load_family_caps(family)

    report = {
        "suite": "sound_track",
        "engine": str(engine or ""),
        "family": family,
        "native_audio": caps["native_audio"],
        "voice_reference": caps["voice_reference"],
        "shots_total": 0,
        "dialogue_native": 0,
        "dialogue_post_tts": 0,
        "narration_post_tts": 0,
        "ambience_native": 0,
        "ambience_post_sfx": 0,
        "lip_sync_sensitive": 0,
        "voice_ref_missing_speakers": [],
    }
    missing_speakers: List[str] = []

    for c in contracts:
        speakers = _dialogue_speakers(c)
        has_narration = _has_narration(c)

        # ② 对白轨：全部 speaker 参考音频可用且模型支持 → 生成端音色参考
        if speakers:
            all_refs = all(_ref_available(s, voice_refs) for s in speakers)
            if caps["native_audio"] and caps["voice_reference"] and all_refs:
                dialogue_track = "native_voice_ref"
                report["dialogue_native"] += 1
            else:
                dialogue_track = "post_tts"
                report["dialogue_post_tts"] += 1
                if caps["native_audio"] and caps["voice_reference"]:
                    for s in speakers:
                        if s not in missing_speakers:
                            missing_speakers.append(s)
        else:
            dialogue_track = None

        # ③ 旁白轨：恒后期
        narration_track = "post_tts" if has_narration else None
        if narration_track:
            report["narration_post_tts"] += 1

        # ① 环境音轨
        ambience_track = "native" if caps["native_audio"] else "post_sfx"
        if ambience_track == "native":
            report["ambience_native"] += 1
        else:
            report["ambience_post_sfx"] += 1

        if c.get("lip_sync_sensitive"):
            report["lip_sync_sensitive"] += 1

        c["sound_track"] = {
            "dialogue_track": dialogue_track,
            "narration_track": narration_track,
            "ambience_track": ambience_track,
            "bgm_track": "post",
            "lip_sync_sensitive": bool(c.get("lip_sync_sensitive")),
            "voice_ref_speakers": speakers if dialogue_track == "native_voice_ref" else [],
        }
        report["shots_total"] += 1

    report["voice_ref_missing_speakers"] = missing_speakers
    return report
