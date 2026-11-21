from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import current_session, get_db
from app.models import Card, CardRelation, CardTag, CardVersion, EvidenceChange, EvidenceLink, Paper, PaperFile, PaperNote, PaperStatusEvent, PaperTag, ReadingPlanItem, ProjectCard, ProjectDraft, ProjectPaper, ProjectPlan, ResearchProject, StructuredNote, PdfImportBatch, PdfImportItem
from app.knowledge import snapshot
from app.paper_files import path_for

router = APIRouter(prefix='/api/v1/trash', tags=['trash'])


class Confirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirm: bool


def trashed_card(id, owner, db):
    card=db.scalar(select(Card).where(Card.id==id,Card.owner_id==owner,Card.deleted_at.is_not(None)).with_for_update())
    if card is None: raise HTTPException(404,'回收站卡片不存在')
    return card


@router.get('/cards')
def list_cards(current=Depends(current_session),db:Session=Depends(get_db)):
    cards=db.scalars(select(Card).where(Card.owner_id==current[1].id,Card.deleted_at.is_not(None)).order_by(Card.deleted_at.desc(),Card.id.desc()).limit(500)).all()
    return {'items':[{'id':c.id,'title':c.title,'deleted_at':c.deleted_at} for c in cards],
            'notice':'当前不自动清理，卡片无限期保留；回收站不能代替备份。最多显示最近 500 条。'}


