from __future__ import annotations

from types import SimpleNamespace

import pytest


def _install_fake_wrapper(
    monkeypatch: pytest.MonkeyPatch,
    *,
    methods: dict[str, object],
) -> dict[str, object]:
    from adapters import legacy_runtime_wrappers

    captured: dict[str, object] = {}

    class FakeWrapper:
        def close(self) -> None:
            captured["closed"] = True

    for method_name, payload in methods.items():
        def _make_method(expected_name: str, result_payload: object):
            def _method(self, *args, **kwargs):
                captured["method"] = expected_name
                captured["args"] = args
                captured["kwargs"] = kwargs
                return SimpleNamespace(
                    success=True,
                    data=result_payload,
                    metadata={"source": "runtime"},
                    error=None,
                    cost=0.5,
                )

            return _method

        setattr(FakeWrapper, method_name, _make_method(method_name, payload))

    def fake_create_runtime_wrapper(name: str, config) -> FakeWrapper:
        captured["name"] = name
        captured["config"] = config
        return FakeWrapper()

    monkeypatch.setattr(legacy_runtime_wrappers, "create_runtime_wrapper", fake_create_runtime_wrapper)
    return captured


def test_wan2_6_t2i_adapter_generate_delegates_to_runtime_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters.model_adapters import ModelConfig, Wan26T2IAdapter

    captured = _install_fake_wrapper(
        monkeypatch,
        methods={"generate": {"image_url": "https://example.com/generated.png"}},
    )

    adapter = Wan26T2IAdapter(ModelConfig(api_key="", base_url="", model_name="wan2.6-t2i"))
    monkeypatch.setattr(adapter, "_make_request", lambda *args, **kwargs: pytest.fail("old request path should not run"))

    result = adapter.generate(
        prompt="hero portrait",
        negative_prompt="blurry",
        width=768,
        height=1024,
        num_inference_steps=40,
        guidance_scale=6.5,
        seed=11,
    )

    assert captured["name"] == "wan2.6-t2i"
    assert captured["method"] == "generate"
    assert captured["kwargs"] == {
        "prompt": "hero portrait",
        "negative_prompt": "blurry",
        "width": 768,
        "height": 1024,
        "num_inference_steps": 40,
        "guidance_scale": 6.5,
        "seed": 11,
    }
    assert captured["closed"] is True
    assert result.success is True
    assert result.data == {"image_url": "https://example.com/generated.png"}
    assert result.metadata == {"source": "runtime"}


@pytest.mark.parametrize(
    ("adapter_class_name", "wrapper_name", "call_kwargs", "expected_data"),
    [
        (
            "Wan27I2VAdapter",
            "wan2.7-i2v",
            {
                "image_path": "person.png",
                "prompt": "animate the portrait",
                "duration": 5,
                "fps": 24,
                "motion_bucket_id": 96,
                "seed": 7,
                "character_references": [{"name": "hero"}],
            },
            {"video_url": "https://example.com/i2v.mp4"},
        ),
        (
            "Wan27T2VAdapter",
            "wan2.7-t2v",
            {
                "prompt": "storm over the sea",
                "negative_prompt": "low quality",
                "width": 1280,
                "height": 720,
                "duration": 5,
                "fps": 24,
                "num_inference_steps": 28,
                "guidance_scale": 7.0,
                "seed": 17,
            },
            {"video_url": "https://example.com/t2v.mp4"},
        ),
        (
            "Wan27R2VAdapter",
            "wan2.7-r2v",
            {
                "reference_video_path": "scene.mp4",
                "prompt": "keep the motion style",
                "duration": 4,
                "fps": 24,
                "seed": 9,
            },
            {"video_url": "https://example.com/r2v.mp4"},
        ),
    ],
)
def test_wan_video_adapters_delegate_to_runtime_wrapper(
    monkeypatch: pytest.MonkeyPatch,
    adapter_class_name: str,
    wrapper_name: str,
    call_kwargs: dict[str, object],
    expected_data: dict[str, str],
) -> None:
    from adapters import model_adapters

    captured = _install_fake_wrapper(monkeypatch, methods={"generate": expected_data})

    adapter_class = getattr(model_adapters, adapter_class_name)
    adapter = adapter_class(model_adapters.ModelConfig(api_key="", base_url="", model_name="demo"))
    monkeypatch.setattr(adapter, "_make_request", lambda *args, **kwargs: pytest.fail("old request path should not run"))

    result = adapter.generate(**call_kwargs)

    assert captured["name"] == wrapper_name
    assert captured["method"] == "generate"
    assert captured["kwargs"] == call_kwargs
    assert captured["closed"] is True
    assert result.success is True
    assert result.data == expected_data


