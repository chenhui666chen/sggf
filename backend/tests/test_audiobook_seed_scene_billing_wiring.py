from __future__ import annotations

from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("relative_path", "expected_count"),
    [
        ("app/api/v1/audiobook_api/routes_projects.py", 2),
        ("app/api/v1/audiobook_api/routes_subtitle.py", 1),
    ],
)
def test_audio_generation_routes_use_project_engine_mode_for_precheck_and_freeze(
    relative_path: str,
    expected_count: int,
) -> None:
    source = (ROOT_DIR / relative_path).read_text(encoding="utf-8")

    assert source.count(
        "resolve_audiobook_billing_pricing_context("
    ) == expected_count
    assert source.count(
        "audio_engine_mode=billing_context.audio_engine_mode"
    ) == expected_count
    assert source.count(
        "tts_pricing_key=billing_context.pricing_key"
    ) == expected_count
    assert source.count(
        "estimated_yuan_override=precheck.estimated_yuan"
    ) == expected_count
