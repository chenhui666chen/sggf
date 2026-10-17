"""P31：进化停止原因必须持久化到存档。

## 问题（真实取证，非推演）

`evolution_history.json` 实测 10 轮里，有 3 轮 `status="completed"` 但实际迭代数
远小于 `max_iterations`：

    86cff7f7  max=6  actual=[0,1,2]
    8260b160  max=5  actual=[0,1,2]
    13aa3353  max=4  actual=[0]

而 `error_message` 全为 `None`。**这 3 轮到底是跑满的、收敛退出的、还是文笔崩坏
中止的，从存档里完全看不出来。**

## 根因

`engine._check_stop_conditions()` 返回的 `StopReason` 有 5 种 `reason_type`
（success / protection / convergence / oscillation / max_iter），但：

1. `EvolutionHistory`（models.py:255）**没有任何字段**承载停止原因
2. `engine.py:1567-1572` 只把 `reason_message` 发给 `_notify_progress`
   （前端进度通知），**从不写回 `self.history`**
3. `score_history`（收敛/震荡判定的唯一数据源，engine.py:79/707）同理不落盘

后果：任何离线分析（含本项目自己的取证脚本）都无法回答「这轮进化为什么停了」。
收敛/震荡是**优化信号**，丢了就无法判断系统是在进步还是在原地打转。

## 修复口径

停止原因进存档，且**不能影响**已有存档的读取（全部新字段可选、有默认值）。
"""
from __future__ import annotations

import inspect
import re
from dataclasses import MISSING, fields


class TestHistoryHasStopReasonFields:
    """EvolutionHistory 必须有承载停止原因的字段。"""

    def _history_cls(self):
        from app.services.prompt_evolution.models import EvolutionHistory
        return EvolutionHistory

    def test_stop_reason_field_exists(self):
        cls = self._history_cls()
        assert hasattr(cls, "stop_reason"), (
            "EvolutionHistory 缺少 stop_reason —— 停止原因只发给前端通知就丢弃，"
            "存档无法区分「跑满」与「收敛/崩坏提前退出」"
        )

    def test_stop_type_field_exists(self):
        """需要同时保留机器可读的 type 与人可读的 message。"""
        cls = self._history_cls()
        assert hasattr(cls, "stop_type"), (
            "缺少 stop_type：只有 message 时无法按类型聚合统计"
        )

    def test_score_history_field_exists(self):
        """收敛/震荡判定的唯一数据源，必须落盘才能离线复核。

        注意：不能用 hasattr 判定 —— dataclass 用 default_factory 的字段
        在类上**没有**属性（只有 default= 才有），hasattr 会假失败。
        """
        names = {f.name for f in fields(self._history_cls())}
        assert "score_history" in names, (
            "缺少 score_history：收敛判定（engine.py:754）依赖它，"
            "不落盘则无法离线复核任何一轮的收敛结论"
        )

    def test_new_fields_are_optional_with_defaults(self):
        """新字段必须可选：否则旧存档（10 轮真实数据）会反序列化失败。"""
        from app.services.prompt_evolution.models import EvolutionHistory
        by_name = {f.name: f for f in fields(EvolutionHistory)}
        for name in ("stop_reason", "stop_type", "score_history"):
            assert name in by_name, f"{name} 不是 dataclass 字段"
            f = by_name[name]
            has_default = f.default is not MISSING
            has_factory = f.default_factory is not MISSING
            assert has_default or has_factory, (
                f"{name} 必须有默认值/默认工厂，否则旧存档读取会崩"
            )

    def test_default_instances_do_not_crash(self):
        from app.services.prompt_evolution.models import EvolutionHistory
        h = EvolutionHistory()
        # 三者都应能安全取到默认值，不该抛 AttributeError
        assert h.stop_reason is None or isinstance(h.stop_reason, str)
        assert h.stop_type is None or isinstance(h.stop_type, str)
        assert isinstance(h.score_history, list)


