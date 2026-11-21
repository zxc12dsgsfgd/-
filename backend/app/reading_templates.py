import unicodedata
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_session, get_db
from app.knowledge import lock_paper, snapshot
from app.models import Card, CardVersion, Paper, ReadingTemplate, StructuredNote
from app.workflows import emit

router=APIRouter(prefix='/api/v1',tags=['reading-templates'])
DEFAULT_FIELDS=['研究问题','研究背景','数据或实验材料','研究方法','主要结果','作者声称的贡献','研究局限','我的疑问','与当前课题的关系','可复用的观点或方法']


def normalize_labels(labels):
    normalized=[unicodedata.normalize('NFKC',label).strip() for label in labels]
    if any(not label or len(label)>100 for label in normalized) or len({label.casefold() for label in normalized})!=len(normalized):
        raise ValueError('字段名称不能为空、超过 100 字或重复')
    return normalized


class TemplateIn(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    name:str=Field(min_length=1,max_length=200)
    fields:list[str]=Field(min_length=1,max_length=20)
    @field_validator('fields')
    @classmethod
    def labels(cls,value):return normalize_labels(value)


class Entry(BaseModel):
    model_config=ConfigDict(extra='forbid')
    label:str=Field(min_length=1,max_length=100)
    value:str=Field(default='',max_length=20000)


class NoteIn(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    template_name:str=Field(min_length=1,max_length=200)
    fields:list[Entry]=Field(min_length=1,max_length=20)
    @field_validator('fields')
    @classmethod
    def labels(cls,value):
        labels=normalize_labels([entry.label for entry in value])
        if sum(len(entry.value) for entry in value)>100000:raise ValueError('笔记内容超过长度限制')
        for entry,label in zip(value,labels):entry.label=label
        return value


class ToCard(BaseModel):
    model_config=ConfigDict(extra='forbid')
    field_index:int=Field(ge=0,le=19)
    title:str=Field(min_length=1,max_length=500)
    type:Literal['concept','method','conclusion','question','idea','other']='idea'


def template_view(t):return {'id':t.id,'name':t.name,'fields':t.fields}
def note_view(n):return {'id':n.id,'paper_id':n.paper_id,'template_name':n.template_name,'fields':n.fields,'created_at':n.created_at,'updated_at':n.updated_at}
def template_owned(id,owner,db):
    t=db.scalar(select(ReadingTemplate).where(ReadingTemplate.id==id,ReadingTemplate.owner_id==owner).with_for_update())
    if not t:raise HTTPException(404,'模板不存在')
    return t
def note_owned(id,owner,db):
    n=db.scalar(select(StructuredNote).join(Paper,Paper.id==StructuredNote.paper_id).where(StructuredNote.id==id,StructuredNote.owner_id==owner,Paper.owner_id==owner,Paper.deleted_at.is_(None)).with_for_update())
    if not n:raise HTTPException(404,'阅读笔记不存在')
    return n


@router.get('/reading-templates')
def templates(current=Depends(current_session),db:Session=Depends(get_db)):
    return {'default':{'name':'结构化阅读','fields':DEFAULT_FIELDS},'custom':[template_view(t) for t in db.scalars(select(ReadingTemplate).where(ReadingTemplate.owner_id==current[1].id).order_by(ReadingTemplate.id.desc()))]}


@router.post('/reading-templates',status_code=201)
def create_template(data:TemplateIn,current=Depends(current_session),db:Session=Depends(get_db)):
    t=ReadingTemplate(owner_id=current[1].id,**data.model_dump());db.add(t);db.commit();db.refresh(t);return template_view(t)


@router.put('/reading-templates/{id}')
def update_template(id:int,data:TemplateIn,current=Depends(current_session),db:Session=Depends(get_db)):
    t=template_owned(id,current[1].id,db);t.name=data.name;t.fields=data.fields;db.commit();return template_view(t)


@router.delete('/reading-templates/{id}',status_code=204)
def delete_template(id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    db.delete(template_owned(id,current[1].id,db));db.commit();return Response(status_code=204)


@router.get('/structured-notes')
def search_notes(q:str=Query(default='',max_length=200),current=Depends(current_session),db:Session=Depends(get_db)):
    query=select(StructuredNote).join(Paper,Paper.id==StructuredNote.paper_id).where(StructuredNote.owner_id==current[1].id,Paper.owner_id==current[1].id,Paper.deleted_at.is_(None)).order_by(StructuredNote.id.desc())
    needle=q.casefold();results=[]
    for note in db.scalars(query).yield_per(100):
        if needle and not any(needle in (field.get('label','')+' '+field.get('value','')).casefold() for field in note.fields):continue
        results.append(note_view(note))
        if len(results)>100:break
    return {'items':results[:100],'truncated':len(results)>100}


@router.get('/papers/{paper_id}/structured-notes')
def paper_notes(paper_id:int,q:str=Query(default='',max_length=200),current=Depends(current_session),db:Session=Depends(get_db)):
    lock_paper(paper_id,current[1].id,db)
    needle=q.casefold()
    return [note_view(n) for n in db.scalars(select(StructuredNote).where(StructuredNote.paper_id==paper_id,StructuredNote.owner_id==current[1].id).order_by(StructuredNote.id.desc())) if not needle or any(needle in (field['label']+' '+field['value']).casefold() for field in n.fields)]


@router.post('/papers/{paper_id}/structured-notes',status_code=201)
def create_note(paper_id:int,data:NoteIn,current=Depends(current_session),db:Session=Depends(get_db)):
    lock_paper(paper_id,current[1].id,db)
    note=StructuredNote(owner_id=current[1].id,paper_id=paper_id,**data.model_dump());db.add(note);db.commit();db.refresh(note);return note_view(note)


@router.put('/structured-notes/{id}')
def update_note(id:int,data:NoteIn,current=Depends(current_session),db:Session=Depends(get_db)):
    note=note_owned(id,current[1].id,db);note.template_name=data.template_name;note.fields=[item.model_dump() for item in data.fields];db.commit();db.refresh(note);return note_view(note)


@router.delete('/structured-notes/{id}',status_code=204)
def delete_note(id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    db.delete(note_owned(id,current[1].id,db));db.commit();return Response(status_code=204)


@router.post('/structured-notes/{id}/cards',status_code=201)
def field_to_card(id:int,data:ToCard,current=Depends(current_session),db:Session=Depends(get_db)):
    owner=current[1].id;note=note_owned(id,owner,db);paper=lock_paper(note.paper_id,owner,db)
    if data.field_index>=len(note.fields):raise HTTPException(422,'字段不存在')
    field=note.fields[data.field_index]
    if not field['value'].strip():raise HTTPException(422,'空字段不能转为卡片')
    card=Card(owner_id=owner,paper_id=paper.id,source_title_snapshot=paper.title,source_state='linked',
              title=data.title.strip(),type=data.type,content=field['value'],content_kind='interpretation',
              verification_status='pending',source_excerpt=None,note='阅读笔记字段：'+field['label'],version=1)
    if not card.title:raise HTTPException(422,'卡片标题不能为空')
    db.add(card);db.flush();db.add(CardVersion(owner_id=owner,card_id=card.id,version=1,snapshot=snapshot(card)))
    emit(db,owner,'card_created',card.id,card.type);db.commit();db.refresh(card)
    return {'id':card.id,'paper_id':card.paper_id,'content_kind':card.content_kind,'verification_status':card.verification_status,'source_excerpt':card.source_excerpt}
