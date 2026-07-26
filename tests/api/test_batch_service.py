"""Direct tests for the batch service SSE subscription (Phase 3)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient



def _create_project(client: TestClient, sample_audio: Path, project_id: str) -> None:
    with sample_audio.open("rb") as fh:
        resp = client.post(
            "/api/projects",
            data={"project_id": project_id},
            files={"audio": ("sample.flac", fh, "audio/flac")},
        )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_subscribe_receives_initial_snapshot(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "svc-snap")

    service = api_workspace.batch_service
    item = service.enqueue("svc-snap", ["separate"], {})

    queue: asyncio.Queue[dict] = asyncio.Queue()
    service.subscribe(queue)

    payload = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert payload["running"] is False
    assert any(i["id"] == item.id for i in payload["items"])


@pytest.mark.asyncio
async def test_enqueue_notifies_existing_subscriber(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "svc-enq")

    service = api_workspace.batch_service
    queue: asyncio.Queue[dict] = asyncio.Queue()
    service.subscribe(queue)
    await asyncio.wait_for(queue.get(), timeout=1.0)  # drain initial snapshot

    service.enqueue("svc-enq", ["separate"], {})
    payload = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert any(i["project_id"] == "svc-enq" for i in payload["items"])


@pytest.mark.asyncio
async def test_enqueue_notifies_multiple_subscribers(api_workspace, sample_audio: Path) -> None:
    """TC-Phase3-07: multiple subscribers receive the same status update."""
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "svc-multi")

    service = api_workspace.batch_service
    queue1: asyncio.Queue[dict] = asyncio.Queue()
    queue2: asyncio.Queue[dict] = asyncio.Queue()
    service.subscribe(queue1)
    service.subscribe(queue2)
    await asyncio.wait_for(queue1.get(), timeout=1.0)
    await asyncio.wait_for(queue2.get(), timeout=1.0)

    item = service.enqueue("svc-multi", ["separate"], {})
    payload1 = await asyncio.wait_for(queue1.get(), timeout=1.0)
    payload2 = await asyncio.wait_for(queue2.get(), timeout=1.0)
    assert any(i["id"] == item.id for i in payload1["items"])
    assert any(i["id"] == item.id for i in payload2["items"])
