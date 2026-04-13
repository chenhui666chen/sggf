from __future__ import annotations

from pathlib import Path

import pytest

from schemas.task_spec import TaskSpecBuilder


def test_wanx_adapter_maps_task_to_multimodal_messages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WAN_T2I_MODEL_NAME", "wan2.6-t2i-custom")
    monkeypatch.delenv("WAN_T2I_MODEL_ID", raising=False)

    from adapters.wanx_adapter import WanxAdapter

    reference_path = tmp_path / "reference.png"
    reference_path.write_bytes(b"fake-image")

    adapter = WanxAdapter(WanxAdapter.get_model_spec())
    task = (
        TaskSpecBuilder()
        .with_modality("text_to_image")
        .with_prompt("hero portrait")
        .with_negative_prompt("blurry")
        .with_dimensions(1024, 1024)
        .with_style("watercolor")
        .with_seed(42)
        .with_num_outputs(2)
        .with_references(images=[str(reference_path)])
        .build()
    )

    payload = adapter._map_task_to_request(task)

    assert payload["model"] == "wan2.6-t2i-custom"
    assert payload["parameters"]["size"] == "1024*1024"
    assert payload["parameters"]["n"] == 2
    assert payload["parameters"]["negative_prompt"] == "blurry"
    assert payload["parameters"]["seed"] == 42
    assert payload["parameters"]["watermark"] is False
    assert payload["parameters"]["prompt_extend"] is True

    content = payload["input"]["messages"][0]["content"]
    assert content[0]["image"].startswith("data:image/png;base64,")
    assert content[1]["text"] == "hero portrait\nStyle requirement: watercolor"


def test_wanx_adapter_marks_oss_inputs_for_resolution() -> None:
    from adapters.wanx_adapter import WanxAdapter

    adapter = WanxAdapter(WanxAdapter.get_model_spec())
    task = (
        TaskSpecBuilder()
        .with_modality("text_to_image")
        .with_prompt("hero portrait")
        .with_references(images=["oss://dashscope/demo/reference.png"])
        .build()
    )

    payload = adapter._map_task_to_request(task)

    assert adapter._request_needs_oss_resolve(payload) is True


def test_wanx_adapter_parse_response_reads_multimodal_choices() -> None:
    from adapters.wanx_adapter import WanxAdapter

    adapter = WanxAdapter(WanxAdapter.get_model_spec())
    task = (
        TaskSpecBuilder()
        .with_modality("text_to_image")
        .with_prompt("hero portrait")
        .build()
    )

    response = {
        "request_id": "req-demo",
        "output": {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"image": "https://example.com/generated.png"},
                        ]
                    }
                }
            ]
        },
    }

    result = adapter._parse_response(response, task)

    assert result.success is True
    assert result.outputs == ["https://example.com/generated.png"]
    assert result.metadata["request_id"] == "req-demo"


def test_wanx_adapter_surfaces_dashscope_error_details(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapters.wanx_adapter import WanxAdapter

    class FakeResponse:
        status_code = 400
        headers: dict[str, str] = {}
        reason = "Bad Request"
        text = "bad request"

        @staticmethod
        def json() -> dict[str, str]:
            return {
                "code": "InvalidParameter",
                "message": "messages.content is required",
                "request_id": "req-error",
            }

    adapter = WanxAdapter(WanxAdapter.get_model_spec())
    monkeypatch.setattr(adapter._session, "post", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(RuntimeError) as exc_info:
        adapter._call_api(
            {
                "model": "wan2.6-t2i",
                "input": {"messages": [{"role": "user", "content": [{"text": "hello"}]}]},
                "parameters": {"size": "1024*1024", "n": 1},
            }
        )

    message = str(exc_info.value)
    assert "DashScope HTTP 400" in message
    assert "InvalidParameter" in message
    assert "messages.content is required" in message
    assert "request_id=req-error" in message