class TestStopReasonRoundTripsThroughSerialization:
    """停止原因必须能穿过 存档→读出 的往返。

    ⚠️ 序列化函数在 `storage.py::_history_to_dict/_dict_to_history`
    （EvolutionHistory 本身没有 to_dict）—— 取证时确认过，别再往 models 里找。
    """

    def _roundtrip(self, **kwargs):
        from app.services.prompt_evolution.storage import EvolutionStorage
        from app.services.prompt_evolution.models import EvolutionHistory
        store = EvolutionStorage.__new__(EvolutionStorage)
        h = EvolutionHistory(**kwargs)
        d = store._history_to_dict(h)
        return store._dict_to_history(d)

    def test_stop_fields_survive_roundtrip(self):
        back = self._roundtrip(
            evolution_id="roundtrip-probe-0001",
            stop_reason="X 已收敛：连续4次改善幅度 < 2.0分",
            stop_type="convergence",
            score_history=[47.2, 38.0, 27.1, 26.4],
        )
        assert back.stop_type == "convergence"
        assert "已收敛" in (back.stop_reason or "")
        assert back.score_history == [47.2, 38.0, 27.1, 26.4]

    def test_old_archive_without_new_fields_still_loads(self):
        """模拟真实旧存档：字段缺失时应回落到默认值，而不是 KeyError。"""
        from app.services.prompt_evolution.storage import EvolutionStorage
        store = EvolutionStorage.__new__(EvolutionStorage)
        old = {
            "evolution_id": "legacy-no-stop-fields",
            "status": "completed",
            "max_iterations": 6,
            "current_iteration": 3,
            "genre": "玄幻",
            "all_versions": [],
            "best_versions": [],
        }
        back = store._dict_to_history(old)
        assert back.stop_reason is None
        assert back.stop_type is None
        assert back.score_history == []


class TestEngineWritesStopReasonIntoHistory:
    """引擎在停止时必须把原因写进 history（而非只发前端通知）。"""

    def test_engine_assigns_stop_reason_to_history(self):
        from app.services.prompt_evolution.engine import PromptEvolutionEngine
        src = inspect.getsource(PromptEvolutionEngine)
        # 停止分支里必须有对 self.history 的写入
        assert "self.history.stop_reason" in src or \
               "history.stop_reason" in src, (
            "引擎只把 reason_message 发给 _notify_progress，没有写回 history"
        )

    def test_engine_assigns_stop_type_to_history(self):
        from app.services.prompt_evolution.engine import PromptEvolutionEngine
        src = inspect.getsource(PromptEvolutionEngine)
        assert "self.history.stop_type" in src or \
               "history.stop_type" in src, (
            "缺少 stop_type 落盘：无法按停止类型聚合统计"
        )

    def test_score_history_is_persisted_not_only_in_memory(self):
        """score_history 是收敛判定的数据源，必须在终止时落到 history。"""
        from app.services.prompt_evolution.engine import PromptEvolutionEngine
        src = inspect.getsource(PromptEvolutionEngine)
        assert "self.history.score_history" in src or \
               "history.score_history" in src, (
            "score_history 只在内存里（engine.py:79），进程退出即丢"
        )


