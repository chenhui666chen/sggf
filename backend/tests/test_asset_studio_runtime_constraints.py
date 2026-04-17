import json
import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")

from app.api.v1.asset_studio import _raise_for_failed_result, _validate_dimensions_for_models, _validate_video_duration
from core.unified_media_runtime import UnifiedMediaResult


def test_asset_studio_video_duration_uses_runtime_union(monkeypatch, tmp_path) -> None:
    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "wan2.7-t2v": {
                        "task_constraints": {
                            "duration_values": [3.0, 5.0, 10.0, 15.0],
                        },
                    },
                    "wan2.7-i2v": {
                        "task_constraints": {
                            "duration_values": [3.0, 5.0, 10.0],
                        },
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

    assert _validate_video_duration("wan2.7-i2v", 15.0) == 15.0


def test_asset_studio_video_duration_rejects_unsupported_value(monkeypatch, tmp_path) -> None:
    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "wan2.7-t2v": {
                        "task_constraints": {
                            "duration_values": [3.0, 5.0, 10.0, 15.0],
                        },
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

    with pytest.raises(HTTPException) as exc_info:
        _validate_video_duration("wan2.7-t2v", 8.0)

    assert exc_info.value.status_code == 400
    assert "3 秒 / 5 秒 / 10 秒 / 15 秒" in str(exc_info.value.detail)


def test_asset_studio_dimensions_use_runtime_union(monkeypatch, tmp_path) -> None:
    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "wan2.7-t2v": {
                        "task_constraints": {
                            "ratio_values": ["16:9", "9:16", "1:1"],
                            "min_width": 480,
                            "max_width": 1920,
                            "min_height": 480,
                            "max_height": 1920,
                        },
                    },
                    "wan2.7-i2v": {
                        "task_constraints": {
                            "ratio_values": ["16:9"],
                            "min_width": 480,
                            "max_width": 1920,
                            "min_height": 480,
                            "max_height": 1080,
                        },
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

    assert _validate_dimensions_for_models({"wan2.7-t2v", "wan2.7-i2v"}, 1080, 1920, request_label="视频") == (1080, 1920)


def test_asset_studio_dimensions_reject_unsupported_ratio(monkeypatch, tmp_path) -> None:
    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "wan2.7-t2v": {
                        "task_constraints": {
                            "ratio_values": ["16:9", "9:16", "1:1"],
                            "min_width": 480,
                            "max_width": 1920,
                            "min_height": 480,
                            "max_height": 1920,
                        },
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

    with pytest.raises(HTTPException) as exc_info:
        _validate_dimensions_for_models({"wan2.7-t2v"}, 1536, 2048, request_label="视频")

    assert exc_info.value.status_code == 400
    assert "1536x2048（3:4）" in str(exc_info.value.detail)


def test_asset_studio_failed_result_uses_bad_request_for_invalid_parameter() -> None:
    result = UnifiedMediaResult(
        success=False,
        model_id="wan2.6-t2i",
        error="DashScope HTTP 400 | InvalidParameter | messages.content is required",
        error_code="invalid_parameter",
    )

    with pytest.raises(HTTPException) as exc_info:
        _raise_for_failed_result(result, fallback_message="图片生成失败")

    assert exc_info.value.status_code == 400
    assert "InvalidParameter" in str(exc_info.value.detail)


def test_asset_studio_failed_result_keeps_service_unavailable_for_runtime_failure() -> None:
    result = UnifiedMediaResult(
        success=False,
        model_id="wan2.6-t2i",
        error="upstream timeout",
        error_code="timeout",
    )

    with pytest.raises(HTTPException) as exc_info:
        _raise_for_failed_result(result, fallback_message="图片生成失败")

    assert exc_info.value.status_code == 503
