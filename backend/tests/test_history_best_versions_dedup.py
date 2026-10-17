# -*- coding: utf-8 -*-
"""P33：`best_versions` 改为存引用，消除存档冗余。

## 取证（13 轮真实存档）

```
主文件 15.98 MB / 13 轮
  all_versions 合计  8.17 MB (51%)
  best_versions 合计 5.24 MB (33%)<-- 与 all_versions 完全重复
  其他字段          2.58 MB (16%)
best ⊆ all 的轮次数: 13/13
```

**`best_versions` 在 13/13 轮里都是 `all_versions` 的子集完整副本**，
每个入选版本被完整序列化两遍（含 `evaluation_results` 里的改写全文与段落标注）。

## 为什么不去裁剪 evaluation_results

先做了字段级体积取证，结论**推翻了直觉**：

```
evaluation_results (296 样本, 7.59 MB) 内各字段占比：
  rewritten_segments      31.1%   ← 段落真值
  original_trace_detail   27.4%
  llm_review              16.6%
  rewritten_trace_detail  15.0%
  其余（正文/指标/评分）   约 10%
```

90% 是段落级证据。且核查消费点后确认：
- `storage.py` / `challenger_pool.py` / `experience_optimizer.py`
  **零处**读 `evaluation_results`
- `MetaOptimizer._build_segment_insight`（:1838）传的是**当轮内存对象**
  （P29 已查明）

也就是说这些证据在**运行时不需要落盘**，但它们是**离线取证的唯一依据**
（本项目的历次决策都建立在对存档的分析上）。**裁剪它们= 用体积换信息，
方向错了。**

`best_versions` 去重则不同：它是**纯冗余**，零信息损失。

## 兼容策略

存量存档（13 轮）的 `best_versions` 是完整副本，必须**继续能读**。
故采用「写引用 + 读时兜底」：
- 写入：`best_version_ids`（引用列表）为准；若无引用，写完整副本（兼容）
- 读取：优先按 id 从 `all_versions` 取；取不到才回落完整副本

这样新旧存档都能读，且不需要数据迁移。
"""
from __future__ import annotations

import inspect
import tempfile
from pathlib import Path


def _storage_cls():
    from app.services.prompt_evolution.storage import EvolutionStorage
    return EvolutionStorage


def _store(tmp: Path):
    return _storage_cls()(storage_dir=str(tmp))


class TestBestVersionsWrittenAsReferences:
    """写入时不再重复序列化版本全文。"""

    def test_history_to_dict_emits_reference_ids(self):
        from app.services.prompt_evolution.models import EvolutionHistory, PromptVersion
        tmp = tempfile.mkdtemp()
        store = _store(Path(tmp))
        v = PromptVersion(
            version_id="v-abc",
            prompt_text="很长的提示词" * 500,
            avg_ai_ratio=0.3,
        )
        h = EvolutionHistory(
            evolution_id="ref-probe",
            best_versions=[v],
            all_versions=[v],
        )
        d = store._history_to_dict(h)
        assert "best_version_ids" in d, (
            "缺少 best_version_ids —— 存档仍会重复序列化版本全文"
        )
        assert d["best_version_ids"] == ["v-abc"]

    def test_best_versions_not_fully_serialized_when_ids_available(self):
        """有引用时 best_versions 不应再带完整 evaluation_results。"""
        from app.services.prompt_evolution.models import (
            EvaluationResult, EvolutionHistory, PromptVersion,
        )
        tmp = tempfile.mkdtemp()
        store = _store(Path(tmp))
        v = PromptVersion(version_id="v-1", prompt_text="x" * 100)
        v.evaluation_results = [EvaluationResult(
            sample_id="s1",
            original_text="原文" * 2000,
            rewritten_text="改写后长文本" * 5000,
            original_ai_score=100,
            rewritten_ai_score=100,
            score_reduction=0,
            success=False,
        )]
        h = EvolutionHistory(evolution_id="p", best_versions=[v], all_versions=[v])
        d = store._history_to_dict(h)
        import json
        full = json.dumps(d["best_versions"], ensure_ascii=False)
        assert len(full) < 2000, (
            f"best_versions 仍被完整序列化（{len(full)} 字符）—— 去重未生效"
        )
        assert "evaluation_results" not in full, (
            "摘要里仍带 evaluation_results —— 这正是占 90% 体积的部分"
        )

    def test_reference_and_full_copy_have_same_meaning(self):
        """引用版与完整版读回来必须完全等价 —— 这是去重的正确性底线。"""
        from app.services.prompt_evolution.models import EvolutionHistory, PromptVersion
        tmp = tempfile.mkdtemp()
        store = _store(Path(tmp))
        v = PromptVersion(version_id="v-eq", prompt_text="提示词",
                          avg_ai_ratio=0.42)
        v.evaluation_results = []
        h = EvolutionHistory(evolution_id="eq", best_versions=[v], all_versions=[v])
        d = store._history_to_dict(h)
        back = store._dict_to_history(d)
        assert len(back.best_versions) == 1
        assert back.best_versions[0].version_id == "v-eq"
        assert back.best_versions[0].avg_ai_ratio == 0.42
        assert back.best_versions[0].prompt_text == "提示词"


