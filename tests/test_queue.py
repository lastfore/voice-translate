"""Tests for GpuJobQueue."""

from __future__ import annotations

import time

from pipeline.models import Job, JobStatus
from pipeline.queue import GpuJobQueue


def test_queue_fifo_order() -> None:
    q = GpuJobQueue()
    order: list[int] = []

    def make_job(n: int) -> Job:
        return Job(
            job_id=f"job-{n}",
            type="stage",
            stage=None,
            status=JobStatus.QUEUED,
            created_at="2026-01-01T00:00:00+08:00",
        )

    for n in (1, 2, 3):
        q.enqueue(make_job(n), lambda n=n: order.append(n) or n)

    for n in (1, 2, 3):
        result = q.wait(f"job-{n}", timeout=10.0)
        assert result.status == JobStatus.COMPLETED
        assert result.result == n

    assert order == [1, 2, 3]
    q.shutdown()


def test_queue_failure_propagates() -> None:
    q = GpuJobQueue()
    job = Job("fail-1", "stage", None, JobStatus.QUEUED, "2026-01-01T00:00:00+08:00")

    def _boom() -> None:
        raise RuntimeError("gpu oom")

    q.enqueue(job, _boom)
    result = q.wait("fail-1", timeout=10.0)
    assert result.status == JobStatus.FAILED
    assert "gpu oom" in (result.error or "")
    q.shutdown()


def test_current_job_while_running() -> None:
    q = GpuJobQueue()
    started = False
    job = Job("run-1", "stage", None, JobStatus.QUEUED, "2026-01-01T00:00:00+08:00")

    def _slow() -> str:
        nonlocal started
        started = True
        time.sleep(0.2)
        return "ok"

    q.enqueue(job, _slow)
    deadline = time.time() + 2.0
    saw_running = False
    while time.time() < deadline:
        if q.current_job() is not None:
            saw_running = True
            break
        time.sleep(0.02)
    q.wait("run-1", timeout=5.0)
    assert started
    assert saw_running
    q.shutdown()
