from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import current_session, get_db, now
from app.models import Card, Draft, Paper, ProjectCard, ProjectDraft, ProjectPaper, ProjectPlan, ReadingPlan, ResearchProject
from app.plans import view as plan_view

router = APIRouter(prefix='/api/v1/projects', tags=['projects'])
RESOURCES = {'papers': (Paper, ProjectPaper), 'cards': (Card, ProjectCard),
             'plans': (ReadingPlan, ProjectPlan), 'drafts': (Draft, ProjectDraft)}


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=20000)
    objective: str = Field(default='', max_length=20000)
    status: Literal['active', 'completed', 'archived'] = 'active'


def owned(project_id, owner, db):
    project = db.scalar(select(ResearchProject).where(ResearchProject.id == project_id,
                        ResearchProject.owner_id == owner, ResearchProject.deleted_at.is_(None)).with_for_update())
    if project is None:
        raise HTTPException(404, '项目不存在')
    return project


def view(project, db):
    result = {key: getattr(project, key) for key in ('id', 'name', 'description', 'objective', 'status', 'created_at', 'updated_at')}
    resources = {}
    for kind, (model, link) in RESOURCES.items():
        query = select(model).join(link, link.resource_id == model.id).where(
            link.project_id == project.id, model.owner_id == project.owner_id)
        if model in (Card, Paper): query = query.where(model.deleted_at.is_(None))
        objects = db.scalars(query.order_by(model.id)).all()
        resources[kind] = [plan_view(obj, db) if kind == 'plans' else {
            'id': obj.id, 'title': obj.title, **({'status': obj.status} if kind in ('papers', 'drafts') else {})
        } for obj in objects]
    result['resources'] = resources
    result['counts'] = {kind: len(items) for kind, items in resources.items()}
    return result


@router.get('')
def list_projects(current=Depends(current_session), db: Session = Depends(get_db)):
    return [view(p, db) for p in db.scalars(select(ResearchProject).where(
        ResearchProject.owner_id == current[1].id, ResearchProject.deleted_at.is_(None)).order_by(ResearchProject.id.desc()))]


@router.post('', status_code=201)
def create_project(data: ProjectIn, current=Depends(current_session), db: Session = Depends(get_db)):
    project = ResearchProject(owner_id=current[1].id, **data.model_dump())
    db.add(project); db.commit(); db.refresh(project)
    return view(project, db)


@router.get('/{project_id}')
def get_project(project_id: int, current=Depends(current_session), db: Session = Depends(get_db)):
    return view(owned(project_id, current[1].id, db), db)


@router.put('/{project_id}')
def update_project(project_id: int, data: ProjectIn, current=Depends(current_session), db: Session = Depends(get_db)):
    project = owned(project_id, current[1].id, db)
    for key, value in data.model_dump().items():
        setattr(project, key, value)
    db.commit(); db.refresh(project)
    return view(project, db)


@router.delete('/{project_id}', status_code=204)
def delete_project(project_id: int, current=Depends(current_session), db: Session = Depends(get_db)):
    project = owned(project_id, current[1].id, db)
    project.deleted_at = now(); db.commit()
    return Response(status_code=204)


@router.post('/{project_id}/{kind}/{resource_id}', status_code=204)
def add_resource(project_id: int, kind: str, resource_id: int, current=Depends(current_session), db: Session = Depends(get_db)):
    project = owned(project_id, current[1].id, db)
    if kind not in RESOURCES:
        raise HTTPException(404, '资源类型不存在')
    model, link = RESOURCES[kind]
    query = select(model.id).where(model.id == resource_id, model.owner_id == current[1].id)
    if model in (Card, Paper): query = query.where(model.deleted_at.is_(None))
    resource = db.scalar(query.with_for_update())
    if resource is None:
        raise HTTPException(404, '资源不存在')
    if db.get(link, (project.id, resource_id)) is None:
        db.add(link(project_id=project.id, resource_id=resource_id)); db.commit()
    return Response(status_code=204)


@router.delete('/{project_id}/{kind}/{resource_id}', status_code=204)
def remove_resource(project_id: int, kind: str, resource_id: int, current=Depends(current_session), db: Session = Depends(get_db)):
    project = owned(project_id, current[1].id, db)
    if kind not in RESOURCES:
        raise HTTPException(404, '资源类型不存在')
    model, link = RESOURCES[kind]
    query = select(model.id).where(model.id == resource_id, model.owner_id == current[1].id)
    if model in (Card, Paper): query = query.where(model.deleted_at.is_(None))
    if db.scalar(query) is None:
        raise HTTPException(404, '资源不存在')
    db.execute(delete(link).where(link.project_id == project.id, link.resource_id == resource_id)); db.commit()
    return Response(status_code=204)
