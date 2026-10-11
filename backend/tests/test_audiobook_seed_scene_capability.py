"""阶段 1 Seed Audio 场景能力合同单元测试。

覆盖指导文档阶段 1 要求：分析与改编 Prompt 统一使用共享能力描述常量，
不硬编码供应商模型 ID；时间轴控制仅在运行时策略通过契约验证并启用时可用。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.script_adapter_pkg._seed_scene_capability import (  # noqa: E402
    SEED_SCENE_CAPABILITY_CONTRACT_VERSION,
    SEED_SCENE_CAPABILITY_DESCRIPTION,
    build_seed_scene_main_generation_block,
)

_PKG_DIR = ROOT_DIR / "app" / "services" / "audiobook" / "script_adapter_pkg"

# 上游 Prompt 中不得出现过期硬编码主模型声明。
_HARDCODED_MODEL_ID = re.compile(r"seed-audio-1\.0(?!\-multilingual)")


class TestCapabilityDescriptionContract:
    def test_description_has_no_hardcoded_model_id(self) -> None:
        assert "seed-audio" not in SEED_SCENE_CAPABILITY_DESCRIPTION
        assert "volcengine" not in SEED_SCENE_CAPABILITY_DESCRIPTION.lower()

    def test_description_declares_timeline_availability_condition(self) -> None:
        assert "时间轴控制仅在运行时策略已通过契约验证并启用时可用" in (
            SEED_SCENE_CAPABILITY_DESCRIPTION
        )

    def test_description_declares_runtime_model_resolution(self) -> None:
        assert "真实模型 ID 由运行时配置决定" in SEED_SCENE_CAPABILITY_DESCRIPTION

    def test_contract_version_is_semver(self) -> None:
        assert re.fullmatch(r"\d+\.\d+\.\d+", SEED_SCENE_CAPABILITY_CONTRACT_VERSION)


class TestMainGenerationBlock:
    def test_block_contains_capability_description(self) -> None:
        block = build_seed_scene_main_generation_block("qwen-audio-3.1-tts-flash")
        assert SEED_SCENE_CAPABILITY_DESCRIPTION in block
        assert "qwen-audio-3.1-tts-flash" in block
        assert "试听参考音色和局部回退" in block

    def test_block_has_no_hardcoded_primary_model_id(self) -> None:
        block = build_seed_scene_main_generation_block("some-tts-model")
        assert not _HARDCODED_MODEL_ID.search(block)


class TestPromptModulesUseSharedConstant:
    def test_analysis_and_transform_reference_shared_module(self) -> None:
        for module_name in ("_analysis.py", "_transform.py"):
            source = (_PKG_DIR / module_name).read_text(encoding="utf-8")
            assert "build_seed_scene_main_generation_block" in source, module_name
            assert "主生成模型：seed-audio-1.0" not in source, module_name
