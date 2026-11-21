from test_papers import clients


def test_notes_cards_history_and_isolation(clients):
    a,b=clients; h={'X-Requested-With':'zhiyan'}
    pid=a.post('/api/v1/papers',json={'title':'来源文献'},headers=h).json()['id']
    note=a.post(f'/api/v1/papers/{pid}/notes',json={'content':'阅读笔记'},headers=h)
    assert note.status_code==201
    assert b.get(f'/api/v1/papers/{pid}/notes').status_code==404
    assert b.put(f"/api/v1/notes/{note.json()['id']}",json={'content':'越权'},headers=h).status_code==404
    data={'title':'方法','type':'method','content':'第一版','paper_id':pid,'source_page':3,'source_excerpt':'原文'}
    assert b.post('/api/v1/cards',json=data,headers=h).status_code==404
    result=a.post('/api/v1/cards',json=data,headers=h);assert result.status_code==201
    card=result.json();cid=card['id']
    assert b.get(f'/api/v1/cards/{cid}').status_code==404
    assert b.get(f'/api/v1/cards/{cid}/versions').status_code==404
    assert a.put(f'/api/v1/cards/{cid}',json={**data,'content':'第二版','version':1},headers=h).status_code==200
    assert a.put(f'/api/v1/cards/{cid}',json={**data,'version':1},headers=h).status_code==409
    history=a.get(f'/api/v1/cards/{cid}/versions').json()
    assert [v['version'] for v in history]==[2,1] and history[1]['snapshot']['content']=='第一版'
    assert len(a.get('/api/v1/cards?q=第二&type=method').json()['items'])==1
    assert a.delete(f'/api/v1/papers/{pid}',headers=h).status_code==204
    detached=a.get(f'/api/v1/cards/{cid}').json()
    assert detached['paper_id']==pid and detached['source_state']=='unavailable' and detached['source_title_snapshot']=='来源文献' and detached['version']==3
    assert len(a.get(f'/api/v1/cards/{cid}/versions').json())==3
    assert b.delete(f'/api/v1/cards/{cid}',headers=h).status_code==404
    assert a.delete(f'/api/v1/cards/{cid}',headers=h).status_code==204


def test_independent_card(clients):
    a,_=clients;h={'X-Requested-With':'zhiyan'}
    response=a.post('/api/v1/cards',json={'title':'想法','type':'idea','content':'独立内容'},headers=h)
    assert response.status_code==201 and response.json()['paper_id'] is None
