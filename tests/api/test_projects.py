"""TC-P0-03 (create), TC-P0-04 (defaults), plus list/get/delete coverage."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_create_project_multipart(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    with sample_audio.open("rb") as fh:
        resp = client.post(
            "/api/projects",
            data={"project_id": "demo", "display_name": "Demo Song"},
            files={"audio": ("sample.flac", fh, "audio/flac")},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"] == "demo"
    assert body["display_name"] == "Demo Song"

    listed = client.get("/api/projects").json()
    assert any(p["id"] == "demo" for p in listed)


def test_create_project_with_lrc(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    lrc_path = api_workspace.root / "sample.lrc"
    lrc_path.write_text("[00:00.00]hello\n", encoding="utf-8")
    with sample_audio.open("rb") as audio_fh, lrc_path.open("rb") as lrc_fh:
        resp = client.post(
            "/api/projects",
            data={"project_id": "withlrc"},
            files={
                "audio": ("sample.flac", audio_fh, "audio/flac"),
                "lrc": ("sample.lrc", lrc_fh, "text/plain"),
            },
        )
    assert resp.status_code == 201, resp.text
    detail = client.get("/api/projects/withlrc").json()
    assert detail["input_lrc"]


def test_create_project_blank_id_is_400(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    with sample_audio.open("rb") as fh:
        resp = client.post(
            "/api/projects",
            data={"project_id": "   "},
            files={"audio": ("sample.flac", fh, "audio/flac")},
        )
    assert resp.status_code == 400


def test_create_project_missing_id_field_is_422(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    with sample_audio.open("rb") as fh:
        resp = client.post(
            "/api/projects",
            files={"audio": ("sample.flac", fh, "audio/flac")},
        )
    assert resp.status_code == 422


def test_create_project_duplicate_is_409(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    with sample_audio.open("rb") as fh:
        resp = client.post(
            "/api/projects",
            data={"project_id": "dup"},
            files={"audio": ("sample.flac", fh, "audio/flac")},
        )
    assert resp.status_code == 201
    with sample_audio.open("rb") as fh:
        resp2 = client.post(
            "/api/projects",
            data={"project_id": "dup"},
            files={"audio": ("sample.flac", fh, "audio/flac")},
        )
    assert resp2.status_code == 409


def test_get_project_not_found_is_404(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/api/projects/does-not-exist")
    assert resp.status_code == 404


def test_defaults_returns_key_fields(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    with sample_audio.open("rb") as fh:
        client.post(
            "/api/projects",
            data={"project_id": "demo2"},
            files={"audio": ("sample.flac", fh, "audio/flac")},
        )
    resp = client.get("/api/projects/demo2/defaults")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("stage_status", "stage_params", "wizard_params", "artifacts", "slice_mode", "convert_mode"):
        assert key in body
    assert set(body["stage_status"].keys()) == {"separate", "slice", "convert", "merge"}
    assert body["stage_status"]["separate"] == "not_run"


def test_defaults_not_found_is_404(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/api/projects/nope/defaults")
    assert resp.status_code == 404


def test_delete_requires_confirmation(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    with sample_audio.open("rb") as fh:
        client.post(
            "/api/projects",
            data={"project_id": "todelete"},
            files={"audio": ("sample.flac", fh, "audio/flac")},
        )
    resp = client.request(
        "DELETE", "/api/projects/todelete", json={"scope": "metadata", "confirmed": False}
    )
    assert resp.status_code == 400

    resp2 = client.request(
        "DELETE", "/api/projects/todelete", json={"scope": "metadata", "confirmed": True}
    )
    assert resp2.status_code == 200
    assert client.get("/api/projects/todelete").status_code == 404


def test_delete_preview_lists_paths(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    with sample_audio.open("rb") as fh:
        client.post(
            "/api/projects",
            data={"project_id": "previewme"},
            files={"audio": ("sample.flac", fh, "audio/flac")},
        )
    resp = client.get("/api/projects/previewme/delete-preview", params={"scope": "all"})
    assert resp.status_code == 200
    rows = resp.json()
    assert any(row["kind"] == "input" for row in rows)
