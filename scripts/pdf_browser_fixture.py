"""Disposable HTTP services and MySQL schema for interactive browser acceptance."""
import os, secrets, subprocess, sys, tempfile, time
from pathlib import Path
import httpx
from sqlalchemy.engine import make_url
from app.config import get_settings

root=Path.cwd(); name='zhiyan_test_browser_'+secrets.token_hex(6)
base=make_url(get_settings().database_url); user=base.username.replace("'","''")
created=granted=False; backend=frontend=None
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0

def mysql(sql):
    result=subprocess.run(['docker','compose','exec','-T','mysql','sh','-c','MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root'],input=sql,text=True,capture_output=True)
    if result.returncode:raise RuntimeError('MySQL test schema operation failed')

def wait(url,process):
    for _ in range(120):
        if process.poll() is not None:raise RuntimeError('test server exited')
        try:
            result=httpx.get(url,timeout=1,trust_env=False)
            if result.status_code==200:return
        except httpx.HTTPError:pass
        time.sleep(.2)
    raise RuntimeError('test server unavailable')

try:
    mysql(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;');created=True
    mysql(f"GRANT ALL PRIVILEGES ON `{name}`.* TO '{user}'@'%';");granted=True
    env=os.environ.copy();env['DATABASE_URL']=base.set(database=name).render_as_string(hide_password=False);env['PYTHONPATH']=str(root/'backend')
    if subprocess.run([sys.executable,'-m','alembic','upgrade','head'],env=env,capture_output=True).returncode:raise RuntimeError('migration failed')
    with tempfile.TemporaryDirectory(prefix='browser-fixture-',dir=root) as tmp:
        env['PDF_TEST_ROOT']=str(Path(tmp)/'pdfs')
        program="import os; from pathlib import Path; import app.paper_files as f; f.STORAGE=Path(os.environ['PDF_TEST_ROOT']); import uvicorn; uvicorn.run('app.main:app',host='127.0.0.1',port=8000,log_level='error')"
        backend=subprocess.Popen([sys.executable,'-c',program],env=env,creationflags=flags,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        wait('http://127.0.0.1:8000/api/v1/health/database',backend)
        with httpx.Client(base_url='http://127.0.0.1:8000',headers={'X-Requested-With':'zhiyan'},trust_env=False) as client:
            for email in ('browser-source@example.org','browser-target@example.org'):
                assert client.post('/api/v1/auth/register',json={'email':email,'password':'temporary-password-123','display_name':'浏览器测试'}).status_code==201
            assert client.post('/api/v1/auth/login',json={'email':'browser-source@example.org','password':'temporary-password-123'}).status_code==200
            paper=client.post('/api/v1/papers',json={'title':'浏览器验收文献'}).json()['id']
            card=client.post('/api/v1/cards',json={'title':'浏览器验收卡片','type':'idea','content':'合成测试内容','paper_id':paper,'source_page':1,'source_excerpt':'合成科研文献'}).json()['id']
            tag=client.post('/api/v1/tags',json={'name':'浏览器验收标签'}).json()['id']
            assert client.post(f'/api/v1/cards/{card}/tags/{tag}').status_code==204
            for index in (1,2):
                project=client.post('/api/v1/projects',json={'name':f'浏览器验收项目{index}'}).json()['id']
                assert client.post(f'/api/v1/projects/{project}/cards/{card}').status_code==204
            pdf=root/'docs/evidence/test-results/pdf-layout-20261120/fixture.pdf'
            assert client.post(f'/api/v1/papers/{paper}/files',files={'file':('source.pdf',pdf.read_bytes(),'application/pdf')}).status_code==201
            jsonfile=Path(tmp)/'backup.json';jsonfile.write_bytes(client.get('/api/v1/personal-backup/export').content)
            zipfile=Path(tmp)/'backup.zip';zipfile.write_bytes(client.get('/api/v1/personal-backup/pdf-export').content)
        frontend=subprocess.Popen(['node','node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5173','--strictPort'],cwd=root/'frontend',env=env,creationflags=flags,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        wait('http://127.0.0.1:5173/',frontend)
        stop=Path(tmp)/'stop'
        print(f'READY source_id={paper} json={jsonfile} zip={zipfile} stop={stop}',flush=True)
        while not stop.exists():
            if backend.poll() is not None or frontend.poll() is not None:raise RuntimeError('test server exited')
            time.sleep(.2)
        for process in (frontend,backend):
            if process and process.poll() is None:process.terminate();process.wait(timeout=10)
        frontend=backend=None
finally:
    for process in (frontend,backend):
        if process and process.poll() is None:process.terminate();process.wait(timeout=10)
    if granted:mysql(f"REVOKE ALL PRIVILEGES ON `{name}`.* FROM '{user}'@'%';")
    if created:mysql(f'DROP DATABASE `{name}`;');print('Temporary schema, grant, services and fixture files removed',flush=True)
