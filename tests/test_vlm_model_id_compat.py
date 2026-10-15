from __future__ import annotations

from pathlib import Path

import pytest


def test_vlm_chat_json_accepts_model_id_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents import vlm_utils

    captured: dict[str, object] = {}

    class FakeResult:
        success = True
        data = {"content": '{"ok": true}'}

    def fake_chat_messages(**kwargs):
        captured.update(kwargs)
        return FakeResult()

    monkeypatch.setattr("adapters.adapter_helpers.chat_messages", fake_chat_messages)

    obj = vlm_utils.vlm_chat_json(
        vlm_adapter="qwen3.8-omni-flash",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.3,
        max_tokens=256,
    )

    assert obj == {"ok": True}
    assert captured == {
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.3,
        "max_tokens": 256,
        "response_format": {"type": "json_object"},
        "model_id": "qwen3.8-omni-flash",
    }


def test_best_image_selector_accepts_model_id_string_for_vlm_analysis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agents.best_image_selector import select_best_candidate

    img_a = tmp_path / "a.png"
    img_b = tmp_path / "b.png"
    img_a.write_bytes(b"a")
    img_b.write_bytes(b"bbbb")

    captured: list[dict[str, object]] = []

    def fake_analyze_image(**kwargs):
        captured.append(dict(kwargs))
        score = 0.2 if kwargs["image_path"].endswith("a.png") else 0.9
        return type(
            "Result",
            (),
            {
                "success": True,
                "data": {"score": score},
            },
        )()

    monkeypatch.setattr("agents.best_image_selector.analyze_image_with_model", fake_analyze_image)

    result = select_best_candidate(
        candidate_paths=[img_a, img_b],
        selector="vlm",
        vlm_adapter="qwen3.8-omni-flash",
        vlm_criteria=["quality"],
    )

    assert result["best_index"] == 1
    assert result["reason"] == "vlm"
    assert captured == [
        {
            "image_path": str(img_a),
            "analysis_type": "quality",
            "criteria": ["quality"],
            "model_id": "qwen3.8-omni-flash",
        },
        {
            "image_path": str(img_b),
            "analysis_type": "quality",
            "criteria": ["quality"],
            "model_id": "qwen3.8-omni-flash",
        },
    ]
