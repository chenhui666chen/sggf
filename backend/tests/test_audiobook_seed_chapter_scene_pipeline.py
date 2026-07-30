from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.scene_engine.chapter_pipeline import ChapterScenePipeline
from app.services.audiobook.scene_engine.planner import ScenePlanner
from app.services.audiobook.scene_engine.preview_reference_asset import (
    PreviewReferenceAsset,
    PreviewReferenceMaterializationError,
)
from app.services.audiobook.scene_engine.scene_renderer import SceneRenderResult
from app.services.audiobook.script_adapter_pkg._dataclasses import ScriptSegment


class FakeMaterializer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def materialize(self, config):
        self.calls.append(dict(config))
        if self.fail:
            raise PreviewReferenceMaterializationError("audio_not_decodable")
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
    def __init__(self, statuses: list[str] | None = None) -> None:
        self.statuses = list(statuses or [])
        self.calls: list[dict[str, Any]] = []

    def render(self, plan, **kwargs):
        self.calls.append({"plan": plan, **kwargs})
        outcome = self.statuses.pop(0) if self.statuses else "passed"
        status = "legacy_stems" if outcome == "quality_failure" else outcome
        passed = status == "passed"
        return SceneRenderResult(
            scene_id=plan.scene_id,
            status=status,
            action="assemble" if passed else "legacy_stems",
            attempts=1,
            audio_path=Path(f"{plan.scene_id}.mp3") if passed else None,
            subtitle_payload=None,
            quality_report=object() if outcome == "quality_failure" else None,
            fallback_reason=None if passed else "transcript_fidelity_failed",
        )


def _segment(
    text: str,
    *,
    speaker: str,
    scene: str,
    emotion: str = "tense",
    pause_after: float = 0.0,
) -> ScriptSegment:
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


def test_chapter_scene_pipeline_is_available() -> None:
    assert ChapterScenePipeline is not None


def test_chapter_pipeline_materializes_authorized_private_reference_once_per_chapter() -> None:
    materializer = FakeMaterializer()
    renderer = FakeRenderer()
    pipeline = ChapterScenePipeline(
        planner=_semantic_planner(),
        reference_materializer=materializer,
        renderer=renderer,
    )
    segments = [
        _segment(
            "她听着雨声，迟迟没有开口。",
            speaker="女主",
            scene="雨夜室内",
            pause_after=5,
        ),
        _segment(
            "列车进站后，她终于说出了真相。",
            speaker="女主",
            scene="清晨站台",
            emotion="sad",
        ),
    ]

    result = pipeline.render(
        segments,
        voice_mapping={
            "女主": {
                "voice_id": "mimo_design:owned",
                "tts_model": "mimo-v2.5-tts-voicedesign",
                "reference_source": "user_private",
                "reference_audio_url": "https://assets.example/reference.mp3",
                "voice_reference_asset_id": "ug-owned",
                "voice_reference_owner_user_id": 7,
            }
        },
    )

    assert len(result.scenes) == 2
    assert len(materializer.calls) == 1
    assert materializer.calls[0]["tts_model"] == "mimo-v2.5-tts-voicedesign"
    assert materializer.calls[0]["voice_id"] == "mimo_design:owned"
    assert materializer.calls[0]["preview_audio_url"] == (
        "https://assets.example/reference.mp3"
    )
    assert len(renderer.calls) == 2
    assert all(
        scene.plan.references == ({"audio_data": "MATERIALIZED_AUDIO"},)
        for scene in result.scenes
    )
    assert all(
        scene.reference_assets[0].sha256 == "reference-sha256"
        for scene in result.scenes
    )


def test_chapter_pipeline_keeps_native_seed_speaker_without_materialization() -> None:
    materializer = FakeMaterializer()
    renderer = FakeRenderer()
    pipeline = ChapterScenePipeline(
        reference_materializer=materializer,
        renderer=renderer,
    )

    result = pipeline.render(
        [_segment("太后冷冷地下令：试药。", speaker="太后", scene="宫殿内殿")],
        voice_mapping={
            "太后": {
                "voice_id": "zh_female_vv_uranus_bigtts",
                "tts_model": "seed-tts-2.0-expressive",
            }
        },
    )

    assert materializer.calls == []
    assert result.scenes[0].plan.references == (
        {"speaker": "zh_female_vv_uranus_bigtts"},
    )
    assert result.scenes[0].reference_assets == ()


def test_chapter_pipeline_continues_after_one_scene_render_falls_back() -> None:
    renderer = FakeRenderer(["legacy_stems", "passed"])
    pipeline = ChapterScenePipeline(
        planner=_semantic_planner(),
        reference_materializer=FakeMaterializer(),
        renderer=renderer,
    )
    checkpoints = {
        "scene_0001": {"checkpoint": 1},
        "scene_0002": {"checkpoint": 2},
    }

    result = pipeline.render(
        [
            _segment(
                "他站在门内，压低声音追问。",
                speaker="男主",
                scene="深夜室内",
                pause_after=5,
            ),
            _segment(
                "门外天光渐亮，她平静地回答。",
                speaker="女主",
                scene="清晨街道",
                emotion="calm",
            ),
        ],
        voice_mapping={},
        model="seed-audio-1.0-multilingual",
        audio_config={"sample_rate": 24000},
        checkpoints=checkpoints,
    )

    assert [scene.result.status for scene in result.scenes] == [
        "legacy_stems",
        "passed",
    ]
    assert len(renderer.calls) == 2
    assert [call["checkpoint"] for call in renderer.calls] == [
        checkpoints["scene_0001"],
        checkpoints["scene_0002"],
    ]
    assert all(
        call["model"] == "seed-audio-1.0-multilingual" for call in renderer.calls
    )
    assert all(
        call["audio_config"] == {"sample_rate": 24000} for call in renderer.calls
    )


