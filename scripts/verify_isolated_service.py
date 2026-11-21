import os,secrets,subprocess,sys,time
from pathlib import Path
import httpx
from sqlalchemy.engine import make_url
from app.config import get_settings

root=Path.cwd(); name='zhiyan_test_service_'+secrets.token_hex(6)
base=make_url(get_settings().database_url); user=base.username.replace("'","''")
created=granted=False;backend=frontend=None
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0

def mysql(sql):
 r=subprocess.run(['docker','compose','exec','-T','mysql','sh','-c','MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root'],input=sql,text=True,capture_output=True)
 if r.returncode:raise RuntimeError('Temporary schema operation failed')

def wait(url,process):
 for _ in range(100):
  if process.poll() is not None:raise RuntimeError(f'service exited: {url}')
  try:
   r=httpx.get(url,timeout=1,trust_env=False)
   if r.status_code==200:return r
  except httpx.HTTPError:pass
  time.sleep(.2)
 raise RuntimeError(f'service unavailable: {url}')

def launch_backend(env):
 return subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--app-dir','backend','--host','127.0.0.1','--port','8000'],cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags)

try:
 mysql(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;');created=True
 mysql(f"GRANT ALL PRIVILEGES ON `{name}`.* TO '{user}'@'%';");granted=True
 env=os.environ.copy();env['DATABASE_URL']=base.set(database=name).render_as_string(hide_password=False)
 result=subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=root,env=env,capture_output=True)
 if result.returncode:raise RuntimeError('migration failed')
 backend=launch_backend(env)
 assert wait('http://127.0.0.1:8000/api/v1/health/database',backend).json()['status']=='connected'
 client=httpx.Client(base_url='http://127.0.0.1:8000',headers={'X-Requested-With':'zhiyan'},trust_env=False)
 credentials={'email':'service-fixture@example.org','password':'temporary-password-123','display_name':'测试'}
 assert client.post('/api/v1/auth/register',json=credentials).status_code==201
 assert client.post('/api/v1/auth/login',json=credentials).status_code==200
 paper=client.post('/api/v1/papers',json={'title':'隔离服务测试文献'});assert paper.status_code==201
 template=client.post('/api/v1/reading-templates',json={'name':'合成模板','fields':['研究问题','研究方法']});assert template.status_code==201
 structured=client.post(f"/api/v1/papers/{paper.json()['id']}/structured-notes",json={'template_name':'合成阅读','fields':[{'label':'研究问题','value':'合成问题'},{'label':'研究方法','value':'合成方法'}]});assert structured.status_code==201
 assert client.get('/api/v1/structured-notes',params={'q':'合成方法'}).json()['items'][0]['id']==structured.json()['id']
 converted=client.post(f"/api/v1/structured-notes/{structured.json()['id']}/cards",json={'field_index':1,'title':'合成方法'});assert converted.status_code==201 and converted.json()['source_excerpt'] is None and converted.json()['content_kind']=='interpretation'
 card=client.post('/api/v1/cards',json={'title':'隔离项目卡片','content':'测试内容','type':'idea'});assert card.status_code==201
 evidence_url=f"/api/v1/cards/{card.json()['id']}/evidence"
 linked=client.post(evidence_url,json={'source_type':'paper','source_id':paper.json()['id'],'location':'第 2 页','excerpt':'合成原文'})
 assert linked.status_code==201
 evidence_id=linked.json()['id']
 assert client.put(f'{evidence_url}/{evidence_id}',json={'location':'第 3 页','note':'合成备注'}).status_code==200
 assert client.delete(f'{evidence_url}/{evidence_id}').status_code==204
 assert [x['action'] for x in client.get(f'{evidence_url}/{evidence_id}/history').json()]==['created','updated','removed']
 active_evidence=client.post(evidence_url,json={'source_type':'paper','source_id':paper.json()['id'],'note':'恢复测试'});assert active_evidence.status_code==201
 projects=[client.post('/api/v1/projects',json={'name':f'隔离项目 {i}'}) for i in (1,2)]
 assert all(p.status_code==201 for p in projects)
 first,second=[p.json()['id'] for p in projects];card_id=card.json()['id']
 plan=client.post('/api/v1/plans',json={'name':'合成计划','start_date':'2026-11-20','target_count':1,'paper_ids':[paper.json()['id']]}).json()['id']
 draft=client.post('/api/v1/drafts',json={'task_type':'review','title':'合成草稿','content':'内容','paper_ids':[paper.json()['id']],'card_ids':[card_id],'text':''}).json()['id']
 assert client.post(f'/api/v1/projects/{second}/plans/{plan}').status_code==204
 assert client.post(f'/api/v1/projects/{second}/drafts/{draft}').status_code==204
 for project in (first,second):assert client.post(f'/api/v1/projects/{project}/cards/{card_id}').status_code==204
 assert client.delete(f'/api/v1/projects/{first}/cards/{card_id}').status_code==204
 assert client.get(f'/api/v1/projects/{first}').json()['counts']['cards']==0
 assert client.get(f'/api/v1/projects/{second}').json()['counts']['cards']==1
 backup=client.get('/api/v1/personal-backup/export');assert backup.status_code==200
 other=httpx.Client(base_url='http://127.0.0.1:8000',headers={'X-Requested-With':'zhiyan'},trust_env=False)
 other_data={'email':'restore-fixture@example.org','password':'temporary-password-456','display_name':'恢复测试'}
 assert other.post('/api/v1/auth/register',json=other_data).status_code==201
 assert other.post('/api/v1/auth/login',json=other_data).status_code==200
 preview=other.post('/api/v1/personal-backup/preview',files={'file':('fixture.json',backup.content,'application/json')});assert preview.status_code==200
 restore=other.post('/api/v1/personal-backup/restore',files={'file':('fixture.json',backup.content,'application/json')},data={'confirmed':'true','expected_sha256':preview.json()['sha256']});assert restore.status_code==200
 assert preview.json()['counts']['structured_notes']==1 and preview.json()['counts']['reading_templates']==1
 restored_paper=other.get('/api/v1/papers').json()['items'][0]['id']
 assert restored_paper!=paper.json()['id']
 assert other.get(f'/api/v1/papers/{restored_paper}/structured-notes').json()[0]['fields'][1]['value']=='合成方法'
 assert other.get('/api/v1/reading-templates').json()['custom'][0]['name']=='合成模板'
 restored_plan=other.get('/api/v1/plans').json()[0];restored_draft=other.get('/api/v1/drafts').json()[0]
 assert restored_plan['papers'][0]['id']==restored_paper
 assert all(s['status']=='available' for s in other.get(f"/api/v1/drafts/{restored_draft['id']}/source-status").json()['sources'])
 assert any(p['counts']['plans']==1 and p['counts']['drafts']==1 for p in other.get('/api/v1/projects').json())
 restored_card=other.get('/api/v1/cards').json()['items'][0]
 assert restored_card['title']=='隔离项目卡片' and restored_card['id']!=card_id
 restored_evidence=other.get(f"/api/v1/cards/{restored_card['id']}/evidence").json()
 assert [e['status'] for e in restored_evidence]==['removed','available']
 assert len(other.get(f"/api/v1/cards/{restored_card['id']}/evidence/{restored_evidence[0]['id']}/history").json())==3
 assert any(p['counts']['cards']==1 for p in other.get('/api/v1/projects').json())
 tag=client.post('/api/v1/tags',json={'name':'批量合成标签'}).json()['id']
 mixed={'kind':'cards','ids':[card_id,restored_card['id']],'action':'add_tag','tag_id':tag}
 denied=client.post('/api/v1/batch',json=mixed);assert denied.status_code==404 and denied.json()['detail']['success_count']==0
 assert client.get(f'/api/v1/cards/{card_id}/tags').json()==[]
 batch=client.post('/api/v1/batch',json={**mixed,'ids':[card_id,converted.json()['id']]});assert batch.status_code==200 and batch.json()['changed_count']==2
 assert client.get(f'/api/v1/cards/{card_id}/tags').json()[0]['id']==tag
 other.close()
 assert client.delete(f'/api/v1/cards/{card_id}').status_code==204
 assert client.get(f'/api/v1/projects/{second}').json()['counts']['cards']==0
 assert client.get('/api/v1/trash/cards').json()['items'][0]['id']==card_id
 assert client.post(f'/api/v1/trash/cards/{card_id}/restore').status_code==204
 assert client.get(f'/api/v1/projects/{second}').json()['counts']['cards']==1
 assert client.delete(f'/api/v1/projects/{second}').status_code==204
 assert client.get(f'/api/v1/projects/{second}').status_code==404
 assert client.post(f'/api/v1/trash/projects/{second}/restore').status_code==204
 assert client.get(f'/api/v1/projects/{second}').json()['counts']['cards']==1
 assert client.delete(f'/api/v1/projects/{second}').status_code==204
 assert client.request('DELETE',f'/api/v1/trash/projects/{second}',json={'confirm':True}).status_code==204
 assert client.get(f'/api/v1/cards/{card_id}').status_code==200
 assert client.delete(f'/api/v1/cards/{card_id}').status_code==204
 assert client.request('DELETE',f'/api/v1/trash/cards/{card_id}',json={'confirm':True}).status_code==204
 disposable=client.post('/api/v1/papers',json={'title':'回收测试文献'}).json()['id']
 upload=client.post(f'/api/v1/papers/{disposable}/files',files={'file':('fixture.pdf',b'%PDF-isolated-fixture','application/pdf')});assert upload.status_code==201
 file_id=upload.json()['id']
 assert client.delete(f'/api/v1/papers/{disposable}').status_code==204
 assert client.get(f'/api/v1/papers/{disposable}/files/{file_id}').status_code==404
 assert client.post(f'/api/v1/trash/papers/{disposable}/restore').status_code==204
 assert client.get(f'/api/v1/papers/{disposable}/files/{file_id}').content==b'%PDF-isolated-fixture'
 assert client.delete(f'/api/v1/papers/{disposable}').status_code==204
 assert client.request('DELETE',f'/api/v1/trash/papers/{disposable}',json={'confirm':True}).status_code==409
 assert client.request('DELETE',f'/api/v1/trash/papers/{disposable}/files/{file_id}',json={'confirm':True}).status_code==204
 assert client.request('DELETE',f'/api/v1/trash/papers/{disposable}',json={'confirm':True}).status_code==204
 backend.terminate();backend.wait(timeout=10);backend=launch_backend(env)
 assert wait('http://127.0.0.1:8000/api/v1/health/database',backend).json()['status']=='connected'
 assert client.get('/api/v1/papers').json()['items'][0]['title']=='隔离服务测试文献'
 frontend=subprocess.Popen(['node','node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5173','--strictPort'],cwd=root/'frontend',stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags)
 assert '知研云枢' in wait('http://127.0.0.1:5173/',frontend).text
 assert wait('http://127.0.0.1:5173/api/v1/health/database',frontend).json()['status']=='connected'
 print('PASS: isolated schema, personal export/restore, evidence history, project links and source deletion, backend restart persistence, frontend proxy verified',flush=True)
finally:
 for process in (frontend,backend):
  if process and process.poll() is None:
   if os.name=='nt':
    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
   else:process.terminate()
   try:process.wait(timeout=10)
   except subprocess.TimeoutExpired:process.kill();process.wait()
 if granted:mysql(f"REVOKE ALL PRIVILEGES ON `{name}`.* FROM '{user}'@'%';")
 if created:mysql(f'DROP DATABASE `{name}`;')
 if created:print('Temporary schema and services cleaned',flush=True)
