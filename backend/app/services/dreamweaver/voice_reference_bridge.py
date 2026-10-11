"""短剧生成端音色参考桥（video_model_capability_watch O4，四轨声音方案轨道②）。

跨板块复用 audiobook voice_reference_asset 池：把短剧剧本角色解析为可用的
参考音频映射（{speaker: {asset_id, storage_uri, ...}}），供 Contract 引擎
sound_track 决策（native_voice_ref 路线）与视频生成请求消费。

复用遵循 adaptation_resource_protocol：只读复用 + provenance 四元组登记；
复用是输入供给不是创作约束，角色无参考资产时对白轨降级后期 TTS（不阻断）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.voice_reference_asset import VoiceReferenceAsset


def get_active_voice_reference_assets_by_speakers(
    db: Session,
    speakers: Sequence[str],
    *,
    owner_user_id: Optional[int] = None,
) -> List[VoiceReferenceAsset]:
    """按角色名查活跃的物化参考音频（storage_uri 非空、未撤销、未删除）。

    同角色多条时按 updated_at 倒序返回，消费方取首条。
    """
    names = [str(s).strip() for s in speakers if str(s).strip()]
    if not names:
        return []
    stmt = (
        select(VoiceReferenceAsset)
        .where(
            VoiceReferenceAsset.speaker.in_(names),
            VoiceReferenceAsset.storage_uri.is_not(None),
            VoiceReferenceAsset.storage_uri != "",
            VoiceReferenceAsset.revoked_at.is_(None),
            VoiceReferenceAsset.deleted_at.is_(None),
        )
        .order_by(VoiceReferenceAsset.updated_at.desc(), VoiceReferenceAsset.id.desc())
    )
    if owner_user_id is not None:
        stmt = stmt.where(VoiceReferenceAsset.owner_user_id == owner_user_id)
    return list(db.scalars(stmt).all())


def resolve_voice_references(
    db: Session,
    *,
    speakers: Sequence[str],
    owner_user_id: Optional[int] = None,
    run_id: str = "",
) -> Dict[str, Any]:
    """角色名列表 → 参考音频映射 + provenance 登记（payload 直接可挂）。"""
    names = [str(s).strip() for s in speakers if str(s).strip()]
    assets = get_active_voice_reference_assets_by_speakers(
        db, names, owner_user_id=owner_user_id,
    )
    by_speaker: Dict[str, VoiceReferenceAsset] = {}
    for asset in assets:  # updated_at 倒序，首条即最新
        if asset.speaker not in by_speaker:
            by_speaker[asset.speaker] = asset

    voice_reference_audio: Dict[str, Dict[str, Any]] = {}
    provenance: List[Dict[str, str]] = []
    for name in names:
        asset = by_speaker.get(name)
        if asset is None:
            continue
        voice_reference_audio[name] = {
            "asset_id": asset.asset_id,
            "storage_uri": asset.storage_uri or "",
            "provider": asset.provider or "",
            "source_type": asset.source_type,
            "duration_s": asset.duration_s,
        }
        provenance.append({
            "source_resource_id": f"voice_ref:{asset.asset_id}",
            "source_version": f"sha256:{asset.sha256}" if asset.sha256 else "",
            "used_in": f"dreamweaver:{run_id or 'unknown'}",
            "reuse_mode": "read_only_audio_reference",
        })

    missing = [n for n in names if n not in voice_reference_audio]
    return {
        "voice_reference_audio": voice_reference_audio,
        "missing_speakers": missing,
        "provenance": provenance,
    }


def extract_script_speakers(payload: Dict[str, Any]) -> List[str]:
    """从 scripter 产物提取角色名（script_document 新 schema + script_entities 兼容 schema 并集）。"""
    speakers: List[str] = []

    def _add(name: Any) -> None:
        text = str(name or "").strip()
        if text and text not in ("旁白", "narrator", "NARRATOR") and text not in speakers:
            speakers.append(text)

    doc = payload.get("script_document")
    if isinstance(doc, dict):
        for scene in doc.get("scenes") or []:
            if not isinstance(scene, dict):
                continue
            for name in scene.get("characters") or []:
                _add(name)
    entities = payload.get("script_entities")
    if isinstance(entities, dict):
        for char in entities.get("characters") or []:
            if isinstance(char, dict):
                _add(char.get("name"))
    return speakers


def inject_voice_references_for_storyboard(
    db: Session,
    payload: Dict[str, Any],
    *,
    run_id: str = "",
    owner_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """STORYBOARD 前注入参考音频映射到 payload（sound_track 决策消费）。

    无角色或无可用资产时是 no-op（对白轨自动降级后期 TTS，不阻断管线）。
    """
    speakers = extract_script_speakers(payload)
    if not speakers:
        return {}
    result = resolve_voice_references(
        db, speakers=speakers, owner_user_id=owner_user_id, run_id=run_id,
    )
    if result["voice_reference_audio"]:
        payload["voice_reference_audio"] = result["voice_reference_audio"]
    if result["provenance"]:
        provenance = payload.setdefault("resource_provenance", [])
        if isinstance(provenance, list):
            provenance.extend(result["provenance"])
    payload["voice_reference_report"] = {
        "missing_speakers": result["missing_speakers"],
        "resolved": sorted(result["voice_reference_audio"]),
    }
    return result
