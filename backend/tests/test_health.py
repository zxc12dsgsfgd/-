from fastapi.testclient import TestClient

from app.main import app


def test_health_is_independent_of_database():
    response = TestClient(app).get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_database_health_reports_connection_failure_without_leaking_details(monkeypatch):
    from sqlalchemy.exc import OperationalError
    import app.main as main

    def fail():
        raise OperationalError("statement", {}, Exception("secret"))

    monkeypatch.setattr(main, "check_database", fail)
    response = TestClient(app).get("/api/v1/health/database")
    assert response.json() == {"status": "unavailable"}
    assert "secret" not in response.text
