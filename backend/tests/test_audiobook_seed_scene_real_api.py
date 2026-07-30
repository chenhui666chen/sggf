from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from adapters.registry import registry
from app.services.audiobook.scene_engine.chapter_pipeline import ChapterScenePipeline
from app.services.audiobook.scene_engine.preview_reference_asset import (
    PreviewReferenceMaterializer,
)
from app.services.audiobook.scene_engine.scene_assembler import SceneAudioAssembler
from app.services.audiobook.scene_engine.scene_renderer import SceneRenderService
from app.services.audiobook.script_adapter_pkg._dataclasses import ScriptSegment


@pytest.mark.skipif(
    os.getenv("RUN_DOUBAO_SEED_SCENE_REAL_API") != "1",
    reason="requires an explicit paid Seed Audio integration run",
)
def test_real_seed_scene_pipeline_renders_and_assembles_short_chapter(
    tmp_path: Path,
) -> None:
    adapter = registry.get_adapter("seed-audio-1.0")
    assert adapter is not None
    checkpoints = []
    pipeline = ChapterScenePipeline(
        reference_materializer=PreviewReferenceMaterializer(
            output_root=tmp_path / "references"
        ),
        renderer=SceneRenderService(
            adapter=adapter,
            output_root=tmp_path / "renders",
            checkpoint_writer=checkpoints.append,
            max_retries=0,
        ),
    )
    segments = [
        ScriptSegment(
            type="narration",
            text="雨停以后，旧城的钟声从远处缓缓传来。",
            speaker="旁白",
            emotion="calm",
            performance_notes="沉稳、清晰，语速稍慢，句尾自然收住",
            instruct_scene="清晨旧城街道，雨后的环境声轻微持续",
        )
    ]

    pipeline_result = pipeline.render(segments, voice_mapping={})

    assert len(pipeline_result.scenes) == 1
    scene = pipeline_result.scenes[0]
    assert scene.result.status == "passed"
    assert scene.result.audio_path is not None and scene.result.audio_path.exists()
    assert checkpoints[-1]["status"] == "passed"

    assembly = SceneAudioAssembler().assemble(
        pipeline_result.scenes,
        output_path=tmp_path / "chapter.wav",
        output_format="wav",
    )

    assert assembly.audio_path.exists()
    assert assembly.duration_s > 0
    assert len(assembly.scene_timings) == 1
