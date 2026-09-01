"""Phase 3 scaffold smoke tests: app boots, unified envelope works."""

from fastapi.testclient import TestClient


def test_health_ok(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["message"] == "success"
    assert body["data"]["database"] == "up"


def test_404_unified_envelope(client: TestClient) -> None:
    r = client.get("/api/v1/nonexistent-route")
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == 1002  # NOT_FOUND
    assert "request_id" in body


def test_openapi_schema_served(client: TestClient) -> None:
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert schema["info"]["title"] == "Manufacturing ERP Lite"
    assert "/api/v1/health" in schema["paths"]
