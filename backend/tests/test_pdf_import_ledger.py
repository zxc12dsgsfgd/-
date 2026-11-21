import hashlib
import pytest
from sqlalchemy import select
from app.auth import get_db
from app.main import app
from app.models import PdfImportBatch, PdfImportItem, PaperFile
from app.pdf_import_ledger import abort_batch, cleanup_aborted, reserve_batch
from test_papers import clients


def test_reservation_and_cleanup_are_owner_scoped(clients,tmp_path,monkeypatch):
    import app.paper_files as files
    monkeypatch.setattr(files,'STORAGE',tmp_path)
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    paper=a.post('/api/v1/papers',json={'title':'来源'},headers=h).json()['id']
    owner=a.get('/api/v1/auth/me').json()['id'];other=b.get('/api/v1/auth/me').json()['id']
    gen=app.dependency_overrides[get_db]();db=next(gen)
    try:
        entry={'paper_id':paper,'name':'x.pdf','size_bytes':6,'sha256':hashlib.sha256(b'%PDF-x').hexdigest()}
        with pytest.raises(ValueError):reserve_batch(db,other,'a'*64,[entry])
        db.rollback()
        batch_id=reserve_batch(db,owner,'a'*64,[entry])
        item=db.scalar(select(PdfImportItem).where(PdfImportItem.batch_id==batch_id))
        target=files.path_for(item.storage_key);target.write_bytes(b'%PDF-x')
        unrelated=tmp_path/'unrelated.pdf';unrelated.write_bytes(b'keep')
        with pytest.raises(ValueError):cleanup_aborted(db,batch_id,owner)
        db.rollback()
        batch=db.get(PdfImportBatch,batch_id);batch.status='aborted';db.commit()
        with pytest.raises(ValueError):cleanup_aborted(db,batch_id,other)
        db.rollback();cleanup_aborted(db,batch_id,owner)
        assert not target.exists() and unrelated.read_bytes()==b'keep'
        assert db.get(PdfImportBatch,batch_id).status=='cleaned'
    finally:gen.close()


def test_cleanup_failure_retains_aborted_ledger(clients,tmp_path,monkeypatch):
    import app.paper_files as files
    a,_=clients;h={'X-Requested-With':'zhiyan'};monkeypatch.setattr(files,'STORAGE',tmp_path)
    paper=a.post('/api/v1/papers',json={'title':'来源'},headers=h).json()['id'];owner=a.get('/api/v1/auth/me').json()['id']
    gen=app.dependency_overrides[get_db]();db=next(gen)
    try:
        batch_id=reserve_batch(db,owner,'b'*64,[{'paper_id':paper,'name':'x.pdf','size_bytes':6,'sha256':'c'*64}])
        item=db.scalar(select(PdfImportItem).where(PdfImportItem.batch_id==batch_id));files.path_for(item.storage_key).write_bytes(b'%PDF-x')
        batch=db.get(PdfImportBatch,batch_id);batch.status='aborted';db.commit()
        original=files.Path.unlink
        def fail(*args,**kwargs):raise OSError('synthetic')
        monkeypatch.setattr(files.Path,'unlink',fail)
        with pytest.raises(OSError):cleanup_aborted(db,batch_id,owner)
        db.rollback();assert db.get(PdfImportBatch,batch_id).status=='aborted'
        monkeypatch.setattr(files.Path,'unlink',original);cleanup_aborted(db,batch_id,owner)
        assert db.get(PdfImportBatch,batch_id).status=='cleaned'
    finally:gen.close()


def test_invalid_entry_does_not_add_partial_batch(clients):
    a,_=clients;h={'X-Requested-With':'zhiyan'}
    paper=a.post('/api/v1/papers',json={'title':'来源'},headers=h).json()['id']
    owner=a.get('/api/v1/auth/me').json()['id']
    gen=app.dependency_overrides[get_db]();db=next(gen)
    try:
        valid={'paper_id':paper,'name':'x.pdf','size_bytes':6,'sha256':'c'*64}
        with pytest.raises(ValueError):
            reserve_batch(db,owner,'b'*64,[valid,{**valid,'sha256':'bad'}])
        db.commit()
        assert db.scalars(select(PdfImportBatch)).all()==[]
        assert db.scalars(select(PdfImportItem)).all()==[]
        with pytest.raises(ValueError):
            reserve_batch(db,owner,'b'*64,[{**valid,'size_bytes':30*1024*1024}]*2)
    finally:gen.close()


def test_partial_cleanup_can_be_retried(clients,tmp_path,monkeypatch):
    import app.paper_files as files
    a,_=clients;h={'X-Requested-With':'zhiyan'};monkeypatch.setattr(files,'STORAGE',tmp_path)
    paper=a.post('/api/v1/papers',json={'title':'来源'},headers=h).json()['id']
    owner=a.get('/api/v1/auth/me').json()['id']
    gen=app.dependency_overrides[get_db]();db=next(gen)
    try:
        entry={'paper_id':paper,'name':'x.pdf','size_bytes':6,'sha256':'c'*64}
        batch_id=reserve_batch(db,owner,'b'*64,[entry,entry])
        items=db.scalars(select(PdfImportItem).where(PdfImportItem.batch_id==batch_id).order_by(PdfImportItem.id)).all()
        paths=[files.path_for(item.storage_key) for item in items]
        for path in paths:path.write_bytes(b'%PDF-x')
        db.get(PdfImportBatch,batch_id).status='aborted';db.commit()
        original=files.Path.unlink
        def fail_second(path,*args,**kwargs):
            if path==paths[1]:raise OSError('synthetic')
            return original(path,*args,**kwargs)
        monkeypatch.setattr(files.Path,'unlink',fail_second)
        with pytest.raises(OSError):cleanup_aborted(db,batch_id,owner)
        db.rollback()
        assert not paths[0].exists() and paths[1].exists()
        assert db.get(PdfImportBatch,batch_id).status=='aborted'
        monkeypatch.setattr(files.Path,'unlink',original)
        cleanup_aborted(db,batch_id,owner)
        assert not any(path.exists() for path in paths)
        assert db.get(PdfImportBatch,batch_id).status=='cleaned'
    finally:gen.close()


def test_abort_batch_is_owner_scoped_and_respects_state(clients):
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    paper=a.post('/api/v1/papers',json={'title':'来源'},headers=h).json()['id']
    owner=a.get('/api/v1/auth/me').json()['id'];other=b.get('/api/v1/auth/me').json()['id']
    gen=app.dependency_overrides[get_db]();db=next(gen)
    try:
        entry={'paper_id':paper,'name':'x.pdf','size_bytes':6,'sha256':'c'*64}
        batch_id=reserve_batch(db,owner,'b'*64,[entry])
        with pytest.raises(ValueError):abort_batch(db,batch_id,other)
        db.rollback()
        assert db.get(PdfImportBatch,batch_id).status=='reserved'
        abort_batch(db,batch_id,owner)
        abort_batch(db,batch_id,owner)
        assert db.get(PdfImportBatch,batch_id).status=='aborted'
        db.get(PdfImportBatch,batch_id).status='completed';db.commit()
        with pytest.raises(ValueError):abort_batch(db,batch_id,owner)
        db.rollback()
        assert db.get(PdfImportBatch,batch_id).status=='completed'
    finally:gen.close()
