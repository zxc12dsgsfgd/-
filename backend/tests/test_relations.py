from test_papers import clients


def test_relation_graph_and_isolation(clients):
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    def card(c,title):
        r=c.post('/api/v1/cards',json={'title':title,'type':'idea','content':'内容'},headers=h);assert r.status_code==201;return r.json()['id']
    x=card(a,'甲');y=card(a,'乙');z=card(b,'他人')
    payload={'source_card_id':x,'target_card_id':y,'relation_type':'supports'}
    assert a.post('/api/v1/card-relations',json={**payload,'target_card_id':x},headers=h).status_code==422
    assert a.post('/api/v1/card-relations',json={**payload,'target_card_id':z},headers=h).status_code==404
    result=a.post('/api/v1/card-relations',json=payload,headers=h);assert result.status_code==201
    assert a.post('/api/v1/card-relations',json=payload,headers=h).status_code==409
    graph=a.get('/api/v1/graph').json();assert len(graph['nodes'])==2 and len(graph['edges'])==1
    assert len(b.get('/api/v1/graph').json()['edges'])==0
    assert b.delete(f"/api/v1/card-relations/{result.json()['id']}",headers=h).status_code==404
    assert a.delete(f'/api/v1/cards/{x}',headers=h).status_code==204
    assert a.get('/api/v1/graph').json()['edges']==[]
