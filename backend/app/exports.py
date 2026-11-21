from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_session, get_db
from app.models import Card, Draft, Paper

router = APIRouter(prefix='/api/v1', tags=['exports'])


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    format: Literal['markdown', 'latex', 'bibtex']
    card_ids: list[int] = Field(default_factory=list, max_length=50)
    draft_id: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def selection(self):
        if bool(self.card_ids) == bool(self.draft_id) or any(i < 1 for i in self.card_ids) or len(set(self.card_ids)) != len(self.card_ids):
            raise ValueError('请选择卡片或单个草稿，卡片编号不能重复')
        return self


def tex(value):
    replacements = {'\\': r'\textbackslash{}', '{': r'\{', '}': r'\}', '$': r'\$', '&': r'\&', '#': r'\#', '%': r'\%', '_': r'\_', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}'}
    return ''.join(replacements.get(char, char) for char in str(value or ''))


def bibtex(references):
    entries = []
    for index, ref in enumerate(references, 1):
        fields = [('title', ref.get('title')), ('author', ' and '.join(ref.get('authors') or [])), ('year', ref.get('year')), ('doi', ref.get('doi')), ('howpublished', ref.get('venue'))]
        lines = [f'@misc{{source{index},']
        lines += [f'  {key} = {{{tex(value)}}},' for key, value in fields if value]
        entries.append('\n'.join(lines + ['}']))
    return '\n\n'.join(entries) + ('\n' if entries else '')


@router.post('/exports')
def export(data: ExportRequest, current=Depends(current_session), db: Session = Depends(get_db)):
    owner = current[1].id
    references = []
    if data.draft_id:
        draft = db.scalar(select(Draft).where(Draft.owner_id == owner, Draft.id == data.draft_id))
        if not draft:
            raise HTTPException(404, '草稿不存在')
        sections = [(draft.title, draft.content, None, None, None, None)]
        # Only paper snapshots contain actual bibliographic metadata. Card snapshots
        # retain their own title and source details, but do not invent a paper.
        references = [s for s in draft.sources if s.get('type') == 'paper']
        card_sources = [s for s in draft.sources if s.get('type') == 'card']
        for source in card_sources:
            sections.append((f"来源卡片：{source.get('title', '')}", source.get('content') or '', source.get('source_title'), source.get('source_page'), source.get('source_excerpt'), source.get('note')))
    else:
        cards = db.scalars(select(Card).where(Card.owner_id == owner, Card.deleted_at.is_(None), Card.id.in_(data.card_ids))).all()
        if len(cards) != len(data.card_ids):
            raise HTTPException(404, '卡片不存在')
        by_id = {c.id: c for c in cards}
        cards = [by_id[i] for i in data.card_ids]
        sections = [(c.title, c.content, c.source_title_snapshot, c.source_page, c.source_excerpt, c.note) for c in cards]
        ids = {c.paper_id for c in cards if c.paper_id}
        papers = db.scalars(select(Paper).where(Paper.owner_id == owner, Paper.deleted_at.is_(None), Paper.id.in_(ids)).order_by(Paper.id)).all()
        references = [{'title': p.title, 'authors': p.authors, 'year': p.year, 'doi': p.doi, 'venue': p.venue} for p in papers]
    if data.format == 'bibtex':
        result, filename = bibtex(references), 'references.bib'
    elif data.format == 'latex':
        parts = [r'\documentclass{article}', r'\usepackage{ctex}', r'\begin{document}']
        for title, content, source, page, excerpt, note in sections:
            parts += [r'\section*{' + tex(title) + '}', tex(content)]
            for label, value in [('来源', source), ('页码', page), ('摘录', excerpt), ('备注', note)]:
                if value: parts.append(tex(label) + '：' + tex(value))
        if references:
            parts.append(r'\section*{参考文献}')
            parts.extend(tex(f"[{i}] " + '，'.join(str(x) for x in [r.get('title'), ', '.join(r.get('authors') or []), r.get('year'), r.get('doi')] if x)) + r'\\' for i, r in enumerate(references, 1))
        result, filename = '\n\n'.join(parts + [r'\end{document}']) + '\n', 'export.tex'
    else:
        parts = []
        for title, content, source, page, excerpt, note in sections:
            parts.append(f'## {title}\n\n{content}')
            parts.extend(f'{label}：{value}' for label, value in [('来源', source), ('页码', page), ('摘录', excerpt), ('备注', note)] if value)
        if references:
            parts.append('## 参考文献')
            parts.extend(f"{i}. " + '，'.join(str(x) for x in [r.get('title'), ', '.join(r.get('authors') or []), r.get('year'), r.get('doi')] if x) for i, r in enumerate(references, 1))
        result, filename = '\n\n'.join(parts) + '\n', 'export.md'
    return Response(result, media_type='text/plain; charset=utf-8', headers={'Content-Disposition': f'attachment; filename="{filename}"', 'Cache-Control': 'no-store'})
