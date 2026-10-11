"""音色画像自动打标：受控枚举合同、盲评提示词、双模型分工与 sidecar 落盘结构。

真值链顺序与 TTS 提示词实验一致：客观层（时长、逐字转写、HTTP 状态）→ 盲评标签 → 人耳终裁。
本模块只在显式调用时使用，不接入章节生产链路；模型输出永远是 candidate，不是已审核画像。
"""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import httpx

from app.schemas.voice_tags import (
    SINGLE_VALUE_DIMENSIONS,
    TAXONOMY_VERSION,
    WRITABLE_TAG_DIMENSIONS,
    dimension_tag_limit,
    normalize_voice_tags,
    voice_tag_label,
)
from app.services.audiobook.scene_quality.audio_score_contract import (
    EMOTION_AUTHORITY_MODEL,
    VERIFIABLE_AUTHORITY_MODEL,
)
from app.services.audiobook.scene_quality.audio_understanding import understand_audio
from app.services.audiobook.tts_output_validator import estimate_tts_duration_ms

TAGGING_SCHEMA_VERSION = "voice-profile-tagging-v1"
PROFILE_SCHEMA_VERSION = "voice-profile-sidecar-v1"

# 采信分工复用评分合同的单一事实源：听感判断只采信豆包，qwen3.8 作参考侧写。
PRIMARY_SCORER = EMOTION_AUTHORITY_MODEL
REFERENCE_SCORER = VERIFIABLE_AUTHORITY_MODEL

# 一条试听样本只能支撑"这段朗读听起来如何"。指南 §4.2 把 performance/scenario/
# role_archetype 的数据来源定为多段标准样本与人工审核，§4.4 要求 emotion 是"可稳定表达"
# 的情绪倾向；而试听语录的内容会主导情绪判断，所以这四类都不进入自动打标合同。
TAGGING_DIMENSIONS = (
    "gender_presentation",
    "age_impression",
    "timbre",
    "style",
    "pitch_range",
    "pace",
    "energy",
    "articulation",
    "temperament",
)

MIN_TAG_CONFIDENCE = 0.6

# 短于此长度的相邻重复是正常口语叠词，不足以认定成 ASR 整句幻觉。
MIN_REPEAT_BLOCK_CHARS = 8

_DIMENSION_GUIDANCE: Mapping[str, str] = {
    "gender_presentation": "听感性别呈现，不推断真实性别",
    "age_impression": "听感年龄，不推断真实年龄",
    "timbre": "声音本体的听感质地",
    "style": "最主要的表达/演绎风格，只选一个",
    "pitch_range": "整体音高区间",
    "pace": "整体语速档位",
    "energy": "整体能量强弱",
    "articulation": "咬字清晰度",
    "temperament": "面向选角的角色气质印象，不含职业与题材",
}

_PUNCT_RE = re.compile(r"[\s\W_]+", re.UNICODE)

# ASR 与试听文本的差异里，有一类不是内容差异：中文数字写法、以及听写无法区分的同音虚字。
# 只归一这两类，漏读整句仍然会拉低相似度。
_CN_DIGIT_VALUES = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_UNIT_VALUES = {"十": 10, "百": 100, "千": 1000, "万": 10_000, "亿": 100_000_000}
_CN_NUMERAL_RE = re.compile(
    f"[{''.join(_CN_DIGIT_VALUES)}{''.join(_CN_UNIT_VALUES)}]+", re.UNICODE
)
_HOMOPHONE_TABLE = str.maketrans({"他": "他", "她": "他", "它": "他", "地": "的", "得": "的"})

# 词表里 pitch_range 用 low_mid、energy 用 medium_low，构词方向不一致会诱导模型写成镜像。
_TAG_SYNONYMS: Mapping[str, Mapping[str, str]] = {
    "pitch_range": {"mid_low": "low_mid", "high_mid": "mid_high"},
}
_KNOWN_TAG_CODES = frozenset(
    code for codes in WRITABLE_TAG_DIMENSIONS.values() for code in codes
)
_JSON_DECODER = json.JSONDecoder()


