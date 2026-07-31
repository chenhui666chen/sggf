# -*- coding: utf-8 -*-
"""
哨兵巡检探针测试（设计文档 §11.2 sentinel_degraded 信号 5 · §14 第 10 步子块 B）

覆盖三段：
- 哨兵语料选取：holdout 留出子集按 sample_id 排序取前 N（确定性、恒定语料）；
- 探针判定：首次探测建基线不退化；同冠军同 policy 下 last - baseline > wake_ai_score_rise
  置退化；未超阈值不退化；冠军/policy 变更基线重置；无冠军/无哨兵样本跳过；
- 缓存读取降级：SentinelStateStore.is_degraded 命中返回缓存标志；无缓存/损坏/policy
  不一致/超龄（TTL）/时间戳缺失一律 False（不误唤醒，安全侧）。
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services.prompt_evolution.evolution_scheduler import DEFAULT_WAKE_AI_SCORE_RISE
from app.services.prompt_evolution.sentinel_probe import (
    SENTINEL_SAMPLE_COUNT,
    SENTINEL_STATE_MAX_AGE_HOURS,
    SentinelStateStore,
    run_sentinel_probe_for_genre,
    select_sentinel_samples,
)
from app.services.prompt_evolution.test_samples import TestSample, TestSampleManager

GENRE = "玄幻"
POLICY = "experiment-policy-v1"


# ============ 测试辅助 ============

def _sample(sample_id: str, *, is_holdout: bool = True, genre: str = GENRE) -> TestSample:
    return TestSample(
        sample_id=sample_id, text=f"文本-{sample_id}", genre=genre, is_holdout=is_holdout
    )


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
    def __init__(self, prompt_text=None):
        self._prompt_text = prompt_text

    def get_prompt_selection(self, genre):
        if self._prompt_text is None:
            return None
        return {"version_id": "v-test", "prompt_text": self._prompt_text, "genre": genre}


async def _probe(tmp_path, *, evaluator, storage, store, manager=None):
    if manager is None:
        manager = _manager(tmp_path, [_sample(f"sentinel_{i}") for i in range(8)])
    return await run_sentinel_probe_for_genre(
        GENRE,
        evaluator=evaluator,
        sample_manager=manager,
        storage=storage,
        store=store,
        policy=POLICY,
    )


# ============ 哨兵语料选取 ============

def test_select_sentinel_samples_sorted_prefix(tmp_path):
    # 乱序入池，选取结果按 sample_id 排序取前 N，且只含留出样本
    ids = [f"s_{i:02d}" for i in range(9, -1, -1)]
    samples = [_sample(sid) for sid in ids] + [_sample("t_train", is_holdout=False)]
    manager = _manager(tmp_path, samples)
    selected = select_sentinel_samples(manager, GENRE)
    assert [s.sample_id for s in selected] == sorted(ids)[:SENTINEL_SAMPLE_COUNT]
    assert all(s.is_holdout for s in selected)


def test_select_sentinel_samples_deterministic(tmp_path):
    manager = _manager(tmp_path, [_sample(f"d_{i}") for i in range(8)])
    first = [s.sample_id for s in select_sentinel_samples(manager, GENRE)]
    second = [s.sample_id for s in select_sentinel_samples(manager, GENRE)]
    assert first == second


def test_select_sentinel_samples_fewer_than_count(tmp_path):
    manager = _manager(tmp_path, [_sample("only_1"), _sample("only_2")])
    assert len(select_sentinel_samples(manager, GENRE)) == 2


# ============ 探针判定 ============

@pytest.mark.asyncio
async def test_first_probe_establishes_baseline(tmp_path):
    store = SentinelStateStore(storage_dir=str(tmp_path))
    result = await _probe(
        tmp_path, evaluator=_StubEvaluator([20.0]), storage=_StubStorage("冠军"), store=store
    )
    assert result["status"] == "baseline_established"
    assert result["degraded"] is False
    record = store.get_record(GENRE)
    assert record["baseline_score"] == pytest.approx(20.0)
    assert record["last_score"] == pytest.approx(20.0)
    assert record["degraded"] is False
    assert record["policy"] == POLICY


@pytest.mark.asyncio
async def test_degraded_when_rise_exceeds_wake_threshold(tmp_path):
    store = SentinelStateStore(storage_dir=str(tmp_path))
    storage = _StubStorage("冠军")
    await _probe(tmp_path, evaluator=_StubEvaluator([20.0]), storage=storage, store=store)
    # 回升 20.0 → 30.0，超过 wake_ai_score_rise=8.0 → 退化
    result = await _probe(
        tmp_path, evaluator=_StubEvaluator([30.0]), storage=storage, store=store
    )
    assert result["status"] == "probed"
    assert result["degraded"] is True
    assert store.is_degraded(GENRE, policy=POLICY) is True
    # 基线保持首测值不随退化漂移
    assert store.get_record(GENRE)["baseline_score"] == pytest.approx(20.0)
    assert 30.0 - 20.0 > DEFAULT_WAKE_AI_SCORE_RISE


@pytest.mark.asyncio
async def test_not_degraded_when_rise_within_threshold(tmp_path):
    store = SentinelStateStore(storage_dir=str(tmp_path))
    storage = _StubStorage("冠军")
    await _probe(tmp_path, evaluator=_StubEvaluator([20.0]), storage=storage, store=store)
    result = await _probe(
        tmp_path, evaluator=_StubEvaluator([25.0]), storage=storage, store=store
    )
    assert result["degraded"] is False
    assert store.is_degraded(GENRE, policy=POLICY) is False


@pytest.mark.asyncio
async def test_baseline_reset_when_champion_changes(tmp_path):
    store = SentinelStateStore(storage_dir=str(tmp_path))
    await _probe(tmp_path, evaluator=_StubEvaluator([20.0]), storage=_StubStorage("旧冠军"), store=store)
    # 换冠军后即便分数大涨也不判退化（与旧基线不可比），重建基线
    result = await _probe(
        tmp_path, evaluator=_StubEvaluator([40.0]), storage=_StubStorage("新冠军"), store=store
    )
    assert result["status"] == "baseline_established"
    assert result["degraded"] is False
    assert store.get_record(GENRE)["baseline_score"] == pytest.approx(40.0)


@pytest.mark.asyncio
async def test_recovery_clears_degraded_flag(tmp_path):
    store = SentinelStateStore(storage_dir=str(tmp_path))
    storage = _StubStorage("冠军")
    await _probe(tmp_path, evaluator=_StubEvaluator([20.0]), storage=storage, store=store)
    await _probe(tmp_path, evaluator=_StubEvaluator([30.0]), storage=storage, store=store)
    assert store.is_degraded(GENRE, policy=POLICY) is True
    # 检测分回落 → 标志清除（滞回由三态转移层负责，探针只报当前事实）
    await _probe(tmp_path, evaluator=_StubEvaluator([21.0]), storage=storage, store=store)
    assert store.is_degraded(GENRE, policy=POLICY) is False


@pytest.mark.asyncio
async def test_skip_when_no_champion(tmp_path):
    evaluator = _StubEvaluator([])
    result = await _probe(
        tmp_path, evaluator=evaluator, storage=_StubStorage(None),
        store=SentinelStateStore(storage_dir=str(tmp_path)),
    )
    assert result["status"] == "skipped_no_champion"
    assert evaluator.calls == []


@pytest.mark.asyncio
async def test_skip_when_no_sentinel_samples(tmp_path):
    # 全训练侧样本 → 无哨兵语料，跳过且不调用外部评分
    manager = _manager(tmp_path, [_sample(f"tr_{i}", is_holdout=False) for i in range(5)])
    evaluator = _StubEvaluator([])
    result = await _probe(
        tmp_path, evaluator=evaluator, storage=_StubStorage("冠军"),
        store=SentinelStateStore(storage_dir=str(tmp_path)), manager=manager,
    )
    assert result["status"] == "skipped_no_sentinel_samples"
    assert evaluator.calls == []


# ============ 缓存读取降级（tick 消费口径） ============

def test_is_degraded_missing_returns_false(tmp_path):
    store = SentinelStateStore(storage_dir=str(tmp_path))
    assert store.is_degraded(GENRE, policy=POLICY) is False


def test_is_degraded_policy_mismatch_returns_false(tmp_path):
    store = SentinelStateStore(storage_dir=str(tmp_path))
    store.set_record(GENRE, {"degraded": True, "policy": "experiment-policy-v0"})
    assert store.is_degraded(GENRE, policy=POLICY) is False


def test_is_degraded_corrupt_file_returns_false(tmp_path):
    (tmp_path / "sentinel_state.json").write_text("{broken", encoding="utf-8")
    store = SentinelStateStore(storage_dir=str(tmp_path))
    assert store.is_degraded(GENRE, policy=POLICY) is False


def test_is_degraded_hit_returns_cached_flag(tmp_path):
    store = SentinelStateStore(storage_dir=str(tmp_path))
    store.set_record(GENRE, {"degraded": True, "policy": POLICY, "checked_at": _iso_ago(hours=1)})
    assert store.is_degraded(GENRE, policy=POLICY) is True
    # 落盘为合法 JSON（原子写）
    data = json.loads((tmp_path / "sentinel_state.json").read_text(encoding="utf-8"))
    assert data[GENRE]["degraded"] is True


# ============ 缓存新鲜度（TTL，2× 12h beat 周期） ============

def _iso_ago(*, hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def test_is_degraded_stale_returns_false(tmp_path):
    # checked_at 超过 SENTINEL_STATE_MAX_AGE_HOURS → 任务停摆旧退化标志不再生效
    store = SentinelStateStore(storage_dir=str(tmp_path))
    store.set_record(
        GENRE,
        {
            "degraded": True,
            "policy": POLICY,
            "checked_at": _iso_ago(hours=SENTINEL_STATE_MAX_AGE_HOURS + 1),
        },
    )
    assert store.is_degraded(GENRE, policy=POLICY) is False


def test_is_degraded_fresh_within_ttl(tmp_path):
    store = SentinelStateStore(storage_dir=str(tmp_path))
    store.set_record(
        GENRE,
        {
            "degraded": True,
            "policy": POLICY,
            "checked_at": _iso_ago(hours=SENTINEL_STATE_MAX_AGE_HOURS - 1),
        },
    )
    assert store.is_degraded(GENRE, policy=POLICY) is True


def test_is_degraded_missing_timestamp_returns_false(tmp_path):
    # 时间戳缺失/不可解析按超龄保守降级
    store = SentinelStateStore(storage_dir=str(tmp_path))
    store.set_record(GENRE, {"degraded": True, "policy": POLICY})
    assert store.is_degraded(GENRE, policy=POLICY) is False
    store.set_record(GENRE, {"degraded": True, "policy": POLICY, "checked_at": "不是时间"})
    assert store.is_degraded(GENRE, policy=POLICY) is False


def test_is_degraded_now_injectable(tmp_path):
    # now 可注入：以未来时点消费同一记录 → 超龄降级
    store = SentinelStateStore(storage_dir=str(tmp_path))
    store.set_record(GENRE, {"degraded": True, "policy": POLICY, "checked_at": _iso_ago(hours=0)})
    assert store.is_degraded(GENRE, policy=POLICY) is True
    future = datetime.now(timezone.utc) + timedelta(hours=SENTINEL_STATE_MAX_AGE_HOURS + 1)
    assert store.is_degraded(GENRE, policy=POLICY, now=future) is False


def test_probe_written_record_is_fresh_for_consumption(tmp_path):
    # 探针刚写入的记录（checked_at=当前）必须立即可被 tick 消费到退化标志
    store = SentinelStateStore(storage_dir=str(tmp_path))
    storage = _StubStorage("冠军")
    asyncio.run(_probe(tmp_path, evaluator=_StubEvaluator([20.0]), storage=storage, store=store))
    asyncio.run(_probe(tmp_path, evaluator=_StubEvaluator([30.0]), storage=storage, store=store))
    assert store.is_degraded(GENRE, policy=POLICY) is True


# ============ 信号观测口径（面板 signals 元数据） ============

def test_describe_signal_fresh_record(tmp_path):
    store = SentinelStateStore(storage_dir=str(tmp_path))
    checked_at = _iso_ago(hours=1)
    store.set_record(GENRE, {"degraded": True, "policy": POLICY, "checked_at": checked_at})
    info = store.describe_signal(GENRE, policy=POLICY)
    assert info == {"degraded": True, "checked_at": checked_at,
                    "stale": False, "defaulted": False}


def test_describe_signal_missing_record(tmp_path):
    store = SentinelStateStore(storage_dir=str(tmp_path))
    info = store.describe_signal(GENRE, policy=POLICY)
    assert info == {"degraded": False, "checked_at": None, "stale": False, "defaulted": True}


def test_describe_signal_stale_and_policy_mismatch(tmp_path):
    store = SentinelStateStore(storage_dir=str(tmp_path))
    # 超龄记录：stale=True 且消费值降级
    stale_at = _iso_ago(hours=SENTINEL_STATE_MAX_AGE_HOURS + 1)
    store.set_record(GENRE, {"degraded": True, "policy": POLICY, "checked_at": stale_at})
    info = store.describe_signal(GENRE, policy=POLICY)
    assert info == {"degraded": False, "checked_at": stale_at, "stale": True, "defaulted": True}
    # policy 不一致但新鲜：stale=False、defaulted=True
    fresh_at = _iso_ago(hours=1)
    store.set_record(GENRE, {"degraded": True, "policy": "experiment-policy-v0", "checked_at": fresh_at})
    info = store.describe_signal(GENRE, policy=POLICY)
    assert info == {"degraded": False, "checked_at": fresh_at, "stale": False, "defaulted": True}


# ============ degraded 严格 bool 校验（评审修复 3，不误唤醒） ============

def test_is_degraded_non_bool_value_returns_false(tmp_path):
    # 合法 JSON 但字段类型损坏（如 "false" 字符串）不得经真值转换误唤醒
    store = SentinelStateStore(storage_dir=str(tmp_path))
    for bad_value in ("false", "true", 1, "1", [True]):
        store.set_record(
            GENRE,
            {"degraded": bad_value, "policy": POLICY, "checked_at": _iso_ago(hours=1)},
        )
        assert store.is_degraded(GENRE, policy=POLICY) is False, repr(bad_value)


def test_describe_signal_non_bool_value_marks_defaulted(tmp_path):
    # 面板不得把损坏值显示为真实信号：degraded 消费降级 False 且 defaulted=True
    store = SentinelStateStore(storage_dir=str(tmp_path))
    checked_at = _iso_ago(hours=1)
    store.set_record(GENRE, {"degraded": "false", "policy": POLICY, "checked_at": checked_at})
    info = store.describe_signal(GENRE, policy=POLICY)
    assert info == {"degraded": False, "checked_at": checked_at, "stale": False, "defaulted": True}
