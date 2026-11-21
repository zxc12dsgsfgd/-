from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.auth import current_session, get_db
from app.auth import now
from app.models import Card, CardRelation, CardTag, CardVersion, EvidenceChange, EvidenceLink, Paper, PaperNote, Tag
from app.papers import owned
from app.workflows import emit

router = APIRouter(prefix='/api/v1', tags=['knowledge'])
Kind = Literal['concept','method','conclusion','question','idea','other']


class NoteIn(BaseModel):
    content: str = Field(min_length=1, max_length=60000)


class CardIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=500)
    type: Kind
    content: str = Field(min_length=1, max_length=60000)
    content_kind: Literal['unspecified', 'interpretation', 'ai_suggestion', 'conclusion'] = 'unspecified'
    verification_status: Literal['pending', 'user_checked', 'doubtful', 'deprecated'] = 'pending'
    paper_id: int | None = Field(default=None, ge=1)
    source_page: int | None = Field(default=None, ge=1)
    source_excerpt: str | None = Field(default=None, max_length=60000)
    note: str | None = Field(default=None, max_length=60000)


class CardUpdate(CardIn):
    version: int = Field(ge=1)


class CardOut(CardIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    version: int
    source_title_snapshot: str | None
    source_state: Literal['none', 'linked', 'detached', 'unavailable']
    created_at: datetime
    updated_at: datetime


def lock_paper(paper_id, user_id, db):
    paper = db.scalar(select(Paper).where(Paper.id==paper_id, Paper.owner_id==user_id, Paper.deleted_at.is_(None)).with_for_update())
    if not paper: raise HTTPException(404,'文献不存在')
    return paper


def card_owned(card_id, user_id, db):
    card = db.scalar(select(Card).where(Card.id==card_id, Card.owner_id==user_id, Card.deleted_at.is_(None)))
    if not card: raise HTTPException(404,'卡片不存在')
    return card


def snapshot(card):
    return {k:getattr(card,k) for k in ('title','type','content','content_kind','verification_status','paper_id','source_title_snapshot','source_state','source_page','source_excerpt','note')}


@router.get('/papers/{paper_id}/notes')
def notes(paper_id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    owned(paper_id,current[1].id,db)
    rows=db.scalars(select(PaperNote).where(PaperNote.paper_id==paper_id,PaperNote.owner_id==current[1].id).order_by(PaperNote.id.desc())).all()
    return [{'id':n.id,'content':n.content,'created_at':n.created_at,'updated_at':n.updated_at} for n in rows]


@router.post('/papers/{paper_id}/notes',status_code=201)
def create_note(paper_id:int,data:NoteIn,current=Depends(current_session),db:Session=Depends(get_db)):
    lock_paper(paper_id,current[1].id,db)
    n=PaperNote(owner_id=current[1].id,paper_id=paper_id,content=data.content);db.add(n);db.commit();db.refresh(n)
    return {'id':n.id,'content':n.content,'created_at':n.created_at,'updated_at':n.updated_at}


@router.put('/notes/{note_id}')
def update_note(note_id:int,data:NoteIn,current=Depends(current_session),db:Session=Depends(get_db)):
    n=db.scalar(select(PaperNote).join(Paper,Paper.id==PaperNote.paper_id).where(PaperNote.id==note_id,PaperNote.owner_id==current[1].id,Paper.owner_id==current[1].id,Paper.deleted_at.is_(None)))
    if not n: raise HTTPException(404,'笔记不存在')
    n.content=data.content;db.commit();return {'id':n.id,'content':n.content}


@router.delete('/notes/{note_id}',status_code=204)
def delete_note(note_id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    n=db.scalar(select(PaperNote).join(Paper,Paper.id==PaperNote.paper_id).where(PaperNote.id==note_id,PaperNote.owner_id==current[1].id,Paper.owner_id==current[1].id,Paper.deleted_at.is_(None)))
    if not n: raise HTTPException(404,'笔记不存在')
    db.delete(n);db.commit();return Response(status_code=204)


@router.get('/cards')
def cards(q:str=Query(default='',max_length=200), type:Kind|None=None, paper_id:int|None=Query(default=None,ge=1), tag_id:int|None=Query(default=None,ge=1), limit:int=Query(default=20,ge=1,le=100), before_id:int|None=Query(default=None,ge=1),current=Depends(current_session),db:Session=Depends(get_db)):
    stmt=select(Card).where(Card.owner_id==current[1].id, Card.deleted_at.is_(None))
    if tag_id: stmt=stmt.join(CardTag,CardTag.card_id==Card.id).join(Tag,Tag.id==CardTag.tag_id).where(Tag.id==tag_id,Tag.owner_id==current[1].id)
    if q: stmt=stmt.where(Card.title.contains(q,autoescape=True) | Card.content.contains(q,autoescape=True))
    if type: stmt=stmt.where(Card.type==type)
    if paper_id: stmt=stmt.where(Card.paper_id==paper_id)
    if before_id: stmt=stmt.where(Card.id<before_id)
    rows=db.scalars(stmt.order_by(Card.id.desc()).limit(limit+1)).all()
    return {'items':[CardOut.model_validate(c) for c in rows[:limit]],'next_cursor':rows[limit-1].id if len(rows)>limit else None}


@router.post('/cards',response_model=CardOut,status_code=201)
def create_card(data:CardIn,current=Depends(current_session),db:Session=Depends(get_db)):
    paper=lock_paper(data.paper_id,current[1].id,db) if data.paper_id else None
    c=Card(owner_id=current[1].id,source_title_snapshot=paper.title if paper else None,source_state='linked' if paper else 'none',version=1,**data.model_dump())
    db.add(c);db.flush();db.add(CardVersion(owner_id=c.owner_id,card_id=c.id,version=1,snapshot=snapshot(c)));emit(db,c.owner_id,'card_created',c.id,c.type);db.commit();db.refresh(c);return c


@router.get('/cards/{card_id}',response_model=CardOut)
def get_card(card_id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    return card_owned(card_id,current[1].id,db)


@router.put('/cards/{card_id}',response_model=CardOut)
def update_card(card_id:int,data:CardUpdate,current=Depends(current_session),db:Session=Depends(get_db)):
    if data.paper_id: paper=lock_paper(data.paper_id,current[1].id,db)
    else: paper=None
    card=card_owned(card_id,current[1].id,db)
    values=data.model_dump(exclude={'version'})
    for field in ('content_kind', 'verification_status'):
        if field not in data.model_fields_set: values[field]=getattr(card,field)
    values['source_title_snapshot']=paper.title if paper else card.source_title_snapshot
    values['source_state']='linked' if paper else ('detached' if card.paper_id else card.source_state)
    evidence_fields=('content','content_kind','paper_id','source_page','source_excerpt','note')
    if values['verification_status']=='user_checked' and any(values[field]!=getattr(card,field) for field in evidence_fields):
        values['verification_status']='pending'
    values['version']=data.version+1
    result=db.execute(update(Card).where(Card.id==card_id,Card.owner_id==current[1].id,Card.deleted_at.is_(None),Card.version==data.version).values(**values))
    if result.rowcount!=1: db.rollback();raise HTTPException(409,'卡片已被修改，请刷新后重试')
    db.flush(); c=card_owned(card_id,current[1].id,db); db.refresh(c)
    db.add(CardVersion(owner_id=c.owner_id,card_id=c.id,version=c.version,snapshot=snapshot(c)));db.commit();db.refresh(c);return c


@router.get('/cards/{card_id}/versions')
def versions(card_id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    card_owned(card_id,current[1].id,db)
    rows=db.scalars(select(CardVersion).where(CardVersion.card_id==card_id,CardVersion.owner_id==current[1].id).order_by(CardVersion.version.desc())).all()
    return [{'version':v.version,'snapshot':v.snapshot,'created_at':v.created_at} for v in rows]


@router.delete('/cards/{card_id}',status_code=204)
def delete_card(card_id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    c=db.scalar(select(Card).where(Card.id==card_id,Card.owner_id==current[1].id,Card.deleted_at.is_(None)).with_for_update())
    if not c: raise HTTPException(404,'卡片不存在')
    c.deleted_at=now();db.commit();return Response(status_code=204)
