"""阶段 1 价格目录单元测试。

覆盖指导文档阶段 1 验收：两模型单价一致（统一价格目录），
账单记录真实模型 ID 以区分计费；预检费率对两模型一致。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.project_audio_config import (  # noqa: E402
    SEED_AUDIO_MODEL_MULTILINGUAL,
    SEED_AUDIO_MODEL_STANDARD,
)
from app.services.audiobook.scene_engine.scene_billing import (  # noqa: E402
    build_seed_scene_billing_summary,
    resolve_seed_audio_pricing,
)


class TestUnifiedPriceCatalog:
    def test_both_models_share_identical_unit_price(self) -> None:
        checkpoints = {"scene_0001": {"billing_duration_s": 60.0}}
        standard = build_seed_scene_billing_summary(
            checkpoints, model=SEED_AUDIO_MODEL_STANDARD
        )
        multilingual = build_seed_scene_billing_summary(
            checkpoints, model=SEED_AUDIO_MODEL_MULTILINGUAL
        )
        assert standard["price_per_second_yuan"] == multilingual["price_per_second_yuan"]
        assert standard["price_per_minute_yuan"] == multilingual["price_per_minute_yuan"]
        assert standard["actual_cost_yuan"] == multilingual["actual_cost_yuan"]
        assert standard["pricing_source"] == multilingual["pricing_source"]

    def test_billing_summary_records_real_model_id(self) -> None:
        checkpoints = {"scene_0001": {"billing_duration_s": 30.0}}
        standard = build_seed_scene_billing_summary(
            checkpoints, model=SEED_AUDIO_MODEL_STANDARD
        )
        multilingual = build_seed_scene_billing_summary(
            checkpoints, model=SEED_AUDIO_MODEL_MULTILINGUAL
        )
        # 单价一致但计费记录按真实模型 ID 区分。
        assert standard["model"] == "seed-audio-1.0"
        assert multilingual["model"] == "seed-audio-1.0-multilingual"

    def test_provider_attempt_ledger_model_recorded_in_billing(self) -> None:
        attempts = (
            {
                "provider_request_id": "request-1",
                "model": SEED_AUDIO_MODEL_MULTILINGUAL,
                "original_duration": 30.0,
            },
        )
        summary = build_seed_scene_billing_summary(
            None, provider_attempts=attempts, model=SEED_AUDIO_MODEL_MULTILINGUAL
        )
        assert summary["model"] == SEED_AUDIO_MODEL_MULTILINGUAL
        assert math.isclose(summary["actual_cost_yuan"], 0.5)

    def test_pricing_rate_matches_models_yaml_catalog(self) -> None:
        import yaml

        project_root = Path(__file__).resolve().parents[2]
        catalog = yaml.safe_load(
            (project_root / "config" / "models.yaml").read_text(encoding="utf-8")
        )
        entries = {
            model["id"]: model
            for model in catalog["models"]
            if model["id"]
            in {SEED_AUDIO_MODEL_STANDARD, SEED_AUDIO_MODEL_MULTILINGUAL}
        }
        pricing = resolve_seed_audio_pricing()
        assert pricing is not None
        for model_id in (SEED_AUDIO_MODEL_STANDARD, SEED_AUDIO_MODEL_MULTILINGUAL):
            cost = entries[model_id]["cost_profile"]
            # 运行时费率与目录登记一致（1 元/分钟）。
            assert math.isclose(pricing.price_per_minute_yuan, cost["price_per_minute"])
            assert math.isclose(
                pricing.price_per_second_yuan, cost["price"], rel_tol=1e-6
            )
