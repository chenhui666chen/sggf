"""阶段 4 验收：五类固定样例 multilingual Prompt 验收（指导文档 L1429）。

验收口径：五类固定样例均生成结构正确、台词逐字一致、时长合法的
multilingual Prompt。

- 结构正确：Prompt 非空、不超过模型 Prompt 硬限制（3000 字符，§8.2），
  台词以中文引号“…”形式冻结在 Prompt 中；
- 台词逐字一致：Prompt 中的引号台词序列与 ``expected_texts`` 逐字相等，
  不得出现未声明台词，也不得改写、缺漏任何一条；
- 时长合法：期望时长落在保守规划区间（软上限 90 秒、硬规划上限 105 秒、
  模型单次输出上限 120 秒，§8.2），且台词朗读估算不超出期望时长；
- multilingual 口径：基线样例由默认 multilingual 模型消费，默认口径
  未被改写。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.duration_estimator import (  # noqa: E402
    estimate_narration_duration_seconds,
)
from app.services.audiobook.project_audio_config import (  # noqa: E402
    DEFAULT_SEED_AUDIO_MODEL,
    SEED_AUDIO_MODEL_MULTILINGUAL,
)
from app.services.audiobook.timeline_validation import (  # noqa: E402
    build_baseline_catalog,
)

_EXPECTED_SCENARIO_IDS = [
    "phone_distortion_dialogue",
    "lingshan_battle",
    "narrative_monologue",
    "live_commerce",
    "ad_timeline",
]

# 模型硬限制与保守规划口径（指导文档 §8.2）。
MODEL_PROMPT_MAX_CHARS = 3000
SOFT_MAX_DURATION_S = 90.0
HARD_MAX_DURATION_S = 105.0
MODEL_MAX_DURATION_S = 120.0

_QUOTED_TEXT_RE = re.compile(r"“([^”]*)”")


def _scenarios():
    return build_baseline_catalog()["scenarios"]


_SCENARIO_IDS = [scenario["id"] for scenario in _scenarios()]


@pytest.fixture(scope="module")
def scenario_map():
    return {scenario["id"]: scenario for scenario in _scenarios()}


class TestCatalogCoverage:
    def test_catalog_contains_exactly_five_acceptance_scenarios(self) -> None:
        assert _SCENARIO_IDS == _EXPECTED_SCENARIO_IDS


class TestPromptStructure:
    @pytest.mark.parametrize("scenario_id", _SCENARIO_IDS)
    def test_prompt_is_non_empty_and_within_model_limit(
        self, scenario_map, scenario_id
    ) -> None:
        scenario = scenario_map[scenario_id]
        prompt = scenario["prompt"]
        assert prompt.strip()
        assert len(prompt) <= MODEL_PROMPT_MAX_CHARS

    @pytest.mark.parametrize("scenario_id", _SCENARIO_IDS)
    def test_all_dialogue_is_frozen_in_chinese_quotes(
        self, scenario_map, scenario_id
    ) -> None:
        scenario = scenario_map[scenario_id]
        quoted = _QUOTED_TEXT_RE.findall(scenario["prompt"])
        assert quoted, f"{scenario_id} 的 Prompt 缺少引号台词"
        for text in scenario["expected_texts"]:
            assert text in quoted


class TestDialogueVerbatim:
    @pytest.mark.parametrize("scenario_id", _SCENARIO_IDS)
    def test_quoted_dialogue_matches_expected_texts_verbatim(
        self, scenario_map, scenario_id
    ) -> None:
        scenario = scenario_map[scenario_id]
        quoted = _QUOTED_TEXT_RE.findall(scenario["prompt"])
        assert quoted == list(scenario["expected_texts"]), (
            f"{scenario_id} 的引号台词必须与 expected_texts 逐字一致，"
            "不得新增、删减或改写"
        )


class TestDurationLegal:
    @pytest.mark.parametrize("scenario_id", _SCENARIO_IDS)
    def test_expected_duration_within_conservative_limits(
        self, scenario_map, scenario_id
    ) -> None:
        duration = scenario_map[scenario_id]["expected_duration_s"]
        assert 0 < duration <= SOFT_MAX_DURATION_S, (
            f"{scenario_id} 期望时长应位于保守规划软上限内"
        )
        assert duration <= HARD_MAX_DURATION_S
        assert duration <= MODEL_MAX_DURATION_S

    @pytest.mark.parametrize("scenario_id", _SCENARIO_IDS)
    def test_dialogue_reading_estimate_fits_expected_duration(
        self, scenario_map, scenario_id
    ) -> None:
        scenario = scenario_map[scenario_id]
        reading_s = sum(
            estimate_narration_duration_seconds(text, min_duration=0.0)
            for text in scenario["expected_texts"]
        )
        assert reading_s <= scenario["expected_duration_s"], (
            f"{scenario_id} 台词朗读估算 {reading_s:.1f}s 超出期望时长"
            f" {scenario['expected_duration_s']}s"
        )


class TestMultilingualCriteria:
    def test_baseline_scenarios_target_default_multilingual_model(self) -> None:
        assert DEFAULT_SEED_AUDIO_MODEL == SEED_AUDIO_MODEL_MULTILINGUAL
