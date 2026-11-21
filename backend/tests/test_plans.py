from test_papers import clients


def test_plan_progress_dashboard_and_isolation(clients):
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    one=a.post('/api/v1/papers',json={'title':'第一篇'},headers=h).json()['id']
    two=a.post('/api/v1/papers',json={'title':'第二篇','status':'read'},headers=h).json()['id']
    other=b.post('/api/v1/papers',json={'title':'另一账号'},headers=h).json()['id']
    data={'name':'阅读计划','start_date':'2026-11-20','end_date':'2026-12-01','target_count':2,'paper_ids':[one,two]}
    assert a.post('/api/v1/plans',json={**data,'paper_ids':[other]},headers=h).status_code==404
    assert a.post('/api/v1/plans',json={**data,'paper_ids':[one,one]},headers=h).status_code==422
    result=a.post('/api/v1/plans',json=data,headers=h);assert result.status_code==201
    plan=result.json();pid=plan['id'];assert (plan['completed'],plan['total'])==(1,2)
    assert b.get(f'/api/v1/plans/{pid}').status_code==404
    assert b.put(f'/api/v1/plans/{pid}',json=data,headers=h).status_code==404
    assert b.delete(f'/api/v1/plans/{pid}',headers=h).status_code==404
    dash=a.get('/api/v1/dashboard').json();assert dash['papers_total']==2 and dash['papers_by_status']['read']==1
    assert a.delete(f'/api/v1/papers/{two}',headers=h).status_code==204
    changed=a.get(f'/api/v1/plans/{pid}').json();assert (changed['completed'],changed['total'])==(0,1)
    assert changed['hidden_papers_count']==1
    assert a.put(f'/api/v1/plans/{pid}',json={**data,'paper_ids':[]},headers=h).status_code==409
    assert a.request('DELETE',f'/api/v1/trash/papers/{two}',json={'confirm':True},headers=h).status_code==204
    assert a.put(f'/api/v1/plans/{pid}',json={**data,'paper_ids':[]},headers=h).json()['total']==0
    assert a.delete(f'/api/v1/plans/{pid}',headers=h).status_code==204
    assert a.get(f'/api/v1/papers/{one}').status_code==200


def test_plan_date_validation(clients):
    a,_=clients;h={'X-Requested-With':'zhiyan'}
    assert a.post('/api/v1/plans',json={'name':'计划','start_date':'2026-11-20','end_date':'2026-11-19','target_count':1},headers=h).status_code==422
