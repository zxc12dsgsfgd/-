from test_papers import clients


def test_sync_failure_preserves_rollback_and_owner_visibility(clients):
    a,b=clients; h={'X-Requested-With':'zhiyan'}
    pid=a.post('/api/v1/papers',json={'title':'测试'},headers=h).json()['id']
    for source,target in [('reading','archived'),('archived','reading')]:
        rule={'name':source,'trigger':'paper_status_changed','filter_value':source,'message':'切换','action_type':'set_status','action_value':target}
        assert a.post('/api/v1/workflows',json=rule,headers=h).status_code==201
    result=a.put(f'/api/v1/papers/{pid}',json={'title':'测试','status':'reading'},headers=h)
    assert result.status_code==409
    assert a.get(f'/api/v1/papers/{pid}').json()['status']=='unread'
    assert a.get('/api/v1/workflow-runs').json()==[]
    failure=a.get('/api/v1/workflow-sync-failures').json()
    assert len(failure)==1 and failure[0]['error_code']=='chain_limit' and failure[0]['object_id']==pid
    assert b.get('/api/v1/workflow-sync-failures').json()==[]


def test_creation_failure_has_no_reusable_object_id(clients,monkeypatch):
    import app.workflows as workflows
    a,_=clients; h={'X-Requested-With':'zhiyan'}
    assert a.post('/api/v1/workflows',json={'name':'失败规则','trigger':'card_created','message':'通知'},headers=h).status_code==201
    def fail(**kwargs): raise ValueError('secret text must not be saved')
    monkeypatch.setattr(workflows,'Notification',fail)
    result=a.post('/api/v1/cards',json={'title':'未保存','content':'内容','type':'concept'},headers=h)
    assert result.status_code==409
    assert a.get('/api/v1/cards').json()['items']==[]
    response=a.get('/api/v1/workflow-sync-failures')
    assert response.json()[0]['object_id'] is None and response.json()[0]['error_code']=='action_failed'
    assert 'secret text' not in response.text
