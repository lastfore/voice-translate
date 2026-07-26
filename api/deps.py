"""FastAPI dependency injection for the pipeline singletons.

Mirrors the module-level singleton pattern used by ``webui/state.py``
(``_store`` / ``_gpu_queue`` / ``_runner``), but exposed as ``Depends``-able
functions so tests can override them per-app via
``app.dependency_overrides[get_store] = lambda: my_test_store``.

``--workers 1`` is a hard requirement (see docs §4.4/§11): these singletons
back a single-GPU job queue, and multiple worker processes would each get
their own queue, breaking the serialization guarantee.
"""

from __future__ import annotations

from api.services.batch_service import BatchService
from pipeline.queue import GpuJobQueue
from pipeline.runner import StageRunner
from pipeline.store import ProjectStore

_store: ProjectStore | None = None
_queue: GpuJobQueue | None = None
_runner: StageRunner | None = None
_batch_service: BatchService | None = None


def get_store() -> ProjectStore:
    global _store
    if _store is None:
        _store = ProjectStore()
    return _store


def get_queue() -> GpuJobQueue:
    global _queue
    if _queue is None:
        _queue = GpuJobQueue()
    return _queue


def get_runner() -> StageRunner:
    global _runner
    if _runner is None:
        _runner = StageRunner(get_store(), get_queue())
    return _runner


def get_batch_service() -> BatchService:
    global _batch_service
    if _batch_service is None:
        _batch_service = BatchService(get_store(), get_runner())
    return _batch_service


def reset_singletons() -> None:
    """Test helper: drop cached singletons so the next ``get_*`` call rebuilds them."""
    global _store, _queue, _runner, _batch_service
    _store = None
    _queue = None
    _runner = None
    _batch_service = None
