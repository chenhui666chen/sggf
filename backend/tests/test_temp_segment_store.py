from __future__ import annotations

import asyncio
import hashlib
import shutil
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.audiobook import temp_segment_store as temp_segment_store_module
from app.services.audiobook.background_jobs_shared import (
    build_checkpoint_patch_from_generation_result,
    compute_audio_project_totals,
)
from app.services.audiobook.engine_pkg._tts_mixin import TTSMixin
from app.services.audiobook.render_plan import (
    build_render_plan,
    render_chunks_to_timing_segments_payload,
    render_plan_to_payload,
)
from app.services.audiobook.tts_batch_planner import plan_tts_batches
from app.services.audiobook.tts_engine_pkg._base import TTSEngineBase
from app.services.audiobook.task_support import (
    _checkpoint_path_exists,
    _extract_checkpoint_segment_indices,
    _mark_checkpoint_recorded_segment_statuses,
)
from app.services.audiobook.temp_segment_janitor import (
    build_completed_checkpoint_cleanup_document,
    build_expired_checkpoint_cleanup_document,
    expire_chapter_run_temp_assets,
    finalize_completed_chapter_run_temp_assets,
)
from app.services.audiobook.temp_segment_store import (
    build_temp_segment_prefix,
    delete_temp_segment_prefix,
    extract_cached_segment_paths,
    load_cached_segment_audio,
    save_segment_audio_batch,
    save_segment_audio_map,
    temp_segment_asset_exists,
)


def _cleanup_run_assets(*, run_id: str, chapter_id: int) -> None:
    prefix_path = Path(build_temp_segment_prefix(run_id=run_id, chapter_id=chapter_id))
    shutil.rmtree(prefix_path.parent, ignore_errors=True)


class _DummyResumeTTSMixin(TTSMixin):
    async def _synthesize_segments(
        self,
        script_segments,
        debug_save_segments=False,
        debug_output_dir=None,
        progress_callback=None,
    ):
        audio_list = []
        total_segments = len(script_segments)
        batch_audio_list = []
        for index, segment in enumerate(script_segments):
            audio_bytes = f"generated::{segment.text}".encode("utf-8")
            audio_list.append(audio_bytes)
            batch_audio_list.append(audio_bytes)
            if progress_callback:
                progress_callback(
                    {
                        "event": "segment",
                        "batch_index": 0,
                        "num_batches": 1,
                        "start_idx": 0,
                        "end_idx": total_segments,
                        "segment_offset": index,
                        "segment_index": index,
                        "audio_bytes": audio_bytes,
                        "completed_segments": len(audio_list),
                        "total_segments": total_segments,
                        "successful_segments": len(audio_list),
                    }
                )
        if progress_callback:
            progress_callback(
                {
                    "event": "batch_completed",
                    "batch_index": 0,
                    "num_batches": 1,
                    "start_idx": 0,
                    "end_idx": total_segments,
                    "batch_audio_list": batch_audio_list,
                    "completed_segments": len(audio_list),
                    "total_segments": total_segments,
                    "successful_segments": len(audio_list),
                    "batch_successful_segments": len(audio_list),
                }
            )
        return audio_list


class _RecordingResumeTTSMixin(TTSMixin):
    def __init__(self):
        self.calls = []

    async def _synthesize_segments(
        self,
        script_segments,
        debug_save_segments=False,
        debug_output_dir=None,
        progress_callback=None,
    ):
        self.calls.append([getattr(segment, "text", "") for segment in script_segments])
        audio_list = []
        total_segments = len(script_segments)
        batch_audio_list = []
        for index, segment in enumerate(script_segments):
            audio_bytes = f"retried::{segment.text}".encode("utf-8")
            audio_list.append(audio_bytes)
            batch_audio_list.append(audio_bytes)
            if progress_callback:
                progress_callback(
                    {
                        "event": "segment",
                        "batch_index": 0,
                        "num_batches": 1,
                        "start_idx": 0,
                        "end_idx": total_segments,
                        "segment_offset": index,
                        "segment_index": index,
                        "audio_bytes": audio_bytes,
                        "segment_status": "succeeded",
                        "completed_segments": len(audio_list),
                        "total_segments": total_segments,
                        "successful_segments": len(audio_list),
                    }
                )
        if progress_callback:
            progress_callback(
                {
                    "event": "batch_completed",
                    "batch_index": 0,
                    "num_batches": 1,
                    "start_idx": 0,
                    "end_idx": total_segments,
                    "batch_audio_list": batch_audio_list,
                    "completed_segments": len(audio_list),
                    "total_segments": total_segments,
                    "successful_segments": len(audio_list),
                    "batch_successful_segments": len(audio_list),
                }
            )
        return audio_list


class _DummyFailingResumeTTSMixin(TTSMixin):
    async def _synthesize_segments(
        self,
        script_segments,
        debug_save_segments=False,
        debug_output_dir=None,
        progress_callback=None,
    ):
        audio_list = []
        total_segments = len(script_segments)
        for index, segment in enumerate(script_segments):
            if index == 1:
                audio_bytes = b""
                if progress_callback:
                    progress_callback(
                        {
                            "event": "segment",
                            "batch_index": 0,
                            "num_batches": 1,
                            "start_idx": 0,
                            "end_idx": total_segments,
                            "segment_offset": index,
                            "segment_index": index,
                            "audio_bytes": audio_bytes,
                            "segment_status": "failed",
                            "error_message": "provider_empty_audio",
                            "error_type": "EmptyAudio",
                            "completed_segments": index + 1,
                            "total_segments": total_segments,
                            "successful_segments": len([item for item in audio_list if item]),
                        }
                    )
                audio_list.append(audio_bytes)
                continue

            audio_bytes = f"generated::{segment.text}".encode("utf-8")
            audio_list.append(audio_bytes)
            if progress_callback:
                progress_callback(
                    {
                        "event": "segment",
                        "batch_index": 0,
                        "num_batches": 1,
                        "start_idx": 0,
                        "end_idx": total_segments,
                        "segment_offset": index,
                        "segment_index": index,
                        "audio_bytes": audio_bytes,
                        "segment_status": "succeeded",
                        "completed_segments": index + 1,
                        "total_segments": total_segments,
                        "successful_segments": len([item for item in audio_list if item]),
                    }
                )
        return audio_list


class _DummyBatchProgressTTSEngine(TTSEngineBase):
    async def synthesize(
        self,
        text,
        voice_params,
        emotion="neutral",
    ) -> bytes:
        return f"audio::{text}".encode("utf-8")


