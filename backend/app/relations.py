from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.auth import current_session, get_db
from app.models import Card, CardRelation

router=APIRouter(prefix='/api/v1',tags=['relations'])
class RelationIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source_card_id:int=Field(ge=1)
    target_card_id:int=Field(ge=1)
    relation_type:Literal['related','supports','contradicts','extends']

@router.post('/card-relations',status_code=201)
def create_relation(data:RelationIn,current=Depends(current_session),db:Session=Depends(get_db)):
    if data.source_card_id==data.target_card_id:raise HTTPException(422,'不能关联同一张卡片')
    ids=sorted([data.source_card_id,data.target_card_id])
    cards=db.scalars(select(Card).where(Card.id.in_(ids),Card.owner_id==current[1].id,Card.deleted_at.is_(None)).order_by(Card.id).with_for_update()).all()
    if len(cards)!=2:raise HTTPException(404,'卡片不存在')
    relation=CardRelation(owner_id=current[1].id,**data.model_dump());db.add(relation)
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,'关系已存在') from None
    db.refresh(relation);return {'id':relation.id,**data.model_dump()}

@router.delete('/card-relations/{relation_id}',status_code=204)
def delete_relation(relation_id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    r=db.scalar(select(CardRelation).where(CardRelation.id==relation_id,CardRelation.owner_id==current[1].id))
    if not r:raise HTTPException(404,'关系不存在')
    active=db.scalar(select(Card.id).where(Card.id.in_([r.source_card_id,r.target_card_id]),Card.owner_id==current[1].id,Card.deleted_at.is_not(None)).limit(1))
    if active:raise HTTPException(404,'关系不存在')
    db.delete(r);db.commit();return Response(status_code=204)

@router.get('/graph')
def graph(current=Depends(current_session),db:Session=Depends(get_db)):
    rows=db.scalars(select(Card).where(Card.owner_id==current[1].id,Card.deleted_at.is_(None)).order_by(Card.id.desc()).limit(201)).all()
    truncated=len(rows)>200;rows=rows[:200];ids=[c.id for c in rows]
    links=db.scalars(select(CardRelation).where(CardRelation.owner_id==current[1].id,CardRelation.source_card_id.in_(ids),CardRelation.target_card_id.in_(ids)).limit(501)).all()
    edge_truncated=len(links)>500
    return {'nodes':[{'id':c.id,'title':c.title,'type':c.type} for c in rows], 'edges':[{'id':r.id,'source':r.source_card_id,'target':r.target_card_id,'type':r.relation_type} for r in links[:500]],'truncated':truncated or edge_truncated}
