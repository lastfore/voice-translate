"""TC-Phase0-03 / TC-P1-03/04: schema endpoint caching + filter correctness."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.routers import params as params_router


def test_schema_endpoint_returns_expected_shape(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/api/params/schema", params={"stage": "convert"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["stage"] == "convert"
    assert isinstance(body["params"], list)
    keys = {p["key"] for p in body["params"]}
    assert "fp16" in keys
    assert "diffusion_steps" in keys


def test_schema_endpoint_unknown_stage_is_404(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/api/params/schema", params={"stage": "not-a-stage"})
    assert resp.status_code == 404


def test_schema_vad_only_filter(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/api/params/schema", params={"stage": "slice", "vad_only": "true"})
    keys = {p["key"] for p in resp.json()["params"]}
    assert keys == {"vad_threshold", "min_speech_ms", "min_silence_ms", "speech_pad_ms"}


def test_schema_slice_batch_only_filter(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/api/params/schema", params={"stage": "convert", "slice_batch_only": "true"})
    keys = {p["key"] for p in resp.json()["params"]}
    assert keys == {"skip_existing", "limit"}


def test_schema_keys_filter(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get(
        "/api/params/schema", params={"stage": "convert", "keys": "diffusion_steps,length_adjust"}
    )
    keys = {p["key"] for p in resp.json()["params"]}
    assert keys == {"diffusion_steps", "length_adjust"}


def test_schema_lrc_only_filter(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/api/params/schema", params={"stage": "slice", "lrc_only": "true"})
    keys = {p["key"] for p in resp.json()["params"]}
    assert keys == {
        "boundary_mode",
        "search_margin_ms",
        "onset_min_lead_silence_ms",
        "min_slice_ms",
        "onset_energy_threshold_db",
    }


def test_schema_repeated_requests_hit_lru_cache(api_workspace, monkeypatch) -> None:
    """Cache is keyed on (stage, vad_only, slice_batch_only, keys); repeated calls
    with the same filters must not re-invoke the underlying schema-building work."""
    call_count = 0
    original_params_for_stage = params_router.params_for_stage

    def counting_params_for_stage(stage: str, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_params_for_stage(stage, **kwargs)

    monkeypatch.setattr(params_router, "params_for_stage", counting_params_for_stage)
    params_router.clear_schema_cache()
    client = TestClient(api_workspace.app)

    first = client.get("/api/params/schema", params={"stage": "separate"}).json()
    second = client.get("/api/params/schema", params={"stage": "separate"}).json()
    third = client.get("/api/params/schema", params={"stage": "separate"}).json()

    assert first == second == third
    assert call_count == 1, "schema build should only run once per distinct filter combo (lru_cache hit)"

    info = params_router._build_schema_cached.cache_info()
    assert info.hits >= 2


def test_schema_different_filters_are_separate_cache_entries(api_workspace) -> None:
    params_router.clear_schema_cache()
    client = TestClient(api_workspace.app)

    plain = client.get("/api/params/schema", params={"stage": "convert"}).json()
    filtered = client.get("/api/params/schema", params={"stage": "convert", "slice_batch_only": "true"}).json()

    assert len(plain["params"]) != len(filtered["params"])
    info = params_router._build_schema_cached.cache_info()
    assert info.currsize >= 2
