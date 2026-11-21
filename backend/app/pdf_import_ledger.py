"""Internal reservation ledger; no user-facing import is enabled yet."""
import re
import secrets
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Paper, PaperFile, PdfImportBatch, PdfImportItem
from app.paper_files import path_for


def reserve_batch(db:Session, owner:int, archive_sha256:str, entries:list[dict], *, batch_id: str | None = None):
    if not re.fullmatch(r'[0-9a-f]{64}',archive_sha256) or not 1<=len(entries)<=100:
        raise ValueError('invalid batch')
    if batch_id is not None and not re.fullmatch(r'[0-9a-f]{32}', batch_id):
        raise ValueError('invalid batch id')
    total = 0
    for entry in entries:
        name = entry.get('name')
        size = entry.get('size_bytes')
        digest = entry.get('sha256')
        paper_id = entry.get('paper_id')
        if (type(paper_id) is not int or paper_id < 1 or not isinstance(name, str)
                or not 1 <= len(name) <= 255 or not name.isprintable()
                or type(size) is not int or not 5 <= size <= 50 * 1024 * 1024
                or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)):
            raise ValueError('invalid file')
        total += size
    if total > 50 * 1024 * 1024:
        raise ValueError('batch too large')
    paper_ids={entry['paper_id'] for entry in entries}
    papers=db.scalars(select(Paper.id).where(Paper.id.in_(paper_ids),Paper.owner_id==owner,Paper.deleted_at.is_(None)).order_by(Paper.id).with_for_update()).all()
    if len(papers)!=len(paper_ids):raise ValueError('inaccessible paper')
    batch=PdfImportBatch(id=batch_id or secrets.token_hex(16),owner_id=owner,archive_sha256=archive_sha256,status='reserved')
    db.add(batch)
    items=[]
    for entry in entries:
        item=PdfImportItem(batch_id=batch.id,paper_id=entry['paper_id'],storage_key=secrets.token_hex(32),original_name=entry['name'],size_bytes=entry['size_bytes'],sha256=entry['sha256'])
        db.add(item);items.append(item)
    db.commit()
    return batch.id


def abort_batch(db: Session, batch_id: str, owner: int) -> None:
    """Commit an owner-scoped transition while holding the batch row lock.

    All writers must hold the same lock until their writes stop. This internal
    transition does not itself clean files or resolve uncertain commits.
    """
    if not isinstance(batch_id, str) or not re.fullmatch(r'[0-9a-f]{32}', batch_id):
        raise ValueError('invalid batch')
    batch = db.scalar(select(PdfImportBatch).where(
        PdfImportBatch.id == batch_id, PdfImportBatch.owner_id == owner
    ).with_for_update())
    if batch is None:
        raise ValueError('batch not found')
    if batch.status == 'aborted':
        db.commit()
        return
    if batch.status != 'reserved':
        raise ValueError('batch cannot be aborted')
    batch.status = 'aborted'
    db.commit()


def cleanup_aborted(db:Session, batch_id:str, owner:int):
    batch=db.scalar(select(PdfImportBatch).where(PdfImportBatch.id==batch_id,PdfImportBatch.owner_id==owner).with_for_update())
    if batch is None:raise ValueError('batch not found')
    if batch.status!='aborted':raise ValueError('batch is not aborted')
    items=db.scalars(select(PdfImportItem).where(PdfImportItem.batch_id==batch.id).order_by(PdfImportItem.id).with_for_update()).all()
    for item in items:
        if db.scalar(select(PaperFile.id).where(PaperFile.storage_key==item.storage_key).limit(1)) is not None:
            raise ValueError('reserved file is in use')
    for item in items:
        path_for(item.storage_key).unlink(missing_ok=True)
    batch.status='cleaned';db.commit()