class _DummyFailingBatchProgressTTSEngine(TTSEngineBase):
    async def synthesize(
        self,
        text,
        voice_params,
        emotion="neutral",
    ) -> bytes:
        if text == "seg-fail":
            raise RuntimeError("provider exploded")
        return f"audio::{text}".encode("utf-8")


def test_save_segment_audio_batch_persists_files_and_metadata():
    run_id = f"pytest_{uuid.uuid4().hex}"
    chapter_id = 12
    audio_list = [b"segment-one", b"segment-two"]

    try:
        result = save_segment_audio_batch(
            run_id=run_id,
            chapter_id=chapter_id,
            audio_list=audio_list,
            format="mp3",
        )

        prefix_path = Path(result["temp_asset_prefix"])
        assert prefix_path.exists()
        assert result["segment_count"] == 2
        assert result["output_format"] == "mp3"

        first_path = Path(result["cached_audio_paths"][0])
        second_path = Path(result["cached_audio_paths"][1])
        assert first_path.exists()
        assert second_path.exists()
        assert first_path.read_bytes() == audio_list[0]
        assert second_path.read_bytes() == audio_list[1]

        first_segment = result["segments"]["0"]
        assert first_segment["status"] == "cached"
        assert first_segment["file_size"] == len(audio_list[0])
        assert first_segment["content_sha1"] == hashlib.sha1(audio_list[0]).hexdigest()
        assert first_segment["temp_object_key"] == first_path.as_posix()
    finally:
        _cleanup_run_assets(run_id=run_id, chapter_id=chapter_id)


def test_checkpoint_path_exists_detects_missing_temp_asset():
    run_id = f"pytest_{uuid.uuid4().hex}"
    chapter_id = 34

    try:
        result = save_segment_audio_batch(
            run_id=run_id,
            chapter_id=chapter_id,
            audio_list=[b"resume-check"],
            format="mp3",
        )

        cached_path = Path(result["cached_audio_paths"][0])
        assert _checkpoint_path_exists(cached_path.as_posix())

        cached_path.unlink()
        assert not _checkpoint_path_exists(cached_path.as_posix())
    finally:
        _cleanup_run_assets(run_id=run_id, chapter_id=chapter_id)


def test_delete_temp_segment_prefix_removes_only_expected_tree():
    run_id = f"pytest_{uuid.uuid4().hex}"
    chapter_id = 56

    try:
        result = save_segment_audio_batch(
            run_id=run_id,
            chapter_id=chapter_id,
            audio_list=[b"a", b"b", b"c"],
            format="mp3",
        )

        prefix_path = Path(result["temp_asset_prefix"])
        assert prefix_path.exists()

        removed_files = delete_temp_segment_prefix(result["temp_asset_prefix"])
        assert removed_files == 3
        assert not prefix_path.exists()
    finally:
        _cleanup_run_assets(run_id=run_id, chapter_id=chapter_id)


def test_extract_cached_segment_paths_merges_cached_paths_and_segments():
    checkpoint = {
        "cached_audio_paths": {"0": "segment_0.mp3"},
        "segments": {
            "1": {"index": 1, "temp_object_key": "segment_1.mp3"},
            "2": {"temp_object_key": "segment_2.mp3"},
            "bad": {"temp_object_key": ""},
        },
    }

    extracted = extract_cached_segment_paths(checkpoint)

    assert extracted == {
        0: "segment_0.mp3",
        1: "segment_1.mp3",
        2: "segment_2.mp3",
    }


def test_load_cached_segment_audio_reads_safe_temp_files():
    run_id = f"pytest_{uuid.uuid4().hex}"
    chapter_id = 66

    try:
        temp_cache = save_segment_audio_batch(
            run_id=run_id,
            chapter_id=chapter_id,
            audio_list=[b"zero", b"one", b"two"],
            format="mp3",
        )

        loaded = load_cached_segment_audio(
            {
                "cached_audio_paths": {
                    "0": temp_cache["cached_audio_paths"][0],
                    "2": temp_cache["cached_audio_paths"][2],
                    "99": "C:/unsafe/outside.mp3",
                }
            },
            max_segment_count=3,
        )

        assert loaded == {
            0: b"zero",
            2: b"two",
        }
    finally:
        _cleanup_run_assets(run_id=run_id, chapter_id=chapter_id)


def test_load_cached_segment_audio_skips_content_mismatch():
    run_id = f"pytest_{uuid.uuid4().hex}"
    chapter_id = 668

    try:
        temp_cache = save_segment_audio_batch(
            run_id=run_id,
            chapter_id=chapter_id,
            audio_list=[b"zero", b"one"],
            format="mp3",
        )
        Path(temp_cache["cached_audio_paths"][0]).write_bytes(b"ZERO")

        loaded = load_cached_segment_audio(temp_cache, max_segment_count=2)

        assert loaded == {1: b"one"}
    finally:
        _cleanup_run_assets(run_id=run_id, chapter_id=chapter_id)


def test_save_segment_audio_map_persists_sparse_segments():
    run_id = f"pytest_{uuid.uuid4().hex}"
    chapter_id = 67

    try:
        result = save_segment_audio_map(
            run_id=run_id,
            chapter_id=chapter_id,
            audio_map={
                2: b"two",
                "0": b"zero",
                "bad": b"skip",
                4: b"",
            },
            format="mp3",
        )

        assert result["segment_count"] == 2
        assert sorted(result["cached_audio_paths"].keys()) == [0, 2]
        assert Path(result["cached_audio_paths"][0]).read_bytes() == b"zero"
        assert Path(result["cached_audio_paths"][2]).read_bytes() == b"two"
    finally:
        _cleanup_run_assets(run_id=run_id, chapter_id=chapter_id)


def test_compute_audio_project_totals_counts_only_real_audio_rows():
    totals = compute_audio_project_totals(
        [
            SimpleNamespace(audio_path="a.mp3", duration=12.5, tts_cost=1.2, file_size=100),
            SimpleNamespace(audio_path="", duration=99.0, tts_cost=9.9, file_size=999),
            SimpleNamespace(audio_path="b.mp3", duration=7.5, tts_cost=0.8, file_size=50),
            SimpleNamespace(audio_path=None, duration=3.0, tts_cost=0.5, file_size=10),
        ]
    )

    assert totals.completed_chapters == 2
    assert totals.total_duration == 20.0
    assert totals.total_cost == 2.0
    assert totals.total_size == 150


def test_extract_checkpoint_segment_indices_derives_from_cached_material():
    checkpoint = {
        "cached_audio_paths": {"2": "segment_2.mp3"},
        "segments": {
            "0": {"temp_object_key": "segment_0.mp3"},
            "1": {"index": 1, "temp_object_key": "segment_1.mp3"},
        },
    }

    assert _extract_checkpoint_segment_indices(checkpoint) == [0, 1, 2]


