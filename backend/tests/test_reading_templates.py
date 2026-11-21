from test_papers import clients


def test_template_note_search_to_card_and_isolation(clients):
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    paper=a.post('/api/v1/papers',json={'title':'合成论文'},headers=h).json()['id']
    default=a.get('/api/v1/reading-templates').json()['default']
    assert '研究问题' in default['fields'] and '研究方法' in default['fields']
    template=a.post('/api/v1/reading-templates',json={'name':'我的模板','fields':['研究问题','研究方法','局限']},headers=h).json()
    assert b.get('/api/v1/reading-templates').json()['custom']==[]
    assert b.put(f"/api/v1/reading-templates/{template['id']}",json={'name':'窃取','fields':['x']},headers=h).status_code==404
    body={'template_name':template['name'],'fields':[{'label':'研究问题','value':'为何变化？'},{'label':'研究方法','value':'采用合成对照方法'},{'label':'局限','value':''}]}
    note=a.post(f'/api/v1/papers/{paper}/structured-notes',json=body,headers=h)
    assert note.status_code==201;note_id=note.json()['id']
    assert b.get(f'/api/v1/papers/{paper}/structured-notes').status_code==404
    assert b.put(f'/api/v1/structured-notes/{note_id}',json=body,headers=h).status_code==404
    assert a.put(f"/api/v1/reading-templates/{template['id']}",json={'name':'已修改','fields':['新字段']},headers=h).status_code==200
    assert a.get(f'/api/v1/papers/{paper}/structured-notes').json()[0]['fields']==body['fields']
    assert a.get('/api/v1/structured-notes',params={'q':'合成对照'}).json()['items'][0]['id']==note_id
    assert b.get('/api/v1/structured-notes',params={'q':'合成对照'}).json()['items']==[]
    assert a.post(f'/api/v1/structured-notes/{note_id}/cards',json={'field_index':2,'title':'空字段'},headers=h).status_code==422
    result=a.post(f'/api/v1/structured-notes/{note_id}/cards',json={'field_index':1,'title':'研究方法','type':'method'},headers=h)
    assert result.status_code==201
    card=a.get(f"/api/v1/cards/{result.json()['id']}").json()
    assert card['content']=='采用合成对照方法' and card['paper_id']==paper
    assert card['content_kind']=='interpretation' and card['verification_status']=='pending' and card['source_excerpt'] is None
    assert card['note']=='阅读笔记字段：研究方法'
    assert a.delete(f'/api/v1/papers/{paper}',headers=h).status_code==204
    assert a.get('/api/v1/structured-notes',params={'q':'合成对照'}).json()['items']==[]
    assert a.post(f'/api/v1/trash/papers/{paper}/restore',headers=h).status_code==204
    assert a.get(f'/api/v1/papers/{paper}/structured-notes').json()[0]['id']==note_id
    assert a.delete(f'/api/v1/papers/{paper}',headers=h).status_code==204
    assert a.request('DELETE',f'/api/v1/trash/papers/{paper}',json={'confirm':True},headers=h).status_code==204
    assert a.get('/api/v1/structured-notes').json()['items']==[]


def test_template_field_validation_and_empty_values(clients):
    a,_=clients;h={'X-Requested-With':'zhiyan'}
    paper=a.post('/api/v1/papers',json={'title':'文献'},headers=h).json()['id']
    assert a.post('/api/v1/reading-templates',json={'name':'重复','fields':['方法',' 方法 ']},headers=h).status_code==422
    note={'template_name':'空模板','fields':[{'label':'研究问题','value':''}]}
    assert a.post(f'/api/v1/papers/{paper}/structured-notes',json=note,headers=h).status_code==201
