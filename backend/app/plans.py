from datetime import date, datetime, time, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from app.auth import current_session, get_db
from app.models import Card, Notification, Paper, PaperStatusEvent, ReadingPlan, ReadingPlanItem

router=APIRouter(prefix='/api/v1',tags=['plans'])
class PlanIn(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    name:str=Field(min_length=1,max_length=200)
    start_date:date
    end_date:date|None=None
    target_count:int=Field(ge=1,le=10000)
    paper_ids:list[int]=Field(default_factory=list,max_length=500)
    @model_validator(mode='after')
    def validate_plan(self):
        if self.end_date and self.end_date<self.start_date:raise ValueError('结束日期不能早于开始日期')
        if any(i<1 for i in self.paper_ids) or len(set(self.paper_ids))!=len(self.paper_ids):raise ValueError('文献编号无效或重复')
        return self

def owned(id,user,db):
    p=db.scalar(select(ReadingPlan).where(ReadingPlan.id==id,ReadingPlan.owner_id==user).with_for_update())
    if not p:raise HTTPException(404,'阅读计划不存在')
    return p
def validate_papers(ids,user,db):
    if not ids:return
    rows=db.scalars(select(Paper.id).where(Paper.id.in_(ids),Paper.owner_id==user,Paper.deleted_at.is_(None)).order_by(Paper.id).with_for_update()).all()
    if len(rows)!=len(ids):raise HTTPException(404,'文献不存在')
def view(plan,db):
    papers=db.execute(select(Paper.id,Paper.title,Paper.status).join(ReadingPlanItem,ReadingPlanItem.paper_id==Paper.id).where(ReadingPlanItem.plan_id==plan.id,Paper.owner_id==plan.owner_id,Paper.deleted_at.is_(None)).order_by(Paper.id)).all()
    done=sum(p.status=='read' for p in papers)
    hidden=db.scalar(select(func.count(Paper.id)).join(ReadingPlanItem,ReadingPlanItem.paper_id==Paper.id).where(ReadingPlanItem.plan_id==plan.id,Paper.owner_id==plan.owner_id,Paper.deleted_at.is_not(None)))
    return {'id':plan.id,'name':plan.name,'start_date':plan.start_date,'end_date':plan.end_date,'target_count':plan.target_count,'paper_ids':[p.id for p in papers],'papers':[{'id':p.id,'title':p.title,'status':p.status} for p in papers],'completed':done,'total':len(papers),'hidden_papers_count':hidden,'created_at':plan.created_at,'updated_at':plan.updated_at}

@router.get('/plans')
def list_plans(current=Depends(current_session),db:Session=Depends(get_db)):
    return [view(p,db) for p in db.scalars(select(ReadingPlan).where(ReadingPlan.owner_id==current[1].id).order_by(ReadingPlan.id.desc()))]
@router.post('/plans',status_code=201)
def create_plan(data:PlanIn,current=Depends(current_session),db:Session=Depends(get_db)):
    validate_papers(data.paper_ids,current[1].id,db)
    p=ReadingPlan(owner_id=current[1].id,**data.model_dump(exclude={'paper_ids'}));db.add(p);db.flush()
    for i in data.paper_ids:db.add(ReadingPlanItem(plan_id=p.id,paper_id=i))
    db.commit();db.refresh(p);return view(p,db)
@router.get('/plans/{plan_id}')
def get_plan(plan_id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    return view(owned(plan_id,current[1].id,db),db)
@router.put('/plans/{plan_id}')
def update_plan(plan_id:int,data:PlanIn,current=Depends(current_session),db:Session=Depends(get_db)):
    p=owned(plan_id,current[1].id,db)
    hidden=db.scalar(select(Paper.id).join(ReadingPlanItem,ReadingPlanItem.paper_id==Paper.id).where(ReadingPlanItem.plan_id==p.id,Paper.owner_id==current[1].id,Paper.deleted_at.is_not(None)).limit(1))
    if hidden:raise HTTPException(409,'计划包含回收站文献，请先恢复或永久删除文献后再编辑计划')
    validate_papers(data.paper_ids,current[1].id,db)
    for key,value in data.model_dump(exclude={'paper_ids'}).items():setattr(p,key,value)
    db.execute(delete(ReadingPlanItem).where(ReadingPlanItem.plan_id==p.id))
    for i in data.paper_ids:db.add(ReadingPlanItem(plan_id=p.id,paper_id=i))
    db.commit();db.refresh(p);return view(p,db)
@router.delete('/plans/{plan_id}',status_code=204)
def delete_plan(plan_id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    p=owned(plan_id,current[1].id,db);db.execute(delete(ReadingPlanItem).where(ReadingPlanItem.plan_id==p.id));db.delete(p);db.commit();return Response(status_code=204)

@router.get('/dashboard')
def dashboard(current=Depends(current_session),db:Session=Depends(get_db)):
    user=current[1].id
    counts=dict(db.execute(select(Paper.status,func.count(Paper.id)).where(Paper.owner_id==user,Paper.deleted_at.is_(None)).group_by(Paper.status)).all())
    total=sum(counts.values())
    card_count=db.scalar(select(func.count(Card.id)).where(Card.owner_id==user,Card.deleted_at.is_(None)))
    unread=db.scalar(select(func.count(Notification.id)).where(Notification.owner_id==user,Notification.read_at.is_(None)))
    recent=db.scalars(select(Card).where(Card.owner_id==user,Card.deleted_at.is_(None)).order_by(Card.id.desc()).limit(5)).all()
    return {'papers_total':total,'papers_by_status':{k:counts.get(k,0) for k in ('unread','reading','read','archived')},'cards_total':card_count,'unread_notifications':unread,'recent_cards':[{'id':c.id,'title':c.title} for c in recent]}

@router.get('/reports/weekly')
def weekly_report(week:date|None=None,current=Depends(current_session),db:Session=Depends(get_db)):
    # Fixed UTC+8 for this local version; historical transition coverage starts at migration.
    local_today=(datetime.now(timezone.utc)+timedelta(hours=8)).date()
    day=week or local_today
    monday=day-timedelta(days=day.weekday())
    start=datetime.combine(monday,time.min)-timedelta(hours=8)
    end=start+timedelta(days=7)
    owner=current[1].id
    papers=db.scalar(select(func.count(Paper.id)).where(Paper.owner_id==owner,Paper.deleted_at.is_(None),Paper.created_at>=start,Paper.created_at<end))
    cards=db.scalar(select(func.count(Card.id)).where(Card.owner_id==owner,Card.deleted_at.is_(None),Card.created_at>=start,Card.created_at<end))
    read=db.scalar(select(func.count(func.distinct(PaperStatusEvent.paper_id))).join(Paper,Paper.id==PaperStatusEvent.paper_id).where(PaperStatusEvent.owner_id==owner,Paper.owner_id==owner,Paper.deleted_at.is_(None),PaperStatusEvent.to_status=='read',PaperStatusEvent.occurred_at>=start,PaperStatusEvent.occurred_at<end))
    return {'week_start':monday,'week_end_exclusive':monday+timedelta(days=7),'timezone':'UTC+08:00','papers_added':papers,'cards_added':cards,'papers_read':read,'read_history_complete':False,'coverage_note':'已读事件仅从启用状态记录后开始统计；更早历史不完整。删除文献或卡片会改变历史统计。'}