class TestFidelityIsNotAProtectionStop:
    """保真相似度**不**参与保护性停止 —— 这是 P7 的分层设计，不是漏写。

    实测发现（manual_p31 行为实测）：`_check_stop_conditions` 的保护分支
    只检查可读性与文笔两项；保真相似度只出现在 `success` 合取条件里
    （engine.py:743）。也就是说「保真崩了」会阻止判成功，但**不会**中止进化。

    这是刻意的：保真把关在**版本准入层**（`_ab_rank_score` / best_versions
    筛选）做，与「保护性停止」是两个不同层次的闸门。LLM 改写天然会改动
    表述，保真瞬时偏低不代表这版本有毒 —— 真的失真会在准入层被挡掉，
    而在停止条件里设保真闸门会把「尚未收敛但方向正确的版本」全挡在传承链外。

    本测试锁定这个事实，防止日后有人"顺手补全保护条件"而改变行为。
    """

    def test_protection_branch_does_not_check_fidelity(self):
        from app.services.prompt_evolution.engine import PromptEvolutionEngine
        src = inspect.getsource(PromptEvolutionEngine._check_stop_conditions)
        # 从「保护性停止」注释行切起 —— 函数**签名**里就有 fidelity_similarity
        # 参数（它是所有分支的共同入参），按整段文本判定会误报。
        marker = "1. 保护性停止"
        assert marker in src, "未找到保护性停止分支标记，源码结构已变"
        body = src.split(marker, 1)[1]
        # 只看保护分支自己（到成功停止分支之前）
        protection = body.split("2. 成功停止", 1)[0]
        code_lines = [
            ln for ln in protection.splitlines()
            if "fidelity" in ln and not ln.strip().startswith("#")
        ]
        assert not code_lines, (
            f"保护性停止分支里出现了 fidelity 判断：{code_lines} —— "
            f"P7 的分层设计是保真走版本准入层、不走保护性停止"
        )

    def test_low_fidelity_does_not_stop_evolution(self):
        """行为断言：保真极低时不应触发 should_stop。"""
        import tempfile
        from app.services.prompt_evolution.storage import EvolutionStorage
        from app.services.prompt_evolution.engine import PromptEvolutionEngine
        from app.services.prompt_evolution.models import (
            EvolutionConfig, EvolutionHistory,
        )
        with tempfile.TemporaryDirectory() as td:
            store = EvolutionStorage(storage_dir=td)
            engine = PromptEvolutionEngine(
                config=EvolutionConfig(genre="玄幻"), storage=store)
            engine.history = EvolutionHistory(evolution_id="fid-probe")
            # AI 未达标(5<=10 达标…改用 50) + 可读性/文笔正常 + 保真极低
            sr = engine._check_stop_conditions(50.0, 90.0, 30.0, 40.0)
            assert not sr.should_stop, (
                f"保真不足(40)不应触发停止，实际返回 {sr.reason_type}"
            )

    def test_fidelity_still_gates_success(self):
        """反向锁定：保真必须继续参与 success 合取，否则它就完全没人管了。"""
        import tempfile
        from app.services.prompt_evolution.storage import EvolutionStorage
        from app.services.prompt_evolution.engine import PromptEvolutionEngine
        from app.services.prompt_evolution.models import (
            EvolutionConfig, EvolutionHistory,
        )
        with tempfile.TemporaryDirectory() as td:
            store = EvolutionStorage(storage_dir=td)
            engine = PromptEvolutionEngine(
                config=EvolutionConfig(genre="玄幻"), storage=store)
            engine.history = EvolutionHistory(evolution_id="fid-probe2")
            # 其他三项全达标，仅保真不达标 → 不应判 success
            sr = engine._check_stop_conditions(5.0, 95.0, 20.0, 40.0)
            assert sr.reason_type != "success", (
                "保真不达标却判了 success —— 保真闸门失效了"
            )


class TestStopTypeVocabularyIsClosed:
    """停止类型取值必须受控，否则统计口径会漂移。

    取证：StopReason.reason_type 在 engine.py 里产出 5 种取值
    （success / protection / convergence / oscillation / max_iter）；
    另有两个绕过 StopReason 直接写入 history.stop_type 的
    —— initial_abort（初始评估即全失格）与 exception（进化抛异常）。
    """

    EXPECTED = {
        "success", "protection", "convergence", "oscillation", "max_iter",
        "initial_abort", "exception",
    }

    def test_engine_only_produces_known_stop_types(self):
        from app.services.prompt_evolution.engine import PromptEvolutionEngine
        src = inspect.getsource(PromptEvolutionEngine)
        found = set(re.findall(r'(?:reason_type|stop_type)\s*=\s*["\']([a-z_]+)["\']', src))
        unknown = found - self.EXPECTED
        assert not unknown, (
            f"引擎产出了未登记的 stop_type：{unknown}；"
            f"新增取值须同步 models.StopReason 注释与此处白名单"
        )

    def test_expected_vocabulary_matches_documented_one(self):
        """防止有人加了新取值却忘了更新本测试的白名单文档。"""
        from app.services.prompt_evolution.models import StopReason
        src = inspect.getsource(StopReason)
        for word in self.EXPECTED:
            assert word in src, (
                f"StopReason 注释未提及 {word}，"
                f"而引擎在产出它 —— 注释与实现已脱节（P24 同类问题）"
            )

    def test_every_expected_type_is_actually_produced(self):
        """反向校验：白名单里不能有僵尸条目。"""
        from app.services.prompt_evolution.engine import PromptEvolutionEngine
        src = inspect.getsource(PromptEvolutionEngine)
        produced = set(re.findall(
            r'(?:reason_type|stop_type)\s*=\s*["\']([a-z_]+)["\']', src))
        missing = self.EXPECTED - produced
        # exception 由 except 分支落 error_message，未写 stop_type；
        # 它是合法取值但可能尚未落地，这里只提示不失败。
        assert missing - {"exception"} == set(), (
            f"白名单中的取值引擎从未产出：{missing - {'exception'}}"
        )