def test_chapter_pipeline_limits_reference_failure_to_affected_scene() -> None:
    materializer = FakeMaterializer(fail=True)
    renderer = FakeRenderer()
    pipeline = ChapterScenePipeline(
        planner=_semantic_planner(),
        reference_materializer=materializer,
        renderer=renderer,
    )

    result = pipeline.render(
        [
            _segment(
                "男子在电话里追问证据的下落。",
                speaker="男子",
                scene="深夜室内",
                pause_after=5,
            ),
            _segment(
                "太后在晨光中下达了最后命令。",
                speaker="太后",
                scene="清晨宫殿",
                emotion="cold",
            ),
        ],
        voice_mapping={
            "男子": {
                "voice_id": "mimo_clone:owned",
                "tts_model": "mimo-v2.5-tts-voiceclone",
                "reference_source": "user_private",
                "reference_audio_url": "https://assets.example/broken.mp3",
                "voice_reference_asset_id": "ug-broken",
                "voice_reference_owner_user_id": 7,
            },
            "太后": {
                "voice_id": "zh_female_vv_uranus_bigtts",
                "tts_model": "seed-tts-2.0-expressive",
            },
        },
    )

    assert [scene.result.status for scene in result.scenes] == [
        "legacy_stems",
        "passed",
    ]
    assert result.scenes[0].result.fallback_reason == (
        "reference_materialization_failed:audio_not_decodable"
    )
    assert [call["plan"].scene_id for call in renderer.calls] == ["scene_0002"]


def test_chapter_pipeline_splits_quality_failure_once_and_replaces_parent_scene() -> None:
    renderer = FakeRenderer(["quality_failure", "passed", "passed"])
    pipeline = ChapterScenePipeline(
        planner=_semantic_planner(),
        reference_materializer=FakeMaterializer(),
        renderer=renderer,
    )
    segments = [
        _segment("审讯室里只剩钟表声。", speaker="旁白", scene="深夜审讯室"),
        _segment("男子低声追问证据在哪。", speaker="男子", scene="深夜审讯室"),
        _segment("女子沉默片刻后摇头。", speaker="女子", scene="深夜审讯室"),
        _segment("门外突然传来急促脚步。", speaker="旁白", scene="深夜审讯室"),
    ]

    result = pipeline.render(segments, voice_mapping={})

    assert len(renderer.calls) == 3
    assert [scene.plan.scene_id for scene in result.scenes] == [
        "scene_0001_split_01",
        "scene_0001_split_02",
    ]
    assert [scene.plan.source_segment_indices for scene in result.scenes] == [
        (0, 1),
        (2, 3),
    ]
    assert [scene.result.status for scene in result.scenes] == ["passed", "passed"]
    assert all(
        scene.result.metadata["split_parent_scene_id"] == "scene_0001"
        for scene in result.scenes
    )


def test_chapter_pipeline_does_not_recursively_split_failed_child_scene() -> None:
    renderer = FakeRenderer(["quality_failure", "quality_failure", "passed"])
    pipeline = ChapterScenePipeline(
        planner=_semantic_planner(),
        reference_materializer=FakeMaterializer(),
        renderer=renderer,
    )
    segments = [
        _segment("第一段对白保持完整。", speaker="男子", scene="电话场景"),
        _segment("第二段对白保持完整。", speaker="男子", scene="电话场景"),
        _segment("第三段对白保持完整。", speaker="男子", scene="电话场景"),
        _segment("第四段对白保持完整。", speaker="男子", scene="电话场景"),
    ]

    result = pipeline.render(segments, voice_mapping={})

    assert len(renderer.calls) == 3
    assert [scene.result.status for scene in result.scenes] == [
        "legacy_stems",
        "passed",
    ]
    assert result.scenes[0].result.metadata["split_parent_scene_id"] == "scene_0001"


def test_chapter_pipeline_does_not_split_single_segment_quality_failure() -> None:
    renderer = FakeRenderer(["quality_failure"])
    pipeline = ChapterScenePipeline(
        reference_materializer=FakeMaterializer(),
        renderer=renderer,
    )

    result = pipeline.render(
        [_segment("唯一一句台词必须原样保留。", speaker="旁白", scene="空房间")],
        voice_mapping={},
    )

    assert len(renderer.calls) == 1
    assert [scene.plan.scene_id for scene in result.scenes] == ["scene_0001"]
    assert result.scenes[0].result.status == "legacy_stems"


def test_chapter_pipeline_resumes_existing_split_topology_without_rerendering_parent() -> None:
    renderer = FakeRenderer(["passed", "passed"])
    pipeline = ChapterScenePipeline(
        planner=_semantic_planner(),
        reference_materializer=FakeMaterializer(),
        renderer=renderer,
    )
    segments = [
        _segment("第一段对白保持完整。", speaker="男子", scene="电话场景"),
        _segment("第二段对白保持完整。", speaker="男子", scene="电话场景"),
        _segment("第三段对白保持完整。", speaker="男子", scene="电话场景"),
        _segment("第四段对白保持完整。", speaker="男子", scene="电话场景"),
    ]
    checkpoints = {
        "scene_0001_split_01": {"status": "passed", "child": 1},
    }

    result = pipeline.render(
        segments,
        voice_mapping={},
        checkpoints=checkpoints,
    )

    assert [call["plan"].scene_id for call in renderer.calls] == [
        "scene_0001_split_01",
        "scene_0001_split_02",
    ]
    assert [call["checkpoint"] for call in renderer.calls] == [
        checkpoints["scene_0001_split_01"],
        None,
    ]
    assert [scene.plan.scene_id for scene in result.scenes] == [
        "scene_0001_split_01",
        "scene_0001_split_02",
    ]
