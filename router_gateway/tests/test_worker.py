# -*- coding: utf-8 -*-
"""DB 状态驱动轮询 worker 单测：无内存调度，每轮重新查库，异常不炸循环。"""
from router_gateway.worker import run_forever, run_once


class FakeRepo:
    def __init__(self, batches):
        # batches: 每轮 list_active_job_ids 返回的 id 列表
        self.batches = list(batches)
        self.list_calls = 0

    def list_active_job_ids(self, limit=20):
        self.list_calls += 1
        if self.batches:
            return list(self.batches.pop(0))
        return []


class ClaimingRepo(FakeRepo):
    def __init__(self, batches):
        super().__init__(batches)
        self.released = []

    def claim_active_job_ids(self, limit=20, worker_id="test", lease_seconds=30):
        return self.list_active_job_ids(limit)

    def release_job_claim(self, job_id, worker_id="test"):
        self.released.append((job_id, worker_id))


class FakeOrch:
    def __init__(self, fail_ids=()):
        self.polled = []
        self.fail_ids = set(fail_ids)

    def poll_job(self, job_id):
        self.polled.append(job_id)
        if job_id in self.fail_ids:
            raise RuntimeError(f"upstream boom {job_id}")


def test_run_once逐任务poll并返回处理数():
    repo = FakeRepo([["j1", "j2"], []])
    orch = FakeOrch()
    assert run_once(orch, repo) == 2
    assert orch.polled == ["j1", "j2"]


def test_单个任务poll异常不影响同批后续任务():
    repo = FakeRepo([["bad", "good"]])
    orch = FakeOrch(fail_ids={"bad"})
    assert run_once(orch, repo) == 2
    assert orch.polled == ["bad", "good"]


def test_run_once无论poll成功失败都会释放租约():
    repo = ClaimingRepo([["bad", "good"]])
    orch = FakeOrch(fail_ids={"bad"})

    assert run_once(orch, repo) == 2
    assert repo.released == [("bad", "test"), ("good", "test")]


def test_run_forever空列表走idle退避且每轮重新查库():
    sleeps = []
    repo = FakeRepo([[], [], []])
    # 查库 3 次后停止
    run_forever(FakeOrch(), repo, sleep=sleeps.append,
                should_continue=lambda: repo.list_calls < 3,
                idle_seconds=5, busy_seconds=1)
    assert sleeps == [5, 5, 5]
    assert repo.list_calls == 3


def test_run_forever有任务的轮次走短退避():
    sleeps = []
    repo = FakeRepo([["j1"], [], []])
    run_forever(FakeOrch(), repo, sleep=sleeps.append,
                should_continue=lambda: repo.list_calls < 3)
    assert sleeps == [1, 5, 5]