def test_render_plan_builds_stable_tts_signatures():
    segment = SimpleNamespace(
        text="seg-0",
        speaker="Narrator",
        emotion="neutral",
        performance_notes="calm delivery",
        voice_params={"speaker": "voice-a", "pause_after": 1.0},
        type="narration",
    )

    first = build_render_plan([segment])
    second = build_render_plan([segment])

    assert len(first) == 1
    assert first[0].cache_key == second[0].cache_key
    assert first[0].voice_params["performance_notes"] == "calm delivery"
    assert render_plan_to_payload(first)[0]["source_segment_indices"] == [0]


def test_render_plan_splits_long_segments_and_keeps_terminal_pause_on_last_chunk():
    segment = SimpleNamespace(
        text=("甲" * 36) + "，" + ("乙" * 36) + "，" + ("丙" * 36) + "。[pause:2]",
        speaker="旁白",
        emotion="neutral",
        performance_notes="稳定叙述",
        voice_params={"speaker": "voice-a", "pause_after": 1.5},
        type="narration",
    )

    chunks = build_render_plan([segment], max_chunk_chars=80)
    timing_payload = render_chunks_to_timing_segments_payload(chunks)

    assert len(chunks) == 2
    assert [chunk.index for chunk in chunks] == [0, 1]
    assert all(chunk.source_segment_indices == [0] for chunk in chunks)
    assert all(len(chunk.text) <= 80 for chunk in chunks)
    assert chunks[0].voice_params["render_chunk_split"] is True
    assert chunks[0].voice_params["mixer_segment_type"] == "phrase"
    assert "pause_after" not in chunks[0].voice_params
    assert "pause_after_ms" not in chunks[0].voice_params
    assert chunks[1].voice_params["pause_after"] == 1.5
    assert chunks[1].voice_params["pause_after_ms"] == 2000
    assert timing_payload[0]["text"] == chunks[0].text
    assert timing_payload[1]["speaker"] == "旁白"


def test_tts_batch_planner_splits_by_voice_and_char_budget():
    segments = [
        {"text": "a" * 10, "voice_params": {"speaker": "voice-a"}},
        {"text": "b" * 10, "voice_params": {"speaker": "voice-a"}},
        {"text": "c" * 10, "voice_params": {"speaker": "voice-b"}},
        {"text": "d" * 50, "voice_params": {"speaker": "voice-b"}},
    ]

    batches = plan_tts_batches(segments, max_items=10, max_chars=25)

    assert [batch.segment_indices for batch in batches] == [[0, 1], [2], [3]]
    assert [batch.voice_key for batch in batches] == ["voice-a", "voice-b", "voice-b"]


def test_build_checkpoint_patch_from_generation_result_includes_completed_indices():
    patch = build_checkpoint_patch_from_generation_result(
        result={
            "temp_segment_cache": {
                "temp_asset_prefix": "backend/data/tmp/audiobook_runs/run_x/chapter_00001",
                "cached_audio_paths": {"2": "c.mp3", 0: "a.mp3"},
                "segments": {"0": {"temp_object_key": "a.mp3"}},
                "segment_statuses": {
                    "0": {
                        "index": 0,
                        "status": "cached",
                        "source": "tts_synthesis",
                        "recovery_stage": "temp_asset_saved",
                    },
                    "1": {
                        "index": 1,
                        "status": "pending",
                        "source": None,
                        "recovery_stage": "pending",
                    },
                },
                "failed_segment_indices": [1, "bad"],
                "failed_segment_errors": {
                    "1": {
                        "error_message": "provider_empty_audio",
                        "error_type": "EmptyAudio",
                    }
                },
                "render_plan_version": 1,
                "render_chunk_count": 2,
                "render_plan": [{"index": 0, "cache_key": "sig-0"}],
            }
        },
        task_id="task_123",
        output_path="audiobooks/project_1/chapter_001.mp3",
    )

    assert patch["engine_task_id"] == "task_123"
    assert patch["output_path"] == "audiobooks/project_1/chapter_001.mp3"
    assert patch["completed_segment_indices"] == [0, 2]
    assert patch["segment_statuses"]["0"]["status"] == "cached"
    assert patch["segment_statuses"]["0"]["recovery_stage"] == "temp_asset_saved"
    assert patch["segment_statuses"]["1"]["status"] == "pending"
    assert patch["segment_statuses"]["1"]["recovery_stage"] == "pending"
    assert patch["failed_segment_indices"] == [1]
    assert patch["failed_segment_errors"]["1"]["error_message"] == "provider_empty_audio"
    assert patch["render_plan_version"] == 1
    assert patch["render_chunk_count"] == 2
    assert patch["render_plan"] == [{"index": 0, "cache_key": "sig-0"}]


def test_build_checkpoint_patch_from_generation_result_includes_effect_timeline():
    patch = build_checkpoint_patch_from_generation_result(
        result={
            "effect_timeline": {
                "timeline": [
                    {"effect_id": "rain_light", "timestamp": 0.0},
                    {"effect_id": "door_open", "timestamp": 2.0},
                ],
            },
        },
        task_id="task_123",
        output_path="audiobooks/project_1/chapter_001.mp3",
    )

    assert patch["effect_timeline"] == {
        "timeline": [
            {"effect_id": "rain_light", "timestamp": 0.0},
            {"effect_id": "door_open", "timestamp": 2.0},
        ],
    }


def test_attach_render_plan_metadata_marks_temp_asset_saved_stage():
    temp_cache = {
        "cached_audio_paths": {
            0: "backend/data/tmp/audiobook_runs/run_x/chapter_00001/segment_00000_cache.mp3",
        },
    }
    metadata = {
        "segment_statuses": {
            "0": {
                "index": 0,
                "status": "cached",
                "source": "tts_synthesis",
                "recovery_stage": "synthesized",
            },
            "1": {
                "index": 1,
                "status": "pending",
                "source": None,
                "recovery_stage": "pending",
            },
        }
    }

    result = TTSMixin()._attach_render_plan_metadata(temp_cache, metadata)

    assert result["segment_statuses"]["0"]["recovery_stage"] == "temp_asset_saved"
    assert result["segment_statuses"]["0"]["source"] == "tts_synthesis"
    assert result["segment_statuses"]["1"]["recovery_stage"] == "pending"


