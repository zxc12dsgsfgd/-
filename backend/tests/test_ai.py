from cryptography.fernet import Fernet
from sqlalchemy import select
from test_papers import clients
from app.auth import get_db
from app.config import get_settings
from app.main import app
from app.models import AIConfig


def test_encrypted_config_and_no_secret_response(clients,monkeypatch):
    a,b=clients;h={'X-Requested-With':'zhiyan'};master=Fernet.generate_key().decode()
    monkeypatch.setattr(get_settings(),'ai_encryption_key',master)
    data={'base_url':'https://example.org/v1','model_name':'model','timeout_seconds':60,'api_key':'private-test-key'}
    assert a.put('/api/v1/settings/ai',json={**data,'base_url':'https://127.0.0.1'},headers=h).status_code==422
    r=a.put('/api/v1/settings/ai',json=data,headers=h);assert r.status_code==200
    assert 'private-test-key' not in r.text and 'private-test-key' not in a.get('/api/v1/settings/ai').text
    assert b.get('/api/v1/settings/ai').json()['configured'] is False
    gen=app.dependency_overrides[get_db]();db=next(gen)
    try:
        saved=db.scalar(select(AIConfig));assert b'private-test-key' not in saved.key_ciphertext
        assert Fernet(master.encode()).decrypt(saved.key_ciphertext)==b'private-test-key'
    finally:gen.close()
    assert a.delete('/api/v1/settings/ai',headers=h).status_code==204


def test_preview_and_draft_owner_snapshot(clients):
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    p=a.post('/api/v1/papers',json={'title':'来源','abstract':'摘要'},headers=h).json()['id']
    data={'task_type':'review','paper_ids':[p],'card_ids':[],'text':'附加内容'}
    assert b.post('/api/v1/ai/preview',json=data,headers=h).status_code==404
    preview=a.post('/api/v1/ai/preview',json=data,headers=h);assert preview.status_code==200 and preview.json()['sources'][0]['abstract']=='摘要'
    draft=a.post('/api/v1/drafts',json={**data,'title':'草稿','content':'人工撰写'},headers=h);assert draft.status_code==201
    did=draft.json()['id'];assert b.put(f'/api/v1/drafts/{did}',json={'title':'越权','content':'x'},headers=h).status_code==404
    assert a.delete(f'/api/v1/papers/{p}',headers=h).status_code==204
    assert a.get('/api/v1/drafts').json()[0]['sources'][0]['title']=='来源'
    assert a.put(f'/api/v1/drafts/{did}',json={'title':'修改','content':'正文'},headers=h).status_code==200
    assert a.delete(f'/api/v1/drafts/{did}',headers=h).status_code==204


def test_confirmed_job_and_background_result(clients,monkeypatch):
    from app.ai_worker import run_ai_once
    import app.ai_worker as worker
    a,b=clients;h={'X-Requested-With':'zhiyan'};monkeypatch.setattr(get_settings(),'ai_encryption_key',Fernet.generate_key().decode())
    cfg={'base_url':'https://example.org/v1','model_name':'model','api_key':'key'}
    assert a.put('/api/v1/settings/ai',json=cfg,headers=h).status_code==200
    p=a.post('/api/v1/papers',json={'title':'材料'},headers=h).json()['id']
    sel={'task_type':'review','paper_ids':[p],'card_ids':[],'text':''}
    pre=a.post('/api/v1/ai/preview',json=sel,headers=h).json()
    assert a.post('/api/v1/ai/tasks',json={**sel,'preview_token':'0'*64},headers=h).status_code==409
    assert a.put(f'/api/v1/papers/{p}',json={'title':'变更'},headers=h).status_code==200
    assert a.post('/api/v1/ai/tasks',json={**sel,'preview_token':pre['preview_token']},headers=h).status_code==409
    pre=a.post('/api/v1/ai/preview',json=sel,headers=h).json()
    job=a.post('/api/v1/ai/tasks',json={**sel,'preview_token':pre['preview_token']},headers=h);assert job.status_code==202
    assert a.post('/api/v1/ai/tasks',json={**sel,'preview_token':pre['preview_token']},headers=h).status_code==429
    assert b.get('/api/v1/ai/tasks').json()==[]
    gen=app.dependency_overrides[get_db]();db=next(gen);engine=db.get_bind();gen.close()
    monkeypatch.setattr(worker,'call_provider',lambda job,key:'模拟测试草稿')
    assert run_ai_once(engine)
    result=a.get('/api/v1/ai/tasks').json()[0];assert result['status']=='success'
    assert a.get('/api/v1/drafts').json()[0]['content']=='模拟测试草稿'


def test_connection_rejects_private_dns_and_redirect(monkeypatch):
    from types import SimpleNamespace
    import pytest
    import app.ai_worker as worker
    job=SimpleNamespace(base_url='https://example.org/v1',timeout_seconds=5,model_name='test',task_type='review',payload={})
    monkeypatch.setattr(worker.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError,match='unsafe_address'):worker.call_provider(job,'key')
    monkeypatch.setattr(worker.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('8.8.8.8',443))])
    class Response:
        status=302
    class Connection:
        def __init__(self,*args):pass
        def request(self,*args,**kwargs):pass
        def getresponse(self):return Response()
        def close(self):pass
    monkeypatch.setattr(worker,'PinnedHTTPS',Connection)
    with pytest.raises(ValueError,match='provider_error'):worker.call_provider(job,'key')


def test_timeout_is_not_automatically_retried(clients,monkeypatch):
    from app.ai_worker import run_ai_once
    import app.ai_worker as worker
    a,_=clients;h={'X-Requested-With':'zhiyan'};monkeypatch.setattr(get_settings(),'ai_encryption_key',Fernet.generate_key().decode())
    assert a.put('/api/v1/settings/ai',json={'base_url':'https://example.org','model_name':'model','api_key':'key'},headers=h).status_code==200
    sel={'task_type':'questions','paper_ids':[],'card_ids':[],'text':'测试'}
    pre=a.post('/api/v1/ai/preview',json=sel,headers=h).json()
    assert a.post('/api/v1/ai/tasks',json={**sel,'preview_token':pre['preview_token']},headers=h).status_code==202
    gen=app.dependency_overrides[get_db]();db=next(gen);engine=db.get_bind();gen.close()
    def timeout(job,key):raise TimeoutError()
    monkeypatch.setattr(worker,'call_provider',timeout)
    assert run_ai_once(engine) and not run_ai_once(engine)
    result=a.get('/api/v1/ai/tasks').json()[0]
    assert result['status']=='failed' and result['error_code']=='timeout_unknown' and a.get('/api/v1/drafts').json()==[]
