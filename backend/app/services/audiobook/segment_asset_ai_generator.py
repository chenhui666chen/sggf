"""单片段工作台音效/配乐 AI 资产生成服务

音效走豆包 seed-audio-1.0（与整章生成管线同模型）；配乐走 Mureka，
失败时回退豆包。生成结果写入素材库索引供后续复用，同时作为片段
重新生成候选的音频字节返回，复用既有候选签发/应用链路。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from fastapi import HTTPException

from app.services.audiobook.agents import SoundEffectDesigner
from app.services.audiobook.ai_music import (
    MusicGenerationRequest,
    MusicStyle,
    create_music_generator,
)
from app.services.audiobook.audio_library_paths import get_audio_library_dir
from app.services.audiobook.doubao_sfx_generator import (
    create_doubao_sfx_generator,
    has_doubao_sfx_api_key,
)
from app.services.audiobook.duration_estimator import estimate_narration_duration_seconds
from app.services.audiobook.segment_preview_service import SegmentPreviewService

logger = logging.getLogger(__name__)

SFX_ASSET_SOURCE = "doubao"
BGM_MUREKA_SOURCE = "mureka"
BGM_FALLBACK_SOURCE = "doubao"


@dataclass
class SegmentAssetGenerationResult:
    """AI 生成的素材结果：候选音频字节 + 素材库引用"""

    audio_bytes: bytes
    asset_id: str
    file_path: str  # 相对素材库目录
    source: str


def _decode_doubao_audio(audio_url: str) -> bytes:
    """豆包返回 HTTP 直链或 data: base64 数据地址，统一解码为字节"""
    if audio_url.startswith("data:"):
        _, _, encoded = audio_url.partition(",")
        return base64.b64decode(re.sub(r"\s+", "", encoded))

    import httpx

    response = httpx.get(audio_url, timeout=120.0, follow_redirects=True)
    response.raise_for_status()
    return response.content


def _collect_sound_effect_descriptions(segment: Dict[str, Any]) -> List[str]:
    specs = SegmentPreviewService.normalize_sound_effects(segment)
    return [
        str(spec.get("name") or "").strip()
        for spec in specs
        if str(spec.get("name") or "").strip()
    ]


def _resolve_music_style(style_hint: str) -> MusicStyle:
    hint = str(style_hint or "").strip()
    if hint:
        for style in MusicStyle:
            if hint in style.value or style.value in hint:
                return style
    return MusicStyle.AMBIENT


def _build_bgm_prompt(segment: Dict[str, Any], cue: Dict[str, Any]) -> str:
    parts: List[str] = []
    style = str(cue.get("style") or "").strip()
    if style:
        parts.append(f"{style}风格配乐")
    text = str(segment.get("text") or "").strip()
    if text:
        scene_excerpt = text[:60]
        parts.append(f"适配场景：{scene_excerpt}")
    parts.append("纯器乐，无人声，不抢对白")
    return "，".join(parts)


async def generate_segment_sfx_asset(segment: Dict[str, Any]) -> SegmentAssetGenerationResult:
    """用豆包 seed-audio-1.0 按片段音效描述生成音效并入库"""
    descriptions = _collect_sound_effect_descriptions(segment)
    if not descriptions:
        raise HTTPException(status_code=400, detail="该片段未配置音效，无法 AI 生成音效")
    if not has_doubao_sfx_api_key():
        raise HTTPException(
            status_code=503,
            detail="未配置豆包音频密钥，无法 AI 生成音效，可改用素材库匹配",
        )

    prompt = f"有声书场景音效：{'；'.join(descriptions)}。纯音效，无人声，无背景音乐。"
    duration = max(
        3.0,
        min(
            10.0,
            float(
                estimate_narration_duration_seconds(
                    str(segment.get("text") or ""), min_duration=3.0
                )
            ),
        ),
    )

    generator = create_doubao_sfx_generator()
    result = await generator.generate_audio_async(prompt=prompt, duration=duration)
    if not result.success or not result.audio_url:
        raise HTTPException(
            status_code=502,
            detail=f"豆包音效生成失败：{result.error or '缺少音频输出'}",
        )

    effect_id = f"segment_sfx_{uuid.uuid4().hex[:12]}"
    designer = SoundEffectDesigner(llm_client=None)
    record = await asyncio.to_thread(
        designer.download_and_register_effect,
        url=result.audio_url,
        effect_id=effect_id,
        category="action/segment_workbench",
        description="；".join(descriptions),
        tags=["单片段工作台", "AI生成"],
        source="ai_generated",
        category_hint="action",
    )
    if not record or not record.get("file_path"):
        raise HTTPException(status_code=500, detail="音效已生成但入库失败，请重试")

    relative_file_path = str(record["file_path"])
    asset_path = get_audio_library_dir() / relative_file_path
    if not asset_path.exists():
        raise HTTPException(status_code=500, detail="音效已生成但素材文件不存在")
    return SegmentAssetGenerationResult(
        audio_bytes=asset_path.read_bytes(),
        asset_id=str(record.get("id") or effect_id),
        file_path=relative_file_path,
        source=SFX_ASSET_SOURCE,
    )


def _append_music_index_record(library_dir: Path, record: Dict[str, Any]) -> None:
    """把豆包回退生成的配乐追加进 music_index.json（索引仅为辅助检索信息）"""
    index_path = library_dir / "music_index.json"
    records: List[Dict[str, Any]] = []
    if index_path.exists():
        try:
            loaded = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                records = loaded
        except Exception as exc:
            logger.warning("读取音乐索引失败，将重建索引: %s", exc)
    records = [item for item in records if item.get("id") != record.get("id")]
    records.append(record)
    index_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


async def _generate_bgm_with_doubao_fallback(
    *,
    prompt: str,
    mood: str,
    style_hint: str,
    duration: int,
) -> SegmentAssetGenerationResult:
    if not has_doubao_sfx_api_key():
        raise HTTPException(
            status_code=502,
            detail="配乐生成失败：Mureka 不可用且未配置豆包音频密钥",
        )

    fallback_prompt = f"背景音乐：{prompt}"
    generator = create_doubao_sfx_generator()
    result = await generator.generate_audio_async(
        prompt=fallback_prompt,
        duration=float(min(30, max(10, duration))),
    )
    if not result.success or not result.audio_url:
        raise HTTPException(
            status_code=502,
            detail=f"配乐生成失败：{result.error or 'Mureka 与豆包均不可用'}",
        )

    audio_bytes = _decode_doubao_audio(result.audio_url)
    library_dir = get_audio_library_dir()
    music_cache_dir = library_dir / "music_cache"
    music_cache_dir.mkdir(parents=True, exist_ok=True)
    asset_id = f"segment_bgm_{uuid.uuid4().hex[:12]}"
    output_path = music_cache_dir / f"{asset_id}.mp3"
    output_path.write_bytes(audio_bytes)
    relative_path = f"music_cache/{output_path.name}"
    _append_music_index_record(
        library_dir,
        {
            "id": asset_id,
            "prompt": fallback_prompt,
            "style": style_hint,
            "duration": duration,
            "tempo": "medium",
            "mood": mood,
            "instruments": [],
            "variant": 0,
            "bucket": "",
            "file_path": relative_path,
            "source": BGM_FALLBACK_SOURCE,
        },
    )
    logger.info("🎵 豆包回退配乐已入库: %s", asset_id)
    return SegmentAssetGenerationResult(
        audio_bytes=audio_bytes,
        asset_id=asset_id,
        file_path=relative_path,
        source=BGM_FALLBACK_SOURCE,
    )


async def generate_segment_bgm_asset(segment: Dict[str, Any]) -> SegmentAssetGenerationResult:
    """用 Mureka 按片段配乐提示生成配乐；失败回退豆包 seed-audio"""
    cue = SegmentPreviewService.normalize_music_cue(segment)
    if not cue:
        raise HTTPException(status_code=400, detail="该片段未配置配乐，无法 AI 生成配乐")

    duration = int(
        max(
            15.0,
            min(
                60.0,
                estimate_narration_duration_seconds(
                    str(segment.get("text") or ""), min_duration=15.0
                ),
            ),
        )
    )
    prompt = _build_bgm_prompt(segment, cue)
    mood = str(
        cue.get("mood")
        or SegmentPreviewService.infer_music_mood(str(segment.get("emotion") or ""))
    )
    style_hint = str(cue.get("style") or "").strip()

    music_result = None
    try:
        music_generator = create_music_generator(enable_cache=True)
        music_result = await music_generator.client.generate_music(
            MusicGenerationRequest(
                prompt=prompt,
                style=_resolve_music_style(style_hint),
                duration=duration,
                mood=mood,
            )
        )
    except Exception as exc:
        logger.warning("Mureka 配乐生成异常: %s", exc)

    if music_result is not None and getattr(music_result, "success", False):
        audio_bytes = getattr(music_result, "audio_data", None)
        relative_path = str(getattr(music_result, "audio_file_path", "") or "")
        if not audio_bytes and relative_path:
            candidate = get_audio_library_dir() / relative_path
            if candidate.exists():
                audio_bytes = candidate.read_bytes()
        if audio_bytes:
            return SegmentAssetGenerationResult(
                audio_bytes=audio_bytes,
                asset_id=Path(relative_path).stem
                if relative_path
                else f"segment_bgm_{uuid.uuid4().hex[:12]}",
                file_path=relative_path,
                source=BGM_MUREKA_SOURCE,
            )

    logger.info("Mureka 配乐生成失败，回退豆包 seed-audio")
    return await _generate_bgm_with_doubao_fallback(
        prompt=prompt,
        mood=mood,
        style_hint=style_hint,
        duration=duration,
    )


__all__ = [
    "SegmentAssetGenerationResult",
    "generate_segment_bgm_asset",
    "generate_segment_sfx_asset",
]
