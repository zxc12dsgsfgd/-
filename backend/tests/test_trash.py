from test_papers import clients


def test_card_trash_hides_and_restores_owned_data(clients):
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    card=a.post('/api/v1/cards',json={'title':'要恢复','type':'idea','content':'内容'},headers=h).json()['id']
    other=a.post('/api/v1/cards',json={'title':'另一张','type':'idea','content':'内容'},headers=h).json()['id']
    tag=a.post('/api/v1/tags',json={'name':'标签'},headers=h).json()['id']
    a.post(f'/api/v1/cards/{card}/tags/{tag}',headers=h)
    a.post('/api/v1/card-relations',json={'source_card_id':card,'target_card_id':other,'relation_type':'related'},headers=h)
    project=a.post('/api/v1/projects',json={'name':'项目'},headers=h).json()['id']
    a.post(f'/api/v1/projects/{project}/cards/{card}',headers=h)
    share=a.post('/api/v1/shares',json={'card_ids':[card],'expires_days':7,'allow_comments':False},headers=h).json()
    assert a.post(f"/api/v1/shares/{share['id']}/revoke",headers=h).status_code==204
    assert a.delete(f'/api/v1/cards/{card}',headers=h).status_code==204
    assert a.get(f'/api/v1/cards/{card}').status_code==404
    assert a.get(f'/api/v1/cards/{card}/versions').status_code==404
    assert a.get(f'/api/v1/cards/{card}/tags').status_code==404
    assert a.get('/api/v1/dashboard').json()['cards_total']==1
    assert len(a.get('/api/v1/graph').json()['edges'])==0
    assert a.get(f'/api/v1/projects/{project}').json()['counts']['cards']==0
    assert a.post('/api/v1/exports',json={'format':'markdown','card_ids':[card]},headers=h).status_code==404
    assert a.post('/api/v1/ai/preview',json={'task_type':'review','paper_ids':[],'card_ids':[card],'text':''},headers=h).status_code==404
    assert a.post('/api/v1/shares',json={'card_ids':[card],'expires_days':7,'allow_comments':False},headers=h).status_code==404
    assert all(x['id']!=card for x in a.get('/api/v1/personal-backup/export').json()['cards'])
    assert b.get('/api/v1/trash/cards').json()['items']==[]
    assert b.post(f'/api/v1/trash/cards/{card}/restore',headers=h).status_code==404
    assert a.post(f'/api/v1/trash/cards/{card}/restore',headers=h).status_code==204
    assert a.get(f'/api/v1/cards/{card}').status_code==200
    assert len(a.get(f'/api/v1/cards/{card}/versions').json())==1
    assert a.get(f'/api/v1/cards/{card}/tags').json()[0]['id']==tag
    assert len(a.get('/api/v1/graph').json()['edges'])==1
    assert a.get(f'/api/v1/projects/{project}').json()['counts']['cards']==1
    assert a.get('/api/v1/public/shares',headers={'X-Share-Token':share['token']}).status_code==404


def test_purge_requires_confirmation_and_owner(clients):
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    card=a.post('/api/v1/cards',json={'title':'永久删除','type':'idea','content':'内容'},headers=h).json()['id']
    assert a.delete(f'/api/v1/cards/{card}',headers=h).status_code==204
    url=f'/api/v1/trash/cards/{card}'
    assert a.request('DELETE',url,json={'confirm':False},headers=h).status_code==422
    assert b.request('DELETE',url,json={'confirm':True},headers=h).status_code==404
    assert a.request('DELETE',url,json={'confirm':True},headers=h).status_code==204
    assert a.post(url+'/restore',headers=h).status_code==404
