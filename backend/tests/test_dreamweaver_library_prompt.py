from __future__ import annotations

import pytest

from app.api.v1.dreamweaver_api._helpers_library_prompt import (
    _character_view_from_role,
    _character_role_for_view,
    _augment_library_prompt_for_role,
    _merge_descriptor_texts,
    _meta_prompt_text,
    _meta_descriptor_text,
    _is_placeholder_entity_name,
    _resolve_character_view_prompt_seed,
    _resolve_prompt_seed_for_role,
    _attach_view_chain_prompt_meta,
    _CHARACTER_VIEW_PREFIX_TO_VIEW,
    _CHARACTER_VIEW_SEED_BASE,
    _CHARACTER_VIEW_REFERENCE_EXTRA,
)


class TestCharacterViewFromRole:
    def test_front_view(self):
        assert _character_view_from_role("lib_character_portrait:1") == "front"

    def test_side_view(self):
        assert _character_view_from_role("lib_character_portrait_side:2") == "side"

    def test_back_view(self):
        assert _character_view_from_role("lib_character_portrait_back:3") == "back"

    def test_bust_front_view(self):
        assert _character_view_from_role("lib_character_portrait_bust:4") == "bust_front"

    def test_bust_three_quarter_view(self):
        assert _character_view_from_role("lib_character_portrait_bust_three_quarter:5") == "bust_three_quarter"

    def test_bust_side_view(self):
        assert _character_view_from_role("lib_character_portrait_bust_side:6") == "bust_side"

    def test_unknown_prefix_returns_default(self):
        assert _character_view_from_role("lib_scene:1") == "default"

    def test_empty_role_returns_default(self):
        assert _character_view_from_role("") == "default"

    def test_role_without_entity_id(self):
        assert _character_view_from_role("lib_character_portrait") == "front"


class TestCharacterRoleForView:
    def test_front_view(self):
        assert _character_role_for_view(entity_id=1, view="front") == "lib_character_portrait:1"

    def test_side_view(self):
        assert _character_role_for_view(entity_id=2, view="side") == "lib_character_portrait_side:2"

    def test_back_view(self):
        assert _character_role_for_view(entity_id=3, view="back") == "lib_character_portrait_back:3"

    def test_unsupported_view_raises(self):
        with pytest.raises(ValueError, match="unsupported character view"):
            _character_role_for_view(entity_id=1, view="nonexistent")


class TestAugmentLibraryPromptForRole:
    def test_non_character_role_unchanged(self):
        prompt = "a beautiful scene"
        result = _augment_library_prompt_for_role(role="lib_scene:1", prompt=prompt)
        assert result == prompt

    def test_empty_prompt_returns_empty(self):
        result = _augment_library_prompt_for_role(role="lib_character_portrait:1", prompt="")
        assert result == ""

    def test_front_view_adds_hints(self):
        result = _augment_library_prompt_for_role(role="lib_character_portrait:1", prompt="a girl")
        assert "背景" in result
        assert "构图" in result
        assert "a girl" in result

    def test_side_view_adds_side_hints(self):
        result = _augment_library_prompt_for_role(role="lib_character_portrait_side:1", prompt="a girl")
        assert "侧面全身" in result
        assert "一致性要求" in result

    def test_back_view_adds_back_hints(self):
        result = _augment_library_prompt_for_role(role="lib_character_portrait_back:1", prompt="a girl")
        assert "背面全身" in result

    def test_bust_front_view_adds_bust_hints(self):
        result = _augment_library_prompt_for_role(role="lib_character_portrait_bust:1", prompt="a girl")
        assert "正面半身" in result

    def test_no_duplicate_hints(self):
        prompt = "a girl\n背景：纯色背景，画面干净，无场景杂物、无文字、无水印、无 logo。"
        result = _augment_library_prompt_for_role(role="lib_character_portrait:1", prompt=prompt)
        assert result.startswith("a girl\n背景")


class TestResolveCharacterViewPromptSeed:
    def test_non_character_role_returns_empty(self):
        result = _resolve_character_view_prompt_seed(
            role="lib_scene:1",
            assets_by_role={},
        )
        assert result == {}

    def test_character_with_no_assets(self):
        result = _resolve_character_view_prompt_seed(
            role="lib_character_portrait_side:1",
            assets_by_role={},
        )
        assert "seed_role" in result
        assert result["seed_prompt"] == ""

    def test_character_with_front_asset(self):
        assets = {
            "lib_character_portrait:1": {
                "meta": {
                    "prompt": "a girl with red hair",
                    "descriptor": "red-haired girl",
                },
            },
        }
        result = _resolve_character_view_prompt_seed(
            role="lib_character_portrait_side:1",
            assets_by_role=assets,
        )
        assert result["seed_prompt"] == "a girl with red hair"
        assert result["anchor_descriptor"] == "red-haired girl"
        assert "lib_character_portrait:1" in result["reference_roles"]


class TestResolvePromptSeedForRole:
    def test_manual_override(self):
        raw_prompt, descriptor, seed_info, manual = _resolve_prompt_seed_for_role(
            role="lib_scene:1",
            assets_by_role={},
            request_prompt="new prompt",
            current_prompt="old prompt",
            descriptor="a scene",
        )
        assert manual is True
        assert raw_prompt == "new prompt"

    def test_no_override_uses_current(self):
        raw_prompt, descriptor, seed_info, manual = _resolve_prompt_seed_for_role(
            role="lib_scene:1",
            assets_by_role={},
            request_prompt="",
            current_prompt="current prompt",
            descriptor="a scene",
        )
        assert manual is False
        assert raw_prompt == "current prompt"

    def test_force_view_chain_seed(self):
        assets = {
            "lib_character_portrait:1": {
                "meta": {"prompt": "seed prompt", "descriptor": "seed desc"},
            },
        }
        raw_prompt, descriptor, seed_info, manual = _resolve_prompt_seed_for_role(
            role="lib_character_portrait_side:1",
            assets_by_role=assets,
            request_prompt="user prompt",
            current_prompt="current prompt",
            descriptor="a girl",
            force_view_chain_seed=True,
        )
        assert manual is False
        assert raw_prompt == "seed prompt"


class TestAttachViewChainPromptMeta:
    def test_empty_meta(self):
        result = _attach_view_chain_prompt_meta(
            {},
            seed_info={"seed_role": "lib_character_portrait:1", "reference_roles": ["lib_character_portrait:1"]},
            manual_override=False,
        )
        assert result["view_chain_prompt_seed_role"] == "lib_character_portrait:1"
        assert result["view_chain_reference_roles"] == ["lib_character_portrait:1"]
        assert result["view_chain_manual_prompt_override"] is False

    def test_manual_override_flag(self):
        result = _attach_view_chain_prompt_meta(
            {},
            seed_info={},
            manual_override=True,
        )
        assert result["view_chain_manual_prompt_override"] is True

    def test_non_dict_meta_returns_empty(self):
        result = _attach_view_chain_prompt_meta(
            "not a dict",
            seed_info={},
            manual_override=False,
        )
        assert result == {}
