from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_kling_auth_provider_prefers_session_token(monkeypatch) -> None:
    from app.services.providers.kling import KlingAuthProvider

    monkeypatch.setenv("KLING_TOKEN", "Bearer session_token_001")
    monkeypatch.setenv("KLINGAI_ACCESS_KEY", "access_key_should_not_be_used")
    monkeypatch.setenv("KLINGAI_SECRET_KEY", "secret_key_should_not_be_used")

    provider = KlingAuthProvider()
    bearer = provider.resolve_bearer_token()

    assert bearer.source == "session_token"
    assert bearer.token == "session_token_001"


def test_kling_element_api_builds_image_payload() -> None:
    from app.services.providers.kling import KlingElementAPI, KlingElementCreateRequest

    api = KlingElementAPI()
    payload = api.build_create_payload(
        KlingElementCreateRequest(
            name="阿青",
            description="黑发少年",
            frontal_image="runs/library/aqing_front.png",
            refer_images=["runs/library/aqing_side.png", "runs/library/aqing_back.png"],
        )
    )

    assert payload["element_name"] == "阿青"
    assert payload["element_description"] == "黑发少年"
    assert payload["reference_type"] == "image_refer"
    assert payload["element_image_list"]["frontal_image"] == "runs/library/aqing_front.png"
    assert len(payload["element_image_list"]["refer_images"]) == 2


def test_kling_element_api_create_and_wait_returns_element_records(monkeypatch) -> None:
    from app.services.providers.kling import KlingElementAPI, KlingElementCreateRequest

    api = KlingElementAPI()
    calls = {"query": 0}

    monkeypatch.setattr(api, "create", lambda request: {"task_id": "task_001"})

    def _fake_query(task_id: str):
        calls["query"] += 1
        if calls["query"] == 1:
            return {"task_status": "processing"}
        return {
            "task_status": "succeed",
            "task_result": {
                "elements": [
                    {
                        "element_id": "el_created_001",
                        "element_name": "阿青",
                        "element_description": "黑发少年",
                        "reference_type": "image_refer",
                    }
                ]
            },
        }

    monkeypatch.setattr(api, "query", _fake_query)

    elements = api.create_and_wait(
        KlingElementCreateRequest(
            name="阿青",
            description="黑发少年",
            frontal_image="runs/library/aqing_front.png",
        ),
        timeout_s=5.0,
        poll_interval_s=0.01,
    )

    assert len(elements) == 1
    assert elements[0].element_id == "el_created_001"
    assert elements[0].element_name == "阿青"


def test_kling_video_api_builds_omni_payload() -> None:
    from app.services.providers.kling import KlingVideoAPI, build_kling_video_request

    api = KlingVideoAPI()
    payload = api.build_create_payload(
        build_kling_video_request(
            prompt="雨夜中主角回头，保持主体一致。",
            model="kling-v3-omni",
            mode="image_to_video",
            duration=5.0,
            aspect_ratio="16:9",
            reference_frames=[
                {"image": "runs/storyboard/shot_001_head.png", "image_type": "first_frame"},
                {"image": "runs/storyboard/shot_001_tail.png", "image_type": "end_frame"},
            ],
            element_ids=["el_123", "el_456"],
            seed=42,
        )
    )

    assert payload["model_name"] == "kling-v3-omni"
    assert payload["prompt"] == "雨夜中主角回头，保持主体一致。"
    assert payload["duration"] == 5.0
    assert payload["aspect_ratio"] == "16:9"
    assert payload["seed"] == 42
    assert payload["element_ids"] == ["el_123", "el_456"]
    assert len(payload["images"]) == 2
    assert payload["images"][0]["image_type"] == "first_frame"
    assert payload["images"][1]["image_type"] == "end_frame"


def test_kling_video_api_create_and_wait_returns_video_result(monkeypatch) -> None:
    from app.services.providers.kling import KlingVideoAPI, build_kling_video_request

    api = KlingVideoAPI()
    calls = {"query": 0}

    monkeypatch.setattr(api, "create", lambda request: {"task_id": "video_task_001"})

    def _fake_query(task_id: str, *, mode: str = "image_to_video"):
        calls["query"] += 1
        assert task_id == "video_task_001"
        assert mode == "image_to_video"
        if calls["query"] == 1:
            return {"task_status": "processing"}
        return {
            "task_status": "succeed",
            "task_result": {
                "videos": [
                    {
                        "url": "https://cdn.example.com/kling/video_task_001.mp4",
                    }
                ]
            },
        }

    monkeypatch.setattr(api, "query", _fake_query)

    result = api.create_and_wait(
        build_kling_video_request(
            prompt="雨夜中主角回头，保持主体一致。",
            model="kling-v3-omni",
            mode="image_to_video",
            duration=5.0,
            reference_frames=[{"image": "runs/storyboard/shot_001_head.png", "image_type": "first_frame"}],
        ),
        timeout_s=5.0,
        poll_interval_s=0.01,
    )

    assert result.task_id == "video_task_001"
    assert result.task_status == "succeed"
    assert result.video_url == "https://cdn.example.com/kling/video_task_001.mp4"
