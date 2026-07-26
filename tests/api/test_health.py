"""TC-Phase0-01 / TC-P0-02: health check, CORS, basic route reachability."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_endpoint_ok(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_alias_ok(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_cors_allows_configured_frontend_origin(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_rejects_unlisted_origin(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/api/health", headers={"Origin": "http://evil.example.com"})
    # Request still succeeds (CORS is enforced by the browser, not the server),
    # but no ACAO header should be echoed back for an origin that isn't allow-listed.
    assert resp.status_code == 200
    assert "http://evil.example.com" != resp.headers.get("access-control-allow-origin")


def test_basic_routes_reachable(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    assert client.get("/api/projects").status_code == 200
    assert client.get("/api/params/schema", params={"stage": "separate"}).status_code == 200
