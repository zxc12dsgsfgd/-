from test_papers import clients


def test_card_evidence_preserved_in_history_and_legacy_updates(clients):
    alice, bob = clients
    h = {'X-Requested-With': 'zhiyan'}
    paper = alice.post('/api/v1/papers', json={'title': '原始材料'}, headers=h).json()
    payload = {'title': '方法', 'type': 'method', 'content': '模型建议', 'paper_id': paper['id'],
               'source_page': 3, 'source_excerpt': '来源原文', 'note': '我的备注',
               'content_kind': 'ai_suggestion', 'verification_status': 'pending'}
    card = alice.post('/api/v1/cards', json=payload, headers=h).json()
    assert card['source_state'] == 'linked'
    assert bob.get(f"/api/v1/cards/{card['id']}").status_code == 404
    updated = alice.put(f"/api/v1/cards/{card['id']}", json={**payload, 'version': 1, 'verification_status': 'user_checked'}, headers=h)
    assert updated.status_code == 200 and updated.json()['verification_status'] == 'user_checked'
    legacy = {key: value for key, value in payload.items() if key not in ('content_kind', 'verification_status')}
    changed = alice.put(f"/api/v1/cards/{card['id']}", json={**legacy, 'paper_id': None, 'version': 2}, headers=h).json()
    assert changed['content_kind'] == 'ai_suggestion' and changed['verification_status'] == 'pending'
    assert changed['source_state'] == 'detached' and changed['source_title_snapshot'] == '原始材料'
    versions = alice.get(f"/api/v1/cards/{card['id']}/versions").json()
    assert versions[0]['snapshot']['source_state'] == 'detached'
    assert versions[1]['snapshot']['verification_status'] == 'user_checked'
    assert versions[2]['snapshot']['verification_status'] == 'pending'


def test_source_deleted_is_unavailable_and_no_automatic_verification(clients):
    a, _ = clients
    h = {'X-Requested-With': 'zhiyan'}
    paper = a.post('/api/v1/papers', json={'title': '测试来源'}, headers=h).json()['id']
    card = a.post('/api/v1/cards', json={'title': '卡片', 'type': 'idea', 'content': '观点', 'paper_id': paper}, headers=h).json()
    assert card['content_kind'] == 'unspecified' and card['verification_status'] == 'pending'
    assert a.delete(f'/api/v1/papers/{paper}', headers=h).status_code == 204
    result = a.get(f"/api/v1/cards/{card['id']}").json()
    assert result['source_state'] == 'unavailable' and result['verification_status'] == 'pending'
    assert result['source_title_snapshot'] == '测试来源'


def test_draft_source_snapshot_retained_and_availability_checked(clients):
    a, b = clients
    h = {'X-Requested-With': 'zhiyan'}
    card = a.post('/api/v1/cards', json={'title': '来源卡片', 'type': 'idea', 'content': '待核查'}, headers=h).json()['id']
    draft = a.post('/api/v1/drafts', json={'task_type': 'review', 'paper_ids': [], 'card_ids': [card], 'text': '', 'title': '草稿', 'content': '内容'}, headers=h).json()['id']
    url = f'/api/v1/drafts/{draft}/source-status'
    assert b.get(url).status_code == 404
    assert a.get(url).json()['sources'][0]['status'] == 'available'
    assert a.delete(f'/api/v1/cards/{card}', headers=h).status_code == 204
    assert a.get(url).json()['sources'][0]['status'] == 'unavailable'
    assert a.get('/api/v1/drafts').json()[0]['sources'][0]['title'] == '来源卡片'