def test_mark_checkpoint_recorded_segment_statuses_uses_checkpoint_paths():
    checkpoint = {
        "cached_audio_paths": {
            "0": "backend/data/tmp/audiobook_runs/run_x/chapter_00001/segment_00000_cache.mp3",
        },
        "segment_statuses": {
            "0": {
                "index": 0,
                "status": "cached",
                "source": "tts_synthesis",
                "recovery_stage": "temp_asset_saved",
            },
            "1": {
                "index": 1,
                "status": "cached",
                "source": "tts_synthesis",
                "recovery_stage": "synthesized",
            },
            "2": {
                "index": 2,
                "status": "pending",
                "source": None,
                "recovery_stage": "pending",
            },
        },
    }

    _mark_checkpoint_recorded_segment_statuses(checkpoint)

    assert checkpoint["segment_statuses"]["0"]["recovery_stage"] == "checkpoint_recorded"
    assert checkpoint["segment_statuses"]["1"]["recovery_stage"] == "synthesized"
    assert checkpoint["segment_statuses"]["2"]["recovery_stage"] == "pending"


def test_build_expired_checkpoint_cleanup_document_clears_resume_material():
    checkpoint = {
        "schema_version": 1,
        "status": "failed",
        "current_stage": "tts_synthesis",
        "temp_asset_prefix": "backend/data/tmp/audiobook_runs/run_x/chapter_00001",
        "cached_audio_paths": {0: "a.mp3"},
        "segments": {"0": {"temp_object_key": "a.mp3"}},
        "completed_segment_indices": [0, 1],
    }

    cleaned = build_expired_checkpoint_cleanup_document(
        checkpoint,
        removed_files=2,
    )

    assert cleaned["status"] == "expired"
    assert cleaned["current_stage"] == "expired"
    assert cleaned["temp_asset_prefix"] is None
    assert cleaned["cached_audio_paths"] == {}
    assert cleaned["segments"] == {}
    assert cleaned["completed_segment_indices"] == [0, 1]
    assert cleaned["cleanup"]["removed_temp_files"] == 2
    assert cleaned["last_error"] == "checkpoint_expired"


def test_build_completed_checkpoint_cleanup_document_prunes_temp_material_only():
    checkpoint = {
        "schema_version": 1,
        "status": "completed",
        "current_stage": "completed",
        "temp_asset_prefix": "backend/data/tmp/audiobook_runs/run_x/chapter_00001",
        "cached_audio_paths": {0: "a.mp3"},
        "segments": {"0": {"temp_object_key": "a.mp3"}},
        "completed_segment_indices": [0, 1],
        "output_path": "audiobooks/project_1/chapter_001.mp3",
        "last_error": "old_transient_error",
    }

    cleaned = build_completed_checkpoint_cleanup_document(
        checkpoint,
        removed_files=2,
    )

    assert cleaned["status"] == "completed"
    assert cleaned["current_stage"] == "completed"
    assert cleaned["temp_asset_prefix"] is None
    assert cleaned["cached_audio_paths"] == {}
    assert cleaned["segments"] == {}
    assert cleaned["completed_segment_indices"] == [0, 1]
    assert cleaned["output_path"] == "audiobooks/project_1/chapter_001.mp3"
    assert cleaned["cleanup"]["cleanup_reason"] == "completed_temp_assets_pruned"
    assert cleaned["cleanup"]["removed_temp_files"] == 2
    assert cleaned["expires_at"] is None
    assert cleaned["expired_at"] is None
    assert cleaned["last_error"] is None


def test_expire_chapter_run_temp_assets_marks_run_expired_and_deletes_files():
    run_id = f"pytest_{uuid.uuid4().hex}"
    chapter_id = 78

    try:
        temp_cache = save_segment_audio_batch(
            run_id=run_id,
            chapter_id=chapter_id,
            audio_list=[b"keep", b"clean"],
            format="mp3",
        )

        run = SimpleNamespace(
            id=123,
            chapter_id=chapter_id,
            status="failed",
            current_stage="tts_synthesis",
            resumable=True,
            temp_asset_prefix=temp_cache["temp_asset_prefix"],
            checkpoint_json={
                "schema_version": 1,
                "status": "failed",
                "current_stage": "tts_synthesis",
                "temp_asset_prefix": temp_cache["temp_asset_prefix"],
                "cached_audio_paths": temp_cache["cached_audio_paths"],
                "segments": temp_cache["segments"],
            },
            error_message=None,
            expires_at=None,
            finished_at=None,
        )

        summary = expire_chapter_run_temp_assets(run)

        assert summary["run_id"] == 123
        assert summary["removed_temp_files"] == 2
        assert run.status == "expired"
        assert run.current_stage == "expired"
        assert run.resumable is False
        assert run.temp_asset_prefix is None
        assert run.error_message == "checkpoint_expired"
        assert run.checkpoint_json["cached_audio_paths"] == {}
        assert run.checkpoint_json["segments"] == {}
        assert not Path(temp_cache["temp_asset_prefix"]).exists()
    finally:
        _cleanup_run_assets(run_id=run_id, chapter_id=chapter_id)


def test_finalize_completed_chapter_run_temp_assets_preserves_completed_state():
    run_id = f"pytest_{uuid.uuid4().hex}"
    chapter_id = 91

    try:
        temp_cache = save_segment_audio_batch(
            run_id=run_id,
            chapter_id=chapter_id,
            audio_list=[b"done", b"cleanup"],
            format="mp3",
        )

        run = SimpleNamespace(
            id=456,
            chapter_id=chapter_id,
            status="completed",
            current_stage="completed",
            resumable=True,
            temp_asset_prefix=temp_cache["temp_asset_prefix"],
            checkpoint_json={
                "schema_version": 1,
                "status": "completed",
                "current_stage": "completed",
                "temp_asset_prefix": temp_cache["temp_asset_prefix"],
                "cached_audio_paths": temp_cache["cached_audio_paths"],
                "segments": temp_cache["segments"],
                "completed_segment_indices": [0, 1],
                "output_path": "audiobooks/project_1/chapter_091.mp3",
                "last_error": "stale_error",
            },
            error_message="stale_error",
            expires_at=None,
            finished_at=None,
        )

        summary = finalize_completed_chapter_run_temp_assets(run)

        assert summary["run_id"] == 456
        assert summary["removed_temp_files"] == 2
        assert run.status == "completed"
        assert run.current_stage == "completed"
        assert run.resumable is False
        assert run.temp_asset_prefix is None
        assert run.error_message is None
        assert run.expires_at is None
        assert run.checkpoint_json["cached_audio_paths"] == {}
        assert run.checkpoint_json["segments"] == {}
        assert run.checkpoint_json["completed_segment_indices"] == [0, 1]
        assert run.checkpoint_json["output_path"] == "audiobooks/project_1/chapter_091.mp3"
        assert run.checkpoint_json["cleanup"]["cleanup_reason"] == "completed_temp_assets_pruned"
        assert run.checkpoint_json["last_error"] is None
        assert not Path(temp_cache["temp_asset_prefix"]).exists()
    finally:
        _cleanup_run_assets(run_id=run_id, chapter_id=chapter_id)


