from test_papers import clients


def test_batch_preview_and_duplicate_scope(clients):
    a, b = clients
    h = {'X-Requested-With': 'zhiyan'}
    assert a.post('/api/v1/papers', json={'title':'Existing', 'doi':'10.1234/ABC'}, headers=h).status_code == 201
    raw = '@article{a,title={First},doi={10.1234/abc}}\n@book{b,title={Second},doi={10.1234/abc}}\n@article{c,title={Third},author={Doe, Jane and Smith, John}}'
    result = a.post('/api/v1/papers/import/batch-preview', json={'value':raw}, headers=h)
    assert result.status_code == 200
    entries = result.json()['items']
    assert len(entries) == 3 and len(entries[0]['duplicates']) == 1
    assert entries[1]['batch_duplicates'] == [1]
    assert entries[2]['paper']['authors'] == ['Doe, Jane', 'Smith, John']
    assert len(b.post('/api/v1/papers/import/batch-preview', json={'value':raw}, headers=h).json()['items'][0]['duplicates']) == 0
    assert len(a.get('/api/v1/papers').json()['items']) == 1
    assert a.post('/api/v1/papers', json=entries[0]['paper'], headers=h).status_code == 409
    assert a.post('/api/v1/papers', json=entries[2]['paper'], headers=h).status_code == 201


def test_batch_invalid_is_rejected_without_partial_import(clients):
    a, _ = clients
    h = {'X-Requested-With': 'zhiyan'}
    for value in ['@article{a,title={One}}\n@article{b,title={Broken}', '@article{a,title={One}}\n@book{a,title={Two}}', '@article{a,author={No title}}', '\n'.join(f'@article{{k{i},title={{T{i}}}}}' for i in range(51))]:
        assert a.post('/api/v1/papers/import/batch-preview', json={'value':value}, headers=h).status_code == 422
    assert a.get('/api/v1/papers').json()['items'] == []
