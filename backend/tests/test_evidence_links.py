from test_papers import clients


def test_evidence_lifecycle_owner_isolation_and_snapshot(clients):
    alice, bob = clients
    h = {'X-Requested-With': 'zhiyan'}
    paper = alice.post('/api/v1/papers', json={'title': '来源', 'doi': '10.1234/test'}, headers=h).json()['id']
    other = bob.post('/api/v1/papers', json={'title': '他人'}, headers=h).json()['id']
    card = alice.post('/api/v1/cards', json={'title': '卡片', 'type': 'idea', 'content': '观点', 'verification_status': 'user_checked'}, headers=h).json()
    url = f"/api/v1/cards/{card['id']}/evidence"
    data = {'source_type': 'paper', 'source_id': paper, 'location': '第 4 页', 'excerpt': '原文', 'note': '说明'}
    assert bob.post(url, json=data, headers=h).status_code == 404
    assert alice.post(url, json={**data, 'source_id': other}, headers=h).status_code == 404
    assert alice.post(url, json={'source_type': 'card', 'source_id': card['id']}, headers=h).status_code == 422
    result = alice.post(url, json=data, headers=h)
    assert result.status_code == 201
    link = result.json(); assert link['source_snapshot']['doi'] == '10.1234/test'
    assert alice.get(f"/api/v1/cards/{card['id']}").json()['verification_status'] == 'pending'
    link_url = f"{url}/{link['id']}"
    assert bob.put(link_url, json={'note': '越权'}, headers=h).status_code == 404
    assert alice.put(link_url, json={'location': '第 5 页', 'excerpt': '另一段', 'note': '修改'}, headers=h).status_code == 200
    assert alice.delete(f'/api/v1/papers/{paper}', headers=h).status_code == 204
    assert alice.get(url).json()[0]['status'] == 'unavailable'
    assert alice.delete(link_url, headers=h).status_code == 204
    assert alice.get(url).json()[0]['status'] == 'removed'
    history = alice.get(link_url + '/history').json()
    assert [item['action'] for item in history] == ['created', 'updated', 'removed']
    assert history[0]['detail']['excerpt'] == '原文' and history[1]['detail']['excerpt'] == '另一段'
    assert bob.get(link_url + '/history').status_code == 404


def test_draft_manual_evidence_never_changes_original_selection(clients):
    alice, _ = clients
    h = {'X-Requested-With': 'zhiyan'}
    card = alice.post('/api/v1/cards', json={'title': '原材料', 'type': 'idea', 'content': '内容'}, headers=h).json()['id']
    paper = alice.post('/api/v1/papers', json={'title': '后来补充'}, headers=h).json()['id']
    draft = alice.post('/api/v1/drafts', json={'task_type': 'review', 'paper_ids': [], 'card_ids': [card], 'text': '', 'title': '草稿', 'content': '内容'}, headers=h).json()
    alice.post(f"/api/v1/drafts/{draft['id']}/accept", json={'title': '草稿', 'content': '内容'}, headers=h)
    created = alice.post(f"/api/v1/drafts/{draft['id']}/evidence", json={'source_type': 'paper', 'source_id': paper}, headers=h)
    assert created.status_code == 201
    after = alice.get('/api/v1/drafts').json()[0]
    assert after['sources'] == draft['sources'] and after['status'] == 'draft'
    assert alice.delete(f"/api/v1/drafts/{draft['id']}", headers=h).status_code == 204