@dataclass(frozen=True)
class DimensionJudgement:
    tags: tuple[str, ...]
    evidence: str
    confidence: float


def build_tagging_prompt(*, text: str) -> str:
    """构造盲评提示词：只给朗读文本与受控枚举，不含音色名称、编号或任何先验标签。"""
    dimension_lines = "\n".join(
        f"- {dimension}（{_selection_rule(dimension)}，{_DIMENSION_GUIDANCE[dimension]}）："
        + "、".join(
            f"{code}（{voice_tag_label(dimension, code)['zh']}）"
            for code in WRITABLE_TAG_DIMENSIONS[dimension]
        )
        for dimension in TAGGING_DIMENSIONS
    )
    output_example = json.dumps(
        {
            "dimensions": {
                dimension: {
                    "tags": ["<code>"],
                    "evidence": "<音频中可听见的具体表现>",
                    "confidence": 0.8,
                }
                for dimension in TAGGING_DIMENSIONS
            }
        },
        ensure_ascii=False,
    )
    return (
        "你是有声书选角导演。请只依据这段音频的听感为朗读者声音打标。\n"
        f"这段音频朗读的文本是：{text}\n"
        "\n规则：\n"
        "1. 每个维度只能从给定的受控取值中选择，禁止自造标签。\n"
        "2. 标注单选的维度最多 1 个值，标注数量的维度不得超过该数量。\n"
        "3. 听不出来的维度返回空数组，并在 evidence 中说明听不出，不要猜测。\n"
        "4. 只描述听感，不得推断真实年龄、真实性别、职业、身体状况或身份。\n"
        "5. evidence 只写在这段音频里实际听到的表现，不得复述本提示词的规则或取值名称。\n"
        f"6. 必须返回全部 {len(TAGGING_DIMENSIONS)} 个维度键，缺少任何一个都算无效。\n"
        "7. 只输出一个 JSON 对象本身：不要 markdown 代码块，不要解释文字，不要多余字段。\n"
        "\n维度与受控取值：\n"
        f"{dimension_lines}\n"
        f"\n输出格式示例：\n{output_example}"
    )


def _load_dimensions(raw: str) -> dict[str, Any]:
    """复原模型输出里的结构性笔误：JSON 之后多吐的尾巴、dimensions 键的拼写错误。"""
    text = str(raw or "").strip()
    try:
        payload, _ = _JSON_DECODER.raw_decode(text)
    except ValueError as exc:
        raise ValueError("invalid tagging JSON") from exc
    if not isinstance(payload, dict) or len(payload) != 1:
        raise ValueError("invalid tagging payload")
    key, dimensions = next(iter(payload.items()))
    if key != "dimensions" and not _looks_like_dimensions(dimensions):
        raise ValueError("invalid tagging payload")
    if not isinstance(dimensions, dict):
        raise ValueError("invalid tagging dimensions")
    return dimensions


def _looks_like_dimensions(value: Any) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    return set(value) <= set(TAGGING_DIMENSIONS)


def _tolerate_tags(dimension: str, codes: list[Any]) -> list[str]:
    """把取值收敛到本维度词表：镜像拼写复原，来自其他维度的取值按维丢弃，自造取值仍报错。"""
    allowed = WRITABLE_TAG_DIMENSIONS[dimension]
    synonyms = _TAG_SYNONYMS.get(dimension, {})
    kept: list[str] = []
    for raw_code in codes:
        code = str(raw_code or "").strip().lower()
        if not code:
            continue
        code = synonyms.get(code, code)
        if code in allowed:
            if code not in kept:
                kept.append(code)
        elif code in _KNOWN_TAG_CODES:
            continue
        else:
            raise ValueError(f"unsupported {dimension} tag: {code}")
    return kept


