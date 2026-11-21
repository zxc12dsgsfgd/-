import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import get_db
from app.main import app
from app.models import Base


@pytest.fixture
def clients():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def override():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = override
    with TestClient(app) as a, TestClient(app) as b:
        h = {"X-Requested-With": "zhiyan"}
        for c, email in [(a, 'a@example.org'), (b, 'b@example.org')]:
            data = {'email':email,'password':'password-long-123','display_name':'研究者'}
            assert c.post('/api/v1/auth/register', json=data, headers=h).status_code == 201
            assert c.post('/api/v1/auth/login', json=data, headers=h).status_code == 200
        yield a,b
    app.dependency_overrides.clear(); engine.dispose()


def test_paper_owner_isolation_and_crud(clients):
    a,b=clients; h={'X-Requested-With':'zhiyan'}
    data={'title':'第一篇','authors':['作者'],'status':'unread'}
    assert a.post('/api/v1/papers', json=data).status_code == 403
    response=a.post('/api/v1/papers', json=data, headers=h)
    assert response.status_code == 201
    paper_id=response.json()['id']
    assert b.get('/api/v1/papers').json()['items'] == []
    assert b.get(f'/api/v1/papers/{paper_id}').status_code == 404
    assert b.put(f'/api/v1/papers/{paper_id}', json=data, headers=h).status_code == 404
    assert b.delete(f'/api/v1/papers/{paper_id}', headers=h).status_code == 404
    assert a.put(f'/api/v1/papers/{paper_id}', json={**data,'title':'更新后','status':'read'}, headers=h).status_code == 200
    assert len(a.get('/api/v1/papers?q=更新&status=read').json()['items']) == 1
    assert a.delete(f'/api/v1/papers/{paper_id}', headers=h).status_code == 204
    assert a.get(f'/api/v1/papers/{paper_id}').status_code == 404


def test_pagination_and_validation(clients):
    a,_=clients; h={'X-Requested-With':'zhiyan'}
    for title in ['一','二','三']:
        assert a.post('/api/v1/papers',json={'title':title},headers=h).status_code == 201
    first=a.get('/api/v1/papers?limit=2').json()
    second=a.get(f"/api/v1/papers?limit=2&before_id={first['next_cursor']}").json()
    assert len(first['items']) == 2 and len(second['items']) == 1
    assert not {p['id'] for p in first['items']} & {p['id'] for p in second['items']}
    assert a.post('/api/v1/papers',json={'title':'  '},headers=h).status_code == 422
    assert a.post('/api/v1/papers',json={'title':'标题','owner_id':999},headers=h).status_code == 422


def test_import_preview_duplicate_confirmation_and_isolation(clients, monkeypatch):
    a,b=clients; h={'X-Requested-With':'zhiyan'}
    original={'title':'Original', 'doi':'https://doi.org/10.1234/ABC'}
    assert a.post('/api/v1/papers',json=original,headers=h).status_code == 201
    raw='@article{x, title={Imported}, author={Doe, Jane and Smith, John}, year={2022}, doi={10.1234/abc}}'
    preview=a.post('/api/v1/papers/import/preview',json={'kind':'bibtex','value':raw},headers=h)
    assert preview.status_code == 200
    assert preview.json()['paper']['authors']==['Doe, Jane','Smith, John']
    assert len(preview.json()['duplicates']) == 1
    assert b.post('/api/v1/papers/import/preview',json={'kind':'bibtex','value':raw},headers=h).json()['duplicates'] == []
    conflict=a.post('/api/v1/papers',json=preview.json()['paper'],headers=h)
    assert conflict.status_code == 409 and conflict.json()['detail']['code']=='possible_duplicate'
    assert len(a.get('/api/v1/papers').json()['items']) == 1
    assert a.post('/api/v1/papers?confirm_duplicate=true',json=preview.json()['paper'],headers=h).status_code == 201
    assert len(a.get('/api/v1/papers').json()['items']) == 2
    assert a.post('/api/v1/papers/import/preview',json={'kind':'bibtex','value':'bad'},headers=h).status_code == 422
    assert a.post('/api/v1/papers/import/preview',json={'kind':'doi','value':'http://127.0.0.1/'},headers=h).status_code == 422
    monkeypatch.setattr('app.papers.resolve_doi',lambda value:{'title':'Resolved','doi':'10.1/x','authors':[], 'status':'unread'})
    assert a.post('/api/v1/papers/import/preview',json={'kind':'doi','value':'10.1234/x'},headers=h).json()['paper']['title']=='Resolved'


