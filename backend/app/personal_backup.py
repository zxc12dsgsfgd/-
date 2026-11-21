"""Versioned personal data export, validation, and non-destructive import."""
import hashlib
import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_session, get_db
from app.knowledge import CardIn
from app.models import Card, CardRelation, CardTag, CardVersion, Paper, PaperNote, PaperTag, ProjectCard, ProjectPaper, ProjectPlan, ProjectDraft, ResearchProject, ReadingPlan, ReadingPlanItem, Draft, Tag, User, ReadingTemplate, StructuredNote, EvidenceLink, EvidenceChange
from app.papers import PaperInput
from app.tags import norm
from app.reading_templates import NoteIn as StructuredNoteInput, TemplateIn
from app.plans import PlanIn

router = APIRouter(prefix='/api/v1/personal-backup', tags=['personal-backup'])
MAX_BYTES = 10 * 1024 * 1024
LIMIT = 10000
EXCLUDED = ['PDF 附件', '回收站数据及计划中回收文献的关联', '工作流和通知', '账户、会话和 AI 配置']
EXCLUDED_V3 = [*EXCLUDED, '手动证据关联及其历史']
EXCLUDED_V2 = [*EXCLUDED_V3, '阅读计划和草稿', '项目与计划或草稿的关联']
EXCLUDED_V1 = [*EXCLUDED_V2, '结构化阅读笔记及自定义模板']
SNAPSHOT_FIELDS = ('title', 'type', 'content', 'content_kind', 'verification_status', 'paper_id', 'source_title_snapshot', 'source_state', 'source_page', 'source_excerpt', 'note')


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ExportPaper(PaperInput):
    id: int = Field(ge=1)


class ExportCard(CardIn):
    id: int = Field(ge=1)
    source_title_snapshot: str | None = Field(default=None, max_length=500)
    source_state: Literal['none', 'linked', 'detached', 'unavailable']
    version: int = Field(ge=1)


class ExportNote(Strict):
    paper_id: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=60000)


class ExportVersion(Strict):
    card_id: int = Field(ge=1)
    version: int = Field(ge=1)
    snapshot: dict


class ExportTag(Strict):
    id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=100)


class ExportRelation(Strict):
    source_card_id: int = Field(ge=1)
    target_card_id: int = Field(ge=1)
    relation_type: Literal['related', 'supports', 'contradicts', 'extends']


class ExportProject(Strict):
    id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=20000)
    objective: str = Field(max_length=20000)
    status: Literal['active', 'completed', 'archived']


class Pair(Strict):
    left: int = Field(ge=1)
    right: int = Field(ge=1)


class ExportStructuredNote(StructuredNoteInput):
    paper_id: int = Field(ge=1)


class ExportPlan(PlanIn):
    id: int = Field(ge=1)


class ExportSource(Strict):
    type: Literal['paper','card','text']
    id: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, max_length=500)
    authors: list[str] | None = Field(default=None, max_length=100)
    year: int | None = Field(default=None, ge=1, le=9999)
    doi: str | None = Field(default=None, max_length=512)
    abstract: str | None = Field(default=None, max_length=60000)
    content: str | None = Field(default=None, max_length=60000)
    note: str | None = Field(default=None, max_length=60000)
    source_title: str | None = Field(default=None, max_length=500)
    source_page: int | None = Field(default=None, ge=1)
    source_excerpt: str | None = Field(default=None, max_length=60000)


class ExportDraft(Strict):
    id: int = Field(ge=1)
    task_type: Literal['review','questions','tags','format']
    title: str = Field(min_length=1,max_length=500)
    content: str = Field(max_length=15000)
    status: Literal['draft','accepted']
    sources: list[ExportSource] = Field(max_length=101)


class EvidenceSnapshot(Strict):
    title: str = Field(max_length=500)
    doi: str | None = Field(default=None, max_length=512)
    source_url: str | None = Field(default=None, max_length=2048)


