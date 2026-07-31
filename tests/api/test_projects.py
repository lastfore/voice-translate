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
    assert set(body["stage_status"].keys()) == {"separate", "deharmonize", "slice", "convert", "merge"}
    assert body["stage_status"]["separate"] == "not_run"


def test_defaults_not_found_is_404(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/api/projects/nope/defaults")
    assert resp.status_code == 404


def test_defaults_prefers_slice_stage_mode(api_workspace) -> None:
    """slice_mode comes from SLICE stage params, not CONVERT active_slice_mode."""
    from pipeline.models import Project, StageName, StageRecord, StageStatus, utc_now_iso
    from pipeline.store import ProjectStore

    store = ProjectStore(api_workspace.root)
    now = utc_now_iso()
    project = Project(id="demo", display_name="demo", created_at=now, updated_at=now)
    project.stages[StageName.SLICE] = StageRecord(
        status=StageStatus.DONE,
        params={"mode": "vad", "active_slice_mode": "vad"},
    )
    project.stages[StageName.CONVERT] = StageRecord(
        status=StageStatus.DONE,
        params={"active_slice_mode": "lrc"},
    )
    store.save_project(project)

    client = TestClient(api_workspace.app)
    resp = client.get("/api/projects/demo/defaults")
    assert resp.status_code == 200
    assert resp.json()["slice_mode"] == "vad"


def test_defaults_artifact_urls_use_media_endpoint(api_workspace, sample_audio: Path) -> None:
    from pipeline.models import Project, StageName, StageRecord, StageStatus, utc_now_iso
    from pipeline.store import ProjectStore

    store = ProjectStore(api_workspace.root)
    now = utc_now_iso()
    project = Project(id="media", display_name="media", created_at=now, updated_at=now)
    sep_dir = api_workspace.root / "output" / "separated"
    sep_dir.mkdir(parents=True, exist_ok=True)
    vocals = sep_dir / "media_(vocals)_m.flac"
    vocals.write_bytes(b"v")
    inst = sep_dir / "media_(other)_m.flac"
    inst.write_bytes(b"i")
    merged = api_workspace.root / "output" / "merged" / "media" / "vad" / "mixed.flac"
    merged.parent.mkdir(parents=True, exist_ok=True)
    merged.write_bytes(b"m")

    project.stages[StageName.SEPARATE] = StageRecord(
        status=StageStatus.DONE,
        artifacts={"vocals": str(vocals.relative_to(api_workspace.root)).replace("\\", "/")},
    )
    project.stages[StageName.SLICE] = StageRecord(
        status=StageStatus.DONE,
        params={"mode": "vad", "active_slice_mode": "vad"},
    )
    project.stages[StageName.MERGE] = StageRecord(
        status=StageStatus.DONE,
        artifacts={
            "vad": {
                "mixed": str(merged.relative_to(api_workspace.root)).replace("\\", "/"),
            }
        },
    )
    store.save_project(project)

    client = TestClient(api_workspace.app)
    resp = client.get("/api/projects/media/defaults")
    assert resp.status_code == 200
    artifacts = resp.json()["artifacts"]
    assert artifacts["sep_vocals"] == "/api/media?path=output/separated/media_(vocals)_m.flac"
    assert artifacts["mixed"] == "/api/media?path=output/merged/media/vad/mixed.flac"


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
