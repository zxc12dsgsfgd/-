from test_papers import clients


def test_batch_tags_project_and_ownership_are_atomic(clients):
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    cards=[a.post('/api/v1/cards',json={'title':f'卡片{i}','type':'idea','content':'内容'},headers=h).json()['id'] for i in range(4)]
    foreign=b.post('/api/v1/cards',json={'title':'他人','type':'idea','content':'内容'},headers=h).json()['id']
    tag=a.post('/api/v1/tags',json={'name':'批量'},headers=h).json()['id']
    project=a.post('/api/v1/projects',json={'name':'项目'},headers=h).json()['id']
    body={'kind':'cards','ids':cards[:3],'action':'add_tag','tag_id':tag}
    result=a.post('/api/v1/batch',json=body,headers=h)
    assert result.status_code==200 and result.json()=={'success_count':3,'failed_count':0,'changed_count':3,'message':'操作完成；未变更项可能已处于目标状态'}
    assert a.get(f'/api/v1/cards/{cards[3]}/tags').json()==[]
    assert a.post('/api/v1/batch',json={**body,'ids':[cards[3],foreign]},headers=h).status_code==404
    assert a.get(f'/api/v1/cards/{cards[3]}/tags').json()==[]
    reject=a.post('/api/v1/batch',json={**body,'ids':[cards[3],foreign]},headers=h).json()['detail']
    assert reject['success_count']==0 and reject['failed_count']==2
    assert a.post('/api/v1/batch',json={'kind':'cards','ids':cards[:3],'action':'add_project','project_id':project},headers=h).json()['changed_count']==3
    assert a.get(f'/api/v1/projects/{project}').json()['counts']['cards']==3
    assert a.post('/api/v1/batch',json={**body,'action':'remove_tag'},headers=h).json()['changed_count']==3
    assert a.get(f'/api/v1/cards/{cards[0]}/tags').json()==[]
    assert a.post('/api/v1/batch',json={**body,'ids':cards[:1]*2},headers=h).status_code==422
    assert a.post('/api/v1/batch',json={**body,'ids':list(range(1,52))},headers=h).status_code==422


def test_batch_status_workflow_and_trash_preserve_sources(clients):
    a,_=clients;h={'X-Requested-With':'zhiyan'}
    papers=[a.post('/api/v1/papers',json={'title':f'文献{i}'},headers=h).json()['id'] for i in range(2)]
    card=a.post('/api/v1/cards',json={'title':'来源卡片','type':'idea','content':'内容','paper_id':papers[0]},headers=h).json()['id']
    a.post('/api/v1/workflows',json={'name':'已读','trigger':'paper_status_changed','filter_value':'read','message':'提醒'},headers=h)
    payload={'kind':'papers','ids':papers,'action':'set_status','status':'read'}
    assert a.post('/api/v1/batch',json=payload,headers=h).status_code==422
    assert a.post('/api/v1/batch',json={**payload,'confirmed':True},headers=h).json()['changed_count']==2
    assert len(a.get('/api/v1/notifications').json())==2
    assert a.post('/api/v1/batch',json={'kind':'papers','ids':papers,'action':'trash','confirmed':True},headers=h).status_code==200
    assert a.get(f'/api/v1/cards/{card}').json()['source_state']=='unavailable'
    assert a.post(f'/api/v1/trash/papers/{papers[0]}/restore',headers=h).status_code==204
    assert a.get(f'/api/v1/cards/{card}').json()['source_state']=='linked'


def test_batch_workflow_failure_rolls_back_all(clients,monkeypatch):
    import app.workflows as workflows
    a,_=clients;h={'X-Requested-With':'zhiyan'}
    papers=[a.post('/api/v1/papers',json={'title':f'回滚{i}'},headers=h).json()['id'] for i in range(2)]
    a.post('/api/v1/workflows',json={'name':'提醒','trigger':'paper_status_changed','filter_value':'read','message':'提醒'},headers=h)
    original=workflows.Notification
    def fail_second(**kwargs):
        fail_second.calls+=1
        if fail_second.calls==2:raise ValueError('synthetic failure')
        return original(**kwargs)
    fail_second.calls=0
    monkeypatch.setattr(workflows,'Notification',fail_second)
    response=a.post('/api/v1/batch',json={'kind':'papers','ids':papers,'action':'set_status','status':'read','confirmed':True},headers=h)
    assert response.status_code==409 and response.json()['detail']['success_count']==0
    assert all(a.get(f'/api/v1/papers/{id}').json()['status']=='unread' for id in papers)
    monkeypatch.setattr(workflows,'Notification',original)
    assert a.get('/api/v1/notifications').json()==[]
