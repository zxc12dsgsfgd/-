"""Internal publication and recovery primitives; no external endpoint."""
import hashlib
import os
import re
import stat
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Paper, PaperFile, PdfImportBatch, PdfImportItem
from app.pdf_import_staging import MARKER, _unsafe_directory, cleanup_staging


def _locked_batch(db: Session, owner: int, batch_id: str, status: str):
    if not isinstance(batch_id, str) or not re.fullmatch(r'[0-9a-f]{32}', batch_id):
        raise ValueError('invalid batch')
    batch = db.scalar(select(PdfImportBatch).where(
        PdfImportBatch.id == batch_id, PdfImportBatch.owner_id == owner
    ).with_for_update())
    if batch is None or batch.status != status:
        raise ValueError('batch unavailable')
    items = db.scalars(select(PdfImportItem).where(
        PdfImportItem.batch_id == batch_id
    ).order_by(PdfImportItem.id).with_for_update()).all()
    if not items or any(not re.fullmatch(r'[0-9a-f]{64}', item.storage_key) for item in items):
        raise ValueError('empty batch')
    return batch, items


def _staged_files(stage_root: Path, batch_id: str, items: list[PdfImportItem]):
    directory = stage_root / batch_id
    if _unsafe_directory(stage_root) or _unsafe_directory(directory):
        raise ValueError('invalid staging directory')
    paths = {item.storage_key + '.pdf': directory / (item.storage_key + '.pdf') for item in items}
    entries = {path.name: path for path in directory.iterdir()}
    if set(entries) != set(paths) | {MARKER}:
        raise ValueError('incomplete staging directory')
    for path in entries.values():
        if not stat.S_ISREG(path.lstat().st_mode) or path.is_symlink():
            raise ValueError('invalid staging file')
    if entries[MARKER].read_bytes() != batch_id.encode('ascii'):
        raise ValueError('invalid staging marker')
    for item in items:
        path = paths[item.storage_key + '.pdf']
        digest = hashlib.sha256()
        with path.open('rb') as source:
            first = source.read(5)
            digest.update(first)
            size = len(first)
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > item.size_bytes:
                    raise ValueError('invalid staged size')
                digest.update(chunk)
        if first != b'%PDF-' or size != item.size_bytes or digest.hexdigest() != item.sha256:
            raise ValueError('invalid staged content')
    return paths


def publish_batch(db: Session, owner: int, batch_id: str, stage_root: Path, final_root: Path) -> int:
    """Link staged files without replacement, then prepare one DB commit.

    Caller must commit or roll back; on error, leave files for explicit recovery.
    Both roots must be application-controlled and on a filesystem with hard links.
    """
    batch, items = _locked_batch(db, owner, batch_id, 'reserved')
    paper_ids = {item.paper_id for item in items}
    papers = db.scalars(select(Paper.id).where(Paper.id.in_(paper_ids), Paper.owner_id == owner,
                                               Paper.deleted_at.is_(None)).order_by(Paper.id).with_for_update()).all()
    if len(papers) != len(paper_ids):
        raise ValueError('inaccessible paper')
    staged = _staged_files(stage_root, batch_id, items)
    final_root.mkdir(parents=True, exist_ok=True)
    if _unsafe_directory(final_root):
        raise ValueError('invalid final directory')
    for item in items:
        source = staged[item.storage_key + '.pdf']
        target = final_root / source.name
        os.link(source, target)  # Fails if the destination already exists.
        db.add(PaperFile(owner_id=owner, paper_id=item.paper_id, storage_key=item.storage_key,
                         original_name=item.original_name, size_bytes=item.size_bytes,
                         sha256=item.sha256, state='ready'))
    batch.status = 'completed'
    db.flush()
    return len(items)


def recover_aborted(db: Session, owner: int, batch_id: str, stage_root: Path, final_root: Path) -> None:
    """Remove only final hard links proven to refer to this batch's staged files."""
    batch, items = _locked_batch(db, owner, batch_id, 'aborted')
    if (final_root.exists() or final_root.is_symlink()) and _unsafe_directory(final_root):
        raise ValueError('invalid final directory')
    directory = stage_root / batch_id
    targets = [final_root / (item.storage_key + '.pdf') for item in items]
    existing = [target for target in targets if target.exists() or target.is_symlink()]
    if existing:
        staged = _staged_files(stage_root, batch_id, items)
        for item, target in zip(items, targets):
            if target.exists() or target.is_symlink():
                if target.is_symlink() or not target.is_file() or not os.path.samefile(target, staged[target.name]):
                    raise ValueError('final file is not owned by batch')
                if db.scalar(select(PaperFile.id).where(PaperFile.storage_key == item.storage_key).limit(1)) is not None:
                    raise ValueError('final file is in use')
        for target in existing:
            target.unlink()
    cleanup_staging(db, owner, batch_id, stage_root)
    batch.status = 'cleaned'
    db.commit()
