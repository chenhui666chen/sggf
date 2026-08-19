"""阶段 1 checkpoint schema registry 与 append-only 迁移单元测试。

覆盖指导文档 §12.2 历史恢复原则与阶段 1 验收：
- checkpoint schema registry 与 contract version 定义；
- 普通 1.0 历史 checkpoint、缺字段 checkpoint、旧签名 checkpoint 三类输入；
- append-only 迁移幂等、不覆盖旧签名、不重烧音频、不重置账单；
- migration_input_hash 使用版本化 canonical_hash 合同；
- 无法证明兼容时进入 legacy_checkpoint_incompatible；
- 历史 checkpoint 按记录的原模型恢复。
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
for _path in (ROOT_DIR, TESTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_engine.checkpoint_contracts import (  # noqa: E402
    CURRENT_SEED_SCENE_CHECKPOINT_SCHEMA_VERSION,
    SEED_SCENE_CHECKPOINT_TYPE,
    get_checkpoint_schema,
    validate_checkpoint_identity,
)
from app.services.audiobook.scene_engine.checkpoint_migration import (  # noqa: E402
    SEED_SCENE_V1_TO_V2_MIGRATION_VERSION,
    compute_checkpoint_identity,
    compute_migration_input_hash,
    migrate_seed_scene_checkpoint,
)
from app.services.audiobook.scene_engine.scene_billing import (  # noqa: E402
    build_seed_scene_billing_summary,
)

_FIXED_NOW = "2026-08-11T00:00:00+00:00"


def _legacy_v1_checkpoint() -> dict:
    """历史普通 1.0 场景 checkpoint（schema v1）。"""
    return {
        "schema_version": 1,
        "renderer_version": "scene-render-service-v2",
        "model": "seed-audio-1.0",
        "audio_config": {"format": "mp3", "sample_rate": 48000},
        "scene_id": "scene_0001",
        "source_segment_indices": [0, 1],
        "source_text_hash": "text-hash",
        "prompt_hash": "prompt-hash",
        "quality_policy_hash": "policy-hash",
        "reference_hashes": ["reference-hash"],
        "status": "passed",
        "attempts": 1,
        "audio_path": "backend/data/scene_0001.wav",
        "billing_duration_s": 12.5,
        "provider_request_ids": ["request-legacy-1"],
    }


class TestCheckpointSchemaRegistry:
    def test_registry_covers_v1_and_v2(self) -> None:
        assert CURRENT_SEED_SCENE_CHECKPOINT_SCHEMA_VERSION == 2
        assert get_checkpoint_schema(1) is not None
        assert get_checkpoint_schema(2) is not None
        assert get_checkpoint_schema(99) is None

    def test_current_schema_declares_required_metadata_fields(self) -> None:
        schema = get_checkpoint_schema(CURRENT_SEED_SCENE_CHECKPOINT_SCHEMA_VERSION)
        required = set(schema.required_fields)
        assert {
            "checkpoint_type",
            "signature_contract_version",
            "producer_version",
        } <= required

    def test_validate_identity_reports_missing_fields(self) -> None:
        checkpoint = _legacy_v1_checkpoint()
        ok, problems = validate_checkpoint_identity(checkpoint)
        assert ok and problems == ()

        del checkpoint["model"]
        ok, problems = validate_checkpoint_identity(checkpoint)
        assert not ok
        assert any("model" in problem for problem in problems)


class TestMigrationInputHashContract:
    def test_hash_is_deterministic_and_field_order_insensitive(self) -> None:
        checkpoint_a = _legacy_v1_checkpoint()
        checkpoint_b = dict(reversed(list(checkpoint_a.items())))
        hash_a = compute_migration_input_hash(
            checkpoint_a, migration_version=SEED_SCENE_V1_TO_V2_MIGRATION_VERSION
        )
        hash_b = compute_migration_input_hash(
            checkpoint_b, migration_version=SEED_SCENE_V1_TO_V2_MIGRATION_VERSION
        )
        assert hash_a == hash_b

    def test_hash_changes_with_migration_version(self) -> None:
        checkpoint = _legacy_v1_checkpoint()
        hash_a = compute_migration_input_hash(checkpoint, migration_version="m@1.0.0")
        hash_b = compute_migration_input_hash(checkpoint, migration_version="m@2.0.0")
        assert hash_a != hash_b

    def test_hash_changes_with_checkpoint_identity(self) -> None:
        checkpoint = _legacy_v1_checkpoint()
        hash_a = compute_migration_input_hash(
            checkpoint, migration_version=SEED_SCENE_V1_TO_V2_MIGRATION_VERSION
        )
        mutated = dict(checkpoint, prompt_hash="other-prompt")
        hash_b = compute_migration_input_hash(
            mutated, migration_version=SEED_SCENE_V1_TO_V2_MIGRATION_VERSION
        )
        assert hash_a != hash_b


class TestAppendOnlyMigration:
    def test_migrates_historical_standard_checkpoint(self) -> None:
        original = _legacy_v1_checkpoint()
        snapshot = copy.deepcopy(original)

        result = migrate_seed_scene_checkpoint(original, now_iso=_FIXED_NOW)

        assert result.status == "migrated"
        migrated = result.checkpoint
        assert migrated is not None
        # append-only：原 checkpoint 保持只读
        assert original == snapshot
        # 新版本升级为 v2 且携带迁移审计字段
        assert migrated["schema_version"] == 2
        assert migrated["checkpoint_type"] == SEED_SCENE_CHECKPOINT_TYPE
        assert migrated["signature_contract_version"]
        assert migrated["producer_version"] == original["renderer_version"]
        assert migrated["original_schema_version"] == 1
        assert migrated["migration_version"] == SEED_SCENE_V1_TO_V2_MIGRATION_VERSION
        assert migrated["migration_input_hash"] == result.migration_input_hash
        assert migrated["migration_status"] == "migrated"
        assert migrated["migrated_at"] == _FIXED_NOW
        assert migrated["migrated_from_checkpoint_hash"] == compute_checkpoint_identity(
            original
        )
        history = migrated["migration_history"]
        assert len(history) == 1
        assert history[0]["migration_version"] == SEED_SCENE_V1_TO_V2_MIGRATION_VERSION

    def test_migration_preserves_old_signature_fields(self) -> None:
        original = _legacy_v1_checkpoint()
        result = migrate_seed_scene_checkpoint(original, now_iso=_FIXED_NOW)
        migrated = result.checkpoint
        # 旧签名字段逐项继承，不得重算或覆盖
        for key in (
            "model",
            "prompt_hash",
            "quality_policy_hash",
            "reference_hashes",
            "audio_config",
            "scene_id",
            "renderer_version",
            "audio_path",
            "status",
            "attempts",
        ):
            assert migrated[key] == original[key], key

    def test_migration_is_idempotent(self) -> None:
        original = _legacy_v1_checkpoint()
        first = migrate_seed_scene_checkpoint(original, now_iso=_FIXED_NOW)
        second = migrate_seed_scene_checkpoint(original, now_iso=_FIXED_NOW)
        assert first.status == second.status == "migrated"
        assert first.migration_input_hash == second.migration_input_hash
        assert first.checkpoint["migrated_from_checkpoint_hash"] == (
            second.checkpoint["migrated_from_checkpoint_hash"]
        )

    def test_already_migrated_checkpoint_is_not_migrated_again(self) -> None:
        original = _legacy_v1_checkpoint()
        first = migrate_seed_scene_checkpoint(original, now_iso=_FIXED_NOW)

        repeat = migrate_seed_scene_checkpoint(first.checkpoint, now_iso=_FIXED_NOW)

        assert repeat.status == "already_migrated"
        assert repeat.checkpoint == first.checkpoint
        # 不叠加迁移历史
        assert len(repeat.checkpoint["migration_history"]) == 1

    def test_missing_field_checkpoint_is_incompatible(self) -> None:
        checkpoint = _legacy_v1_checkpoint()
        del checkpoint["model"]

        result = migrate_seed_scene_checkpoint(checkpoint, now_iso=_FIXED_NOW)

        assert result.status == "legacy_checkpoint_incompatible"
        assert result.checkpoint is None
        assert result.reasons
        # 缺字段不得静默当作命中，也不得破坏旧 checkpoint
        assert "model" not in checkpoint

    def test_old_signature_checkpoint_is_incompatible(self) -> None:
        checkpoint = _legacy_v1_checkpoint()
        checkpoint["schema_version"] = 0

        result = migrate_seed_scene_checkpoint(checkpoint, now_iso=_FIXED_NOW)

        assert result.status == "legacy_checkpoint_incompatible"
        assert result.checkpoint is None

    def test_missing_schema_version_is_incompatible(self) -> None:
        checkpoint = _legacy_v1_checkpoint()
        del checkpoint["schema_version"]

        result = migrate_seed_scene_checkpoint(checkpoint, now_iso=_FIXED_NOW)

        assert result.status == "legacy_checkpoint_incompatible"

    def test_unknown_schema_version_is_incompatible(self) -> None:
        checkpoint = _legacy_v1_checkpoint()
        checkpoint["schema_version"] = 99

        result = migrate_seed_scene_checkpoint(checkpoint, now_iso=_FIXED_NOW)

        assert result.status == "legacy_checkpoint_incompatible"

    def test_non_mapping_input_is_incompatible(self) -> None:
        result = migrate_seed_scene_checkpoint(None, now_iso=_FIXED_NOW)  # type: ignore[arg-type]
        assert result.status == "legacy_checkpoint_incompatible"


class TestMigrationDoesNotResetBilling:
    def test_billing_summary_unchanged_after_migration(self) -> None:
        original = _legacy_v1_checkpoint()
        migrated = migrate_seed_scene_checkpoint(
            original, now_iso=_FIXED_NOW
        ).checkpoint

        before = build_seed_scene_billing_summary(
            {"scene_0001": original}, model=original["model"]
        )
        after = build_seed_scene_billing_summary(
            {"scene_0001": migrated}, model=migrated["model"]
        )
        # 迁移只引用账本与计费记录，不复制、不重置
        assert before == after
        assert after["provider_request_count"] == 1
        assert after["billable_duration_s"] == 12.5


class TestHistoricalCheckpointRestoresWithOriginalModel:
    def test_pipeline_resolves_resume_model_from_checkpoint(self) -> None:
        from app.services.audiobook.scene_engine.chapter_pipeline import (
            ChapterScenePipeline,
        )

        checkpoint = _legacy_v1_checkpoint()
        resolved = ChapterScenePipeline._resume_model(  # noqa: SLF001
            checkpoint, fallback_model="seed-audio-1.0-multilingual"
        )
        # 历史普通 1.0 checkpoint 仍请求原模型
        assert resolved == "seed-audio-1.0"

    def test_pipeline_uses_requested_model_for_incomplete_checkpoint(self) -> None:
        from app.services.audiobook.scene_engine.chapter_pipeline import (
            ChapterScenePipeline,
        )

        checkpoint = _legacy_v1_checkpoint()
        checkpoint["status"] = "failed"
        resolved = ChapterScenePipeline._resume_model(  # noqa: SLF001
            checkpoint, fallback_model="seed-audio-1.0-multilingual"
        )
        assert resolved == "seed-audio-1.0-multilingual"

    def test_pipeline_uses_requested_model_without_checkpoint(self) -> None:
        from app.services.audiobook.scene_engine.chapter_pipeline import (
            ChapterScenePipeline,
        )

        resolved = ChapterScenePipeline._resume_model(  # noqa: SLF001
            None, fallback_model="seed-audio-1.0-multilingual"
        )
        assert resolved == "seed-audio-1.0-multilingual"
