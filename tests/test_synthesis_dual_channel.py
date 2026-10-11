# -*- coding: utf-8 -*-
"""Phase 2.7 合成双通道测试：编码基线 / 产物校验 / 剪映草稿导出 / 双通道编排 / editor CRF 注入。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------- 编码基线
def test_encoding_baseline_controlled():
    from agents.synthesis_kit import ENCODING_BASELINE, encoder_args
    assert ENCODING_BASELINE["vcodec"] == "libx264"
    assert 18 <= ENCODING_BASELINE["crf"] <= 23
    assert ENCODING_BASELINE["pix_fmt"] == "yuv420p"
    assert ENCODING_BASELINE["movflags"] == "+faststart"
    args = encoder_args()
    assert "-crf" in args and "20" in args
    assert "-movflags" in args and "+faststart" in args


def test_editor_source_has_crf_baseline():
    """editor.py 的重编码命令已注入 CRF 基线（源码级断言，防回归）。"""
    src = Path("agents/editor.py").read_text(encoding="utf-8")
    assert '"-crf", "20"' in src, "editor 重编码必须带 CRF 基线"
    assert src.count('"-crf", "20"') >= 2, "字幕滤镜与重编码两条路径都要有基线"


# ---------------------------------------------------------------- 产物校验
def test_verify_encoding_baseline_degrades_without_file(tmp_path: Path):
    from agents.synthesis_kit import verify_encoding_baseline
    out = verify_encoding_baseline(tmp_path / "nonexistent.mp4")
    assert out["status"] == "skipped_no_file"
    assert out["path"].endswith("nonexistent.mp4")


def test_verify_encoding_baseline_checks():
    from agents.synthesis_kit import verify_encoding_baseline
    out = verify_encoding_baseline(None)
    assert out["status"] == "skipped_no_file"


# ---------------------------------------------------------------- 剪映草稿导出
def test_export_jianying_draft_minimal_structure(tmp_path: Path):
    from agents.synthesis_kit import export_jianying_draft
    storyboard = [
        {"shot_id": "shot_001", "desc": "a"},
        {"shot_id": "shot_002", "desc": "b"},
    ]
    out = export_jianying_draft(run_dir=tmp_path, storyboard=storyboard)
    draft = json.loads(Path(out["draft_content"]).read_text(encoding="utf-8"))
    assert draft["version"] == 3
    assert len(draft["materials"]["videos"]) == 2
    assert len(draft["tracks"][0]["segments"]) == 2
    assert draft["tracks"][0]["segments"][0]["shot_id"] == "shot_001"
    assert draft["fm"]["source"] == "ai_director_os_synthesis_kit"
    # 报告含导入步骤与手动任务清单
    report = Path(out["report"]).read_text(encoding="utf-8")
    assert "导入步骤" in report and "手动任务清单" in report
    assert "com.lveditor.draft" in report
    assert out["shots"] == 2


def test_export_jianying_draft_with_clips_and_refs(tmp_path: Path):
    from agents.synthesis_kit import export_jianying_draft
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"x")
    out = export_jianying_draft(
        run_dir=tmp_path,
        storyboard=[{"shot_id": "shot_001"}],
        video_clips=[{"path": "runs/x/video/shot_001.mp4", "shot_id": "shot_001"}],
        audio_path=audio,
    )
    draft = json.loads(Path(out["draft_content"]).read_text(encoding="utf-8"))
    assert draft["materials"]["videos"][0]["path"].endswith("shot_001.mp4")
    assert draft["materials"]["audios"], "音频应引用"
    report = Path(out["report"]).read_text(encoding="utf-8")
    assert "已引用" in report


# ---------------------------------------------------------------- 双通道编排
def test_dual_channel_orchestration(tmp_path: Path, monkeypatch):
    from agents.synthesis_kit import run_synthesis_dual_channel
    payload = {"storyboard": [{"shot_id": "shot_001", "desc": "x"}]}
    channels = run_synthesis_dual_channel(payload=payload, run_dir=tmp_path)
    # 通道 A：无 merged.mp4 → skipped（不阻断）
    assert channels["ffmpeg"]["verify"]["status"] == "skipped_no_file"
    # 通道 B：默认导出
    assert channels["jianying"]["shots"] == 1
    assert Path(channels["jianying"]["draft_content"]).exists()
    assert payload["synthesis_channels"] is channels


def test_dual_channel_jianying_disabled(tmp_path: Path, monkeypatch):
    from agents.synthesis_kit import run_synthesis_dual_channel
    monkeypatch.setenv("DREAMWEAVER_JIANYING_EXPORT", "0")
    payload: dict = {}
    channels = run_synthesis_dual_channel(payload=payload, run_dir=tmp_path)
    assert channels["jianying"] == {"status": "disabled"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