@router.post('/cards/{id}/restore',status_code=204)
def restore_card(id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    card=trashed_card(id,current[1].id,db);card.deleted_at=None;db.commit();return Response(status_code=204)


@router.delete('/cards/{id}',status_code=204)
def purge_card(id:int,data:Confirmation,current=Depends(current_session),db:Session=Depends(get_db)):
    if not data.confirm:raise HTTPException(422,'请确认永久删除')
    owner=current[1].id
    card=trashed_card(id,owner,db)
    links=select(EvidenceLink.id).where(EvidenceLink.card_id==card.id,EvidenceLink.owner_id==owner)
    db.execute(delete(EvidenceChange).where(EvidenceChange.link_id.in_(links),EvidenceChange.owner_id==owner))
    db.execute(delete(EvidenceLink).where(EvidenceLink.card_id==card.id,EvidenceLink.owner_id==owner))
    db.execute(delete(CardRelation).where(CardRelation.owner_id==owner,(CardRelation.source_card_id==card.id)|(CardRelation.target_card_id==card.id)))
    db.execute(delete(CardTag).where(CardTag.card_id==card.id))
    db.execute(delete(CardVersion).where(CardVersion.card_id==card.id,CardVersion.owner_id==owner))
    db.execute(delete(ProjectCard).where(ProjectCard.resource_id==card.id))
    db.delete(card);db.commit();return Response(status_code=204)


def trashed_project(id,owner,db):
    project=db.scalar(select(ResearchProject).where(ResearchProject.id==id,ResearchProject.owner_id==owner,ResearchProject.deleted_at.is_not(None)).with_for_update())
    if project is None:raise HTTPException(404,'回收站项目不存在')
    return project


@router.get('/projects')
def list_projects(current=Depends(current_session),db:Session=Depends(get_db)):
    projects=db.scalars(select(ResearchProject).where(ResearchProject.owner_id==current[1].id,ResearchProject.deleted_at.is_not(None)).order_by(ResearchProject.deleted_at.desc(),ResearchProject.id.desc()).limit(500)).all()
    return {'items':[{'id':p.id,'title':p.name,'deleted_at':p.deleted_at} for p in projects],
            'notice':'当前不自动清理，项目无限期保留；回收站不能代替备份。最多显示最近 500 条。'}


@router.post('/projects/{id}/restore',status_code=204)
def restore_project(id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    project=trashed_project(id,current[1].id,db);project.deleted_at=None;db.commit();return Response(status_code=204)


@router.delete('/projects/{id}',status_code=204)
def purge_project(id:int,data:Confirmation,current=Depends(current_session),db:Session=Depends(get_db)):
    if not data.confirm:raise HTTPException(422,'请确认永久删除')
    project=trashed_project(id,current[1].id,db)
    for link in (ProjectCard,ProjectDraft,ProjectPaper,ProjectPlan):
        db.execute(delete(link).where(link.project_id==project.id))
    db.delete(project);db.commit();return Response(status_code=204)


def trashed_paper(id,owner,db):
    paper=db.scalar(select(Paper).where(Paper.id==id,Paper.owner_id==owner,Paper.deleted_at.is_not(None)).with_for_update())
    if paper is None:raise HTTPException(404,'回收站文献不存在')
    return paper


@router.get('/papers')
def list_papers(current=Depends(current_session),db:Session=Depends(get_db)):
    papers=db.scalars(select(Paper).where(Paper.owner_id==current[1].id,Paper.deleted_at.is_not(None)).order_by(Paper.deleted_at.desc(),Paper.id.desc()).limit(500)).all()
    return {'items':[{'id':p.id,'title':p.title,'deleted_at':p.deleted_at} for p in papers],
            'notice':'文献和附件无限期保留，不自动清理；回收站不能代替备份。最多显示最近 500 条。'}


@router.get('/papers/{id}/files')
def list_paper_files(id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    paper=trashed_paper(id,current[1].id,db)
    files=db.scalars(select(PaperFile).where(PaperFile.paper_id==paper.id,PaperFile.owner_id==current[1].id).order_by(PaperFile.id)).all()
    return [{'id':f.id,'name':f.original_name,'state':f.state,'size_bytes':f.size_bytes} for f in files]


@router.post('/papers/{id}/restore',status_code=204)
def restore_paper(id:int,current=Depends(current_session),db:Session=Depends(get_db)):
    owner=current[1].id
    paper=trashed_paper(id,owner,db)
    if db.scalar(select(PaperFile.id).where(PaperFile.paper_id==paper.id,PaperFile.owner_id==owner,PaperFile.state=='deleting').limit(1)):
        raise HTTPException(409,'附件清理尚未完成，请先重试清理')
    cards=db.scalars(select(Card).where(Card.paper_id==paper.id,Card.owner_id==owner).with_for_update()).all()
    for card in cards:
        card.source_state='linked';card.version+=1
        db.add(CardVersion(owner_id=owner,card_id=card.id,version=card.version,snapshot=snapshot(card)))
    paper.deleted_at=None;db.commit();return Response(status_code=204)


@router.delete('/papers/{id}/files/{file_id}',status_code=204)
def purge_paper_file(id:int,file_id:int,data:Confirmation,current=Depends(current_session),db:Session=Depends(get_db)):
    if not data.confirm:raise HTTPException(422,'请确认永久删除附件')
    owner=current[1].id
    paper=trashed_paper(id,owner,db)
    record=db.scalar(select(PaperFile).where(PaperFile.id==file_id,PaperFile.paper_id==paper.id,PaperFile.owner_id==owner).with_for_update())
    if record is None:raise HTTPException(404,'附件不存在')
    record.state='deleting';db.commit()
    try:path_for(record.storage_key).unlink(missing_ok=True)
    except (OSError,ValueError):raise HTTPException(503,'附件清理失败，请重试；此时不能恢复文献') from None
    db.delete(record);db.commit();return Response(status_code=204)


@router.delete('/papers/{id}',status_code=204)
def purge_paper(id:int,data:Confirmation,current=Depends(current_session),db:Session=Depends(get_db)):
    if not data.confirm:raise HTTPException(422,'请确认永久删除文献')
    owner=current[1].id
    paper=trashed_paper(id,owner,db)
    if db.scalar(select(PaperFile.id).where(PaperFile.paper_id==paper.id,PaperFile.owner_id==owner).limit(1)):
        raise HTTPException(409,'请先逐个确认并清理 PDF 附件')
    pending=db.scalar(select(PdfImportBatch.id).join(PdfImportItem,PdfImportItem.batch_id==PdfImportBatch.id).where(
        PdfImportItem.paper_id==paper.id,PdfImportBatch.owner_id==owner,
        PdfImportBatch.status.not_in(['completed','cleaned'])).limit(1))
    if pending:raise HTTPException(409,'该文献有未处理的 PDF 导入批次，请先恢复或清理批次')
    db.execute(delete(PdfImportItem).where(PdfImportItem.paper_id==paper.id,
        PdfImportItem.batch_id.in_(select(PdfImportBatch.id).where(PdfImportBatch.owner_id==owner,
                                   PdfImportBatch.status.in_(['completed','cleaned'])))))
    db.execute(delete(PaperNote).where(PaperNote.paper_id==paper.id,PaperNote.owner_id==owner))
    db.execute(delete(StructuredNote).where(StructuredNote.paper_id==paper.id,StructuredNote.owner_id==owner))
    db.execute(delete(PaperStatusEvent).where(PaperStatusEvent.paper_id==paper.id,PaperStatusEvent.owner_id==owner))
    db.execute(delete(PaperTag).where(PaperTag.paper_id==paper.id))
    db.execute(delete(ReadingPlanItem).where(ReadingPlanItem.paper_id==paper.id))
    db.execute(delete(ProjectPaper).where(ProjectPaper.resource_id==paper.id))
    cards=db.scalars(select(Card).where(Card.paper_id==paper.id,Card.owner_id==owner).with_for_update()).all()
    for card in cards:
        card.paper_id=None;card.source_state='unavailable';card.source_title_snapshot=paper.title
        if card.verification_status=='user_checked':card.verification_status='pending'
        card.version+=1;db.add(CardVersion(owner_id=owner,card_id=card.id,version=card.version,snapshot=snapshot(card)))
    db.flush();db.delete(paper);db.commit();return Response(status_code=204)
