# -*- coding: utf-8 -*-
"""请求意图三级仲裁：显式 mode → 素材结构规则 → 歧义时决策模型（保守兜底）。

原则（见 docs/VIDEO_API_SMART_ROUTING_GUIDE.md）：
- 素材是用户实际上传的意图证据，结构可确定时绝不调模型（省延迟/费用/故障点）；
- 唯一结构性歧义是"恰好 2 张图"：首尾帧强约束或双图参考，交由可注入的
  决策模型返回离散类别与置信度；分类器缺失/故障/低置信一律保守按
  多图参考处理，保证素材不丢失、主链路不被辅助模型阻断；
- 显式 mode 永远第一优先，但必须与素材结构一致，矛盾按客户端错误拒绝。

事实收紧（2026-10-12 三家工作流台账）：AutoDL/Grsai/算力AI 均无"单首帧"
工作流，首尾帧必须恰好 2 张，因此 1 张图不存在首帧/参考歧义。

第六模式（2026-10-13 wan3 多参台账）：图/视/音任意混合的叙事融合归
mixed_multimodal——wan3 工作流 10图5视5音、10图5音、图+视+音均有付费实证，
落不进任何单一素材模式。自动仲裁下仅"恰好 1 图 1 音无视频"保留为对口型；
显式 mode 第一优先的规则不变。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from . import Mode


class IntentError(ValueError):
    """显式模式与素材结构矛盾，或素材组合本身非法（应转为 4xx）。"""


@dataclass(frozen=True)
class ModeDecision:
    mode: Mode
    confidence: float  # 0.0-1.0


@dataclass(frozen=True)
class ResolvedIntent:
    mode: Mode
    source: str  # explicit / rule / classifier / fallback
    confidence: Optional[float] = None


class IntentClassifier(Protocol):
    """决策模型端口：仅在结构歧义时调用，返回离散模式与置信度。"""

    def classify_mode(self, prompt: str, *, image_count: int,
                      candidates: tuple[Mode, ...]) -> ModeDecision:
        ...


# 歧义候选与保守默认：多图参考槽位能容纳 2 张图，绝不会丢素材
_AMBIGUOUS_CANDIDATES = (Mode.FIRST_LAST_FRAME, Mode.MULTI_IMAGE)
_FALLBACK_ON_AMBIGUITY = Mode.MULTI_IMAGE


def _coerce_mode(value) -> Mode:
    if isinstance(value, Mode):
        return value
    try:
        return Mode(str(value))
    except ValueError:
        raise IntentError(f"unknown_mode: {value!r}")


def _validate(mode: Mode, *, images: int, videos: int, audios: int) -> None:
    """校验已确定模式与素材结构一致；不一致属于请求方错误。"""
    if mode is Mode.TEXT:
        if images or videos or audios:
            raise IntentError("mode 'text' 与携带的素材矛盾：文生不能携带素材")
    if mode is Mode.FIRST_LAST_FRAME:
        if images != 2 or videos or audios:
            raise IntentError(
                "mode 'first_last_frame' 需要恰好 2 张图（首帧+尾帧）且无视频/音频")
    if mode is Mode.MULTI_IMAGE:
        if images < 1 or videos or audios:
            raise IntentError(
                "mode 'multi_image' 需要 1 张及以上参考图且无视频/音频")
    if mode is Mode.VIDEO_REFERENCE:
        if videos < 1 or audios:
            raise IntentError(
                "mode 'video_reference' 需要至少 1 个参考视频且无音频")
    if mode is Mode.IMAGE_AUDIO_LIPSYNC:
        if images != 1 or audios != 1 or videos:
            raise IntentError(
                "mode 'image_audio_lipsync' 需要至少 1 张图与 1 段音频且无视频")
    if mode is Mode.MIXED_MULTIMODAL:
        if images + videos + audios < 1:
            raise IntentError(
                "mode 'mixed_multimodal' 需要至少 1 个参考素材（图/视频/音频）")


def resolve_mode(*, prompt: str, image_count: int, video_count: int,
                 audio_count: int, explicit=None,
                 classifier: Optional[IntentClassifier] = None,
                 confidence_threshold: float = 0.6) -> ResolvedIntent:
    if explicit is not None:
        mode = _coerce_mode(explicit)
        _validate(mode, images=image_count, videos=video_count, audios=audio_count)
        return ResolvedIntent(mode=mode, source="explicit")

    # 音频必须伴随参考图或参考视频：纯音频没有对应工作流
    if audio_count > 0 and image_count == 0 and video_count == 0:
        raise IntentError(
            "audio_without_visual: 携带音频但无参考图/视频，"
            "多素材混合请提供至少 1 个视觉参考")

    if audio_count > 0:
        # 唯一的对口型结构：恰好 1 图 1 音、无视频；
        # 多图/多音/带视频均为多素材叙事融合（wan3 全槽位实证）
        if (video_count == 0 and image_count == 1 and audio_count == 1):
            mode = Mode.IMAGE_AUDIO_LIPSYNC
        else:
            mode = Mode.MIXED_MULTIMODAL
    elif video_count > 0:
        mode = Mode.VIDEO_REFERENCE
    elif image_count == 2:
        return _resolve_ambiguous(prompt, image_count, classifier,
                                  confidence_threshold)
    elif image_count >= 1:
        mode = Mode.MULTI_IMAGE
    else:
        mode = Mode.TEXT

    _validate(mode, images=image_count, videos=video_count, audios=audio_count)
    return ResolvedIntent(mode=mode, source="rule")


def _resolve_ambiguous(prompt: str, image_count: int,
                       classifier: Optional[IntentClassifier],
                       threshold: float) -> ResolvedIntent:
    if classifier is None:
        return ResolvedIntent(mode=_FALLBACK_ON_AMBIGUITY, source="fallback")
    try:
        decision = classifier.classify_mode(
            prompt, image_count=image_count, candidates=_AMBIGUOUS_CANDIDATES)
    except Exception:
        # 辅助模型故障不得阻断主链路
        return ResolvedIntent(mode=_FALLBACK_ON_AMBIGUITY, source="fallback")
    if (decision.mode in _AMBIGUOUS_CANDIDATES
            and decision.confidence >= threshold):
        return ResolvedIntent(mode=decision.mode, source="classifier",
                              confidence=decision.confidence)
    return ResolvedIntent(mode=_FALLBACK_ON_AMBIGUITY, source="fallback",
                          confidence=decision.confidence)
