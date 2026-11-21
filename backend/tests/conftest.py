import pytest


@pytest.fixture(autouse=True)
def isolate_http_test_settings(monkeypatch):
    """Existing TestClient fixtures use HTTP and must not inherit local deployment settings."""
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, 'secure_cookies', False)
    monkeypatch.setattr(settings, 'public_origin', '')
