"""Exercise staging and abort serialization using an isolated MySQL schema."""
import hashlib
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Paper, PdfImportBatch, PdfImportItem, User
from app.pdf_import_ledger import abort_batch, reserve_batch
from app.pdf_import_staging import cleanup_staging, stage_batch

root = Path.cwd()
schema = 'zhiyan_test_pdf_lock_' + secrets.token_hex(6)
base = make_url(get_settings().database_url)
user = base.username.replace("'", "''")
created = granted = False
engine = writer = worker = None
errors = []
done = threading.Event()


def mysql(sql):
    result = subprocess.run(
        ['docker', 'compose', 'exec', '-T', 'mysql', 'sh', '-c',
         'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root -N'],
        input=sql, text=True, capture_output=True,
    )
    if result.returncode:
        raise RuntimeError('MySQL administrative operation failed')
    return result.stdout.strip()


try:
    mysql(f'CREATE DATABASE `{schema}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;')
    created = True
    mysql(f"GRANT ALL PRIVILEGES ON `{schema}`.* TO '{user}'@'%';")
    granted = True
    url = base.set(database=schema)
    env = os.environ.copy()
    env['DATABASE_URL'] = url.render_as_string(hide_password=False)
    env['PYTHONPATH'] = str(root / 'backend')
    result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env=env, capture_output=True)
    if result.returncode:
        raise RuntimeError('isolated migration failed')
    engine = create_engine(url)
    data = b'%PDF-synthetic'
    with Session(engine) as db:
        account = User(email='lock@example.org', email_norm='lock@example.org', password_hash='fixture', display_name='fixture')
        db.add(account); db.flush()
        paper = Paper(owner_id=account.id, title='fixture', authors=[], status='unread')
        db.add(paper); db.flush()
        owner, paper_id = account.id, paper.id
        db.commit()
        batch_id = reserve_batch(db, owner, 'a' * 64, [dict(
            paper_id=paper_id, name='fixture.pdf', size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())])
        item_id = db.scalar(select(PdfImportItem.id).where(PdfImportItem.batch_id == batch_id))
    with tempfile.TemporaryDirectory(prefix='pdf-lock-', dir=root) as temp:
        staging_root = Path(temp) / 'stage'
        writer = Session(engine)
        stage_batch(writer, owner, batch_id, {item_id: data}, staging_root)

        def abort_worker():
            try:
                with Session(engine) as db:
                    db.execute(text('SET SESSION innodb_lock_wait_timeout=15'))
                    abort_batch(db, batch_id, owner)
            except Exception as exc:
                errors.append(exc)
            finally:
                done.set()

        worker = threading.Thread(target=abort_worker)
        worker.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not done.is_set():
            query = ("SELECT COUNT(*) FROM performance_schema.data_lock_waits w "
                     "JOIN performance_schema.data_locks l "
                     "ON l.ENGINE_LOCK_ID=w.REQUESTING_ENGINE_LOCK_ID "
                     f"WHERE l.OBJECT_SCHEMA='{schema}' AND l.OBJECT_NAME='pdf_import_batches';")
            if int(mysql(query) or '0'):
                break
            time.sleep(.2)
        else:
            raise RuntimeError('could not observe abort waiting on a database lock')
        if done.is_set():
            raise RuntimeError('abort finished while writer still held lock')
        writer.commit(); writer.close(); writer = None
        if not done.wait(15) or errors:
            raise RuntimeError('abort did not complete after writer released lock')
        worker.join(); worker = None
        with Session(engine) as db:
            assert db.get(PdfImportBatch, batch_id).status == 'aborted'
            cleanup_staging(db, owner, batch_id, staging_root)
            assert not (staging_root / batch_id).exists()
            db.rollback()
        print('PASS: MySQL abort waited for staging batch lock, then aborted and cleaned staged fixture')
finally:
    if writer:
        writer.rollback(); writer.close()
    if worker:
        worker.join(timeout=20)
    if engine:
        engine.dispose()
    if granted:
        mysql(f"REVOKE ALL PRIVILEGES ON `{schema}`.* FROM '{user}'@'%';")
    if created:
        mysql(f'DROP DATABASE `{schema}`;')
    if created:
        print('Temporary schema and grant removed')
