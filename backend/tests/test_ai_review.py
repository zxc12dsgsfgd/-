from test_papers import clients


def test_review_requires_current_content_and_resets_on_edit(clients):
    a, b = clients
    h={'X-Requested-With':'zhiyan'}
    payload={'task_type':'review','paper_ids':[],'card_ids':[],'text':'','title':'初稿','content':'未经核实'}
    d=a.post('/api/v1/drafts',json=payload,headers=h).json(); did=d['id']
    review={'title':d['title'],'content':d['content']}
    assert b.post(f'/api/v1/drafts/{did}/accept',json=review,headers=h).status_code==404
    assert a.post(f'/api/v1/drafts/{did}/accept',json={**review,'content':'过期内容'},headers=h).status_code==409
    assert a.post(f'/api/v1/drafts/{did}/accept',json=review,headers=h).json()['status']=='accepted'
    assert a.put(f'/api/v1/drafts/{did}',json=review,headers=h).json()['status']=='accepted'
    assert a.put(f'/api/v1/drafts/{did}',json={'title':'已修改','content':'新内容'},headers=h).json()['status']=='draft'
    assert a.post(f'/api/v1/drafts/{did}/accept',json=review,headers=h).status_code==409


def test_apply_tags_requires_acceptance_and_owned_resources(clients):
    a,b=clients; h={'X-Requested-With':'zhiyan'}
    draft=a.post('/api/v1/drafts',json={'task_type':'tags','paper_ids':[],'card_ids':[],'text':'','title':'标签建议','content':'建议方法'},headers=h).json()
    card=a.post('/api/v1/cards',json={'title':'卡片','content':'内容','type':'concept'},headers=h).json()
    foreign=b.post('/api/v1/cards',json={'title':'其他卡片','content':'内容','type':'concept'},headers=h).json()
    tag=a.post('/api/v1/tags',json={'name':'方法'},headers=h).json()
    other=b.post('/api/v1/tags',json={'name':'私人'},headers=h).json()
    base={'title':draft['title'],'content':draft['content'],'card_id':card['id'],'tag_ids':[tag['id']]}
    url=f"/api/v1/drafts/{draft['id']}/apply-tags"
    assert a.post(url,json=base,headers=h).status_code==409
    assert a.get(f"/api/v1/cards/{card['id']}/tags").json()==[]
    assert a.post(f"/api/v1/drafts/{draft['id']}/accept",json={'title':draft['title'],'content':draft['content']},headers=h).status_code==200
    assert b.post(url,json=base,headers=h).status_code==404
    assert a.post(url,json={**base,'card_id':foreign['id']},headers=h).status_code==404
    assert a.post(url,json={**base,'tag_ids':[tag['id'],other['id']]},headers=h).status_code==404
    assert a.get(f"/api/v1/cards/{card['id']}/tags").json()==[]
    assert a.post(url,json=base,headers=h).json()['added']==1
    assert a.post(url,json=base,headers=h).json()['added']==0
    assert a.get(f"/api/v1/cards/{card['id']}/tags").json()==[tag]
    a.put(f"/api/v1/drafts/{draft['id']}",json={'title':'标签建议','content':'变化'},headers=h)
    assert a.post(url,json=base,headers=h).status_code==409
