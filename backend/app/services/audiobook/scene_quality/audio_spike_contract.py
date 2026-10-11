"""离线音频对照实验的标准语料与缺陷评测合同；不生成或调用音频。"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class CorpusCase:
    case_id: str
    mode: str
    text: str
    emotion: str
    pause_expectation: str
    audible_delivery_cue: str


@dataclass(frozen=True)
class SpikeCase:
    case_id: str
    clean_id: str
    defect: str
    dimension: str
    construction: str


STANDARD_CORPUS = (
    CorpusCase("narration-suspense", "narration", "走廊尽头的灯忽然灭了。她停下脚步，听见门后传来轻轻的敲击。", "tense", "门后揭示前短暂停顿", "声音略收紧，揭示敲击前留白"),
    CorpusCase("dialogue-whisper", "dialogue", "别回头。他们就在楼梯口。", "fearful", "两句之间短暂停顿", "低声急促提示危险，后一句压低音量"),
    CorpusCase("monologue-grief", "monologue", "我把那封信留了很多年，却一直没有勇气拆开。", "sad", "句尾自然留白", "语势克制，句尾缓缓落下，不刻意上扬"),
    CorpusCase("narration-reveal", "narration", "箱子打开时，所有人都愣住了：里面只有一张旧照片。", "surprised", "冒号前短暂停顿", "揭晓时语气微扬，避免持续高声"),
    CorpusCase("dialogue-stop", "dialogue", "停下！那扇门不能打开。", "angry", "呼喊后短暂停顿", "首句果断制止，后句降低强度说明危险"),
    CorpusCase("monologue-relief", "monologue", "我以为再也见不到你了。现在看到你平安回来，终于能放心了。", "relieved", "情绪转折处停顿", "由急切转为松弛，第二句语势渐缓"),
    CorpusCase("narration-calm", "narration", "天亮后，雨渐渐停了。街道恢复平静，新的旅程才刚刚开始。", "calm", "结尾自然留白", "平稳陈述，结尾自然收束"),
)

# construction 是离线造样说明，不是已产出的音频或生成提示词。
SPIKE_CASES = (
    SpikeCase("omission-1", "dialogue-whisper", "omission", "fidelity", "删去录音中一句完整台词；保持其余音频不变"),
    SpikeCase("substitution-1", "narration-reveal", "substitution", "fidelity", "替换录音中关键名词，并保留其余台词"),
    SpikeCase("tag-leak-1", "dialogue-stop", "tag_leak", "contamination", "在录音中读出原本不应朗读的控制标签"),
    SpikeCase("pause-mismatch-1", "narration-suspense", "pause_mismatch", "prosody_pause", "把指定揭示前停顿移至句尾"),
    SpikeCase("emotion-mismatch-1", "monologue-grief", "emotion_mismatch", "emotion_match", "用明显欢快语气录制原本克制悲伤的台词"),
)


@dataclass(frozen=True)
class VoiceIdentityScope:
    """按角色与 A/B 变体聚合的音色一致性评测范围，不包含评分。"""

    speaker_id: str
    variant: str
    sample_ids: tuple[str, ...]
    status: str


def build_voice_identity_scopes(samples: Sequence[Mapping[str, str]]) -> tuple[VoiceIdentityScope, ...]:
    """单片段只能弃评；同一角色的 A/B 必须引用同一音色资产。"""
    groups: dict[tuple[str, str], list[str]] = {}
    voices: dict[str, str] = {}
    seen: set[str] = set()
    for sample in samples:
        sample_id = sample.get("sample_id", "")
        speaker = sample.get("speaker_id", "")
        variant = sample.get("variant", "")
        voice = sample.get("voice_id", "")
        if not all((sample_id, speaker, voice)) or variant not in {"A", "B"}:
            raise ValueError("missing or invalid voice identity sample fields")
        if sample_id in seen:
            raise ValueError("duplicate sample_id")
        if speaker in voices and voices[speaker] != voice:
            raise ValueError("voice_id differs for the same speaker")
        seen.add(sample_id)
        voices[speaker] = voice
        groups.setdefault((speaker, variant), []).append(sample_id)
    return tuple(
        VoiceIdentityScope(
            speaker_id=speaker,
            variant=variant,
            sample_ids=tuple(ids),
            status="pending_sequence_review" if len(ids) >= 2 else "not_assessable",
        )
        for (speaker, variant), ids in sorted(groups.items())
    )


def build_blind_manifest(sample_ids: Sequence[str], *, seed: int) -> tuple[tuple[str, ...], dict[str, str]]:
    """返回匿名随机顺序及仅供解盲的映射；不能把映射传给评分器。"""
    if len(set(sample_ids)) != len(sample_ids):
        raise ValueError("duplicate sample IDs")
    shuffled = list(sample_ids)
    random.Random(seed).shuffle(shuffled)
    answer_key = {
        hashlib.sha256(f"audio-blind-v1:{seed}:{index}".encode()).hexdigest()[:16]: sample_id
        for index, sample_id in enumerate(shuffled)
    }
    return tuple(answer_key), answer_key


def validate_ab_pair(baseline: Mapping[str, str], optimized: Mapping[str, str]) -> None:
    """只允许音频产物路径与提示词变化，拒绝后期处理不一致的对照。"""
    required = frozenset({
        "text_hash", "voice_id", "model_id", "audio_settings_hash",
        "postprocess_hash", "prompt_hash", "audio_path",
    })
    if required - baseline.keys() or required - optimized.keys():
        raise ValueError("missing A/B fields")
    for field in required - {"prompt_hash", "audio_path"}:
        if not baseline[field] or baseline[field] != optimized[field]:
            raise ValueError(f"A/B field differs: {field}")
    if not baseline["prompt_hash"] or not optimized["prompt_hash"] or baseline["prompt_hash"] == optimized["prompt_hash"]:
        raise ValueError("prompt_hash must differ")


def assess_spike_detection(
    verdicts: Mapping[str, str], *, clean_ids: set[str], spike_ids: set[str]
) -> dict[str, int | float | None]:
    """将弃评计入检出率分母；无干净对照时误报率为空。"""
    if clean_ids & spike_ids:
        raise ValueError("clean and spike IDs overlap")
    expected = clean_ids | spike_ids
    if expected - verdicts.keys():
        raise ValueError("missing verdicts")
    if verdicts.keys() - expected or set(verdicts.values()) - {"pass", "fail", "not_assessable"}:
        raise ValueError("invalid verdicts")
    tp = sum(verdicts[item] == "fail" for item in spike_ids)
    fn = sum(verdicts[item] == "pass" for item in spike_ids)
    fp = sum(verdicts[item] == "fail" for item in clean_ids)
    tn = sum(verdicts[item] == "pass" for item in clean_ids)
    abstained = sum(value == "not_assessable" for value in verdicts.values())
    return {
        "true_positive": tp,
        "false_negative": fn,
        "false_positive": fp,
        "true_negative": tn,
        "abstained": abstained,
        "detection_rate": tp / len(spike_ids) if spike_ids else None,
        "false_alarm_rate": fp / len(clean_ids) if clean_ids else None,
    }
