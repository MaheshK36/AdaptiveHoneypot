from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_endpoint() -> None:
    response = client.get("/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "Adaptive Honeypot API"
    assert payload["version"] == "0.1.0"


def test_health_endpoint() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "adaptive-honeypot-backend"
    assert payload["database"] in {"up", "down"}
