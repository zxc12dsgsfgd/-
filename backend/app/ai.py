import ipaddress
import hashlib
import hmac
import json
import math
from datetime import timedelta
from typing import Literal
from urllib.parse import urlsplit
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from app.auth import current_session, get_db
from app.config import get_settings
from app.models import AIConfig, AIJob, Card, CardTag, Draft, EvidenceChange, EvidenceLink, Paper, Tag, User

router=APIRouter(prefix='/api/v1',tags=['ai'])
Task=Literal['review','questions','tags','format']

def cipher():
    try:return Fernet(get_settings().ai_encryption_key.encode())
    except (ValueError,TypeError):raise HTTPException(503,'服务端 AI 加密密钥未配置或无效') from None

class ConfigIn(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    base_url:str=Field(min_length=1,max_length=2048)
    model_name:str=Field(min_length=1,max_length=255)
    timeout_seconds:int=Field(default=60,ge=5,le=300)
    api_key:str=Field(min_length=1,max_length=4096,repr=False)
    @field_validator('base_url')
    @classmethod
    def url(cls,value):
        try:
            parts=urlsplit(value)
            if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.port not in (None,443):raise ValueError()
            try: address=ipaddress.ip_address(parts.hostname)
            except ValueError: address=None
            if address is not None and not address.is_global:raise ValueError()
            if address is None and (':' in parts.hostname or parts.hostname.lower() in ('localhost','localhost.localdomain') or parts.hostname.lower().endswith('.local')):raise ValueError()
            return value.rstrip('/')
        except ValueError:raise ValueError('仅支持不含凭据或查询参数的 HTTPS 公网服务地址') from None

class Selection(BaseModel):
    model_config=ConfigDict(extra='forbid')
    task_type:Task
    paper_ids:list[int]=Field(default_factory=list,max_length=50)
    card_ids:list[int]=Field(default_factory=list,max_length=50)
    text:str=Field(default='',max_length=20000)

class DraftIn(Selection):
    title:str=Field(min_length=1,max_length=500)
    content:str=Field(max_length=15000)

class DraftUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    title:str=Field(min_length=1,max_length=500)
    content:str=Field(max_length=15000)

class ReviewIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(min_length=1,max_length=500)
    content:str=Field(max_length=15000)

class ApplyTagsIn(ReviewIn):
    card_id:int=Field(ge=1)
    tag_ids:list[int]=Field(min_length=1,max_length=50)
    @field_validator('tag_ids')
    @classmethod
    def valid_ids(cls, value):
        if any(i<1 for i in value) or len(set(value)) != len(value):raise ValueError('标签编号无效或重复')
        return value

class ConfirmedSelection(Selection):
    preview_token:str=Field(min_length=64,max_length=64)

def selected(data,user,db):
    if len(set(data.paper_ids))!=len(data.paper_ids) or len(set(data.card_ids))!=len(data.card_ids) or any(x<1 for x in data.paper_ids+data.card_ids):raise HTTPException(422,'材料编号无效或重复')
    papers=db.scalars(select(Paper).where(Paper.owner_id==user,Paper.deleted_at.is_(None),Paper.id.in_(data.paper_ids)).order_by(Paper.id)).all()
    cards=db.scalars(select(Card).where(Card.owner_id==user,Card.deleted_at.is_(None),Card.id.in_(data.card_ids)).order_by(Card.id)).all()
    if len(papers)!=len(data.paper_ids) or len(cards)!=len(data.card_ids):raise HTTPException(404,'材料不存在')
    return ([{'type':'paper','id':p.id,'title':p.title,'authors':p.authors,'year':p.year,'doi':p.doi,'abstract':p.abstract} for p in papers]+[{'type':'card','id':c.id,'title':c.title,'content':c.content,'note':c.note,'source_title':c.source_title_snapshot,'source_page':c.source_page,'source_excerpt':c.source_excerpt} for c in cards])

def preview_payload(data,user,db):
    sources=selected(data,user,db)
    if not sources and not data.text.strip():raise HTTPException(422,'请选择材料或输入文本')
    c=db.scalar(select(AIConfig).where(AIConfig.owner_id==user))
    if not c:raise HTTPException(409,'请先配置 AI 服务')
    payload={'task_type':data.task_type,'sources':sources,'text':data.text,'base_url':c.base_url,'model_name':c.model_name,'timeout_seconds':c.timeout_seconds,'key_fingerprint':hashlib.sha256(c.key_ciphertext).hexdigest()}
    raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    if len(raw)>200000:raise HTTPException(413,'所选材料超过 200 KB，请减少材料')
    cipher()
    token=hmac.new(get_settings().ai_encryption_key.encode(),raw,hashlib.sha256).hexdigest()
    return payload,token,c

@router.get('/settings/ai')
def get_config(current=Depends(current_session),db:Session=Depends(get_db)):
    c=db.scalar(select(AIConfig).where(AIConfig.owner_id==current[1].id))
    return {'configured':bool(c),'base_url':c.base_url if c else None,'model_name':c.model_name if c else None,'timeout_seconds':c.timeout_seconds if c else None}

@router.put('/settings/ai')
def put_config(data:ConfigIn,current=Depends(current_session),db:Session=Depends(get_db)):
    encrypted=cipher().encrypt(data.api_key.encode());c=db.scalar(select(AIConfig).where(AIConfig.owner_id==current[1].id).with_for_update())
    if not c:c=AIConfig(owner_id=current[1].id);db.add(c)
    c.base_url=data.base_url;c.model_name=data.model_name;c.timeout_seconds=data.timeout_seconds;c.key_ciphertext=encrypted;db.commit()
    return {'configured':True,'base_url':c.base_url,'model_name':c.model_name,'timeout_seconds':c.timeout_seconds}

@router.delete('/settings/ai',status_code=204)
def delete_config(current=Depends(current_session),db:Session=Depends(get_db)):
    c=db.scalar(select(AIConfig).where(AIConfig.owner_id==current[1].id))
    if c:db.delete(c);db.commit()
    return Response(status_code=204)

@router.post('/ai/preview')
def preview(data:Selection,current=Depends(current_session),db:Session=Depends(get_db)):
    sources=selected(data,current[1].id,db)
    if not sources and not data.text.strip():raise HTTPException(422,'请选择材料或输入文本')
    c=db.scalar(select(AIConfig).where(AIConfig.owner_id==current[1].id))
    token=preview_payload(data,current[1].id,db)[1] if c else None
    return {'task_type':data.task_type,'sources':sources,'text':data.text,'base_url':c.base_url if c else None,'model_name':c.model_name if c else None,'preview_token':token,'notice':'确认后以上材料将发送给所配置的外部服务提供方；输出未经核实。'}

@router.post('/ai/tasks',status_code=202)
def create_task(data:ConfirmedSelection,current=Depends(current_session),db:Session=Depends(get_db)):
    db.scalar(select(User.id).where(User.id==current[1].id).with_for_update())
    payload,token,c=preview_payload(data,current[1].id,db)
    if not hmac.compare_digest(token,data.preview_token):raise HTTPException(409,'材料或配置已变化，请重新预览')
    settings=get_settings()
    timestamp=db.scalar(select(func.current_timestamp()))
    cutoff=timestamp-timedelta(seconds=settings.ai_rate_limit_window_seconds)
    # Locking reads use the latest committed state under MySQL REPEATABLE READ.
    recent=db.scalars(select(AIJob.created_at).where(AIJob.owner_id==current[1].id,AIJob.created_at>cutoff).order_by(AIJob.created_at.desc(),AIJob.id.desc()).limit(settings.ai_rate_limit_count).with_for_update()).all()
    if len(recent)>=settings.ai_rate_limit_count:
        retry=max(1,math.ceil((recent[-1]+timedelta(seconds=settings.ai_rate_limit_window_seconds)-timestamp).total_seconds()))
        raise HTTPException(429,'AI 请求过于频繁，请稍后重试',headers={'Retry-After':str(retry)})
    active=db.scalar(select(AIJob.id).where(AIJob.owner_id==current[1].id,AIJob.status.in_(['pending','running'])).limit(1).with_for_update())
    if active:raise HTTPException(429,'已有任务正在处理，请稍后重试',headers={'Retry-After':'60'})
    job=AIJob(owner_id=current[1].id,task_type=data.task_type,payload={'sources':payload['sources'],'text':payload['text']},base_url=c.base_url,model_name=c.model_name,timeout_seconds=c.timeout_seconds,key_ciphertext=c.key_ciphertext,status='pending',created_at=timestamp);db.add(job);db.commit();db.refresh(job)
    return {'id':job.id,'status':job.status}

@router.get('/ai/tasks')
def tasks(current=Depends(current_session),db:Session=Depends(get_db)):
    return [{'id':j.id,'status':j.status,'error_code':j.error_code,'draft_id':j.draft_id,'created_at':j.created_at} for j in db.scalars(select(AIJob).where(AIJob.owner_id==current[1].id).order_by(AIJob.id.desc()).limit(30))]

@router.post('/drafts',status_code=201)
def create_draft(data:DraftIn,current=Depends(current_session),db:Session=Depends(get_db)):
    sources=selected(data,current[1].id,db)
    if data.text:sources.append({'type':'text','content':data.text})
    d=Draft(owner_id=current[1].id,task_type=data.task_type,title=data.title,content=data.content,sources=sources,status='draft');db.add(d);db.commit();db.refresh(d);return draft_view(d)

def draft_view(d):return {'id':d.id,'task_type':d.task_type,'title':d.title,'content':d.content,'sources':d.sources,'status':d.status,'created_at':d.created_at,'updated_at':d.updated_at}
def owned_draft(id,user,db):
    d=db.scalar(select(Draft).where(Draft.id==id,Draft.owner_id==user))
    if not d:raise HTTPException(404,'草稿不存在')
    return d
@router.get('/drafts')
def drafts(current=Depends(current_session),db:Session=Depends(get_db)):
    return [draft_view(d) for d in db.scalars(select(Draft).where(Draft.owner_id==current[1].id).order_by(Draft.id.desc()).limit(100))]

@router.get('/drafts/{id}/source-status')
def draft_source_status(id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    draft=owned_draft(id,current[1].id,db)
    result=[]
    for index,source in enumerate(draft.sources):
        kind=source.get('type') if isinstance(source,dict) else None
        source_id=source.get('id') if isinstance(source,dict) else None
        if kind in ('paper','card') and isinstance(source_id,int) and not isinstance(source_id,bool):
            model=Paper if kind=='paper' else Card
            query=select(model.id).where(model.id==source_id,model.owner_id==current[1].id)
            query=query.where(model.deleted_at.is_(None))
            exists=db.scalar(query) is not None
            state='available' if exists else 'unavailable'
        elif kind in ('paper','card'): state='unavailable'
        elif kind=='text': state='text_snapshot'
        else: state='unknown'
        result.append({'index':index,'type':kind,'title':source.get('title') if isinstance(source,dict) else None,'status':state})
    return {'sources':result,'notice':'材料快照仅记录当次选择，不代表逐句引用或内容已经核实。'}
@router.put('/drafts/{id}')
def edit_draft(id:int,data:DraftUpdate,current=Depends(current_session),db:Session=Depends(get_db)):
    d=db.scalar(select(Draft).where(Draft.id==id,Draft.owner_id==current[1].id).with_for_update())
    if not d:raise HTTPException(404,'草稿不存在')
    if d.title!=data.title or d.content!=data.content:d.status='draft'
    d.title=data.title;d.content=data.content;db.commit();db.refresh(d);return draft_view(d)

def reviewed_draft(id,data,owner,db):
    draft=db.scalar(select(Draft).where(Draft.id==id,Draft.owner_id==owner).with_for_update())
    if not draft:raise HTTPException(404,'草稿不存在')
    if draft.title!=data.title or draft.content!=data.content:raise HTTPException(409,'草稿已变化，请刷新并重新审核')
    return draft

@router.post('/drafts/{id}/accept')
def accept_draft(id:int,data:ReviewIn,current=Depends(current_session),db:Session=Depends(get_db)):
    d=reviewed_draft(id,data,current[1].id,db)
    d.status='accepted';db.commit();return draft_view(d)

@router.post('/drafts/{id}/apply-tags')
def apply_draft_tags(id:int,data:ApplyTagsIn,current=Depends(current_session),db:Session=Depends(get_db)):
    owner=current[1].id
    d=reviewed_draft(id,data,owner,db)
    if d.task_type!='tags' or d.status!='accepted':raise HTTPException(409,'请先接受标签建议草稿')
    card=db.scalar(select(Card).where(Card.id==data.card_id,Card.owner_id==owner,Card.deleted_at.is_(None)).with_for_update())
    if not card:raise HTTPException(404,'卡片不存在')
    tags=db.scalars(select(Tag).where(Tag.owner_id==owner,Tag.id.in_(data.tag_ids)).order_by(Tag.id).with_for_update()).all()
    if len(tags)!=len(data.tag_ids):raise HTTPException(404,'标签不存在')
    added=0
    for tag in tags:
        if not db.get(CardTag,(card.id,tag.id)):
            db.add(CardTag(card_id=card.id,tag_id=tag.id));added+=1
    db.commit()
    return {'added':added}

@router.delete('/drafts/{id}',status_code=204)
def delete_draft(id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    draft=owned_draft(id,current[1].id,db)
    links=select(EvidenceLink.id).where(EvidenceLink.draft_id==draft.id,EvidenceLink.owner_id==current[1].id)
    db.execute(delete(EvidenceChange).where(EvidenceChange.link_id.in_(links),EvidenceChange.owner_id==current[1].id))
    db.execute(delete(EvidenceLink).where(EvidenceLink.draft_id==draft.id,EvidenceLink.owner_id==current[1].id))
    db.delete(draft);db.commit();return Response(status_code=204)
