"""AI 痕迹竞争系统的并发安全本地存储与任务互斥。"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional
from datetime import datetime


_LOCKS: Dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _thread_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    lock = _thread_lock(path)
    with lock:
        lock_path = path.with_suffix(path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a+b") as lock_file:
            if os.name == "nt":
                import msvcrt

                lock_file.seek(0)
                if lock_file.tell() == 0:
                    lock_file.write(b"0")
                    lock_file.flush()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                if os.name == "nt":
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


# 🔧 2026-10-17(P32) 备份清理的时间节流记录。
# 键为被清理的主文件路径（同一文件在进程内共享节流状态），
# 使「进程启动时清理一次」在多次 __init__ 调用下也只真正执行一次。
_LAST_PRUNE_TIME: Dict[Path, float] = {}


class AtomicJsonStore:
    """带进程锁、原子替换和上一版本备份的 JSON 存储。

    🔧 2026-10-17(P28) 备份保留策略：
    实测 `data/prompt_evolution/evolution_history.json` 已达 8.10 MB，
    其 `.bak` 同样8.10 MB（`_write_unlocked` 写入前整体 copy，故等大）。

    注意：`.bak` 保留的是**上一版**而非历史版本链，回退读取也只用这一份
    （见 `read`）—— 所以单份 `.bak` 已经足够，多份历史备份对崩溃恢复
    **毫无价值**，只会让目录无界增长。
    故引入轮转：把超出 `BACKUP_KEEP` 份的旧备份轮转为带序号的历史文件，
    并对历史备份设总量上限 `BACKUP_HISTORY_MAX_BYTES`。

    **崩溃恢复能力不受影响**：`BACKUP_KEEP >= 1` 保证永远至少有一份
    可回退的 `.bak`；超限的历史备份仅是回退链上的更老版本，
    删除不影响「主文件损坏→读上一版」这条路径。
    """

    #: 必须 >= 1 —— 归零等于取消崩溃恢复能力（守卫 test_json_store_backup_rotation）
    BACKUP_KEEP = 1
    #: 历史备份总量上限（字节）。超出后从最老的开始删。
    BACKUP_HISTORY_MAX_BYTES = 32 * 1024 * 1024

    # 🔧 2026-10-17(P32) 清理移出写路径。事故取证见下方 _prune_backups 文档串。
    #: 单次清理最多删除几个文件 —— 避免一次撞穿环境的批量删除保护阈值
    PRUNE_MAX_DELETE = 3
    #: 两次清理之间的最小间隔（秒）—— 跨进程/多次初始化都受此节流
    PRUNE_INTERVAL = 600.0

    def __init__(self, path: Path, root_type: type = dict):
        self.path = Path(path)
        self.backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        self.root_type = root_type
        # 🔧 2026-10-17(P32) 清理移到这里：进程启动时做一次，绝不在写路径上做。
        # 该调用自身带时间节流（PRUNE_INTERVAL）与删除上限（PRUNE_MAX_DELETE），
        # 因此多次 __init__ 也只低频、少量地删除，不会撞环境的批量删除保护。
        try:
            self._prune_backups()
        except Exception:  # noqa: BLE001 —— 清理绝不能影响初始化
            pass

    def _history_pattern(self) -> str:
        return f"{self.path.name}.bak.*"

    def _is_own_rotated_backup(self, path: Path) -> bool:
        """严格判定某个文件是否为本类**自己**创建的轮转备份。

        🔧 P32：白名单式校验。宁可漏删也不误删 ——
        清理逻辑一旦误伤用户数据，代价远高于多留几个备份文件。

        仅接受 `{name}.bak.<数字>.<数字>` 这一个形态，
        其余任何文件（哪怕 glob 命中 `.bak.*`）一律不碰。
        """
        prefix = f"{self.path.name}.bak."
        if not path.name.startswith(prefix):
            return False
        parts = path.name[len(prefix):].split(".")
        if len(parts) != 2:
            return False
        ts, pid = parts
        return ts.isdigit() and pid.isdigit()

    def _prune_backups(self) -> None:
        """轮转历史备份：超出份数或总量的从最老开始删。

        🔧 2026-10-17(P32) 本方法**禁止**在写路径上调用。

        ## 事故取证

        P28 把本方法挂到写路径（每次写入都调用），配合「每次写入都新建一个
        `.bak.<ts>.<pid>`」，一轮进化写几十次 ⇒ 几十个轮转文件 + 几十次删除。
        实测撞上环境的批量删除保护：

            [safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED]
              {"count":50,"threshold":50,"scope":"turn","targetCount":1}

        之后后端事件循环被完全阻塞：`/docs` 15 秒无响应、状态接口超时、
        进化队列被判定需要停止。⚠️ 注意 `targetCount:1` ——
        保护机制数的是**本轮累计删除次数**而非单次批量，
        所以「每次只删一个文件」照样撞线。

        ## 现在的约束

        1. 只在 `__init__` 时调用（进程启动一次），不挂写路径
        2. `PRUNE_INTERVAL` 时间节流 —— 跨进程也不高频
        3. `PRUNE_MAX_DELETE` 硬上限 —— 单次最多删几个
        4. 白名单式形态校验 —— 只删自己命名的文件，`.bak` 本体绝不碰

        注意与 `_locked` 的关系：现在只在 `__init__` 调用，不持锁
        （`__init__` 时文件尚不存在，无并发写风险）。
        清理失败不得阻断任何操作 —— 本方法吞掉所有异常。
        """
        now = time.time()
        last = _LAST_PRUNE_TIME.get(self.path)
        if last is not None and (now - last) < self.PRUNE_INTERVAL:
            return
        _LAST_PRUNE_TIME[self.path] = now

        try:
            history = sorted(
                (
                    p for p in self.path.parent.glob(self._history_pattern())
                    # 🔧 P32 白名单：只考虑自己创建的形态，glob 误伤一律排除
                    if self._is_own_rotated_backup(p)
                ),
                key=lambda p: p.stat().st_mtime,
            )
        except (FileNotFoundError, OSError):
            return

        total = 0
        try:
            for item in history:
                total += item.stat().st_size
        except OSError:
            return

        deleted = 0
        for index, item in enumerate(history):
            remaining_count = len(history) - index
            if (remaining_count <= self.BACKUP_KEEP
                    and total <= self.BACKUP_HISTORY_MAX_BYTES):
                break
            # 🔧 P32 删除数量硬上限 —— 避免一次撞穿保护阈值
            if deleted >= self.PRUNE_MAX_DELETE:
                logger.debug(
                    "备份清理达单次上限 %d 个，其余留待下次",
                    self.PRUNE_MAX_DELETE,
                )
                break
            try:
                total -= item.stat().st_size
                item.unlink()
                deleted += 1
            except OSError:
                pass

    def _read_path(self, path: Path) -> Any:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, self.root_type):
            raise ValueError(f"JSON root must be {self.root_type.__name__}")
        return data

    def read(self) -> Any:
        with _locked(self.path):
            return self._read_unlocked()

    def _read_unlocked(self) -> Any:
        if not self.path.exists():
            return self.root_type()
        try:
            return self._read_path(self.path)
        except (json.JSONDecodeError, OSError, ValueError):
            if self.backup_path.exists():
                return self._read_path(self.backup_path)
            raise

    def write(self, data: Any) -> None:
        with _locked(self.path):
            self._write_unlocked(data)

    def _write_unlocked(self, data: Any) -> None:
        if not isinstance(data, self.root_type):
            raise ValueError(f"JSON root must be {self.root_type.__name__}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                self._read_path(self.path)
                # 🔧 2026-10-17(P32) 写路径不再为每次写入新建轮转备份。
                #
                # 原P28 实现在此做两件危险的事：
                #   ① 把现有 .bak 改名成 `.bak.<ts>.<pid>`（每次写入一个新文件）
                #   ② 调用 _prune_backups()（每次写入都删文件）
                # 一轮进化写几十次 ⇒ 几十个备份 + 几十次删除，
                # 实测撞上环境批量删除保护（count:50），后端事件循环被完全阻塞：
                # `/docs` 15 秒无响应、状态接口超时、进化队列被判定停止。
                #
                # 改为**就地覆盖单份 .bak**：崩溃恢复能力完全不变
                # （「主文件损坏→回退读上一版」这条路不受影响），
                # 而写路径不再产生任何文件与删除操作。
                # 历史遗留备份的清理由 __init__ 低频完成（见 _prune_backups）。
                shutil.copy2(self.path, self.backup_path)
            except (json.JSONDecodeError, OSError, ValueError):
                pass
        temp_path = self.path.with_suffix(self.path.suffix + f".{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, self.path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def update(self, transform: Callable[[Any], Any]) -> Any:
        with _locked(self.path):
            updated = transform(self._read_unlocked())
            self._write_unlocked(updated)
            return updated


class _EvaluationLease:
    def __init__(self, guard: "EvaluationRunGuard", key: str):
        self._guard = guard
        self._key = key
        self._released = False

    def release(self, completed_at: Optional[float] = None) -> None:
        if self._released:
            return
        self._guard._release(self._key, completed_at)
        self._released = True


class EvaluationRunGuard:
    """按题材限制并行评测，并为成功释放后的任务提供冷却期。"""

    def __init__(
        self,
        cooldown_seconds: float = 60.0,
        max_completed_runs: int = 20,
        budget_window_seconds: float = 86400.0,
    ):
        self.cooldown_seconds = cooldown_seconds
        self.max_completed_runs = max_completed_runs
        self.budget_window_seconds = budget_window_seconds
        self._lock = threading.Lock()
        self._running: set[str] = set()
        self._last_completed: Dict[str, float] = {}
        self._completed_runs: list[float] = []

    def try_acquire(self, key: str, now: Optional[float] = None) -> Optional[_EvaluationLease]:
        current = time.time() if now is None else now
        with self._lock:
            self._completed_runs = [
                timestamp for timestamp in self._completed_runs
                if current - timestamp < self.budget_window_seconds
            ]
            if len(self._completed_runs) >= self.max_completed_runs:
                return None
            if key in self._running:
                return None
            completed = self._last_completed.get(key)
            if completed is not None and current - completed < self.cooldown_seconds:
                return None
            self._running.add(key)
            return _EvaluationLease(self, key)

    def _release(self, key: str, completed_at: Optional[float]) -> None:
        with self._lock:
            self._running.discard(key)
            self._last_completed[key] = time.time() if completed_at is None else completed_at
            self._completed_runs.append(self._last_completed[key])


class _BackgroundTaskLease:
    def __init__(self, coordinator: "BackgroundOptimizationCoordinator", task_id: str):
        self._coordinator = coordinator
        self.task_id = task_id
        self._finished = False

    def finish(self, now: Optional[float] = None, status: str = "completed") -> None:
        if self._finished:
            return
        self._coordinator.finish_task(self.task_id, now=now, status=status)
        self._finished = True


class BackgroundOptimizationCoordinator:
    """单执行器后台优化任务与每日评测预算的持久化协调器。"""

    def __init__(self, path: Path, daily_budget: int = 20, cooldown_seconds: float = 60.0):
        self.store = AtomicJsonStore(Path(path))
        self.daily_budget = daily_budget
        self.cooldown_seconds = cooldown_seconds

    @staticmethod
    def _day_key(now: float) -> str:
        return datetime.fromtimestamp(now).strftime("%Y-%m-%d")

    @staticmethod
    def _windows_pid_is_alive(pid: int) -> bool:
        """通过只读进程句柄检查 Windows PID，绝不向目标进程发送信号。"""
        import ctypes

        process_query_limited_information = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            process_query_limited_information, False, pid
        )
        if handle:
            kernel32.CloseHandle(handle)
            return True
        # ERROR_ACCESS_DENIED 表示进程存在，但当前用户没有查询权限。
        return ctypes.get_last_error() == 5

    @classmethod
    def _pid_is_alive(cls, pid: Any) -> bool:
        try:
            process_id = int(pid)
            if process_id <= 0:
                return False
            if process_id == os.getpid():
                return True
            if os.name == "nt":
                return cls._windows_pid_is_alive(process_id)
            os.kill(process_id, 0)
            return True
        except (OSError, TypeError, ValueError):
            return False

    def _normalized(self, state: Dict[str, Any], now: float) -> Dict[str, Any]:
        day = self._day_key(now)
        if state.get("budget_date") != day:
            state["budget_date"] = day
            state["budget_used"] = 0
        state.setdefault("is_running", False)
        state.setdefault("budget_used", 0)
        state.setdefault("cooldown_until", 0.0)
        if state.get("is_running") and not self._pid_is_alive(state.get("owner_pid")):
            state.update({
                "is_running": False,
                "status": "interrupted",
                "completed_at": now,
                "cooldown_until": 0.0,
            })
        return state

    def try_start(
        self, task_type: str, genre: str, now: Optional[float] = None
    ) -> Optional[_BackgroundTaskLease]:
        current = time.time() if now is None else now
        task_id = f"{int(current * 1000)}-{os.getpid()}-{threading.get_ident()}"
        acquired = False

        def update(state: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal acquired
            state = self._normalized(state, current)
            if state["is_running"] or current < float(state.get("cooldown_until", 0)):
                return state
            state.update({
                "is_running": True,
                "task_id": task_id,
                "task_type": task_type,
                "genre": genre,
                "started_at": current,
                "owner_pid": os.getpid(),
                "status": "running",
                "expected_models": 0,
                "completed_models": 0,
                "success_models": 0,
                "failed_models": 0,
            })
            acquired = True
            return state

        self.store.update(update)
        return _BackgroundTaskLease(self, task_id) if acquired else None

    def consume_budget(self, units: int = 1, now: Optional[float] = None) -> bool:
        current = time.time() if now is None else now
        consumed = False

        def update(state: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal consumed
            state = self._normalized(state, current)
            used = int(state["budget_used"])
            if units < 0 or used + units > self.daily_budget:
                return state
            state["budget_used"] = used + units
            consumed = True
            return state

        self.store.update(update)
        return consumed

    def update_progress(
        self,
        expected_models: int,
        completed_models: int,
        success_models: int,
        failed_models: int,
    ) -> None:
        def update(state: Dict[str, Any]) -> Dict[str, Any]:
            if state.get("is_running"):
                state.update({
                    "expected_models": expected_models,
                    "completed_models": completed_models,
                    "success_models": success_models,
                    "failed_models": failed_models,
                })
            return state

        self.store.update(update)

    def finish_task(
        self,
        task_id: str,
        now: Optional[float] = None,
        status: str = "completed",
    ) -> None:
        current = time.time() if now is None else now

        def update(state: Dict[str, Any]) -> Dict[str, Any]:
            state = self._normalized(state, current)
            if state.get("task_id") != task_id:
                return state
            state.update({
                "is_running": False,
                "status": status,
                "completed_at": current,
                "cooldown_until": current + self.cooldown_seconds,
            })
            return state

        self.store.update(update)

    def get_status(self, now: Optional[float] = None) -> Dict[str, Any]:
        current = time.time() if now is None else now
        state = self.store.update(lambda data: self._normalized(data, current))
        return {
            **state,
            "daily_budget": self.daily_budget,
            "budget_remaining": max(0, self.daily_budget - int(state.get("budget_used", 0))),
        }


_BACKGROUND_COORDINATOR: Optional[BackgroundOptimizationCoordinator] = None


def get_background_optimization_coordinator() -> BackgroundOptimizationCoordinator:
    global _BACKGROUND_COORDINATOR
    if _BACKGROUND_COORDINATOR is None:
        # 与 EvolutionStorage / ModelConfigStorage 统一使用仓库根 data/prompt_evolution
        base_dir = Path(__file__).resolve().parents[3] / "data" / "prompt_evolution"
        base_dir.mkdir(parents=True, exist_ok=True)
        state_file = base_dir / "background_optimization_state.json"
        legacy_file = Path(__file__).resolve().parents[2] / "data" / "prompt_evolution" / "background_optimization_state.json"
        if not state_file.exists() and legacy_file.exists():
            import shutil
            shutil.copy2(legacy_file, state_file)
        _BACKGROUND_COORDINATOR = BackgroundOptimizationCoordinator(state_file)
    return _BACKGROUND_COORDINATOR
