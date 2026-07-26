"""Shared fixtures for tests/api/ — isolated workspace + FastAPI app per test."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from api import deps
from api.main import app
from api.routers import params as params_router
from api.services.batch_service import BatchService
from pipeline.queue import GpuJobQueue
from pipeline.runner import StageRunner
from pipeline.store import ProjectStore


@dataclass
class ApiWorkspace:
    app: object
    store: ProjectStore
    queue: GpuJobQueue
    runner: StageRunner
    batch_service: BatchService
    root: Path


@pytest.fixture
def api_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ApiWorkspace]:
    monkeypatch.setenv("VOICE_TRANSLATE_ROOT", str(tmp_path))
    (tmp_path / "input").mkdir(parents=True, exist_ok=True)
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)

    store = ProjectStore(tmp_path)
    gpu_queue = GpuJobQueue()
    runner = StageRunner(store, gpu_queue)
    batch_service = BatchService(store, runner)

    app.dependency_overrides[deps.get_store] = lambda: store
    app.dependency_overrides[deps.get_queue] = lambda: gpu_queue
    app.dependency_overrides[deps.get_runner] = lambda: runner
    app.dependency_overrides[deps.get_batch_service] = lambda: batch_service
    params_router.clear_schema_cache()

    try:
        yield ApiWorkspace(app=app, store=store, queue=gpu_queue, runner=runner, batch_service=batch_service, root=tmp_path)
    finally:
        app.dependency_overrides.clear()
        gpu_queue.shutdown()
        params_router.clear_schema_cache()


@pytest.fixture
def sample_audio(tmp_path: Path) -> Path:
    audio = tmp_path / "sample.flac"
    audio.write_bytes(b"fake-flac-bytes")
    return audio
