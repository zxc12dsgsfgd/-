from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import current_session, get_db, now
from app.knowledge import snapshot
from app.models import Card, CardVersion, Draft, EvidenceChange, EvidenceLink, Paper

router = APIRouter(prefix='/api/v1', tags=['evidence'])
ParentKind = Literal['cards', 'drafts']


class EvidenceFields(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    location: str = Field(default='', max_length=200)
    excerpt: str = Field(default='', max_length=20000)
    note: str = Field(default='', max_length=20000)


class EvidenceCreate(EvidenceFields):
    source_type: Literal['paper', 'card']
    source_id: int = Field(ge=1)


def parent_owned(kind, id, owner, db, lock=False):
    model = Card if kind == 'cards' else Draft
    query = select(model).where(model.id == id, model.owner_id == owner)
    if model is Card:
        query = query.where(Card.deleted_at.is_(None))
    if lock:
        query = query.with_for_update()
    obj = db.scalar(query)
    if obj is None:
        raise HTTPException(404, '对象不存在')
    return obj


def link_query(kind, parent_id, owner):
    parent_col = EvidenceLink.card_id if kind == 'cards' else EvidenceLink.draft_id
    return select(EvidenceLink).where(parent_col == parent_id, EvidenceLink.owner_id == owner)


def link_view(link, db):
    model = Paper if link.source_type == 'paper' else Card
    query = select(model.id).where(model.id == link.source_id, model.owner_id == link.owner_id)
    query = query.where(model.deleted_at.is_(None))
    available = db.scalar(query) is not None
    return {'id': link.id, 'source_type': link.source_type, 'source_id': link.source_id,
            'source_snapshot': link.source_snapshot, 'location': link.location,
            'excerpt': link.excerpt, 'note': link.note, 'removed_at': link.removed_at,
            'status': 'removed' if link.removed_at else 'available' if available else 'unavailable',
            'created_at': link.created_at}


def record(link, action, db):
    db.add(EvidenceChange(owner_id=link.owner_id, link_id=link.id, action=action, detail={
        'source_type': link.source_type, 'source_id': link.source_id, 'source_snapshot': link.source_snapshot,
        'location': link.location, 'excerpt': link.excerpt, 'note': link.note}))


def touch_parent(parent, db):
    if isinstance(parent, Card):
        if parent.verification_status == 'user_checked':
            parent.verification_status = 'pending'
        parent.version += 1
        db.add(CardVersion(owner_id=parent.owner_id, card_id=parent.id, version=parent.version, snapshot=snapshot(parent)))
    else:
        parent.status = 'draft'


@router.get('/{kind}/{parent_id}/evidence')
def list_evidence(kind: ParentKind, parent_id: int, current=Depends(current_session), db: Session = Depends(get_db)):
    parent_owned(kind, parent_id, current[1].id, db)
    links = db.scalars(link_query(kind, parent_id, current[1].id).order_by(EvidenceLink.id)).all()
    return [link_view(link, db) for link in links]


@router.post('/{kind}/{parent_id}/evidence', status_code=201)
def add_evidence(kind: ParentKind, parent_id: int, data: EvidenceCreate, current=Depends(current_session), db: Session = Depends(get_db)):
    owner = current[1].id
    parent = parent_owned(kind, parent_id, owner, db, True)
    if kind == 'cards' and data.source_type == 'card' and data.source_id == parent_id:
        raise HTTPException(422, '卡片不能关联自身')
    model = Paper if data.source_type == 'paper' else Card
    query = select(model).where(model.id == data.source_id, model.owner_id == owner)
    query = query.where(model.deleted_at.is_(None))
    source = db.scalar(query.with_for_update())
    if source is None:
        raise HTTPException(404, '来源不存在')
    parent_col = EvidenceLink.card_id if kind == 'cards' else EvidenceLink.draft_id
    active = db.scalar(select(func.count()).select_from(EvidenceLink).where(parent_col == parent_id, EvidenceLink.owner_id == owner, EvidenceLink.removed_at.is_(None)))
    if active >= 50:
        raise HTTPException(422, '每个对象最多关联 50 条来源')
    source_snapshot = {'title': source.title}
    if data.source_type == 'paper':
        source_snapshot.update({'doi': source.doi, 'source_url': source.source_url})
    link = EvidenceLink(owner_id=owner, **({'card_id': parent_id} if kind == 'cards' else {'draft_id': parent_id}),
                        source_type=data.source_type, source_id=data.source_id, source_snapshot=source_snapshot,
                        **data.model_dump(exclude={'source_type', 'source_id'}))
    db.add(link); db.flush(); record(link, 'created', db); touch_parent(parent, db); db.commit(); db.refresh(link)
    return link_view(link, db)


def active_link(kind, parent_id, link_id, owner, db):
    link = db.scalar(link_query(kind, parent_id, owner).where(EvidenceLink.id == link_id).with_for_update())
    if link is None or link.removed_at is not None:
        raise HTTPException(404, '来源关联不存在')
    return link


@router.put('/{kind}/{parent_id}/evidence/{link_id}')
def edit_evidence(kind: ParentKind, parent_id: int, link_id: int, data: EvidenceFields, current=Depends(current_session), db: Session = Depends(get_db)):
    owner = current[1].id
    parent = parent_owned(kind, parent_id, owner, db, True)
    link = active_link(kind, parent_id, link_id, owner, db)
    for field, value in data.model_dump().items():
        setattr(link, field, value)
    record(link, 'updated', db); touch_parent(parent, db); db.commit(); db.refresh(link)
    return link_view(link, db)


@router.delete('/{kind}/{parent_id}/evidence/{link_id}', status_code=204)
def remove_evidence(kind: ParentKind, parent_id: int, link_id: int, current=Depends(current_session), db: Session = Depends(get_db)):
    owner = current[1].id
    parent = parent_owned(kind, parent_id, owner, db, True)
    link = active_link(kind, parent_id, link_id, owner, db)
    link.removed_at = now(); record(link, 'removed', db); touch_parent(parent, db); db.commit()
    return Response(status_code=204)


@router.get('/{kind}/{parent_id}/evidence/{link_id}/history')
def history(kind: ParentKind, parent_id: int, link_id: int, current=Depends(current_session), db: Session = Depends(get_db)):
    owner = current[1].id
    parent_owned(kind, parent_id, owner, db)
    link = db.scalar(link_query(kind, parent_id, owner).where(EvidenceLink.id == link_id))
    if link is None:
        raise HTTPException(404, '来源关联不存在')
    changes = db.scalars(select(EvidenceChange).where(EvidenceChange.link_id == link_id, EvidenceChange.owner_id == owner).order_by(EvidenceChange.id)).all()
    return [{'action': item.action, 'detail': item.detail, 'created_at': item.created_at} for item in changes]
