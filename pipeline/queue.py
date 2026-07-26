"""GPU job queue — serializes GPU-intensive pipeline work."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from queue import Empty, Queue

from pipeline.models import Job, JobStatus


@dataclass
class JobResult:
    job_id: str
    status: JobStatus
    result: object | None = None
    error: str | None = None


@dataclass
class _QueuedJob:
    job: Job
    fn: Callable[[], object]
    done: threading.Event = field(default_factory=threading.Event)
    result: JobResult | None = None
    cancel_requested: bool = False


class GpuJobQueue:
    """Single-worker FIFO queue for GPU-bound tasks."""

    def __init__(self) -> None:
        self._queue: Queue[_QueuedJob | None] = Queue()
        self._jobs: dict[str, _QueuedJob] = {}
        self._current: _QueuedJob | None = None
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._run_worker, name="gpu-job-queue", daemon=True)
        self._worker.start()

    def _run_worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            with self._lock:
                self._current = item
                item.job.status = JobStatus.RUNNING
            try:
                value = item.fn()
                with self._lock:
                    cancelled = item.cancel_requested
                if cancelled:
                    item.result = JobResult(item.job.job_id, JobStatus.CANCELLED, error="cancelled by user")
                    item.job.status = JobStatus.CANCELLED
                else:
                    item.result = JobResult(item.job.job_id, JobStatus.COMPLETED, result=value)
                    item.job.status = JobStatus.COMPLETED
            except Exception as exc:  # noqa: BLE001 - worker boundary
                with self._lock:
                    cancelled = item.cancel_requested
                if cancelled:
                    item.result = JobResult(item.job.job_id, JobStatus.CANCELLED, error="cancelled by user")
                    item.job.status = JobStatus.CANCELLED
                else:
                    item.result = JobResult(item.job.job_id, JobStatus.FAILED, error=str(exc))
                    item.job.status = JobStatus.FAILED
            finally:
                with self._lock:
                    self._current = None
                item.done.set()
                self._queue.task_done()

    def enqueue(self, job: Job, fn: Callable[[], object]) -> str:
        queued = _QueuedJob(job=job, fn=fn)
        with self._lock:
            self._jobs[job.job_id] = queued
        job.status = JobStatus.QUEUED
        self._queue.put(queued)
        return job.job_id

    def new_job_id(self, prefix: str = "job") -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}"

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            queued = self._jobs.get(job_id)
            if queued is None:
                return False
            if queued.job.status == JobStatus.QUEUED:
                queued.job.status = JobStatus.CANCELLED
                queued.result = JobResult(job_id, JobStatus.CANCELLED)
                queued.done.set()
                return True
        return False

    def cancel_current(self) -> bool:
        """Request cancellation of the currently RUNNING job (if any).

        Marks the job so the worker reports CANCELLED once its work function
        returns/raises, and best-effort terminates the subprocess registered
        by ``pipeline.venv_runner`` for the worker thread. Returns True if a
        job was running and cancellation was requested (regardless of whether
        a live subprocess was found to terminate — the work function may not
        have spawned one yet, or may already be wrapping up).
        """
        with self._lock:
            current = self._current
            worker_ident = self._worker.ident
            if current is None:
                return False
            current.cancel_requested = True

        if worker_ident is not None:
            from pipeline import venv_runner

            venv_runner.terminate_process_for_thread(worker_ident)
        return True

    def get_status(self, job_id: str) -> JobStatus:
        with self._lock:
            queued = self._jobs.get(job_id)
            if queued is None:
                return JobStatus.CANCELLED
            return queued.job.status

    def current_job(self) -> Job | None:
        with self._lock:
            if self._current is None:
                return None
            return self._current.job

    def wait(self, job_id: str, timeout: float | None = None) -> JobResult:
        with self._lock:
            queued = self._jobs.get(job_id)
        if queued is None:
            return JobResult(job_id, JobStatus.CANCELLED, error="unknown job")
        if not queued.done.wait(timeout):
            return JobResult(job_id, JobStatus.RUNNING, error="timeout")
        return queued.result or JobResult(job_id, JobStatus.FAILED, error="no result")

    def shutdown(self) -> None:
        self._queue.put(None)
        self._worker.join(timeout=5.0)
