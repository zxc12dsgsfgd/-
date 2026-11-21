import http.client
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import quote, urlsplit, urlunsplit

from fastapi import HTTPException
from app.ai_worker import PinnedHTTPS


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values = {}
        self.title = []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            key = (attrs.get('name') or attrs.get('property') or '').lower()
            value = (attrs.get('content') or '').strip()
            if key and value:
                self.values.setdefault(key, []).append(value)
        elif tag == 'title':
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)


def resolve_link(value: str) -> dict:
    value = value.strip()
    try:
        if len(value) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('url')
        parts = urlsplit(value)
        if parts.scheme != 'https' or not parts.hostname or parts.username is not None or parts.password is not None or parts.port not in (None, 443) or parts.fragment:
            raise ValueError('url')
        host = parts.hostname.encode('idna').decode('ascii')
        if host.endswith('.local') or host in ('localhost', 'localhost.localdomain'):
            raise ValueError('url')
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        ips = {entry[4][0] for entry in answers}
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise ValueError('url')
        path = quote(parts.path or '/', safe="/%:@!$&'()*+,;=-._~")
        if parts.query:
            path += '?' + quote(parts.query, safe="/%?:@!$&'()*+,;=-._~")
        conn = PinnedHTTPS(host, sorted(ips)[0], 8)
        try:
            conn.request('GET', path, headers={'Accept':'text/html', 'Accept-Encoding':'identity', 'User-Agent':'ZhiyanMetadata/1.0'})
            response = conn.getresponse()
            if response.status < 200 or response.status >= 300:
                raise ValueError('status')
            if response.headers.get_content_type() not in ('text/html', 'application/xhtml+xml'):
                raise ValueError('type')
            charset = response.headers.get_content_charset() or 'utf-8'
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError('size')
        finally:
            conn.close()
        parser = Metadata()
        parser.feed(raw.decode(charset, errors='replace'))
        meta = parser.values
        def first(*keys):
            return next((meta[k][0] for k in keys if meta.get(k)), None)
        title = first('citation_title', 'dc.title', 'og:title', 'twitter:title') or ''.join(parser.title).strip()
        if not title:
            raise ValueError('title')
        date = first('citation_publication_date', 'citation_date', 'dc.date', 'article:published_time') or ''
        match = re.search(r'\b(?:1\d{3}|2\d{3})\b', date)
        return {'title': title, 'authors': meta.get('citation_author', meta.get('dc.creator', [])), 'year': int(match.group()) if match else None,
                'doi': first('citation_doi', 'dc.identifier.doi'), 'venue': first('citation_journal_title', 'citation_conference_title'),
                'abstract': first('citation_abstract', 'dc.description', 'description', 'og:description'),
                'source_url': urlunsplit(parts), 'bibtex': None, 'status': 'unread'}
    except (ValueError, OSError, LookupError, UnicodeError, OverflowError, http.client.HTTPException):
        raise HTTPException(422, '链接无法安全解析：请使用可直接访问的 HTTPS 网页，或手动填写文献') from None
