from test_papers import clients
from fastapi.testclient import TestClient
from app.main import app


def test_error_envelope_keeps_detail_without_echoing_secrets(clients):
    a, _ = clients
    secret = "sensitive-input-for-validation"
    response = a.post(
        "/api/v1/users/me",
        json={"password": secret},
        headers={"X-Requested-With": "zhiyan"},
    )
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "http_405"
    response = a.patch(
        "/api/v1/users/me",
        json={"display_name": "x", "unexpected": secret},
        headers={"X-Requested-With": "zhiyan"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "http_422"
    assert len(response.json()["error"]["request_id"]) == 32
    assert secret not in response.text
    response = a.patch("/api/v1/users/me", json={"display_name": "x"})
    assert response.status_code == 403
    assert response.json()["detail"] == "请求校验失败"
    assert response.json()["error"]["code"] == "http_403"


def test_unexpected_errors_do_not_expose_internal_exception(monkeypatch):
    from app import main

    def fail():
        raise RuntimeError("internal-sensitive-information")

    monkeypatch.setattr(main, "check_database", fail)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/health/database")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "http_500"
    assert "internal-sensitive-information" not in response.text