def test_title_duplicate_only_without_doi(clients):
    a,_=clients; h={'X-Requested-With':'zhiyan'}
    assert a.post('/api/v1/papers',json={'title':'  Example   Title  '},headers=h).status_code==201
    assert a.post('/api/v1/papers',json={'title':'example title'},headers=h).status_code==409
    assert a.post('/api/v1/papers',json={'title':'example title','doi':'10.1234/other'},headers=h).status_code==201


def test_pdf_upload_access_and_cleanup(clients, tmp_path, monkeypatch):
    import app.paper_files as files_module
    a,b=clients; h={'X-Requested-With':'zhiyan'}
    monkeypatch.setattr(files_module, 'STORAGE', tmp_path)
    pid=a.post('/api/v1/papers',json={'title':'文献'},headers=h).json()['id']
    url=f'/api/v1/papers/{pid}/files'
    assert a.post(url,files={'file':('wrong.txt',b'%PDF-1.4\n%%EOF','text/plain')},headers=h).status_code==422
    assert a.post(url,files={'file':('wrong.pdf',b'not pdf','application/pdf')},headers=h).status_code==422
    pdf=b'%PDF-1.4\nexample\n%%EOF'
    result=a.post(url,files={'file':('../../private.pdf',pdf,'application/pdf')},headers=h)
    assert result.status_code==201
    data=result.json(); assert data['name']=='private.pdf'
    file_url=f"{url}/{data['id']}"
    assert b.get(file_url).status_code==404
    assert b.delete(file_url,headers=h).status_code==404
    response=a.get(file_url)
    assert response.status_code==200 and response.content==pdf
    assert response.headers['content-type'].startswith('application/pdf')
    assert a.delete(f'/api/v1/papers/{pid}',headers=h).status_code==204
    assert a.get(file_url).status_code==404
    assert a.post(f'/api/v1/trash/papers/{pid}/restore',headers=h).status_code==204
    assert a.get(file_url).content==pdf
    assert a.delete(file_url,headers=h).status_code==204
    assert list(tmp_path.iterdir())==[]
    assert a.delete(f'/api/v1/papers/{pid}',headers=h).status_code==204


def test_pdf_size_limit_and_retry_cleanup(clients, tmp_path, monkeypatch):
    import app.paper_files as files_module
    a,_=clients; h={'X-Requested-With':'zhiyan'}
    monkeypatch.setattr(files_module,'STORAGE',tmp_path)
    monkeypatch.setattr(files_module.get_settings(),'pdf_max_bytes',10)
    pid=a.post('/api/v1/papers',json={'title':'文献'},headers=h).json()['id']
    url=f'/api/v1/papers/{pid}/files'
    assert a.post(url,files={'file':('x.pdf',b'%PDF-'+b'x'*10,'application/pdf')},headers=h).status_code==413
    assert list(tmp_path.iterdir())==[]
    result=a.post(url,files={'file':('x.pdf',b'%PDF-abc','application/pdf')},headers=h)
    file_url=f"{url}/{result.json()['id']}"
    original=files_module.Path.unlink
    def fail(self, *args, **kwargs): raise OSError('test')
    monkeypatch.setattr(files_module.Path,'unlink',fail)
    assert a.delete(file_url,headers=h).status_code==503
    assert a.get(file_url).status_code==404
    assert a.delete(f'/api/v1/papers/{pid}',headers=h).status_code==204
    assert a.post(f'/api/v1/trash/papers/{pid}/restore',headers=h).status_code==409
    monkeypatch.setattr(files_module.Path,'unlink',original)
    assert a.request('DELETE',f"/api/v1/trash/papers/{pid}/files/{result.json()['id']}",json={'confirm':True},headers=h).status_code==204
    assert a.post(f'/api/v1/trash/papers/{pid}/restore',headers=h).status_code==204