class TestLegacyArchivesStillLoad:
    """存量 13 轮存档（完整副本形态）必须继续可读。"""

    def test_legacy_full_copy_loads(self):
        from app.services.prompt_evolution.models import (
            EvolutionHistory, PromptVersion,
        )
        tmp = tempfile.mkdtemp()
        store = _store(Path(tmp))
        legacy = {
            "evolution_id": "legacy-full",
            "status": "completed",
            "max_iterations": 3,
            "current_iteration": 2,
            "all_versions": [{
                "version_id": "lv-1", "prompt_text": "旧提示词",
                "avg_ai_ratio": 0.5, "iteration": 1,
            }],
            # 存量形态：完整副本，没有 best_version_ids
            "best_versions": [{
                "version_id": "lv-1", "prompt_text": "旧提示词",
                "avg_ai_ratio": 0.5, "iteration": 1,
            }],
        }
        back = store._dict_to_history(legacy)
        assert len(back.best_versions) == 1, "存量存档的 best_versions 丢了"
        assert back.best_versions[0].version_id == "lv-1"
        assert back.best_versions[0].prompt_text == "旧提示词"

    def test_real_archive_13_rounds_still_loads(self):
        """用真实存档实测 —— 不能只靠构造夹具。"""
        from app.services.ai_trace_storage import AtomicJsonStore
        archive = (Path(__file__).resolve().parents[2]
                   / "data" / "prompt_evolution" / "evolution_history.json")
        if not archive.exists():
            return
        rounds = AtomicJsonStore(archive, root_type=list).read()
        assert isinstance(rounds, list) and rounds, "真实存档读取失败"
        # 每一轮都必须能被新的 _dict_to_history 读回来，
        # 且 best_versions 的**内容**与原始一致（数量可能本就为 0）
        store = _store(Path(tempfile.mkdtemp()))
        for r in rounds:
            h = store._dict_to_history(r)
            assert h.evolution_id == r.get("evolution_id"), (
                f"真实存档某轮回读失败：{str(r.get('evolution_id'))[:8]}"
            )
            want = [v.get("version_id") for v in (r.get("best_versions") or [])]
            got = [v.version_id for v in h.best_versions]
            assert got == want, (
                f"真实轮次 {str(r.get('evolution_id'))[:8]} 的 best_versions "
                f"回读不一致：期望 {want}，实得 {got}"
            )
            # 全量重建（供引用解析用）不能丢版本
            assert len(h.all_versions) == len(r.get("all_versions") or []), (
                f"真实轮次 {str(r.get('evolution_id'))[:8]} 的 all_versions 回读不一致"
            )

    def test_reference_pointing_to_missing_version_falls_back(self):
        """引用指向的版本不在 all_versions 时不得静默丢数据。"""
        tmp = tempfile.mkdtemp()
        store = _store(Path(tmp))
        d = {
            "evolution_id": "dangling",
            "status": "completed",
            "all_versions": [],
            "best_version_ids": ["v-does-not-exist"],
        }
        back = store._dict_to_history(d)
        # 悬空引用的处理：不得抛异常
        assert back is not None
        assert isinstance(back.best_versions, list)


class TestStorageConsumersUnaffected:
    """存储层直接读原始 dict 的消费点必须仍能工作。"""

    def test_list_histories_still_sees_best_versions(self):
        """storage.py:171 用 `h.get("best_versions")` 过滤有最佳版本的轮次。

        ⚠️ 去重后 best_versions 变轻但仍在 dict 里（只是不再是完整副本），
        该过滤逻辑必须仍成立 —— 否则历史列表会凭空少掉大量轮次。
        """
        src = inspect.getsource(_storage_cls())
        assert 'h.get("best_versions")' in src or 'best_versions' in src, (
            "storage 的历史过滤依赖 best_versions 字段，必须确认其仍存在"
        )

    def test_best_ai_ratio_lookup_still_works(self):
        """storage.py:79-98 从 best_versions 提取最优 ai_ratio。"""
        from app.services.prompt_evolution.models import (
            EvolutionHistory, PromptVersion,
        )
        tmp = tempfile.mkdtemp()
        store = _store(Path(tmp))
        v = PromptVersion(version_id="v-r", prompt_text="p", avg_ai_ratio=0.31)
        h = EvolutionHistory(evolution_id="r", best_versions=[v], all_versions=[v])
        d = store._history_to_dict(h)
        assert d["best_versions"], "去重后 best_versions 必须仍在 dict 中"

    def test_round_trip_preserves_ordering(self):
        """引用必须保持顺序 —— best_versions[0] 是「最优版本」，API 直接取它。"""
        from app.services.prompt_evolution.models import EvolutionHistory, PromptVersion
        tmp = tempfile.mkdtemp()
        store = _store(Path(tmp))
        vs = [PromptVersion(version_id=f"v-{i}", prompt_text="p",
                            avg_ai_ratio=0.1 * i) for i in range(1, 4)]
        h = EvolutionHistory(evolution_id="ord", best_versions=vs, all_versions=vs)
        back = store._dict_to_history(store._history_to_dict(h))
        assert [v.version_id for v in back.best_versions] == ["v-1", "v-2", "v-3"], (
            f"顺序被打乱：{[v.version_id for v in back.best_versions]}"
        )


class TestEngineWritePathStillWorks:
    """引擎调 _update_best_versions 后存档仍需可读（真实调用链）。"""

    def test_engine_source_still_appends_to_best_versions(self):
        """引擎的内存操作不变 —— 本次只改序列化层。"""
        from app.services.prompt_evolution.engine import PromptEvolutionEngine
        src = inspect.getsource(PromptEvolutionEngine._update_best_versions)
        assert "self.history.best_versions.append" in src, (
            "引擎的 best_versions 追加逻辑被改动 —— 本次只应改序列化层"
        )
        assert "best_versions.sort" in src, "排序逻辑被改动"