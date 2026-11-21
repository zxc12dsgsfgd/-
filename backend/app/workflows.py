from typing import Literal
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auth import current_session, get_db, now
from app.models import Card, CardTag, Notification, Paper, PaperStatusEvent, PaperTag, SchedulerFailure, Tag, Workflow, WorkflowEvent, WorkflowRun, WorkflowSyncFailure

router=APIRouter(prefix='/api/v1',tags=['workflows'])
Trigger=Literal['paper_created','paper_status_changed','card_created','scheduled_check']
class WorkflowIn(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    name:str=Field(min_length=1,max_length=200)
    enabled:bool=True
    trigger:Trigger
    filter_value:str|None=Field(default=None,max_length=40)
    message:str=Field(min_length=1,max_length=1000)
    action_type:Literal['notify','add_tag','set_status']='notify'
    action_value:str|None=Field(default=None,max_length=100)
    @model_validator(mode='after')
    def check_filter(self):
        valid={'paper_created':{'unread','reading','read','archived'},'paper_status_changed':{'unread','reading','read','archived'},'card_created':{'concept','method','conclusion','question','idea','other'},'scheduled_check':set()}
        if self.trigger!='scheduled_check' and self.filter_value is not None and self.filter_value not in valid[self.trigger]:raise ValueError('过滤值与触发类型不匹配')
        if self.trigger=='scheduled_check' and (self.filter_value is None or not self.filter_value.isdecimal() or not 1<=int(self.filter_value)<=3650):raise ValueError('请输入 1 至 3650 的超期天数')
        if self.action_type=='add_tag' and (not self.action_value or not self.action_value.isdecimal() or int(self.action_value)<1):raise ValueError('请选择标签')
        if self.action_type=='set_status' and (self.trigger=='card_created' or self.action_value not in valid['paper_created']):raise ValueError('文献状态动作参数无效')
        if self.trigger=='scheduled_check' and self.action_type=='set_status' and self.action_value=='unread':raise ValueError('超期规则不能将状态改回待读')
        if self.action_type=='notify' and self.action_value is not None:raise ValueError('提醒动作不接受动作值')
        return self

class WorkflowExecutionError(Exception):
    def __init__(self, name, trigger, code):
        self.name=name
        self.trigger=trigger
        self.code=code


def emit(db:Session,owner_id:int,trigger:str,object_id:int,value:str,event_id:str|None=None,depth:int=0):
    try:
        return _emit(db,owner_id,trigger,object_id,value,event_id,depth)
    except WorkflowExecutionError as exc:
        if depth:
            raise
        # Snapshot primitives before rollback; creation IDs are invalid after rollback.
        failed_id = object_id if trigger == 'paper_status_changed' else None
        db.rollback()
        try:
            db.add(WorkflowSyncFailure(owner_id=owner_id,workflow_name=exc.name,trigger=exc.trigger,object_id=failed_id,error_code=exc.code))
            db.commit()
        except Exception:
            db.rollback()
            raise HTTPException(503,'业务操作已回滚，失败记录暂不可用') from None
        raise HTTPException(409,'工作流执行失败，业务操作已回滚；请查看同步失败记录') from None


def _emit(db:Session,owner_id:int,trigger:str,object_id:int,value:str,event_id:str|None=None,depth:int=0):
    """Record event and matching notification in the caller's transaction."""
    event_id=event_id or str(uuid4())
    if db.get(WorkflowEvent,event_id): return
    event=WorkflowEvent(id=event_id,owner_id=owner_id,trigger=trigger,object_id=object_id);db.add(event);db.flush()
    rules=db.scalars(select(Workflow).where(Workflow.owner_id==owner_id,Workflow.enabled.is_(True),Workflow.trigger==trigger)).all()
    for rule in rules:
        if rule.filter_value is not None and rule.filter_value!=value:continue
        try:
            run=WorkflowRun(owner_id=owner_id,workflow_id=rule.id,event_id=event_id,workflow_name=rule.name,result='success');db.add(run);db.flush()
            if rule.action_type=='notify':
                db.add(Notification(owner_id=owner_id,run_id=run.id,message=rule.message))
            elif rule.action_type=='add_tag':
                tag=db.scalar(select(Tag).where(Tag.id==int(rule.action_value),Tag.owner_id==owner_id))
                model=Card if trigger=='card_created' else Paper
                query=select(model).where(model.id==object_id,model.owner_id==owner_id)
                query=query.where(model.deleted_at.is_(None))
                obj=db.scalar(query.with_for_update())
                if not tag or not obj:raise HTTPException(409,'规则引用的标签或对象不存在')
                link=CardTag if trigger=='card_created' else PaperTag
                if not db.get(link,(object_id,tag.id)):
                    db.add(link(**({'card_id':object_id} if trigger=='card_created' else {'paper_id':object_id}),tag_id=tag.id));db.flush()
            elif rule.action_type=='set_status':
                paper=db.scalar(select(Paper).where(Paper.id==object_id,Paper.owner_id==owner_id,Paper.deleted_at.is_(None)).with_for_update())
                if not paper:raise HTTPException(409,'规则对象不存在')
                if paper.status!=rule.action_value:
                    if depth>=5:raise HTTPException(409,'规则触发链超过限制，操作已回滚')
                    paper.status=rule.action_value;db.add(PaperStatusEvent(owner_id=owner_id,paper_id=paper.id,to_status=paper.status,occurred_at=now()));db.flush()
                    _emit(db,owner_id,'paper_status_changed',paper.id,paper.status,depth=depth+1)
            db.flush()
        except WorkflowExecutionError:
            raise
        except Exception as exc:
            code = 'chain_limit' if isinstance(exc, HTTPException) and exc.detail == '规则触发链超过限制，操作已回滚' else 'action_failed'
            raise WorkflowExecutionError(rule.name,trigger,code) from exc


def run_scheduled_once(db:Session):
    """Scan current UTC day; isolate each rule and paper, retry failed actions."""
    rules=db.execute(select(Workflow.id,Workflow.owner_id,Workflow.filter_value).where(Workflow.enabled.is_(True),Workflow.trigger=='scheduled_check')).all()
    processed=0
    for rule_id,owner_id,days_value in rules:
        ids=db.scalars(select(Paper.id).where(Paper.owner_id==owner_id,Paper.deleted_at.is_(None),Paper.status=='unread',Paper.created_at<=now()-timedelta(days=int(days_value))).order_by(Paper.id)).all()
        db.commit()
        for paper_id in ids:
            timestamp=now()
            current_key=str(uuid5(NAMESPACE_URL,f'overdue:{rule_id}:{paper_id}:{timestamp.date().isoformat()}'))
            pending=db.scalar(select(SchedulerFailure).where(SchedulerFailure.workflow_id==rule_id,SchedulerFailure.owner_id==owner_id,SchedulerFailure.object_id==paper_id,SchedulerFailure.resolved_at.is_(None)).order_by(SchedulerFailure.updated_at).limit(1))
            key=pending.event_id if pending else current_key
            db.commit()
            try:
                rule=db.scalar(select(Workflow).where(Workflow.id==rule_id,Workflow.owner_id==owner_id,Workflow.enabled.is_(True),Workflow.trigger=='scheduled_check').with_for_update())
                if not rule: db.rollback();continue
                paper=db.scalar(select(Paper).where(Paper.id==paper_id,Paper.owner_id==owner_id,Paper.deleted_at.is_(None)).with_for_update())
                if not paper or paper.status!='unread' or paper.created_at>timestamp-timedelta(days=int(rule.filter_value)):
                    db.rollback();continue
                if db.get(WorkflowEvent,current_key):db.rollback();continue
                if db.get(WorkflowEvent,key):db.rollback();continue
                failure=db.get(SchedulerFailure,key)
                if failure and failure.next_retry_at>timestamp:db.rollback();continue
                event=WorkflowEvent(id=key,owner_id=owner_id,trigger='scheduled_check',object_id=paper.id);db.add(event);db.flush()
                run=WorkflowRun(owner_id=owner_id,workflow_id=rule.id,event_id=key,workflow_name=rule.name,result='success');db.add(run);db.flush()
                if rule.action_type=='notify':db.add(Notification(owner_id=owner_id,run_id=run.id,message=rule.message))
                elif rule.action_type=='add_tag':
                    tag=db.scalar(select(Tag).where(Tag.id==int(rule.action_value),Tag.owner_id==owner_id))
                    if not tag:raise ValueError('tag_missing')
                    if not db.get(PaperTag,(paper.id,tag.id)):db.add(PaperTag(paper_id=paper.id,tag_id=tag.id))
                elif rule.action_type=='set_status':
                    if rule.action_value=='unread':raise ValueError('invalid_status')
                    paper.status=rule.action_value
                    db.add(PaperStatusEvent(owner_id=owner_id,paper_id=paper.id,to_status=paper.status,occurred_at=timestamp))
                    emit(db,owner_id,'paper_status_changed',paper.id,paper.status,depth=1)
                if failure:
                    failure.resolved_at=timestamp;failure.updated_at=timestamp
                    if key!=current_key:
                        db.add(WorkflowEvent(id=current_key,owner_id=owner_id,trigger='scheduled_check',object_id=paper.id))
                db.commit();processed+=1
            except Exception as exc:
                db.rollback()
                # Unique event means another worker succeeded; no failure to report.
                if db.get(WorkflowEvent,key):db.rollback();continue
                rule=db.scalar(select(Workflow).where(Workflow.id==rule_id,Workflow.owner_id==owner_id).with_for_update())
                if not rule:db.rollback();continue
                failure=db.get(SchedulerFailure,key)
                attempts=(failure.attempts if failure else 0)+1
                code=exc.args[0] if isinstance(exc,ValueError) and exc.args and exc.args[0] in ('tag_missing','invalid_status') else 'execution_failed'
                if not failure:
                    failure=SchedulerFailure(event_id=key,owner_id=owner_id,workflow_id=rule_id,workflow_name=rule.name,object_id=paper_id,error_code=code,attempts=attempts,next_retry_at=timestamp,updated_at=timestamp);db.add(failure)
                failure.error_code=code;failure.attempts=attempts;failure.updated_at=timestamp;failure.resolved_at=None
                failure.next_retry_at=timestamp+timedelta(seconds=min(3600,60*(2**min(attempts-1,6))))
                db.commit()
    return processed

def own(rule_id,user,db):
    r=db.scalar(select(Workflow).where(Workflow.id==rule_id,Workflow.owner_id==user))
    if not r:raise HTTPException(404,'规则不存在')
    return r
def view(r):return {'id':r.id,'name':r.name,'enabled':r.enabled,'trigger':r.trigger,'filter_value':r.filter_value,'message':r.message,'action_type':r.action_type,'action_value':r.action_value,'created_at':r.created_at,'updated_at':r.updated_at}

def validate_action(data,user,db):
    if data.action_type=='add_tag' and not db.scalar(select(Tag.id).where(Tag.id==int(data.action_value),Tag.owner_id==user)):
        raise HTTPException(404,'标签不存在')

@router.get('/workflows')
def list_rules(current=Depends(current_session),db:Session=Depends(get_db)):
    return [view(r) for r in db.scalars(select(Workflow).where(Workflow.owner_id==current[1].id).order_by(Workflow.id.desc()))]
@router.post('/workflows',status_code=201)
def create_rule(data:WorkflowIn,current=Depends(current_session),db:Session=Depends(get_db)):
    validate_action(data,current[1].id,db);r=Workflow(owner_id=current[1].id,**data.model_dump());db.add(r);db.commit();db.refresh(r);return view(r)
@router.put('/workflows/{rule_id}')
def update_rule(rule_id:int,data:WorkflowIn,current=Depends(current_session),db:Session=Depends(get_db)):
    validate_action(data,current[1].id,db);r=own(rule_id,current[1].id,db)
    for k,v in data.model_dump().items():setattr(r,k,v)
    db.commit();db.refresh(r);return view(r)
@router.delete('/workflows/{rule_id}',status_code=204)
def delete_rule(rule_id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    r=own(rule_id,current[1].id,db)
    for run in db.scalars(select(WorkflowRun).where(WorkflowRun.workflow_id==r.id,WorkflowRun.owner_id==current[1].id)):run.workflow_id=None
    for failure in db.scalars(select(SchedulerFailure).where(SchedulerFailure.workflow_id==r.id,SchedulerFailure.owner_id==current[1].id)):failure.workflow_id=None
    db.delete(r);db.commit();return Response(status_code=204)
@router.get('/workflow-runs')
def runs(current=Depends(current_session),db:Session=Depends(get_db)):
    rows=db.execute(select(WorkflowRun,WorkflowEvent).join(WorkflowEvent,WorkflowEvent.id==WorkflowRun.event_id).where(WorkflowRun.owner_id==current[1].id).order_by(WorkflowRun.id.desc()).limit(100)).all()
    return [{'id':r.id,'workflow_name':r.workflow_name,'trigger':e.trigger,'object_id':e.object_id,'result':r.result,'created_at':r.created_at} for r,e in rows]
@router.get('/notifications')
def notifications(current=Depends(current_session),db:Session=Depends(get_db)):
    return [{'id':n.id,'message':n.message,'read_at':n.read_at,'created_at':n.created_at} for n in db.scalars(select(Notification).where(Notification.owner_id==current[1].id).order_by(Notification.id.desc()).limit(100))]
@router.post('/notifications/{notification_id}/read')
def mark_read(notification_id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    n=db.scalar(select(Notification).where(Notification.id==notification_id,Notification.owner_id==current[1].id))
    if not n:raise HTTPException(404,'提醒不存在')
    if not n.read_at:n.read_at=now();db.commit()
    return {'id':n.id,'read_at':n.read_at}

@router.get('/workflow-failures')
def failures(current=Depends(current_session),db:Session=Depends(get_db)):
    return [{'workflow_name':f.workflow_name,'object_id':f.object_id,'error_code':f.error_code,'attempts':f.attempts,'next_retry_at':f.next_retry_at,'resolved_at':f.resolved_at,'updated_at':f.updated_at} for f in db.scalars(select(SchedulerFailure).where(SchedulerFailure.owner_id==current[1].id).order_by(SchedulerFailure.updated_at.desc()).limit(100))]


@router.get('/workflow-sync-failures')
def sync_failures(current=Depends(current_session),db:Session=Depends(get_db)):
    rows=db.scalars(select(WorkflowSyncFailure).where(WorkflowSyncFailure.owner_id==current[1].id).order_by(WorkflowSyncFailure.id.desc()).limit(100)).all()
    return [{'id':f.id,'workflow_name':f.workflow_name,'trigger':f.trigger,'object_id':f.object_id,'error_code':f.error_code,'created_at':f.created_at} for f in rows]
