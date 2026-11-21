"""Non-AI API smoke test against the configured MySQL; all DB writes roll back."""
import tempfile
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text, update
from sqlalchemy.orm import Session

from app.auth import get_db, limit_login, now
from app.config import get_settings
from app.main import app
from app.models import Share
from app.shares import limit_public
import app.paper_files as files


def check(response, status):
    if response.status_code != status:
        raise AssertionError(f'{response.request.method} {response.request.url.path}: expected {status}, got {response.status_code}: {response.text[:300]}')
    return response


def run():
    engine=create_engine(get_settings().database_url)
    if engine.dialect.name != 'mysql': raise RuntimeError('Smoke test requires project MySQL')
    h={'X-Requested-With':'zhiyan'}
    original_storage=files.STORAGE
    with tempfile.TemporaryDirectory(prefix='smoke-',dir=Path.cwd()) as temp, engine.connect() as connection:
        files.STORAGE=Path(temp)
        transaction=connection.begin()
        version=connection.execute(text('select version()')).scalar()
        migration=connection.execute(text('select version_num from alembic_version')).scalar()
        def override():
            with Session(bind=connection) as db: yield db
        app.dependency_overrides[get_db]=override
        # This smoke test rolls business writes back and does not test rate limiting.
        app.dependency_overrides[limit_login] = lambda: None
        app.dependency_overrides[limit_public] = lambda: None
        label=uuid4().hex[:12]
        try:
            with TestClient(app) as a, TestClient(app) as b, TestClient(app) as guest:
                for client, suffix in ((a,'a'),(b,'b')):
                    credentials={'email':f'smoke-{label}-{suffix}@example.org','password':'temporary-password-123','display_name':'测试用户'}
                    check(client.post('/api/v1/auth/register',json=credentials,headers=h),201)
                    check(client.post('/api/v1/auth/login',json=credentials,headers=h),200)
                check(guest.get('/api/v1/papers'),401)
                raw='@article{test,title={Smoke Reference},author={Doe},year={2024},doi={10.1234/smoke}}'
                preview=check(a.post('/api/v1/papers/import/preview',json={'kind':'bibtex','value':raw},headers=h),200).json()
                paper=check(a.post('/api/v1/papers',json=preview['paper'],headers=h),201).json();pid=paper['id']
                check(a.post('/api/v1/papers',json=preview['paper'],headers=h),409)
                check(b.get(f'/api/v1/papers/{pid}'),404)
                upload=check(a.post(f'/api/v1/papers/{pid}/files',files={'file':('fixture.pdf',b'%PDF-1.4\nfixture\n%%EOF','application/pdf')},headers=h),201).json()
                fileurl=f"/api/v1/papers/{pid}/files/{upload['id']}"
                check(a.get(fileurl),200);check(b.get(fileurl),404)
                payload={'title':'Card one','type':'concept','content':'Meaning','paper_id':pid,'source_page':1,'source_excerpt':'Excerpt'}
                c1=check(a.post('/api/v1/cards',json=payload,headers=h),201).json()
                c2=check(a.post('/api/v1/cards',json={'title':'Card two','type':'idea','content':'Other'},headers=h),201).json()
                tid=check(a.post('/api/v1/tags',json={'name':'方法'},headers=h),201).json()['id']
                check(a.post(f"/api/v1/cards/{c1['id']}/tags/{tid}",headers=h),204)
                assert len(check(a.get(f'/api/v1/cards?tag_id={tid}'),200).json()['items'])==1
                check(a.put(f"/api/v1/cards/{c1['id']}",json={**payload,'content':'Updated','version':c1['version']},headers=h),200)
                assert len(check(a.get(f"/api/v1/cards/{c1['id']}/versions"),200).json())==2
                check(b.get(f"/api/v1/cards/{c1['id']}"),404)
                check(a.post('/api/v1/card-relations',json={'source_card_id':c1['id'],'target_card_id':c2['id'],'relation_type':'supports'},headers=h),201)
                assert len(check(a.get('/api/v1/graph'),200).json()['edges'])==1
                check(a.post('/api/v1/workflows',json={'name':'read','trigger':'paper_status_changed','filter_value':'read','message':'read'},headers=h),201)
                check(a.put(f'/api/v1/papers/{pid}',json={'title':'Smoke Reference','status':'read'},headers=h),200)
                assert len(check(a.get('/api/v1/workflow-runs'),200).json())==1
                assert len(check(a.get('/api/v1/notifications'),200).json())==1
                plan=check(a.post('/api/v1/plans',json={'name':'plan','start_date':'2026-11-20','target_count':1,'paper_ids':[pid]},headers=h),201).json()
                assert plan['completed']==1 and check(a.get('/api/v1/dashboard'),200).json()['cards_total']==2
                for fmt in ('markdown','bibtex','latex'):
                    export=check(a.post('/api/v1/exports',json={'format':fmt,'card_ids':[c1['id']]},headers=h),200)
                    assert 'Smoke Reference' in export.text
                share=check(a.post('/api/v1/shares',json={'card_ids':[c1['id']],'expires_days':1,'allow_comments':True},headers=h),201).json()
                sh={'X-Share-Token':share['token']}
                item=check(guest.get('/api/v1/public/shares',headers=sh),200).json()['items'][0]
                check(guest.post('/api/v1/public/shares/comments',json={'share_item_id':item['id'],'author_name':'访客','content':'批注'},headers={**h,**sh}),201)
                assert len(check(a.get(f"/api/v1/shares/{share['id']}/comments"),200).json())==1
                check(b.get(f"/api/v1/shares/{share['id']}/comments"),404)
                check(a.post(f"/api/v1/shares/{share['id']}/revoke",headers=h),204)
                check(guest.get('/api/v1/public/shares',headers=sh),404)
                readonly=check(a.post('/api/v1/shares',json={'card_ids':[c2['id']],'expires_days':1,'allow_comments':False},headers=h),201).json()
                readonly_headers={'X-Share-Token':readonly['token']}
                readonly_item=check(guest.get('/api/v1/public/shares',headers=readonly_headers),200).json()['items'][0]
                check(guest.post('/api/v1/public/shares/comments',json={'share_item_id':readonly_item['id'],'author_name':'访客','content':'批注'},headers={**h,**readonly_headers}),403)
                connection.execute(update(Share).where(Share.id==readonly['id']).values(expires_at=now()-timedelta(seconds=1)))
                check(guest.get('/api/v1/public/shares',headers=readonly_headers),404)
                check(guest.post('/api/v1/public/shares/comments',json={'share_item_id':readonly_item['id'],'author_name':'访客','content':'批注'},headers={**h,**readonly_headers}),404)
                check(a.post('/api/v1/auth/logout',headers=h),204);check(a.get('/api/v1/papers'),401)
                print(f'PASS: real MySQL {version}, migration {migration}; non-AI API, isolation, export, sharing, disabled comments and expiry')
        finally:
            app.dependency_overrides.clear();files.STORAGE=original_storage
            transaction.rollback()
    engine.dispose()
    print('Temporary transaction rolled back; temporary PDF storage removed.')


if __name__=='__main__': run()
