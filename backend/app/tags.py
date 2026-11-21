import unicodedata
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.auth import current_session, get_db
from app.models import Card, CardTag, Paper, PaperTag, Tag, Workflow

router=APIRouter(prefix='/api/v1',tags=['tags'])
class TagIn(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    name:str=Field(min_length=1,max_length=100)

def norm(name): return unicodedata.normalize('NFKC',name).strip().casefold()
def tag_owned(id,user,db):
    t=db.scalar(select(Tag).where(Tag.id==id,Tag.owner_id==user))
    if not t: raise HTTPException(404,'标签不存在')
    return t
def save(db):
    try: db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'标签名称已存在或关联已变化') from None

@router.get('/tags')
def list_tags(current=Depends(current_session),db:Session=Depends(get_db)):
    return [{'id':t.id,'name':t.name} for t in db.scalars(select(Tag).where(Tag.owner_id==current[1].id).order_by(Tag.name,Tag.id))]

@router.post('/tags',status_code=201)
def create_tag(data:TagIn,current=Depends(current_session),db:Session=Depends(get_db)):
    n=norm(data.name)
    if not n or len(n)>300: raise HTTPException(422,'标签名称无效')
    t=Tag(owner_id=current[1].id,name=data.name,name_norm=n);db.add(t);save(db);db.refresh(t);return {'id':t.id,'name':t.name}

@router.put('/tags/{tag_id}')
def rename_tag(tag_id:int,data:TagIn,current=Depends(current_session),db:Session=Depends(get_db)):
    t=tag_owned(tag_id,current[1].id,db);n=norm(data.name)
    if not n or len(n)>300: raise HTTPException(422,'标签名称无效')
    t.name=data.name;t.name_norm=n;save(db);return {'id':t.id,'name':t.name}

@router.delete('/tags/{tag_id}',status_code=204)
def delete_tag(tag_id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    t=tag_owned(tag_id,current[1].id,db)
    if db.scalar(select(Workflow.id).where(Workflow.owner_id==current[1].id,Workflow.action_type=='add_tag',Workflow.action_value==str(tag_id)).limit(1)):
        raise HTTPException(409,'请先修改或删除引用此标签的规则')
    db.execute(delete(PaperTag).where(PaperTag.tag_id==t.id));db.execute(delete(CardTag).where(CardTag.tag_id==t.id));db.delete(t);db.commit();return Response(status_code=204)

def resource(kind,id,user,db):
    model=Paper if kind=='papers' else Card
    query=select(model).where(model.id==id,model.owner_id==user)
    query=query.where(model.deleted_at.is_(None))
    obj=db.scalar(query.with_for_update())
    if not obj: raise HTTPException(404,'资源不存在')
    return obj

@router.get('/{kind}/{resource_id}/tags')
def resource_tags(kind:str,resource_id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    if kind not in ('papers','cards'): raise HTTPException(404)
    resource(kind,resource_id,current[1].id,db); link=PaperTag if kind=='papers' else CardTag; col=link.paper_id if kind=='papers' else link.card_id
    return [{'id':t.id,'name':t.name} for t in db.scalars(select(Tag).join(link,link.tag_id==Tag.id).where(col==resource_id,Tag.owner_id==current[1].id).order_by(Tag.name))]

@router.post('/{kind}/{resource_id}/tags/{tag_id}',status_code=204)
def add_tag(kind:str,resource_id:int,tag_id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    if kind not in ('papers','cards'): raise HTTPException(404)
    resource(kind,resource_id,current[1].id,db);tag_owned(tag_id,current[1].id,db)
    link=PaperTag if kind=='papers' else CardTag; key={'paper_id' if kind=='papers' else 'card_id':resource_id,'tag_id':tag_id}
    if not db.get(link,(resource_id,tag_id)): db.add(link(**key));save(db)
    return Response(status_code=204)

@router.delete('/{kind}/{resource_id}/tags/{tag_id}',status_code=204)
def remove_tag(kind:str,resource_id:int,tag_id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    if kind not in ('papers','cards'): raise HTTPException(404)
    resource(kind,resource_id,current[1].id,db);tag_owned(tag_id,current[1].id,db)
    link=PaperTag if kind=='papers' else CardTag; obj=db.get(link,(resource_id,tag_id))
    if obj: db.delete(obj);db.commit()
    return Response(status_code=204)
