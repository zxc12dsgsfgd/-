import hashlib
import re
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_session, get_db
from app.config import get_settings
from app.models import PaperFile
from app.papers import owned

router = APIRouter(prefix='/api/v1/papers', tags=['paper-files'])
STORAGE = Path(__file__).resolve().parents[2] / 'data' / 'pdfs'


def path_for(key: str) -> Path:
    if not re.fullmatch(r'[0-9a-f]{64}', key):
        raise ValueError('invalid storage key')
    return STORAGE / f'{key}.pdf'


def file_owned(paper_id, file_id, owner_id, db):
    owned(paper_id, owner_id, db)
    record = db.scalar(select(PaperFile).where(PaperFile.id == file_id, PaperFile.paper_id == paper_id, PaperFile.owner_id == owner_id))
    if not record:
        raise HTTPException(404, '文件不存在')
    return record


@router.get('/{paper_id}/files')
def list_files(paper_id: int, current=Depends(current_session), db: Session = Depends(get_db)):
    owned(paper_id, current[1].id, db)
    records = db.scalars(select(PaperFile).where(PaperFile.paper_id == paper_id, PaperFile.owner_id == current[1].id).order_by(PaperFile.id)).all()
    return [{'id': x.id, 'name': x.original_name, 'size_bytes': x.size_bytes, 'state': x.state} for x in records]


@router.post('/{paper_id}/files', status_code=201)
async def upload_pdf(paper_id: int, file: UploadFile = File(...), current=Depends(current_session), db: Session = Depends(get_db)):
    owned(paper_id, current[1].id, db)
    name = (file.filename or '').replace('\\', '/').rsplit('/', 1)[-1]
    if not name.lower().endswith('.pdf') or file.content_type != 'application/pdf':
        raise HTTPException(422, '请选择 PDF 文件')
    name = ''.join(c for c in name if c.isprintable())[:255]
    key = secrets.token_hex(32)
    STORAGE.mkdir(parents=True, exist_ok=True)
    temp = STORAGE / f'{key}.tmp'
    target = path_for(key)
    size = 0
    sha = hashlib.sha256()
    committed = False
    try:
        with temp.open('xb') as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > get_settings().pdf_max_bytes:
                    raise HTTPException(413, 'PDF 超过大小限制')
                if size == len(chunk) and not chunk.startswith(b'%PDF-'):
                    raise HTTPException(422, '文件不是有效的 PDF 格式')
                sha.update(chunk); out.write(chunk)
        if size < 5:
            raise HTTPException(422, '文件不是有效的 PDF 格式')
        temp.replace(target)
        record = PaperFile(owner_id=current[1].id, paper_id=paper_id, storage_key=key, original_name=name,
                           size_bytes=size, sha256=sha.hexdigest(), state='ready')
        db.add(record); db.commit(); committed = True; db.refresh(record)
        return {'id': record.id, 'name': record.original_name, 'size_bytes': record.size_bytes, 'state': record.state}
    except Exception:
        db.rollback()
        temp.unlink(missing_ok=True)
        if not committed:
            target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@router.get('/{paper_id}/files/{file_id}')
def get_file(paper_id: int, file_id: int, current=Depends(current_session), db: Session = Depends(get_db)):
    record = file_owned(paper_id, file_id, current[1].id, db)
    path = path_for(record.storage_key)
    if record.state != 'ready' or not path.is_file():
        raise HTTPException(404, '文件不可用')
    return FileResponse(path, media_type='application/pdf', headers={'Content-Disposition':'inline', 'X-Content-Type-Options':'nosniff', 'Cache-Control':'private, no-store', 'Content-Security-Policy':"sandbox; default-src 'none'"})


@router.delete('/{paper_id}/files/{file_id}', status_code=204)
def delete_file(paper_id: int, file_id: int, current=Depends(current_session), db: Session = Depends(get_db)):
    record = file_owned(paper_id, file_id, current[1].id, db)
    record.state = 'deleting'; db.commit()
    try:
        path_for(record.storage_key).unlink(missing_ok=True)
    except OSError:
        raise HTTPException(503, '文件清理失败，请重试') from None
    db.delete(record); db.commit()
    return Response(status_code=204)
