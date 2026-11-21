"""Verify PDF import API with synthetic accounts in a disposable MySQL schema."""
import json
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from app.config import get_settings

root=Path.cwd();schema='zhiyan_test_pdf_api_'+secrets.token_hex(6)
base=make_url(get_settings().database_url);user=base.username.replace("'","''")
created=granted=False;engine=None


def mysql(sql):
    result=subprocess.run(['docker','compose','exec','-T','mysql','sh','-c',
                           'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root -N'],
                          input=sql,text=True,capture_output=True)
    if result.returncode:raise RuntimeError('MySQL administrative operation failed')


try:
    mysql(f'CREATE DATABASE `{schema}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;');created=True
    mysql(f"GRANT ALL PRIVILEGES ON `{schema}`.* TO '{user}'@'%';");granted=True
    url=base.set(database=schema);env=os.environ.copy()
    env['DATABASE_URL']=url.render_as_string(hide_password=False);env['PYTHONPATH']=str(root/'backend')
    if subprocess.run([sys.executable,'-m','alembic','upgrade','head'],env=env,capture_output=True).returncode:
        raise RuntimeError('isolated migration failed')
    engine=create_engine(url)
    from app.auth import get_db
    from app.main import app
    import app.paper_files as files
    def override():
        with Session(engine) as db:yield db
    app.dependency_overrides[get_db]=override
    with tempfile.TemporaryDirectory(prefix='pdf-api-',dir=root) as temp:
        old=files.STORAGE;files.STORAGE=Path(temp)/'pdfs'
        try:
            with TestClient(app) as a, TestClient(app) as b:
                h={'X-Requested-With':'zhiyan'}
                for client,email in [(a,'source@example.org'),(b,'target@example.org')]:
                    data={'email':email,'password':'password-long-123','display_name':'fixture'}
                    assert client.post('/api/v1/auth/register',json=data,headers=h).status_code==201
                    assert client.post('/api/v1/auth/login',json=data,headers=h).status_code==200
                source=a.post('/api/v1/papers',json={'title':'source'},headers=h).json()['id']
                target=b.post('/api/v1/papers',json={'title':'target'},headers=h).json()['id']
                content=b'%PDF-synthetic-fixture'
                assert a.post(f'/api/v1/papers/{source}/files',files={'file':('x.pdf',content,'application/pdf')},headers=h).status_code==201
                raw=a.get('/api/v1/personal-backup/pdf-export').content
                preview=b.post('/api/v1/personal-backup/pdf-preview',files={'file':('x.zip',raw,'application/zip')},headers=h).json()
                mapping=json.dumps([{'source_paper_id':source,'target_paper_id':target}])
                form={'mapping':mapping,'expected_sha256':preview['sha256']}
                result=b.post('/api/v1/personal-backup/pdf-mapping-preview',files={'file':('x.zip',raw,'application/zip')},data=form,headers=h)
                assert result.status_code==200,result.text
                form.update(receipt=result.json()['mapping_receipt'],request_id=secrets.token_hex(16),confirmed='true')
                endpoint='/api/v1/personal-backup/pdf-import'
                for _ in range(2):
                    result=b.post(endpoint,files={'file':('x.zip',raw,'application/zip')},data=form,headers=h)
                    assert result.status_code==200,result.text
                uploaded=b.get(f'/api/v1/papers/{target}/files').json()
                assert len(uploaded)==1
                item=uploaded[0]['id'];resource=f'/api/v1/papers/{target}/files/{item}'
                assert b.get(resource).content==content and a.get(resource).status_code==404
                assert b.delete(resource,headers=h).status_code==204
                assert b.delete(f'/api/v1/papers/{target}',headers=h).status_code==204
                result=b.request('DELETE',f'/api/v1/trash/papers/{target}',json={'confirm':True},headers=h)
                assert result.status_code==204,result.text
                print('PASS: isolated MySQL PDF export, mapping, import, repeat request, owner isolation and paper purge')
        finally:
            files.STORAGE=old;app.dependency_overrides.clear()
finally:
    if engine:engine.dispose()
    if granted:mysql(f"REVOKE ALL PRIVILEGES ON `{schema}`.* FROM '{user}'@'%';")
    if created:mysql(f'DROP DATABASE `{schema}`;');print('Temporary schema, grant and files removed')
