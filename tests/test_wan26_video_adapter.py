from __future__ import annotations

import json

import pytest

from adapters.base import AdapterConfig
from schemas.task_spec import TaskSpecBuilder


def test_wan2_7_i2v_adapter_maps_1280x720_to_720p(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from adapters.wan26_video_adapter import Wan27ImageToVideoAdapter

    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "wan2.7-i2v": {
                        "task_constraints": {
                            "resolution_options": ["720P", "1080P"],
                        }
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

    adapter = Wan27ImageToVideoAdapter(
        Wan27ImageToVideoAdapter.get_model_spec(),
        AdapterConfig(api_key="", base_url="https://dashscope.aliyuncs.com", extra={"model_name": "wan2.7-i2v"}),
    )
    task = (
        TaskSpecBuilder()
        .with_modality("image_to_video")
        .with_prompt("happy dog on the beach")
        .with_dimensions(1280, 720)
        .with_duration(5.0)
        .with_references(images=["start.png"])
        .build()
    )

    request = adapter._map_task_to_request(task)

    assert request["model"] == "wan2.7-i2v"
    assert request["parameters"]["resolution"] == "720P"
    assert request["parameters"]["size"] == "1280*720"
    assert request["input"]["img_url"] == "start.png"
    assert request["input"]["ref_image_url"] == "start.png"


def test_wan2_7_i2v_adapter_maps_square_video_to_nearest_supported_bucket(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from adapters.wan26_video_adapter import Wan27ImageToVideoAdapter

    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "wan2.7-i2v": {
                        "task_constraints": {
                            "resolution_options": ["480P", "720P", "1080P"],
                        }
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

    adapter = Wan27ImageToVideoAdapter(
        Wan27ImageToVideoAdapter.get_model_spec(),
        AdapterConfig(api_key="", base_url="https://dashscope.aliyuncs.com", extra={"model_name": "wan2.7-i2v"}),
    )
    task = (
        TaskSpecBuilder()
        .with_modality("image_to_video")
        .with_prompt("dog portrait animation")
        .with_dimensions(1024, 1024)
        .with_duration(5.0)
        .with_references(images=["start.png"])
        .build()
    )

    request = adapter._map_task_to_request(task)

    assert request["parameters"]["resolution"] == "1080P"
    assert request["parameters"]["size"] == "1024*1024"


def test_wan2_7_video_adapter_surfaces_dashscope_invalid_parameter(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapters.wan26_video_adapter import Wan27ImageToVideoAdapter

    class FakeResponse:
        status_code = 400
        headers: dict[str, str] = {}
        reason = "Bad Request"
        text = "bad request"

        @staticmethod
        def json() -> dict[str, str]:
            return {
                "code": "InvalidParameter",
                "message": "resolution 1280x720 is not supported, available ones are ['720P', '1080P']",
                "request_id": "req-video-error",
            }

    adapter = Wan27ImageToVideoAdapter(
        Wan27ImageToVideoAdapter.get_model_spec(),
        AdapterConfig(api_key="", base_url="https://dashscope.aliyuncs.com", extra={"model_name": "wan2.7-i2v"}),
    )
    monkeypatch.setattr(adapter._session, "post", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(RuntimeError) as exc_info:
        adapter._call_api(
            {
                "model": "wan2.7-i2v",
                "input": {"text": "happy dog", "img_url": "start.png", "ref_image_url": "start.png"},
                "parameters": {"duration": 5, "resolution": "1280x720", "size": "1280*720"},
            }
        )

    message = str(exc_info.value)
    assert "DashScope HTTP 400" in message
    assert "InvalidParameter" in message
    assert "resolution 1280x720 is not supported" in message
    assert "request_id=req-video-error" in message
