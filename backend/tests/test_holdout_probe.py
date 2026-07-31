# -*- coding: utf-8 -*-
"""
holdout 过拟合探针测试（设计文档 §11.1 holdout_score_gap · §13#3 · §14 第 10 步子块 B）

覆盖三段：
- C1 留出集划分：TestSample.is_holdout 字段持久化兼容 + 按 sample_id 哈希确定性划分
  + get_samples_by_genre holdout 过滤；
- C2 冠军新鲜复评：evaluate_holdout_gap 用注入的 evaluator stub 验证 gap 计算、缓存落盘、
  champion_hash 未变跳过重算（省外部 API 成本）、无冠军/样本不足跳过；
- C3 缓存读取降级：HoldoutScoreStore.get_gap 命中返 gap；无缓存/损坏/policy 不一致/
  超龄（TTL）/时间戳缺失一律返回 0.0 中性（不阻止入眠、不误触发）。
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services.prompt_evolution.holdout_probe import (
    HOLDOUT_GAP_MAX_AGE_HOURS,
    HoldoutScoreStore,
    champion_prompt_hash,
    evaluate_holdout_gap,
    is_record_stale,
)
from app.services.prompt_evolution.test_samples import (
    HOLDOUT_RATIO,
    TestSample,
    TestSampleManager,
    is_holdout_sample_id,
)

GENRE = "玄幻"
POLICY = "experiment-policy-v1"


# ============ 测试辅助 ============

def _sample(sample_id: str, genre: str = GENRE) -> TestSample:
    return TestSample(sample_id=sample_id, text=f"文本-{sample_id}", genre=genre)


def _manager(tmp_path, samples):
    return TestSampleManager(samples=samples, storage_dir=str(tmp_path))


class _StubEvaluator:
    """按调用顺序出分的评估器替身，记录每次收到的样本 ID 列表。"""

    def __init__(self, scores):
        self._scores = list(scores)
        self.calls = []

    async def evaluate_prompt(self, prompt, samples, **kwargs):
        self.calls.append([s.sample_id for s in samples])
        return self._scores.pop(0), []


class _StubStorage:
    """get_prompt_selection 替身：返回预设冠军或 None。"""

    def __init__(self, prompt_text=None):
        self._prompt_text = prompt_text

    def get_prompt_selection(self, genre):
        if self._prompt_text is None:
            return None
        return {"version_id": "v-test", "prompt_text": self._prompt_text, "genre": genre}


# ============ C1 留出集划分 ============

def test_sample_is_holdout_defaults_false():
    assert _sample("s1").is_holdout is False


def test_sample_dict_roundtrip_preserves_is_holdout():
    sample = _sample("s1")
    sample.is_holdout = True
    restored = TestSample.from_dict(sample.to_dict())
    assert restored.is_holdout is True


def test_from_dict_legacy_without_field_defaults_false():
    # 旧 JSON 无 is_holdout 键 → 按训练样本处理（向后兼容）
    data = _sample("legacy").to_dict()
    data.pop("is_holdout")
    assert TestSample.from_dict(data).is_holdout is False


def test_holdout_assignment_deterministic():
    ids = [f"sample_{i}" for i in range(50)]
    first = [is_holdout_sample_id(sid) for sid in ids]
    second = [is_holdout_sample_id(sid) for sid in ids]
    assert first == second


def test_holdout_ratio_approximate():
    # 200 个 ID 的留出占比应落在 HOLDOUT_RATIO 的合理邻域（哈希均匀性）
    ids = [f"ratio_sample_{i}" for i in range(200)]
    holdout_count = sum(1 for sid in ids if is_holdout_sample_id(sid))
    assert 0.15 <= holdout_count / len(ids) <= 0.45
    assert 0.0 < HOLDOUT_RATIO < 1.0


def test_apply_holdout_split_persists_and_idempotent(tmp_path):
    samples = [_sample(f"split_{i}") for i in range(40)]
    manager = _manager(tmp_path, samples)
    stats_first = manager.apply_holdout_split()
    stats_second = manager.apply_holdout_split()
    assert stats_first == stats_second
    assert stats_first["holdout"] + stats_first["training"] == 40
    # 划分结果已持久化：重新加载后归属不变
    reloaded = TestSampleManager(storage_dir=str(tmp_path))
    for sample in reloaded.get_all_samples():
        assert sample.is_holdout == is_holdout_sample_id(sample.sample_id)


def test_split_disjoint_and_complete(tmp_path):
    manager = _manager(tmp_path, [_sample(f"pool_{i}") for i in range(40)])
    manager.apply_holdout_split()
    holdout = manager.get_samples_by_genre(GENRE, holdout=True)
    training = manager.get_samples_by_genre(GENRE, holdout=False)
    everything = manager.get_samples_by_genre(GENRE)
    holdout_ids = {s.sample_id for s in holdout}
    training_ids = {s.sample_id for s in training}
    assert holdout_ids.isdisjoint(training_ids)
    assert holdout_ids | training_ids == {s.sample_id for s in everything}


def test_get_samples_by_genre_holdout_none_returns_all(tmp_path):
    manager = _manager(tmp_path, [_sample(f"all_{i}") for i in range(10)])
    manager.apply_holdout_split()
    assert len(manager.get_samples_by_genre(GENRE)) == 10


# ============ C2 冠军新鲜复评 + 缓存 ============

def _split_manager(tmp_path, count=40):
    """构造已完成划分、训练/留出均非空的样本管理器。"""
    manager = _manager(tmp_path, [_sample(f"eval_{i}") for i in range(count)])
    manager.apply_holdout_split()
    assert manager.get_samples_by_genre(GENRE, holdout=True)
    assert manager.get_samples_by_genre(GENRE, holdout=False)
    return manager


@pytest.mark.asyncio
async def test_gap_computed_and_cached(tmp_path):
    manager = _split_manager(tmp_path)
    evaluator = _StubEvaluator([20.0, 28.0])  # training → 20.0, holdout → 28.0
    store = HoldoutScoreStore(storage_dir=str(tmp_path))
    result = await evaluate_holdout_gap(
        GENRE,
        evaluator=evaluator,
        sample_manager=manager,
        storage=_StubStorage("冠军提示词全文"),
        store=store,
        policy=POLICY,
        now="2026-07-25T00:00:00+00:00",
    )
    assert result["status"] == "updated"
    assert result["gap"] == pytest.approx(8.0)
    record = store.get_record(GENRE)
    assert record["gap"] == pytest.approx(8.0)
    assert record["training_avg"] == pytest.approx(20.0)
    assert record["holdout_avg"] == pytest.approx(28.0)
    assert record["computed_at"] == "2026-07-25T00:00:00+00:00"
    assert record["champion_hash"] == champion_prompt_hash("冠军提示词全文")
    assert record["policy"] == POLICY
    # 先训练集后留出集各评一次
    assert len(evaluator.calls) == 2


@pytest.mark.asyncio
async def test_skip_when_champion_hash_unchanged(tmp_path):
    manager = _split_manager(tmp_path)
    store = HoldoutScoreStore(storage_dir=str(tmp_path))
    storage = _StubStorage("冠军提示词全文")
    await evaluate_holdout_gap(
        GENRE, evaluator=_StubEvaluator([20.0, 28.0]), sample_manager=manager,
        storage=storage, store=store, policy=POLICY,
    )
    second_evaluator = _StubEvaluator([0.0, 0.0])
    result = await evaluate_holdout_gap(
        GENRE, evaluator=second_evaluator, sample_manager=manager,
        storage=storage, store=store, policy=POLICY,
    )
    # 冠军与 policy 均未变 → 跳过重算，不再调用外部评分
    assert result["status"] == "skipped_cached"
    assert second_evaluator.calls == []
    assert store.get_gap(GENRE, policy=POLICY) == pytest.approx(8.0)


@pytest.mark.asyncio
async def test_recompute_when_champion_changes(tmp_path):
    manager = _split_manager(tmp_path)
    store = HoldoutScoreStore(storage_dir=str(tmp_path))
    await evaluate_holdout_gap(
        GENRE, evaluator=_StubEvaluator([20.0, 28.0]), sample_manager=manager,
        storage=_StubStorage("旧冠军"), store=store, policy=POLICY,
    )
    evaluator = _StubEvaluator([15.0, 17.0])
    result = await evaluate_holdout_gap(
        GENRE, evaluator=evaluator, sample_manager=manager,
        storage=_StubStorage("新冠军"), store=store, policy=POLICY,
    )
    assert result["status"] == "updated"
    assert result["gap"] == pytest.approx(2.0)
    assert len(evaluator.calls) == 2
    assert store.get_record(GENRE)["champion_hash"] == champion_prompt_hash("新冠军")


@pytest.mark.asyncio
async def test_skip_when_no_champion(tmp_path):
    manager = _split_manager(tmp_path)
    evaluator = _StubEvaluator([])
    result = await evaluate_holdout_gap(
        GENRE, evaluator=evaluator, sample_manager=manager,
        storage=_StubStorage(None), store=HoldoutScoreStore(storage_dir=str(tmp_path)),
        policy=POLICY,
    )
    assert result["status"] == "skipped_no_champion"
    assert evaluator.calls == []


@pytest.mark.asyncio
async def test_skip_when_insufficient_samples(tmp_path):
    # 单样本必然缺训练或留出一侧 → 证据不足跳过，不调用外部评分
    manager = _manager(tmp_path, [_sample("only_one")])
    manager.apply_holdout_split()
    evaluator = _StubEvaluator([])
    result = await evaluate_holdout_gap(
        GENRE, evaluator=evaluator, sample_manager=manager,
        storage=_StubStorage("冠军"), store=HoldoutScoreStore(storage_dir=str(tmp_path)),
        policy=POLICY,
    )
    assert result["status"] == "skipped_insufficient_samples"
    assert evaluator.calls == []


# ============ C3 缓存读取降级（tick 消费口径） ============

def test_get_gap_missing_returns_zero(tmp_path):
    store = HoldoutScoreStore(storage_dir=str(tmp_path))
    assert store.get_gap(GENRE, policy=POLICY) == 0.0


def test_get_gap_policy_mismatch_returns_zero(tmp_path):
    store = HoldoutScoreStore(storage_dir=str(tmp_path))
    store.set_record(GENRE, {"gap": 9.0, "policy": "experiment-policy-v0"})
    assert store.get_gap(GENRE, policy=POLICY) == 0.0


def test_get_gap_corrupt_file_returns_zero(tmp_path):
    (tmp_path / "holdout_scores.json").write_text("{broken", encoding="utf-8")
    store = HoldoutScoreStore(storage_dir=str(tmp_path))
    assert store.get_gap(GENRE, policy=POLICY) == 0.0


def test_get_gap_hit_returns_cached_value(tmp_path):
    store = HoldoutScoreStore(storage_dir=str(tmp_path))
    store.set_record(GENRE, {"gap": 3.5, "policy": POLICY, "computed_at": _iso_ago(hours=1)})
    assert store.get_gap(GENRE, policy=POLICY) == pytest.approx(3.5)
    # 落盘为合法 JSON（原子写）
    data = json.loads((tmp_path / "holdout_scores.json").read_text(encoding="utf-8"))
    assert data[GENRE]["gap"] == pytest.approx(3.5)


# ============ 缓存新鲜度（TTL，2× 每日 beat 周期） ============

def _iso_ago(*, hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def test_get_gap_stale_returns_zero(tmp_path):
    # computed_at 超过 HOLDOUT_GAP_MAX_AGE_HOURS → 任务停摆旧缓存不再生效
    store = HoldoutScoreStore(storage_dir=str(tmp_path))
    store.set_record(
        GENRE,
        {"gap": 9.0, "policy": POLICY, "computed_at": _iso_ago(hours=HOLDOUT_GAP_MAX_AGE_HOURS + 1)},
    )
    assert store.get_gap(GENRE, policy=POLICY) == 0.0


def test_get_gap_fresh_within_ttl(tmp_path):
    store = HoldoutScoreStore(storage_dir=str(tmp_path))
    store.set_record(
        GENRE,
        {"gap": 4.0, "policy": POLICY, "computed_at": _iso_ago(hours=HOLDOUT_GAP_MAX_AGE_HOURS - 1)},
    )
    assert store.get_gap(GENRE, policy=POLICY) == pytest.approx(4.0)


def test_get_gap_missing_timestamp_returns_zero(tmp_path):
    # 时间戳缺失/不可解析按超龄保守降级
    store = HoldoutScoreStore(storage_dir=str(tmp_path))
    store.set_record(GENRE, {"gap": 4.0, "policy": POLICY})
    assert store.get_gap(GENRE, policy=POLICY) == 0.0
    store.set_record(GENRE, {"gap": 4.0, "policy": POLICY, "computed_at": "不是时间"})
    assert store.get_gap(GENRE, policy=POLICY) == 0.0


def test_get_gap_now_injectable(tmp_path):
    # now 可注入：以未来时点消费同一记录 → 超龄降级
    store = HoldoutScoreStore(storage_dir=str(tmp_path))
    store.set_record(GENRE, {"gap": 4.0, "policy": POLICY, "computed_at": _iso_ago(hours=0)})
    assert store.get_gap(GENRE, policy=POLICY) == pytest.approx(4.0)
    future = datetime.now(timezone.utc) + timedelta(hours=HOLDOUT_GAP_MAX_AGE_HOURS + 1)
    assert store.get_gap(GENRE, policy=POLICY, now=future) == 0.0


# ============ 信号观测口径（面板 signals 元数据） ============

def test_describe_signal_fresh_record(tmp_path):
    store = HoldoutScoreStore(storage_dir=str(tmp_path))
    computed_at = _iso_ago(hours=1)
    store.set_record(GENRE, {"gap": 3.5, "policy": POLICY, "computed_at": computed_at})
    info = store.describe_signal(GENRE, policy=POLICY)
    assert info == {"gap": pytest.approx(3.5), "computed_at": computed_at,
                    "stale": False, "defaulted": False}


def test_describe_signal_missing_record(tmp_path):
    store = HoldoutScoreStore(storage_dir=str(tmp_path))
    info = store.describe_signal(GENRE, policy=POLICY)
    assert info == {"gap": 0.0, "computed_at": None, "stale": False, "defaulted": True}


def test_describe_signal_stale_and_policy_mismatch(tmp_path):
    store = HoldoutScoreStore(storage_dir=str(tmp_path))
    # 超龄记录：stale=True 且消费值降级
    stale_at = _iso_ago(hours=HOLDOUT_GAP_MAX_AGE_HOURS + 1)
    store.set_record(GENRE, {"gap": 9.0, "policy": POLICY, "computed_at": stale_at})
    info = store.describe_signal(GENRE, policy=POLICY)
    assert info == {"gap": 0.0, "computed_at": stale_at, "stale": True, "defaulted": True}
    # policy 不一致但新鲜：stale=False、defaulted=True
    fresh_at = _iso_ago(hours=1)
    store.set_record(GENRE, {"gap": 9.0, "policy": "experiment-policy-v0", "computed_at": fresh_at})
    info = store.describe_signal(GENRE, policy=POLICY)
    assert info == {"gap": 0.0, "computed_at": fresh_at, "stale": False, "defaulted": True}


# ============ 生产端保鲜闭环（评审修复 1）+ 未来时间戳（评审修复 2） ============

@pytest.mark.asyncio
async def test_recompute_when_cached_record_is_stale(tmp_path):
    # 同冠军 + 同 policy 但缓存超龄 → 必须重算刷新，否则消费端永久降级 0.0 不可恢复
    manager = _split_manager(tmp_path)
    store = HoldoutScoreStore(storage_dir=str(tmp_path))
    prompt = "冠军提示词全文"
    store.set_record(
        GENRE,
        {
            "gap": 9.0,
            "training_avg": 1.0,
            "holdout_avg": 10.0,
            "computed_at": _iso_ago(hours=HOLDOUT_GAP_MAX_AGE_HOURS + 1),
            "champion_hash": champion_prompt_hash(prompt),
            "policy": POLICY,
        },
    )
    evaluator = _StubEvaluator([10.0, 12.0])
    result = await evaluate_holdout_gap(
        GENRE, evaluator=evaluator, sample_manager=manager,
        storage=_StubStorage(prompt), store=store, policy=POLICY,
    )
    assert result["status"] == "updated"
    assert result["gap"] == pytest.approx(2.0)
    assert len(evaluator.calls) == 2
    # computed_at 已刷新为新鲜 → 消费端恢复真实值
    assert not is_record_stale(
        store.get_record(GENRE)["computed_at"], HOLDOUT_GAP_MAX_AGE_HOURS
    )
    assert store.get_gap(GENRE, policy=POLICY) == pytest.approx(2.0)


def test_future_timestamp_is_stale(tmp_path):
    # 未来时间戳不可信（时钟异常/人工改动），按超龄处理，不得无限新鲜
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    assert is_record_stale(future, HOLDOUT_GAP_MAX_AGE_HOURS) is True
    store = HoldoutScoreStore(storage_dir=str(tmp_path))
    store.set_record(GENRE, {"gap": 4.0, "policy": POLICY, "computed_at": future})
    assert store.get_gap(GENRE, policy=POLICY) == 0.0
    info = store.describe_signal(GENRE, policy=POLICY)
    assert info["stale"] is True
    assert info["defaulted"] is True


# ============ gap 严格有限数值校验（三轮评审修复：bool/NaN/inf 不得穿透） ============

@pytest.mark.parametrize(
    "bad_gap",
    [True, False, float("nan"), float("inf"), float("-inf")],
    ids=["true", "false", "nan", "inf", "-inf"],
)
def test_gap_invalid_numeric_value_defaults(tmp_path, bad_gap):
    # bool 是 int 子类、json 默认解析 NaN/Infinity——均为合法 JSON 但非法 gap，
    # 消费降级 0.0 且面板 defaulted=True（NaN 会让休眠门槛比较恒 False 永不休眠）
    store = HoldoutScoreStore(storage_dir=str(tmp_path))
    store.set_record(
        GENRE, {"gap": bad_gap, "policy": POLICY, "computed_at": _iso_ago(hours=1)}
    )
    assert store.get_gap(GENRE, policy=POLICY) == 0.0
    info = store.describe_signal(GENRE, policy=POLICY)
    assert info["stale"] is False
    assert info["defaulted"] is True


@pytest.mark.asyncio
async def test_evaluate_holdout_gap_rejects_non_finite_scores(tmp_path):
    # 外部评分返回非有限值时抛明确异常（任务层单题材兜底接住），旧缓存不被污染
    manager = _split_manager(tmp_path)
    store = HoldoutScoreStore(storage_dir=str(tmp_path))
    old_record = {
        "gap": 1.5,
        "policy": POLICY,
        "computed_at": _iso_ago(hours=1),
        "champion_hash": "hash-of-old-champion",
    }
    store.set_record(GENRE, old_record)
    evaluator = _StubEvaluator([float("nan"), 12.0])
    with pytest.raises(ValueError, match="training_avg"):
        await evaluate_holdout_gap(
            GENRE, evaluator=evaluator, sample_manager=manager,
            storage=_StubStorage("新冠军提示词"), store=store, policy=POLICY,
        )
    assert store.get_record(GENRE) == old_record
