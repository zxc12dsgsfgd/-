from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import get_db, now
from app.main import app
from app.models import Base, LoginSession, RateLimitBucket, User
from app.rate_limit import cleanup_expired_limits


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def override():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        yield c, engine
    app.dependency_overrides.clear()
    engine.dispose()


def test_register_login_logout_and_expiry(client):
    c, engine = client
    h = {"X-Requested-With": "zhiyan"}
    data = {"email": "person@example.org", "password": "long-password-123", "display_name": "研究者"}
    assert c.post('/api/v1/auth/register', json=data).status_code == 403
    assert c.post('/api/v1/auth/register', json=data, headers=h).status_code == 201
    assert c.post('/api/v1/auth/register', json=data, headers=h).status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(User)).password_hash.startswith('$argon2id$')
        assert data['password'] not in db.scalar(select(User)).password_hash
    assert c.post('/api/v1/auth/login', json={'email':data['email'], 'password':'wrong'}, headers=h).status_code == 401
    response = c.post('/api/v1/auth/login', json=data, headers=h)
    assert response.status_code == 200
    assert 'httponly' in response.headers['set-cookie'].lower()
    assert c.get('/api/v1/auth/me').json()['email'] == data['email']
    with Session(engine) as db:
        session = db.scalar(select(LoginSession))
        assert session.token_hash != c.cookies.get('zhiyan_session').encode()
        session.expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert c.get('/api/v1/auth/me').status_code == 401
    assert c.post('/api/v1/auth/login', json=data, headers=h).status_code == 200
    assert c.post('/api/v1/auth/logout', headers=h).status_code == 204
    assert c.get('/api/v1/auth/me').status_code == 401


def test_origin_and_login_rate_limit(client):
    c, engine = client
    data = {'email':'person@example.org','password':'wrong'}
    h = {'X-Requested-With':'zhiyan', 'Origin':'https://untrusted.example'}
    assert c.post('/api/v1/auth/login', json=data, headers=h).status_code == 403
    h.pop('Origin')
    for _ in range(10):
        assert c.post('/api/v1/auth/login', json=data, headers=h).status_code == 401
    limited = c.post('/api/v1/auth/login', json=data, headers=h)
    assert limited.status_code == 429 and limited.headers["retry-after"] == "60"
    with Session(engine) as db:
        db.execute(update(RateLimitBucket).values(window_start=now() - timedelta(seconds=61)))
        db.commit()
    assert c.post('/api/v1/auth/login', json=data, headers=h).status_code == 401


def test_https_deployment_sets_secure_cookie(client, monkeypatch):
    from app.config import get_settings
    c, _ = client
    monkeypatch.setattr(get_settings(), 'secure_cookies', True)
    headers = {'X-Requested-With': 'zhiyan'}
    data = {'email':'secure@example.org','password':'long-password-123','display_name':'测试'}
    assert c.post('/api/v1/auth/register', json=data, headers=headers).status_code == 201
    result = c.post('/api/v1/auth/login', json=data, headers=headers)
    assert result.status_code == 200 and 'secure' in result.headers['set-cookie'].lower()


def test_current_user_can_only_update_own_display_name(client):
    c, _ = client
    headers = {"X-Requested-With": "zhiyan"}
    path = "/api/v1/users/me"
    alice = {"email": "alice@example.org", "password": "fixture-password-a", "display_name": "甲"}
    bob = {"email": "bob@example.org", "password": "fixture-password-b", "display_name": "乙"}
    assert c.get(path).status_code == 401
    assert c.patch(path, json={"display_name": "未经登录"}, headers=headers).status_code == 401
    assert c.post("/api/v1/auth/register", json=alice, headers=headers).status_code == 201
    bob_response = c.post("/api/v1/auth/register", json=bob, headers=headers)
    assert bob_response.status_code == 201
    assert c.post("/api/v1/auth/login", json=alice, headers=headers).status_code == 200

    assert c.get(path).json()["display_name"] == "甲"
    assert c.patch(path, json={"display_name": "改名"}).status_code == 403
    for invalid in (
        {"display_name": "  "},
        {"display_name": "长" * 101},
        {"display_name": "越权尝试", "owner_id": bob_response.json()["id"]},
        {"display_name": "改邮箱", "email": bob["email"]},
    ):
        assert c.patch(path, json=invalid, headers=headers).status_code == 422
    assert c.get(path).json()["display_name"] == "甲"
    response = c.patch(path, json={"display_name": "  文献研究者  "}, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"email": alice["email"], "display_name": "文献研究者"}
    assert c.get("/api/v1/auth/me").json()["display_name"] == "文献研究者"

    assert c.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert c.post("/api/v1/auth/login", json=bob, headers=headers).status_code == 200
    assert c.get(path).json()["display_name"] == "乙"
    assert c.post("/api/v1/auth/logout", headers=headers).status_code == 204
    login = c.post("/api/v1/auth/login", json=alice, headers=headers)
    assert login.status_code == 200
    assert login.json()["display_name"] == "文献研究者"


def test_limit_cleanup_preserves_current_windows(client):
    _, engine = client
    with Session(engine) as db:
        db.add_all([
            RateLimitBucket(key="login:expired", window_start=now() - timedelta(days=2), count=8),
            RateLimitBucket(key="share:active", window_start=now(), count=3),
        ])
        db.commit()
    assert cleanup_expired_limits(engine) == 1
    with Session(engine) as db:
        assert db.get(RateLimitBucket, "login:expired") is None
        assert db.get(RateLimitBucket, "share:active").count == 3
