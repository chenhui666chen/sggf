# -*- coding: utf-8 -*-
"""资产工作台音效「按实际时长结算」契约。

2026-10-08 实测：`seed-audio-1.0` 没有时长入参，短音效实际产出约 4.0-5.5 秒，
真实时长写在响应 metadata 的 duration 字段里。此前结算基准用的是用户
**请求**的时长（3/5/8/10 秒下拉），请求 10 秒只产出 4 秒时用户多付 2.5 倍，
而供应商按实际产出时长计费，因此口径必须改为实际时长。

冻结仍按请求时长（作为上限），结算按实际时长；实际时长缺失或超过请求时长时
回退请求时长，保证不会扣掉比冻结更多的积分。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.api.v1.asset_studio_api._helpers import _resolve_billed_audio_duration_seconds
from app.services.points_usage_pricing import estimate_asset_studio_basis_yuan

REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTE_SOURCE_RELATIVE = "backend/app/api/v1/asset_studio_api/routes_audio.py"
SOUND_EFFECT_SECTION_START = (
    'resolved_duration = _validate_audio_duration("sound-effect", duration)'
)
PER_SECOND_YUAN = "0.04"


def _read_route_source() -> str:
    return (REPO_ROOT / ROUTE_SOURCE_RELATIVE).read_text(encoding="utf-8")


def _sound_effect_section(source: str) -> str:
    """只取音效分支源码，避免断言被音乐/语音分支误命中。"""
    start = source.index(SOUND_EFFECT_SECTION_START)
    tail = source[start:]
    end = tail.index("except Exception:")
    return tail[:end]


def _estimate(duration_seconds: float) -> float:
    return estimate_asset_studio_basis_yuan(
        kind="audio",
        mode="text_to_sound_effect",
        model_id="seed-audio-1.0",
        duration_seconds=duration_seconds,
        prompt_chars=32,
    )


class TestResolveBilledAudioDuration:
    @pytest.mark.parametrize(
        "metadata,expected",
        [
            ({"duration": 4.03}, 4.03),
            ({"duration": "6.5"}, 6.5),
            ({"duration": 5.0}, 5.0),
        ],
    )
    def test_uses_reported_duration_when_within_request(self, metadata: dict[str, Any], expected: float):
        assert _resolve_billed_audio_duration_seconds(requested_seconds=8, metadata=metadata) == expected

    def test_caps_at_requested_duration(self):
        """实际时长可能比请求长，结算不得超过已冻结的请求时长上限。"""
        assert _resolve_billed_audio_duration_seconds(requested_seconds=5, metadata={"duration": 9.5}) == 5.0

    @pytest.mark.parametrize(
        "metadata",
        [
            {},
            {"duration": None},
            {"duration": 0},
            {"duration": -2},
            {"duration": "abc"},
            {"duration": ""},
        ],
    )
    def test_falls_back_to_requested_when_duration_unusable(self, metadata: dict[str, Any]):
        assert _resolve_billed_audio_duration_seconds(requested_seconds=3, metadata=metadata) == 3.0


class TestSettledAmountFollowsActualDuration:
    def test_settled_amount_is_lower_when_actual_shorter_than_requested(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("POINTS_ASSET_STUDIO_SOUND_EFFECT_PER_SECOND_YUAN", PER_SECOND_YUAN)
        frozen = _estimate(10.0)
        billed_seconds = _resolve_billed_audio_duration_seconds(
            requested_seconds=10,
            metadata={"duration": 4.03},
        )
        settled = _estimate(billed_seconds)
        assert frozen == pytest.approx(0.40)
        assert settled == pytest.approx(0.16)
        assert settled < frozen

    def test_settled_amount_equals_frozen_when_duration_missing(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("POINTS_ASSET_STUDIO_SOUND_EFFECT_PER_SECOND_YUAN", PER_SECOND_YUAN)
        billed_seconds = _resolve_billed_audio_duration_seconds(requested_seconds=10, metadata={})
        assert _estimate(billed_seconds) == _estimate(10.0)


class TestSoundEffectRouteWiresActualDurationBilling:
    def test_route_computes_billed_duration_from_result_metadata(self):
        section = _sound_effect_section(_read_route_source())
        assert "billed_duration_seconds = _resolve_billed_audio_duration_seconds(" in section
        assert "metadata=result_metadata," in section

    def test_route_freezes_on_request_and_settles_on_billed_duration(self):
        section = _sound_effect_section(_read_route_source())
        assert "basis_yuan=settled_basis_yuan," in section
        # 冻结调用必须仍用请求时长基准，避免扣款超过用户确认的上限。
        freeze_call = section[: section.index("basis_yuan=settled_basis_yuan,")]
        assert "basis_yuan=basis_yuan," in freeze_call

    def test_route_records_both_durations_in_settlement_payload(self):
        section = _sound_effect_section(_read_route_source())
        assert '"billed_duration_seconds": billed_duration_seconds,' in section
        assert '"actual_duration_seconds": actual_duration_seconds,' in section

    def test_helper_is_imported_explicitly(self):
        """下划线开头的名字不会被 `import *` 带进来，必须写进显式导入清单。"""
        source = _read_route_source()
        import_block = source[: source.index("@router.post")]
        assert "_resolve_billed_audio_duration_seconds," in import_block
