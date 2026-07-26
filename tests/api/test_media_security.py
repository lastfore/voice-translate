"""TC-Phase0-02 (resolve_safe_path coverage), TC-P0-05 (path traversal), TC-P0-06 (ext whitelist)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.services.media_service import ALLOWED_AUDIO_EXTS, UnsafePathError, resolve_safe_path


def test_resolve_safe_path_accepts_relative_path_under_root(api_workspace) -> None:
    audio = api_workspace.root / "input" / "song.flac"
    audio.write_bytes(b"x")
    resolved = resolve_safe_path("input/song.flac", allow_extensions=ALLOWED_AUDIO_EXTS, root=api_workspace.root)
    assert resolved == audio.resolve()


def test_resolve_safe_path_rejects_parent_traversal(api_workspace) -> None:
    outside = api_workspace.root.parent / "secret.flac"
    outside.write_bytes(b"top secret")
    try:
        with pytest.raises(UnsafePathError):
            resolve_safe_path("../secret.flac", allow_extensions=ALLOWED_AUDIO_EXTS, root=api_workspace.root)
    finally:
        outside.unlink(missing_ok=True)


def test_resolve_safe_path_rejects_absolute_path_outside_root(api_workspace, tmp_path_factory) -> None:
    other_root = tmp_path_factory.mktemp("outside")
    outside_file = other_root / "leak.flac"
    outside_file.write_bytes(b"leak")
    with pytest.raises(UnsafePathError):
        resolve_safe_path(str(outside_file), allow_extensions=ALLOWED_AUDIO_EXTS, root=api_workspace.root)


def test_resolve_safe_path_rejects_disallowed_extension(api_workspace) -> None:
    script = api_workspace.root / "input" / "run.exe"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_bytes(b"MZ")
    with pytest.raises(UnsafePathError):
        resolve_safe_path("input/run.exe", allow_extensions=ALLOWED_AUDIO_EXTS, root=api_workspace.root)


def test_resolve_safe_path_rejects_missing_file_when_must_exist(api_workspace) -> None:
    with pytest.raises(UnsafePathError):
        resolve_safe_path("input/missing.flac", allow_extensions=ALLOWED_AUDIO_EXTS, root=api_workspace.root)


def test_resolve_safe_path_rejects_empty_path(api_workspace) -> None:
    with pytest.raises(UnsafePathError):
        resolve_safe_path("", root=api_workspace.root)


def test_media_endpoint_serves_allowed_file(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    audio = api_workspace.root / "input" / "song.flac"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"fake-flac-data")

    resp = client.get("/api/media", params={"path": "input/song.flac"})
    assert resp.status_code == 200
    assert resp.content == b"fake-flac-data"


def test_media_endpoint_rejects_path_traversal(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/api/media", params={"path": "../../../../etc/passwd"})
    assert resp.status_code == 400


def test_media_endpoint_rejects_traversal_with_encoded_dots(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/api/media", params={"path": "input/../../outside.flac"})
    assert resp.status_code == 400


def test_media_endpoint_rejects_disallowed_extension(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    doc = api_workspace.root / "input" / "notes.txt"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("not audio", encoding="utf-8")

    resp = client.get("/api/media", params={"path": "input/notes.txt"})
    assert resp.status_code == 400


def test_media_endpoint_allows_all_whitelisted_audio_extensions(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    for ext in ALLOWED_AUDIO_EXTS:
        f = api_workspace.root / "input" / f"clip{ext}"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"data")
        resp = client.get("/api/media", params={"path": f"input/clip{ext}"})
        assert resp.status_code == 200, f"extension {ext} should be allowed"


def test_media_endpoint_missing_file_is_400(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/api/media", params={"path": "input/does-not-exist.flac"})
    assert resp.status_code == 400
