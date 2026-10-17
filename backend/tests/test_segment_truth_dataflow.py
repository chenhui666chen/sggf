# -*- coding: utf-8 -*-
"""段落真值数据流守卫（P29）。

## 背景：P4「遗留」项被证伪

P4（2026-10-16）遗留记录：
    「段落真值未持久化到样本库：`test_samples.json` 已有
      `ai_detection_ai_segments`（**原文**段落真值），但**改写后**的段落标注
      目前只随版本存档走，样本库侧不落。」
    推论：这会限制「按段落做特征归因」的能力上限。

## 取证：推论的前提不成立

段落特征归因的实现是 `MetaOptimizer._build_segment_insight(samples)`：

- `meta_optimizer.py:1091` 函数签名收 `List[EvaluationResult]`
- `meta_optimizer.py:1838` 调用处传入 `results` —— **当轮评估的内存结果**
- `:1106` 从 `r.rewritten_segments` 取数据，而 `rewritten_segments` 是
  `EvaluationResult` 的字段（`models.py:82`），由 `evaluator` 现场产出

**归因消费的是「本轮内存中的评估结果」，不是从样本库读。**
所以把改写段落真值落进样本库，对归因能力**没有任何提升**。

## 样本库的段落真值是另一回事，且有明确设计

`test_samples.py` 的 `ai_detection_ai_segments` 注释写得很清楚：
    「仅持久化『被判确定AI』的段原文，**供定点改写生成真值指令**
      （novel_rules.build_detector_segment_hint）。不落供应商原始响应，
      只存最小可用字段」

它是给**下一次进化的定点改写**提供**原文**真值 —— 与「改写段落真值」
是两件不同的事。前者已完整实现（含 `get_ai_detection` 的缓存还原逻辑）。

## 本守卫的作用

防止后来者再次提出「把改写段落真值落样本库」——
那是一次会增加存档体积（实测单轮段落字段约 3KB × 样本数）
却不带来任何归因收益的改动。

顺带锁定现状：改写段落真值必须**随版本存档保留**（P0~P20 取证依赖它）。
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_OPT = "backend/app/services/prompt_evolution/meta_optimizer.py"
SAMPLES = "backend/app/services/prompt_evolution/test_samples.py"
MODELS = "backend/app/services/prompt_evolution/models.py"


def _src(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


class TestAttributionReadsInMemoryResults:
    """归因的数据来源：当轮内存结果，不是样本库。"""

    def test_segment_insight_signature(self):
        src = _src(ENGINE_OPT)
        assert "_build_segment_insight" in src, "段落归因函数缺失"

    def test_called_with_current_results(self):
        """调用处传入的是当轮 `results`，证明数据来自内存。"""
        src = _src(ENGINE_OPT)
        assert "self._build_segment_insight(results)" in src, (
            "段落归因应消费当轮评估结果（内存），"
            "这是它不依赖样本库存档的关键证据"
        )

    def test_reads_from_evaluation_result_field(self):
        src = _src(ENGINE_OPT)
        assert "r.rewritten_segments" in src, (
            "归因应从 EvaluationResult.rewritten_segments 读取"
        )


class TestSampleSegmentsServeDifferentPurpose:
    """样本库段落真值：供**定点改写**用原文真值，是另一件事。"""

    def test_field_exists_with_purpose_documented(self):
        src = _src(SAMPLES)
        assert "ai_detection_ai_segments" in src, "原文段落真值字段缺失"
        assert "build_detector_segment_hint" in src, (
            "应记录该字段的用途：供定点改写生成真值指令"
        )

    def test_minimal_fields_only(self):
        """只存最小可用字段，不落供应商原始响应。"""
        src = _src(SAMPLES)
        assert "不持久化供应商原始响应" in src, (
            "样本库段落真值应坚持最小字段原则"
        )

    def test_cache_restores_segment_labels(self):
        """走持久化缓存时也要能还原段落标注结构。"""
        src = _src(SAMPLES)
        assert "segment_labels" in src, (
            "get_ai_detection 应能还原 segment_labels，"
            "否则缓存命中时定点改写拿不到真值"
        )


class TestRewrittenSegmentsRetainedInArchive:
    """改写段落真值仍必须随版本存档保留 —— P0~P20 取证依赖它。"""

    def test_in_models(self):
        src = _src(MODELS)
        assert "rewritten_segments" in src, (
            "EvaluationResult.rewritten_segments 被移除 —— "
            "段落归因与失败详情都依赖它"
        )

    def test_serialized_in_archive(self):
        src = _src(MODELS)
        assert "rewritten_segments" in src, "段落真值未纳入序列化"

    def test_not_pushed_into_sample_store(self):
        """改写段落真值**不应**进样本库 —— 那是无收益的体积负担。

        样本库服务的是「下一次进化的定点改写」，只需要原文真值。
        """
        src = _src(SAMPLES)
        assert "rewritten_segments" not in src, (
            "改写段落真值不应写入样本库 —— 归因读的是当轮内存结果，"
            "入库只增加体积不带来收益"
        )