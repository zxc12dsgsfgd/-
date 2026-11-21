"""Kill a staging writer and recover its batch in a disposable MySQL schema."""
import hashlib
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import Paper, PdfImportBatch, PdfImportItem, User
from app.pdf_import_ledger import abort_batch, reserve_batch
from app.pdf_import_staging import cleanup_staging, stage_batch
from app.pdf_import_publish import publish_batch, recover_aborted
from app.pdf_import_process_lock import batch_process_lock
from sqlalchemy import text
import threading


if len(sys.argv) > 1 and sys.argv[1] in ('--writer', '--publisher', '--committed', '--disconnect'):
    engine = create_engine(get_settings().database_url)
    if sys.argv[1] == '--disconnect':
        with batch_process_lock(Path(sys.argv[7]), sys.argv[3]), Session(engine) as db:
            stage_batch(db, int(sys.argv[2]), sys.argv[3], {int(sys.argv[4]): b'%PDF-fixture'}, Path(sys.argv[5]))
            connection_id=db.scalar(text('SELECT CONNECTION_ID()'))
            Path(sys.argv[6]).write_text(str(connection_id))
            time.sleep(120)
        raise SystemExit(0)
    with Session(engine) as db:
        stage_batch(db, int(sys.argv[2]), sys.argv[3], {int(sys.argv[4]): b'%PDF-fixture'}, Path(sys.argv[5]))
        if sys.argv[1] in ('--publisher', '--committed'):
            publish_batch(db, int(sys.argv[2]), sys.argv[3], Path(sys.argv[5]), Path(sys.argv[7]))
        if sys.argv[1] == '--committed':
            db.commit()
        Path(sys.argv[6]).write_text('ready')
        time.sleep(120)
    raise SystemExit(0)

root = Path.cwd()
schema = 'zhiyan_test_pdf_crash_' + secrets.token_hex(6)
base = make_url(get_settings().database_url)
user = base.username.replace("'", "''")
created = granted = False
engine = process = None