class ExportEvidenceDetail(Strict):
    source_type: Literal['paper','card']
    source_id: int | None = Field(ge=1)
    source_snapshot: EvidenceSnapshot
    location: str = Field(max_length=200)
    excerpt: str = Field(max_length=20000)
    note: str = Field(max_length=20000)


class ExportEvidenceChange(Strict):
    action: Literal['created','updated','removed']
    detail: ExportEvidenceDetail
    created_at: datetime


class ExportEvidence(ExportEvidenceDetail):
    card_id: int | None = Field(default=None,ge=1)
    draft_id: int | None = Field(default=None,ge=1)
    removed_at: datetime | None = None
    created_at: datetime
    changes: list[ExportEvidenceChange] = Field(max_length=LIMIT)

    @model_validator(mode='after')
    def validate_history(self):
        if (self.card_id is None)==(self.draft_id is None):raise ValueError('证据关联对象无效')
        if self.created_at.utcoffset() is not None or (self.removed_at is not None and self.removed_at.utcoffset() is not None) or any(x.created_at.utcoffset() is not None for x in self.changes):
            raise ValueError('证据时间必须为 UTC 无时区格式')
        if any(x.detail.source_type!=self.source_type or x.detail.source_id!=self.source_id for x in self.changes):
            raise ValueError('证据历史来源不一致')
        return self


class PersonalExport(Strict):
    format: Literal['zhiyan-personal-export']
    version: Literal[1, 2, 3, 4]
    excluded: list[str] = Field(max_length=20)
    papers: list[ExportPaper] = Field(max_length=LIMIT)
    notes: list[ExportNote] = Field(max_length=LIMIT)
    cards: list[ExportCard] = Field(max_length=LIMIT)
    card_versions: list[ExportVersion] = Field(max_length=LIMIT)
    tags: list[ExportTag] = Field(max_length=LIMIT)
    card_relations: list[ExportRelation] = Field(max_length=LIMIT)
    projects: list[ExportProject] = Field(max_length=LIMIT)
    paper_tags: list[Pair] = Field(max_length=LIMIT)
    card_tags: list[Pair] = Field(max_length=LIMIT)
    project_papers: list[Pair] = Field(max_length=LIMIT)
    project_cards: list[Pair] = Field(max_length=LIMIT)
    reading_templates: list[TemplateIn] | None = Field(default=None, max_length=LIMIT)
    structured_notes: list[ExportStructuredNote] | None = Field(default=None, max_length=LIMIT)
    plans: list[ExportPlan] | None = Field(default=None, max_length=LIMIT)
    drafts: list[ExportDraft] | None = Field(default=None, max_length=LIMIT)
    project_plans: list[Pair] | None = Field(default=None, max_length=LIMIT)
    project_drafts: list[Pair] | None = Field(default=None, max_length=LIMIT)
    evidence: list[ExportEvidence] | None = Field(default=None, max_length=LIMIT)

    @model_validator(mode='after')
    def validate_references(self):
        if self.version == 1 and (self.reading_templates is not None or self.structured_notes is not None):
            raise ValueError('版本 1 不支持结构化阅读数据')
        if self.version >= 2 and (self.reading_templates is None or self.structured_notes is None):
            raise ValueError('版本 2 缺少结构化阅读数据')
        additions = (self.plans,self.drafts,self.project_plans,self.project_drafts)
        if (self.version < 3 and any(x is not None for x in additions)) or (self.version >= 3 and any(x is None for x in additions)):
            raise ValueError('备份版本与计划或草稿字段不匹配')
        if (self.version < 4 and self.evidence is not None) or (self.version == 4 and self.evidence is None):
            raise ValueError('备份版本与证据字段不匹配')
        def ids(items):
            values = [item.id for item in items]
            if len(values) != len(set(values)):
                raise ValueError('重复编号')
            return set(values)
        papers, cards, tags, projects = map(ids, (self.papers, self.cards, self.tags, self.projects))
        plans, drafts = ids(self.plans or []), ids(self.drafts or [])
        if any((e.card_id is not None and e.card_id not in cards) or (e.draft_id is not None and e.draft_id not in drafts) for e in (self.evidence or [])):
            raise ValueError('证据关联对象无效')
        if sum(len(e.changes) for e in (self.evidence or [])) > LIMIT:raise ValueError('证据历史超过上限')
        if any(paper not in papers for plan in (self.plans or []) for paper in plan.paper_ids):
            raise ValueError('阅读计划文献引用无效')
        if any(c.paper_id is not None and c.paper_id not in papers for c in self.cards):
            raise ValueError('卡片文献引用无效')
        if any(n.paper_id not in papers for n in self.notes) or any(v.card_id not in cards for v in self.card_versions):
            raise ValueError('笔记或版本引用无效')
        if any(n.paper_id not in papers for n in (self.structured_notes or [])):
            raise ValueError('结构化笔记文献引用无效')
        versions = [(v.card_id, v.version) for v in self.card_versions]
        if len(versions) != len(set(versions)):
            raise ValueError('卡片版本重复')
        card_versions = {c.id: c.version for c in self.cards}
        if any(v.version > card_versions[v.card_id] for v in self.card_versions):
            raise ValueError('卡片版本超出当前版本')
        if any(r.source_card_id not in cards or r.target_card_id not in cards or r.source_card_id == r.target_card_id for r in self.card_relations):
            raise ValueError('卡片关系引用无效')
        rels = [(r.source_card_id, r.target_card_id, r.relation_type) for r in self.card_relations]
        if len(rels) != len(set(rels)):
            raise ValueError('卡片关系重复')
        tag_names = [norm(t.name) for t in self.tags]
        if any(not name or len(name) > 300 for name in tag_names) or len(tag_names) != len(set(tag_names)):
            raise ValueError('标签名称无效或重复')
        for links, left, right in ((self.paper_tags, papers, tags), (self.card_tags, cards, tags),
                                   (self.project_papers, projects, papers), (self.project_cards, projects, cards),
                                   (self.project_plans or [],projects,plans),(self.project_drafts or [],projects,drafts)):
            pairs = [(item.left, item.right) for item in links]
            if len(pairs) != len(set(pairs)) or any(a not in left or b not in right for a, b in pairs):
                raise ValueError('关联引用无效或重复')
        return self