@pytest.mark.parametrize(
    ("adapter_class_name", "wrapper_name"),
    [
        ("QwenImageEditPlusAdapter", "qwen_image_edit_plus"),
        ("WanImageEditAdapter", "wan_image_edit"),
        ("QwenImageEditMaxAdapter", "qwen_image_edit_max"),
    ],
)
def test_image_edit_adapters_delegate_to_runtime_wrapper(
    monkeypatch: pytest.MonkeyPatch,
    adapter_class_name: str,
    wrapper_name: str,
) -> None:
    from adapters import model_adapters

    captured = _install_fake_wrapper(
        monkeypatch,
        methods={"generate": {"image_url": "https://example.com/edited.png"}},
    )

    adapter_class = getattr(model_adapters, adapter_class_name)
    adapter = adapter_class(model_adapters.ModelConfig(api_key="", base_url="", model_name="demo"))
    monkeypatch.setattr(adapter, "_request_json_url", lambda *args, **kwargs: pytest.fail("old edit path should not run"))

    result = adapter.generate(
        image_path="base.png",
        edit_prompt="add moonlight",
        mask_path="mask.png",
        strength=0.65,
        guidance_scale=7.5,
        seed=123,
        image_paths=["ref-1.png", "ref-2.png"],
    )

    assert captured["name"] == wrapper_name
    assert captured["method"] == "generate"
    assert captured["kwargs"] == {
        "image_path": "base.png",
        "edit_prompt": "add moonlight",
        "mask_path": "mask.png",
        "strength": 0.65,
        "guidance_scale": 7.5,
        "seed": 123,
        "image_paths": ["ref-1.png", "ref-2.png"],
    }
    assert captured["closed"] is True
    assert result.success is True
    assert result.data == {"image_url": "https://example.com/edited.png"}


def test_qwen_multiperson_match_scene_delegates_to_runtime_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters.model_adapters import ModelConfig, QwenMultiPersonFusionAdapter

    captured = _install_fake_wrapper(
        monkeypatch,
        methods={"match_scene": {"image_url": "https://example.com/fused.png"}},
    )

    adapter = QwenMultiPersonFusionAdapter(ModelConfig(api_key="", base_url="", model_name="demo"))
    monkeypatch.setattr(adapter, "_make_request", lambda *args, **kwargs: pytest.fail("old fusion path should not run"))

    result = adapter.match_scene(
        person_image_path="person.png",
        target_scene_path="scene.png",
        scene_prompt="place the character into the scene",
    )

    assert captured["name"] == "qwen_multiperson_fusion"
    assert captured["method"] == "match_scene"
    assert captured["kwargs"] == {
        "person_image_path": "person.png",
        "target_scene_path": "scene.png",
        "scene_prompt": "place the character into the scene",
    }
    assert result.success is True
    assert result.data == {
        "image_url": "https://example.com/fused.png",
        "image_urls": ["https://example.com/fused.png"],
    }


def test_qwen_multiperson_fuse_multiple_persons_delegates_to_runtime_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters.model_adapters import ModelConfig, QwenMultiPersonFusionAdapter

    captured = _install_fake_wrapper(
        monkeypatch,
        methods={"generate": {"image_url": "https://example.com/group.png"}},
    )

    adapter = QwenMultiPersonFusionAdapter(ModelConfig(api_key="", base_url="", model_name="demo"))
    result = adapter.fuse_multiple_persons(
        person_images=["p1.png", "p2.png"],
        target_scene_path="scene.png",
        fusion_prompt="merge the cast naturally",
        layout_description="p1 left, p2 right",
    )

    assert captured["name"] == "qwen_multiperson_fusion"
    assert captured["method"] == "generate"
    assert captured["kwargs"]["image_path"] == "scene.png"
    assert captured["kwargs"]["image_paths"] == ["p1.png", "p2.png"]
    assert captured["kwargs"]["edit_prompt"].startswith("merge the cast naturally\n")
    assert captured["kwargs"]["edit_prompt"].endswith("p1 left, p2 right")
    assert result.success is True
    assert result.data == {
        "image_url": "https://example.com/group.png",
        "image_urls": ["https://example.com/group.png"],
    }


def test_qwen3_vl_plus_methods_delegate_to_runtime_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters.model_adapters import ModelConfig, Qwen3VLPlusAdapter

    captured = _install_fake_wrapper(
        monkeypatch,
        methods={
            "chat": {"content": '{"ok": true}'},
            "analyze_image": {"score": 95},
        },
    )

    adapter = Qwen3VLPlusAdapter(ModelConfig(api_key="", base_url="", model_name="qwen3-vl-plus"))
    monkeypatch.setattr(adapter, "_make_request", lambda *args, **kwargs: pytest.fail("old vl path should not run"))

    chat_result = adapter.generate(
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.3,
        max_tokens=128,
    )
    image_result = adapter.analyze_image(
        image_path="cover.png",
        analysis_type="quality",
        criteria=["clarity"],
    )

    assert captured["name"] == "qwen3_vl_plus"
    assert captured["method"] == "analyze_image"
    assert captured["kwargs"] == {
        "image_path": "cover.png",
        "analysis_type": "quality",
        "criteria": ["clarity"],
    }
    assert chat_result.success is True
    assert chat_result.data == {"content": '{"ok": true}'}
    assert image_result.success is True
    assert image_result.data == {"score": 95}