def mysql(sql):
    result = subprocess.run(['docker', 'compose', 'exec', '-T', 'mysql', 'sh', '-c',
                             'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root -N'],
                            input=sql, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('MySQL administrative operation failed')
    return result.stdout.strip()


try:
    mysql(f'CREATE DATABASE `{schema}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;'); created = True
    mysql(f"GRANT ALL PRIVILEGES ON `{schema}`.* TO '{user}'@'%';"); granted = True
    url = base.set(database=schema)
    env = os.environ.copy()
    env['DATABASE_URL'] = url.render_as_string(hide_password=False)
    env['PYTHONPATH'] = str(root / 'backend')
    if subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env=env, capture_output=True).returncode:
        raise RuntimeError('isolated migration failed')
    engine = create_engine(url)
    data = b'%PDF-fixture'
    with Session(engine) as db:
        account = User(email='crash@example.org', email_norm='crash@example.org', password_hash='fixture', display_name='fixture')
        db.add(account); db.flush()
        paper = Paper(owner_id=account.id, title='fixture', authors=[], status='unread')
        db.add(paper); db.flush()
        owner, paper_id = account.id, paper.id
        db.commit()
        batch = reserve_batch(db, owner, 'a' * 64, [dict(paper_id=paper_id, name='fixture.pdf',
                              size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())])
        item = db.scalar(select(PdfImportItem.id).where(PdfImportItem.batch_id == batch))
    with tempfile.TemporaryDirectory(prefix='pdf-crash-', dir=root) as temp:
        stage = Path(temp) / 'stage'
        ready = Path(temp) / 'ready'
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        process = subprocess.Popen([sys.executable, __file__, '--writer', str(owner), batch, str(item), str(stage), str(ready)],
                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        deadline = time.monotonic() + 25
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.1)
        if not ready.exists():
            raise RuntimeError('writer did not reach staging checkpoint')
        process.kill(); process.wait(timeout=10); process = None
        with Session(engine) as db:
            assert db.get(PdfImportBatch, batch).status == 'reserved'
            abort_batch(db, batch, owner)
            cleanup_staging(db, owner, batch, stage)
            assert not (stage / batch).exists()
            db.rollback()
        print('PASS: killed real staging process; aborted and cleaned its synthetic batch after lock release')
        with Session(engine) as db:
            batch = reserve_batch(db, owner, 'b' * 64, [dict(paper_id=paper_id, name='fixture.pdf',
                                  size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())])
            item = db.scalar(select(PdfImportItem.id).where(PdfImportItem.batch_id == batch))
            key = db.get(PdfImportItem, item).storage_key
        ready.unlink()
        final = Path(temp) / 'final'
        process = subprocess.Popen([sys.executable, __file__, '--publisher', str(owner), batch, str(item),
                                    str(stage), str(ready), str(final)], env=env, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=flags)
        deadline = time.monotonic() + 25
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.1)
        if not ready.exists():
            raise RuntimeError('publisher did not reach pre-commit checkpoint')
        target = final / (key + '.pdf')
        assert target.exists()
        process.kill(); process.wait(timeout=10); process = None
        with Session(engine) as db:
            assert db.get(PdfImportBatch, batch).status == 'reserved'
            abort_batch(db, batch, owner)
            recover_aborted(db, owner, batch, stage, final)
            assert not target.exists() and not (stage / batch).exists()
        print('PASS: killed real publisher before DB commit; recovered its hard link and staging files')
        with Session(engine) as db:
            batch = reserve_batch(db, owner, 'c' * 64, [dict(paper_id=paper_id, name='fixture.pdf',
                                  size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())])
            item = db.scalar(select(PdfImportItem.id).where(PdfImportItem.batch_id == batch))
            key = db.get(PdfImportItem, item).storage_key
        ready.unlink()
        process = subprocess.Popen([sys.executable, __file__, '--committed', str(owner), batch, str(item),
                                    str(stage), str(ready), str(final)], env=env, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=flags)
        deadline = time.monotonic() + 25
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.1)
        if not ready.exists():
            raise RuntimeError('publisher did not reach committed checkpoint')
        target = final / (key + '.pdf')
        process.kill(); process.wait(timeout=10); process = None
        with Session(engine) as db:
            assert db.get(PdfImportBatch, batch).status == 'completed'
            cleanup_staging(db, owner, batch, stage, completed=True)
            assert target.read_bytes() == data and not (stage / batch).exists()
            db.rollback()
        print('PASS: killed publisher after commit; staging cleanup preserved the published attachment')
        with Session(engine) as db:
            batch = reserve_batch(db, owner, 'd' * 64, [dict(paper_id=paper_id, name='fixture.pdf',
                                  size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())])
            item = db.scalar(select(PdfImportItem.id).where(PdfImportItem.batch_id == batch))
        ready.unlink()
        locks = Path(temp) / 'locks'
        process = subprocess.Popen([sys.executable, __file__, '--disconnect', str(owner), batch, str(item),
                                    str(stage), str(ready), str(locks)], env=env, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=flags)
        deadline = time.monotonic() + 25
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.1)
        if not ready.exists():raise RuntimeError('writer did not reach disconnect checkpoint')
        connection_id=int(ready.read_text())
        mysql(f'KILL CONNECTION {connection_id};')
        completed=threading.Event();errors=[]
        def recover_after_disconnect():
            try:
                with batch_process_lock(locks,batch), Session(engine) as db:
                    abort_batch(db,batch,owner)
                    recover_aborted(db,owner,batch,stage,final)
            except Exception as error:errors.append(error)
            finally:completed.set()
        worker=threading.Thread(target=recover_after_disconnect)
        worker.start()
        if completed.wait(1):raise RuntimeError('recovery bypassed active process lock')
        process.kill();process.wait(timeout=10);process=None
        if not completed.wait(15) or errors:raise RuntimeError('recovery failed after writer exit')
        worker.join()
        with Session(engine) as db:assert db.get(PdfImportBatch,batch).status=='cleaned'
        print('PASS: MySQL connection killed; recovery waited for live writer process lock before cleanup')
finally:
    if process and process.poll() is None:
        process.kill(); process.wait(timeout=10)
    if engine:
        engine.dispose()
    if granted:
        mysql(f"REVOKE ALL PRIVILEGES ON `{schema}`.* FROM '{user}'@'%';")
    if created:
        mysql(f'DROP DATABASE `{schema}`;')
        print('Temporary schema and grant removed')
