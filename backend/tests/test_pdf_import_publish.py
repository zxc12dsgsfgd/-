import hashlib
import pytest
from sqlalchemy import select
from app.auth import get_db
from app.main import app
from app.models import PaperFile, PdfImportBatch, PdfImportItem
from app.pdf_import_ledger import abort_batch, reserve_batch
from app.pdf_import_publish import publish_batch, recover_aborted
from app.pdf_import_staging import cleanup_staging, stage_batch
from test_papers import clients


def test_publish_commit_and_completed_staging_cleanup(clients, tmp_path):
    a,_=clients; h={'X-Requested-With':'zhiyan'}; data=b'%PDF-content'
    paper=a.post('/api/v1/papers',json={'title':'fixture'},headers=h).json()['id']
    owner=a.get('/api/v1/auth/me').json()['id']
    gen=app.dependency_overrides[get_db]();db=next(gen)
    try:
        batch=reserve_batch(db,owner,'a'*64,[dict(paper_id=paper,name='x.pdf',size_bytes=len(data),sha256=hashlib.sha256(data).hexdigest())])
        item=db.scalar(select(PdfImportItem).where(PdfImportItem.batch_id==batch))
        stage, final=tmp_path/'stage',tmp_path/'final'
        stage_batch(db,owner,batch,{item.id:data},stage)
        assert publish_batch(db,owner,batch,stage,final)==1
        db.commit()
        assert db.get(PdfImportBatch,batch).status=='completed'
        assert db.scalar(select(PaperFile).where(PaperFile.storage_key==item.storage_key)).paper_id==paper
        cleanup_staging(db,owner,batch,stage,completed=True)
        assert (final/(item.storage_key+'.pdf')).read_bytes()==data
        assert not (stage/batch).exists()
    finally:db.rollback();gen.close()


def test_publish_collision_never_deletes_unrelated_file(clients, tmp_path):
    a,_=clients;h={'X-Requested-With':'zhiyan'};data=b'%PDF-content'
    paper=a.post('/api/v1/papers',json={'title':'fixture'},headers=h).json()['id']
    owner=a.get('/api/v1/auth/me').json()['id'];gen=app.dependency_overrides[get_db]();db=next(gen)
    try:
        entry=dict(paper_id=paper,name='x.pdf',size_bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        batch=reserve_batch(db,owner,'a'*64,[entry]);item=db.scalar(select(PdfImportItem).where(PdfImportItem.batch_id==batch))
        stage,final=tmp_path/'stage',tmp_path/'final';stage_batch(db,owner,batch,{item.id:data},stage)
        final.mkdir();target=final/(item.storage_key+'.pdf');target.write_bytes(b'unrelated')
        with pytest.raises(FileExistsError):publish_batch(db,owner,batch,stage,final)
        db.rollback();abort_batch(db,batch,owner)
        with pytest.raises(ValueError):recover_aborted(db,owner,batch,stage,final)
        db.rollback();assert target.read_bytes()==b'unrelated'
        assert db.get(PdfImportBatch,batch).status=='aborted'
    finally:db.rollback();gen.close()


def test_rolled_back_publish_recovers_only_its_hard_links(clients,tmp_path):
    a,_=clients;h={'X-Requested-With':'zhiyan'};data=b'%PDF-content'
    paper=a.post('/api/v1/papers',json={'title':'fixture'},headers=h).json()['id']
    owner=a.get('/api/v1/auth/me').json()['id'];gen=app.dependency_overrides[get_db]();db=next(gen)
    try:
        entry=dict(paper_id=paper,name='x.pdf',size_bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        batch=reserve_batch(db,owner,'a'*64,[entry]);item=db.scalar(select(PdfImportItem).where(PdfImportItem.batch_id==batch))
        stage,final=tmp_path/'stage',tmp_path/'final';stage_batch(db,owner,batch,{item.id:data},stage)
        publish_batch(db,owner,batch,stage,final);db.rollback()
        target=final/(item.storage_key+'.pdf');assert target.exists()
        assert db.scalars(select(PaperFile)).all()==[]
        abort_batch(db,batch,owner);recover_aborted(db,owner,batch,stage,final)
        assert not target.exists() and not (stage/batch).exists()
        assert db.get(PdfImportBatch,batch).status=='cleaned'
    finally:db.rollback();gen.close()