def limited(db, statement):
    rows = db.scalars(statement.limit(LIMIT + 1)).all()
    if len(rows) > LIMIT:
        raise HTTPException(413, '数据条数超过当前导出上限')
    return rows


def pair_rows(db, statement):
    rows = db.execute(statement.limit(LIMIT + 1)).all()
    if len(rows) > LIMIT:
        raise HTTPException(413, '关联条数超过当前导出上限')
    return [{'left': a, 'right': b} for a, b in rows]


@router.get('/export')
def export_data(current=Depends(current_session), db: Session = Depends(get_db)):
    owner = current[1].id
    papers = limited(db, select(Paper).where(Paper.owner_id == owner, Paper.deleted_at.is_(None)).order_by(Paper.id))
    cards = limited(db, select(Card).where(Card.owner_id == owner, Card.deleted_at.is_(None)).order_by(Card.id))
    tags = limited(db, select(Tag).where(Tag.owner_id == owner).order_by(Tag.id))
    projects = limited(db, select(ResearchProject).where(ResearchProject.owner_id == owner, ResearchProject.deleted_at.is_(None)).order_by(ResearchProject.id))
    notes = limited(db, select(PaperNote).join(Paper, Paper.id == PaperNote.paper_id).where(PaperNote.owner_id == owner, Paper.owner_id == owner, Paper.deleted_at.is_(None)).order_by(PaperNote.id))
    templates = limited(db, select(ReadingTemplate).where(ReadingTemplate.owner_id == owner).order_by(ReadingTemplate.id))
    structured = limited(db, select(StructuredNote).join(Paper, Paper.id == StructuredNote.paper_id).where(StructuredNote.owner_id == owner, Paper.owner_id == owner, Paper.deleted_at.is_(None)).order_by(StructuredNote.id))
    plans = limited(db, select(ReadingPlan).where(ReadingPlan.owner_id == owner).order_by(ReadingPlan.id))
    drafts = limited(db, select(Draft).where(Draft.owner_id == owner).order_by(Draft.id))
    evidence = limited(db, select(EvidenceLink).where(EvidenceLink.owner_id==owner,
        ((EvidenceLink.card_id.in_([c.id for c in cards])) | (EvidenceLink.draft_id.in_([d.id for d in drafts])))).order_by(EvidenceLink.id))
    changes = limited(db,select(EvidenceChange).where(EvidenceChange.owner_id==owner,EvidenceChange.link_id.in_([e.id for e in evidence])).order_by(EvidenceChange.id))
    changes_by_link = {}
    for change in changes:changes_by_link.setdefault(change.link_id,[]).append({'action':change.action,'detail':change.detail,'created_at':change.created_at})
    plan_items = pair_rows(db, select(ReadingPlanItem.plan_id,ReadingPlanItem.paper_id).join(ReadingPlan,ReadingPlan.id==ReadingPlanItem.plan_id).join(Paper,Paper.id==ReadingPlanItem.paper_id).where(ReadingPlan.owner_id==owner,Paper.owner_id==owner,Paper.deleted_at.is_(None)))
    versions = limited(db, select(CardVersion).join(Card, Card.id == CardVersion.card_id).where(CardVersion.owner_id == owner, Card.owner_id == owner, Card.deleted_at.is_(None)).order_by(CardVersion.id))
    active_ids = [c.id for c in cards]
    active_paper_ids = {p.id for p in papers}
    papers_by_plan = {}
    for pair in plan_items:
        papers_by_plan.setdefault(pair['left'], []).append(pair['right'])
    for draft in drafts:
        for source in draft.sources:
            if not isinstance(source,dict) or set(source)-set(ExportSource.model_fields):
                raise HTTPException(422, '草稿来源包含当前版本无法安全备份的字段，请检查草稿')
    relations = limited(db, select(CardRelation).where(CardRelation.owner_id == owner, CardRelation.source_card_id.in_(active_ids), CardRelation.target_card_id.in_(active_ids)).order_by(CardRelation.id))
    obj = PersonalExport.model_validate({
        'format': 'zhiyan-personal-export', 'version': 4, 'excluded': EXCLUDED,
        'papers': [{'id': p.id, **PaperInput.model_validate(p, from_attributes=True).model_dump()} for p in papers],
        'notes': [{'paper_id': n.paper_id, 'content': n.content} for n in notes],
        'reading_templates': [{'name': t.name, 'fields': t.fields} for t in templates],
        'structured_notes': [{'paper_id': n.paper_id, 'template_name': n.template_name, 'fields': n.fields} for n in structured],
        'plans': [{'id':p.id,'name':p.name,'start_date':p.start_date,'end_date':p.end_date,'target_count':p.target_count,'paper_ids':papers_by_plan.get(p.id,[])} for p in plans],
        'drafts': [{'id':d.id,'task_type':d.task_type,'title':d.title,'content':d.content,'status':d.status,'sources':[ExportSource.model_validate({k:v for k,v in s.items() if k in ExportSource.model_fields}).model_dump(exclude_none=True) for s in d.sources]} for d in drafts],
        'evidence': [{'card_id':e.card_id,'draft_id':e.draft_id,'source_type':e.source_type,'source_id':e.source_id,'source_snapshot':e.source_snapshot,'location':e.location,'excerpt':e.excerpt,'note':e.note,'removed_at':e.removed_at,'created_at':e.created_at,'changes':changes_by_link.get(e.id,[])} for e in evidence],
        'cards': [{'id': c.id, **{**CardIn.model_validate(c, from_attributes=True).model_dump(), 'paper_id': c.paper_id if c.paper_id in active_paper_ids else None}, 'source_title_snapshot': c.source_title_snapshot, 'source_state': c.source_state, 'version': c.version} for c in cards],
        'card_versions': [{'card_id': v.card_id, 'version': v.version, 'snapshot': {k: v.snapshot[k] for k in SNAPSHOT_FIELDS if k in v.snapshot}} for v in versions],
        'tags': [{'id': t.id, 'name': t.name} for t in tags],
        'card_relations': [{'source_card_id': r.source_card_id, 'target_card_id': r.target_card_id, 'relation_type': r.relation_type} for r in relations],
        'projects': [{'id': p.id, 'name': p.name, 'description': p.description, 'objective': p.objective, 'status': p.status} for p in projects],
        'paper_tags': pair_rows(db, select(PaperTag.paper_id, PaperTag.tag_id).join(Paper, Paper.id == PaperTag.paper_id).join(Tag, Tag.id == PaperTag.tag_id).where(Paper.owner_id == owner, Paper.deleted_at.is_(None), Tag.owner_id == owner)),
        'card_tags': pair_rows(db, select(CardTag.card_id, CardTag.tag_id).join(Card, Card.id == CardTag.card_id).join(Tag, Tag.id == CardTag.tag_id).where(Card.owner_id == owner, Card.deleted_at.is_(None), Tag.owner_id == owner)),
        'project_papers': pair_rows(db, select(ProjectPaper.project_id, ProjectPaper.resource_id).join(ResearchProject, ResearchProject.id == ProjectPaper.project_id).join(Paper, Paper.id == ProjectPaper.resource_id).where(ResearchProject.owner_id == owner, ResearchProject.deleted_at.is_(None), Paper.owner_id == owner, Paper.deleted_at.is_(None))),
        'project_cards': pair_rows(db, select(ProjectCard.project_id, ProjectCard.resource_id).join(ResearchProject, ResearchProject.id == ProjectCard.project_id).join(Card, Card.id == ProjectCard.resource_id).where(ResearchProject.owner_id == owner, ResearchProject.deleted_at.is_(None), Card.deleted_at.is_(None), Card.owner_id == owner)),
        'project_plans': pair_rows(db,select(ProjectPlan.project_id,ProjectPlan.resource_id).join(ResearchProject,ResearchProject.id==ProjectPlan.project_id).join(ReadingPlan,ReadingPlan.id==ProjectPlan.resource_id).where(ResearchProject.owner_id==owner,ResearchProject.deleted_at.is_(None),ReadingPlan.owner_id==owner)),
        'project_drafts': pair_rows(db,select(ProjectDraft.project_id,ProjectDraft.resource_id).join(ResearchProject,ResearchProject.id==ProjectDraft.project_id).join(Draft,Draft.id==ProjectDraft.resource_id).where(ResearchProject.owner_id==owner,ResearchProject.deleted_at.is_(None),Draft.owner_id==owner)),
    })
    encoded = obj.model_dump_json().encode('utf-8')
    if len(encoded) > MAX_BYTES:
        raise HTTPException(413, '导出数据超过 10 MiB 上限')
    return Response(encoded, media_type='application/json', headers={'Content-Disposition': 'attachment; filename="zhiyan-personal-export-v4.json"', 'Cache-Control': 'no-store'})


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


