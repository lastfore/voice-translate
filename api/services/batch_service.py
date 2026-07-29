"""In-memory batch queue with SSE subscriber notifications.

A single batch runner processes items serially. Status updates are pushed to
all active SSE subscribers immediately on enqueue/clear/start/finish.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from pipeline.models import ConvertMode, JobStatus, ProgressEvent, SliceMode, StageName, utc_now_iso
from pipeline.runner import StageRunner
from pipeline.store import ProjectStore


class BatchStatus(str):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BatchItem:
    id: str
    project_id: str
    stages: list[str]
    params: dict[str, Any]
    status: str = BatchStatus.PENDING
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "stages": self.stages,
            "params": self.params,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }


class BatchService:
    def __init__(self, store: ProjectStore, runner: StageRunner) -> None:
        self._store = store
        self._runner = runner
        self._items: list[BatchItem] = []
        self._lock = threading.Lock()
        self._subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]] = []
        self._running = False
        self._run_thread: threading.Thread | None = None

    def _notify(self, payload: dict[str, Any]) -> None:
        """Push a snapshot to all subscribers from any thread."""
        # Copy subscribers under lock, then notify outside the lock to avoid
        # blocking enqueue/clear while iterating.
        with self._lock:
            subs = list(self._subscribers)
        for loop, queue in subs:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, payload)
            except Exception:  # noqa: BLE001 - best-effort notification
                pass

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "items": [item.to_dict() for item in self._items],
            }

    def _notify_snapshot(self) -> None:
        self._notify(self.snapshot())

    def subscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        loop = asyncio.get_running_loop()
        with self._lock:
            self._subscribers.append((loop, queue))
        # Send an immediate snapshot so the subscriber starts with current state.
        # subscribe() is called from the subscriber's event loop, so a direct
        # put_nowait is safe and avoids cross-loop scheduling issues.
        try:
            queue.put_nowait(self.snapshot())
        except Exception:  # noqa: BLE001
            pass

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            try:
                self._subscribers.remove((asyncio.get_running_loop(), queue))
            except ValueError:
                pass

    def enqueue(self, project_id: str, stages: list[str], params: dict[str, Any]) -> BatchItem:
        item = BatchItem(
            id=f"batch-{uuid.uuid4().hex[:12]}",
            project_id=project_id,
            stages=stages,
            params=params,
            status=BatchStatus.PENDING,
            created_at=utc_now_iso(),
        )
        with self._lock:
            self._items.append(item)
        self._notify_snapshot()
        return item

    def clear(self, *, remove_done: bool = True, remove_failed: bool = True, remove_pending: bool = False) -> int:
        with self._lock:
            statuses = []
            if remove_done:
                statuses.append(BatchStatus.DONE)
            if remove_failed:
                statuses.append(BatchStatus.FAILED)
            if remove_pending:
                statuses.append(BatchStatus.PENDING)
            statuses = set(statuses)
            original = len(self._items)
            self._items = [item for item in self._items if item.status not in statuses]
            removed = original - len(self._items)
        if removed:
            self._notify_snapshot()
        return removed

    def _set_item_status(self, item: BatchItem, status: str, error: str | None = None) -> None:
        item.status = status
        item.finished_at = utc_now_iso() if status in (BatchStatus.DONE, BatchStatus.FAILED, BatchStatus.CANCELLED) else item.finished_at
        if error is not None:
            item.error = error

    def _run_item(self, item: BatchItem, progress_queue: asyncio.Queue[dict[str, Any]], loop: asyncio.AbstractEventLoop) -> None:
        item.started_at = utc_now_iso()
        item.status = BatchStatus.RUNNING
        self._notify_snapshot()

        def on_progress(event: ProgressEvent) -> None:
            loop.call_soon_threadsafe(progress_queue.put_nowait, {"type": "log", "item_id": item.id, "event": event.to_ui_dict()})

        stage_enums = [StageName(s) for s in item.stages if s in StageName._value2member_map_]
        convert_mode = item.params.get("convert_mode", "slice_batch")
        if isinstance(convert_mode, str):
            convert_mode = ConvertMode(convert_mode)
        slice_mode_raw = item.params.get("slice_mode")
        if slice_mode_raw:
            slice_mode = SliceMode(slice_mode_raw) if isinstance(slice_mode_raw, str) else slice_mode_raw
        else:
            slice_mode = SliceMode(self._store.resolve_pipeline_slice_mode(item.project_id))
        try:
            result = self._runner.run_pipeline(
                item.project_id,
                stages=stage_enums,
                convert_mode=convert_mode,
                slice_mode=slice_mode,
                on_progress=on_progress,
                **item.params,
            )
            if result.success:
                self._set_item_status(item, BatchStatus.DONE)
            else:
                self._set_item_status(item, BatchStatus.FAILED, result.error)
        except Exception as exc:  # noqa: BLE001 - item boundary
            self._set_item_status(item, BatchStatus.FAILED, str(exc))
        self._notify_snapshot()

    def _run_worker(self, progress_queue: asyncio.Queue[dict[str, Any]], loop: asyncio.AbstractEventLoop) -> None:
        while True:
            with self._lock:
                pending = [item for item in self._items if item.status == BatchStatus.PENDING]
                if not pending:
                    self._running = False
                    break
                item = pending[0]
            self._run_item(item, progress_queue, loop)

    def run(self) -> asyncio.Queue[dict[str, Any]]:
        """Start the batch runner if not already running; return a progress queue."""
        with self._lock:
            if self._running:
                raise RuntimeError("batch runner already active")
            self._running = True

        loop = asyncio.get_running_loop()
        progress_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        def _worker() -> None:
            try:
                self._run_worker(progress_queue, loop)
            finally:
                loop.call_soon_threadsafe(progress_queue.put_nowait, {"type": "done"})

        thread = threading.Thread(target=_worker, name="batch-runner", daemon=True)
        thread.start()
        self._run_thread = thread
        return progress_queue