def test_synthesize_segments_with_resume_reuses_cached_audio_and_only_generates_missing():
    run_id = f"pytest_{uuid.uuid4().hex}"
    chapter_id = 92

    try:
        temp_cache = save_segment_audio_batch(
            run_id=run_id,
            chapter_id=chapter_id,
            audio_list=[b"cached-0", b"cached-1", b"cached-2"],
            format="mp3",
        )
        dummy = _DummyResumeTTSMixin()
        script_segments = [
            SimpleNamespace(text="seg-0"),
            SimpleNamespace(text="seg-1"),
            SimpleNamespace(text="seg-2"),
        ]

        result = asyncio.run(
            dummy._synthesize_segments_with_resume(
                script_segments,
                resume_checkpoint={
                    "total_segments": 3,
                    "cached_audio_paths": {
                        "0": temp_cache["cached_audio_paths"][0],
                    },
                    "source_checkpoint": {
                        "total_segments": 3,
                        "cached_audio_paths": {
                            "2": temp_cache["cached_audio_paths"][2],
                        },
                    },
                },
            )
        )

        assert result["resume_source"] == "current_checkpoint+source_checkpoint"
        assert result["reused_indices"] == [0, 2]
        assert result["synthesized_indices"] == [1]
        assert result["audio_list"] == [
            b"cached-0",
            b"generated::seg-1",
            b"cached-2",
        ]
    finally:
        _cleanup_run_assets(run_id=run_id, chapter_id=chapter_id)


def test_synthesize_segments_with_resume_skips_stale_render_signature():
    run_id = f"pytest_{uuid.uuid4().hex}"
    chapter_id = 925

    try:
        temp_cache = save_segment_audio_batch(
            run_id=run_id,
            chapter_id=chapter_id,
            audio_list=[b"cached-stale"],
            format="mp3",
        )
        stale_plan = render_plan_to_payload(build_render_plan([SimpleNamespace(text="old-text")]))
        dummy = _DummyResumeTTSMixin()

        result = asyncio.run(
            dummy._synthesize_segments_with_resume(
                [SimpleNamespace(text="new-text")],
                resume_checkpoint={
                    "total_segments": 1,
                    "cached_audio_paths": {
                        "0": temp_cache["cached_audio_paths"][0],
                    },
                    "render_plan": stale_plan,
                },
            )
        )

        assert result["reused_indices"] == []
        assert result["synthesized_indices"] == [0]
        assert result["audio_list"] == [b"generated::new-text"]
    finally:
        _cleanup_run_assets(run_id=run_id, chapter_id=chapter_id)


def test_synthesize_segments_with_resume_remaps_cached_audio_by_render_signature():
    run_id = f"pytest_{uuid.uuid4().hex}"
    chapter_id = 926

    try:
        old_segments = [
            SimpleNamespace(text="removed"),
            SimpleNamespace(text="kept"),
        ]
        temp_cache = save_segment_audio_batch(
            run_id=run_id,
            chapter_id=chapter_id,
            audio_list=[b"cached-removed", b"cached-kept"],
            format="mp3",
        )
        dummy = _DummyResumeTTSMixin()

        result = asyncio.run(
            dummy._synthesize_segments_with_resume(
                [SimpleNamespace(text="kept")],
                resume_checkpoint={
                    "total_segments": 2,
                    "cached_audio_paths": {
                        "0": temp_cache["cached_audio_paths"][0],
                        "1": temp_cache["cached_audio_paths"][1],
                    },
                    "render_plan": render_plan_to_payload(build_render_plan(old_segments)),
                },
            )
        )

        assert result["reused_indices"] == [0]
        assert result["synthesized_indices"] == []
        assert result["audio_list"] == [b"cached-kept"]
    finally:
        _cleanup_run_assets(run_id=run_id, chapter_id=chapter_id)


def test_synthesize_segments_with_resume_falls_back_to_source_checkpoint():
    run_id = f"pytest_{uuid.uuid4().hex}"
    chapter_id = 93

    try:
        temp_cache = save_segment_audio_batch(
            run_id=run_id,
            chapter_id=chapter_id,
            audio_list=[b"cached-source"],
            format="mp3",
        )
        dummy = _DummyResumeTTSMixin()
        script_segments = [SimpleNamespace(text="seg-0")]

        result = asyncio.run(
            dummy._synthesize_segments_with_resume(
                script_segments,
                resume_checkpoint={
                    "total_segments": 99,
                    "cached_audio_paths": {
                        "0": temp_cache["cached_audio_paths"][0],
                    },
                    "source_checkpoint": {
                        "total_segments": 1,
                        "cached_audio_paths": {
                            "0": temp_cache["cached_audio_paths"][0],
                        },
                    },
                },
            )
        )

        assert result["resume_source"] == "source_checkpoint"
        assert result["reused_indices"] == [0]
        assert result["synthesized_indices"] == []
        assert result["audio_list"] == [b"cached-source"]
    finally:
        _cleanup_run_assets(run_id=run_id, chapter_id=chapter_id)


def test_synthesize_segments_with_resume_reports_incremental_progress_payloads():
    run_id = f"pytest_{uuid.uuid4().hex}"
    chapter_id = 94
    progress_events = []

    try:
        temp_cache = save_segment_audio_batch(
            run_id=run_id,
            chapter_id=chapter_id,
            audio_list=[b"cached-0"],
            format="mp3",
        )
        dummy = _DummyResumeTTSMixin()
        script_segments = [
            SimpleNamespace(text="seg-0"),
            SimpleNamespace(text="seg-1"),
            SimpleNamespace(text="seg-2"),
        ]

        asyncio.run(
            dummy._synthesize_segments_with_resume(
                script_segments,
                resume_checkpoint={
                    "total_segments": 3,
                    "cached_audio_paths": {
                        "0": temp_cache["cached_audio_paths"][0],
                    },
                },
                progress_callback=progress_events.append,
            )
        )

        completed_states = [event["completed_segment_indices"] for event in progress_events]

        assert len(progress_events) >= 3
        assert progress_events[0]["completed_segment_indices"] == [0]
        assert progress_events[0]["progress"] == (1 / 3)
        assert progress_events[0]["segment_statuses"]["0"] == {
            "index": 0,
            "status": "cached",
            "source": "resume_cache",
            "recovery_stage": "cache_loaded",
        }
        assert progress_events[0]["segment_statuses"]["1"] == {
            "index": 1,
            "status": "pending",
            "source": None,
            "recovery_stage": "pending",
        }
        assert [0, 1] in completed_states
        assert completed_states.index([0, 1]) < completed_states.index([0, 1, 2])
        middle_event = next(
            event
            for event in progress_events
            if event["completed_segment_indices"] == [0, 1]
        )
        assert middle_event["progress"] == (2 / 3)
        assert middle_event["synthesized_indices"] == [1]
        assert middle_event["segment_statuses"]["1"] == {
            "index": 1,
            "status": "cached",
            "source": "tts_synthesis",
            "recovery_stage": "synthesized",
        }
        assert progress_events[-1]["completed_segment_indices"] == [0, 1, 2]
        assert progress_events[-1]["progress"] == 1.0
        assert progress_events[-1]["synthesized_indices"] == [1, 2]
        assert progress_events[-1]["segment_statuses"]["2"] == {
            "index": 2,
            "status": "cached",
            "source": "tts_synthesis",
            "recovery_stage": "synthesized",
        }
    finally:
        _cleanup_run_assets(run_id=run_id, chapter_id=chapter_id)