async def read_export(file):
    data = await file.read(MAX_BYTES + 1)
    await file.close()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, '文件超过 10 MiB 上限')
    try:
        obj = PersonalExport.model_validate(json.loads(data.decode('utf-8'), object_pairs_hook=unique_keys))
    except (ValueError, UnicodeError, ValidationError, RecursionError):
        raise HTTPException(422, '文件格式、版本或数据关联无效') from None
    return obj, hashlib.sha256(data).hexdigest()


def conflicts(obj, owner, db):
    existing = set(db.scalars(select(Tag.name_norm).where(Tag.owner_id == owner)).all())
    return [t.name for t in obj.tags if norm(t.name) in existing]


@router.post('/preview')
async def preview(file: UploadFile = File(...), current=Depends(current_session), db: Session = Depends(get_db)):
    obj, digest = await read_export(file)
    keys = ('papers', 'notes', 'cards', 'card_versions', 'tags', 'card_relations', 'projects', 'paper_tags', 'card_tags', 'project_papers', 'project_cards')
    counts = {key: len(getattr(obj, key)) for key in keys}
    if obj.version >= 2:
        counts.update(reading_templates=len(obj.reading_templates), structured_notes=len(obj.structured_notes))
    if obj.version >= 3:
        counts.update(plans=len(obj.plans), drafts=len(obj.drafts), project_plans=len(obj.project_plans), project_drafts=len(obj.project_drafts))
    if obj.version == 4:counts.update(evidence=len(obj.evidence),evidence_changes=sum(len(e.changes) for e in obj.evidence))
    return {'format': obj.format, 'version': obj.version, 'sha256': digest, 'counts': counts,
            'tag_conflicts': conflicts(obj, current[1].id, db), 'excluded': EXCLUDED_V1 if obj.version == 1 else EXCLUDED_V2 if obj.version == 2 else EXCLUDED_V3 if obj.version == 3 else EXCLUDED,
            'notice': '导入将新建数据，不覆盖或合并；若标签名称与现有标签冲突则全部拒绝。未包含的数据无法恢复。'}


