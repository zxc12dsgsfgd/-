"""Round-trip a synthetic, isolated MySQL schema through a logical dump."""
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Card, Paper, User

root = Path.cwd()
suffix = secrets.token_hex(6)
source = 'zhiyan_test_backup_' + suffix
target = 'zhiyan_test_restore_' + suffix
base = make_url(get_settings().database_url)
user = base.username.replace("'", "''")
created, granted, engines = [], [], []
docker = ['docker', 'compose', 'exec', '-T', 'mysql', 'sh', '-c']


def run(command, data=None):
    result = subprocess.run(docker + [command], input=data, capture_output=True)
    if result.returncode:
        raise RuntimeError('MySQL operation failed: ' + result.stderr.decode('utf-8', 'replace')[-1000:])
    return result.stdout


def mysql(sql, database=''):
    return run('MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root --default-character-set=utf8mb4 ' + database,
               sql.encode('utf-8'))


try:
    for name in (source, target):
        mysql(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;')
        created.append(name)
        mysql(f"GRANT ALL PRIVILEGES ON `{name}`.* TO '{user}'@'%';")
        granted.append(name)
    env = os.environ.copy()
    env['DATABASE_URL'] = base.set(database=source).render_as_string(hide_password=False)
    env['PYTHONPATH'] = str(root / 'backend')
    migration = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env=env, capture_output=True)
    if migration.returncode:
        raise RuntimeError('Migration failed: ' + migration.stderr.decode('utf-8', 'replace')[-1500:])
    src = create_engine(base.set(database=source)); engines.append(src)
    dst = create_engine(base.set(database=target)); engines.append(dst)
    with Session(src) as db:
        owner = User(email='backup-fixture@example.org', email_norm='backup-fixture@example.org', password_hash='synthetic', display_name='测试用户')
        db.add(owner); db.flush()
        paper = Paper(owner_id=owner.id, title='合成文献 α', authors=['测试作者'], status='unread', doi='10.1234/synthetic')
        db.add(paper); db.flush()
        db.add(Card(owner_id=owner.id, paper_id=paper.id, title='恢复卡片', type='note', content='备份内容 & evidence', version=1))
        db.commit()
    # Keep the dump in the workspace and remove it even when verification fails.
    with tempfile.TemporaryDirectory(prefix='mysql-backup-test-', dir=root) as temporary:
        dump = Path(temporary) / 'synthetic.sql'
        dump.write_bytes(run('MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -u root --default-character-set=utf8mb4 --single-transaction --set-gtid-purged=OFF ' + source))
        assert dump.stat().st_size > 0
        mysql(dump.read_text(encoding='utf-8'), target)
        with src.connect() as a, dst.connect() as b:
            src_tables, dst_tables = set(inspect(a).get_table_names()), set(inspect(b).get_table_names())
            assert src_tables == dst_tables and len(dst_tables) == 39
            assert a.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == b.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == '0026_pdf_import'
            query = text('SELECT u.display_name, p.title, p.authors, p.doi, c.title, c.content FROM users u JOIN papers p ON p.owner_id=u.id JOIN cards c ON c.paper_id=p.id AND c.owner_id=u.id')
            assert a.execute(query).all() == b.execute(query).all()
            row = b.execute(query).one()
            assert row.display_name == '测试用户' and row.content == '备份内容 & evidence'
            assert any(fk['constrained_columns'] == ['paper_id'] and fk['referred_table'] == 'papers' for fk in inspect(b).get_foreign_keys('cards'))
            assert any('email_norm' in u['column_names'] for u in inspect(b).get_unique_constraints('users'))
        try:
            with dst.begin() as conn:
                conn.execute(text("INSERT INTO users (email,email_norm,password_hash,display_name) VALUES ('other@example.org','backup-fixture@example.org','x','x')"))
        except IntegrityError:
            pass
        else:
            raise AssertionError('Restored unique constraint did not reject duplicate')
        print('PASS: dump restored; 39 tables, revision, linked Unicode/JSON data and constraints verified')
finally:
    for engine in engines:
        engine.dispose()
    for name in reversed(granted):
        mysql(f"REVOKE ALL PRIVILEGES ON `{name}`.* FROM '{user}'@'%';")
    for name in reversed(created):
        mysql(f'DROP DATABASE `{name}`;')
    if created:
        quoted = ','.join("'" + name + "'" for name in created)
        remaining = mysql(f'SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME IN ({quoted});')
        assert not remaining.strip(), 'Temporary schema remains'
        grants = mysql(f"SHOW GRANTS FOR '{user}'@'%';").decode('utf-8', 'replace')
        assert all(name not in grants for name in granted), 'Temporary grant remains'
        print('PASS: temporary schemas and grants removed; temporary dump deleted')