def test_synthesize_segments_with_resume_reports_failed_segment_status():
    dummy = _DummyFailingResumeTTSMixin()
    progress_events = []
    script_segments = [
        SimpleNamespace(text="seg-0"),
        SimpleNamespace(text="seg-1"),
        SimpleNamespace(text="seg-2"),
    ]

    result = asyncio.run(
        dummy._synthesize_segments_with_resume(
            script_segments,
            resume_checkpoint={},
            progress_callback=progress_events.append,
        )
    )

    assert result["audio_list"] == [
        b"generated::seg-0",
        b"",
        b"generated::seg-2",
    ]
    assert result["synthesized_indices"] == [0, 2]
    assert result["failed_segment_indices"] == [1]
    assert result["failed_segment_errors"]["1"] == {
        "error_message": "provider_empty_audio",
        "error_type": "EmptyAudio",
    }
    assert result["segment_statuses"]["1"] == {
        "index": 1,
        "status": "failed",
        "source": "tts_synthesis",
        "recovery_stage": "failed",
        "error": {
            "error_message": "provider_empty_audio",
            "error_type": "EmptyAudio",
        },
    }
    failed_event = next(
        event
        for event in progress_events
        if event.get("failed_segment_indices") == [1]
    )
    assert failed_event["segment_statuses"]["1"]["status"] == "failed"
    assert failed_event["failed_segment_errors"]["1"]["error_type"] == "EmptyAudio"


def test_synthesize_segments_with_resume_retries_only_failed_segment_from_checkpoint():
    run_id = f"pytest_{uuid.uuid4().hex}"
    chapter_id = 941
    script_segments = [
        SimpleNamespace(text="seg-0"),
        SimpleNamespace(text="seg-1"),
        SimpleNamespace(text="seg-2"),
    ]

    try:
        failing_dummy = _DummyFailingResumeTTSMixin()
        first_result = asyncio.run(
            failing_dummy._synthesize_segments_with_resume(
                script_segments,
                resume_checkpoint={},
            )
        )
        temp_cache = save_segment_audio_map(
            run_id=run_id,
            chapter_id=chapter_id,
            audio_map={
                index: audio_bytes
                for index, audio_bytes in enumerate(first_result["audio_list"])
                if audio_bytes
            },
            format="mp3",
        )
        temp_cache = failing_dummy._attach_render_plan_metadata(temp_cache, first_result)
        retry_checkpoint = build_checkpoint_patch_from_generation_result(
            result={"temp_segment_cache": temp_cache},
            task_id="retry_task",
            output_path="audiobooks/project_1/chapter_941.mp3",
        )
        retry_dummy = _RecordingResumeTTSMixin()

        retry_result = asyncio.run(
            retry_dummy._synthesize_segments_with_resume(
                script_segments,
                resume_checkpoint=retry_checkpoint,
            )
        )

        assert retry_dummy.calls == [["seg-1"]]
        assert retry_result["reused_indices"] == [0, 2]
        assert retry_result["synthesized_indices"] == [1]
        assert retry_result["failed_segment_indices"] == []
        assert retry_result["audio_list"] == [
            b"generated::seg-0",
            b"retried::seg-1",
            b"generated::seg-2",
        ]
        assert retry_result["segment_statuses"]["0"]["source"] == "resume_cache"
        assert retry_result["segment_statuses"]["1"]["source"] == "tts_synthesis"
        assert retry_result["segment_statuses"]["2"]["source"] == "resume_cache"
        assert retry_checkpoint["failed_segment_indices"] == [1]
        assert retry_checkpoint["segment_statuses"]["1"]["recovery_stage"] == "failed"
    finally:
        _cleanup_run_assets(run_id=run_id, chapter_id=chapter_id)


def test_synthesize_batch_emits_segment_progress_before_batch_completed():
    engine = _DummyBatchProgressTTSEngine(
        enable_cache=False,
        max_concurrent=1,
        request_delay=0,
    )
    progress_events = []

    audio_list = asyncio.run(
        engine.synthesize_batch(
            [
                {"text": "seg-0", "voice_params": {}, "emotion": "neutral"},
                {"text": "seg-1", "voice_params": {}, "emotion": "neutral"},
            ],
            batch_size=2,
            batch_interval=0,
            progress_callback=progress_events.append,
        )
    )

    assert audio_list == [b"audio::seg-0", b"audio::seg-1"]
    assert [event["event"] for event in progress_events] == [
        "segment",
        "segment",
        "batch_completed",
    ]
    assert progress_events[0]["segment_index"] == 0
    assert progress_events[0]["audio_bytes"] == b"audio::seg-0"
    assert progress_events[0]["successful_segments"] == 1
    assert progress_events[1]["segment_index"] == 1
    assert progress_events[1]["audio_bytes"] == b"audio::seg-1"
    assert progress_events[1]["successful_segments"] == 2


def test_synthesize_batch_reports_segment_failure_reason():
    engine = _DummyFailingBatchProgressTTSEngine(
        enable_cache=False,
        max_concurrent=1,
        request_delay=0,
    )
    progress_events = []

    audio_list = asyncio.run(
        engine.synthesize_batch(
            [
                {"text": "seg-ok", "voice_params": {}, "emotion": "neutral"},
                {"text": "seg-fail", "voice_params": {}, "emotion": "neutral"},
            ],
            batch_size=2,
            batch_interval=0,
            progress_callback=progress_events.append,
        )
    )

    assert audio_list == [b"audio::seg-ok", b""]
    failed_event = progress_events[1]
    assert failed_event["event"] == "segment"
    assert failed_event["segment_index"] == 1
    assert failed_event["segment_status"] == "failed"
    assert failed_event["error_message"] == "provider exploded"
    assert failed_event["error_type"] == "RuntimeError"
    assert failed_event["successful_segments"] == 1


