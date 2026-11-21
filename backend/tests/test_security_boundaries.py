from test_papers import clients


def test_cross_owner_resource_combinations_do_not_change_data(clients):
    alice, bob = clients
    headers = {'X-Requested-With': 'zhiyan'}
    paper = alice.post('/api/v1/papers', json={'title': '甲的文献'}, headers=headers).json()
    card = alice.post('/api/v1/cards', json={'title': '甲的卡片', 'type': 'idea', 'content': '私有内容'}, headers=headers).json()
    alice_tag = alice.post('/api/v1/tags', json={'name': '甲的标签'}, headers=headers).json()
    bob_tag = bob.post('/api/v1/tags', json={'name': '乙的标签'}, headers=headers).json()

    assert bob.post('/api/v1/cards', json={'title': '越权引用', 'type': 'idea', 'content': '内容', 'paper_id': paper['id']}, headers=headers).status_code == 404
    assert bob.get(f"/api/v1/cards/{card['id']}/versions").status_code == 404
    assert bob.get(f"/api/v1/papers/{paper['id']}/notes").status_code == 404
    assert bob.post(f"/api/v1/cards/{card['id']}/tags/{bob_tag['id']}", headers=headers).status_code == 404
    assert alice.post(f"/api/v1/cards/{card['id']}/tags/{bob_tag['id']}", headers=headers).status_code == 404
    assert bob.delete(f"/api/v1/tags/{alice_tag['id']}", headers=headers).status_code == 404
    assert alice.get(f"/api/v1/cards/{card['id']}/tags").json() == []
    assert alice.get(f"/api/v1/cards/{card['id']}").json()['content'] == '私有内容'
    assert alice.get('/api/v1/tags').json() == [alice_tag]


def test_browser_cross_origin_mutations_and_reads_are_not_authorized(clients):
    alice, _ = clients
    path = '/api/v1/papers'
    attacker = 'https://untrusted.example'
    payload = {'title': '跨来源写入'}
    for headers in ({'Origin': attacker}, {'Origin': attacker, 'X-Requested-With': 'zhiyan'}):
        assert alice.post(path, json=payload, headers=headers).status_code == 403
    preflight = alice.options(path, headers={
        'Origin': attacker, 'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'content-type,x-requested-with',
    })
    assert 'access-control-allow-origin' not in preflight.headers
    read = alice.get(path, headers={'Origin': attacker})
    assert 'access-control-allow-origin' not in read.headers
    assert alice.get(path).json()['items'] == []


def test_exact_configured_public_origin_only(clients, monkeypatch):
    from app.config import get_settings
    alice, _ = clients
    monkeypatch.setattr(get_settings(), 'public_origin', 'https://approved.example')
    headers = {'X-Requested-With': 'zhiyan'}
    data = {'title': '公网测试文献'}
    assert alice.post('/api/v1/papers', json=data, headers={**headers, 'Origin': 'https://approved.example'}).status_code == 201
    for origin in ('https://other.example', 'https://approved.example.attacker.example', 'http://approved.example'):
        assert alice.post('/api/v1/papers', json=data, headers={**headers, 'Origin': origin}).status_code == 403


def test_public_origin_configuration_requires_exact_https_origin():
    import pytest
    from pydantic import ValidationError
    from app.config import Settings
    assert Settings(public_origin='https://approved.example').public_origin == 'https://approved.example'
    for value in ('http://approved.example', 'https://*.example', 'https://approved.example/path', 'https://approved.example?x=1', 'https://user@approved.example'):
        with pytest.raises(ValidationError):
            Settings(public_origin=value)
