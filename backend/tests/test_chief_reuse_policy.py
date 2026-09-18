"""主审模型兼任评审官开关测试。

背景：默认评审面板里主审模型同时占一个评审席位（如 balanced_3 的 logic_continuity），
主审既下场评审又做裁决汇总，等于给自己的意见背书，交叉印证的独立性被削弱。
新增开关 MULTI_MODEL_REVIEW_ALLOW_CHIEF_REUSE：默认 True 保持现状，
关闭后被主审占用的席位改由异厂商模型接替，席位数量与 profile 覆盖不变。
"""

from app.core.config import settings
from app.services.agents.multi_model_review_service import (
    MODEL_REVIEW_GOVERNANCE,
    REVIEWER_PANEL_PRESETS,
    MultiModelReviewService,
)


def _disable_chief_reuse(monkeypatch) -> None:
    monkeypatch.setattr(settings, "MULTI_MODEL_REVIEW_ALLOW_CHIEF_REUSE", False, raising=False)


def _panel_models(service: MultiModelReviewService) -> list[str]:
    return [reviewer["model"] for reviewer in service.reviewers]


def _panel_providers(service: MultiModelReviewService) -> list[str]:
    return [MODEL_REVIEW_GOVERNANCE[model]["provider"] for model in _panel_models(service)]


def test_default_allows_chief_to_sit_as_reviewer() -> None:
    service = MultiModelReviewService(preset="balanced_3")

    assert service.chief_model in _panel_models(service)
    assert service.chief_model_reused_as_reviewer is True


def test_switch_off_keeps_panel_size_and_profiles(monkeypatch) -> None:
    _disable_chief_reuse(monkeypatch)
    service = MultiModelReviewService(preset="balanced_3")

    original = REVIEWER_PANEL_PRESETS["balanced_3"]
    assert [reviewer["profile"] for reviewer in service.reviewers] == [
        reviewer["profile"] for reviewer in original
    ]
    assert len(service.reviewers) == len(original)


def test_switch_off_removes_chief_from_review_panel(monkeypatch) -> None:
    _disable_chief_reuse(monkeypatch)
    service = MultiModelReviewService(preset="balanced_3")

    assert service.chief_model not in _panel_models(service)
    assert service.chief_model_reused_as_reviewer is False


def test_switch_off_substitute_keeps_provider_diversity(monkeypatch) -> None:
    _disable_chief_reuse(monkeypatch)
    service = MultiModelReviewService(preset="balanced_3")

    models = _panel_models(service)
    assert len(set(models)) == len(models)
    assert len(set(_panel_providers(service))) == len(models)
    # 替身不得来自主审自家厂商，否则独立性只是名义上的
    assert MODEL_REVIEW_GOVERNANCE[service.chief_model]["provider"] not in _panel_providers(service)


def test_switch_off_substitute_keeps_reasoning_tier(monkeypatch) -> None:
    _disable_chief_reuse(monkeypatch)
    service = MultiModelReviewService(preset="balanced_3")

    original_seat = next(
        reviewer for reviewer in REVIEWER_PANEL_PRESETS["balanced_3"]
        if reviewer["model"] == service.chief_model
    )
    replaced_seat = next(
        reviewer for reviewer in service.reviewers if reviewer["profile"] == original_seat["profile"]
    )
    expected = MODEL_REVIEW_GOVERNANCE[original_seat["model"]]["reasoning"]
    assert MODEL_REVIEW_GOVERNANCE[replaced_seat["model"]]["reasoning"] is expected


def test_switch_off_leaves_panel_untouched_when_chief_not_a_reviewer(monkeypatch) -> None:
    _disable_chief_reuse(monkeypatch)
    service = MultiModelReviewService(preset="deep_7")

    assert _panel_models(service) == [
        reviewer["model"] for reviewer in REVIEWER_PANEL_PRESETS["deep_7"]
    ]


def test_switch_off_applies_to_five_seat_preset_as_well(monkeypatch) -> None:
    _disable_chief_reuse(monkeypatch)
    service = MultiModelReviewService(preset="key_chapter_5")

    assert service.chief_model not in _panel_models(service)
    assert len(service.reviewers) == 5
    assert len(set(_panel_providers(service))) == 5