def test_synthesize_batch_uses_planned_voice_boundaries():
    engine = _DummyBatchProgressTTSEngine(
        enable_cache=False,
        max_concurrent=1,
        request_delay=0,
    )
    progress_events = []

    audio_list = asyncio.run(
        engine.synthesize_batch(
            [
                {"text": "seg-0", "voice_params": {"speaker": "voice-a"}, "emotion": "neutral"},
                {"text": "seg-1", "voice_params": {"speaker": "voice-b"}, "emotion": "neutral"},
            ],
            batch_size=10,
            batch_interval=0,
            progress_callback=progress_events.append,
        )
    )

    batch_events = [event for event in progress_events if event["event"] == "batch_completed"]

    assert audio_list == [b"audio::seg-0", b"audio::seg-1"]
    assert len(batch_events) == 2
    assert batch_events[0]["start_idx"] == 0
    assert batch_events[0]["end_idx"] == 1
    assert batch_events[1]["start_idx"] == 1
    assert batch_events[1]["end_idx"] == 2
    assert batch_events[0]["batch_audio_list"] == [b"audio::seg-0"]
    assert batch_events[1]["batch_audio_list"] == [b"audio::seg-1"]


def test_save_segment_audio_batch_supports_dashscope_oss(monkeypatch):
    upload_calls = []
    head_calls = []

    monkeypatch.setenv("AUDIOBOOK_TEMP_SEGMENT_STORAGE_DRIVER", "dashscope_oss")
    monkeypatch.setenv("AUDIOBOOK_TEMP_SEGMENT_OSS_PREFIX", "tmp/audiobook_runs")
    monkeypatch.setenv("AUDIOBOOK_TEMP_SEGMENT_OSS_PUBLIC_HOST", "https://oss.example.com")

    monkeypatch.setattr(
        temp_segment_store_module,
        "_get_dashscope_upload_policy",
        lambda model: {
            "upload_host": "https://upload.example.com",
            "oss_access_key_id": "test-access-key",
            "signature": "test-signature",
            "policy": "test-policy",
            "x_oss_object_acl": "private",
            "x_oss_forbid_overwrite": "false",
        },
    )

    def _fake_head(url, timeout=15.0):
        head_calls.append((url, timeout))
        return httpx.Response(404, request=httpx.Request("HEAD", url))

    def _fake_post(url, data=None, files=None, timeout=30.0):
        upload_calls.append(
            {
                "url": url,
                "key": dict(data or {}).get("key"),
                "timeout": timeout,
                "filename": (files or {}).get("file", ("",))[0],
            }
        )
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(temp_segment_store_module.httpx, "head", _fake_head)
    monkeypatch.setattr(temp_segment_store_module.httpx, "post", _fake_post)

    result = save_segment_audio_batch(
        run_id="oss_pytest_run",
        chapter_id=101,
        audio_list=[b"segment-one", b"segment-two"],
        format="mp3",
    )

    assert result["storage_driver"] == "dashscope_oss"
    assert result["temp_asset_prefix"] == "oss://tmp/audiobook_runs/oss_pytest_run/chapter_00101"
    assert result["segment_count"] == 2
    assert sorted(result["cached_audio_paths"].keys()) == [0, 1]
    assert result["cached_audio_paths"][0].startswith("oss://tmp/audiobook_runs/oss_pytest_run/chapter_00101/")
    assert result["segments"]["0"]["temp_object_key"] == result["cached_audio_paths"][0]
    assert len(head_calls) == 2
    assert len(upload_calls) == 2
    assert upload_calls[0]["url"] == "https://upload.example.com"
    assert upload_calls[0]["key"].startswith("tmp/audiobook_runs/oss_pytest_run/chapter_00101/segment_00000_")


def test_load_cached_segment_audio_supports_oss_paths(monkeypatch):
    monkeypatch.setenv("AUDIOBOOK_TEMP_SEGMENT_OSS_PUBLIC_HOST", "https://oss.example.com")

    def _fake_get(url, timeout=30.0, headers=None):
        assert headers is None
        if url.endswith("segment_00000_cache.mp3"):
            return httpx.Response(200, content=b"oss-zero", request=httpx.Request("GET", url))
        if url.endswith("segment_00002_cache.mp3"):
            return httpx.Response(200, content=b"oss-two", request=httpx.Request("GET", url))
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(temp_segment_store_module.httpx, "get", _fake_get)

    loaded = load_cached_segment_audio(
        {
            "cached_audio_paths": {
                "0": "oss://tmp/audiobook_runs/run_x/chapter_00001/segment_00000_cache.mp3",
                "2": "oss://tmp/audiobook_runs/run_x/chapter_00001/segment_00002_cache.mp3",
                "9": "oss://tmp/audiobook_runs/run_x/chapter_00001/segment_00009_missing.mp3",
            }
        },
        max_segment_count=3,
    )

    assert loaded == {
        0: b"oss-zero",
        2: b"oss-two",
    }


def test_temp_segment_asset_exists_supports_oss_paths(monkeypatch):
    monkeypatch.setenv("AUDIOBOOK_TEMP_SEGMENT_OSS_PUBLIC_HOST", "https://oss.example.com")

    def _fake_head(url, timeout=15.0):
        if url.endswith("segment_00000_cache.mp3"):
            return httpx.Response(200, request=httpx.Request("HEAD", url))
        return httpx.Response(404, request=httpx.Request("HEAD", url))

    monkeypatch.setattr(temp_segment_store_module.httpx, "head", _fake_head)

    assert temp_segment_asset_exists("oss://tmp/audiobook_runs/run_x/chapter_00001/segment_00000_cache.mp3") is True
    assert temp_segment_asset_exists("oss://tmp/audiobook_runs/run_x/chapter_00001/segment_99999_missing.mp3") is False


def test_delete_temp_segment_prefix_allows_oss_prefix_without_delete_capability():
    removed_files = delete_temp_segment_prefix(
        "oss://tmp/audiobook_runs/run_x/chapter_00001",
        checkpoint_json={
            "cached_audio_paths": {
                "0": "oss://tmp/audiobook_runs/run_x/chapter_00001/segment_00000_cache.mp3",
            },
            "segments": {
                "0": {
                    "index": 0,
                    "temp_object_key": "oss://tmp/audiobook_runs/run_x/chapter_00001/segment_00000_cache.mp3",
                }
            },
        },
    )

    assert removed_files == 0


