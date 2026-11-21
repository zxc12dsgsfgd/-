from test_papers import clients


def test_export_cards_formats_and_isolation(clients):
    a, b = clients
    h = {'X-Requested-With': 'zhiyan'}
    p = a.post('/api/v1/papers', json={'title': 'A & B', 'authors': ['Doe'], 'year': 2024, 'doi': '10.1/test'}, headers=h).json()['id']
    c = a.post('/api/v1/cards', json={'title': '标题_1', 'type': 'concept', 'content': '50% & $x$', 'paper_id': p, 'source_page': 3, 'source_excerpt': '摘录'}, headers=h).json()['id']
    def export(client, fmt, **selection):
        return client.post('/api/v1/exports', json={'format': fmt, **selection}, headers=h)
    md = export(a, 'markdown', card_ids=[c])
    assert md.status_code == 200 and 'A & B' in md.text and '页码：3' in md.text and '摘录' in md.text
    latex = export(a, 'latex', card_ids=[c])
    assert r'标题\_1' in latex.text and r'50\% \& \$x\$' in latex.text
    bib = export(a, 'bibtex', card_ids=[c])
    assert '@misc{source1,' in bib.text and r'A \& B' in bib.text and '10.1/test' in bib.text
    assert export(b, 'markdown', card_ids=[c]).status_code == 404
    assert export(a, 'markdown', card_ids=[c, c]).status_code == 422
    assert export(a, 'markdown', card_ids=[c], draft_id=1).status_code == 422
    assert a.delete(f'/api/v1/papers/{p}', headers=h).status_code == 204
    assert 'A & B' in export(a, 'markdown', card_ids=[c]).text
    assert export(a, 'bibtex', card_ids=[c]).text == ''


def test_draft_export_uses_saved_snapshots(clients):
    a, b = clients
    h = {'X-Requested-With': 'zhiyan'}
    p = a.post('/api/v1/papers', json={'title': '保存时的来源', 'authors': ['作者'], 'year': 2020}, headers=h).json()['id']
    draft = a.post('/api/v1/drafts', json={'task_type': 'review', 'paper_ids': [p], 'card_ids': [], 'text': '', 'title': '草稿', 'content': '正文'}, headers=h).json()['id']
    assert a.delete(f'/api/v1/papers/{p}', headers=h).status_code == 204
    for fmt in ('markdown', 'latex', 'bibtex'):
        response = a.post('/api/v1/exports', json={'format': fmt, 'draft_id': draft}, headers=h)
        assert response.status_code == 200 and '保存时的来源' in response.text
    assert b.post('/api/v1/exports', json={'format': 'markdown', 'draft_id': draft}, headers=h).status_code == 404
