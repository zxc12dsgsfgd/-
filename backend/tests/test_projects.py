from test_papers import clients


def test_projects_share_resources_and_enforce_ownership(clients):
    alice, bob = clients
    h = {'X-Requested-With': 'zhiyan'}
    one = alice.post('/api/v1/projects', json={'name': '项目一'}, headers=h).json()
    two = alice.post('/api/v1/projects', json={'name': '项目二'}, headers=h).json()
    card = alice.post('/api/v1/cards', json={'title': '共享卡片', 'type': 'idea', 'content': '内容'}, headers=h).json()
    foreign = bob.post('/api/v1/cards', json={'title': '他人的卡片', 'type': 'idea', 'content': '内容'}, headers=h).json()
    for project in (one, two):
        url = f"/api/v1/projects/{project['id']}/cards/{card['id']}"
        assert alice.post(url, headers=h).status_code == 204
        assert alice.post(url, headers=h).status_code == 204
    assert bob.get(f"/api/v1/projects/{one['id']}").status_code == 404
    assert bob.post(f"/api/v1/projects/{one['id']}/cards/{foreign['id']}", headers=h).status_code == 404
    assert alice.post(f"/api/v1/projects/{one['id']}/cards/{foreign['id']}", headers=h).status_code == 404
    assert alice.delete(f"/api/v1/projects/{one['id']}/cards/{card['id']}", headers=h).status_code == 204
    assert alice.get(f"/api/v1/projects/{one['id']}").json()['counts']['cards'] == 0
    assert alice.get(f"/api/v1/projects/{two['id']}").json()['counts']['cards'] == 1
    assert alice.delete(f"/api/v1/projects/{two['id']}", headers=h).status_code == 204
    assert alice.get(f"/api/v1/cards/{card['id']}").status_code == 200
    assert alice.put(f"/api/v1/projects/{one['id']}", json={'name': '完成', 'status': 'completed'}, headers=h).json()['status'] == 'completed'
    assert alice.put(f"/api/v1/projects/{one['id']}", json={'name': '归档', 'status': 'archived'}, headers=h).json()['status'] == 'archived'


def test_project_four_resource_types_and_real_progress(clients):
    a, _ = clients
    h = {'X-Requested-With': 'zhiyan'}
    project = a.post('/api/v1/projects', json={'name': '材料'}, headers=h).json()['id']
    paper = a.post('/api/v1/papers', json={'title': '已读文献', 'status': 'read'}, headers=h).json()['id']
    card = a.post('/api/v1/cards', json={'title': '卡片', 'type': 'idea', 'content': '正文'}, headers=h).json()['id']
    plan = a.post('/api/v1/plans', json={'name': '计划', 'start_date': '2026-11-20', 'target_count': 1, 'paper_ids': [paper]}, headers=h).json()['id']
    draft = a.post('/api/v1/drafts', json={'task_type': 'review', 'paper_ids': [], 'card_ids': [], 'text': '', 'title': '草稿', 'content': '正文'}, headers=h).json()['id']
    for kind, resource in [('papers', paper), ('cards', card), ('plans', plan), ('drafts', draft)]:
        assert a.post(f'/api/v1/projects/{project}/{kind}/{resource}', headers=h).status_code == 204
    details = a.get(f'/api/v1/projects/{project}').json()
    assert details['counts'] == {'papers': 1, 'cards': 1, 'plans': 1, 'drafts': 1}
    assert details['resources']['plans'][0]['completed'] == 1
    assert details['resources']['plans'][0]['total'] == 1