def test_delete_temp_segment_prefix_deletes_oss_assets_with_direct_credentials(monkeypatch):
    delete_calls = []

    monkeypatch.setenv("AUDIOBOOK_TEMP_SEGMENT_OSS_DELETE_HOST", "https://dashscope-temp.oss-cn-hangzhou.aliyuncs.com")
    monkeypatch.setenv("AUDIOBOOK_TEMP_SEGMENT_OSS_DELETE_BUCKET", "dashscope-temp")
    monkeypatch.setenv("AUDIOBOOK_TEMP_SEGMENT_OSS_DELETE_ACCESS_KEY_ID", "test-ak")
    monkeypatch.setenv("AUDIOBOOK_TEMP_SEGMENT_OSS_DELETE_ACCESS_KEY_SECRET", "test-sk")
    monkeypatch.setenv("AUDIOBOOK_TEMP_SEGMENT_OSS_DELETE_SECURITY_TOKEN", "test-token")

    def _fake_delete(url, headers=None, timeout=20.0):
        delete_calls.append(
            {
                "url": url,
                "headers": dict(headers or {}),
                "timeout": timeout,
            }
        )
        return httpx.Response(204, request=httpx.Request("DELETE", url))

    monkeypatch.setattr(temp_segment_store_module.httpx, "delete", _fake_delete)

    removed_files = delete_temp_segment_prefix(
        "oss://tmp/audiobook_runs/run_x/chapter_00001",
        checkpoint_json={
            "cached_audio_paths": {
                "0": "oss://tmp/audiobook_runs/run_x/chapter_00001/segment_00000_cache.mp3",
                "1": "oss://tmp/audiobook_runs/run_x/chapter_00001/segment_00001_cache.mp3",
            },
            "segments": {
                "0": {
                    "index": 0,
                    "temp_object_key": "oss://tmp/audiobook_runs/run_x/chapter_00001/segment_00000_cache.mp3",
                },
                "1": {
                    "index": 1,
                    "temp_object_key": "oss://tmp/audiobook_runs/run_x/chapter_00001/segment_00001_cache.mp3",
                },
            },
        },
    )

    assert removed_files == 2
    assert len(delete_calls) == 2
    assert delete_calls[0]["url"] == (
        "https://dashscope-temp.oss-cn-hangzhou.aliyuncs.com/"
        "tmp/audiobook_runs/run_x/chapter_00001/segment_00000_cache.mp3"
    )
    assert delete_calls[0]["headers"]["Authorization"].startswith("OSS test-ak:")
    assert delete_calls[0]["headers"]["x-oss-security-token"] == "test-token"
    assert delete_calls[0]["timeout"] == 20.0


def test_finalize_completed_chapter_run_temp_assets_accepts_oss_prefix_cleanup():
    run = SimpleNamespace(
        id=789,
        chapter_id=102,
        status="completed",
        current_stage="completed",
        resumable=True,
        temp_asset_prefix="oss://tmp/audiobook_runs/run_x/chapter_00102",
        checkpoint_json={
            "schema_version": 1,
            "status": "completed",
            "current_stage": "completed",
            "temp_asset_prefix": "oss://tmp/audiobook_runs/run_x/chapter_00102",
            "cached_audio_paths": {
                "0": "oss://tmp/audiobook_runs/run_x/chapter_00102/segment_00000_cache.mp3",
            },
            "segments": {
                "0": {
                    "index": 0,
                    "temp_object_key": "oss://tmp/audiobook_runs/run_x/chapter_00102/segment_00000_cache.mp3",
                }
            },
            "completed_segment_indices": [0],
            "output_path": "audiobooks/project_1/chapter_102.mp3",
        },
        error_message=None,
        expires_at=None,
        finished_at=None,
    )

    summary = finalize_completed_chapter_run_temp_assets(run)

    assert summary["run_id"] == 789
    assert summary["removed_temp_files"] == 0
    assert run.resumable is False
    assert run.temp_asset_prefix is None
    assert run.checkpoint_json["cached_audio_paths"] == {}
    assert run.checkpoint_json["segments"] == {}


def test_finalize_completed_chapter_run_temp_assets_reports_oss_cleanup_count(monkeypatch):
    delete_calls = []

    monkeypatch.setenv("AUDIOBOOK_TEMP_SEGMENT_OSS_DELETE_HOST", "https://dashscope-temp.oss-cn-hangzhou.aliyuncs.com")
    monkeypatch.setenv("AUDIOBOOK_TEMP_SEGMENT_OSS_DELETE_BUCKET", "dashscope-temp")
    monkeypatch.setenv("AUDIOBOOK_TEMP_SEGMENT_OSS_DELETE_ACCESS_KEY_ID", "test-ak")
    monkeypatch.setenv("AUDIOBOOK_TEMP_SEGMENT_OSS_DELETE_ACCESS_KEY_SECRET", "test-sk")

    def _fake_delete(url, headers=None, timeout=20.0):
        delete_calls.append((url, dict(headers or {}), timeout))
        return httpx.Response(204, request=httpx.Request("DELETE", url))

    monkeypatch.setattr(temp_segment_store_module.httpx, "delete", _fake_delete)

    run = SimpleNamespace(
        id=790,
        chapter_id=103,
        status="completed",
        current_stage="completed",
        resumable=True,
        temp_asset_prefix="oss://tmp/audiobook_runs/run_x/chapter_00103",
        checkpoint_json={
            "schema_version": 1,
            "status": "completed",
            "current_stage": "completed",
            "temp_asset_prefix": "oss://tmp/audiobook_runs/run_x/chapter_00103",
            "cached_audio_paths": {
                "0": "oss://tmp/audiobook_runs/run_x/chapter_00103/segment_00000_cache.mp3",
            },
            "segments": {
                "0": {
                    "index": 0,
                    "temp_object_key": "oss://tmp/audiobook_runs/run_x/chapter_00103/segment_00000_cache.mp3",
                }
            },
            "completed_segment_indices": [0],
            "output_path": "audiobooks/project_1/chapter_103.mp3",
        },
        error_message=None,
        expires_at=None,
        finished_at=None,
    )

    summary = finalize_completed_chapter_run_temp_assets(run)

    assert summary["run_id"] == 790
    assert summary["removed_temp_files"] == 1
    assert len(delete_calls) == 1
    assert run.resumable is False
    assert run.temp_asset_prefix is None
    assert run.checkpoint_json["cached_audio_paths"] == {}
    assert run.checkpoint_json["segments"] == {}
