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