def parse_tagging_response(raw: str) -> dict[str, DimensionJudgement]:
    """解析打标输出：结构性笔误可复原，未知维度、自造取值、超量、缺证据一律报错。"""
    dimensions = _load_dimensions(raw)

    unknown = sorted(set(dimensions) - set(TAGGING_DIMENSIONS))
    if unknown:
        raise ValueError(f"dimension outside the tagging contract: {', '.join(unknown)}")
    missing = [name for name in TAGGING_DIMENSIONS if name not in dimensions]
    if missing:
        raise ValueError(f"missing tagging dimension(s): {', '.join(missing)}")

    parsed: dict[str, DimensionJudgement] = {}
    for name in TAGGING_DIMENSIONS:
        entry = dimensions[name]
        if not isinstance(entry, dict) or set(entry) != {"tags", "evidence", "confidence"}:
            raise ValueError(f"invalid {name} fields")
        if not isinstance(entry["tags"], list):
            raise ValueError(f"invalid {name} tags")
        tags = normalize_voice_tags(_tolerate_tags(name, entry["tags"]), dimension=name)
        evidence = entry["evidence"]
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f"invalid {name} evidence")
        confidence = entry["confidence"]
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise ValueError(f"invalid {name} confidence")
        parsed[name] = DimensionJudgement(
            tags=tuple(tags),
            evidence=evidence.strip(),
            confidence=float(confidence),
        )
    return parsed


def transcript_similarity(*, expected: str, transcript: str) -> float:
    """逐字转写与试听文本的相似度：忽略标点、大小写、数字写法与同音虚字，只比可读内容。"""
    left = _canonical_compare_text(expected)
    right = _canonical_compare_text(transcript)
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def _chinese_numeral_to_int(run: str) -> int:
    total = 0
    section = 0
    number: int | None = None
    for char in run:
        if char in _CN_DIGIT_VALUES:
            number = _CN_DIGIT_VALUES[char]
            continue
        unit = _CN_UNIT_VALUES[char]
        if unit < 10_000:
            section += (1 if number is None else number) * unit
            number = None
        else:
            total += (section + (number or 0)) * unit
            section = 0
            number = None
    return total + section + (number or 0)


def _canonical_compare_text(value: str) -> str:
    text = _PUNCT_RE.sub("", str(value or "")).casefold()
    text = _CN_NUMERAL_RE.sub(lambda match: str(_chinese_numeral_to_int(match.group())), text)
    return text.translate(_HOMOPHONE_TABLE)


@dataclass(frozen=True)
class AsrRepeatFold:
    """一次成立的重复折叠：折叠后相似度与被摘掉的重复段（规范化文本）。"""

    similarity: float
    removed_block: str


