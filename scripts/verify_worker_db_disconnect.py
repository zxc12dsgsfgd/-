"""Disconnect an isolated test worker's MySQL session during a transaction."""
import os
import secrets
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Notification, Paper, User, Workflow, WorkflowEvent, WorkflowRun

root = Path.cwd()
name = 'zhiyan_test_disconnect_' + secrets.token_hex(6)
base = make_url(get_settings().database_url)
user = base.username.replace("'", "''")
created = granted = False
engine = process = None


def mysql(sql):
    result = subprocess.run(
        ['docker', 'compose', 'exec', '-T', 'mysql', 'sh', '-c',
         'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root -N -B'],
        input=sql.encode(), capture_output=True, timeout=20,
    )
    if result.returncode:
        raise RuntimeError('Temporary database operation failed')
    return result.stdout.decode().strip()


def counts():
    with Session(engine) as db:
        return tuple(db.scalar(select(func.count()).select_from(model))
                     for model in (WorkflowEvent, WorkflowRun, Notification))


try:
    mysql(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;')
    created = True
    mysql(f"GRANT ALL PRIVILEGES ON `{name}`.* TO '{user}'@'%';")
    granted = True
    env = os.environ.copy()
    env['DATABASE_URL'] = base.set(database=name).render_as_string(hide_password=False)
    env['PYTHONPATH'] = str(root / 'backend')
    result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'],
                            env=env, capture_output=True, timeout=40)
    if result.returncode:
        raise RuntimeError('Migration failed')
    engine = create_engine(base.set(database=name), pool_pre_ping=True)
    with Session(engine) as db:
        account = User(email='disconnect-fixture@example.org', email_norm='disconnect-fixture@example.org',
                       password_hash='synthetic', display_name='fixture')
        db.add(account)
        db.flush()
        db.add(Workflow(owner_id=account.id, name='disconnect', enabled=True, trigger='scheduled_check',
                        filter_value='1', message='synthetic reminder', action_type='notify'))
        db.add(Paper(owner_id=account.id, title='overdue', authors=[], status='unread',
                     created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3)))
        db.commit()
    mysql(f'CREATE TRIGGER `{name}`.`pause_notification` BEFORE INSERT ON `{name}`.`notifications` FOR EACH ROW DO SLEEP(30);')
    process = subprocess.Popen([sys.executable, '-m', 'app.worker'], cwd=root, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Worker exited before transaction was observed')
        ids = mysql('SELECT ID FROM information_schema.PROCESSLIST '
                    f"WHERE DB='{name}' AND (INFO LIKE 'INSERT INTO notifications%' OR INFO LIKE 'DO SLEEP(%');")
        if ids:
            break
        time.sleep(.25)
    else:
        raise RuntimeError('Did not observe isolated worker insertion')
    if len(ids.splitlines()) != 1 or not ids.isdecimal():
        raise RuntimeError('Could not uniquely identify the isolated worker connection')
    mysql(f'KILL CONNECTION {int(ids)};')
    mysql(f'DROP TRIGGER `{name}`.`pause_notification`;')
    if counts() != (0, 0, 0):
        raise RuntimeError('Interrupted transaction was not rolled back')
    deadline = time.monotonic() + 80
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Worker exited after database disconnect')
        if counts() == (1, 1, 1):
            break
        time.sleep(.5)
    else:
        raise RuntimeError(f'Worker did not recover: {counts()}')
    time.sleep(2)
    assert counts() == (1, 1, 1)
    print('PASS: isolated connection interrupted, transaction rolled back, worker recovered once')
finally:
    if process and process.poll() is None:
        process.kill()
        process.wait(timeout=10)
    if engine:
        engine.dispose()
    if granted:
        mysql(f"REVOKE ALL PRIVILEGES ON `{name}`.* FROM '{user}'@'%';")
    if created:
        mysql(f'DROP DATABASE `{name}`;')
        assert not mysql(f"SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='{name}';")
        assert name not in mysql(f"SHOW GRANTS FOR '{user}'@'%';")
        print('Temporary schema, grant and worker cleaned')
