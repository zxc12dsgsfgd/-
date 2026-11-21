from datetime import timedelta

from sqlalchemy import select

from app.auth import digest, get_db, now
from app.main import app
from app.models import Share
from test_papers import clients


def test_snapshot_comment_isolation_and_revoke(clients):
    a, b = clients
    h = {'X-Requested-With': 'zhiyan'}
    card = a.post('/api/v1/cards', json={'title': '原始标题', 'content': '私有正文', 'type': 'concept'}, headers=h).json()
    choice = {'card_ids': [card['id']], 'expires_days': 7, 'allow_comments': True}
    assert b.post('/api/v1/shares', json=choice, headers=h).status_code == 404
    created = a.post('/api/v1/shares', json=choice, headers=h)
    assert created.status_code == 201
    share_id, token = created.json()['id'], created.json()['token']
    assert token not in a.get('/api/v1/shares').text
    gen = app.dependency_overrides[get_db](); db = next(gen)
    try:
        saved = db.scalar(select(Share).where(Share.id == share_id))
        assert saved.token_hash == digest(token) and token.encode() not in saved.token_hash
    finally: gen.close()
    public = {'X-Share-Token': token}
    assert a.delete(f"/api/v1/cards/{card['id']}", headers=h).status_code == 204
    result = b.get('/api/v1/public/shares', headers=public)
    assert result.status_code == 200 and result.json()['items'][0]['snapshot']['title'] == '原始标题'
    assert result.headers['cache-control'] == 'no-store'
    item_id = result.json()['items'][0]['id']
    payload = {'share_item_id': item_id, 'author_name': '访客', 'content': '<script>alert(1)</script>'}
    assert b.post('/api/v1/public/shares/comments', json=payload, headers={**h, **public}).status_code == 201
    assert b.post('/api/v1/public/shares/comments', json={**payload, 'share_item_id': item_id + 1}, headers={**h, **public}).status_code == 404
    assert b.get(f'/api/v1/shares/{share_id}/comments').status_code == 404
    comment = a.get(f'/api/v1/shares/{share_id}/comments').json()[0]
    assert comment['content'] == payload['content']
    assert a.patch(f"/api/v1/shares/{share_id}/comments/{comment['id']}", json={'handled': True}, headers=h).status_code == 200
    assert a.get(f'/api/v1/shares/{share_id}/comments').json()[0]['handled_at'] is not None
    assert b.post(f'/api/v1/shares/{share_id}/revoke', headers=h).status_code == 404
    assert a.post(f'/api/v1/shares/{share_id}/revoke', headers=h).status_code == 204
    assert b.get('/api/v1/public/shares', headers=public).status_code == 404
    assert b.post('/api/v1/public/shares/comments', json=payload, headers={**h, **public}).status_code == 404


def test_disabled_expired_and_draft_snapshots(clients):
    a, b = clients
    h = {'X-Requested-With': 'zhiyan'}
    draft = a.post('/api/v1/drafts', json={'task_type':'review','paper_ids':[],'card_ids':[],'text':'x','title':'草稿','content':'正文'}, headers=h).json()
    share = a.post('/api/v1/shares', json={'draft_id':draft['id'],'expires_days':1,'allow_comments':False}, headers=h).json()
    public = {'X-Share-Token': share['token']}
    assert a.delete(f"/api/v1/drafts/{draft['id']}", headers=h).status_code == 204
    result = b.get('/api/v1/public/shares', headers=public)
    assert result.json()['items'][0]['snapshot'] == {'title':'草稿','content':'正文'}
    item = result.json()['items'][0]['id']
    assert b.post('/api/v1/public/shares/comments', json={'share_item_id':item,'author_name':'a','content':'x'}, headers={**h,**public}).status_code == 403
    gen = app.dependency_overrides[get_db](); db = next(gen)
    try:
        saved = db.scalar(select(Share).where(Share.id == share['id'])); saved.expires_at = now() - timedelta(seconds=1); db.commit()
    finally: gen.close()
    assert b.get('/api/v1/public/shares', headers=public).status_code == 404
    assert b.get('/api/v1/public/shares', headers={'X-Share-Token':'invalid'}).status_code == 404


def test_public_share_rate_limit_counts_invalid_requests(clients):
    a, _ = clients
    headers = {'X-Share-Token': 'invalid'}
    for _ in range(60):
        assert a.get('/api/v1/public/shares', headers=headers).status_code == 404
    response = a.get('/api/v1/public/shares', headers=headers)
    assert response.status_code == 429 and response.headers['retry-after'] == '60'
