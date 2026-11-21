from test_papers import clients


def test_tags_associations_filters_and_isolation(clients):
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    tag=a.post('/api/v1/tags',json={'name':'  Research  '},headers=h)
    assert tag.status_code==201; tid=tag.json()['id']
    assert a.post('/api/v1/tags',json={'name':'research'},headers=h).status_code==409
    assert b.post('/api/v1/tags',json={'name':'research'},headers=h).status_code==201
    p=a.post('/api/v1/papers',json={'title':'文献'},headers=h).json()['id']
    c=a.post('/api/v1/cards',json={'title':'卡片','type':'idea','content':'内容'},headers=h).json()['id']
    assert b.post(f'/api/v1/cards/{c}/tags/{tid}',headers=h).status_code==404
    assert b.get(f'/api/v1/cards/{c}/tags').status_code==404
    assert a.post(f'/api/v1/papers/{p}/tags/{tid}',headers=h).status_code==204
    assert a.post(f'/api/v1/cards/{c}/tags/{tid}',headers=h).status_code==204
    assert a.post(f'/api/v1/cards/{c}/tags/{tid}',headers=h).status_code==204
    assert len(a.get(f'/api/v1/papers?tag_id={tid}').json()['items'])==1
    assert len(a.get(f'/api/v1/cards?tag_id={tid}').json()['items'])==1
    assert a.put(f'/api/v1/tags/{tid}',json={'name':'修改'},headers=h).status_code==200
    assert a.get(f'/api/v1/cards/{c}/tags').json()[0]['name']=='修改'
    assert a.delete(f'/api/v1/cards/{c}/tags/{tid}',headers=h).status_code==204
    assert a.get(f'/api/v1/cards/{c}/tags').json()==[]
    assert a.delete(f'/api/v1/tags/{tid}',headers=h).status_code==204
    assert a.get(f'/api/v1/papers/{p}').status_code==200
    assert a.get(f'/api/v1/papers/{p}/tags').json()==[]
