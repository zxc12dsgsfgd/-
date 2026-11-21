from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import current_session, get_db
from app.models import Card, CardVersion, Paper, PaperFile, PaperNote, PaperStatusEvent, PaperTag, ReadingPlanItem, Tag, User
from app.auth import now
from app.paper_import import normalize_doi, normalize_title, parse_bibtex, parse_bibtex_batch, resolve_doi
from app.link_import import resolve_link
from app.workflows import emit

router = APIRouter(prefix="/api/v1/papers", tags=["papers"])
Status = Literal["unread", "reading", "read", "archived"]


class PaperInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=500)
    authors: list[str] = Field(default_factory=list, max_length=100)
    year: int | None = Field(default=None, ge=1, le=9999)
    doi: str | None = Field(default=None, max_length=512)
    venue: str | None = Field(default=None, max_length=500)
    abstract: str | None = Field(default=None, max_length=60000)
    source_url: str | None = Field(default=None, max_length=2048)
    bibtex: str | None = Field(default=None, max_length=60000)
    status: Status = "unread"

    @field_validator("authors")
    @classmethod
    def validate_authors(cls, value):
        if any(not name.strip() or len(name) > 200 for name in value):
            raise ValueError("作者名称不能为空且不得超过 200 字符")
        return [name.strip() for name in value]


