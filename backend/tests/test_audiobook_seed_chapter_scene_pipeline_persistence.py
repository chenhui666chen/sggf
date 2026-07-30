"""ChapterScenePipeline 运行时物化落库接线 TDD。

用户已授权的私有设计/复刻音色在注入 ``db_session_factory`` 时把物化结果
回写到既有 ``VoiceReferenceAsset``；未注入时行为完全不变，落库失败也不
阻断渲染主流程。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.models.voice_reference_asset import VoiceReferenceAsset
from app.services.audiobook.scene_engine.chapter_pipeline import ChapterScenePipeline
from app.services.audiobook.scene_engine.planner import ScenePlanner
from app.services.audiobook.scene_engine.preview_reference_asset import (
    PreviewReferenceAsset,
)
from app.services.audiobook.scene_engine.scene_renderer import SceneRenderResult
from app.services.audiobook.script_adapter_pkg._dataclasses import ScriptSegment
from app.services.audiobook.voice_reference_asset_repository import (
    persist_user_generated_voice_reference,
)


class FakeMaterializer:
    def materialize(self, config):
        return PreviewReferenceAsset(
            source_model=str(config.get("tts_model") or ""),
            source_voice_id=str(config.get("voice_id") or ""),
            source_preview_cache_key="preview-cache-key",
            storage_path=Path("reference-assets/materialized.wav"),
            source_url=str(config.get("preview_audio_url") or "") or None,
            sha256="reference-sha256",
            duration_s=8.0,
            content_type="audio/wav",
            reference={"audio_data": "MATERIALIZED_AUDIO"},
        )


class FakeRenderer:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def render(self, plan, **kwargs):
        self.calls.append({"plan": plan, **kwargs})
        return SceneRenderResult(
            scene_id=plan.scene_id,
            status="passed",
            action="assemble",
            attempts=1,
            audio_path=Path(f"{plan.scene_id}.mp3"),
            subtitle_payload=None,
            quality_report=None,
            fallback_reason=None,
        )


def _segment(text: str, *, speaker: str, scene: str, emotion: str = "tense", pause_after: float = 0.0) -> ScriptSegment:
    return ScriptSegment(
        type="dialogue",
        text=text,
        speaker=speaker,
        emotion=emotion,
        instruct_scene=scene,
        pause_after=pause_after,
    )


def _semantic_planner() -> ScenePlanner:
    return ScenePlanner(
        target_min_duration_s=5,
        target_max_duration_s=100,
        soft_max_duration_s=110,
        hard_max_duration_s=120,
    )


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    VoiceReferenceAsset.__table__.create(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _private_reference_segments() -> list[ScriptSegment]:
    return [
        _segment("她听着雨声，迟迟没有开口。", speaker="女主", scene="雨夜室内", pause_after=5),
        _segment("列车进站后，她终于说出了真相。", speaker="女主", scene="清晨站台", emotion="sad"),
    ]


def _private_reference_mapping(asset_id: str = "ug-owned") -> dict[str, dict[str, Any]]:
    return {
        "女主": {
            "voice_id": "mimo_design:owned",
            "tts_model": "mimo-v2.5-tts-voicedesign",
            "reference_source": "user_private",
            "reference_audio_url": "https://assets.example/reference.mp3",
            "voice_reference_asset_id": asset_id,
            "voice_reference_owner_user_id": 7,
        }
    }


def _seed_private_reference(factory) -> dict[str, dict[str, Any]]:
    session = factory()
    try:
        asset = persist_user_generated_voice_reference(
            session,
            owner_user_id=7,
            provider="mimo",
            source_model="mimo-v2.5-tts-voicedesign",
            source_voice_id="mimo_design:owned",
            authorization_basis="synthetic_design",
            source_url="https://assets.example/reference.mp3",
        )
        session.commit()
        return _private_reference_mapping(asset.asset_id)
    finally:
        session.close()


def test_pipeline_persists_materialized_reference_when_session_injected() -> None:
    factory = _session_factory()
    voice_mapping = _seed_private_reference(factory)
    pipeline = ChapterScenePipeline(
        planner=_semantic_planner(),
        reference_materializer=FakeMaterializer(),
        renderer=FakeRenderer(),
        db_session_factory=factory,
    )

    result = pipeline.render(_private_reference_segments(), voice_mapping=voice_mapping)

    assert len(result.scenes) == 2
    session = factory()
    try:
        rows = session.query(VoiceReferenceAsset).all()
        assert len(rows) == 1
        asset = rows[0]
        assert asset.reference_kind == "user_generated_voice"
        assert asset.reference_field == "audio_data"
        assert asset.sha256 == "reference-sha256"
        assert asset.source_model == "mimo-v2.5-tts-voicedesign"
        assert asset.source_voice_id == "mimo_design:owned"
        assert asset.storage_uri == str(Path("reference-assets/materialized.wav"))
        assert asset.duration_s == 8.0
        assert asset.metadata_json["materialized_for_seed_audio"] is True
    finally:
        session.close()


def test_pipeline_persistence_is_idempotent_per_asset() -> None:
    factory = _session_factory()
    voice_mapping = _seed_private_reference(factory)
    pipeline = ChapterScenePipeline(
        planner=_semantic_planner(),
        reference_materializer=FakeMaterializer(),
        renderer=FakeRenderer(),
        db_session_factory=factory,
    )

    pipeline.render(_private_reference_segments(), voice_mapping=voice_mapping)
    pipeline.render(_private_reference_segments(), voice_mapping=voice_mapping)

    session = factory()
    try:
        assert session.query(VoiceReferenceAsset).count() == 1
    finally:
        session.close()


def test_pipeline_without_session_factory_is_unchanged() -> None:
    renderer = FakeRenderer()
    pipeline = ChapterScenePipeline(
        planner=_semantic_planner(),
        reference_materializer=FakeMaterializer(),
        renderer=renderer,
    )

    result = pipeline.render(
        _private_reference_segments(),
        voice_mapping=_private_reference_mapping(),
    )

    assert len(result.scenes) == 2
    assert all(
        scene.plan.references == ({"audio_data": "MATERIALIZED_AUDIO"},)
        for scene in result.scenes
    )


def test_pipeline_persistence_failure_does_not_break_render() -> None:
    def _boom_factory():
        raise RuntimeError("db unavailable")

    renderer = FakeRenderer()
    pipeline = ChapterScenePipeline(
        planner=_semantic_planner(),
        reference_materializer=FakeMaterializer(),
        renderer=renderer,
        db_session_factory=_boom_factory,
    )

    result = pipeline.render(
        _private_reference_segments(),
        voice_mapping=_private_reference_mapping(),
    )

    assert len(result.scenes) == 2
    assert all(scene.result.status == "passed" for scene in result.scenes)
