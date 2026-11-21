from test_papers import clients


def test_project_trash_preserves_resources_and_excludes_backup(clients):
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    project=a.post('/api/v1/projects',json={'name':'课题','status':'completed'},headers=h).json()['id']
    paper=a.post('/api/v1/papers',json={'title':'文献'},headers=h).json()['id']
    card=a.post('/api/v1/cards',json={'title':'卡片','type':'idea','content':'内容'},headers=h).json()['id']
    plan=a.post('/api/v1/plans',json={'name':'计划','start_date':'2026-11-20','target_count':1},headers=h).json()['id']
    draft=a.post('/api/v1/drafts',json={'title':'草稿','content':'内容','task_type':'review','paper_ids':[],'card_ids':[],'text':''},headers=h).json()['id']
    for kind,id in [('papers',paper),('cards',card),('plans',plan),('drafts',draft)]:
        assert a.post(f'/api/v1/projects/{project}/{kind}/{id}',headers=h).status_code==204
    assert a.delete(f'/api/v1/projects/{project}',headers=h).status_code==204
    assert a.get(f'/api/v1/projects/{project}').status_code==404
    assert a.put(f'/api/v1/projects/{project}',json={'name':'修改'},headers=h).status_code==404
    assert a.post(f'/api/v1/projects/{project}/cards/{card}',headers=h).status_code==404
    assert a.get('/api/v1/projects').json()==[]
    exported=a.get('/api/v1/personal-backup/export').json()
    assert exported['projects']==[] and exported['project_papers']==[] and exported['project_cards']==[]
    assert a.get(f'/api/v1/papers/{paper}').status_code==200 and a.get(f'/api/v1/cards/{card}').status_code==200
    assert b.get('/api/v1/trash/projects').json()['items']==[]
    assert b.post(f'/api/v1/trash/projects/{project}/restore',headers=h).status_code==404
    assert b.request('DELETE',f'/api/v1/trash/projects/{project}',json={'confirm':True},headers=h).status_code==404
    assert a.post(f'/api/v1/trash/projects/{project}/restore',headers=h).status_code==204
    restored=a.get(f'/api/v1/projects/{project}').json()
    assert restored['status']=='completed' and restored['counts']=={'papers':1,'cards':1,'plans':1,'drafts':1}


def test_project_purge_requires_confirmation_and_never_deletes_material(clients):
    a,_=clients;h={'X-Requested-With':'zhiyan'}
    project=a.post('/api/v1/projects',json={'name':'删除'},headers=h).json()['id']
    card=a.post('/api/v1/cards',json={'title':'原资料','type':'idea','content':'内容'},headers=h).json()['id']
    a.post(f'/api/v1/projects/{project}/cards/{card}',headers=h)
    a.delete(f'/api/v1/projects/{project}',headers=h)
    url=f'/api/v1/trash/projects/{project}'
    assert a.request('DELETE',url,json={'confirm':False},headers=h).status_code==422
    assert a.request('DELETE',url,json={'confirm':True},headers=h).status_code==204
    assert a.post(url+'/restore',headers=h).status_code==404
    assert a.get(f'/api/v1/cards/{card}').status_code==200
