from email.message import Message
import socket

from test_papers import clients


def test_link_metadata_preview_and_duplicate(clients, monkeypatch):
    import app.link_import as link
    a, b = clients
    headers = {'X-Requested-With': 'zhiyan'}
    assert a.post('/api/v1/papers', json={'title':'Existing', 'doi':'10.1234/test'}, headers=headers).status_code == 201
    monkeypatch.setattr(link.socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))])
    class Response:
        status = 200
        headers = Message()
        headers['Content-Type'] = 'text/html; charset=utf-8'
        def read(self, n):
            return b'<title>Fallback</title><meta name="citation_title" content="Paper &amp; Data"><meta name="citation_author" content="A"><meta name="citation_author" content="B"><meta name="citation_publication_date" content="2024/01"><meta name="citation_doi" content="10.1234/test">'
    class Connection:
        def __init__(self, host, ip, timeout): assert ip == '8.8.8.8'
        def request(self, method, path, headers): assert method == 'GET' and path == '/paper?x=1'
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(link, 'PinnedHTTPS', Connection)
    body = {'kind':'link','value':'https://example.org/paper?x=1'}
    result = a.post('/api/v1/papers/import/preview', json=body, headers=headers)
    assert result.status_code == 200
    assert result.json()['paper']['title'] == 'Paper & Data'
    assert result.json()['paper']['authors'] == ['A','B'] and result.json()['paper']['year'] == 2024
    assert len(result.json()['duplicates']) == 1
    assert b.post('/api/v1/papers/import/preview', json=body, headers=headers).json()['duplicates'] == []


def test_link_rejects_private_mixed_dns_and_redirect(clients, monkeypatch):
    import app.link_import as link
    a, _ = clients
    headers = {'X-Requested-With':'zhiyan'}
    for url in ['http://example.org/', 'https://127.0.0.1/', 'https://user:password@example.org/', 'https://example.org:444/', 'https://example.org/#fragment']:
        monkeypatch.setattr(link.socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('127.0.0.1', 443))])
        assert a.post('/api/v1/papers/import/preview', json={'kind':'link','value':url}, headers=headers).status_code == 422
    monkeypatch.setattr(link.socket, 'getaddrinfo', lambda *a, **k: [(2,1,6,'',('8.8.8.8',443)), (2,1,6,'',('127.0.0.1',443))])
    assert a.post('/api/v1/papers/import/preview', json={'kind':'link','value':'https://example.org/'}, headers=headers).status_code == 422
    monkeypatch.setattr(link.socket, 'getaddrinfo', lambda *a, **k: [(2,1,6,'',('8.8.8.8',443))])
    class Redirect:
        status = 302
    class Connection:
        def __init__(self, *args): pass
        def request(self, *args, **kwargs): pass
        def getresponse(self): return Redirect()
        def close(self): pass
    monkeypatch.setattr(link, 'PinnedHTTPS', Connection)
    assert a.post('/api/v1/papers/import/preview', json={'kind':'link','value':'https://example.org/'}, headers=headers).status_code == 422