class PaperOutput(PaperInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


class ImportPreview(BaseModel):
    kind: Literal['bibtex', 'doi', 'link']
    value: str = Field(min_length=1, max_length=60000)


class BatchPreview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    value: str = Field(min_length=1, max_length=60000)


def duplicates(data: PaperInput, owner_id: int, db: Session):
    # Existing records predate normalized columns; compare within the owner's library.
    doi = normalize_doi(data.doi)
    title = normalize_title(data.title)
    existing = db.scalars(select(Paper).where(Paper.owner_id == owner_id, Paper.deleted_at.is_(None))).all()
    return [p for p in existing if (normalize_doi(p.doi) == doi if doi else normalize_title(p.title) == title)]


@router.post('/import/preview')
def preview_import(data: ImportPreview, current=Depends(current_session), db: Session = Depends(get_db)):
    parsed = parse_bibtex(data.value) if data.kind == 'bibtex' else resolve_doi(data.value) if data.kind == 'doi' else resolve_link(data.value)
    try:
        candidate = PaperInput.model_validate(parsed)
    except ValueError:
        raise HTTPException(422, '解析结果不符合字段限制，请手动填写') from None
    matches = duplicates(candidate, current[1].id, db)
    return {'paper': candidate.model_dump(), 'duplicates': [{'id': p.id, 'title': p.title, 'doi': p.doi} for p in matches[:20]]}


@router.post('/import/batch-preview')
def batch_preview(data: BatchPreview, current=Depends(current_session), db: Session = Depends(get_db)):
    try:
        candidates = [PaperInput.model_validate(item) for item in parse_bibtex_batch(data.value)]
    except ValueError:
        raise HTTPException(422, '某条记录不符合字段限制，请修改后重试') from None
    existing = db.scalars(select(Paper).where(Paper.owner_id == current[1].id, Paper.deleted_at.is_(None))).all()
    result = []
    for index, candidate in enumerate(candidates):
        doi, title = normalize_doi(candidate.doi), normalize_title(candidate.title)
        matches = [p for p in existing if (normalize_doi(p.doi) == doi if doi else normalize_title(p.title) == title)]
        earlier = [i + 1 for i, other in enumerate(candidates[:index]) if (normalize_doi(other.doi) == doi if doi else normalize_title(other.title) == title)]
        result.append({'paper': candidate.model_dump(), 'duplicates': [{'id': p.id, 'title': p.title} for p in matches[:20]], 'batch_duplicates': earlier})
    return {'items': result}


def owned(paper_id: int, user_id: int, db: Session):
    paper = db.scalar(select(Paper).where(Paper.id == paper_id, Paper.owner_id == user_id, Paper.deleted_at.is_(None)))
    if paper is None:
        raise HTTPException(404, "文献不存在")
    return paper


@router.get("")
def list_papers(q: str = Query(default="", max_length=200), status: Status | None = None,
                tag_id: int | None = Query(default=None, ge=1),
                limit: int = Query(default=20, ge=1, le=100), before_id: int | None = Query(default=None, ge=1),
                current=Depends(current_session), db: Session = Depends(get_db)):
    query = select(Paper).where(Paper.owner_id == current[1].id, Paper.deleted_at.is_(None))
    if tag_id: query = query.join(PaperTag, PaperTag.paper_id==Paper.id).join(Tag,Tag.id==PaperTag.tag_id).where(Tag.id==tag_id,Tag.owner_id==current[1].id)
    if q:
        query = query.where(Paper.title.contains(q, autoescape=True))
    if status:
        query = query.where(Paper.status == status)
    if before_id:
        query = query.where(Paper.id < before_id)
    papers = db.scalars(query.order_by(Paper.id.desc()).limit(limit + 1)).all()
    return {"items": [PaperOutput.model_validate(p) for p in papers[:limit]],
            "next_cursor": papers[limit - 1].id if len(papers) > limit else None}


@router.post("", response_model=PaperOutput, status_code=201)
def create_paper(data: PaperInput, confirm_duplicate: bool = False, current=Depends(current_session), db: Session = Depends(get_db)):
    # Serialize duplicate checks and writes for each owner on MySQL.
    db.scalar(select(User.id).where(User.id == current[1].id).with_for_update())
    matches = duplicates(data, current[1].id, db)
    if matches and not confirm_duplicate:
        raise HTTPException(409, {'code': 'possible_duplicate', 'matches': [{'id': p.id, 'title': p.title, 'doi': p.doi} for p in matches[:20]]})
    paper = Paper(owner_id=current[1].id, **data.model_dump())
    db.add(paper); db.flush(); db.add(PaperStatusEvent(owner_id=paper.owner_id,paper_id=paper.id,to_status=paper.status,occurred_at=now())); emit(db,paper.owner_id,'paper_created',paper.id,paper.status); db.commit(); db.refresh(paper)
    return paper


@router.get("/{paper_id}", response_model=PaperOutput)
def get_paper(paper_id: int, current=Depends(current_session), db: Session = Depends(get_db)):
    return owned(paper_id, current[1].id, db)


@router.put("/{paper_id}", response_model=PaperOutput)
def update_paper(paper_id: int, data: PaperInput, current=Depends(current_session), db: Session = Depends(get_db)):
    paper = db.scalar(select(Paper).where(Paper.id == paper_id, Paper.owner_id == current[1].id, Paper.deleted_at.is_(None)).with_for_update())
    if paper is None: raise HTTPException(404, '文献不存在')
    old_status = paper.status
    for key, value in data.model_dump().items():
        setattr(paper, key, value)
    if old_status != paper.status:
        db.add(PaperStatusEvent(owner_id=paper.owner_id,paper_id=paper.id,to_status=paper.status,occurred_at=now()))
        emit(db,paper.owner_id,'paper_status_changed',paper.id,paper.status)
    db.commit(); db.refresh(paper)
    return paper


def move_paper_to_trash(paper, owner, db):
    paper.deleted_at=now()
    cards = db.scalars(select(Card).where(Card.paper_id == paper.id, Card.owner_id == owner).order_by(Card.id).with_for_update()).all()
    for card in cards:
        card.source_title_snapshot = paper.title
        card.source_state = 'unavailable'
        if card.verification_status == 'user_checked':
            card.verification_status = 'pending'
        card.version += 1
        snapshot = {k:getattr(card,k) for k in ('title','type','content','content_kind','verification_status','paper_id','source_title_snapshot','source_state','source_page','source_excerpt','note')}
        db.add(CardVersion(owner_id=card.owner_id,card_id=card.id,version=card.version,snapshot=snapshot))


@router.delete("/{paper_id}", status_code=204)
def delete_paper(paper_id: int, current=Depends(current_session), db: Session = Depends(get_db)):
    paper = db.scalar(select(Paper).where(Paper.id == paper_id, Paper.owner_id == current[1].id, Paper.deleted_at.is_(None)).with_for_update())
    if paper is None: raise HTTPException(404, '文献不存在')
    move_paper_to_trash(paper, current[1].id, db)
    db.commit()
    return Response(status_code=204)
