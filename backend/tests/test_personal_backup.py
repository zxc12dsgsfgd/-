import json

from test_papers import clients


def test_personal_export_scope_and_read_only_preview(clients):
    alice, bob = clients
    h = {'X-Requested-With': 'zhiyan'}
    paper = alice.post('/api/v1/papers', json={'title': '合成文献'}, headers=h).json()['id']
    alice.post(f'/api/v1/papers/{paper}/notes', json={'content': '合成笔记'}, headers=h)
    card = alice.post('/api/v1/cards', json={'title': '合成卡片', 'type': 'idea', 'content': '合成正文', 'paper_id': paper}, headers=h).json()['id']
    tag = alice.post('/api/v1/tags', json={'name': '合成标签'}, headers=h).json()['id']
    alice.post(f'/api/v1/cards/{card}/tags/{tag}', headers=h)
    project = alice.post('/api/v1/projects', json={'name': '合成项目'}, headers=h).json()['id']
    alice.post(f'/api/v1/projects/{project}/cards/{card}', headers=h)
    bob.post('/api/v1/papers', json={'title': '其他用户私有内容'}, headers=h)
    response = alice.get('/api/v1/personal-backup/export')
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert '其他用户私有内容' not in response.text
    for secret_key in ('password_hash', 'token_hash', 'key_ciphertext', 'api_key'):
        assert secret_key not in response.text
    exported = response.json()
    assert exported['format'] == 'zhiyan-personal-export' and exported['version'] == 4
    assert exported['card_tags'] == [{'left': card, 'right': tag}]
    assert exported['project_cards'] == [{'left': project, 'right': card}]
    assert 'PDF 附件' in exported['excluded']
    preview = bob.post('/api/v1/personal-backup/preview', files={'file': ('backup.json', response.content, 'application/json')}, headers=h)
    assert preview.status_code == 200 and preview.json()['counts']['cards'] == 1
    assert '不覆盖或合并' in preview.json()['notice']
    assert bob.get('/api/v1/cards').json()['items'] == []
    imported = bob.post('/api/v1/personal-backup/restore', files={'file': ('backup.json', response.content, 'application/json')}, data={'confirmed':'true','expected_sha256':preview.json()['sha256']}, headers=h)
    assert imported.status_code == 200
    restored = bob.get('/api/v1/cards').json()['items'][0]
    assert restored['title'] == '合成卡片'
    assert bob.get(f"/api/v1/cards/{restored['id']}/tags").json()[0]['name'] == '合成标签'
    restored_project = bob.get('/api/v1/projects').json()[0]
    assert restored_project['resources']['cards'][0]['id'] == restored['id']
    assert bob.get(f"/api/v1/cards/{restored['id']}/versions").json()[0]['snapshot']['paper_id'] == restored['paper_id']
    again = bob.post('/api/v1/personal-backup/restore', files={'file': ('backup.json', response.content, 'application/json')}, data={'confirmed':'true','expected_sha256':preview.json()['sha256']}, headers=h)
    assert again.status_code == 409 and len(bob.get('/api/v1/cards').json()['items']) == 1


def test_preview_rejects_bad_versions_duplicate_keys_and_invalid_links(clients):
    a, _ = clients
    h = {'X-Requested-With': 'zhiyan'}
    backup = a.get('/api/v1/personal-backup/export').json()
    def preview(data):
        return a.post('/api/v1/personal-backup/preview', files={'file': ('backup.json', data, 'application/json')}, headers=h)
    assert preview(b'{"format":"x","format":"y"}').status_code == 422
    assert preview(json.dumps({**backup, 'version': 5}).encode()).status_code == 422
    assert preview(json.dumps({**backup, 'project_cards': [{'left': 1, 'right': 1}]}).encode()).status_code == 422
    assert preview(b'PK\x03\x04').status_code == 422
    assert preview(b'x' * (10 * 1024 * 1024 + 1)).status_code == 413


