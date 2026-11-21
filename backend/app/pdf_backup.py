"""Export, preview, and restore bounded PDF attachment archives."""
import hashlib
import hmac
import io
import json
import re
import stat
import zipfile

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.auth import current_session, get_db
from app.config import get_settings
from app.models import Paper, PaperFile, PdfImportBatch, PdfImportItem
from app.paper_files import path_for
from app import paper_files
from app.pdf_import_ledger import abort_batch, reserve_batch
from app.pdf_import_publish import publish_batch, recover_aborted
from app.pdf_import_process_lock import batch_process_lock
from app.pdf_import_staging import cleanup_staging, stage_batch

router = APIRouter(prefix='/api/v1/personal-backup', tags=['personal-backup'])
MAX_FILES = 100
MAX_TOTAL = 50 * 1024 * 1024
MAX_ARCHIVE = MAX_TOTAL + 1024 * 1024
MAX_MANIFEST = 128 * 1024


class ManifestFile(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    paper_id:int=Field(ge=1)
    name:str=Field(min_length=1,max_length=255)
    path:str=Field(pattern=r'^files/[0-9]{4}\.pdf$')
    size_bytes:int=Field(ge=5,le=MAX_TOTAL)
    sha256:str=Field(pattern=r'^[0-9a-f]{64}$')


class Manifest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    format:str
    version:int
    files:list[ManifestFile]=Field(max_length=MAX_FILES)


class PaperMapping(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    source_paper_id:int=Field(ge=1)
    target_paper_id:int=Field(ge=1)


def unique_keys(pairs):
    out={}
    for key,value in pairs:
        if key in out:raise ValueError('duplicate key')
        out[key]=value
    return out


def mapping_receipt(session_hash:bytes, archive_sha256:str, entries:list[PaperMapping]):
    """Bind an explicit mapping to the authenticated session and exact archive."""
    canonical=json.dumps({'archive_sha256':archive_sha256,'mapping':sorted(
        (entry.model_dump() for entry in entries), key=lambda item:item['source_paper_id'])},
        sort_keys=True,separators=(',',':')).encode('utf-8')
    return hmac.new(session_hash,canonical,hashlib.sha256).hexdigest()


def parse_mapping(mapping, manifest):
    try:
        raw=json.loads(mapping,object_pairs_hook=unique_keys)
        if not isinstance(raw,list) or len(raw)>MAX_FILES:raise ValueError('mapping')
        entries=[PaperMapping.model_validate(item) for item in raw]
    except (ValueError,ValidationError,RecursionError):
        raise HTTPException(422,'文献映射格式无效') from None
    source_ids={item.paper_id for item in manifest.files}
    if len(entries)!=len(source_ids) or {entry.source_paper_id for entry in entries}!=source_ids:
        raise HTTPException(422,'请为附件包中每个原文献填写一次映射')
    return entries


def validate_archive(data:bytes):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries=archive.infolist();names=[entry.filename for entry in entries]
            if len(entries)>MAX_FILES+1 or len(set(names))!=len(names) or names.count('manifest.json')!=1:
                raise ValueError('entries')
            for entry in entries:
                mode=(entry.external_attr>>16)&0o170000
                if entry.is_dir() or mode==stat.S_IFLNK or entry.flag_bits&1 or entry.compress_type!=zipfile.ZIP_STORED:
                    raise ValueError('entry type')
                if entry.filename!='manifest.json' and not re.fullmatch(r'files/[0-9]{4}\.pdf',entry.filename):
                    raise ValueError('path')
            manifest_info=archive.getinfo('manifest.json')
            if manifest_info.file_size>MAX_MANIFEST:raise ValueError('manifest size')
            manifest=Manifest.model_validate(json.loads(archive.read(manifest_info).decode('utf-8'),object_pairs_hook=unique_keys))
            if manifest.format!='zhiyan-pdf-export' or manifest.version!=1:raise ValueError('version')
            paths=[item.path for item in manifest.files]
            if len(set(paths))!=len(paths) or set(names)!={'manifest.json',*paths}:raise ValueError('contents')
            if sum(item.size_bytes for item in manifest.files)>MAX_TOTAL:raise ValueError('total size')
            for item in manifest.files:
                info=archive.getinfo(item.path)
                if info.file_size!=item.size_bytes or info.file_size>get_settings().pdf_max_bytes:raise ValueError('size')
                digest=hashlib.sha256();total=0
                with archive.open(info) as source:
                    while chunk:=source.read(1024*1024):
                        if total==0 and not chunk.startswith(b'%PDF-'):raise ValueError('signature')
                        total+=len(chunk)
                        if total>item.size_bytes:raise ValueError('expanded size')
                        digest.update(chunk)
                if total!=item.size_bytes or digest.hexdigest()!=item.sha256:raise ValueError('hash')
            return manifest
    except (ValueError,ValidationError,UnicodeError,zipfile.BadZipFile,KeyError,OSError,RuntimeError,NotImplementedError,RecursionError):
        raise HTTPException(422,'附件包格式、路径或文件校验失败') from None


@router.post('/pdf-preview')
async def preview_pdf(file:UploadFile=File(...),current=Depends(current_session)):
    try:data=await file.read(MAX_ARCHIVE+1)
    finally:await file.close()
    if len(data)>MAX_ARCHIVE:raise HTTPException(413,'附件包超过大小限制')
    manifest=validate_archive(data)
    return {'sha256':hashlib.sha256(data).hexdigest(),'files':[item.model_dump() for item in manifest.files],
            'total_bytes':sum(item.size_bytes for item in manifest.files),
            'notice':'仅校验附件包；请为来源文献填写目标映射并核对后再导入。'}


@router.post('/pdf-mapping-preview')
async def preview_pdf_mapping(file:UploadFile=File(...), mapping:str=Form(...), expected_sha256:str=Form(...),
                              current=Depends(current_session),db:Session=Depends(get_db)):
    try:data=await file.read(MAX_ARCHIVE+1)
    finally:await file.close()
    if len(data)>MAX_ARCHIVE:raise HTTPException(413,'附件包超过大小限制')
    manifest=validate_archive(data)
    if hashlib.sha256(data).hexdigest()!=expected_sha256:raise HTTPException(409,'附件包已变化，请重新校验')
    entries=parse_mapping(mapping,manifest)
    targets={entry.target_paper_id for entry in entries}
    papers=db.scalars(select(Paper).where(Paper.id.in_(targets),Paper.owner_id==current[1].id,Paper.deleted_at.is_(None))).all()
    if len(papers)!=len(targets):raise HTTPException(404,'部分目标文献不存在或不可访问')
    names={paper.id:paper.title for paper in papers}
    return {'sha256':expected_sha256,'mapping_receipt':mapping_receipt(current[0].token_hash,expected_sha256,entries),'mappings':[{'source_paper_id':entry.source_paper_id,'target_paper_id':entry.target_paper_id,'target_title':names[entry.target_paper_id],
            'file_count':sum(item.paper_id==entry.source_paper_id for item in manifest.files)} for entry in entries],
            'notice':'映射仅供核对，尚未保存或导入附件。'}


@router.post('/pdf-import')
async def import_pdf(file:UploadFile=File(...), mapping:str=Form(...), expected_sha256:str=Form(...),
                     receipt:str=Form(...), request_id:str=Form(...), confirmed:bool=Form(...),
                     current=Depends(current_session), db:Session=Depends(get_db)):
    if not confirmed or not re.fullmatch(r'[0-9a-f]{32}',request_id):
        raise HTTPException(422,'请确认导入并提供有效请求编号')
    try:data=await file.read(MAX_ARCHIVE+1)
    finally:await file.close()
    if len(data)>MAX_ARCHIVE:raise HTTPException(413,'附件包超过大小限制')
    manifest=validate_archive(data)
    digest=hashlib.sha256(data).hexdigest()
    if digest!=expected_sha256:raise HTTPException(409,'附件包已变化，请重新校验')
    entries=parse_mapping(mapping,manifest)
    if not re.fullmatch(r'[0-9a-f]{64}', receipt) or not hmac.compare_digest(mapping_receipt(current[0].token_hash,digest,entries),receipt):
        raise HTTPException(409,'映射确认已失效，请重新核对')
    if not manifest.files:raise HTTPException(422,'附件包中没有 PDF')
    owner=current[1].id
    targets={entry.source_paper_id:entry.target_paper_id for entry in entries}
    expected=[dict(paper_id=targets[item.paper_id],name=item.name,size_bytes=item.size_bytes,sha256=item.sha256) for item in manifest.files]
    def existing():
        batch=db.get(PdfImportBatch,request_id)
        if batch is None:return None
        if batch.owner_id!=owner or batch.archive_sha256!=digest:
            raise HTTPException(409,'请求编号已使用')
        rows=db.scalars(select(PdfImportItem).where(PdfImportItem.batch_id==request_id).order_by(PdfImportItem.id)).all()
        actual=[dict(paper_id=x.paper_id,name=x.original_name,size_bytes=x.size_bytes,sha256=x.sha256) for x in rows]
        if actual!=expected:raise HTTPException(409,'请求编号对应的附件映射已变化')
        if batch.status=='completed':return {'status':'completed','count':len(rows),'notice':'该请求已完成，无需重复导入'}
        raise HTTPException(409,'该请求尚未完成，请先使用恢复操作处理该批次')
    previous=existing()
    if previous is not None:return previous
    try:
        reserve_batch(db,owner,digest,expected,batch_id=request_id)
    except IntegrityError:
        db.rollback()
        previous=existing()
        if previous is not None:return previous
        raise HTTPException(409,'请求编号冲突，请重试') from None
    except ValueError:
        db.rollback();raise HTTPException(422,'目标文献不可访问或附件信息无效') from None
    root=paper_files.STORAGE
    stage=root/'.import-staging'
    try:
        with batch_process_lock(root/'.import-locks',request_id):
            items=db.scalars(select(PdfImportItem).where(PdfImportItem.batch_id==request_id).order_by(PdfImportItem.id)).all()
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                contents={item.id:archive.read(source.path) for item,source in zip(items,manifest.files)}
            stage_batch(db,owner,request_id,contents,stage)
            count=publish_batch(db,owner,request_id,stage,root)
            db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(503,'导入结果待确认，请使用恢复操作检查该请求编号') from None
    try:
        with batch_process_lock(root/'.import-locks',request_id):
            cleanup_staging(db,owner,request_id,stage,completed=True)
            db.commit()
    except (OSError,ValueError):db.rollback()
    return {'status':'completed','count':count,'notice':'附件已导入为新文件；重复文件不会自动合并'}


@router.get('/pdf-import-batches')
def pdf_import_batches(current=Depends(current_session),db:Session=Depends(get_db)):
    batches=db.scalars(select(PdfImportBatch).where(PdfImportBatch.owner_id==current[1].id,
                       PdfImportBatch.status.in_(['reserved','aborted'])).order_by(PdfImportBatch.created_at.desc()).limit(100)).all()
    return {'items':[{'id':item.id,'status':item.status,'created_at':item.created_at} for item in batches]}


@router.post('/pdf-import-batches/{batch_id}/recover')
def recover_pdf_import(batch_id:str,current=Depends(current_session),db:Session=Depends(get_db)):
    if not re.fullmatch(r'[0-9a-f]{32}',batch_id):raise HTTPException(404,'导入批次不存在')
    owner=current[1].id
    batch=db.scalar(select(PdfImportBatch).where(PdfImportBatch.id==batch_id,PdfImportBatch.owner_id==owner))
    if batch is None:raise HTTPException(404,'导入批次不存在')
    if batch.status=='completed':return {'status':'completed','notice':'附件导入已完成，无需重复导入'}
    if batch.status=='cleaned':return {'status':'cleaned','notice':'未完成批次已清理，可重新导入'}
    try:
        with batch_process_lock(paper_files.STORAGE/'.import-locks',batch_id):
            abort_batch(db,batch_id,owner)
            recover_aborted(db,owner,batch_id,paper_files.STORAGE/'.import-staging',paper_files.STORAGE)
    except (OSError,ValueError):
        db.rollback();raise HTTPException(409,'批次暂不能自动清理，请保留现场并联系管理员') from None
    return {'status':'cleaned','notice':'未完成批次已清理，可重新导入'}


def records(owner, db):
    return db.scalars(select(PaperFile).join(Paper, Paper.id == PaperFile.paper_id).where(
        PaperFile.owner_id == owner, Paper.owner_id == owner, Paper.deleted_at.is_(None)
    ).order_by(PaperFile.id).limit(MAX_FILES + 1)).all()


@router.get('/pdf-summary')
def pdf_summary(current=Depends(current_session), db:Session=Depends(get_db)):
    files = records(current[1].id, db)
    return {'count':len(files), 'bytes':sum(f.size_bytes for f in files), 'max_files':MAX_FILES,
            'max_total_bytes':MAX_TOTAL, 'truncated':len(files)>MAX_FILES,
            'notice':'仅统计有效文献的附件；导出时会校验文件。'}


@router.get('/pdf-export')
def export_pdf(current=Depends(current_session), db:Session=Depends(get_db)):
    files = records(current[1].id, db)
    if len(files)>MAX_FILES or sum(f.size_bytes for f in files)>MAX_TOTAL:
        raise HTTPException(413,'附件数量或总大小超过导出上限')
    output=io.BytesIO();manifest=[];total=0
    try:
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED,allowZip64=False) as archive:
            for index,record in enumerate(files,1):
                if record.state!='ready' or record.size_bytes>get_settings().pdf_max_bytes:
                    raise ValueError('unavailable')
                path=path_for(record.storage_key)
                digest=hashlib.sha256();size=0;name=f'files/{index:04d}.pdf'
                with path.open('rb') as source, archive.open(name,'w') as dest:
                    while chunk:=source.read(1024*1024):
                        if size==0 and not chunk.startswith(b'%PDF-'):raise ValueError('signature')
                        size+=len(chunk);total+=len(chunk)
                        if size>get_settings().pdf_max_bytes or total>MAX_TOTAL:raise ValueError('size')
                        digest.update(chunk);dest.write(chunk)
                if size!=record.size_bytes or digest.hexdigest()!=record.sha256:raise ValueError('integrity')
                manifest.append({'paper_id':record.paper_id,'name':record.original_name,'path':name,'size_bytes':size,'sha256':digest.hexdigest()})
            archive.writestr('manifest.json',json.dumps({'format':'zhiyan-pdf-export','version':1,'files':manifest},ensure_ascii=False).encode('utf-8'))
    except (OSError,ValueError,zipfile.BadZipFile):
        raise HTTPException(409,'附件不可用或校验失败，未生成附件包；请检查附件后重试') from None
    return Response(output.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="zhiyan-pdf-export-v1.zip"','Cache-Control':'no-store'})
