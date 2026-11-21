from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import current_session, get_db, now
from app.models import Card, CardTag, Paper, PaperStatusEvent, PaperTag, ProjectCard, ProjectPaper, ResearchProject, Tag
from app.papers import move_paper_to_trash
from app.workflows import emit

router=APIRouter(prefix='/api/v1',tags=['batch'])


class BatchRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind:Literal['papers','cards']
    ids:list[int]=Field(min_length=1,max_length=50)
    action:Literal['add_tag','remove_tag','add_project','set_status','trash']
    tag_id:int|None=Field(default=None,ge=1)
    project_id:int|None=Field(default=None,ge=1)
    status:Literal['unread','reading','read','archived']|None=None
    confirmed:bool=False

    @model_validator(mode='after')
    def valid(self):
        if any(i<1 for i in self.ids) or len(self.ids)!=len(set(self.ids)):raise ValueError('编号必须为不重复的正整数')
        if (self.tag_id is not None)!=(self.action in ('add_tag','remove_tag')):raise ValueError('标签参数与操作不匹配')
        if (self.project_id is not None)!=(self.action=='add_project'):raise ValueError('项目参数与操作不匹配')
        if (self.status is not None)!=(self.action=='set_status'):raise ValueError('状态参数与操作不匹配')
        if self.action=='set_status' and self.kind!='papers':raise ValueError('只有文献支持状态变更')
        if self.action in ('set_status','trash') and not self.confirmed:raise ValueError('操作需要明确确认')
        return self


def reject(count,reason,status=404):
    raise HTTPException(status,{'code':'batch_rejected','message':reason,'success_count':0,'failed_count':count})


@router.post('/batch')
def batch(data:BatchRequest,current=Depends(current_session),db:Session=Depends(get_db)):
    owner=current[1].id;count=len(data.ids)
    if data.action=='add_project':
        project=db.scalar(select(ResearchProject.id).where(ResearchProject.id==data.project_id,ResearchProject.owner_id==owner,ResearchProject.deleted_at.is_(None)).with_for_update())
        if project is None:reject(count,'项目不存在或不可访问')
    model=Paper if data.kind=='papers' else Card
    objects=db.scalars(select(model).where(model.id.in_(data.ids),model.owner_id==owner,model.deleted_at.is_(None)).order_by(model.id).with_for_update()).all()
    if len(objects)!=count:reject(count,'部分所选资料不存在或不可访问，整批未执行')
    if data.action in ('add_tag','remove_tag'):
        tag=db.scalar(select(Tag.id).where(Tag.id==data.tag_id,Tag.owner_id==owner).with_for_update())
        if tag is None:reject(count,'标签不存在或不可访问')
    changed=0
    try:
        for obj in objects:
            if data.action in ('add_tag','remove_tag'):
                model_link=PaperTag if data.kind=='papers' else CardTag
                link=db.get(model_link,(obj.id,data.tag_id))
                if data.action=='add_tag' and link is None:
                    values={'paper_id':obj.id} if data.kind=='papers' else {'card_id':obj.id}
                    db.add(model_link(**values,tag_id=data.tag_id));changed+=1
                elif data.action=='remove_tag' and link is not None:
                    db.delete(link);changed+=1
            elif data.action=='add_project':
                model_link=ProjectPaper if data.kind=='papers' else ProjectCard
                if db.get(model_link,(data.project_id,obj.id)) is None:
                    db.add(model_link(project_id=data.project_id,resource_id=obj.id));changed+=1
            elif data.action=='set_status':
                if obj.status!=data.status:
                    obj.status=data.status;db.add(PaperStatusEvent(owner_id=owner,paper_id=obj.id,to_status=obj.status,occurred_at=now()))
                    emit(db,owner,'paper_status_changed',obj.id,obj.status);changed+=1
            else:
                if data.kind=='papers':move_paper_to_trash(obj,owner,db)
                else:obj.deleted_at=now()
                changed+=1
        db.commit()
    except HTTPException:
        db.rollback();reject(count,'工作流执行失败，整批操作已回滚',409)
    except SQLAlchemyError:
        db.rollback();reject(count,'数据发生冲突或服务暂不可用，整批操作已回滚',409)
    return {'success_count':count,'failed_count':0,'changed_count':changed,'message':'操作完成；未变更项可能已处于目标状态'}
