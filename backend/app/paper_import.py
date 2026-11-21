import re
import unicodedata
from urllib.parse import quote

import bibtexparser
import httpx
from fastapi import HTTPException
from bibtexparser.bibdatabase import BibDatabase


def normalize_doi(value: str | None) -> str:
    value = (value or '').strip()
    value = re.sub(r'^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)', '', value, flags=re.I)
    return value.strip().casefold()


def normalize_title(value: str) -> str:
    return ' '.join(unicodedata.normalize('NFKC', value).split()).casefold()


def parse_bibtex(raw: str) -> dict:
    try:
        database = bibtexparser.loads(raw)
    except Exception:
        raise HTTPException(422, 'BibTeX 无法解析，请检查格式或手动填写') from None
    if len(database.entries) != 1 or not database.entries[0].get('title'):
        raise HTTPException(422, '请提供一条含标题的 BibTeX 记录')
    entry = database.entries[0]
    year = entry.get('year', '').strip()
    return {'title': entry['title'], 'authors': [s.strip() for s in re.split(r'\s+and\s+', entry.get('author', ''), flags=re.I) if s.strip()],
            'year': int(year) if year.isdigit() and 1 <= int(year) <= 9999 else None,
            'doi': entry.get('doi') or None, 'venue': entry.get('journal') or entry.get('booktitle') or None,
            'abstract': entry.get('abstract') or None, 'source_url': entry.get('url') or None,
            'bibtex': raw, 'status': 'unread'}


def parse_bibtex_batch(raw: str) -> list[dict]:
    try:
        database = bibtexparser.loads(raw)
        # bibtexparser treats unparsed malformed entries as comments.
        if any(re.search(r'@\s*(?!comment\b|preamble\b|string\b)[a-z]+\s*[({]', comment, re.I) for comment in database.comments):
            raise ValueError('malformed entry')
        if not 1 <= len(database.entries) <= 50:
            raise ValueError('entry count')
        if len({entry['ID'] for entry in database.entries}) != len(database.entries):
            raise ValueError('duplicate keys')
        result = []
        for entry in database.entries:
            single = BibDatabase()
            single.entries = [entry]
            result.append(parse_bibtex(bibtexparser.dumps(single)))
        return result
    except Exception:
        raise HTTPException(422, '批量 BibTeX 无法完整解析；请检查格式、标题、重复引用键，且每次最多 50 条') from None


def resolve_doi(value: str) -> dict:
    doi = normalize_doi(value)
    if not re.fullmatch(r'10\.\d{4,9}/\S{1,480}', doi):
        raise HTTPException(422, '请输入有效 DOI 或 doi.org 链接')
    try:
        # A fixed host and disabled redirects prevent user-controlled fetch targets.
        response = httpx.get('https://api.crossref.org/works/' + quote(doi, safe=''), timeout=10, follow_redirects=False, trust_env=False)
        response.raise_for_status()
        item = response.json()['message']
        title = item.get('title', [None])[0]
        if not title:
            raise ValueError('missing title')
        date = item.get('published', {}).get('date-parts', [[]])[0]
        return {'title': title, 'authors': [' '.join(filter(None, [a.get('given'), a.get('family')])) or a.get('name', '') for a in item.get('author', [])],
                'year': date[0] if date else None, 'doi': item.get('DOI', doi),
                'venue': (item.get('container-title') or [None])[0], 'abstract': None,
                'source_url': 'https://doi.org/' + quote(doi, safe='/'), 'bibtex': None, 'status': 'unread'}
    except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError):
        raise HTTPException(502, 'DOI 解析失败，请检查 DOI 或手动填写') from None
