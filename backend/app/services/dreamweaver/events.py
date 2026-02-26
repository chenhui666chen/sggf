from __future__ import annotations

import asyncio
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from app.db.base import SessionLocal
from app.models.dreamweaver import DreamweaverRunEvent
from app.websocket.manager import ws_manager


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except Exception:  # noqa: BLE001
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except Exception:  # noqa: BLE001
        return default


_background_loop: asyncio.AbstractEventLoop | None = None
_background_thread: threading.Thread | None = None
_background_lock = threading.Lock()


def _ensure_background_loop() -> asyncio.AbstractEventLoop:
    global _background_loop, _background_thread
    with _background_lock:
        if _background_loop and _background_loop.is_running():
            return _background_loop
        loop = asyncio.new_event_loop()
        _background_loop = loop

        def _run() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        _background_thread = threading.Thread(target=_run, name="dreamweaver-ws-loop", daemon=True)
        _background_thread.start()
        return loop


@dataclass
class _StreamState:
    stage: str
    buffer: str = ""
    last_flush_ts: float = 0.0
    index: int = 0
    total_chars: int = 0


class DreamweaverEventEmitter:
    def __init__(
        self,
        *,
        project_id: int,
        user_id: int,
        run_id: str,
        ws_enabled: bool = True,
    ) -> None:
        self.project_id = int(project_id)
        self.user_id = int(user_id)
        self.run_id = str(run_id)
        self.ws_enabled = bool(ws_enabled)
        self.stream_chunk_size = max(40, _env_int("DREAMWEAVER_STREAM_CHUNK_SIZE", 160))
        self.stream_flush_interval = max(0.05, _env_float("DREAMWEAVER_STREAM_FLUSH_INTERVAL", 0.4))
        self._stream_states: Dict[str, _StreamState] = {}

    def _emit_ws(self, payload: Dict[str, Any]) -> None:
        if not self.ws_enabled:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        async def _send() -> None:
            await ws_manager.broadcast_to_project(self.project_id, "dreamweaver_event", payload)

        try:
            if loop and loop.is_running():
                loop.create_task(_send())
            else:
                bg_loop = _ensure_background_loop()
                asyncio.run_coroutine_threadsafe(_send(), bg_loop)
        except Exception:  # noqa: BLE001
            pass

    def emit_event(self, *, stage: str | None, event_type: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        session = SessionLocal()
        try:
            row = DreamweaverRunEvent(
                run_id=self.run_id,
                project_id=self.project_id,
                user_id=self.user_id,
                stage=str(stage) if stage else None,
                event_type=str(event_type),
                payload=payload or None,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            event_payload = {
                "event_id": int(row.id),
                "run_id": self.run_id,
                "project_id": self.project_id,
                "stage": str(stage) if stage else None,
                "event_type": str(event_type),
                "payload": payload or {},
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            self._emit_ws(event_payload)
            return event_payload
        except Exception:  # noqa: BLE001
            session.rollback()
            return None
        finally:
            session.close()

    def emit_stage_start(self, *, stage: str, state: str | None = None, progress: int | None = None) -> None:
        self.emit_event(
            stage=stage,
            event_type="stage_start",
            payload={"state": state, "progress": progress},
        )

    def emit_stage_progress(self, *, stage: str, state: str | None = None, progress: int | None = None) -> None:
        self.emit_event(
            stage=stage,
            event_type="stage_progress",
            payload={"state": state, "progress": progress},
        )

    def emit_stage_end(self, *, stage: str, state: str | None = None, progress: int | None = None) -> None:
        self.emit_event(
            stage=stage,
            event_type="stage_end",
            payload={"state": state, "progress": progress},
        )

    def stream_start(self, *, stage: str, stream_key: str, meta: Optional[Dict[str, Any]] = None) -> None:
        key = str(stream_key).strip() or stage
        self._stream_states[key] = _StreamState(stage=str(stage), last_flush_ts=time.monotonic())
        self.emit_event(
            stage=stage,
            event_type="text_stream_start",
            payload={"stream_key": key, "meta": meta or {}},
        )

    def _flush_stream(self, *, stream_key: str, force: bool = False) -> None:
        state = self._stream_states.get(stream_key)
        if not state:
            return
        if not state.buffer and not force:
            return
        chunk = state.buffer
        if not chunk:
            return
        state.buffer = ""
        state.last_flush_ts = time.monotonic()
        state.index += 1
        self.emit_event(
            stage=state.stage,
            event_type="text_stream_delta",
            payload={
                "stream_key": stream_key,
                "chunk": chunk,
                "chunk_index": state.index,
                "is_complete": False,
            },
        )

    def stream_chunk(self, *, stage: str, stream_key: str, chunk: str) -> None:
        key = str(stream_key).strip() or stage
        state = self._stream_states.get(key)
        if not state:
            state = _StreamState(stage=str(stage), last_flush_ts=time.monotonic())
            self._stream_states[key] = state
        state.total_chars += len(chunk)
        state.buffer += chunk
        now = time.monotonic()
        if len(state.buffer) >= self.stream_chunk_size or (now - state.last_flush_ts) >= self.stream_flush_interval:
            self._flush_stream(stream_key=key)

    def stream_end(self, *, stage: str, stream_key: str, meta: Optional[Dict[str, Any]] = None) -> None:
        key = str(stream_key).strip() or stage
        state = self._stream_states.get(key)
        if state:
            if state.buffer:
                self._flush_stream(stream_key=key, force=True)
            total_chars = state.total_chars
        else:
            total_chars = 0
        self.emit_event(
            stage=stage,
            event_type="text_stream_end",
            payload={"stream_key": key, "total_chars": total_chars, "meta": meta or {}},
        )
        if key in self._stream_states:
            self._stream_states.pop(key, None)

    def build_stream_callback(self, *, stage: str, stream_key: str) -> Callable[[str, int], None]:
        def _on_chunk(chunk: str, _idx: int) -> None:
            if not chunk:
                return
            self.stream_chunk(stage=stage, stream_key=stream_key, chunk=chunk)

        return _on_chunk