def test_restore_requires_preview_digest_and_rolls_back_on_failure(clients):
    from sqlalchemy import event
    from app.models import Tag
    a, b = clients
    h = {'X-Requested-With': 'zhiyan'}
    a.post('/api/v1/papers', json={'title': '不应残留'}, headers=h)
    a.post('/api/v1/tags', json={'name': '失败标签'}, headers=h)
    exported = a.get('/api/v1/personal-backup/export').content
    preview = b.post('/api/v1/personal-backup/preview', files={'file': ('b.json', exported, 'application/json')}, headers=h).json()
    def restore(digest, confirmed='true'):
        return b.post('/api/v1/personal-backup/restore', files={'file': ('b.json', exported, 'application/json')}, data={'confirmed':confirmed,'expected_sha256':digest}, headers=h)
    assert restore('0' * 64).status_code == 409
    assert restore(preview['sha256'], 'false').status_code == 409
    def fail(*args):
        raise RuntimeError('synthetic failure')
    event.listen(Tag, 'before_insert', fail)
    try:
        assert restore(preview['sha256']).status_code == 503
    finally:
        event.remove(Tag, 'before_insert', fail)
    assert b.get('/api/v1/papers').json()['items'] == []


def test_version_2_structured_roundtrip_and_legacy_version_1(clients):
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    paper=a.post('/api/v1/papers',json={'title':'来源'},headers=h).json()['id']
    a.post('/api/v1/reading-templates',json={'name':'自定义','fields':['问题','方法']},headers=h)
    body={'template_name':'旧模板快照','fields':[{'label':'问题','value':'合成问题'},{'label':'方法','value':''}]}
    a.post(f'/api/v1/papers/{paper}/structured-notes',json=body,headers=h)
    a.post('/api/v1/reading-templates',json={'name':'自定义','fields':['其他']},headers=h)
    trashed=a.post('/api/v1/papers',json={'title':'回收文献'},headers=h).json()['id']
    a.post(f'/api/v1/papers/{trashed}/structured-notes',json=body,headers=h)
    a.delete(f'/api/v1/papers/{trashed}',headers=h)
    exported=a.get('/api/v1/personal-backup/export').json()
    assert len(exported['reading_templates'])==2 and len(exported['structured_notes'])==1
    raw=json.dumps(exported,ensure_ascii=False).encode()
    preview=b.post('/api/v1/personal-backup/preview',files={'file':('x.json',raw,'application/json')},headers=h).json()
    assert preview['counts']['structured_notes']==1 and preview['counts']['reading_templates']==2
    restored=b.post('/api/v1/personal-backup/restore',files={'file':('x.json',raw,'application/json')},data={'confirmed':'true','expected_sha256':preview['sha256']},headers=h)
    assert restored.status_code==200
    new_paper=b.get('/api/v1/papers').json()['items'][0]['id']
    assert new_paper!=paper
    assert b.get(f'/api/v1/papers/{new_paper}/structured-notes').json()[0]['fields']==body['fields']
    assert len(b.get('/api/v1/reading-templates').json()['custom'])==2
    legacy={k:v for k,v in exported.items() if k not in ('structured_notes','reading_templates','plans','drafts','project_plans','project_drafts','evidence')};legacy['version']=1
    legacy_raw=json.dumps(legacy,ensure_ascii=False).encode()
    old_preview=b.post('/api/v1/personal-backup/preview',files={'file':('v1.json',legacy_raw,'application/json')},headers=h)
    assert old_preview.status_code==200 and '结构化阅读笔记及自定义模板' in old_preview.json()['excluded']
    old_restore=b.post('/api/v1/personal-backup/restore',files={'file':('v1.json',legacy_raw,'application/json')},data={'confirmed':'true','expected_sha256':old_preview.json()['sha256']},headers=h)
    assert old_restore.status_code==200
    v2={k:v for k,v in exported.items() if k not in ('plans','drafts','project_plans','project_drafts','evidence')};v2['version']=2
    v2_raw=json.dumps(v2,ensure_ascii=False).encode()
    v2_preview=b.post('/api/v1/personal-backup/preview',files={'file':('v2.json',v2_raw,'application/json')},headers=h)
    assert v2_preview.status_code==200 and '阅读计划和草稿' in v2_preview.json()['excluded']
    v2_restore=b.post('/api/v1/personal-backup/restore',files={'file':('v2.json',v2_raw,'application/json')},data={'confirmed':'true','expected_sha256':v2_preview.json()['sha256']},headers=h)
    assert v2_restore.status_code==200
    assert len(b.get('/api/v1/reading-templates').json()['custom'])==4
    assert len(b.get('/api/v1/structured-notes').json()['items'])==2
    invalid={**exported,'structured_notes':[{'paper_id':99999,**body}]}
    assert b.post('/api/v1/personal-backup/preview',files={'file':('bad.json',json.dumps(invalid).encode(),'application/json')},headers=h).status_code==422