@router.post('/restore')
async def restore(file: UploadFile = File(...), confirmed: bool = Form(False), expected_sha256: str = Form(''),
                  current=Depends(current_session), db: Session = Depends(get_db)):
    obj, digest = await read_export(file)
    if not confirmed or digest != expected_sha256:
        raise HTTPException(409, '请先预览该文件并确认导入；文件变更后需重新预览')
    owner = current[1].id
    db.scalar(select(User.id).where(User.id == owner).with_for_update())
    if conflicts(obj, owner, db):
        raise HTTPException(409, '标签名称与现有标签冲突；未导入任何数据')
    paper_ids, card_ids, tag_ids, project_ids, plan_ids, draft_ids = {}, {}, {}, {}, {}, {}
    try:
        for item in obj.papers:
            row = Paper(owner_id=owner, **item.model_dump(exclude={'id'})); db.add(row); db.flush(); paper_ids[item.id] = row.id
        for item in obj.notes:
            db.add(PaperNote(owner_id=owner, paper_id=paper_ids[item.paper_id], content=item.content))
        for item in obj.reading_templates or []:
            db.add(ReadingTemplate(owner_id=owner, **item.model_dump()))
        for item in obj.structured_notes or []:
            db.add(StructuredNote(owner_id=owner, paper_id=paper_ids[item.paper_id], **item.model_dump(exclude={'paper_id'})))
        for item in obj.cards:
            data = item.model_dump(exclude={'id'})
            data['paper_id'] = paper_ids[item.paper_id] if item.paper_id is not None else None
            row = Card(owner_id=owner, **data); db.add(row); db.flush(); card_ids[item.id] = row.id
        for item in obj.card_versions:
            snapshot = {k: item.snapshot[k] for k in SNAPSHOT_FIELDS if k in item.snapshot}
            if snapshot.get('paper_id') is not None:
                original_id = snapshot['paper_id']
                snapshot['paper_id'] = paper_ids.get(original_id) if isinstance(original_id, int) and not isinstance(original_id, bool) else None
                if snapshot['paper_id'] is None:
                    snapshot['source_state'] = 'unavailable'
            db.add(CardVersion(owner_id=owner, card_id=card_ids[item.card_id], version=item.version, snapshot=snapshot))
        for item in obj.tags:
            row = Tag(owner_id=owner, name=item.name, name_norm=norm(item.name)); db.add(row); db.flush(); tag_ids[item.id] = row.id
        for item in obj.projects:
            row = ResearchProject(owner_id=owner, **item.model_dump(exclude={'id'})); db.add(row); db.flush(); project_ids[item.id] = row.id
        for item in obj.plans or []:
            row=ReadingPlan(owner_id=owner,**item.model_dump(exclude={'id','paper_ids'}));db.add(row);db.flush();plan_ids[item.id]=row.id
            for paper_id in item.paper_ids:db.add(ReadingPlanItem(plan_id=row.id,paper_id=paper_ids[paper_id]))
        for item in obj.drafts or []:
            sources=[]
            for source in item.sources:
                value=source.model_dump(exclude_none=True)
                if source.type in ('paper','card'):
                    mapped=(paper_ids if source.type=='paper' else card_ids).get(source.id)
                    value['id']=mapped
                sources.append(value)
            row=Draft(owner_id=owner,task_type=item.task_type,title=item.title,content=item.content,status=item.status,sources=sources);db.add(row);db.flush();draft_ids[item.id]=row.id
        for item in obj.evidence or []:
            mapped=(paper_ids if item.source_type=='paper' else card_ids).get(item.source_id)
            row=EvidenceLink(owner_id=owner,card_id=card_ids.get(item.card_id),draft_id=draft_ids.get(item.draft_id),source_type=item.source_type,source_id=mapped,source_snapshot=item.source_snapshot.model_dump(exclude_unset=True),location=item.location,excerpt=item.excerpt,note=item.note,removed_at=item.removed_at,created_at=item.created_at)
            db.add(row);db.flush()
            for change in item.changes:
                detail=change.detail.model_dump();detail['source_id']=mapped
                db.add(EvidenceChange(owner_id=owner,link_id=row.id,action=change.action,detail=detail,created_at=change.created_at))
        for item in obj.paper_tags: db.add(PaperTag(paper_id=paper_ids[item.left], tag_id=tag_ids[item.right]))
        for item in obj.card_tags: db.add(CardTag(card_id=card_ids[item.left], tag_id=tag_ids[item.right]))
        for item in obj.project_papers: db.add(ProjectPaper(project_id=project_ids[item.left], resource_id=paper_ids[item.right]))
        for item in obj.project_cards: db.add(ProjectCard(project_id=project_ids[item.left], resource_id=card_ids[item.right]))
        for item in obj.project_plans or []:db.add(ProjectPlan(project_id=project_ids[item.left],resource_id=plan_ids[item.right]))
        for item in obj.project_drafts or []:db.add(ProjectDraft(project_id=project_ids[item.left],resource_id=draft_ids[item.right]))
        for item in obj.card_relations:
            db.add(CardRelation(owner_id=owner, source_card_id=card_ids[item.source_card_id], target_card_id=card_ids[item.target_card_id], relation_type=item.relation_type))
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(503, '导入失败，数据库操作已回滚；请检查数据和服务状态') from None
    counts = {key: len(getattr(obj, key)) for key in ('papers', 'notes', 'cards', 'card_versions', 'tags', 'card_relations', 'projects')}
    if obj.version >= 2:
        counts.update(reading_templates=len(obj.reading_templates), structured_notes=len(obj.structured_notes))
    if obj.version >= 3:counts.update(plans=len(obj.plans),drafts=len(obj.drafts))
    if obj.version == 4:counts.update(evidence=len(obj.evidence),evidence_changes=sum(len(e.changes) for e in obj.evidence))
    return {'counts': counts, 'excluded': EXCLUDED_V1 if obj.version == 1 else EXCLUDED_V2 if obj.version == 2 else EXCLUDED_V3 if obj.version == 3 else EXCLUDED, 'notice': '已导入为新数据；文件未包含的内容没有恢复。'}
