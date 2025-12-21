from __future__ import annotations

from pathlib import Path

from pipeline.state_machine import RunContext, State, run_until_done


def test_dreamweaver_mock_pipeline_uses_run_id_isolated_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    run_id = "run_123"
    ctx = RunContext(
        run_id=run_id,
        payload={"project_id": 1, "chapter_ids": [1], "source_text": "hello"},
    )

    ctx = run_until_done(ctx, max_steps=30)

    assert ctx.state == State.DONE
    assert (tmp_path / "runs" / "default").exists() is False

    merged_video = Path(ctx.payload["merged_video"])
    assert merged_video.exists()
    assert merged_video.as_posix().endswith(f"runs/{run_id}/merged.mp4")

    for frame in ctx.payload.get("keyframes", []):
        assert Path(frame["path"]).as_posix().startswith(f"runs/{run_id}/")

    for frame in ctx.payload.get("midframes", []):
        assert Path(frame["path"]).as_posix().startswith(f"runs/{run_id}/")

    for clip in ctx.payload.get("video_clips", []):
        assert Path(clip["path"]).as_posix().startswith(f"runs/{run_id}/")
