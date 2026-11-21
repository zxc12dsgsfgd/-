from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from sqlalchemy import select

from app.auth import get_db
from app.config import get_settings
from app.main import app
from app.models import AIJob
from test_papers import clients


def test_ai_window_limit_recovery_and_user_isolation(clients, monkeypatch):
    a,b=clients; h={'X-Requested-With':'zhiyan'}
    settings=get_settings()
    monkeypatch.setattr(settings,'ai_encryption_key',Fernet.generate_key().decode())
    monkeypatch.setattr(settings,'ai_rate_limit_count',2)
    monkeypatch.setattr(settings,'ai_rate_limit_window_seconds',60)
    for client in (a,b):
        assert client.put('/api/v1/settings/ai',json={'base_url':'https://example.org','model_name':'test','api_key':'key'},headers=h).status_code==200
    selection={'task_type':'review','paper_ids':[],'card_ids':[],'text':'测试材料'}
    def submit(client):
        preview=client.post('/api/v1/ai/preview',json=selection,headers=h).json()
        return client.post('/api/v1/ai/tasks',json={**selection,'preview_token':preview['preview_token']},headers=h)
    assert submit(a).status_code==202
    assert submit(a).status_code==429  # active task is independently limited
    generator=app.dependency_overrides[get_db]();db=next(generator)
    try:
        job=db.scalar(select(AIJob));job.status='success';db.commit()
        assert submit(a).status_code==202
        for row in db.scalars(select(AIJob)).all(): row.status='success'
        db.commit()
        blocked=submit(a)
        assert blocked.status_code==429 and 1<=int(blocked.headers['Retry-After'])<=60
        assert submit(b).status_code==202
        for row in db.scalars(select(AIJob)).all(): row.created_at=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=61);row.status='success'
        db.commit()
        assert submit(a).status_code==202
    finally:generator.close()
