from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_check_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_check_returns_ready(monkeypatch) -> None:
    from app import main

    monkeypatch.setattr(main, "check_database_connection", lambda: None)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_check_hides_database_error(monkeypatch) -> None:
    from app import main

    def raise_database_error() -> None:
        raise RuntimeError("postgresql://user:private-password@localhost/db")

    monkeypatch.setattr(main, "check_database_connection", raise_database_error)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "private-password" not in response.text
