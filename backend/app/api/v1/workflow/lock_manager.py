"""Workflow concurrency lock management."""
import asyncio

_workflow_execution_locks: dict[int, asyncio.Lock] = {}

def _get_workflow_execution_lock(project_id: int) -> asyncio.Lock:
    lock = _workflow_execution_locks.get(project_id)
    if lock is None:
        lock = asyncio.Lock()
        _workflow_execution_locks[project_id] = lock
    return lock
