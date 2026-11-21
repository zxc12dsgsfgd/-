import hashlib

import pytest
from sqlalchemy import select

from app.auth import get_db
from app.main import app
from app.models import PaperFile, PdfImportBatch, PdfImportItem
from app.pdf_import_ledger import reserve_batch
from app.pdf_import_staging import MARKER, cleanup_staging, stage_batch
from test_papers import clients


def test_stage_checks_owner_contents_and_refuses_overwrite(clients, tmp_path):
    a, b = clients
    h = {'X-Requested-With': 'zhiyan'}
    paper = a.post('/api/v1/papers', json={'title': '来源'}, headers=h).json()['id']
    owner = a.get('/api/v1/auth/me').json()['id']
    other = b.get('/api/v1/auth/me').json()['id']
    data = b'%PDF-test'
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        batch_id = reserve_batch(db, owner, 'a' * 64, [dict(
            paper_id=paper, name='test.pdf', size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())])
        item = db.scalar(select(PdfImportItem).where(PdfImportItem.batch_id == batch_id))
        root = tmp_path / 'staging'
        with pytest.raises(ValueError):
            stage_batch(db, other, batch_id, {item.id: data}, root)
        db.rollback()
        with pytest.raises(ValueError):
            stage_batch(db, owner, batch_id, {item.id: b'%PDF-fail'}, root)
        db.rollback()
        assert not root.exists()
        directory = stage_batch(db, owner, batch_id, {item.id: data}, root)
        path = directory / (item.storage_key + '.pdf')
        assert path.read_bytes() == data
        assert db.scalars(select(PaperFile)).all() == []
        assert db.get(PdfImportBatch, batch_id).status == 'reserved'
        db.rollback()
        with pytest.raises(FileExistsError):
            stage_batch(db, owner, batch_id, {item.id: data}, root)
        assert path.read_bytes() == data
    finally:
        db.rollback()
        gen.close()


def test_staging_failure_preserves_partial_files(clients, tmp_path, monkeypatch):
    import app.pdf_import_staging as staging
    a, _ = clients
    h = {'X-Requested-With': 'zhiyan'}
    paper = a.post('/api/v1/papers', json={'title': '来源'}, headers=h).json()['id']
    owner = a.get('/api/v1/auth/me').json()['id']
    data = b'%PDF-test'
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        entry = dict(paper_id=paper, name='test.pdf', size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        batch_id = reserve_batch(db, owner, 'a' * 64, [entry, entry])
        items = db.scalars(select(PdfImportItem).where(PdfImportItem.batch_id == batch_id).order_by(PdfImportItem.id)).all()
        original = staging.os.fsync
        calls = 0
        def fail_second(fd):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError('synthetic write failure')
            original(fd)
        monkeypatch.setattr(staging.os, 'fsync', fail_second)
        with pytest.raises(OSError):
            stage_batch(db, owner, batch_id, {item.id: data for item in items}, tmp_path / 'staging')
        db.rollback()
        directory = tmp_path / 'staging' / batch_id
        assert (directory / (items[0].storage_key + '.pdf')).read_bytes() == data
        assert db.get(PdfImportBatch, batch_id).status == 'reserved'
        assert db.scalars(select(PaperFile)).all() == []
        with pytest.raises(FileExistsError):
            stage_batch(db, owner, batch_id, {item.id: data for item in items}, tmp_path / 'staging')
    finally:
        db.rollback()
        gen.close()


def test_cleanup_staging_checks_owner_state_and_unexpected_entries(clients, tmp_path):
    a, b = clients
    h = {'X-Requested-With': 'zhiyan'}
    paper = a.post('/api/v1/papers', json={'title': '来源'}, headers=h).json()['id']
    owner = a.get('/api/v1/auth/me').json()['id']
    other = b.get('/api/v1/auth/me').json()['id']
    data = b'%PDF-test'
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        entry = dict(paper_id=paper, name='test.pdf', size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        batch_id = reserve_batch(db, owner, 'a' * 64, [entry])
        item = db.scalar(select(PdfImportItem).where(PdfImportItem.batch_id == batch_id))
        root = tmp_path / 'staging'
        directory = stage_batch(db, owner, batch_id, {item.id: data}, root)
        db.rollback()
        with pytest.raises(ValueError):
            cleanup_staging(db, owner, batch_id, root)
        db.rollback()
        db.get(PdfImportBatch, batch_id).status = 'aborted'
        db.commit()
        with pytest.raises(ValueError):
            cleanup_staging(db, other, batch_id, root)
        db.rollback()
        extra = directory / 'unrelated.txt'
        extra.write_bytes(b'keep')
        with pytest.raises(ValueError):
            cleanup_staging(db, owner, batch_id, root)
        db.rollback()
        assert extra.read_bytes() == b'keep'
        assert (directory / (item.storage_key + '.pdf')).read_bytes() == data
        extra.unlink()
        marker = directory / MARKER
        marker.write_text('wrong')
        with pytest.raises(ValueError):
            cleanup_staging(db, owner, batch_id, root)
        db.rollback()
        marker.write_text(batch_id)
        cleanup_staging(db, owner, batch_id, root)
        assert not directory.exists()
        assert db.get(PdfImportBatch, batch_id).status == 'aborted'
        cleanup_staging(db, owner, batch_id, root)
    finally:
        db.rollback()
        gen.close()


def test_cleanup_staging_partial_failure_retry(clients, tmp_path, monkeypatch):
    import app.pdf_import_staging as staging
    a, _ = clients
    h = {'X-Requested-With': 'zhiyan'}
    paper = a.post('/api/v1/papers', json={'title': '来源'}, headers=h).json()['id']
    owner = a.get('/api/v1/auth/me').json()['id']
    data = b'%PDF-test'
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        entry = dict(paper_id=paper, name='test.pdf', size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        batch_id = reserve_batch(db, owner, 'a' * 64, [entry, entry])
        items = db.scalars(select(PdfImportItem).where(PdfImportItem.batch_id == batch_id)).all()
        root = tmp_path / 'staging'
        directory = stage_batch(db, owner, batch_id, {item.id: data for item in items}, root)
        db.get(PdfImportBatch, batch_id).status = 'aborted'
        db.commit()
        paths = sorted(directory / (item.storage_key + '.pdf') for item in items)
        original = staging.Path.unlink
        def fail_second(path, *args, **kwargs):
            if path == paths[1]:
                raise OSError('synthetic cleanup failure')
            return original(path, *args, **kwargs)
        monkeypatch.setattr(staging.Path, 'unlink', fail_second)
        with pytest.raises(OSError):
            cleanup_staging(db, owner, batch_id, root)
        db.rollback()
        assert not paths[0].exists() and paths[1].exists() and (directory / MARKER).exists()
        assert db.get(PdfImportBatch, batch_id).status == 'aborted'
        monkeypatch.setattr(staging.Path, 'unlink', original)
        cleanup_staging(db, owner, batch_id, root)
        assert not directory.exists()
    finally:
        db.rollback()
        gen.close()
