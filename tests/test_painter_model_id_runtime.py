from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.painter_pkg import _edit_pipeline, _library, _t2i_pipeline, _utils


def test_generate_t2i_with_candidates_accepts_model_id_string(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_generate_image(**kwargs):
        captured.update(kwargs)
        return type(
            "Result",
            (),
            {
                "success": True,
                "data": {"image_url": "https://example.com/generated.png"},
                "error": None,
            },
        )()

    monkeypatch.setattr(_utils, "generate_image", fake_generate_image)
    monkeypatch.setattr(_t2i_pipeline, "_sanitize_prompt_for_safety", lambda prompt: (prompt, {"issues": 0}))
    monkeypatch.setattr(_t2i_pipeline, "_env_flag", lambda name, default: False)
    monkeypatch.setattr(
        _t2i_pipeline,
        "_write_image_from_generation_result",
        lambda result, out_path: out_path.write_bytes(b"png"),
    )

    ctx = SimpleNamespace(payload={}, run_id="run-1")
    output_path = tmp_path / "out.png"

    result = _t2i_pipeline._generate_t2i_with_candidates(
        adapter="qwen-image-3.0",
        prompt="hero portrait",
        negative_prompt="blurry",
        width=768,
        height=1024,
        base_seed=11,
        ctx=ctx,
        shot_id="shot-1",
        role="head",
        output_path=output_path,
        candidate_count=1,
        parallelism=1,
        selector="first",
        vlm_adapter=None,
        vlm_criteria=[],
        keep_candidates=False,
        enable_hash_cache=False,
    )

    assert output_path.read_bytes() == b"png"
    assert result["seed"] == 11
    assert captured == {
        "prompt": "hero portrait",
        "negative_prompt": "blurry",
        "width": 768,
        "height": 1024,
        "seed": 11,
        "model_id": "qwen-image-3.0",
    }


def test_generate_t2i_with_parallel_candidates_keeps_model_id_string_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agents import painter

    calls: list[dict[str, object]] = []

    def fake_generate_image(**kwargs):
        calls.append(dict(kwargs))
        return type(
            "Result",
            (),
            {
                "success": True,
                "data": {"image_url": f"https://example.com/{kwargs['seed']}.png"},
                "error": None,
            },
        )()

    monkeypatch.setattr(_utils, "generate_image", fake_generate_image)
    monkeypatch.setattr(_t2i_pipeline, "_sanitize_prompt_for_safety", lambda prompt: (prompt, {"issues": 0}))
    monkeypatch.setattr(_t2i_pipeline, "_env_flag", lambda name, default: False)
    monkeypatch.setattr(
        _t2i_pipeline,
        "_write_image_from_generation_result",
        lambda result, out_path: out_path.write_bytes(str(result.data["image_url"]).encode("utf-8")),
    )

    ctx = SimpleNamespace(payload={}, run_id="run-1b")
    output_path = tmp_path / "parallel.png"

    result = _t2i_pipeline._generate_t2i_with_candidates(
        adapter="qwen-image-3.0",
        prompt="hero portrait",
        negative_prompt="blurry",
        width=768,
        height=1024,
        base_seed=21,
        ctx=ctx,
        shot_id="shot-1b",
        role="head",
        output_path=output_path,
        candidate_count=2,
        parallelism=2,
        selector="first",
        vlm_adapter=None,
        vlm_criteria=[],
        keep_candidates=False,
        enable_hash_cache=False,
    )

    assert hasattr(painter, "create_runtime_client") is False
    assert len(calls) == 2
    assert [call["model_id"] for call in calls] == ["qwen-image-3.0", "qwen-image-3.0"]
    assert sorted(int(call["seed"]) for call in calls) == [21, 22]
    assert output_path.exists() is True
    assert result["candidate_count"] == 2
    assert result["candidate_seeds"] == [21, 22]


def test_resolve_runtime_model_id_prefers_runtime_config_over_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DREAMWEAVER_T2I_MODEL", "env-image-model")

    resolved = _utils._resolve_runtime_model_id(
        {"adapter": "runtime-image-model"},
        key="adapter",
        env_name="DREAMWEAVER_T2I_MODEL",
        default="qwen-image-3.0",
    )

    assert resolved == "runtime-image-model"


def test_resolve_runtime_model_id_requires_available_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DREAMWEAVER_VLM_ADAPTER", "env-vlm-model")
    monkeypatch.setattr(_utils, "_model_client_available", lambda model_id: model_id == "runtime-vlm-model")

    resolved = _utils._resolve_runtime_model_id(
        {"vlm_adapter": "runtime-vlm-model"},
        key="vlm_adapter",
        env_name="DREAMWEAVER_VLM_ADAPTER",
        default="qwen3_vl_plus",
        require_available=True,
    )
    missing = _utils._resolve_runtime_model_id(
        {"vlm_adapter": "missing-vlm-model"},
        key="vlm_adapter",
        env_name="DREAMWEAVER_VLM_ADAPTER",
        default="qwen3_vl_plus",
        require_available=True,
    )

    assert resolved == "runtime-vlm-model"
    assert missing is None


def test_generate_edit_with_candidates_accepts_model_id_string_and_multi_ref(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base_image = tmp_path / "base.png"
    ref_image = tmp_path / "ref.png"
    base_image.write_bytes(b"base")
    ref_image.write_bytes(b"ref")

    captured: dict[str, object] = {}

    def fake_edit_image(**kwargs):
        captured.update(kwargs)
        return type(
            "Result",
            (),
            {
                "success": True,
                "data": {"image_url": "https://example.com/edited.png"},
                "error": None,
            },
        )()

    monkeypatch.setattr(_utils, "edit_image", fake_edit_image)
    monkeypatch.setattr(_utils, "model_supports_capability", lambda model_id, capability: capability == "multi_image")
    monkeypatch.setattr(_edit_pipeline, "_sanitize_prompt_for_safety", lambda prompt: (prompt, {"issues": 0}))
    monkeypatch.setattr(_edit_pipeline, "_env_flag", lambda name, default: False)
    monkeypatch.setattr(
        _edit_pipeline,
        "_write_image_from_generation_result",
        lambda result, out_path: out_path.write_bytes(b"edited"),
    )

    ctx = SimpleNamespace(payload={}, run_id="run-2")
    output_path = tmp_path / "edited.png"

    result = _edit_pipeline._generate_edit_with_candidates(
        adapter="qwen_image_edit_plus",
        image_path=base_image,
        edit_prompt="add moonlight",
        reference_desc="base",
        strength=0.65,
        guidance_scale=7.5,
        base_seed=7,
        ctx=ctx,
        shot_id="shot-2",
        role="tail",
        output_path=output_path,
        candidate_count=1,
        parallelism=1,
        selector="first",
        vlm_adapter=None,
        vlm_criteria=[],
        reference_images=[{"path": ref_image, "desc": "reference"}],
        keep_candidates=False,
        enable_hash_cache=False,
        use_multi_ref=True,
        max_ref_images=3,
    )

    assert output_path.read_bytes() == b"edited"
    assert result["seed"] == 7
    assert captured == {
        "image_path": str(base_image),
        "edit_prompt": "以 Image 1 为基准，参考 Image 2 保持主体一致。\nadd moonlight",
        "strength": 0.65,
        "reference_images": [str(ref_image)],
        "model_id": "qwen_image_edit_plus",
        "seed": 7,
        "guidance_scale": 7.5,
    }


def test_try_generate_multiperson_fusion_head_uses_match_scene_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scene = tmp_path / "scene.png"
    person_a = tmp_path / "a.png"
    person_b = tmp_path / "b.png"
    scene.write_bytes(b"scene")
    person_a.write_bytes(b"a")
    person_b.write_bytes(b"b")

    calls: list[dict[str, object]] = []

    def fake_match_scene_with_model(**kwargs):
        calls.append(dict(kwargs))
        return type(
            "Result",
            (),
            {
                "success": True,
                "data": {"image_url": f"https://example.com/{len(calls)}.png"},
                "error": None,
            },
        )()

    monkeypatch.setattr(_library, "match_scene_with_model", fake_match_scene_with_model)
    monkeypatch.setattr(_library, "_model_client_available", lambda model_id: True)
    monkeypatch.setattr(
        _library,
        "_write_image_from_generation_result",
        lambda result, out_path: out_path.write_bytes(f"step-{len(calls)}".encode("utf-8")),
    )

    output_path = tmp_path / "head.png"
    fused_path, meta = _library._try_generate_multiperson_fusion_head(
        shot_id="shot-1",
        output_path=output_path,
        head_prompt="hero group shot",
        style_negative_prompt="blurry",
        asset_match={
            "character_assets": [
                {"path": person_a, "entity_name": "Alice", "role": "char_alice", "desc": "alice"},
                {"path": person_b, "entity_name": "Bob", "role": "char_bob", "desc": "bob"},
            ],
            "scene_assets": [
                {"path": scene, "entity_name": "Square", "role": "scene_square", "desc": "square"},
            ],
        },
        head_anchor=None,
        use_anchor_scene=False,
        max_persons=3,
        keep_candidates=True,
    )

    assert fused_path == output_path
    assert output_path.read_bytes() == b"step-2"
    assert meta["status"] == "success"
    assert len(meta["steps"]) == 2
    assert [call["model_id"] for call in calls] == ["qwen_multiperson_fusion", "qwen_multiperson_fusion"]
    assert calls[0]["target_scene_path"] == str(scene)
    assert calls[1]["target_scene_path"].endswith("shot-1_head_fuse_1.png")
