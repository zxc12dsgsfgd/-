"""Internal PDF staging primitive. Not an import or recovery endpoint."""
import hashlib
import os
import re
import stat
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PdfImportBatch, PdfImportItem

MARKER = '.zhiyan-pdf-import'


def _unsafe_directory(path: Path) -> bool:
    return path.is_symlink() or os.path.isjunction(path) or not path.is_dir()


def stage_batch(db: Session, owner: int, batch_id: str, contents: dict[int, bytes], root: Path) -> Path:
    """Write verified bytes under a new batch directory while holding its DB lock.

    On I/O failure the caller must roll back and leave the directory for future
    recovery. This function deliberately neither publishes nor removes files.
    The storage root must be controlled by the application, not a user.
    """
    if not re.fullmatch(r'[0-9a-f]{32}', batch_id):
        raise ValueError('invalid batch')
    batch = db.scalar(select(PdfImportBatch).where(
        PdfImportBatch.id == batch_id, PdfImportBatch.owner_id == owner
    ).with_for_update())
    if batch is None or batch.status != 'reserved':
        raise ValueError('batch unavailable')
    items = db.scalars(select(PdfImportItem).where(
        PdfImportItem.batch_id == batch_id
    ).order_by(PdfImportItem.id).with_for_update()).all()
    if not items or set(contents) != {item.id for item in items}:
        raise ValueError('incomplete batch')
    for item in items:
        data = contents[item.id]
        if (not isinstance(data, bytes) or len(data) != item.size_bytes
                or not data.startswith(b'%PDF-')
                or hashlib.sha256(data).hexdigest() != item.sha256
                or not re.fullmatch(r'[0-9a-f]{64}', item.storage_key)):
            raise ValueError('invalid file content')
    root.mkdir(parents=True, exist_ok=True)
    if _unsafe_directory(root):
        raise ValueError('invalid staging root')
    directory = root / batch_id
    directory.mkdir()  # Exclusive: never reuse or overwrite an existing batch directory.
    with (directory / MARKER).open('xb') as marker:
        marker.write(batch_id.encode('ascii'))
        marker.flush()
        os.fsync(marker.fileno())
    for item in items:
        with (directory / (item.storage_key + '.pdf')).open('xb') as output:
            output.write(contents[item.id])
            output.flush()
            os.fsync(output.fileno())
    return directory


def cleanup_staging(db: Session, owner: int, batch_id: str, root: Path, *, completed: bool = False) -> None:
    """Remove registered staged files for an already-aborted batch only.

    The caller owns the transaction and must maintain the lock until this
    function returns. The application must exclusively control root and its
    ancestors. No batch status is changed by this operation.
    """
    if not re.fullmatch(r'[0-9a-f]{32}', batch_id):
        raise ValueError('invalid batch')
    batch = db.scalar(select(PdfImportBatch).where(
        PdfImportBatch.id == batch_id, PdfImportBatch.owner_id == owner
    ).with_for_update())
    if batch is None or batch.status != ('completed' if completed else 'aborted'):
        raise ValueError('batch unavailable')
    items = db.scalars(select(PdfImportItem).where(
        PdfImportItem.batch_id == batch_id
    ).order_by(PdfImportItem.id).with_for_update()).all()
    if not items or any(not re.fullmatch(r'[0-9a-f]{64}', item.storage_key) for item in items):
        raise ValueError('invalid batch items')
    if not root.exists() and not root.is_symlink():
        return
    if _unsafe_directory(root):
        raise ValueError('invalid staging root')
    directory = root / batch_id
    if not directory.exists() and not directory.is_symlink():
        return
    if _unsafe_directory(directory):
        raise ValueError('invalid batch directory')
    expected = {item.storage_key + '.pdf' for item in items}
    entries = {path.name: path for path in directory.iterdir()}
    if MARKER not in entries or set(entries) - expected - {MARKER}:
        raise ValueError('unrecognized staging directory')
    for path in entries.values():
        if not stat.S_ISREG(path.lstat().st_mode) or path.is_symlink():
            raise ValueError('unrecognized staging entry')
    if entries[MARKER].read_bytes() != batch_id.encode('ascii'):
        raise ValueError('invalid staging marker')
    for name in sorted(expected & entries.keys()):
        entries[name].unlink()
    entries[MARKER].unlink()
    directory.rmdir()