def test_plan_draft_project_restore_and_missing_source_is_not_relinked(clients):
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    p=a.post('/api/v1/papers',json={'title':'文献'},headers=h).json()['id']
    c=a.post('/api/v1/cards',json={'title':'来源卡','type':'idea','content':'正文'},headers=h).json()['id']
    missing=a.post('/api/v1/cards',json={'title':'已回收','type':'idea','content':'旧快照'},headers=h).json()['id']
    plan=a.post('/api/v1/plans',json={'name':'计划','start_date':'2026-11-20','target_count':1,'paper_ids':[p]},headers=h).json()['id']
    draft=a.post('/api/v1/drafts',json={'task_type':'review','title':'草稿','content':'内容','paper_ids':[p],'card_ids':[c,missing],'text':'手工材料'},headers=h).json()['id']
    a.delete(f'/api/v1/cards/{missing}',headers=h)
    project=a.post('/api/v1/projects',json={'name':'课题'},headers=h).json()['id']
    for kind,id in [('plans',plan),('drafts',draft)]:assert a.post(f'/api/v1/projects/{project}/{kind}/{id}',headers=h).status_code==204
    raw=a.get('/api/v1/personal-backup/export').content
    pre=b.post('/api/v1/personal-backup/preview',files={'file':('b.json',raw,'application/json')},headers=h).json()
    assert pre['counts']['plans']==1 and pre['counts']['drafts']==1
    result=b.post('/api/v1/personal-backup/restore',files={'file':('b.json',raw,'application/json')},data={'confirmed':'true','expected_sha256':pre['sha256']},headers=h)
    assert result.status_code==200
    new_plan=b.get('/api/v1/plans').json()[0];new_draft=b.get('/api/v1/drafts').json()[0]
    assert new_plan['papers'][0]['title']=='文献'
    statuses=b.get(f"/api/v1/drafts/{new_draft['id']}/source-status").json()['sources']
    assert [s['status'] for s in statuses]==['available','available','unavailable','text_snapshot']
    assert next(s for s in new_draft['sources'] if s.get('title')=='已回收')['id'] is None
    project_data=b.get('/api/v1/projects').json()[0]
    assert project_data['resources']['plans'][0]['id']==new_plan['id']
    assert project_data['resources']['drafts'][0]['id']==new_draft['id']


def test_structured_note_failure_rolls_back_templates_and_papers(clients):
    from sqlalchemy import event
    from app.models import StructuredNote
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    paper=a.post('/api/v1/papers',json={'title':'事务测试'},headers=h).json()['id']
    a.post('/api/v1/reading-templates',json={'name':'模板','fields':['方法']},headers=h)
    a.post(f'/api/v1/papers/{paper}/structured-notes',json={'template_name':'模板','fields':[{'label':'方法','value':'内容'}]},headers=h)
    raw=a.get('/api/v1/personal-backup/export').content
    digest=b.post('/api/v1/personal-backup/preview',files={'file':('x.json',raw,'application/json')},headers=h).json()['sha256']
    def fail(*args):raise RuntimeError('synthetic')
    event.listen(StructuredNote,'before_insert',fail)
    try:
        result=b.post('/api/v1/personal-backup/restore',files={'file':('x.json',raw,'application/json')},data={'confirmed':'true','expected_sha256':digest},headers=h)
        assert result.status_code==503
    finally:event.remove(StructuredNote,'before_insert',fail)
    assert b.get('/api/v1/papers').json()['items']==[]
    assert b.get('/api/v1/reading-templates').json()['custom']==[]
    assert b.get('/api/v1/structured-notes').json()['items']==[]