def _fold_adjacent_duplicate(canonical: str) -> tuple[str, str] | None:
    """摘掉最长的一段相邻完全重复，返回 (折叠结果, 被摘掉的段)。"""
    for size in range(len(canonical) // 2, MIN_REPEAT_BLOCK_CHARS - 1, -1):
        for start in range(len(canonical) - 2 * size + 1):
            if canonical[start : start + size] == canonical[start + size : start + 2 * size]:
                return (
                    canonical[: start + size] + canonical[start + 2 * size :],
                    canonical[start + size : start + 2 * size],
                )
    return None


def fold_suspected_asr_repeat(
    *, expected: str, transcript: str, voiced_duration_ms: float
) -> AsrRepeatFold | None:
    """有时长反证时折叠 ASR 的整句重复幻觉，否则不动转写。

    ASR 会把整句再念一遍（实测跨三种音色逐字节复现），把相似度压到门下。只有当
    "转写需要的朗读时长 > 实测发声时长"时才折叠：时长装得下重复就说明是 TTS 真复读，
    必须让门禁继续拒掉，所以判据是物理反证而不是相似度猜测。
    """
    left = _canonical_compare_text(expected)
    right = _canonical_compare_text(transcript)
    if not left or not right or voiced_duration_ms <= 0:
        return None
    if estimate_tts_duration_ms(transcript) <= voiced_duration_ms:
        return None
    folded = _fold_adjacent_duplicate(right)
    if folded is None:
        return None
    folded_text, removed_block = folded
    similarity = difflib.SequenceMatcher(None, left, folded_text).ratio()
    if similarity <= transcript_similarity(expected=expected, transcript=transcript):
        return None
    return AsrRepeatFold(similarity=similarity, removed_block=removed_block)


def profile_entry_from_judgements(
    *,
    model: str,
    voice_id: str,
    preview_text: str,
    audio_sha256: str,
    primary: Mapping[str, DimensionJudgement] | None,
    reference: Mapping[str, DimensionJudgement] | None,
    objective: Mapping[str, Any],
) -> dict[str, Any]:
    """合成 sidecar 条目：标签只取主模型，参考模型另存一档且不参与投影。"""
    gate_passed = bool(objective.get("passed"))
    tags: dict[str, list[str]] = {}
    tag_evidence: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []

    if not gate_passed:
        reasons.append("objective_gate_failed")
    elif primary is None:
        reasons.append("primary_scorer_failed")
    else:
        reasons.append("single_sample_evidence")
        for name, judgement in primary.items():
            if not judgement.tags:
                continue
            tags[name] = list(judgement.tags)
            tag_evidence[name] = {
                "evidence": judgement.evidence,
                "confidence": judgement.confidence,
            }
            if judgement.confidence < MIN_TAG_CONFIDENCE:
                reasons.append(f"low_confidence:{name}")
        if reference is not None:
            for name in TAGGING_DIMENSIONS:
                if name not in SINGLE_VALUE_DIMENSIONS:
                    continue
                reference_tags = list(reference[name].tags)
                if tags.get(name) and reference_tags and tags[name] != reference_tags:
                    reasons.append(f"scorer_disagreement:{name}")

    # 靠时长反证折叠过重复的行必须留痕，人耳复核要能一眼看到它是"放行"而不是"读顺了"。
    if objective.get("asr_repeat_suspect"):
        reasons.append("asr_repeat_suspect")

    entry: dict[str, Any] = {
        "source": "auto_tagging",
        "model": model,
        "voice_id": voice_id,
        "preview_text": preview_text,
        "audio_sha256": audio_sha256,
        "schema_version": TAGGING_SCHEMA_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "primary_scorer": PRIMARY_SCORER,
        "reference_scorer": REFERENCE_SCORER,
        "profile_status": "ready" if tags else "pending",
        # §7.4：模型产出的画像一律先是候选；§5.3 的人工复核只挑高曝光与低置信度项。
        "review_status": "candidate",
        "needs_review": True,
        "needs_review_reasons": reasons,
        "objective": dict(objective),
        "tags": tags,
        "tag_evidence": tag_evidence,
    }
    if reference is not None:
        entry["reference"] = _serialise_judgements(reference)
    return entry


def raw_cache_path(
    cache_dir: str | Path,
    *,
    scorer: str,
    model: str,
    voice_id: str,
    text: str,
    audio_sha256: str,
) -> Path:
    """幂等缓存键：词表版本、提示词文本、音频内容与评分模型任一变化都失效。"""
    payload = "|".join(
        (
            TAGGING_SCHEMA_VERSION,
            TAXONOMY_VERSION,
            scorer,
            model,
            voice_id,
            hashlib.sha256(str(text).encode("utf-8")).hexdigest(),
            str(audio_sha256),
        )
    )
    return Path(cache_dir) / f"{hashlib.sha256(payload.encode('utf-8')).hexdigest()}.json"


def tag_voice_profile(
    *,
    audio_path: str | Path,
    text: str,
    model: str,
    voice_id: str,
    api_keys: Mapping[str, str],
    cache_dir: str | Path | None = None,
    client: httpx.Client | None = None,
) -> tuple[dict[str, DimensionJudgement], dict[str, DimensionJudgement] | None, list[Path]]:
    """主/参考两个模型各听一次；参考模型失败不阻塞，主模型失败必须报错。"""
    prompt = build_tagging_prompt(text=text)
    audio_sha256 = hashlib.sha256(Path(audio_path).read_bytes()).hexdigest()
    judgements: dict[str, dict[str, DimensionJudgement]] = {}
    written: list[Path] = []

    for scorer in (PRIMARY_SCORER, REFERENCE_SCORER):
        api_key = str(api_keys.get(scorer) or "").strip()
        if not api_key:
            if scorer == PRIMARY_SCORER:
                raise ValueError(f"primary scorer {scorer} api key is missing")
            continue
        cache_path = (
            raw_cache_path(
                cache_dir,
                scorer=scorer,
                model=model,
                voice_id=voice_id,
                text=text,
                audio_sha256=audio_sha256,
            )
            if cache_dir is not None
            else None
        )
        raw = _read_cached_raw(cache_path) if cache_path else None
        if raw is None:
            result = understand_audio(
                audio_path=audio_path, prompt=prompt, model=scorer, api_key=api_key,
                max_tokens=2048, client=client,
            )
            if result.status != "ok":
                if scorer == PRIMARY_SCORER:
                    raise ValueError(f"primary scorer {scorer} unavailable: {result.error_kind}")
                continue
            raw = result.raw
            if cache_path is not None:
                _write_cache(
                    cache_path,
                    raw=raw,
                    scorer=scorer,
                    model=model,
                    voice_id=voice_id,
                    audio_sha256=audio_sha256,
                    usage=result.usage,
                )
                written.append(cache_path)
        try:
            judgements[scorer] = parse_tagging_response(raw)
        except ValueError:
            if scorer == PRIMARY_SCORER:
                raise ValueError(f"primary scorer {scorer} returned an invalid tagging payload")
            continue

    return (
        judgements[PRIMARY_SCORER],
        judgements.get(REFERENCE_SCORER),
        written,
    )


def build_sidecar_document(
    *,
    model: str,
    catalog_filename: str,
    catalog_revision: str,
    entries: Mapping[str, Mapping[str, Any]],
    generated_by: tuple[str, ...] = (PRIMARY_SCORER, REFERENCE_SCORER),
) -> dict[str, Any]:
    """画像文件顶层元数据：可审计地绑定目录版本、词表版本与产出方。"""
    voice_profiles = {voice_id: dict(entry) for voice_id, entry in entries.items()}
    digest = hashlib.sha256(
        json.dumps(voice_profiles, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "tagging_schema_version": TAGGING_SCHEMA_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "model": model,
        "catalog_filename": catalog_filename,
        "catalog_revision": catalog_revision,
        "generated_by": list(generated_by),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile_version": f"sha256:{digest[:16]}",
        "voice_profiles": voice_profiles,
    }


def _selection_rule(dimension: str) -> str:
    if dimension in SINGLE_VALUE_DIMENSIONS:
        return "单选"
    return f"最多 {dimension_tag_limit(dimension)} 个"


def _serialise_judgements(judgements: Mapping[str, DimensionJudgement]) -> dict[str, Any]:
    return {
        "dimensions": {
            name: {
                "tags": list(judgement.tags),
                "evidence": judgement.evidence,
                "confidence": judgement.confidence,
            }
            for name, judgement in judgements.items()
        }
    }


def _read_cached_raw(cache_path: Path | None) -> str | None:
    if cache_path is None or not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    raw = payload.get("raw") if isinstance(payload, dict) else None
    return raw if isinstance(raw, str) and raw.strip() else None


def _write_cache(
    cache_path: Path,
    *,
    raw: str,
    model: str,
    voice_id: str,
    audio_sha256: str,
    scorer: str,
    usage: Mapping[str, Any] | None,
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "scorer": scorer,
                "model": model,
                "voice_id": voice_id,
                "audio_sha256": audio_sha256,
                "taxonomy_version": TAXONOMY_VERSION,
                "tagging_schema_version": TAGGING_SCHEMA_VERSION,
                "usage": dict(usage or {}),
                "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "raw": raw,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
        newline="\n",
    )
