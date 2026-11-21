from test_papers import clients


def test_paper_trash_restore_and_confirmed_file_purge(clients,tmp_path,monkeypatch):
    import app.paper_files as files
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    monkeypatch.setattr(files,'STORAGE',tmp_path)
    paper=a.post('/api/v1/papers',json={'title':'合成文献','status':'read'},headers=h).json()['id']
    file=a.post(f'/api/v1/papers/{paper}/files',files={'file':('fixture.pdf',b'%PDF-fixture','application/pdf')},headers=h).json()['id']
    note=a.post(f'/api/v1/papers/{paper}/notes',json={'content':'合成笔记'},headers=h).json()['id']
    card=a.post('/api/v1/cards',json={'title':'卡片','type':'idea','content':'内容','paper_id':paper,'verification_status':'user_checked'},headers=h).json()['id']
    plan=a.post('/api/v1/plans',json={'name':'计划','start_date':'2026-11-20','target_count':1,'paper_ids':[paper]},headers=h).json()['id']
    project=a.post('/api/v1/projects',json={'name':'课题'},headers=h).json()['id']
    a.post(f'/api/v1/projects/{project}/papers/{paper}',headers=h)
    url=f'/api/v1/trash/papers/{paper}'
    assert a.delete(f'/api/v1/papers/{paper}',headers=h).status_code==204
    assert a.get(f'/api/v1/papers/{paper}').status_code==404
    assert a.get(f'/api/v1/papers/{paper}/files/{file}').status_code==404
    assert a.put(f'/api/v1/notes/{note}',json={'content':'修改'},headers=h).status_code==404
    assert a.get(f'/api/v1/cards/{card}').json()['source_state']=='unavailable'
    assert a.get(f'/api/v1/plans/{plan}').json()['total']==0
    assert a.get(f'/api/v1/plans/{plan}').json()['hidden_papers_count']==1
    assert a.put(f'/api/v1/plans/{plan}',json={'name':'修改','start_date':'2026-11-20','target_count':1,'paper_ids':[]},headers=h).status_code==409
    assert a.get(f'/api/v1/projects/{project}').json()['counts']['papers']==0
    exported=a.get('/api/v1/personal-backup/export').json()
    assert exported['papers']==[] and exported['cards'][0]['paper_id'] is None
    assert b.get('/api/v1/trash/papers').json()['items']==[]
    assert b.post(url+'/restore',headers=h).status_code==404
    assert b.request('DELETE',url+'/files/'+str(file),json={'confirm':True},headers=h).status_code==404
    assert a.post(url+'/restore',headers=h).status_code==204
    assert a.get(f'/api/v1/papers/{paper}/files/{file}').content==b'%PDF-fixture'
    restored=a.get(f'/api/v1/cards/{card}').json()
    assert restored['source_state']=='linked' and restored['verification_status']=='pending'
    assert a.get(f'/api/v1/plans/{plan}').json()['total']==1
    assert a.get(f'/api/v1/projects/{project}').json()['counts']['papers']==1
    assert a.delete(f'/api/v1/papers/{paper}',headers=h).status_code==204
    assert a.request('DELETE',url,json={'confirm':True},headers=h).status_code==409
    assert a.request('DELETE',f'{url}/files/{file}',json={'confirm':False},headers=h).status_code==422
    assert a.request('DELETE',f'{url}/files/{file}',json={'confirm':True},headers=h).status_code==204
    assert a.request('DELETE',url,json={'confirm':True},headers=h).status_code==204
    assert a.post(url+'/restore',headers=h).status_code==404
    final=a.get(f'/api/v1/cards/{card}').json()
    assert final['paper_id'] is None and final['source_state']=='unavailable'
    assert list(tmp_path.iterdir())==[]


def test_failed_trash_file_cleanup_is_retryable(clients,tmp_path,monkeypatch):
    import app.paper_files as files
    a,_=clients;h={'X-Requested-With':'zhiyan'}
    monkeypatch.setattr(files,'STORAGE',tmp_path)
    paper=a.post('/api/v1/papers',json={'title':'测试'},headers=h).json()['id']
    file=a.post(f'/api/v1/papers/{paper}/files',files={'file':('x.pdf',b'%PDF-test','application/pdf')},headers=h).json()['id']
    a.delete(f'/api/v1/papers/{paper}',headers=h)
    url=f'/api/v1/trash/papers/{paper}';original=files.Path.unlink
    def fail(*args,**kwargs):raise OSError('synthetic')
    monkeypatch.setattr(files.Path,'unlink',fail)
    assert a.request('DELETE',f'{url}/files/{file}',json={'confirm':True},headers=h).status_code==503
    assert a.get(url+'/files').json()[0]['state']=='deleting'
    assert a.post(url+'/restore',headers=h).status_code==409
    monkeypatch.setattr(files.Path,'unlink',original)
    assert a.request('DELETE',f'{url}/files/{file}',json={'confirm':True},headers=h).status_code==204
    assert a.post(url+'/restore',headers=h).status_code==204
