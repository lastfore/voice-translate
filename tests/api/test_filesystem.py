"""Tests for GET /api/fs/browse (Phase 1 gap-fill, migration doc §5.3/§7)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_browse_root_lists_input_and_output(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/api/fs/browse")
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == ""
    assert body["parent"] is None
    names = {e["name"] for e in body["entries"]}
    assert "input" in names
    assert "output" in names
    input_entry = next(e for e in body["entries"] if e["name"] == "input")
    assert input_entry["is_dir"] is True
    assert input_entry["path"] == "input"


def test_browse_subdirectory(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    sub = api_workspace.root / "input" / "mysong"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "reference.flac").write_bytes(b"x")

    resp = client.get("/api/fs/browse", params={"path": "input/mysong"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == "input/mysong"
    assert body["parent"] == "input"
    assert any(e["name"] == "reference.flac" for e in body["entries"])


def test_browse_rejects_path_traversal(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/api/fs/browse", params={"path": "../../../etc"})
    assert resp.status_code == 400


def test_browse_rejects_file_path(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    f = api_workspace.root / "input" / "song.flac"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"x")
    resp = client.get("/api/fs/browse", params={"path": "input/song.flac"})
    assert resp.status_code == 400


def test_browse_rejects_missing_directory(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/api/fs/browse", params={"path": "input/does-not-exist"})
    assert resp.status_code == 400


def test_browse_extensions_filter(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    d = api_workspace.root / "input" / "mixed"
    d.mkdir(parents=True, exist_ok=True)
    (d / "a.flac").write_bytes(b"x")
    (d / "b.txt").write_text("nope", encoding="utf-8")
    (d / "sub").mkdir()

    resp = client.get("/api/fs/browse", params={"path": "input/mixed", "extensions": ".flac"})
    assert resp.status_code == 200
    names = {e["name"] for e in resp.json()["entries"]}
    assert "a.flac" in names
    assert "b.txt" not in names
    assert "sub" in names  # directories always listed regardless of extension filter


def test_browse_dirs_only_excludes_files(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    d = api_workspace.root / "input" / "mixed2"
    d.mkdir(parents=True, exist_ok=True)
    (d / "a.flac").write_bytes(b"x")
    (d / "sub").mkdir()

    resp = client.get("/api/fs/browse", params={"path": "input/mixed2", "dirs_only": True})
    assert resp.status_code == 200
    names = {e["name"] for e in resp.json()["entries"]}
    assert names == {"sub"}