def test_evidence_history_roundtrip_missing_source_and_v3(clients):
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    paper=a.post('/api/v1/papers',json={'title':'来源','doi':'10.1234/example'},headers=h).json()['id']
    missing=a.post('/api/v1/papers',json={'title':'回收来源'},headers=h).json()['id']
    card=a.post('/api/v1/cards',json={'title':'卡片','type':'idea','content':'正文'},headers=h).json()['id']
    draft=a.post('/api/v1/drafts',json={'task_type':'review','title':'草稿','content':'正文','paper_ids':[],'card_ids':[],'text':''},headers=h).json()['id']
    url=f'/api/v1/cards/{card}/evidence'
    link=a.post(url,json={'source_type':'paper','source_id':paper,'excerpt':'初始'},headers=h).json()['id']
    a.put(f'{url}/{link}',json={'excerpt':'修改','note':'合成备注'},headers=h)
    gone=a.post(f'/api/v1/drafts/{draft}/evidence',json={'source_type':'paper','source_id':missing,'note':'失效'},headers=h).json()['id']
    removed=a.post(url,json={'source_type':'paper','source_id':paper,'note':'移除'},headers=h).json()['id']
    a.delete(f'{url}/{removed}',headers=h)
    a.delete(f'/api/v1/papers/{missing}',headers=h)
    raw=a.get('/api/v1/personal-backup/export').content
    preview=b.post('/api/v1/personal-backup/preview',files={'file':('b.json',raw,'application/json')},headers=h).json()
    assert preview['counts']['evidence']==3 and preview['counts']['evidence_changes']==5
    result=b.post('/api/v1/personal-backup/restore',files={'file':('b.json',raw,'application/json')},data={'confirmed':'true','expected_sha256':preview['sha256']},headers=h)
    assert result.status_code==200
    new_card=b.get('/api/v1/cards').json()['items'][0]['id'];new_draft=b.get('/api/v1/drafts').json()[0]['id']
    restored=b.get(f'/api/v1/cards/{new_card}/evidence').json()
    assert [x['status'] for x in restored]==['available','removed']
    history=b.get(f"/api/v1/cards/{new_card}/evidence/{restored[0]['id']}/history").json()
    assert [x['action'] for x in history]==['created','updated'] and history[0]['detail']['excerpt']=='初始'
    assert history[0]['detail']['source_id']==restored[0]['source_id']!=paper
    unavailable=b.get(f'/api/v1/drafts/{new_draft}/evidence').json()[0]
    assert unavailable['status']=='unavailable' and unavailable['source_id'] is None
    assert b.get(f"/api/v1/drafts/{new_draft}/evidence/{unavailable['id']}/history").json()[0]['detail']['source_id'] is None
    assert b.get('/api/v1/personal-backup/export').status_code==200
    legacy=json.loads(raw);legacy.pop('evidence');legacy['version']=3
    pre=b.post('/api/v1/personal-backup/preview',files={'file':('v3.json',json.dumps(legacy).encode(),'application/json')},headers=h)
    assert pre.status_code==200 and '手动证据关联及其历史' in pre.json()['excluded']
    legacy_raw=json.dumps(legacy).encode()
    assert b.post('/api/v1/personal-backup/restore',files={'file':('v3.json',legacy_raw,'application/json')},data={'confirmed':'true','expected_sha256':pre.json()['sha256']},headers=h).status_code==200
    assert len(b.get('/api/v1/cards').json()['items'])==2


def test_evidence_import_failure_rolls_back_all(clients):
    from sqlalchemy import event
    from app.models import EvidenceChange
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    paper=a.post('/api/v1/papers',json={'title':'事务来源'},headers=h).json()['id']
    card=a.post('/api/v1/cards',json={'title':'事务卡','type':'idea','content':'正文'},headers=h).json()['id']
    a.post(f'/api/v1/cards/{card}/evidence',json={'source_type':'paper','source_id':paper},headers=h)
    raw=a.get('/api/v1/personal-backup/export').content
    digest=b.post('/api/v1/personal-backup/preview',files={'file':('x.json',raw,'application/json')},headers=h).json()['sha256']
    def fail(*args):raise RuntimeError('synthetic')
    event.listen(EvidenceChange,'before_insert',fail)
    try:
        assert b.post('/api/v1/personal-backup/restore',files={'file':('x.json',raw,'application/json')},data={'confirmed':'true','expected_sha256':digest},headers=h).status_code==503
    finally:event.remove(EvidenceChange,'before_insert',fail)
    assert b.get('/api/v1/papers').json()['items']==[] and b.get('/api/v1/cards').json()['items']==[]
